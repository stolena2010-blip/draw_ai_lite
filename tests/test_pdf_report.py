"""
Smoke tests ל-storage.pdf_report — מוודא ש-build_batch_pdf יוצר קובץ
תקין עבור שרטוטים בודדים / מרובים / מקרי קצה.
"""
from __future__ import annotations

import pytest

from storage.pdf_report import _coating_match_key, build_batch_pdf


@pytest.fixture
def sample_drawing():
    return {
        "part_number": "BBLE12345",
        "drawing_number": "BBLE12345",
        "revision": "A",
        "customer": "RAFAEL",
        "material": "AL 6061-T6",
        "source_filename": "test.pdf",
        "process_summary_hebrew": "סיכום לבדיקה.",
        "notes": "Some notes",
        "coating_processes": [
            {
                "type_he": "ניקל אלקטרולס",
                "type": "Electroless Nickel",
                "standard": "ASTM B733",
                "thickness": "25um",
                "rohs": True,
            }
        ],
        "painting_processes": [],
        "standards": ["ASTM B733", "ISO 9001"],
        "master_matches": [
            {
                "coating": {
                    "type_he": "ניקל אלקטרולס",
                    "type": "Electroless Nickel",
                    "standard": "ASTM B733",
                    "thickness": "25um",
                },
                "matches": [
                    {
                        "master_id": "M0001",
                        "score": 85,
                        "desc": "Electroless Nickel HP",
                        "standard": "ASTM B733",
                        "thickness": "25um",
                    }
                ],
            }
        ],
    }


def test_coating_match_key_is_stable_across_dict_copies():
    """המפתח עובד גם על עותק של ה-dict (הסיבה שהחלפנו את id())."""
    coat = {"type_he": "ניקל", "type": "Nickel", "standard": "B733", "thickness": "25um"}
    assert _coating_match_key(coat) == _coating_match_key(dict(coat))


def test_coating_match_key_handles_empty_fields():
    assert _coating_match_key({}) == ("", "", "", "")
    assert _coating_match_key(None) == ("None", "", "", "")


def test_build_batch_pdf_single_drawing(sample_drawing, tmp_path):
    out = tmp_path / "single.pdf"
    result = build_batch_pdf([sample_drawing], out)
    assert result.exists()
    assert result.stat().st_size > 0
    # PyMuPDF PDFs always start with %PDF-
    assert result.read_bytes().startswith(b"%PDF-")


def test_build_batch_pdf_multiple_drawings(sample_drawing, tmp_path):
    drawings = [
        sample_drawing,
        {**sample_drawing, "part_number": "BBLE99999", "source_filename": "b.pdf"},
        {**sample_drawing, "part_number": "BBLE11111", "source_filename": "c.pdf"},
    ]
    out = tmp_path / "batch.pdf"
    result = build_batch_pdf(drawings, out)
    assert result.exists()
    assert result.read_bytes().startswith(b"%PDF-")


def test_build_batch_pdf_empty_list(tmp_path):
    """רשימה ריקה — צריך ליצור לפחות עמוד שער."""
    out = tmp_path / "empty.pdf"
    result = build_batch_pdf([], out)
    assert result.exists()
    assert result.read_bytes().startswith(b"%PDF-")


def test_master_lookup_works_after_dict_copy(sample_drawing, tmp_path):
    """
    מדמה round-trip דרך cache — הציפוי ב-master_matches יהיה עותק (id שונה)
    של הציפוי ב-coating_processes. באג קודם: id() lookup היה נכשל.
    """
    import copy
    d = copy.deepcopy(sample_drawing)
    # עכשיו coating_processes[0] ו-master_matches[0]["coating"] הם שני אובייקטים שונים
    assert id(d["coating_processes"][0]) != id(d["master_matches"][0]["coating"])
    # אבל build_batch_pdf צריך עדיין לשייך ביניהם נכון
    out = tmp_path / "roundtrip.pdf"
    result = build_batch_pdf([d], out)
    assert result.exists()
    # Sanity — הקובץ לא ריק
    assert result.stat().st_size > 1000
