"""
שכבת ולידציה לאחר חילוץ — מגן מפני הזיות נפוצות.
מחזיר רשימת אזהרות בפורמט אחיד: [{"type", "severity", "source", "value", "message"}]
"""
import re
from difflib import SequenceMatcher

# ─── RAL codes ───────────────────────────────────────────────────────────────

VALID_RAL_CODES = {
    "1000", "1001", "1002", "1003", "1004", "1005", "1006", "1007",
    "1011", "1012", "1013", "1014", "1015", "1016", "1017", "1018",
    "1019", "1020", "1021", "1023", "1024", "1026", "1027", "1028",
    "2000", "2001", "2002", "2003", "2004", "2005", "2008", "2009",
    "2010", "2011", "2012", "2013",
    "3000", "3001", "3002", "3003", "3004", "3005", "3007", "3009",
    "3011", "3012", "3013", "3014", "3015", "3016", "3017", "3018",
    "3020", "3022", "3024", "3026", "3027", "3028", "3031", "3032",
    "3033",
    "5000", "5001", "5002", "5003", "5004", "5005", "5007", "5008",
    "5009", "5010", "5011", "5012", "5013", "5014", "5015", "5017",
    "5018", "5019", "5020", "5021", "5022", "5023", "5024",
    "6000", "6001", "6002", "6003", "6004", "6005", "6006", "6007",
    "6008", "6009", "6010", "6011", "6012", "6013", "6014", "6015",
    "6016", "6017", "6018", "6019", "6020", "6021", "6022", "6024",
    "6025", "6026", "6027", "6028", "6029", "6032", "6033", "6034",
    "7000", "7001", "7002", "7003", "7004", "7005", "7006", "7008",
    "7009", "7010", "7011", "7012", "7013", "7015", "7016", "7021",
    "7022", "7023", "7024", "7026", "7030", "7031", "7032", "7033",
    "7034", "7035", "7036", "7037", "7038", "7039", "7040", "7042",
    "7043", "7044", "7045", "7046", "7047", "7048",
    "8000", "8001", "8002", "8003", "8004", "8007", "8008", "8011",
    "8012", "8014", "8015", "8016", "8017", "8019", "8022", "8023",
    "8024", "8025", "8028", "8029",
    "9001", "9002", "9003", "9004", "9005", "9006", "9007", "9010",
    "9011", "9016", "9017", "9018",
}

_RAL_PATTERN = re.compile(r'RAL\s*(\d{3,4})', re.IGNORECASE)


def validate_ral_codes(report_json: dict) -> list[dict]:
    """מוצא קודי RAL ומאמת שהם תקינים."""
    warnings = []
    texts_to_scan: list[tuple[str, str]] = []

    for proc in report_json.get("painting_processes", []):
        step = proc.get("step_no", "painting")
        texts_to_scan.append((step, proc.get("name", "")))
        texts_to_scan.append((step, proc.get("standard", "")))

    for std in report_json.get("standards", []):
        texts_to_scan.append(("standards", str(std)))

    for source, text in texts_to_scan:
        for match in _RAL_PATTERN.finditer(text or ""):
            code = match.group(1).zfill(4)  # normalize 3→4 digits
            if code not in VALID_RAL_CODES:
                warnings.append({
                    "type": "INVALID_RAL",
                    "severity": "CRITICAL",
                    "source": source,
                    "value": f"RAL {code}",
                    "message": f"RAL {code} אינו קוד RAL תקני — ייתכן שנקרא בשגיאה. בדוק ידנית.",
                })

    return warnings


# ─── Paint brands ─────────────────────────────────────────────────────────────

KNOWN_PAINT_BRANDS = {
    "TAMBOUR", "TAMAGLAS", "TAMGLAS", "NIRLAT", "TIKKURILA",
    "SHERWIN-WILLIAMS", "SHERWIN WILLIAMS", "SHERWINWILLIAMS",
    "AKZONOBEL", "JOTUN", "HEMPEL", "PPG", "INTERNATIONAL",
    "SIGMA", "CARBOLINE", "DUPONT", "AXALTA", "BASF",
    "NIPPON", "KANSAI", "SIKKENS", "RUST-OLEUM",
}

_BY_PATTERN = re.compile(r'\b(\w[\w\s]{1,20})\s+BY\s+(\w+)\b', re.IGNORECASE)


