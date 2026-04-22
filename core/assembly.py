"""
Assembly Mode — חילוץ מלא של מספר שרטוטים וניתוח קשרים בין מכלולים.

מודול זה נפרד לחלוטין מ-core/extractor.py כדי לא להשפיע על המצב הקיים
של ניתוח שרטוט בודד. הוא משתמש ב-pipeline משלו עם prompts ייעודיים
מתוך core/assembly_prompts.py.

שלבים:
  1. extract_assembly_drawing(pdf_path) — חילוץ מלא של שרטוט בודד (ללא מאסטרים).
  2. analyze_relationships(results) — ניתוח קשרי אבא/בן בין כל השרטוטים שנותחו.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from core.azure_client import get_client, get_deployment, is_reasoning_model
from core.pdf_utils import pdf_to_images, image_file_to_b64
from core.cost_tracker import DrawingCostTracker, calculate_cost
from core.ocr_fallback import is_ocr_available, extract_text_from_pdf, build_enhanced_prompt
from core.assembly_prompts import (
    ASSEMBLY_STAGE_1_PROMPT,
    ASSEMBLY_STAGE_2_PROMPT,
    ASSEMBLY_RELATIONSHIPS_PROMPT_TEMPLATE,
    ASSEMBLY_OVERVIEW_IMAGE_PROMPT,
)
from core.exceptions import PDFError, ImageError
from core.drawing_cache import get_cached_result, save_cached_result

logger = logging.getLogger(__name__)


_OCR_FIXES = {
    r"\b1SO(\d)": r"ISO\1",
    r"\bMIR-": "M1R-",
    r"\bBBO\b": "BB0",
    r"\b1SO11833\b": "ISO11833",
}


def _fix_ocr_text(text: str) -> str:
    if not isinstance(text, str) or not text:
        return text
    out = text
    for pattern, repl in _OCR_FIXES.items():
        out = re.sub(pattern, repl, out)
    return out


def _fix_ocr_in_relationships(analysis: dict) -> None:
    """מתקן שגיאות OCR ידועות בשדות רלוונטיים ל-P/N/DWG/טקסט."""
    for a in analysis.get("assemblies", []) or []:
        if not isinstance(a, dict):
            continue
        a["parent_part_number"] = _fix_ocr_text(a.get("parent_part_number", ""))
        a["parent_drawing_number"] = _fix_ocr_text(a.get("parent_drawing_number", ""))
        for k in a.get("children", []) or []:
            if not isinstance(k, dict):
                continue
            for fld in ("part_number", "drawing_number", "description"):
                if fld in k:
                    k[fld] = _fix_ocr_text(k.get(fld, ""))


def _collect_overview_ids(results: list[dict]) -> set[str]:
    """מזהים אפשריים של שרטוט Overview כדי לסנן אותו מהעץ."""
    ids: set[str] = set()
    for d in results or []:
        if not isinstance(d, dict):
            continue
        role = (d.get("assembly_role") or "").strip().lower()
        if role != "assembly overview image":
            continue
        for raw in (d.get("part_number"), d.get("drawing_number"), d.get("source_filename")):
            val = (raw or "").strip().lower()
            if val:
                ids.add(val)
                ids.add(Path(val).stem)
    return ids


def _is_overview_label(value: str, overview_ids: set[str]) -> bool:
    v = (value or "").strip().lower()
    if not v:
        return False
    if v in overview_ids or Path(v).stem in overview_ids:
        return True
    return "asm_temp_image" in v or "overview image" in v or v.startswith("image")


def _filter_overview_assemblies(analysis: dict, results: list[dict]) -> int:
    """מסיר assemblies שמייצגים תמונת overview ומחזיר כמה הוסרו."""
    asms = analysis.get("assemblies") or []
    if not asms:
        return 0
    overview_ids = _collect_overview_ids(results)
    kept = []
    removed = 0
    for a in asms:
        if not isinstance(a, dict):
            continue
        parent_pn = a.get("parent_part_number") or ""
        parent_dwg = a.get("parent_drawing_number") or ""
        if _is_overview_label(parent_pn, overview_ids) or _is_overview_label(parent_dwg, overview_ids):
            removed += 1
            continue
        kept.append(a)
    analysis["assemblies"] = kept
    return removed


def _validate_product_tree(analysis: dict, results: list[dict]) -> list[str]:
    """ולידציית שלמות בסיסית לעץ מוצר מול BOM של שרטוט ההרכבה."""
    warnings: list[str] = []
    asms = [a for a in (analysis.get("assemblies") or []) if isinstance(a, dict)]

    if len(asms) != 1:
        roots = [a.get("parent_part_number", "?") for a in asms]
        warnings.append(
            f"[CRITICAL][TREE_STRUCTURE] expected 1 root assembly, got {len(asms)}: {roots}"
        )
        return warnings

    root = asms[0]
    root_pn = (root.get("parent_part_number") or "").strip().upper()
    children = [c for c in (root.get("children") or []) if isinstance(c, dict)]
    tree_pns = {
        (c.get("part_number") or "").strip().upper()
        for c in children if (c.get("part_number") or "").strip()
    }

    asm_doc = None
    for d in results or []:
        if not isinstance(d, dict):
            continue
        if (d.get("assembly_role") or "").strip() != "ASSEMBLY":
            continue
        pn = (d.get("part_number") or "").strip().upper()
        if pn == root_pn or (not asm_doc and d.get("bom_items")):
            asm_doc = d
            if pn == root_pn:
                break

    if not asm_doc:
        warnings.append("[HIGH][TREE_BOM_SOURCE] no ASSEMBLY drawing with BOM found for validation")
        return warnings

    bom_items = [it for it in (asm_doc.get("bom_items") or []) if isinstance(it, dict)]
    bom_pns = {
        (it.get("part_number") or "").strip().upper()
        for it in bom_items if (it.get("part_number") or "").strip()
    }

    missing = sorted(bom_pns - tree_pns)
    if missing:
        warnings.append(
            f"[CRITICAL][MISSING_BOM_ITEMS] missing in tree: {missing}"
        )

    bom_qty = {
        (it.get("part_number") or "").strip().upper(): str(it.get("qty") or "").strip()
        for it in bom_items if (it.get("part_number") or "").strip()
    }
    for c in children:
        cpn = (c.get("part_number") or "").strip().upper()
        if not cpn or cpn not in bom_qty:
            continue
        tree_qty = str(c.get("qty") or "").strip()
        if tree_qty and bom_qty[cpn] and tree_qty != bom_qty[cpn]:
            warnings.append(
                f"[CRITICAL][QTY_MISMATCH] {cpn}: tree={tree_qty}, bom={bom_qty[cpn]}"
            )

    for c in children:
        pn = (c.get("part_number") or "").strip().upper()
        dwg = (c.get("drawing_number") or "").strip().upper()
        if pn and dwg and pn != dwg and pn.startswith("BP") and dwg.startswith("BP"):
            warnings.append(
                f"[HIGH][PN_DWG_MISMATCH] child pn={pn} differs from dwg={dwg}"
            )

    return warnings


# ───────────────────────────────────────────────────────────────
# עזרי קריאה למודל (עצמאיים — לא נשענים על הפרטיים של extractor.py)
# ───────────────────────────────────────────────────────────────
def _build_kwargs(max_tokens: int, temperature: float, json_mode: bool) -> dict:
    kwargs: dict = {}
    if is_reasoning_model():
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["max_tokens"] = max_tokens
        kwargs["temperature"] = temperature
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
    return kwargs


def _strip_json_fences(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    return raw


def _call_vision(client, deployment: str, prompt: str, images_b64: list[str]):
    content = [{"type": "text", "text": prompt}]
    for img_b64 in images_b64:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{img_b64}",
                "detail": "high",
            },
        })
    budget = 16000 if is_reasoning_model() else 6000
    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": content}],
        **_build_kwargs(max_tokens=budget, temperature=0.1, json_mode=True),
    )
    raw = _strip_json_fences(response.choices[0].message.content or "")
    if not raw:
        return {}, response.usage
    try:
        return json.loads(raw), response.usage
    except json.JSONDecodeError as exc:
        logger.warning("Assembly JSON parse failed: %s — head: %s", exc, raw[:200])
        return {}, response.usage


def _call_text_json(client, deployment: str, prompt: str):
    """קריאה טקסטואלית שמחזירה JSON (לשלב ניתוח הקשרים)."""
    budget = 8000 if is_reasoning_model() else 3000
    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": prompt}],
        **_build_kwargs(max_tokens=budget, temperature=0.2, json_mode=True),
    )
    raw = _strip_json_fences(response.choices[0].message.content or "")
    if not raw:
        return {}, response.usage
    try:
        return json.loads(raw), response.usage
    except json.JSONDecodeError as exc:
        logger.warning("Relationships JSON parse failed: %s — head: %s", exc, raw[:200])
        return {"summary_he": raw, "assemblies": [], "orphans": [],
                "missing_children": [], "warnings_he": []}, response.usage


# ───────────────────────────────────────────────────────────────
# Helper: חילוץ MATERIAL מ-OCR text (fallback לחילוץ ויז'ואלי שנכשל)
# ───────────────────────────────────────────────────────────────
_MATERIAL_NOISE_PHRASES = (
    "OTHER SIZE",
    "SIMILAR MATERIAL",
    "RAW MATERIAL IDENTIFICATION",
    "SAME MATERIAL",
    "MATERIAL AND THERMAL",
    "MATERIAL ACC",
    "MATERIAL IS OPTIONAL",
)


def _extract_material_from_text(text: str) -> str:
    """חיפוש שדה MATERIAL בטקסט OCR. מחזיר ערך נקי או "" אם לא נמצא ברור.

    מחפש את התבנית "MATERIAL <ערך>" או שדה ייעודי, ומסנן הערות/disclaimers.
    """
    if not text:
        return ""

    # פיצול לשורות
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # נסה לחפש בלוק MATERIAL <ערך בשורה הבאה>
    for i, line in enumerate(lines):
        upper = line.upper()
        # התעלם משורות שהן הערות/disclaimers
        if any(noise in upper for noise in _MATERIAL_NOISE_PHRASES):
            continue
        # שורה שמורכבת מהמילה MATERIAL בלבד (label של title block)
        if upper in ("MATERIAL", "MATERIAL:", "MATL", "MATL:", "MAT'L", "MAT'L:"):
            # נסה לקחת את 1-3 השורות הבאות
            for j in range(i + 1, min(i + 4, len(lines))):
                candidate = lines[j].strip()
                cu = candidate.upper()
                if any(noise in cu for noise in _MATERIAL_NOISE_PHRASES):
                    continue
                # פסיכת תוויות לא רלוונטיות
                if cu in ("MATERIAL", "MATL", "QTY", "DATE", "REV", "SIZE",
                          "SCALE", "SHEET", "TITLE", "DRAWING", "DWG"):
                    continue
                # חייב להכיל לפחות אות אחת ומעל 4 תווים
                if len(candidate) < 4 or not any(c.isalpha() for c in candidate):
                    continue
                # סינון: צריך להראות כמו חומר (אלומיניום/פלדה/וכו')
                if _looks_like_material(candidate):
                    return candidate[:200]
            continue

        # תבנית בשורה אחת: "MATERIAL: <ערך>" או "MATL <ערך>"
        m = re.match(r"^\s*(?:MATERIAL|MATL|MAT'L)\s*[:\-]?\s*(.+)$", line, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            cu = candidate.upper()
            if any(noise in cu for noise in _MATERIAL_NOISE_PHRASES):
                continue
            if _looks_like_material(candidate):
                return candidate[:200]

    return ""


_MATERIAL_KEYWORDS = (
    "ALUMIN", "ALLOY", "STEEL", "STAINLESS", "BRASS", "BRONZE",
    "TITANIUM", "COPPER", "PLATE", "BAR", "ROD", "TUBE", "SHEET",
    "AL ", "SS ", "CRES", "INCONEL", "MONEL", "PLASTIC", "NYLON",
    "DELRIN", "PEEK", "ABS ", "POLYCARBONATE", "POM", "PTFE",
    "6061", "7075", "2024", "5052", "303", "304", "316", "321",
    "17-4", "17-7", "15-5", "C36", "Ti-6", "PEEK",
)


def _looks_like_material(text: str) -> bool:
    """heuristic: האם המחרוזת נראית כמו חומר גלם תקין."""
    if not text:
        return False
    upper = text.upper()
    return any(kw in upper for kw in _MATERIAL_KEYWORDS)


# ───────────────────────────────────────────────────────────────
# 1. חילוץ שרטוט בודד במצב Assembly
# ───────────────────────────────────────────────────────────────
def extract_assembly_drawing(pdf_path: str | Path) -> dict:
    """חילוץ מלא של שרטוט (כולל עיבוד שבבי) — ללא התאמת מאסטרים.

    מחזיר dict עם:
      part_number, revision, drawing_number, customer, material, quantity,
      assembly_role, bom_items,
      machining_processes, coating_processes, painting_processes,
      inspection_processes, final_approval, additional_processes,
      packaging_notes, standards, notes,
      source_filename, _cost_info, _ocr_used.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise PDFError(
            f"File not found: {pdf_path}",
            user_message=f"קובץ ה-PDF לא נמצא: {pdf_path.name}",
            suggestion="ודאי שהקובץ קיים וההעלאה הושלמה.",
            context={"path": str(pdf_path)},
        )

    # ─── בדיקת Cache ───
    cached = get_cached_result(pdf_path, extra="assembly")
    if cached:
        logger.info(f"[Assembly] 🎯 Cache HIT: {pdf_path.name}")
        return cached

    logger.info(f"[Assembly] מעבד שרטוט: {pdf_path.name}")
    images = pdf_to_images(pdf_path, dpi=300)

    client = get_client()
    deployment = get_deployment()
    tracker = DrawingCostTracker(pdf_path.name)

    # OCR מוקדם
    ocr_text = ""
    ocr_used = False
    if is_ocr_available():
        try:
            ocr_text = extract_text_from_pdf(pdf_path)
            ocr_used = bool(ocr_text.strip())
        except Exception as exc:
            logger.warning("[Assembly] OCR נכשל: %s", exc)

    # Stage 1
    s1_prompt = (
        build_enhanced_prompt(ASSEMBLY_STAGE_1_PROMPT, ocr_text)
        if ocr_text else ASSEMBLY_STAGE_1_PROMPT
    )
    stage1, usage1 = _call_vision(client, deployment, s1_prompt, images)
    tracker.add_stage("assembly_stage_1_basic", calculate_cost(usage1, deployment))

    # Stage 2 — תכולה מלאה
    s2_prompt = (
        build_enhanced_prompt(ASSEMBLY_STAGE_2_PROMPT, ocr_text)
        if ocr_text else ASSEMBLY_STAGE_2_PROMPT
    )
    stage2, usage2 = _call_vision(client, deployment, s2_prompt, images)
    tracker.add_stage("assembly_stage_2_full", calculate_cost(usage2, deployment))

    # Fallback ל-part_number כמו ב-extractor הרגיל
    if not (stage1.get("part_number") or "").strip():
        dn = (stage1.get("drawing_number") or "").strip()
        if dn:
            stage1["part_number"] = dn

    # Fallback לחומר — אם המודל החזיר ריק אבל OCR הצליח לקרוא MATERIAL
    if not (stage1.get("material") or "").strip() and ocr_text:
        material_from_text = _extract_material_from_text(ocr_text)
        if material_from_text:
            stage1["material"] = material_from_text
            logger.info(
                f"[Assembly] 🧪 חומר הושלם מ-OCR: {material_from_text[:60]}"
            )

    result = {
        **stage1,
        **stage2,
        "source_filename": pdf_path.name,
        "_cost_info": tracker.summary(),
        "_ocr_used": ocr_used,
    }
    tracker.save_to_log()
    logger.info(
        f"[Assembly] ✅ {pdf_path.name} | עלות: ${tracker.total_cost():.4f}"
    )

    save_cached_result(pdf_path, result, extra="assembly")
    return result


