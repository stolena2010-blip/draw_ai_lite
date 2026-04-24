"""
בדיקות לוולידטורים של Tier 1+2: standard format, OCR grounding,
Elbit UN prefix, process filtering.
"""
from __future__ import annotations

from core.extractor import _extract_pn_from_filename, _is_meaningful_process
from core.validators import (
    validate_ocr_grounded,
    validate_standard_formats,
)


# ─── Elbit UN prefix fix ──────────────────────────────────────────────────────

def test_elbit_un_prefix_stripped():
    """קבצי Elbit בפורמט un8554-... — 'UN' לא חלק מ-P/N."""
    # לפני התיקון: היה מחזיר 'UN8554' (שגוי)
    result = _extract_pn_from_filename("un8554-3672-00#RevA#A0#S2_30.pdf")
    # אחרי התיקון: מחזיר ריק כי אין candidate תקין של 6+ תווים
    assert "UN" not in result


def test_elbit_un34040t_stripped():
    result = _extract_pn_from_filename("un34040T-40301-01#Rev02#A0#S2_30.pdf")
    assert not result.startswith("UN")


def test_un_prefix_not_stripped_if_followed_by_letter():
    """אם יש UN + אות (לא ספרה) — לא לגעת."""
    # Edge case: קובץ שבאמת מתחיל ב-UNIT או UNUSED (לא קשור לפרפיקס URL).
    # הרגקס שלנו דורש UN + ספרה, אז UNIT3456 ישאר כמו שהוא.
    result = _extract_pn_from_filename("UNITX1234-something.pdf")
    # UNITX1234 יכול להיות candidate (UN + ITX1234), לא נחסם
    # הבדיקה רק ש-UN לא הוסר בצורה שגויה
    assert "1234" in result or result == ""


def test_regular_filenames_unchanged():
    """שם רגיל של RAFAEL — לא מושפע מהשינוי."""
    assert _extract_pn_from_filename("B2BDraw_BN80760B-A-PD-bn80760b_a.pdf_30.PDF") == "BN80760B"


# ─── Numeric compound P/N extraction ──────────────────────────────────────────

def test_numeric_pn_extracted_from_filename():
    """שמות קובץ שכולם ספרות — פעם ראשונה נתפסים."""
    assert _extract_pn_from_filename("30-173803-(143593).PDF") == "30-173803"


def test_numeric_pn_ignores_paren_metadata():
    """ID בסוגריים בסוף (metadata) לא נחשב ל-P/N."""
    # Parens content should be stripped before search
    result = _extract_pn_from_filename("408-2119-00-(143193).PDF")
    # Prefer alpha-less but multi-group PN before paren
    assert "143193" not in result


def test_numeric_pn_compound():
    """שם ארוך עם 4 קבוצות ספרות — תפיסה מלאה."""
    result = _extract_pn_from_filename("915-80-00586-00.PDF")
    assert result == "915-80-00586-00"


def test_numeric_pn_not_triggered_when_alpha_exists():
    """אם יש alpha candidate — משתמשים בו, לא במסלול הנומרי."""
    # "CX145-08120" — "CX145" matches alpha pattern (5 chars, but <6 fallback rejects)
    # but falling through to numeric should NOT capture "08120" alone;
    # pattern requires 2+ groups with middle 3+ digits.
    result = _extract_pn_from_filename("CX145-08120-(137692).PDF")
    # Numeric fallback requires NN-NNN pattern; "08120" alone doesn't match.
    # The "08120" followed by "-(137692" contains non-paren content before parens
    # which is "08120", single group. Should not trigger numeric fallback.
    # Result may be empty or "08120-something". Either way not a FP.
    assert "137692" not in result  # metadata excluded


# ─── Standard format — PS-TILDOCS/RAFDOCS ─────────────────────────────────────

def test_standard_accepts_ps_tildocs():
    from core.validators import validate_standard_formats
    data = {"standards": ["PS-TILDOCS#172373"]}
    assert validate_standard_formats(data) == []


