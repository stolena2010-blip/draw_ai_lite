"""
Unit tests ל-master_matcher.

הרצה:
    pytest tests/ -v
"""
import pandas as pd
import pytest

from core.master_matcher import (
    STATUS_FULL,
    STATUS_NA,
    STATUS_NONE,
    STATUS_PARTIAL,
    _classify_rohs,
    _classify_standards_match,
    _classify_thickness_match,
    _classify_type_match,
    _collect_coating_codes,
    _collect_coating_types,
    _compound_label,
    _dedupe_matches,
    _detect_color,
    _detect_phosphorus_level,
    _detect_primary_type,
    _detect_type,
    _extract_std_codes,
    _extract_thickness_range,
    _extract_type_class,
    _master_covers_types,
    _ranges_overlap,
    _score_master,
    build_match_details,
    find_compound_masters,
    match_all_coatings,
)


# ─────────────────────────────────────────────
# _detect_type
# ─────────────────────────────────────────────
class TestDetectType:
    def test_zinc_english(self):
        assert _detect_type("ZINC PLATING") == "zinc"

    def test_zinc_hebrew(self):
        assert _detect_type("ציפוי אבץ") == "zinc"

    def test_electroless_nickel_priority(self):
        # electroless_nickel חייב להיתפס לפני nickel הרגיל
        assert _detect_type("ELECTROLESS NICKEL") == "electroless_nickel"

    def test_hard_anodize_priority(self):
        assert _detect_type("HARD ANODIZE TYPE III") == "hard_anodize"

    def test_conversion_aliases(self):
        assert _detect_type("ALODINE") == "conversion"
        assert _detect_type("CHEM FILM") == "conversion"
        assert _detect_type("IRIDITE") == "conversion"

    def test_no_match(self):
        assert _detect_type("RANDOM TEXT") is None


# ─────────────────────────────────────────────
# _detect_color
# ─────────────────────────────────────────────
class TestDetectColor:
    def test_blue_white_equivalents(self):
        assert _detect_color("NATURAL CHROMATE") == "blue_white"
        assert _detect_color("CLEAR ZINC") == "blue_white"
        assert _detect_color("BLUE/WHITE") == "blue_white"

    def test_yellow(self):
        assert _detect_color("YELLOW CHROMATE") == "yellow"

    def test_hebrew_yellow(self):
        assert _detect_color("צהוב") == "yellow"


# ─────────────────────────────────────────────
# _detect_phosphorus_level
# ─────────────────────────────────────────────
class TestPhosphorusLevel:
    def test_high_phosphor(self):
        assert _detect_phosphorus_level("HIGH PHOSPHOR") == "high"

    def test_low_phosphor(self):
        assert _detect_phosphorus_level("LOW PHOSPHOR") == "low"

    def test_requires_phosphor_keyword(self):
        # "HIGH" לבד לא מספיק
        assert _detect_phosphorus_level("HIGH QUALITY") is None

    def test_medium_variants(self):
        assert _detect_phosphorus_level("MEDIUM PHOSPHOR") == "medium"
        assert _detect_phosphorus_level("MED PHOSPHOR") == "medium"


# ─────────────────────────────────────────────
# _extract_std_codes
# ─────────────────────────────────────────────
class TestStdCodes:
    def test_mil_codes(self):
        codes = _extract_std_codes("MIL-A-8625 Type II Class 1")
        assert "MILA8625" in codes

    def test_astm_codes(self):
        codes = _extract_std_codes("ASTM B633 Class 1A")
        assert "ASTMB633" in codes

    def test_version_letter_stripped(self):
        # AMS-C-26074D → AMSC26074 (ללא אות גרסה)
        codes = _extract_std_codes("AMS-C-26074D")
        assert "AMSC26074" in codes


