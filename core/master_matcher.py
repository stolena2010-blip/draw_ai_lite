"""
Masters matcher — מציאת התאמת מאסטרים לציפויי השרטוט.

קובץ Masters.xlsx מכיל ~1239 מאסטרים, כל אחד עם:
  - master_id (ms.X)
  - desc (תיאור באנגלית, למשל "BLUE/WHITE ZINC-RoHS")
  - standard (תקן עם Type/Class/Grade)
  - thickness (טווח עובי, למשל "5-10 mic")
  - color, rohs

כל ציפוי בשרטוט מוערך מול כל המאסטרים, ומוחזרים top-3 התאמות הכי גבוהות.
"""
from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

# קריאה ממשתנה סביבה עם fallback לנתיב ברירת המחדל
def _get_masters_path() -> Path:
    """מחזיר את נתיב ה-Masters.xlsx הנוכחי (מ-runtime או מ-.env)."""
    try:
        from core.azure_client import get_masters_xlsx_path
        custom_path = get_masters_xlsx_path()
        if custom_path:
            return Path(custom_path).resolve()
    except (ImportError, Exception):
        pass
    
    env_path = os.getenv("MASTERS_XLSX_PATH", "").strip()
    if env_path:
        return Path(env_path).resolve()
    
    return Path(__file__).resolve().parent.parent / "Masters.xlsx"

MASTERS_PATH = _get_masters_path()


# ─── ציון התאמה ───
W_STANDARD = 30.0      # התאמת קוד תקן (MIL-C-5541, PS-111.21, ASTM B633 וכו')
W_STANDARD_EXTRA_PENALTY = -12.0  # קנס לכל תקן שמופיע במאסטר אך לא בשרטוט
W_TYPE_CLASS = 20.0    # Type/Class/Grade בתוך התקן
W_COATING_TYPE = 50.0  # סוג ציפוי (zinc, nickel, anodize, conversion) — הכי קריטי
W_COATING_TYPE_PENALTY = -30.0  # קנס כשסוגי הציפוי שונים לחלוטין
W_COLOR = 8.0          # צבע (NATURAL≡BLUE/WHITE)
W_THICKNESS = 15.0     # חפיפת טווח עובי
W_ROHS = 12.0          # תאימות RoHS — חשוב יותר
W_ROHS_PENALTY = -10.0 # קנס כשהשרטוט דורש RoHS אבל המאסטר לא תואם
W_PHOSPHORUS = 15.0    # התאמת רמת זרחן ב-Electroless Nickel (High/Medium/Low)
W_PHOSPHORUS_PENALTY = -10.0  # קנס כשרמת הזרחן הפוכה


_TYPE_KEYWORDS = {
    "zinc": ["ZINC", "ZINK", "אבץ"],
    "nickel": ["NICKEL", "ניקל"],
    "electroless_nickel": ["ELECTROLESS"],
    "anodize": ["ANODIZE", "ANODIC", "אנודייז"],
    "hard_anodize": ["HARD ANODIZE", "TYPE III ANOD"],
    "conversion": ["CONVERSION", "ALODINE", "CHEM FILM", "IRIDITE", "CHROMATE CONV", "תמורה"],
    "passivation": ["PASSIVAT", "פסיבציה"],
    "cadmium": ["CADMIUM"],
    "chrome": ["CHROME", "CHROMIUM", "כרום"],
    "tin": ["TIN PLAT", "בדיל"],
    "silver": ["SILVER", "כסף"],
    "gold": ["GOLD", "זהב"],
    "copper": ["COPPER", "נחושת"],
    "black_oxide": ["BLACK OXIDE", "BLACKENING"],
    "phosphate": ["PHOSPHATE"],
}

_COLOR_KEYWORDS = {
    "yellow": ["YELLOW", "צהוב"],
    # NATURAL ו-CLEAR בעולם ציפויי האבץ = BLUE/WHITE chromate (אותו ציפוי)
    "blue_white": ["BLUE/WHITE", "BLUE\\WHITE", "BLUE WHITE", "כחלבן",
                   "NATURAL", "CLEAR"],
    "blue": ["BLUE", "כחול"],
    "black": ["BLACK", "שחור"],
    "olive": ["OLIVE"],
    "green": ["GREEN", "ירוק"],
}