def validate_paint_brand(text: str, source: str = "") -> dict | None:
    """
    בודק אם שם יצרן הצבע (בתבנית 'XXX BY YYY') מוכר.
    מחזיר אזהרה אם לא, אחרת None.
    """
    text_upper = text.upper()
    for brand in KNOWN_PAINT_BRANDS:
        if brand in text_upper:
            return None  # מותג מוכר — תקין

    match = _BY_PATTERN.search(text)
    if match:
        manufacturer = match.group(2).upper()
        if manufacturer not in KNOWN_PAINT_BRANDS:
            return {
                "type": "UNKNOWN_PAINT_BRAND",
                "severity": "HIGH",
                "source": source,
                "value": match.group(0),
                "message": (
                    f"שם היצרן '{match.group(2)}' לא מוכר. "
                    f"בדוק ידנית — מותגים נפוצים: TAMBOUR, JOTUN, SHERWIN-WILLIAMS."
                ),
            }
    return None


def validate_all_paint_brands(report_json: dict) -> list[dict]:
    """סורק את כל תהליכי הצביעה ומאמת שמות יצרנים."""
    warnings = []
    for proc in report_json.get("painting_processes", []):
        name = proc.get("name", "")
        source = proc.get("step_no", "painting")
        w = validate_paint_brand(name, source)
        if w:
            warnings.append(w)
    return warnings


# ─── Coating classification ───────────────────────────────────────────────────

_PRIMER_KEYWORDS = ["PRIMER", "PAINT", "TOP COAT", "TOPCOAT", "POLYURETHANE", "EPOXY"]
_MASKING_KEYWORDS = ["MASK", "MASKING"]
_ACTUAL_COATING_KEYWORDS = [
    "PLATING", "ANODIZE", "ANODIC", "PASSIVAT", "BLACK OXIDE",
    "CONVERSION COAT", "MIL-DTL-16232", "QQ-Z-325",
    "MIL-PRF-46010", "AMS-C-26074", "ELECTROLESS",
]


def validate_coating_classification(coating_processes: list) -> list[dict]:
    """
    בודק שפריטים ב-coating_processes לא מכילים פריימר/צביעה/מיסוך.
    """
    warnings = []
    for proc in coating_processes:
        name = (proc.get("name", "") or "").upper()
        step = proc.get("step_no", "coating")

        is_primer = any(kw in name for kw in _PRIMER_KEYWORDS)
        is_masking = any(kw in name for kw in _MASKING_KEYWORDS)
        is_actual = any(kw in name for kw in _ACTUAL_COATING_KEYWORDS)

        if is_primer and not is_actual:
            warnings.append({
                "type": "MISCLASSIFIED_COATING",
                "severity": "HIGH",
                "source": step,
                "value": name[:80],
                "message": (
                    f"סעיף {step} מכיל מילת מפתח PRIMER/PAINT — "
                    "שייך ל-painting_processes, לא ל-coating_processes."
                ),
            })
        elif is_masking:
            warnings.append({
                "type": "MISCLASSIFIED_COATING",
                "severity": "MEDIUM",
                "source": step,
                "value": name[:80],
                "message": (
                    f"סעיף {step} הוא הוראת מיסוך — "
                    "שייך ל-additional_processes, לא ל-coating_processes."
                ),
            })

    return warnings


# ─── Packing notes ────────────────────────────────────────────────────────────

_KNOWN_PACKING_TEMPLATES = [
    "PACKING SHALL PREVENT CORROSION AND PHYSICAL DAMAGE DURING PROCESS, STORAGE AND SHIPMENT",
    "EACH PART SHALL BE INDIVIDUALLY PACKED",
    "PACKING SHALL PREVENT CORROSION AND PHYSICAL DAMAGE DURING PROCESS, STORAGE AND SUPPLY",
    "PREVENT CORROSION",
    "PHYSICAL DAMAGE",
]