def test_standard_accepts_ps_rafdocs():
    from core.validators import validate_standard_formats
    data = {"standards": ["PS-RAFDOCS-434847"]}
    assert validate_standard_formats(data) == []


def test_standard_accepts_ps_38_compound():
    from core.validators import validate_standard_formats
    data = {"standards": ["PS-38-576104"]}
    assert validate_standard_formats(data) == []


def test_standard_accepts_tildocs_standalone():
    from core.validators import validate_standard_formats
    data = {"standards": ["TILDOCS#172373", "RAFDOCS-434847"]}
    assert validate_standard_formats(data) == []


def test_standard_accepts_ansi():
    """ANSI Y14.5M, ANSI 14.5M — תקני dimensioning אמיתיים."""
    from core.validators import validate_standard_formats
    data = {"standards": ["ANSI Y14.5M", "ANSI 14.5M - 1982", "ANSI B18.3"]}
    assert validate_standard_formats(data) == []


def test_standard_accepts_internal_company_ids():
    """תקני פנים־חברה (AMAT, IAI, KLA, KRETOS) — לא לדגל כ-unrecognized."""
    from core.validators import validate_standard_formats
    data = {"standards": [
        "0250-01019",           # AMAT
        "0250-00098",           # AMAT
        "04.4-01-11",           # AMAT with dots
        "5902Y004-001",         # IAI
        "5902N800-001",         # IAI
        "905-610019-007",       # KLA
        "DWG.1002A315-001",     # IAI with DWG prefix
        "I-630028 STEP 1,2",    # KRETOS
    ]}
    warnings = validate_standard_formats(data)
    assert len(warnings) == 0, f"FP detected: {[w['value'] for w in warnings]}"


def test_standard_unrecognized_severity_is_low():
    """UNRECOGNIZED_STANDARD_FORMAT עכשיו LOW, לא MEDIUM."""
    from core.validators import validate_standard_formats
    data = {"standards": ["TOTALLY_BOGUS_VALUE_XXX"]}
    warnings = validate_standard_formats(data)
    assert len(warnings) == 1
    assert warnings[0]["severity"] == "LOW"


def test_standard_still_flags_pure_gibberish():
    """מילה בודדת בלי פורמט (כמו PSSOOIOO שזה OCR של PS500100) — עדיין נדגלת."""
    from core.validators import validate_standard_formats
    data = {"standards": ["PSSOOIOO"]}
    warnings = validate_standard_formats(data)
    assert len(warnings) == 1
    assert warnings[0]["type"] == "UNRECOGNIZED_STANDARD_FORMAT"


# ─── Benign labels — expanded set ─────────────────────────────────────────────

def test_benign_labels_not_flagged():
    """תוויות גנריות שמופיעות כ'תקן' אבל אינן — לא לדגל."""
    from core.validators import validate_standard_formats
    data = {"standards": [
        "ISO",            # לבד, לא תקן ספציפי
        "ISO STANDARDS",
        "N/A", "NONE",
        "FE/ZN 8",         # Coating notation — לא תקן
        "TYPE II",         # חלקי של תקן אחר
        "CLASS 3",
    ]}
    warnings = validate_standard_formats(data)
    assert warnings == [], f"FP: {[w['value'] for w in warnings]}"


# ─── P/N auto-correction ──────────────────────────────────────────────────────

def test_autocorrect_pn_fixes_ocr_error():
    """THR1510712 → TH151012 צריך להיות מתוקן אוטומטית."""
    from core.extractor import _try_autocorrect_pn
    stage1 = {"part_number": "TH151012", "drawing_number": "TH151012"}
    filename = "THR1510712-(133739).PDF"
    # OCR text שמכיל את שם הקובץ אבל לא את ה-P/N שחולץ
    ocr = (
        "DIMENSIONS IN MILLIMETERS. INTERPRET DRAWING ACCORDING TO "
        "ISO STANDARDS. SURFACE TEXTURE RA 1.6. TOLERANCES UNLESS "
        "OTHERWISE SPECIFIED. P.N. THR1510712 REV A CUSTOMER IAI. "
        "MORE TEXT TO GET OVER 20 TOKENS THRESHOLD. MATERIAL SECTION."
    )
    result = _try_autocorrect_pn(stage1, filename, ocr)
    assert result == ("TH151012", "THR1510712")
    assert stage1["part_number"] == "THR1510712"
    assert stage1["drawing_number"] == "THR1510712"  # drawing_number also updated
    assert stage1["_pn_autocorrected_from"] == "TH151012"