# ─────────────────────────────────────────────
# _extract_type_class
# ─────────────────────────────────────────────
class TestTypeClass:
    def test_extract_type(self):
        tc = _extract_type_class("Type II Class 1A")
        assert "TYPEII" in tc
        assert "CLASS1A" in tc

    def test_grade(self):
        tc = _extract_type_class("Grade B")
        assert "GRADEB" in tc


# ─────────────────────────────────────────────
# _extract_thickness_range
# ─────────────────────────────────────────────
class TestThicknessRange:
    def test_range_microns(self):
        r = _extract_thickness_range("5-10 mic")
        assert r == (5.0, 10.0)

    def test_single_value_with_tolerance(self):
        # 15µm ± 15% = (12.75, 17.25)
        r = _extract_thickness_range("15 microns")
        assert r is not None
        assert 12 < r[0] < 14
        assert 16 < r[1] < 18

    def test_no_match(self):
        assert _extract_thickness_range("no numbers") is None


# ─────────────────────────────────────────────
# _ranges_overlap
# ─────────────────────────────────────────────
class TestRangesOverlap:
    def test_full_overlap(self):
        assert _ranges_overlap((5, 10), (5, 10)) == 1.0

    def test_no_overlap(self):
        assert _ranges_overlap((5, 10), (20, 30)) == 0.0

    def test_partial_overlap(self):
        # חפיפה > 0
        result = _ranges_overlap((5, 10), (8, 13))
        assert result > 0.0
        assert result < 1.0


# ─────────────────────────────────────────────
# _score_master — בדיקות אינטגרציה
# ─────────────────────────────────────────────
class TestScoreMaster:
    def test_exact_match_high_score(self):
        coating = {
            "type": "Zinc",
            "name": "Zinc plating blue/white",
            "standard": "ASTM B633 Type II Class 1",
            "thickness": "5-10 microns",
            "rohs": True,
        }
        master = pd.Series({
            "desc": "BLUE/WHITE ZINC-RoHS",
            "standard": "ASTM B633 Type II Class 1",
            "thickness": "5-10 mic",
        })
        score, _ = _score_master(coating, master)
        # התאמה מלאה צריכה לתת ציון גבוה
        assert score > 80

    def test_different_type_penalty(self):
        coating = {
            "type": "Zinc",
            "name": "Zinc plating",
            "standard": "ASTM B633",
        }
        master = pd.Series({
            "desc": "NICKEL PLATING",
            "standard": "QQ-N-290",
            "thickness": "",
        })
        score, _ = _score_master(coating, master)
        # סוגים שונים → ציון נמוך / שלילי
        assert score < 20


# ─────────────────────────────────────────────
# Compound matching (Silver over Nickel וכו')
# ─────────────────────────────────────────────
class TestDetectPrimaryType:
    """הגנה מפני false-positive כש-name מכיל תיאור של שכבה אחרת."""

    def test_silver_coating_with_nickel_in_description(self):
        """ציפוי כסף שה-name שלו מציין 'OVER ELECTROLESS NICKEL' — צריך להיות silver, לא electroless_nickel."""
        silver = {
            "type": "Silver Plating",
            "type_he": "כסף",
            "name": "ELECTROLYTIC SILVER PLATING, 3-5 μm THICK, OVER "
                    "HIGH PHOSPHOROUS ELECTROLESS NICKEL, 3-5μm THICK PER PS-111.21",
            "standard": "PS-111.21",
        }
        assert _detect_primary_type(silver) == "silver"

    def test_electroless_nickel_detected_normally(self):
        en = {
            "type": "Electroless Nickel",
            "type_he": "ניקל אלקטרולס",
            "name": "HIGH PHOSPHOROUS ELECTROLESS NICKEL, 3-5μm THICK PER PS-111.21",
        }
        assert _detect_primary_type(en) == "electroless_nickel"

    def test_hebrew_silver_label(self):
        assert _detect_primary_type({"type_he": "כסף"}) == "silver"

    def test_hebrew_gold_label(self):
        assert _detect_primary_type({"type_he": "זהב"}) == "gold"

    def test_fallback_to_full_text_when_type_empty(self):
        """אם type/type_he ריקים — נופל חזרה לסריקת טקסט מלא."""
        coat = {"type": "", "type_he": "", "name": "ZINC PLATING"}
        assert _detect_primary_type(coat) == "zinc"