def validate_packing_note(packaging_notes: dict | str) -> dict | None:
    """
    בודק האם הוראת האריזה נראית סבירה (דומה לתבניות ידועות).
    מחזיר אזהרה אם הטקסט חשוד (similarity נמוך מאוד = הזיה).
    """
    if isinstance(packaging_notes, dict):
        text = packaging_notes.get("en", "") or packaging_notes.get("he", "")
    else:
        text = str(packaging_notes or "")

    text = text.strip()
    if not text or len(text) < 10:
        return None  # ריק — אין מה לבדוק

    text_upper = text.upper()

    # בדיקה מהירה — מכיל מילת מפתח מוכרת?
    for tmpl in _KNOWN_PACKING_TEMPLATES:
        if tmpl in text_upper:
            return None

    # בדיקת similarity לתבנית הארוכה
    best_ratio = max(
        SequenceMatcher(None, text_upper, tmpl.upper()).ratio()
        for tmpl in _KNOWN_PACKING_TEMPLATES
    )

    if best_ratio < 0.45:
        return {
            "type": "UNUSUAL_PACKING_NOTE",
            "severity": "HIGH",
            "source": "packaging_notes",
            "value": text[:100],
            "message": (
                f"הוראת האריזה לא דומה לתבניות ידועות (similarity: {best_ratio:.0%}). "
                "ייתכן שנוצרה בהזיה — בדוק ידנית."
            ),
        }

    return None


# ─── Thickness unit validator ─────────────────────────────────────────────────

# תופס מספר או טווח + יחידה: "25um", "12-20 µm", "40-60 MM", "0.5 mil"
_THICKNESS_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*-?\s*(\d+(?:\.\d+)?)?\s*(µm|μm|um|micron|mic|mm|mil|in)",
    re.IGNORECASE,
)


def _parse_max_thickness_mm(thickness: str) -> float | None:
    """מחזיר את הערך המקסימלי מתוך שדה thickness כמיליטרים, או None."""
    if not thickness:
        return None
    m = _THICKNESS_RE.search(thickness)
    if not m:
        return None
    v1 = float(m.group(1))
    v2 = float(m.group(2)) if m.group(2) else v1
    vmax = max(v1, v2)
    unit = m.group(3).lower()
    # נרמל למילימטרים
    if unit in ("µm", "μm", "um", "micron", "mic"):
        return vmax / 1000.0
    if unit == "mm":
        return vmax
    if unit == "mil":
        return vmax * 0.0254  # 1 mil = 0.0254 mm
    if unit == "in":
        return vmax * 25.4
    return None


def validate_thickness_units(report_json: dict) -> list[dict]:
    """מזהיר על יחידות עובי חשודות.

    ציפויים וצביעות כמעט תמיד 0.5μm–500μm (0.0005–0.5 מ"מ). אם המודל מחזיר
    `MM` עם ערך >= 1 — כמעט ודאי שהיחידה האמיתית הייתה μm (micrometer) והאות
    μ/µ הומרה ל-M (שגיאת OCR נפוצה). הפרש פקטור 1000.
    """
    warnings: list[dict] = []

    for kind, key in (("coating", "coating_processes"), ("painting", "painting_processes")):
        for proc in report_json.get(key) or []:
            if not isinstance(proc, dict):
                continue
            raw = (proc.get("thickness") or "").strip()
            if not raw:
                continue
            m = _THICKNESS_RE.search(raw)
            if not m:
                continue
            unit = m.group(3).lower()
            v1 = float(m.group(1))
            v2 = float(m.group(2)) if m.group(2) else v1
            vmax = max(v1, v2)
            # חשוד: MM עם ערך >= 1 (1mm זה כבר 1000μm — לא ריאלי לציפוי/צבע)
            if unit == "mm" and vmax >= 1.0:
                label = (proc.get("type_he") or proc.get("type") or "").strip()
                warnings.append({
                    "type": "SUSPICIOUS_THICKNESS_UNIT",
                    "severity": "HIGH",
                    "source": f"{kind}:{label}",
                    "value": raw,
                    "message": (
                        f"עובי '{raw}' ב-{kind} — יחידת MM עם ערך גבוה. "
                        f"כמעט ודאי שהיחידה האמיתית היא μm (micrometer). "
                        f"בדוק ידנית."
                    ),
                    "suggestion": f"ייתכן שצריך להיות {vmax:.0f}μm במקום {vmax:.0f}mm",
                })

    return warnings


# ─── Standard format validator ────────────────────────────────────────────────

