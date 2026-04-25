"""
חילוץ נתונים משרטוט PDF — מודול ראשי של DrawingAI Lite.
עם Cost Tracking + OCR Fallback + Drawing Cache.
"""
import logging
import re
from pathlib import Path

from core.azure_client import get_client, get_deployment
from core.pdf_utils import pdf_to_images
from core.prompts import STAGE_1_PROMPT, STAGE_2_PROMPT, STAGE_3_PROMPT_TEMPLATE
from core.cost_tracker import DrawingCostTracker, calculate_cost
from core.master_matcher import match_all_coatings
from core.validators import run_all_validators, normalize_revision
from core.two_pass import compare_and_merge, should_run_two_pass, compare_identity_fields
from core.ocr_fallback import (
    is_ocr_available,
    extract_text_from_pdf,
    should_use_fallback,
    build_enhanced_prompt,
)
from core.ai_helpers import call_vision as _call_vision
from core.ai_helpers import call_text as _call_text
from core.ai_helpers import safe_call as _safe_call
from core.drawing_cache import get_cached_result, save_cached_result
from core.exceptions import (
    PDFError,
    StageFailedError,
    MasterMatchingError,
)

logger = logging.getLogger(__name__)


_MATERIAL_RE = re.compile(
    r"MATERIAL[:\s]+([A-Z0-9][A-Z0-9 \-./]*?)(?=[.\n]|$)",
    re.IGNORECASE,
)


def _extract_material_from_notes(notes: str) -> str:
    """Fallback — מוצא 'MATERIAL ...' בתוך טקסט ה-NOTES."""
    if not notes:
        return ""
    m = _MATERIAL_RE.search(notes)
    if not m:
        return ""
    return m.group(1).strip(" .,-")


# מילות מפתח לזיהוי שציפוי צריך להיות מזוהה אבל Stage 2 פספס
_COATING_KEYWORDS_RE = re.compile(
    r"\b(CONVERSION COATING|ALODINE|IRIDITE|CHEM FILM|CHROMATE|"
    r"ANODIZE|ANODIZING|ANODIC|"
    r"PASSIVAT|ELECTROLESS|NICKEL PLAT|ZINC PLAT|CADMIUM|CHROME PLAT|"
    r"TIN PLAT|SILVER PLAT|GOLD PLAT|COPPER PLAT|"
    r"BLACK OXIDE|PHOSPHAT|"
    r"MIL-?C-?5541|MIL-?DTL-?5541|MIL-?A-?8625|MIL-?C-?26074|"
    r"ASTM B633|ASTM B733|QQ-?N-?290|QQ-?P-?416|QQ-?Z-?325)\b",
    re.IGNORECASE,
)


def _notes_hint_coating(stage1: dict, stage2: dict) -> bool:
    """האם ב-NOTES של stage1/stage2 מופיעות מילות מפתח של ציפוי?"""
    text = " ".join([
        str(stage1.get("notes") or ""),
        str(stage2.get("notes") or ""),
    ])
    return bool(_COATING_KEYWORDS_RE.search(text))


# מספר פריט לרוב: 5-15 תווים, אותיות+ספרות, אופציונלי מקפים פנימיים
# Whitelist של prefixes מוכרים של לקוחות — מקבלים עדיפות
_KNOWN_PN_PREFIXES = (
    "PWRL", "BBLE", "HLTA", "FTLS", "FTL",  # RAFAEL
    "BG", "BO", "RF",                        # RAFAEL קצרים
    "BP",                                    # B2B / Aerospace
    "IAI",                                   # Israel Aerospace
    "EL",                                    # Elbit
)
# Blacklist של מחרוזות שאסור לקחת (false positives נפוצים)
_PN_BLACKLIST = {"CAGE", "DWG", "DRAW", "DATE", "NOTES", "QTY", "SIZE",
                 "REV", "SHEET", "SCALE", "TOLERANCE", "FINISH"}