class TestCompoundHelpers:
    def test_collect_types_multiple(self):
        coats = [
            {"type": "Silver Plating"},
            {"type": "Electroless Nickel High Phosphorus"},
        ]
        assert _collect_coating_types(coats) == {"silver", "electroless_nickel"}

    def test_collect_types_single_ignored(self):
        coats = [{"type": "Zinc Plating"}]
        assert _collect_coating_types(coats) == {"zinc"}

    def test_collect_codes_merges(self):
        coats = [
            {"standard": "ASTM B700-20 PS-111.21"},
            {"standard": "MIL-C-26074 PS-111.21"},
        ]
        codes = _collect_coating_codes(coats)
        # PS111.21 + ASTMB700 + MILC26074
        assert len(codes) >= 3

    def test_master_covers_types_all(self):
        covered = _master_covers_types(
            "SILVER OVER ELECTROLESS NICKEL",
            {"silver", "electroless_nickel"},
        )
        assert covered == {"silver", "electroless_nickel"}

    def test_master_covers_types_partial(self):
        covered = _master_covers_types(
            "SILVER PLATING ONLY",
            {"silver", "electroless_nickel"},
        )
        # מכסה רק silver — לא עונה על הדרישה המלאה
        assert covered == {"silver"}

    def test_compound_label_english_and_hebrew(self):
        coats = [
            {"type": "Silver Plating", "type_he": "כסף"},
            {"type": "Electroless Nickel", "type_he": "ניקל אלקטרולס"},
        ]
        en, he = _compound_label(coats)
        assert "Silver" in en and "Nickel" in en
        assert "over" in en
        assert "כסף" in he and "ניקל" in he


class TestFindCompoundMasters:
    """בדיקות שדורשות Masters.xlsx אמיתי."""

    def test_silver_over_electroless_nickel_finds_compound(self):
        """המקרה מהשרטוט BH07784A — אמור למצוא מאסטרים רלוונטיים."""
        coats = [
            {"type": "Silver Plating", "thickness": "3-5 micron",
             "standard": "PS-111.21 ASTM B700-20"},
            {"type": "Electroless Nickel High Phosphorus",
             "thickness": "3-5 micron", "standard": "PS-111.21 MIL-C-26074"},
        ]
        matches = find_compound_masters(coats, top_n=5)
        assert len(matches) > 0, "compound masters should be found"
        # המאסטר הראשון אמור לכסות גם כסף וגם ניקל
        top = matches[0]
        assert "silver" in top["covers_types"]
        assert "electroless_nickel" in top["covers_types"]

    def test_single_type_returns_empty(self):
        coats = [{"type": "Zinc Plating", "thickness": "8 micron",
                  "standard": "ASTM B633"}]
        assert find_compound_masters(coats) == []

    def test_two_same_types_returns_empty(self):
        coats = [
            {"type": "Zinc Clear", "standard": "ASTM B633"},
            {"type": "Zinc Black", "standard": "ASTM B633"},
        ]
        # שני ציפויי אבץ = 1 סוג → לא compound
        assert find_compound_masters(coats) == []