# דפוסים של משפחות תקנים מוכרות. ערך שלא תואם אף אחד — חשוד (OCR error / הזיה).
# נוגע רק בתחילת המחרוזת (^...) — אחרי "MIL-DTL-5541" יכול להופיע TYPE/CLASS וכו'.
_STANDARD_PATTERNS = [
    # US Military: MIL-DTL-5541, MIL-A-8625F, MIL-PRF-85285, MIL-C-26074
    re.compile(r"^MIL[-\s]+[A-Z]{1,5}[-\s]+\d{3,}", re.IGNORECASE),
    # SAE/AMS: SAE-AMS-4027, SAE-AMS-C-26074, AMS-QQ-A-250/11, AMS 2700
    re.compile(r"^(?:SAE[-\s]+)?AMS[-\s]*(?:[A-Z][-\s]*)?(?:QQ[-\s]*[A-Z][-\s]*)?\d{2,}", re.IGNORECASE),
    # ASTM: ASTM B633, ASTM A 564, ASTM-B-209, ASTM D3951
    re.compile(r"^ASTM[-\s]*[A-Z][-\s]*\d{2,}", re.IGNORECASE),
    # ISO: ISO 9001, ISO 15730, ISO 3098/1, ISO 1302
    re.compile(r"^ISO[-\s]*\d{3,}", re.IGNORECASE),
    # QQ (legacy US mil-spec): QQ-P-416, QQ-Z-325, QQ-S-365
    re.compile(r"^QQ[-\s]*[A-Z][-\s]*\d{2,}", re.IGNORECASE),
    # RAFAEL PS family: PS-111.21, PS 111.24, PS-TILDOCS#172373,
    # PS-RAFDOCS-434847, PS-38-576104, P.S.233100 (IAI variant with dots)
    re.compile(r"^P\.?\s?S[-\s.]*(?:[A-Z]+[-#\s.]*)?\d+", re.IGNORECASE),
    # RAFDOCS / TILDOCS / DOCS stand-alone
    re.compile(r"^(?:[A-Z]{3,}DOCS|DOCS)[-#\s]*\d+", re.IGNORECASE),
    # FED-STD: FED-STD-595, FED-STD-101
    re.compile(r"^FED[-\s]*STD[-\s]*\d+", re.IGNORECASE),
    # A-A (commercial item description)
    re.compile(r"^A[-\s]*A[-\s]*\d{2,}", re.IGNORECASE),
    # AS / NAS (aerospace standard): AS478, NAS123, NASM series
    re.compile(r"^NAS[MC]?\d+", re.IGNORECASE),
    re.compile(r"^AS\d+(?:[-/]\d+[A-Z]?)?", re.IGNORECASE),
    # ASME Y14.5, ASME B46.1
    re.compile(r"^ASME[-\s]+[A-Z]\d+(?:\.\d+)?", re.IGNORECASE),
    # ANSI (dimensioning, screw threads): ANSI Y14.5M, ANSI 14.5M - 1982, ANSI B18.3
    re.compile(r"^ANSI[-.\s]+[A-Z]?\d+(?:\.\d+[A-Z]?)?", re.IGNORECASE),
    # DIN, EN (European)
    re.compile(r"^(?:DIN|EN)[-\s]*\d{2,}", re.IGNORECASE),
    # GEN_ (RAFAEL material spec)
    re.compile(r"^GEN[-_]\d+", re.IGNORECASE),
    # ECSS (European Space), JIS (Japan), BS (British)
    re.compile(r"^(?:ECSS|JIS|BS)[-\s]*[A-Z]?\d+", re.IGNORECASE),
    # Internal / proprietary document IDs with separator:
    # AMAT (0250-01019), IAI (5902Y004-001, DWG.1002A315-001), KLA (905-610019-007),
    # KRETOS (I-630028, I-630028 STEP 1,2).
    # Pattern: 0-4 letter prefix + optional separator + 2+ digits + alphanumeric tail
    # + optional second group (digits after separator).
    re.compile(
        r"^[A-Z]{0,4}[-./]?\d{2,}[A-Z0-9]*(?:[-./\s,][A-Z0-9][\w\s.,/-]*)?",
        re.IGNORECASE,
    ),
]

# ערכים שמופיעים כ"תקן" אבל הם בעצם תוויות — לא לדגל
_STANDARD_BENIGN_LABELS = {
    "ISO", "ISO STANDARDS", "ISO STANDARD",
    "SEE EDR", "SEE SHEET", "SEE NOTE", "SEE DRAWING", "SEE MODEL",
    "PROTECTED", "N/A", "NONE", "N.A.", "NA",
    "FE/ZN", "FE/ZN 8", "FE/ZN 12", "FE/ZN 25",
    "TYPE I", "TYPE II", "TYPE III", "TYPE IV",
    "CLASS 1", "CLASS 2", "CLASS 3",
}