# P/N עם prefix של אותיות (1-4) ואחריו ספרות:
# Y80786A (1+ספרות+אות), J35018A (1+ספרות+אות), BN80760B (2+ספרות+אות),
# UAB2040574 (3+ספרות), BBLE1234X (4+ספרות).
# הפחתנו מ-{2,4} ל-{1,4} כדי לתפוס PNs של רפאל/Elbit עם אות יחידה (Y, J, M).
_PN_PATTERN = re.compile(r"\b([A-Z]{1,4}[A-Z0-9]{0,3}\d{2,}[A-Z0-9]*)\b")

# Compound numeric PNs: "30-173803", "915-80-00586-00", "408-2119-00"
# דורש 2+ קבוצות ספרות עם מקף. אחרי חילוץ נסנן בקוד לפי מספר ספרות כולל >= 6
# (כדי לא לתפוס מידות כמו "10-20").
_NUMERIC_PN_PATTERN = re.compile(r"\b\d+(?:-\d+){1,5}\b")

# Pure-numeric PNs בלי מפרידים (041310219 — 9 ספרות רצופות).
# מופיע רק כשה-stem (לפני parens של metadata) הוא רק ספרות.
_PURE_NUMERIC_PN = re.compile(r"^\d{6,15}$")

# הוספה של קבוצות ספרות אחרי alpha candidate ("DD1000506-01-4" → "DD1000506" + "-01-4")
def _extend_with_compound_suffix(candidate: str, stem: str) -> str:
    """אם candidate מופיע ב-stem ואחריו -\\d+(-\\d+)+, מחזיר את הצירוף המלא."""
    pattern = re.escape(candidate) + r"(-\d+(?:-\d+)*)"
    m = re.search(pattern, stem)
    if m:
        return candidate + m.group(1)
    return candidate