class TestMatchAllCoatingsCompound:
    """end-to-end בדיקות של match_all_coatings עם לוגיקת compound."""

    def test_compound_case_returns_single_merged_entry(self):
        coats = [
            {"type": "Silver Plating", "type_he": "כסף",
             "thickness": "3-5 micron", "standard": "PS-111.21 ASTM B700-20"},
            {"type": "Electroless Nickel High Phosphorus", "type_he": "ניקל אלקטרולס",
             "thickness": "3-5 micron", "standard": "PS-111.21 MIL-C-26074"},
        ]
        result = match_all_coatings(coats, top_n=3)
        assert len(result) == 1
        assert result[0]["kind"] == "compound_coating"
        assert result[0]["coating"]["compound"] is True
        assert "layers" in result[0]["coating"]
        assert len(result[0]["coating"]["layers"]) == 2

    def test_single_coating_unchanged(self):
        coats = [{"type": "Zinc Plating", "thickness": "8 micron",
                  "standard": "ASTM B633", "rohs": True}]
        result = match_all_coatings(coats, top_n=3)
        assert len(result) == 1
        assert result[0]["kind"] == "coating"
        assert "compound" not in result[0]["coating"] or \
               result[0]["coating"].get("compound") is not True

    def test_bh07784a_drawing_bug_regression(self):
        """הרגרסיה מהשרטוט BH07784A: Silver OVER EN High P — צריך להחזיר compound.

        הבאג שמופיע כשה-name של הציפוי העליון (Silver) מכיל את תיאור
        השכבה התחתונה (ELECTROLESS NICKEL). לפני התיקון — שני הציפויים
        זוהו כ-electroless_nickel וה-compound matcher לא הופעל.
        """
        silver = {
            "type": "Silver Plating",
            "type_he": "כסף",
            "name": "ELECTROLYTIC SILVER PLATING, 3-5 μm THICK, OVER "
                    "HIGH PHOSPHOROUS ELECTROLESS NICKEL, 3-5μm THICK "
                    "PER PS-111.21 (RAFDOCS-434847)",
            "standard": "PS-111.21 (RAFDOCS-434847)",
            "thickness": "3-5 μm",
        }
        en = {
            "type": "Electroless Nickel",
            "type_he": "ניקל אלקטרולס",
            "name": "HIGH PHOSPHOROUS ELECTROLESS NICKEL, 3-5μm THICK "
                    "PER PS-111.21 (RAFDOCS-434847)",
            "standard": "PS-111.21 (RAFDOCS-434847)",
            "thickness": "3-5 μm",
        }
        result = match_all_coatings([silver, en], top_n=3)
        assert len(result) == 1
        assert result[0]["kind"] == "compound_coating"
        # הראשון צריך להיות Silver over Electroless Nickel (ms.1101)
        top = result[0]["matches"][0]
        assert "silver" in top["covers_types"]
        assert "electroless_nickel" in top["covers_types"]
        # לא אמור להיות ms.2805 (רק Electroless Nickel — לא מכסה Silver)
        assert top["master_id"] != "ms.2805"


class TestDedupeMatches:
    def test_same_master_across_coatings_deduped(self):
        entry1 = {
            "coating": {"type": "A"}, "kind": "coating",
            "matches": [{"master_id": "ms.100", "score": 50},
                        {"master_id": "ms.200", "score": 40}],
        }
        entry2 = {
            "coating": {"type": "B"}, "kind": "coating",
            "matches": [{"master_id": "ms.100", "score": 30},  # duplicate, lower score
                        {"master_id": "ms.300", "score": 45}],
        }
        cleaned = _dedupe_matches([entry1, entry2])
        all_ids = []
        for e in cleaned:
            for m in e["matches"]:
                all_ids.append(m["master_id"])
        # ms.100 צריך להופיע פעם אחת בלבד
        assert all_ids.count("ms.100") == 1
        # והציון המוצג צריך להיות הגבוה יותר
        for e in cleaned:
            for m in e["matches"]:
                if m["master_id"] == "ms.100":
                    assert m["score"] == 50

    def test_empty_list(self):
        assert _dedupe_matches([]) == []

    def test_no_duplicates_preserves_all(self):
        entry1 = {"coating": {"type": "A"}, "kind": "coating",
                  "matches": [{"master_id": "ms.1", "score": 50}]}
        entry2 = {"coating": {"type": "B"}, "kind": "coating",
                  "matches": [{"master_id": "ms.2", "score": 40}]}
        cleaned = _dedupe_matches([entry1, entry2])
        assert len(cleaned) == 2


