"""
Two-Pass Extraction — מריץ Stage 2 פעמיים ומשווה שדות קריטיים (RAL, מותגים, P/N, Rev).
אם יש אי-התאמה → מסמן [VERIFY] ומוסיף אזהרה ל-_verification_warnings.
"""
import json
import logging
import re

logger = logging.getLogger(__name__)


def compare_identity_fields(s1: dict, s2: dict) -> list[dict]:
    """משווה שדות זיהוי (P/N, Rev, drawing_number) בין שתי הרצות Stage 1.

    שגיאת OCR בשדות האלה קריטית כי הם מזהי המפתח של השרטוט.
    מחזיר רשימת warnings — ריקה אם אין מחלוקת.
    """
    warnings: list[dict] = []

    for field, label in [
        ("part_number", "P/N"),
        ("revision", "Rev"),
        ("drawing_number", "Drawing Number"),
    ]:
        v1 = (s1.get(field) or "").strip()
        v2 = (s2.get(field) or "").strip()
        # שני הצדדים ריקים או זהים — אין מחלוקת
        if v1 == v2:
            continue
        # אחד ריק והשני מלא — לא ממש מחלוקת, פשוט השלמה
        if not v1 or not v2:
            continue
        warnings.append({
            "type": f"{field.upper()}_MISMATCH",
            "severity": "HIGH",
            "source": "two_pass",
            "value": f"הרצה 1: {v1} | הרצה 2: {v2}",
            "message": (
                f"{label} שונה בין שתי ההרצות. ייתכן שגיאת OCR "
                f"(C↔V, T↔1, 0↔O, N↔B וכו') — בדוק ידנית מול השרטוט."
            ),
            "suggestion": f"ערך אחד מתוך: {v1}, {v2} — אבל מי הנכון?",
        })
    return warnings

_RAL_RE = re.compile(r'RAL\s*\d{3,4}', re.IGNORECASE)
_BRAND_BY_RE = re.compile(r'\b[A-Z]{3,}\s+BY\s+[A-Z]{3,}\b')


def _mark_verify(text: str, patterns: list[str]) -> str:
    """מחליף ערכים שנמצאו בסט הממוחלק ב-[VERIFY: ...]."""
    for pat in patterns:
        text = text.replace(pat, f"[VERIFY: {pat}]")
    return text


def compare_and_merge(result_1: dict, result_2: dict) -> tuple[dict, list[dict]]:
    """
    משווה שני תוצאות חילוץ ומחזיר (merged_result, warnings).
    - merged_result: result_1 עם סימוני [VERIFY] בשדות לא-עקביים.
    - warnings: רשימת אי-התאמות שנמצאו.
    """
    warnings: list[dict] = []

    r1_str = json.dumps(result_1, ensure_ascii=False)
    r2_str = json.dumps(result_2, ensure_ascii=False)

    # השוואת קודי RAL
    rals_1 = set(_RAL_RE.findall(r1_str))
    rals_2 = set(_RAL_RE.findall(r2_str))
    rals_only_in_1 = rals_1 - rals_2
    rals_only_in_2 = rals_2 - rals_1

    if rals_only_in_1 or rals_only_in_2:
        warnings.append({
            "type": "RAL_MISMATCH",
            "severity": "CRITICAL",
            "source": "two_pass",
            "value": f"הרצה 1: {sorted(rals_1)} | הרצה 2: {sorted(rals_2)}",
            "message": "קודי RAL שונים בין שתי ההרצות — נסמן [VERIFY]. בדוק ידנית!",
        })
        # סמן את כל ה-RAL בתוצאה המאוחדת
        for ral in rals_1 | rals_2:
            r1_str = r1_str.replace(f'"{ral}"', f'"[VERIFY: {ral}]"')
            r1_str = r1_str.replace(ral, f"[VERIFY: {ral}]")

    # השוואת שמות מותג (תבנית "X BY Y")
    brands_1 = set(_BRAND_BY_RE.findall(r1_str))
    brands_2 = set(_BRAND_BY_RE.findall(r2_str))

    if brands_1 != brands_2:
        warnings.append({
            "type": "BRAND_MISMATCH",
            "severity": "HIGH",
            "source": "two_pass",
            "value": f"הרצה 1: {sorted(brands_1)} | הרצה 2: {sorted(brands_2)}",
            "message": "שמות מותג/יצרן שונים בין שתי ההרצות — הזיה אפשרית. בדוק ידנית!",
        })

    # בנה תוצאה מאוחדת (בסיס: הרצה 1 עם סימוני VERIFY)
    try:
        merged = json.loads(r1_str)
    except json.JSONDecodeError:
        logger.warning("two_pass: JSON parse failed after marking — returning original")
        merged = result_1

    return merged, warnings


def should_run_two_pass(stage2: dict) -> bool:
    """
    קובע האם כדאי להריץ two-pass.
    מריץ רק אם יש נתוני צביעה (RAL / מותג) שיכולים להכיל הזיות.
    """
    has_painting = bool(stage2.get("painting_processes"))
    r2_str = json.dumps(stage2, ensure_ascii=False)
    has_ral = bool(_RAL_RE.search(r2_str))
    has_brand = bool(_BRAND_BY_RE.search(r2_str))
    return has_painting and (has_ral or has_brand)