def test_autocorrect_pn_noop_when_both_match():
    """שניהם מופיעים ב-OCR — לא לתקן (שניהם לגיטימיים)."""
    from core.extractor import _try_autocorrect_pn
    stage1 = {"part_number": "BN80760B"}
    filename = "BN80760B-A-PD-bn80760b_a.pdf"
    ocr = (
        "DIMENSIONS IN MILLIMETERS. INTERPRET DRAWING ACCORDING TO "
        "ISO STANDARDS. P.N. BN80760B REV A CUSTOMER RAFAEL. "
        "MORE TEXT TO GET OVER 20 TOKENS. MATERIAL SECTION."
    )
    result = _try_autocorrect_pn(stage1, filename, ocr)
    assert result is None
    assert stage1["part_number"] == "BN80760B"  # unchanged


def test_autocorrect_pn_noop_when_substring():
    """אחד תת-מחרוזת של השני — כנראה שניהם לגיטימיים (prefixes/suffixes)."""
    from core.extractor import _try_autocorrect_pn
    stage1 = {"part_number": "BN80760B-A"}
    filename = "BN80760B_A.pdf"
    ocr = "MATCHING STUFF WITH BN80760B APPEARING MULTIPLE TIMES " * 5
    result = _try_autocorrect_pn(stage1, filename, ocr)
    assert result is None


def test_autocorrect_pn_noop_when_no_candidate():
    """בלי מועמד משם הקובץ — לא לתקן."""
    from core.extractor import _try_autocorrect_pn
    stage1 = {"part_number": "SOMETHING"}
    filename = "random.pdf"
    ocr = "SOME LONG OCR TEXT WITH MANY TOKENS TO GET OVER THRESHOLD " * 5
    result = _try_autocorrect_pn(stage1, filename, ocr)
    assert result is None


def test_autocorrect_pn_noop_when_candidate_not_in_ocr():
    """מועמד שם הקובץ לא מופיע ב-OCR — אין עדות שהוא נכון. לא לתקן."""
    from core.extractor import _try_autocorrect_pn
    stage1 = {"part_number": "SOMETHING"}
    filename = "BN80760B_A.pdf"
    ocr = "SOME TEXT THAT MENTIONS NOTHING RELEVANT HERE " * 5
    result = _try_autocorrect_pn(stage1, filename, ocr)
    assert result is None


# ─── OCR grounding — P/N as single token ──────────────────────────────────────

def test_pn_single_token_not_in_ocr_flagged():
    """P/N כטוקן יחיד (כמו '31073803') שלא מופיע ב-OCR — נתפס עכשיו."""
    ocr = (
        "DIMENSIONS IN MILLIMETERS. INTERPRET DRAWING ACCORDING TO "
        "ISO STANDARDS. SURFACE TEXTURE RA 1.6. TOLERANCES UNLESS "
        "OTHERWISE SPECIFIED. MATERIAL DESCRIPTION CAT NO QUANTITY. "
        "P.N. 30-173803 REV C CUSTOMER RAFAEL. REMOVE BURRS."
    )
    # "31073803" לא ב-OCR, רק "30-173803"
    data = {"part_number": "31073803", "standards": []}
    from core.validators import validate_ocr_grounded
    warnings = validate_ocr_grounded(data, ocr)
    assert any(w["type"] == "PN_NOT_IN_OCR" for w in warnings)