# ─────────────────────────────────────────────
# Match Details (פירוט התאמה להצגה ב-UI)
# ─────────────────────────────────────────────
class TestClassifyTypeMatch:
    def test_identical_types_full(self):
        assert _classify_type_match("silver", "silver")["status"] == STATUS_FULL

    def test_close_types_partial(self):
        assert _classify_type_match("nickel", "electroless_nickel")["status"] == STATUS_PARTIAL

    def test_different_types_none(self):
        assert _classify_type_match("silver", "zinc")["status"] == STATUS_NONE

    def test_missing_coat_type_na(self):
        assert _classify_type_match(None, "silver")["status"] == STATUS_NA


class TestClassifyStandards:
    def test_full_match_no_extras(self):
        r = _classify_standards_match({"PS111.21"}, {"PS111.21"})
        assert r["status"] == STATUS_FULL

    def test_partial_when_master_has_extras(self):
        r = _classify_standards_match({"PS111.21"}, {"PS111.21", "X1", "X2"})
        assert r["status"] == STATUS_PARTIAL
        assert "X1" in r["only_in_master"]

    def test_none_when_no_overlap(self):
        r = _classify_standards_match({"A"}, {"B"})
        assert r["status"] == STATUS_NONE

    def test_na_when_no_coat_codes(self):
        r = _classify_standards_match(set(), {"PS111.21"})
        assert r["status"] == STATUS_NA


class TestClassifyThickness:
    def test_full_on_high_overlap(self):
        r = _classify_thickness_match((3.0, 5.0), (3.0, 5.0))
        assert r["status"] == STATUS_FULL

    def test_partial_on_small_overlap(self):
        r = _classify_thickness_match((3.0, 5.0), (4.5, 10.0))
        assert r["status"] == STATUS_PARTIAL

    def test_none_when_no_overlap(self):
        r = _classify_thickness_match((3.0, 5.0), (10.0, 15.0))
        assert r["status"] == STATUS_NONE

    def test_na_when_no_coat_thickness(self):
        r = _classify_thickness_match(None, (3.0, 5.0))
        assert r["status"] == STATUS_NA


class TestClassifyRohs:
    def test_na_when_drawing_no_rohs(self):
        assert _classify_rohs(False, True)["status"] == STATUS_NA

    def test_full_when_both_rohs(self):
        assert _classify_rohs(True, True)["status"] == STATUS_FULL

    def test_none_when_drawing_wants_rohs_master_doesnt(self):
        assert _classify_rohs(True, False)["status"] == STATUS_NONE


class TestBuildMatchDetails:
    def test_all_criteria_present(self):
        coating = {
            "type": "Zinc Plating", "type_he": "אבץ",
            "standard": "ASTM B633", "thickness": "8 micron",
        }
        master = {
            "desc": "ZINC PLATING CHROMATE", "standard": "ASTM B633 TYPE II",
            "thickness": "5-10 micron", "full_name": "",
        }
        details = build_match_details(coating, master)
        assert "coating_type" in details
        assert "standards" in details
        assert "thickness" in details
        assert "rohs" in details

    def test_compound_layer_silver_in_compound_master(self):
        """Silver-layer של ms.1101 (Silver over EN) — עם is_compound_layer=True."""
        silver = {
            "type": "Silver Plating", "type_he": "כסף",
            "standard": "PS-111.21 ASTM B700-20", "thickness": "3-5 μm",
        }
        # ms.1101 master approximation
        master = {
            "desc": "Silver over Electroless Nickel High Phosphorus",
            "standard": "QQ-S-365 Type 2 Grade B+MIL C 26074 Class 1",
            "thickness": "10-15 mic", "full_name": "",
        }
        details = build_match_details(silver, master, is_compound_layer=True)
        # coating_type צריך להיות "מלא" כי המאסטר מכיל "SILVER"
        assert details["coating_type"]["status"] == STATUS_FULL