def validate_standard_formats(report_json: dict) -> list[dict]:
    """מזהיר אם תקן לא תואם לפורמטים מוכרים.

    תופס OCR errors נפוצים: "TIPE" (במקום TYPE) בתוך שם תקן, "CLASS @"
    (במקום "CLASS 2"), תקן מומצא לחלוטין וכו'.
    """
    warnings: list[dict] = []
    for std in report_json.get("standards") or []:
        if not isinstance(std, str):
            continue
        val = std.strip()
        if not val or len(val) < 3:
            continue
        if val.upper() in _STANDARD_BENIGN_LABELS:
            continue
        # אם תואם לפחות דפוס אחד — תקין
        if any(p.match(val) for p in _STANDARD_PATTERNS):
            # בנוסף — בדיקת "TYPE" לעומת "TIPE", "CLASS" לעומת "@"
            if re.search(r"\bTIPE\b", val, re.IGNORECASE):
                warnings.append({
                    "type": "STANDARD_OCR_TYPO",
                    "severity": "HIGH",
                    "source": "standards",
                    "value": val[:100],
                    "message": f"תקן '{val[:60]}' מכיל 'TIPE' — כמעט ודאי OCR ל-'TYPE'.",
                    "suggestion": "החלף TIPE ב-TYPE",
                })
            if re.search(r"CLASS\s+[@#&*]", val, re.IGNORECASE):
                warnings.append({
                    "type": "STANDARD_OCR_TYPO",
                    "severity": "HIGH",
                    "source": "standards",
                    "value": val[:100],
                    "message": f"תקן '{val[:60]}' מכיל 'CLASS @/#/&/*' — OCR של ספרה.",
                    "suggestion": "בדוק את הספרה המקורית בשרטוט",
                })
            continue
        # לא תואם אף דפוס — LOW severity בלבד, כי תקני פנים־חברה
        # לא סטנדרטיים אבל לגיטימיים (AMAT / IAI / KLA / KRETOS). הדגל שימושי
        # יותר יחד עם STANDARD_NOT_IN_OCR מאשר לבד.
        warnings.append({
            "type": "UNRECOGNIZED_STANDARD_FORMAT",
            "severity": "LOW",
            "source": "standards",
            "value": val[:100],
            "message": (
                f"התקן '{val[:60]}' לא בפורמט שגרתי (MIL/AMS/ASTM/ISO/QQ/PS/ANSI...). "
                f"ייתכן שגיאת OCR, תקן פנימי של חברה, או הזיה. "
                f"אם גם מופיעה אזהרת STANDARD_NOT_IN_OCR — סימן חזק יותר."
            ),
            "suggestion": "אמת מול השרטוט.",
        })
    return warnings


# ─── Revision sanity check ────────────────────────────────────────────────────

_REV_VALID_RE = re.compile(r"^[A-Z]{1,2}[0-9]?$|^-$|^[0-9]{1,2}$")


def normalize_revision(rev: str) -> str:
    """נקה ערך Rev מרווחים ומקפים מיותרים.

    דוגמאות: 'E-' → 'E', ' A ' → 'A', '--' → '-'.
    לא משנה ערכים תקינים (A, B, C, 01, etc.).
    """
    if not rev:
        return ""
    cleaned = rev.strip()
    # הסר מקפים וסוגריים ורווחים בקצוות, אבל שמור '-' יחיד (מסמן "ללא גרסה")
    if cleaned == "-":
        return "-"
    cleaned = cleaned.strip("- \t()[]")
    return cleaned


def validate_revision(report_json: dict) -> list[dict]:
    """מזהיר אם Rev בפורמט לא שגרתי (אחרי normalize)."""
    warnings: list[dict] = []
    rev = (report_json.get("revision") or "").strip()
    if not rev:
        return warnings
    normalized = normalize_revision(rev)
    # אזהרה אם הפורמט חריג — Rev בד"כ 1-2 אותיות או ספרה קצרה
    if not _REV_VALID_RE.match(normalized.upper()):
        warnings.append({
            "type": "SUSPICIOUS_REVISION",
            "severity": "MEDIUM",
            "source": "title_block",
            "value": rev,
            "message": (
                f"ערך Revision '{rev}' בפורמט חריג. "
                f"ערך תקין בד\"כ אות אחת (A-Z) או 1-2 ספרות."
            ),
            "suggestion": "בדוק ידנית מול השרטוט.",
        })
    return warnings