@lru_cache(maxsize=1)
def load_masters() -> pd.DataFrame:
    """טעינת קובץ המאסטרים פעם אחת ושמירה ב-cache."""
    masters_path = _get_masters_path()
    if not masters_path.exists():
        logger.warning("Masters.xlsx not found at %s", masters_path)
        return pd.DataFrame(
            columns=["master_id", "desc", "standard", "thickness", "color", "col5", "rohs", "full_name"]
        )
    df = pd.read_excel(masters_path)
    df.columns = ["master_id", "desc", "standard", "thickness", "color", "col5", "rohs", "full_name"]
    for c in df.columns:
        df[c] = df[c].astype(str).fillna("").replace({"nan": "", "None": ""})
    logger.info("Loaded %d masters from %s", len(df), masters_path)
    return df


# ─── עזרים לנירמול ───
_THICKNESS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)")
_TYPE_RE = re.compile(r"\bTYPE\s*[IVX0-9]+\b", re.IGNORECASE)
_CLASS_RE = re.compile(r"\bCLASS\s*[A-Z0-9]+\b", re.IGNORECASE)
_GRADE_RE = re.compile(r"\bGRADE\s*[A-Z0-9-]+\b", re.IGNORECASE)
_STD_CODE_RE = re.compile(
    r"\b(?:MIL[- ][A-Z]+[- ]?\d+[A-Z]?|"
    r"AMS[- ]?[A-Z]?[- ]?\d+[A-Z]?|"
    r"ASTM[- ]?[A-Z]?[- ]?\d+[A-Z]?|"
    r"QQ[- ]?[A-Z][- ]?\d+[A-Z]?|"
    r"FED[- ]STD[- ]?\d+|"
    r"PS[- ]?\d+(?:\.\d+)?|"
    r"RAFDOCS[- ]?\d+|"
    r"TILDOCS[- ]?#?\d+)\b",
    re.IGNORECASE,
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").upper()).strip()


def _extract_thickness_range(text: str) -> tuple[float, float] | None:
    """מחזיר (low, high) במיקרון מתוך טקסט עובי — או None."""
    if not text:
        return None
    t = str(text).lower()
    # נרמל יחידות
    mult = 1.0
    if "in" in t and "mic" not in t and "µ" not in t:
        # inches → microns
        mult = 25400.0
    elif "mm" in t:
        mult = 1000.0
    m = _THICKNESS_RE.search(t)
    if not m:
        return None
    if m.group(1) and m.group(2):
        lo = float(m.group(1)) * mult
        hi = float(m.group(2)) * mult
    else:
        v = float(m.group(3)) * mult
        lo = v * 0.85
        hi = v * 1.15
    return (lo, hi)


def _ranges_overlap(r1: tuple[float, float], r2: tuple[float, float]) -> float:
    """מחזיר ציון 0..1 לפי חפיפת טווחים."""
    lo = max(r1[0], r2[0])
    hi = min(r1[1], r2[1])
    if hi < lo:
        return 0.0
    overlap = hi - lo
    avg_span = ((r1[1] - r1[0]) + (r2[1] - r2[0])) / 2 or 1.0
    return min(1.0, overlap / avg_span)


def _detect_type(text: str) -> str | None:
    t = _norm(text)
    # סדר מבוקר — ארוכים קודם
    for key in ("electroless_nickel", "hard_anodize"):
        for kw in _TYPE_KEYWORDS[key]:
            if kw.upper() in t:
                return key
    for key, kws in _TYPE_KEYWORDS.items():
        if key in ("electroless_nickel", "hard_anodize"):
            continue
        for kw in kws:
            if kw.upper() in t:
                return key
    return None


def _detect_color(text: str) -> str | None:
    t = _norm(text)
    # blue_white קודם — כולל את הכינויים NATURAL ו-CLEAR (chromate שקוף = BLUE/WHITE)
    for kw in _COLOR_KEYWORDS["blue_white"]:
        if kw.upper() in t:
            return "blue_white"
    for key, kws in _COLOR_KEYWORDS.items():
        if key == "blue_white":
            continue
        for kw in kws:
            if kw.upper() in t:
                return key
    return None


def _detect_phosphorus_level(text: str) -> str | None:
    """מזהה רמת זרחן ב-Electroless Nickel: HIGH / MEDIUM / LOW."""
    t = _norm(text)
    # נדרש שתופיע גם המילה PHOSPHOR* כדי להבחין בהקשר
    if "PHOSPHOR" not in t:
        return None
    if "HIGH" in t:
        return "high"
    if "MEDIUM" in t or "MED " in t or "MID" in t:
        return "medium"
    if "LOW" in t:
        return "low"
    return None


def _extract_std_codes(text: str) -> set[str]:
    """מחזיר סט קודי תקן מנורמלים (ללא רווחים, ללא REV)."""
    codes = set()
    for m in _STD_CODE_RE.finditer(str(text or "")):
        c = m.group(0).upper().replace(" ", "").replace("-", "")
        # הסרת אות גרסה בודדת בסוף (כגון AMSC26074D → AMSC26074)
        # כך שהשרטוט "AMS-C-26074" יזוהה כזהה למאסטר "AMS-C-26074D".
        c = re.sub(r"(\d)[A-Z]$", r"\1", c)
        codes.add(c)
    return codes


def _extract_type_class(text: str) -> set[str]:
    """מחזיר סט {'TYPE2', 'CLASS1A', ...}."""
    out = set()
    for r in (_TYPE_RE, _CLASS_RE, _GRADE_RE):
        for m in r.finditer(str(text or "")):
            out.add(m.group(0).upper().replace(" ", ""))
    return out


def _coating_text(coating: dict) -> str:
    """אוסף את כל הטקסט הזמין על הציפוי."""
    return " ".join(
        str(coating.get(k, "") or "")
        for k in ("type", "type_he", "name", "standard", "thickness")
    )


# ─── ציון התאמה ───
def _score_master(coating: dict, master: pd.Series) -> tuple[float, dict]:
    """מחזיר (score, breakdown) להתאמה בין ציפוי בודד למאסטר בודד."""
    breakdown = {}
    score = 0.0

    coat_text = _coating_text(coating)
    master_text = f"{master['desc']} {master['standard']}"

    # 1. תקן — קודי MIL/ASTM/QQ/PS
    coat_codes = _extract_std_codes(coat_text)
    master_codes = _extract_std_codes(master_text)
    if coat_codes and master_codes:
        common = coat_codes & master_codes
        extra_in_master = master_codes - coat_codes  # תקנים שהמאסטר דורש אך אינם בשרטוט
        if common:
            ratio = len(common) / max(len(coat_codes), 1)
            s = W_STANDARD * ratio
            score += s
            breakdown["תקן"] = (s, ", ".join(sorted(common)))
        # קנס על תקנים נוספים במאסטר שאינם מופיעים בשרטוט —
        # לדוגמה: מאסטר "Tin over Electroless Nickel" עם תקן ASTM B545 (בדיל)
        # בשרטוט שיש בו רק תקן ניקל אלקטרולס. ללא קנס המאסטר היה מקבל
        # ציון מלא ולכן נבחר בטעות.
        if extra_in_master:
            penalty = W_STANDARD_EXTRA_PENALTY * len(extra_in_master)
            score += penalty
            breakdown["תקנים עודפים במאסטר"] = (
                penalty, ", ".join(sorted(extra_in_master))
            )

    # 2. Type/Class/Grade
    coat_tc = _extract_type_class(coat_text)
    master_tc = _extract_type_class(master_text)
    if coat_tc and master_tc:
        common_tc = coat_tc & master_tc
        if common_tc:
            ratio = len(common_tc) / max(len(coat_tc), 1)
            s = W_TYPE_CLASS * ratio
            score += s
            breakdown["Type/Class"] = (s, ", ".join(sorted(common_tc)))

    # 3. סוג ציפוי — הכי קריטי. ציפוי שונה לחלוטין → קנס שלילי שמסנן בפועל
    coat_type = _detect_type(coat_text)
    master_type = _detect_type(master_text)
    if coat_type and master_type:
        if coat_type == master_type:
            score += W_COATING_TYPE
            breakdown["סוג ציפוי"] = (W_COATING_TYPE, coat_type)
        elif (coat_type, master_type) in {("nickel", "electroless_nickel"), ("electroless_nickel", "nickel"),
                                          ("anodize", "hard_anodize"), ("hard_anodize", "anodize")}:
            score += W_COATING_TYPE * 0.5
            breakdown["סוג ציפוי (חלקי)"] = (W_COATING_TYPE * 0.5, f"{coat_type}~{master_type}")
        else:
            score += W_COATING_TYPE_PENALTY
            breakdown["סוג ציפוי שונה"] = (W_COATING_TYPE_PENALTY, f"{coat_type} vs {master_type}")
    elif coat_type and not master_type:
        # יש לנו סוג מזוהה לציפוי אבל לא במאסטר — הורדה קלה
        score -= 5.0

    # 4. צבע
    coat_color = _detect_color(coat_text)
    master_color = _detect_color(master_text)
    if coat_color and master_color and coat_color == master_color:
        score += W_COLOR
        breakdown["צבע"] = (W_COLOR, coat_color)

    # 5. עובי — חפיפת טווחים
    coat_thick = _extract_thickness_range(coating.get("thickness", "") or "") \
        or _extract_thickness_range(coat_text)
    master_thick = _extract_thickness_range(master["thickness"]) \
        or _extract_thickness_range(master["standard"])
    if coat_thick and master_thick:
        overlap = _ranges_overlap(coat_thick, master_thick)
        if overlap > 0:
            s = W_THICKNESS * overlap
            score += s
            breakdown["עובי"] = (s, f"{coat_thick[0]:.0f}-{coat_thick[1]:.0f} ↔ {master_thick[0]:.0f}-{master_thick[1]:.0f}µm")

    # 6. RoHS
    coat_rohs = bool(coating.get("rohs"))
    master_rohs = "ROHS" in _norm(master_text) or "RoHS" in str(master["desc"])
    if coat_rohs and master_rohs:
        score += W_ROHS
        breakdown["RoHS"] = (W_ROHS, "✓")
    elif coat_rohs and not master_rohs:
        # השרטוט מחייב RoHS — מאסטר ללא RoHS פחות מתאים
        score += W_ROHS_PENALTY
        breakdown["RoHS חסר"] = (W_ROHS_PENALTY, "drawing requires RoHS")

    # 7. רמת זרחן ב-Electroless Nickel (High/Medium/Low Phosphorus)
    coat_phos = _detect_phosphorus_level(coat_text)
    master_phos = _detect_phosphorus_level(master_text)
    if coat_phos and master_phos:
        if coat_phos == master_phos:
            score += W_PHOSPHORUS
            breakdown["רמת זרחן"] = (W_PHOSPHORUS, coat_phos)
        else:
            score += W_PHOSPHORUS_PENALTY
            breakdown["רמת זרחן שונה"] = (
                W_PHOSPHORUS_PENALTY, f"{coat_phos} vs {master_phos}"
            )

    return score, breakdown


def find_top_masters(coating: dict, top_n: int = 3, min_score: float = 15.0) -> list[dict]:
    """מציאת top_n מאסטרים מתאימים לציפוי בודד."""
    df = load_masters()
    if df.empty:
        return []

    scored = []
    for _, row in df.iterrows():
        score, breakdown = _score_master(coating, row)
        if score >= min_score:
            scored.append({
                "master_id": row["master_id"],
                "desc": row["desc"],
                "standard": row["standard"],
                "thickness": row["thickness"],
                "full_name": row["full_name"].replace("\\\\", " | ").replace("\\", " | "),
                "score": round(score, 1),
                "breakdown": breakdown,
                "match_details": build_match_details(coating, row),
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]


# ─── Match Details (פירוט התאמה להצגה ב-UI) ───
STATUS_FULL = "full"        # ✅ התאמה מלאה
STATUS_PARTIAL = "partial"  # 🟡 התאמה חלקית
STATUS_NONE = "none"        # ❌ ללא התאמה
STATUS_NA = "na"            # ⚪ לא רלוונטי / אין נתון


def _classify_type_match(coat_type: str | None, master_type: str | None) -> dict:
    """מסווג התאמת סוג ציפוי — Full/Partial/None/NA."""
    if not coat_type:
        return {"status": STATUS_NA, "reason": "לא זוהה סוג בשרטוט"}
    if not master_type:
        return {"status": STATUS_NA, "reason": "לא זוהה סוג במאסטר"}
    if coat_type == master_type:
        return {"status": STATUS_FULL, "coat": coat_type, "master": master_type}
    # סוגים קרובים (ניקל ~ ניקל אלקטרולס, אנודייז ~ הארד אנודייז)
    close_pairs = {
        ("nickel", "electroless_nickel"), ("electroless_nickel", "nickel"),
        ("anodize", "hard_anodize"), ("hard_anodize", "anodize"),
    }
    if (coat_type, master_type) in close_pairs:
        return {"status": STATUS_PARTIAL, "coat": coat_type, "master": master_type}
    return {"status": STATUS_NONE, "coat": coat_type, "master": master_type}


def _classify_layer_type_in_master(coat_type: str | None, master_text: str) -> dict:
    """
    לשכבה בודדת בתוך compound master — בודק אם המאסטר *מכיל* את סוג הציפוי
    (לא זהות מדויקת). לדוגמה: Silver-layer של ms.1101 "Silver over Electroless
    Nickel" → המאסטר מכיל SILVER → התאמה מלאה.
    """
    if not coat_type:
        return {"status": STATUS_NA, "reason": "לא זוהה סוג בשרטוט"}
    norm = _norm(master_text)
    for kw in _TYPE_KEYWORDS.get(coat_type, []):
        if kw.upper() in norm:
            return {
                "status": STATUS_FULL,
                "coat": coat_type,
                "note": "המאסטר מכיל את הסוג",
            }
    return {
        "status": STATUS_NONE,
        "coat": coat_type,
        "note": "המאסטר לא מכיל את הסוג",
    }


def _classify_standards_match(coat_codes: set[str], master_codes: set[str]) -> dict:
    """מסווג התאמת תקנים."""
    if not coat_codes and not master_codes:
        return {"status": STATUS_NA, "reason": "אין תקנים בשניהם",
                "matched": [], "only_in_master": [], "only_in_coat": []}
    if not coat_codes:
        return {"status": STATUS_NA, "reason": "אין תקנים בשרטוט",
                "matched": [], "only_in_master": sorted(master_codes), "only_in_coat": []}
    if not master_codes:
        return {"status": STATUS_NONE, "reason": "אין תקנים במאסטר",
                "matched": [], "only_in_master": [], "only_in_coat": sorted(coat_codes)}

    matched = coat_codes & master_codes
    only_coat = coat_codes - master_codes
    only_master = master_codes - coat_codes

    # מלא = כל תקני השרטוט נמצאו במאסטר, ואין "עודפים" רבים במאסטר
    if matched == coat_codes and len(only_master) <= 1:
        status = STATUS_FULL
    elif matched:
        status = STATUS_PARTIAL
    else:
        status = STATUS_NONE
    return {
        "status": status,
        "matched": sorted(matched),
        "only_in_coat": sorted(only_coat),
        "only_in_master": sorted(only_master),
    }


def _classify_thickness_match(coat_range: tuple | None,
                               master_range: tuple | None) -> dict:
    """מסווג התאמת עובי — רק אם יש עובי בשרטוט."""
    if not coat_range:
        return {"status": STATUS_NA, "reason": "אין עובי בשרטוט"}
    if not master_range:
        return {"status": STATUS_NA, "reason": "אין עובי במאסטר",
                "coat_range": coat_range}
    overlap = _ranges_overlap(coat_range, master_range)
    if overlap >= 0.7:
        status = STATUS_FULL
    elif overlap > 0:
        status = STATUS_PARTIAL
    else:
        status = STATUS_NONE
    return {
        "status": status,
        "coat_range": coat_range,
        "master_range": master_range,
        "overlap_pct": round(overlap * 100),
    }


def _classify_rohs(coat_rohs: bool, master_rohs: bool) -> dict:
    """מסווג התאמת RoHS — רק אם השרטוט דורש RoHS."""
    if not coat_rohs:
        return {"status": STATUS_NA, "reason": "RoHS לא דרוש בשרטוט"}
    if master_rohs:
        return {"status": STATUS_FULL, "note": "המאסטר תומך ב-RoHS"}
    return {"status": STATUS_NONE, "note": "השרטוט דורש RoHS, המאסטר לא"}


def _classify_phosphorus(coat_phos: str | None, master_phos: str | None) -> dict:
    """מסווג התאמת רמת זרחן ב-Electroless Nickel."""
    if not coat_phos:
        return {"status": STATUS_NA, "reason": "אין רמת זרחן בשרטוט"}
    if not master_phos:
        return {"status": STATUS_PARTIAL, "reason": "אין רמת זרחן במאסטר",
                "coat_phos": coat_phos}
    if coat_phos == master_phos:
        return {"status": STATUS_FULL, "coat_phos": coat_phos, "master_phos": master_phos}
    return {"status": STATUS_NONE, "coat_phos": coat_phos, "master_phos": master_phos}


def build_match_details(coating: dict, master, *, is_compound_layer: bool = False) -> dict:
    """
    בונה פירוט התאמה מוצלבת בין ציפוי למאסטר.

    Args:
        coating: dict של ציפוי השרטוט
        master: pandas.Series או dict (מ-cache)
        is_compound_layer: True אם זה שכבה בתוך compound master
            → בדיקת סוג תיעשה ע"י "האם המאסטר מכיל את הסוג" במקום זהות מדויקת.

    מחזיר dict עם 4-5 קריטריונים, לכל אחד:
      - status: "full" / "partial" / "none" / "na"
      - פרטים נוספים (ערכים שהושוו, מה התגלה)

    מיועד להצגה ב-UI — כל קריטריון מוצג עם אייקון וצבע לפי status.
    """
    # נרמל master ל-dict כך שנעבוד על שניהם באותה דרך
    if isinstance(master, dict):
        m_dict = master
    else:
        # pandas.Series
        m_dict = {
            "desc": str(master.get("desc", "") or ""),
            "standard": str(master.get("standard", "") or ""),
            "thickness": str(master.get("thickness", "") or ""),
            "full_name": str(master.get("full_name", "") or ""),
        }

    coat_text = _coating_text(coating)
    master_text = f"{m_dict.get('desc', '')} {m_dict.get('standard', '')} {m_dict.get('full_name', '')}"

    # 1. סוג ציפוי
    coat_type = _detect_primary_type(coating)
    if is_compound_layer:
        # בתוך compound — בדוק אם המאסטר מכיל את הסוג הזה
        type_match = _classify_layer_type_in_master(coat_type, master_text)
    else:
        master_type = _detect_type(master_text)
        type_match = _classify_type_match(coat_type, master_type)

    # 2. תקנים
    coat_codes = _extract_std_codes(coat_text)
    master_codes = _extract_std_codes(master_text)

    # 3. עובי (רק אם יש בשרטוט)
    coat_thick = (
        _extract_thickness_range(coating.get("thickness", "") or "")
        or _extract_thickness_range(coat_text)
    )
    master_thick = (
        _extract_thickness_range(m_dict.get("thickness", ""))
        or _extract_thickness_range(m_dict.get("standard", ""))
    )

    # 4. RoHS
    coat_rohs = bool(coating.get("rohs"))
    master_rohs = "ROHS" in _norm(master_text)

    # 5. רמת זרחן (רק ל-electroless nickel)
    coat_phos = _detect_phosphorus_level(coat_text)
    master_phos = _detect_phosphorus_level(master_text)

    details = {
        "coating_type": type_match,
        "standards": _classify_standards_match(coat_codes, master_codes),
        "thickness": _classify_thickness_match(coat_thick, master_thick),
        "rohs": _classify_rohs(coat_rohs, master_rohs),
    }

    # זרחן — רק אם רלוונטי (ציפוי מכיל electroless nickel)
    if coat_type == "electroless_nickel" or coat_phos:
        details["phosphorus"] = _classify_phosphorus(coat_phos, master_phos)

    return details


# ─── Compound matching (Silver over Nickel וכו') ───
_COMPOUND_KEYWORDS_RE = re.compile(r"\b(OVER|ON TOP|\+|PLUS)\b", re.IGNORECASE)

# בונוס לציפוי שמכסה את *כל* סוגי הציפוי בשרטוט
W_COMPOUND_COVERAGE = 50.0   # בונוס בסיס פר סוג שכוסה
W_COMPOUND_OVER_BONUS = 20.0  # מאסטר שמסומן במפורש "OVER/+"
MIN_COMPOUND_SCORE = 60.0    # סף לקבלת תוצאת compound כעיקרית


def _detect_primary_type(coating: dict) -> str | None:
    """
    מזהה את הסוג העיקרי של ציפוי — משתמש ב-type/type_he קודם, לא בטקסט המלא.

    חשוב: תיאור של "Silver OVER Electroless Nickel" מופיע לעיתים ב-name
    של הציפוי העליון (Silver). אם נסרוק את כל הטקסט, נחשוב בטעות
    שהציפוי הוא electroless_nickel (בגלל המילה "ELECTROLESS" בתיאור).
    לכן נבודד את זיהוי הסוג ל-type / type_he בלבד.
    """
    for field in ("type", "type_he"):
        text = str(coating.get(field) or "").strip()
        if text:
            t = _detect_type(text)
            if t:
                return t
    # fallback — סריקה מלאה (רק אם type/type_he ריקים)
    return _detect_type(_coating_text(coating))


def _collect_coating_types(coatings: list[dict]) -> set[str]:
    """אוסף את כל סוגי הציפוי שזוהו באוסף הציפויים.

    משתמש ב-_detect_primary_type — בודק type/type_he בלבד כדי להימנע
    משגיאות זיהוי כש-name מכיל תיאור של שכבה אחרת (Silver OVER Nickel).
    """
    types: set[str] = set()
    for c in coatings:
        if not isinstance(c, dict):
            continue
        t = _detect_primary_type(c)
        if t:
            types.add(t)
    return types


def _collect_coating_codes(coatings: list[dict]) -> set[str]:
    """אוסף את כל קודי התקן מאוסף הציפויים."""
    codes: set[str] = set()
    for c in coatings:
        if not isinstance(c, dict):
            continue
        codes.update(_extract_std_codes(_coating_text(c)))
    return codes


def _master_covers_types(master_text_norm: str, required_types: set[str]) -> set[str]:
    """מחזיר אילו סוגי ציפוי נמצאים בטקסט המאסטר (מתוך required_types)."""
    covered: set[str] = set()
    for t in required_types:
        for kw in _TYPE_KEYWORDS.get(t, []):
            if kw.upper() in master_text_norm:
                covered.add(t)
                break
    return covered


def _score_compound_master(coatings: list[dict], master: pd.Series,
                            required_types: set[str],
                            coat_codes: set[str]) -> tuple[float, dict]:
    """
    ציון מאסטר עבור מקרה של מספר ציפויים.

    קריטריונים:
    - המאסטר מכיל את *כל* סוגי הציפוי שמופיעים בשרטוט
    - המאסטר מסומן כ-compound (OVER/+/PLUS) — בונוס נוסף
    - התאמת קודי תקן
    """
    breakdown: dict = {}
    master_text = f"{master['desc']} {master['standard']} {master['full_name']}"
    master_norm = _norm(master_text)

    covered = _master_covers_types(master_norm, required_types)
    if covered != required_types:
        # לא מכסה את כל הסוגים — לא רלוונטי כ-compound
        return 0.0, {}

    score = W_COMPOUND_COVERAGE * len(required_types)
    breakdown["כיסוי סוגים"] = (score, ", ".join(sorted(required_types)))

    # בונוס למאסטר compound מפורש
    if _COMPOUND_KEYWORDS_RE.search(master_text):
        score += W_COMPOUND_OVER_BONUS
        breakdown["compound explicit"] = (W_COMPOUND_OVER_BONUS, "OVER/+")

    # התאמת תקנים
    master_codes = _extract_std_codes(master_text)
    if coat_codes and master_codes:
        common = coat_codes & master_codes
        if common:
            ratio = len(common) / max(len(coat_codes), 1)
            s = W_STANDARD * ratio
            score += s
            breakdown["תקן"] = (s, ", ".join(sorted(common)))

    # התאמת רמת זרחן (אם יש ניקל אלקטרולס בציפוי)
    for c in coatings:
        c_phos = _detect_phosphorus_level(_coating_text(c))
        if not c_phos:
            continue
        m_phos = _detect_phosphorus_level(master_text)
        if m_phos and c_phos == m_phos:
            score += W_PHOSPHORUS
            breakdown["רמת זרחן"] = (W_PHOSPHORUS, c_phos)
            break
        elif m_phos and c_phos != m_phos:
            score += W_PHOSPHORUS_PENALTY
            breakdown["רמת זרחן שונה"] = (W_PHOSPHORUS_PENALTY, f"{c_phos} vs {m_phos}")
            break

    # RoHS — אם כל הציפויים דורשים RoHS, המאסטר צריך לציין RoHS
    all_rohs = all(bool(c.get("rohs")) for c in coatings if isinstance(c, dict))
    master_rohs = "ROHS" in master_norm
    if all_rohs and master_rohs:
        score += W_ROHS
        breakdown["RoHS"] = (W_ROHS, "✓")
    elif all_rohs and not master_rohs:
        score += W_ROHS_PENALTY
        breakdown["RoHS חסר"] = (W_ROHS_PENALTY, "drawing requires RoHS")

    return score, breakdown


def find_compound_masters(coatings: list[dict], top_n: int = 3,
                           min_score: float = MIN_COMPOUND_SCORE) -> list[dict]:
    """
    מחפש מאסטרים שמכסים את כל סוגי הציפוי יחד (Silver over Nickel וכו').

    מתאים כשיש 2+ ציפויים שזוהו בשרטוט. מחזיר רשימה ריקה אם:
    - פחות מ-2 סוגי ציפוי זוהו
    - אין מאסטר שמכסה את כל הסוגים בציון מעל הסף
    """
    required_types = _collect_coating_types(coatings)
    if len(required_types) < 2:
        return []

    coat_codes = _collect_coating_codes(coatings)
    df = load_masters()
    if df.empty:
        return []

    scored = []
    for _, row in df.iterrows():
        score, breakdown = _score_compound_master(coatings, row, required_types, coat_codes)
        if score >= min_score:
            # פירוט התאמה לכל שכבה בנפרד (Silver, Electroless Nickel וכו')
            layer_details = []
            for c in coatings:
                if not isinstance(c, dict):
                    continue
                layer_type = _detect_primary_type(c)
                layer_details.append({
                    "layer": layer_type or "unknown",
                    "coating": c,
                    "details": build_match_details(c, row, is_compound_layer=True),
                })
            scored.append({
                "master_id": row["master_id"],
                "desc": row["desc"],
                "standard": row["standard"],
                "thickness": row["thickness"],
                "full_name": row["full_name"].replace("\\\\", " | ").replace("\\", " | "),
                "score": round(score, 1),
                "breakdown": breakdown,
                "covers_types": sorted(required_types),
                "layer_details": layer_details,
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]


def _compound_label(coatings: list[dict]) -> tuple[str, str]:
    """בונה תווית compound: ('Silver over Electroless Nickel', 'כסף מעל ניקל אלקטרולס')."""
    types_en = []
    types_he = []
    for c in coatings:
        if not isinstance(c, dict):
            continue
        en = (c.get("type") or c.get("name") or "").strip()
        he = (c.get("type_he") or "").strip()
        if en:
            types_en.append(en)
        if he:
            types_he.append(he)
    en_label = " over ".join(types_en) if types_en else ""
    he_label = " מעל ".join(types_he) if types_he else ""
    return en_label, he_label


def _dedupe_matches(per_coating_results: list[dict]) -> list[dict]:
    """
    מסיר כפילויות של master_id בין ציפויים שונים.
    שומר את ההתאמה עם הציון הגבוה ביותר לכל מאסטר.
    """
    # איתור הציון המקסימלי לכל master_id
    best_score: dict[str, float] = {}
    for entry in per_coating_results:
        for m in entry.get("matches", []) or []:
            mid = m.get("master_id")
            if mid is None:
                continue
            sc = float(m.get("score") or 0)
            if mid not in best_score or sc > best_score[mid]:
                best_score[mid] = sc

    seen: set[str] = set()
    cleaned = []
    for entry in per_coating_results:
        filtered = []
        for m in entry.get("matches", []) or []:
            mid = m.get("master_id")
            sc = float(m.get("score") or 0)
            # שמור את המופע המוביל של כל מאסטר פעם אחת בלבד
            if mid in seen:
                continue
            if mid in best_score and sc < best_score[mid]:
                # זו לא הגרסה הטובה ביותר — דלג
                continue
            seen.add(mid)
            filtered.append(m)
        if filtered:
            entry = {**entry, "matches": filtered}
            cleaned.append(entry)
    return cleaned


def match_all_coatings(coating_processes: list, painting_processes: list | None = None,
                        top_n: int = 3) -> list[dict]:
    """מחזיר רשימת התאמות לציפויי השרטוט.

    לוגיקה:
    1. אם יש 2+ ציפויים מסוגים שונים → ניסיון compound matching (Silver over Nickel וכו').
       אם נמצא מאסטר עם ציון >= MIN_COMPOUND_SCORE → מוחזר כתוצאה יחידה.
    2. אחרת (או אם compound נכשל) — התאמה לכל ציפוי בנפרד + dedupe של כפילויות.

    הערה: מאסטרים מתבצעים רק על coating_processes — לא על צביעות.
    הפרמטר painting_processes נשמר לתאימות לאחור.
    """
    coats = [c for c in (coating_processes or []) if isinstance(c, dict)]

    # ─── שלב 1: נסה compound matching ───
    if len(coats) >= 2:
        compound_matches = find_compound_masters(coats, top_n=top_n)
        if compound_matches:
            en_label, he_label = _compound_label(coats)
            return [{
                "coating": {
                    "type": en_label or "Compound Coating",
                    "type_he": he_label or "ציפוי מרובה-שכבות",
                    "compound": True,
                    "layers": coats,
                },
                "kind": "compound_coating",
                "matches": compound_matches,
            }]

    # ─── שלב 2: התאמה לכל ציפוי + dedupe ───
    results = []
    for coat in coats:
        matches = find_top_masters(coat, top_n=top_n)
        results.append({
            "coating": coat,
            "kind": "coating",
            "matches": matches,
        })
    return _dedupe_matches(results)
