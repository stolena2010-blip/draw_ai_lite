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


# ─── Combined validator ───────────────────────────────────────────────────────

def run_all_validators(report_json: dict) -> list[dict]:
    """
    מריץ את כל הולידטורים על דוח חילוץ ומחזיר רשימת אזהרות.
    """
    warnings: list[dict] = []
    warnings.extend(validate_ral_codes(report_json))
    warnings.extend(validate_all_paint_brands(report_json))
    warnings.extend(validate_coating_classification(
        report_json.get("coating_processes", [])
    ))
    packing_warning = validate_packing_note(
        report_json.get("packaging_notes", {})
    )
    if packing_warning:
        warnings.append(packing_warning)
    return warnings