# ─── Part number vs filename cross-check ──────────────────────────────────────

def validate_pn_filename_match(report_json: dict, filename: str,
                                filename_candidate: str) -> list[dict]:
    """מזהיר אם ה-P/N שחולץ שונה מהותית מהמועמד משם הקובץ.

    משווה רק כשיש מועמד ברור משם הקובץ (אחרת לא נותן false positives).
    """
    warnings: list[dict] = []
    if not filename_candidate:
        return warnings
    extracted = (report_json.get("part_number") or "").strip().upper()
    candidate = filename_candidate.strip().upper()
    if not extracted or extracted == candidate:
        return warnings
    # נוגע גם ב-drawing_number — לפעמים הוא שונה מ-P/N אבל כולל את המזהה
    dwg = (report_json.get("drawing_number") or "").strip().upper()
    if candidate in extracted or extracted in candidate:
        return warnings
    if dwg and (candidate in dwg or dwg in candidate):
        return warnings
    # Levenshtein קצר — אם 1-2 תווים שונים, ייתכן OCR אך שווה לדווח
    ratio = SequenceMatcher(None, extracted, candidate).ratio()
    warnings.append({
        "type": "PN_FILENAME_MISMATCH",
        "severity": "HIGH" if ratio < 0.6 else "MEDIUM",
        "source": filename,
        "value": f"חולץ: {extracted} | שם קובץ: {candidate}",
        "message": (
            f"P/N שחולץ ({extracted}) שונה מהמזהה בשם הקובץ ({candidate}). "
            f"ייתכן שגיאת OCR (C↔V, T↔1, 0↔O, μ↔M) — בדוק ידנית."
        ),
        "suggestion": "השווה את ה-P/N לכותרת השרטוט.",
    })
    return warnings


# ─── OCR grounding validator ──────────────────────────────────────────────────

# תווים שמפרידים טוקנים בטקסט (לא אלפא-נומריים)
_TOKENIZE_RE = re.compile(r"[A-Z0-9]+")


def _tokenize(s: str) -> set:
    """מפצל מחרוזת לסט טוקנים אלפא-נומריים (UPPERCASE)."""
    return set(_TOKENIZE_RE.findall((s or "").upper()))


def _coverage_ratio(value: str, ocr_tokens: set) -> tuple[float, int]:
    """יחס כיסוי: כמה מהטוקנים של value מופיעים ב-ocr_tokens.

    מחזיר (ratio, n_tokens). ratio=1.0 = הכל מופיע ב-OCR. ratio<0.6 = חשוד.
    """
    tokens = _tokenize(value)
    # סנן טוקנים קצרים (<=2 תווים) שעלולים להיות מילות קישור
    significant = {t for t in tokens if len(t) >= 3}
    if not significant:
        return 1.0, 0  # לא ניתן לבדיקה
    matched = sum(1 for t in significant if t in ocr_tokens)
    return matched / len(significant), len(significant)