def _extract_pn_from_filename(filename: str) -> str:
    """מנסה למצוא מספר פריט בשם הקובץ (זהיר — מסנן blacklist + עדיפות whitelist)."""
    if not filename:
        return ""
    stem = Path(filename).stem.upper()
    # ננקה תחיליות שכיחות
    for prefix in ("B2BDRAW_", "DRAW_", "_"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
    # Elbit: קבצים בפורמט "un<digits>-..." — ה-"UN" הוא prefix URL-legacy,
    # לא חלק מה-P/N. מסירים אותו כדי לא להחזיר מועמד שגוי כמו "UN8554".
    stem = re.sub(r"^UN(?=\d)", "", stem)
    # פיצול לסגמנטים לפי מקף, קו תחתון, סוגריים, # (Elbit), או ! (corrupted)
    segments = re.split(r"[-_()#!\s]+", stem)
    candidates: list[str] = []
    for seg in segments:
        for m in _PN_PATTERN.findall(seg):
            # דרישות:
            # 1. אורך סביר (4-15) — הורדנו מ-5 ל-4 כי PNs קצרים כמו "Y80786A" קיימים
            # 2. גם אות וגם ספרה
            # 3. לא ברשימה השחורה
            if not (4 <= len(m) <= 15):
                continue
            if m.isdigit() or not any(c.isalpha() for c in m):
                continue
            if any(bl in m for bl in _PN_BLACKLIST):
                continue
            candidates.append(m)

    # אם יש candidate alpha — בדוק אם יש לו suffix קומפאונד (DD1000506-01-4)
    if candidates:
        # עדיפות ל-prefix מוכר
        for c in candidates:
            if c.startswith(_KNOWN_PN_PREFIXES):
                return _extend_with_compound_suffix(c, stem)
        # אחרת — הארוך ביותר (לפחות 5 תווים)
        longest = max(candidates, key=len)
        if len(longest) >= 5:
            return _extend_with_compound_suffix(longest, stem)

    # Fallback 1: compound numeric ("30-173803-00", "915-80-00586-00")
    before_paren = re.split(r"[()]", stem, maxsplit=1)[0]
    for m in _NUMERIC_PN_PATTERN.findall(before_paren):
        digit_count = sum(1 for c in m if c.isdigit())
        if digit_count >= 6:
            return m

    # Fallback 2: pure numeric (041310219)
    # רק אם ה-stem-לפני-parens הוא בדיוק ספרות (אחרי ניקוי מפרידים)
    cleaned = re.sub(r"[-_!\s]+", "", before_paren).strip()
    if _PURE_NUMERIC_PN.match(cleaned):
        return cleaned

    return ""


def _reconcile_part_number(stage1: dict, filename: str) -> None:
    """משלים part_number כש-Stage 1 לא הצליח לחלץ.

    כללים (שמרני — לא מחליפים ערך תקף קיים):
    - אם part_number ריק אבל drawing_number קיים → השתמש ב-drawing_number
      (נפוץ ברפאל — אותו ערך מופיע ב-P.N. וב-DRAWING NO.).
    - אחרת, אם שם הקובץ מכיל מועמד סביר — השתמש בו.
    """
    pn = (stage1.get("part_number") or "").strip()
    if pn:
        return  # יש כבר ערך — לא נוגעים

    dn = (stage1.get("drawing_number") or "").strip()
    if dn:
        stage1["part_number"] = dn
        logger.info(f"📝 part_number הושלם מ-drawing_number: {dn}")
        return

    fname_pn = _extract_pn_from_filename(filename)
    if fname_pn:
        stage1["part_number"] = fname_pn
        logger.info(f"📝 part_number הושלם משם הקובץ: {fname_pn}")


_REV_OK_RE = re.compile(r"^[A-Z]{1,2}[0-9]?$|^-$|^[0-9]{1,2}$")


def _identity_fields_look_suspicious(stage1: dict, filename: str) -> bool:
    """האם ה-P/N או ה-Rev שחולצו בחשד לשגיאת OCR?

    Red flags:
    - Rev בפורמט לא שגרתי (מקף בסוף, >2 תווים, תווים לא-אלפאנומריים).
    - P/N חולץ, מועמד סביר קיים בשם הקובץ, והם שונים משמעותית.
    - drawing_number ריק אבל P/N קיים (לפעמים Vision מבלבל בין השדות).
    """
    rev = (stage1.get("revision") or "").strip().upper()
    if rev and not _REV_OK_RE.match(rev):
        return True

    extracted_pn = (stage1.get("part_number") or "").strip().upper()
    fname_pn = _extract_pn_from_filename(filename).upper()
    if extracted_pn and fname_pn and fname_pn not in extracted_pn and extracted_pn not in fname_pn:
        dwg = (stage1.get("drawing_number") or "").strip().upper()
        if not (fname_pn in dwg or dwg in fname_pn):
            return True

    return False


def _proc_to_str(p) -> str:
    """ממיר תהליך (str או dict) למחרוזת אחת לתצוגה / סיכום."""
    if isinstance(p, dict):
        type_he = (p.get("type_he") or "").strip()
        type_en = (p.get("type") or "").strip()
        head = type_he or type_en or (p.get("name") or "").strip()
        thickness = (p.get("thickness") or "").strip()
        std = (p.get("standard") or "").strip()
        rohs = " (RoHS)" if p.get("rohs") is True else ""
        parts = [x for x in [head, thickness, std] if x]
        return " — ".join(parts) + rohs
    return str(p or "").strip()


# OCR confusion pairs — תווים שמודלי Vision ו-OCR נוטים לבלבל ביניהם
_OCR_CONFUSIONS = frozenset({
    frozenset({"0", "O"}),
    frozenset({"1", "I"}), frozenset({"1", "L"}), frozenset({"1", "l"}),
    frozenset({"I", "L"}),
    frozenset({"5", "S"}),
    frozenset({"6", "G"}),
    frozenset({"8", "B"}),
    frozenset({"2", "Z"}),
    frozenset({"3", "E"}),
    frozenset({"4", "A"}),
    frozenset({"M", "H"}),
    frozenset({"N", "H"}),
})


def _is_ocr_similar(s1: str, s2: str, max_edits: int = 2) -> bool:
    """האם s1 ו-s2 דומים תחת שגיאות OCR שכיחות?

    מחזיר True אם:
    - אותו אורך + עד max_edits הבדלים, כולם מסיווגי OCR ידועים (0↔O, L↔I וכו'),
      או
    - אורך שונה בעד max_edits + הקצר הוא subsequence של הארוך
      (insertion/deletion של ספרה/אות בודדת).
    """
    a, b = s1.upper(), s2.upper()
    if a == b:
        return False  # זהים — לא "דומים"
    # Case 1: אותו אורך, סיווגים
    if len(a) == len(b):
        diffs = [(x, y) for x, y in zip(a, b) if x != y]
        if 0 < len(diffs) <= max_edits:
            return all(frozenset({x, y}) in _OCR_CONFUSIONS for x, y in diffs)
        return False
    # Case 2: אורך שונה — subsequence
    if abs(len(a) - len(b)) <= max_edits:
        longer, shorter = (a, b) if len(a) > len(b) else (b, a)
        i = 0
        for c in longer:
            if i < len(shorter) and c == shorter[i]:
                i += 1
        return i == len(shorter)
    return False


def _try_autocorrect_pn(stage1: dict, filename: str, ocr_text: str) -> tuple[str, str] | None:
    """מתקן P/N אוטומטית לפי 3 כללים (בסדר עדיפות):

    כלל 1 — substring prefer-filename:
      אם ה-P/N שחולץ הוא תת־מחרוזת של מועמד שם הקובץ, וה-candidate משמעותי
      יותר (3+ תווים ארוך יותר) — העדף את ה-candidate (למשל: '421604' ⊂
      'BLG421604-003').

    כלל 2 — OCR substitution:
      אם ה-candidate וה-extracted דומים תחת שגיאות OCR ידועות (0↔O, L↔I,
      spare digit), העדף את ה-candidate גם אם ה-OCR טועה באותה צורה
      (למשל BHO6031A→BH06031A, EI0498→EL0498).

    כלל 3 — OCR grounding:
      אם ה-candidate מופיע ב-OCR (≥80% כיסוי) וה-extracted לא (<30%),
      העדף את ה-candidate.

    מחזיר (before, after) אם בוצע תיקון, או None אחרת.
    """
    extracted = (stage1.get("part_number") or "").strip()
    if not extracted:
        return None
    candidate = _extract_pn_from_filename(filename)
    if not candidate:
        return None
    if extracted.upper() == candidate.upper():
        return None

    def _apply_correction() -> tuple[str, str]:
        stage1["part_number"] = candidate
        dwg = (stage1.get("drawing_number") or "").strip()
        if dwg.upper() == extracted.upper():
            stage1["drawing_number"] = candidate
        stage1["_pn_autocorrected_from"] = extracted
        return (extracted, candidate)

    # כלל 1: substring — filename יותר ספציפי (≥2 תווים נוספים)
    # ירדנו מ-3 ל-2 כדי לתפוס "DD1000506-01" → "DD1000506-01-4"
    if extracted.upper() in candidate.upper() and len(candidate) - len(extracted) >= 2:
        return _apply_correction()

    # אם candidate הוא substring של extracted — extracted יותר מלא, לא לתקן
    if candidate.upper() in extracted.upper():
        return None

    # כלל 2: OCR substitution similarity — גם אם OCR טעה באותה צורה
    if _is_ocr_similar(extracted, candidate, max_edits=2):
        return _apply_correction()

    # כלל 3: OCR grounding — הכלל הישן
    if not ocr_text or len(ocr_text) < 50:
        return None
    ocr_upper = ocr_text.upper()
    ocr_tokens = set(re.findall(r"[A-Z0-9]+", ocr_upper))
    if len(ocr_tokens) < 20:
        return None

    def _coverage(s: str) -> float:
        toks = set(re.findall(r"[A-Z0-9]+", s.upper()))
        significant = {t for t in toks if len(t) >= 3}
        if not significant:
            return 0.0
        return sum(1 for t in significant if t in ocr_tokens) / len(significant)

    if _coverage(candidate) >= 0.8 and _coverage(extracted) < 0.3:
        return _apply_correction()
    return None


def _is_meaningful_process(p) -> bool:
    """האם תהליך מכיל מספיק מידע כדי להיות שווה שימור?

    מסנן רשומות "רעש" — dict ריק או עם כל השדות המזהים ריקים.
    """
    if not isinstance(p, dict):
        return bool(str(p or "").strip())
    # לפחות אחד מהשדות המזהים חייב להיות מלא
    for key in ("type", "type_he", "name", "standard"):
        if (p.get(key) or "").strip():
            return True
    return False


def extract_drawing(pdf_path: str | Path, use_ocr_fallback: bool = True) -> dict:
    """
    חילוץ מלא של שרטוט PDF עם cost tracking ו-OCR fallback.

    Args:
        pdf_path: נתיב לקובץ PDF
        use_ocr_fallback: האם להפעיל OCR fallback אם Stage 1 חלש

    Returns:
        dict עם כל השדות + _cost_info עם פירוט עלויות
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
    cached = get_cached_result(pdf_path, extra=f"ocr={use_ocr_fallback}")
    if cached:
        logger.info(f"🎯 Cache HIT: {pdf_path.name} — מדלג על עיבוד AI")
        return cached

    logger.info(f"מעבד שרטוט: {pdf_path.name}")

    images = pdf_to_images(pdf_path, dpi=300)
    logger.info(f"PDF הומר ל-{len(images)} עמודים")

    client = get_client()
    deployment = get_deployment()
    tracker = DrawingCostTracker(pdf_path.name)

    # ─── OCR מוקדם (פעם אחת) — עוזר עם NOTES בעברית RTL וקריאת ספרות ───
    # הערה: OCR רץ תמיד (אם זמין) כי הוא עוזר לקריאת חומר, תקנים וכו'.
    # גם אם Stage 1 מחזיר ערך — ייתכן שהוא שגוי ו-OCR היה מונע את זה.
    ocr_text = ""
    ocr_used = False
    if is_ocr_available():
        try:
            ocr_text = extract_text_from_pdf(pdf_path)
            ocr_used = bool(ocr_text.strip())
        except Exception as exc:
            logger.warning("OCR נכשל: %s", exc)

    # ─── Stage 1 — מידע בסיסי (עם OCR אם זמין) ───
    logger.info("Stage 1: חילוץ מידע בסיסי...")
    stage1_prompt = (
        build_enhanced_prompt(STAGE_1_PROMPT, ocr_text) if ocr_text else STAGE_1_PROMPT
    )
    stage1, usage1 = _safe_call(
        _call_vision, client, deployment, stage1_prompt, images,
        stage="stage_1_basic_info",
    )
    tracker.add_stage("stage_1_basic_info", calculate_cost(usage1, deployment))

    # Retry נוסף רק אם Stage 1 עדיין חלש (2+ שדות קריטיים ריקים)
    if use_ocr_fallback and should_use_fallback(stage1) and ocr_text:
        logger.info("⚠️ Stage 1 חלש גם עם OCR — מנסה שוב...")
        try:
            stage1_retry, usage_retry = _safe_call(
                _call_vision, client, deployment, stage1_prompt, images
            )
            tracker.add_stage(
                "stage_1_ocr_retry", calculate_cost(usage_retry, deployment)
            )
            for key, value in stage1_retry.items():
                if value and not stage1.get(key):
                    stage1[key] = value
        except Exception as exc:
            logger.warning("Stage 1 retry נכשל: %s", exc)

    # ─── Two-pass זיהוי: Rev/P/N חשודים ───
    # מריץ Stage 1 שנית רק אם יש red flag — Rev עם פורמט חריג או P/N שלא
    # תואם למועמד משם הקובץ. מטרה: לתפוס שגיאות OCR של אות יחידה (C↔V, T↔1).
    identity_mismatch_warnings: list[dict] = []
    if _identity_fields_look_suspicious(stage1, pdf_path.name):
        logger.info("🔍 Rev/P/N חשודים — מריץ Stage 1 שנית לאימות זהות...")
        try:
            stage1_pass2, usage_pass2 = _safe_call(
                _call_vision, client, deployment, stage1_prompt, images
            )
            tracker.add_stage(
                "stage_1_identity_verify",
                calculate_cost(usage_pass2, deployment),
            )
            identity_mismatch_warnings = compare_identity_fields(stage1, stage1_pass2)
            if identity_mismatch_warnings:
                logger.warning(
                    "⚠️ Two-pass זיהוי: נמצאו %d אי-התאמות ב-P/N/Rev",
                    len(identity_mismatch_warnings),
                )
        except Exception as exc:
            logger.warning("Stage 1 identity-verify נכשל: %s", exc)

    # ─── Stage 2 — תהליכים ───
    logger.info("Stage 2: חילוץ תהליכים...")
    stage2_prompt = (
        build_enhanced_prompt(STAGE_2_PROMPT, ocr_text) if ocr_text else STAGE_2_PROMPT
    )
    stage2, usage2 = _safe_call(
        _call_vision, client, deployment, stage2_prompt, images,
        stage="stage_2_processes",
    )
    tracker.add_stage("stage_2_processes", calculate_cost(usage2, deployment))

    # ─── Retry חכם לציפוי: אם ציפוי ריק אבל הטקסט מזכיר ציפוי — נסה שוב ───
    coatings_empty = not (stage2.get("coating_processes") or stage2.get("painting_processes"))
    if coatings_empty:
        hint_text = " ".join([
            str(stage1.get("notes") or ""),
            str(stage2.get("notes") or ""),
            ocr_text,
        ])
        if _COATING_KEYWORDS_RE.search(hint_text):
            logger.warning(
                "Stage 2 החזיר ציפוי ריק אך הטקסט מזכיר ציפוי — מבצע retry..."
            )
            retry_prompt = (
                stage2_prompt
                + "\n\n⚠️ שים לב! בשרטוט מופיעות מילות מפתח של ציפוי/תקן "
                "(למשל CONVERSION COATING, MIL-DTL-5541, ANODIZE, "
                "ELECTROLESS NICKEL, ASTM B633 וכו'). חובה לחלץ את כל "
                "הציפויים המוזכרים בשרטוט למערך coating_processes או "
                "painting_processes, עם פרטי התקן המלאים (TYPE/CLASS/GRADE)."
            )
            try:
                stage2_retry, usage_retry = _safe_call(
                    _call_vision, client, deployment, retry_prompt, images
                )
                tracker.add_stage(
                    "stage_2_retry", calculate_cost(usage_retry, deployment)
                )
                for key, value in (stage2_retry or {}).items():
                    if value and not stage2.get(key):
                        stage2[key] = value
                if stage2.get("coating_processes") or stage2.get("painting_processes"):
                    logger.info("✅ Retry הצליח: נמצאו תהליכים")
                else:
                    logger.warning("⚠️ Retry לא מצא תהליכים גם עם OCR")
            except Exception as exc:
                logger.warning("Stage 2 retry נכשל: %s", exc)

    # ─── Two-Pass: השוואת Stage 2 פעמיים לשדות קריטיים (RAL / מותגים) ───
    two_pass_warnings: list[dict] = []
    if should_run_two_pass(stage2):
        logger.info("Stage 2 Two-Pass: מריץ הרצה שנייה לאימות RAL ומותגים...")
        try:
            stage2_pass2, usage_pass2 = _safe_call(
                _call_vision, client, deployment, stage2_prompt, images
            )
            tracker.add_stage("stage_2_two_pass", calculate_cost(usage_pass2, deployment))
            stage2, two_pass_warnings = compare_and_merge(stage2, stage2_pass2)
            if two_pass_warnings:
                logger.warning(
                    "⚠️ Two-Pass: נמצאו %d אי-התאמות", len(two_pass_warnings)
                )
        except Exception as exc:
            logger.warning("Two-Pass נכשל: %s", exc)

    # ─── Post-processing: סנן רשומות ציפוי/צביעה ריקות (רעש מהמודל) ───
    for key in ("coating_processes", "painting_processes"):
        before = stage2.get(key) or []
        after = [p for p in before if _is_meaningful_process(p)]
        if len(after) < len(before):
            logger.info(f"📝 {key}: סוננו {len(before) - len(after)} רשומות ריקות")
        stage2[key] = after

    # ─── Post-processing: חילוץ material מתוך NOTES אם חסר ───
    if not (stage1.get("material") or "").strip():
        material_from_notes = _extract_material_from_notes(stage2.get("notes", ""))
        if material_from_notes:
            stage1["material"] = material_from_notes
            logger.info(f"📝 חומר חולץ מ-NOTES: {material_from_notes}")

    # ─── Post-processing: השלמה / תיקון part_number ───
    _reconcile_part_number(stage1, pdf_path.name)

    # ─── Post-processing: ניקוי Rev (מקפים/רווחים מיותרים בקצוות) ───
    rev_raw = (stage1.get("revision") or "").strip()
    if rev_raw:
        rev_clean = normalize_revision(rev_raw)
        if rev_clean != rev_raw:
            logger.info(f"📝 Rev נוקה: '{rev_raw}' → '{rev_clean}'")
            stage1["revision"] = rev_clean

    # ─── Post-processing: תיקון אוטומטי של P/N ───
    # אם מה שחולץ לא נמצא ב-OCR, אבל מועמד משם הקובץ כן נמצא ב-OCR —
    # כמעט ודאי שהמודל טעה ושם הקובץ מדויק. מחליפים ומתעדים.
    pn_auto_corrected = _try_autocorrect_pn(stage1, pdf_path.name, ocr_text)
    if pn_auto_corrected:
        logger.info(
            "🔧 P/N תוקן אוטומטית: '%s' → '%s' (שם הקובץ מופיע ב-OCR, הערך שחולץ לא)",
            pn_auto_corrected[0],
            pn_auto_corrected[1],
        )

    # ─── Stage 3 — סיכום עברי ───
    logger.info("Stage 3: יצירת סיכום עברי...")
    coatings_str = ", ".join(_proc_to_str(c) for c in stage2.get("coating_processes", []) if _proc_to_str(c))
    paintings_str = ", ".join(_proc_to_str(p) for p in stage2.get("painting_processes", []) if _proc_to_str(p))
    stage3_prompt = STAGE_3_PROMPT_TEMPLATE.format(
        material=stage1.get("material", ""),
        coatings=coatings_str,
        paintings=paintings_str,
    )
    # Stage 3 הוא cosmetic — אם נכשל, נמשיך בלי סיכום עברי
    try:
        hebrew_summary, usage3 = _safe_call(
            _call_text, client, deployment, stage3_prompt,
            stage="stage_3_hebrew_summary",
        )
        tracker.add_stage("stage_3_hebrew_summary", calculate_cost(usage3, deployment))
    except StageFailedError as exc:
        logger.warning("Stage 3 נכשל — מדלג על סיכום עברי: %s", exc)
        hebrew_summary = ""

    # ─── ולידציה — RAL, מותגים, ציפוי, עובי, Rev, P/N, פורמט תקן, OCR grounding ───
    filename_pn_candidate = _extract_pn_from_filename(pdf_path.name)
    validation_warnings = run_all_validators(
        {**stage1, **stage2},
        filename=pdf_path.name,
        filename_pn=filename_pn_candidate,
        ocr_text=ocr_text,
    )
    all_warnings = two_pass_warnings + identity_mismatch_warnings + validation_warnings
    if all_warnings:
        logger.warning(
            "⚠️ ולידציה: %d אזהרות נמצאו (%d קריטיות)",
            len(all_warnings),
            sum(1 for w in all_warnings if w.get("severity") == "CRITICAL"),
        )

    # ─── איחוד תוצאות ───
    result = {
        **stage1,
        **stage2,
        "process_summary_hebrew": hebrew_summary,
        "source_filename": pdf_path.name,
        "_cost_info": tracker.summary(),
        "_ocr_used": ocr_used,
        "_validation_warnings": all_warnings,
    }

    # ─── התאמת מאסטרים ───
    try:
        result["master_matches"] = match_all_coatings(
            stage2.get("coating_processes", []),
            stage2.get("painting_processes", []),
            top_n=3,
        )
    except Exception as exc:  # pragma: no cover
        # Master matching הוא best-effort — נכשל לא עוצר את החילוץ
        mm_err = MasterMatchingError(
            f"Master matching failed: {exc}",
            context={"original_error": str(exc)},
        )
        logger.warning("%s (%s)", mm_err.user_message, exc)
        result["master_matches"] = []
        result.setdefault("_validation_warnings", []).append({
            "severity": "warning",
            "message": mm_err.user_message,
            "suggestion": mm_err.suggestion,
        })

    tracker.save_to_log()

    logger.info(
        f"✅ חילוץ הושלם | עלות: ${tracker.total_cost():.4f} "
        f"(~₪{tracker.total_cost() * 3.7:.3f})"
    )

    # ─── שמירה ל-cache ל-runs עתידיים ───
    save_cached_result(pdf_path, result, extra=f"ocr={use_ocr_fallback}")

    return result