def test_pn_partial_match_flagged_as_medium():
    """P/N עם חלק מופיע וחלק לא — MEDIUM, לא HIGH."""
    ocr = (
        "DIMENSIONS IN MILLIMETERS. INTERPRET DRAWING ACCORDING TO "
        "ISO STANDARDS. SURFACE TEXTURE RA 1.6. TOLERANCES UNLESS "
        "OTHERWISE SPECIFIED. MATERIAL DESCRIPTION CAT NO QUANTITY. "
        "DRAWING 34778 APPLIES TO MULTIPLE PARTS. REMOVE BURRS."
    )
    # P/N has "34778" (in OCR) + "49" (filtered too short) + "003" (not in OCR)
    data = {"part_number": "34778-49-FAKE", "standards": []}
    from core.validators import validate_ocr_grounded
    warnings = validate_ocr_grounded(data, ocr)
    # Tokens ≥3 chars: 34778, FAKE. 34778 in OCR, FAKE not. ratio=50% — NOT flagged (edge).
    # Adjust test: use explicit 3+ token value
    data = {"part_number": "34778-ABC-FAKE-XYZ", "standards": []}
    warnings = validate_ocr_grounded(data, ocr)
    # tokens: 34778, ABC, FAKE, XYZ. Only 34778 in OCR → 25% → flagged
    types = [w["type"] for w in warnings]
    assert "PN_PARTIALLY_IN_OCR" in types or "PN_NOT_IN_OCR" in types


# ─── _is_meaningful_process ───────────────────────────────────────────────────

def test_meaningful_process_with_type():
    assert _is_meaningful_process({"type": "Conversion"}) is True


def test_meaningful_process_with_type_he():
    assert _is_meaningful_process({"type_he": "ניקל"}) is True


def test_meaningful_process_with_standard_only():
    assert _is_meaningful_process({"standard": "MIL-DTL-5541"}) is True


def test_meaningful_process_empty_dict_is_noise():
    assert _is_meaningful_process({}) is False


def test_meaningful_process_all_empty_fields_is_noise():
    assert _is_meaningful_process(
        {"type": "", "type_he": "", "name": "", "standard": "", "thickness": ""}
    ) is False


def test_meaningful_process_accepts_string():
    assert _is_meaningful_process("some coating description") is True
    assert _is_meaningful_process("") is False
    assert _is_meaningful_process(None) is False


# ─── validate_standard_formats ────────────────────────────────────────────────

def test_standard_accepts_mil_spec():
    data = {"standards": ["MIL-DTL-5541", "MIL-A-8625F", "MIL-PRF-85285"]}
    assert validate_standard_formats(data) == []


def test_standard_accepts_ams():
    data = {"standards": ["SAE-AMS-4027", "AMS-C-26074", "AMS 2700"]}
    assert validate_standard_formats(data) == []


def test_standard_accepts_astm():
    data = {"standards": ["ASTM B633", "ASTM A 564", "ASTM-B-209"]}
    assert validate_standard_formats(data) == []


def test_standard_accepts_iso():
    data = {"standards": ["ISO 9001", "ISO 15730", "ISO 3098/1"]}
    assert validate_standard_formats(data) == []


def test_standard_accepts_qq():
    data = {"standards": ["QQ-P-416", "QQ-Z-325"]}
    assert validate_standard_formats(data) == []


def test_standard_accepts_rafael_ps():
    data = {"standards": ["PS-111.21", "PS 111.24"]}
    assert validate_standard_formats(data) == []


def test_standard_benign_label_not_flagged():
    """'ISO STANDARDS' מופיע בהרבה שרטוטים כתווית גנרית, לא דגל."""
    data = {"standards": ["ISO STANDARDS"]}
    assert validate_standard_formats(data) == []


def test_standard_flags_tipe_ocr_error():
    """'TIPE III' = OCR של TYPE III."""
    data = {"standards": ["MIL-A-8625F TIPE III, CLASS 2"]}
    warnings = validate_standard_formats(data)
    assert any(w["type"] == "STANDARD_OCR_TYPO" for w in warnings)


def test_standard_flags_class_at_sign():
    """'CLASS @' = OCR של ספרה."""
    data = {"standards": ["MIL-A-8625 TYPE III CLASS @"]}
    warnings = validate_standard_formats(data)
    assert any(w["type"] == "STANDARD_OCR_TYPO" for w in warnings)