# ───────────────────────────────────────────────────────────────
# 1b. חילוץ תמונת תרשים מכלול (Exploded View / Assembly Overview)
# ───────────────────────────────────────────────────────────────
def extract_assembly_overview_image(image_path: str | Path) -> dict:
    """מנתח תמונת תרשים מכלול (PNG/JPG) ומחזיר אותה כ"שרטוט" במבנה זהה
    ל-extract_assembly_drawing, עם assembly_role="Assembly Overview Image".

    התמונה משמשת כמפת-מבנה לניתוח קשרי אבא/בן — היא מכילה בועיות מספור
    (Find Numbers) שמחברות בין החלקים, גם אם ה-PN המדויק לא רשום בה.
    אין OCR (התמונה לרוב גרפית), אין Stage2 (אין title block ותהליכים).
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise ImageError(
            f"Image not found: {image_path}",
            user_message=f"קובץ התמונה לא נמצא: {image_path.name}",
            suggestion="ודאי שהקובץ קיים וההעלאה הושלמה.",
            context={"path": str(image_path)},
        )

    cached = get_cached_result(image_path, extra="overview")
    if cached:
        logger.info(f"[Assembly] 🎯 Cache HIT: {image_path.name}")
        return cached

    logger.info(f"[Assembly] מעבד תרשים מכלול (תמונה): {image_path.name}")
    images = image_file_to_b64(image_path)

    client = get_client()
    deployment = get_deployment()
    tracker = DrawingCostTracker(image_path.name)

    data, usage = _call_vision(client, deployment, ASSEMBLY_OVERVIEW_IMAGE_PROMPT, images)
    tracker.add_stage("assembly_overview_image", calculate_cost(usage, deployment))

    # נירמול שדות חסרים כדי להישאר תואם למבנה של שרטוט רגיל
    data.setdefault("part_number", "")
    data.setdefault("drawing_number", "")
    data.setdefault("revision", "")
    data.setdefault("customer", "")
    data.setdefault("material", "")
    data.setdefault("quantity", "")
    data["assembly_role"] = "Assembly Overview Image"
    data.setdefault("bom_items", [])
    for k in ("machining_processes", "coating_processes", "painting_processes",
              "inspection_processes", "additional_processes", "standards"):
        data.setdefault(k, [])
    data.setdefault("final_approval", "")
    data.setdefault("packaging_notes", "")
    data.setdefault("notes", "")

    # אם לא הצלחנו לחלץ PN — נשתמש בשם הקובץ כמזהה
    if not (data.get("part_number") or "").strip():
        data["part_number"] = image_path.stem

    data["source_filename"] = image_path.name
    data["_cost_info"] = tracker.summary()
    data["_ocr_used"] = False
    data["_is_overview_image"] = True

    tracker.save_to_log()
    logger.info(
        f"[Assembly] ✅ תרשים מכלול {image_path.name} | "
        f"בועיות={len(data.get('bom_items') or [])} | "
        f"עלות: ${tracker.total_cost():.4f}"
    )

    save_cached_result(image_path, data, extra="overview")
    return data


# ───────────────────────────────────────────────────────────────
# 2. ניתוח קשרי אבא/בן בין שרטוטים שנותחו
# ───────────────────────────────────────────────────────────────
def _summarize_drawing_for_prompt(d: dict, idx: int) -> str:
    """דוחס שרטוט לטקסט קצר בשביל ה-prompt של ניתוח הקשרים."""
    pn = d.get("part_number") or "?"
    dn = d.get("drawing_number") or "?"
    rev = d.get("revision") or "?"
    cust = d.get("customer") or "?"
    mat = d.get("material") or "?"
    role = d.get("assembly_role") or "?"
    qty = d.get("quantity") or ""
    src = d.get("source_filename") or ""

    # תהליכים מרוכזים
    procs = []
    for c in d.get("coating_processes", []) or []:
        if isinstance(c, dict):
            t = c.get("type_he") or c.get("type") or c.get("name") or ""
            s = c.get("standard") or ""
            procs.append(f"{t} ({s})".strip())
    for p in d.get("painting_processes", []) or []:
        if isinstance(p, dict):
            t = p.get("type_he") or p.get("type") or p.get("name") or ""
            s = p.get("standard") or ""
            procs.append(f"{t} ({s})".strip())

    bom_items = d.get("bom_items") or []
    bom_text = ""
    if bom_items:
        lines = []
        for it in bom_items:
            if isinstance(it, dict):
                lines.append(
                    f"      - item {it.get('item_no','?')}: "
                    f"P/N={it.get('part_number','?')} | "
                    f"qty={it.get('qty','?')} | desc={it.get('description','')}"
                )
        bom_text = "\n   BOM:\n" + "\n".join(lines)

    return (
        f"#{idx}  file={src}\n"
        f"   part_number={pn} | drawing_number={dn} | rev={rev} | customer={cust}\n"
        f"   material={mat}\n"
        f"   role={role} | quantity={qty}\n"
        f"   processes={'; '.join(procs) if procs else '—'}"
        f"{bom_text}"
    )


def analyze_relationships(results: list[dict]) -> dict:
    """מריץ AI על כל השרטוטים יחד ומחזיר ניתוח קשרי אבא/בן.

    מחזיר dict:
      {
        "summary_he": str,
        "assemblies": [{parent_part_number, parent_drawing_number, children:[...]}],
        "orphans": [...],
        "missing_children": [...],
        "warnings_he": [...],
        "_cost_info": {...}
      }
    """
    if not results:
        return {
            "summary_he": "לא הועלו שרטוטים.",
            "assemblies": [], "orphans": [],
            "missing_children": [], "warnings_he": [],
            "_cost_info": {},
        }

    drawings_text = "\n\n".join(
        _summarize_drawing_for_prompt(d, i + 1) for i, d in enumerate(results)
    )
    prompt = ASSEMBLY_RELATIONSHIPS_PROMPT_TEMPLATE.format(
        drawings_data=drawings_text
    )

    client = get_client()
    deployment = get_deployment()
    tracker = DrawingCostTracker("__assembly_relationships__")
    analysis, usage = _call_text_json(client, deployment, prompt)
    tracker.add_stage("assembly_relationships", calculate_cost(usage, deployment))

    # ודא מבנה תקין
    analysis.setdefault("summary_he", "")
    analysis.setdefault("assemblies", [])
    analysis.setdefault("orphans", [])
    analysis.setdefault("missing_children", [])
    analysis.setdefault("warnings_he", [])

    _fix_ocr_in_relationships(analysis)
    removed = _filter_overview_assemblies(analysis, results)
    if removed:
        analysis["warnings_he"].append(
            f"[HIGH][IMAGE_FILTERED] {removed} overview image node(s) removed from assemblies tree"
        )

    tree_warnings = _validate_product_tree(analysis, results)
    analysis["warnings_he"].extend(tree_warnings)

    analysis["_cost_info"] = tracker.summary()
    tracker.save_to_log()
    logger.info(
        f"[Assembly] ניתוח קשרים הושלם | עלות: ${tracker.total_cost():.4f}"
    )
    return analysis
