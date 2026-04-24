"""
בדיקות לולידטורים החדשים: עובי, Rev, ו-P/N mismatch.
"""
from __future__ import annotations

from core.validators import (
    normalize_revision,
    validate_pn_filename_match,
    validate_revision,
    validate_thickness_units,
)


# ─── normalize_revision ───────────────────────────────────────────────────────

def test_normalize_revision_removes_trailing_dash():
    assert normalize_revision("E-") == "E"
    assert normalize_revision("A-") == "A"


def test_normalize_revision_keeps_dash_alone():
    """מקף לבד = גרסה ראשונה ללא תג — לא לנגוע."""
    assert normalize_revision("-") == "-"


def test_normalize_revision_strips_whitespace():
    assert normalize_revision(" A ") == "A"
    assert normalize_revision("\tB\n") == "B"


def test_normalize_revision_empty():
    assert normalize_revision("") == ""
    assert normalize_revision(None) == ""


def test_normalize_revision_strips_brackets():
    assert normalize_revision("[A]") == "A"
    assert normalize_revision("(C)") == "C"


# ─── validate_revision ────────────────────────────────────────────────────────

def test_validate_revision_accepts_single_letter():
    assert validate_revision({"revision": "A"}) == []
    assert validate_revision({"revision": "E"}) == []


def test_validate_revision_accepts_digit():
    assert validate_revision({"revision": "01"}) == []
    assert validate_revision({"revision": "2"}) == []


def test_validate_revision_accepts_dash():
    """גרסה ראשונה מסומנת ב'-'."""
    assert validate_revision({"revision": "-"}) == []


def test_validate_revision_flags_weird_format():
    warnings = validate_revision({"revision": "ABC123"})
    assert len(warnings) == 1
    assert warnings[0]["type"] == "SUSPICIOUS_REVISION"


def test_validate_revision_flags_special_chars():
    warnings = validate_revision({"revision": "A#"})
    assert len(warnings) == 1


def test_validate_revision_ignores_empty():
    assert validate_revision({"revision": ""}) == []
    assert validate_revision({}) == []


# ─── validate_thickness_units ─────────────────────────────────────────────────

def test_thickness_flags_mm_with_high_value():
    """MM עם ערך >= 1 חשוד לציפוי (בד\"כ μm)."""
    data = {"coating_processes": [{"thickness": "40-60MM", "type_he": "המרה"}]}
    warnings = validate_thickness_units(data)
    assert len(warnings) == 1
    assert warnings[0]["type"] == "SUSPICIOUS_THICKNESS_UNIT"
    assert "μm" in warnings[0]["suggestion"]


def test_thickness_accepts_micrometers():
    """μm תקין — לא דגל."""
    data = {"coating_processes": [{"thickness": "25um"}]}
    assert validate_thickness_units(data) == []
    data = {"coating_processes": [{"thickness": "12-20 µm"}]}
    assert validate_thickness_units(data) == []


def test_thickness_accepts_mm_below_1():
    """MM עם ערך נמוך (<1) עדיין יכול להיות חוקי במקרים מסוימים."""
    data = {"coating_processes": [{"thickness": "0.5 mm"}]}
    # 0.5mm = 500μm — עדיין גבוה אבל לא זורקים אלא אם >= 1
    assert validate_thickness_units(data) == []


def test_thickness_flags_paintings_too():
    data = {"painting_processes": [{"thickness": "25-40MM", "type_he": "פריימר"}]}
    warnings = validate_thickness_units(data)
    assert len(warnings) == 1


def test_thickness_empty_field_ok():
    data = {"coating_processes": [{"thickness": ""}, {"thickness": None}]}
    assert validate_thickness_units(data) == []


def test_thickness_accepts_mil():
    """יחידת mil (0.0254mm) — תקינה."""
    data = {"coating_processes": [{"thickness": "0.5 mil"}]}
    assert validate_thickness_units(data) == []


# ─── validate_pn_filename_match ───────────────────────────────────────────────

def test_pn_match_identical():
    """חולץ = שם הקובץ — אין אזהרה."""
    warnings = validate_pn_filename_match(
        {"part_number": "BN80760B"}, "BN80760B_A.pdf", "BN80760B"
    )
    assert warnings == []


def test_pn_match_substring():
    """שם הקובץ כלול ב-P/N שחולץ — OK."""
    warnings = validate_pn_filename_match(
        {"part_number": "BN80760B-A"}, "BN80760B_A.pdf", "BN80760B"
    )
    assert warnings == []


def test_pn_match_flags_ocr_error():
    """OCR החליף N8 ב-NB — צריך לדגל."""
    warnings = validate_pn_filename_match(
        {"part_number": "BNB0760B"}, "BN80760B_A.pdf", "BN80760B"
    )
    assert len(warnings) == 1
    assert warnings[0]["type"] == "PN_FILENAME_MISMATCH"


def test_pn_match_no_candidate():
    """אין מועמד משם הקובץ — לא מריצים בדיקה."""
    warnings = validate_pn_filename_match(
        {"part_number": "ABC123"}, "random.pdf", ""
    )
    assert warnings == []


def test_pn_match_via_drawing_number():
    """אם ה-PN שונה אבל drawing_number תואם — OK."""
    warnings = validate_pn_filename_match(
        {"part_number": "CATALOG-X", "drawing_number": "BN80760B"},
        "BN80760B.pdf",
        "BN80760B",
    )
    assert warnings == []