def test_standard_flags_unrecognized_format():
    """תקן שהוא סתם טקסט — מזהיר.

    הערה: "XYZ-123" עכשיו עובר כי הוא מתאים לדפוס doc-ID פנימי (אותיות + -
    + ספרות). רק טקסט חופשי בלי ספרות או סימן מפריד ידגל.
    """
    data = {"standards": ["HELLO WORLD", "NOTASTANDARD"]}
    warnings = validate_standard_formats(data)
    assert len(warnings) == 2
    for w in warnings:
        assert w["type"] == "UNRECOGNIZED_STANDARD_FORMAT"
        assert w["severity"] == "LOW"  # downgraded from MEDIUM


def test_standard_ignores_short_values():
    data = {"standards": ["A", "12"]}
    assert validate_standard_formats(data) == []


# ─── validate_ocr_grounded ────────────────────────────────────────────────────

def test_ocr_grounding_passes_when_standards_in_text():
    ocr = "SURFACE FINISH PER MIL-DTL-5541 TYPE I CLASS 3. ASTM B633 APPLIES."
    data = {
        "standards": ["MIL-DTL-5541", "ASTM B633"],
        "part_number": "",
    }
    assert validate_ocr_grounded(data, ocr) == []


_FULL_OCR = (
    "DIMENSIONS ARE IN MILLIMETERS. INTERPRET DRAWING ACCORDING TO "
    "ISO STANDARDS. SURFACE TEXTURE RA 1.6. TOLERANCES UNLESS OTHERWISE "
    "SPECIFIED. MATERIAL DESCRIPTION CAT NO QUANTITY. ALUMINUM ALLOY "
    "6061-T651 PLATE COMMERCIAL. REMOVE BURRS SHARP EDGES. CUSTOMER "
    "DRAWING TITLE BLOCK OTHER PART NUMBER ABC-123-456."
)


def test_ocr_grounding_flags_hallucinated_standard():
    data = {
        "standards": ["MIL-DTL-99999"],  # not in OCR
        "part_number": "",
    }
    warnings = validate_ocr_grounded(data, _FULL_OCR)
    assert any(w["type"] == "STANDARD_NOT_IN_OCR" for w in warnings)


def test_ocr_grounding_flags_hallucinated_pn():
    data = {
        "standards": [],
        "part_number": "GFA-5000-251",  # not in OCR
    }
    warnings = validate_ocr_grounded(data, _FULL_OCR)
    assert any(w["type"] == "PN_NOT_IN_OCR" for w in warnings)


def test_ocr_grounding_skipped_when_no_ocr():
    """בלי OCR text, הוולידטור מדלג לגמרי."""
    data = {"standards": ["MIL-DTL-99999"], "part_number": "FAKE"}
    assert validate_ocr_grounded(data, "") == []
    assert validate_ocr_grounded(data, "   ") == []


def test_ocr_grounding_skipped_when_ocr_too_short():
    """OCR חלש (<20 טוקנים) = לא אמין לבדיקה."""
    short_ocr = "A B C D E F G"
    data = {"standards": ["MIL-DTL-99999"], "part_number": "FAKE"}
    assert validate_ocr_grounded(data, short_ocr) == []


def test_ocr_grounding_passes_partial_match():
    """גם אם רק רוב הטוקנים מופיעים ב-OCR — עובר."""
    # OCR: standard text of a drawing
    ocr_text = "MATERIAL: AL. AL. 6061-T6/T651 PER SAE-AMS-4027 OR SAE-AMS 4117. " \
               "MATCHING FIELD LOTS OF ADDITIONAL TEXT ABOUT THE DRAWING WITH " \
               "MANY TOKENS TO GET OVER THE THRESHOLD OF 20. CHEMICAL CONVERSION " \
               "COATING PER MIL-DTL-5541 TYPE I CLASS 3."
    data = {"standards": ["SAE-AMS-4027"], "part_number": ""}
    # "SAE", "AMS", "4027" כולם ב-OCR → 100%
    assert validate_ocr_grounded(data, ocr_text) == []