def validate_ocr_grounded(report_json: dict, ocr_text: str,
                           min_coverage: float = 0.6) -> list[dict]:
    """מוודא ששדות זיהוי ותקנים מופיעים בטקסט ה-OCR.

    OCR לא מושלם — לכן דיגול MEDIUM בלבד. אם רק 60% מהטוקנים של ערך שחולץ
    מופיעים ב-OCR — כמעט ודאי הזיה של המודל (מודל Vision לפעמים ממציא
    תקנים שנראים אמינים אבל לא מופיעים בשרטוט).

    Skip-conditions:
    - OCR text ריק → דלג לגמרי (אי אפשר לבדוק)
    - ערכים עם <2 טוקנים משמעותיים → דלג
    """
    warnings: list[dict] = []
    if not ocr_text or len(ocr_text.strip()) < 50:
        return warnings

    ocr_tokens = _tokenize(ocr_text)
    if len(ocr_tokens) < 20:
        # OCR חלש מדי — לא אמין לבדיקה
        return warnings

    # 1. תקנים
    for std in report_json.get("standards") or []:
        if not isinstance(std, str):
            continue
        val = std.strip()
        if not val:
            continue
        ratio, n = _coverage_ratio(val, ocr_tokens)
        if n >= 2 and ratio < min_coverage:
            warnings.append({
                "type": "STANDARD_NOT_IN_OCR",
                "severity": "MEDIUM",
                "source": "standards",
                "value": val[:100],
                "message": (
                    f"התקן '{val[:60]}' לא נמצא בטקסט OCR ({ratio:.0%} כיסוי). "
                    f"ייתכן הזיה של המודל — בדוק ידנית מול השרטוט."
                ),
                "suggestion": "אמת שהתקן אכן כתוב בשרטוט המקורי.",
            })

    # 2. P/N — גם טוקן יחיד אם הוא מספיק ארוך (מזהה קומפקטי כמו "31073803")
    pn = (report_json.get("part_number") or "").strip()
    if pn:
        ratio, n = _coverage_ratio(pn, ocr_tokens)
        # ≥1 טוקן משמעותי (≥3 תווים), 0% כיסוי — PN לא מופיע בכלל ב-OCR
        if n >= 1 and ratio == 0:
            warnings.append({
                "type": "PN_NOT_IN_OCR",
                "severity": "HIGH",
                "source": "title_block",
                "value": pn,
                "message": (
                    f"P/N '{pn}' לא נמצא בטקסט OCR. "
                    f"ייתכן הזיה או שגיאת OCR חמורה — בדוק ידנית."
                ),
                "suggestion": "אמת מול כותרת השרטוט.",
            })
        # ≥2 טוקנים, כיסוי חלקי (<50%) — חלק מה-PN מופיע, חלק לא
        elif n >= 2 and ratio < 0.5:
            warnings.append({
                "type": "PN_PARTIALLY_IN_OCR",
                "severity": "MEDIUM",
                "source": "title_block",
                "value": pn,
                "message": (
                    f"רק {ratio:.0%} מה-P/N '{pn}' מופיע ב-OCR — "
                    f"ייתכן שגיאת OCR בחלק מהתווים."
                ),
                "suggestion": "בדוק מול כותרת השרטוט.",
            })

    # 3. שמות יצרני צבע (brands ב-painting_processes)
    for proc in report_json.get("painting_processes") or []:
        if not isinstance(proc, dict):
            continue
        brand = (proc.get("brand") or "").strip()
        if not brand:
            continue
        ratio, n = _coverage_ratio(brand, ocr_tokens)
        if n >= 1 and ratio < 0.6:
            warnings.append({
                "type": "BRAND_NOT_IN_OCR",
                "severity": "MEDIUM",
                "source": "painting_processes",
                "value": brand[:80],
                "message": (
                    f"יצרן צבע '{brand}' לא נמצא בטקסט OCR — ייתכן הזיה."
                ),
                "suggestion": "אמת ששם היצרן מופיע בשרטוט.",
            })

    return warnings


# ─── Combined validator ───────────────────────────────────────────────────────

def run_all_validators(report_json: dict,
                       *, filename: str = "",
                       filename_pn: str = "",
                       ocr_text: str = "") -> list[dict]:
    """
    מריץ את כל הולידטורים על דוח חילוץ ומחזיר רשימת אזהרות.

    Args:
        report_json: תוצאת החילוץ.
        filename: שם הקובץ המקורי (לדיווח בלבד).
        filename_pn: מועמד P/N שנגזר משם הקובץ (מ-_extract_pn_from_filename).
                     אם ריק — לא תרוץ בדיקת cross-check.
        ocr_text: טקסט OCR של השרטוט (לבדיקת grounding של תקנים/מותגים).
                  אם ריק — דלג על OCR grounding.
    """
    warnings: list[dict] = []
    warnings.extend(validate_ral_codes(report_json))
    warnings.extend(validate_all_paint_brands(report_json))
    warnings.extend(validate_coating_classification(
        report_json.get("coating_processes", [])
    ))
    warnings.extend(validate_thickness_units(report_json))
    warnings.extend(validate_revision(report_json))
    warnings.extend(validate_pn_filename_match(report_json, filename, filename_pn))
    warnings.extend(validate_standard_formats(report_json))
    warnings.extend(validate_ocr_grounded(report_json, ocr_text))
    packing_warning = validate_packing_note(
        report_json.get("packaging_notes", {})
    )
    if packing_warning:
        warnings.append(packing_warning)
    return warnings
