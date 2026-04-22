"""
Prompts עבור שלבי החילוץ (מצב שרטוט בודד).

הפרומפטים מאוחסנים בקבצי טקסט תחת ``prompts/single/`` כדי לאפשר עריכה
ללא נגיעה בקוד. הקובץ הזה רק טוען אותם וחושף את אותם שמות קבועים שהיו
קיימים קודם, כך שאף קוד צרכן לא צריך להשתנות.

שימוש:
    from core.prompts import STAGE_1_PROMPT, STAGE_2_PROMPT, STAGE_3_PROMPT_TEMPLATE
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts" / "single"


@lru_cache(maxsize=None)
def _load(name: str) -> str:
    path = _PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"קובץ פרומפט חסר: {path}. ודא שתיקיית 'prompts/single/' קיימת."
        )
    return path.read_text(encoding="utf-8")


STAGE_1_PROMPT = _load("stage_1.txt")
STAGE_2_PROMPT = _load("stage_2.txt")
STAGE_3_PROMPT_TEMPLATE = _load("stage_3_template.txt")
"""
Prompts עבור שלבי החילוץ — גרסה משופרת בהשראת drawingai-pro.
"""

STAGE_1_PROMPT = """אתה מומחה לזיהוי מידע משרטוטים הנדסיים.

⚙️ כללי זהב:
- חלץ רק מידע שמופיע במפורש בטקסט/תמונה.
- העתק ערכים בדיוק כפי שכתובים (כולל אותיות גדולות/קטנות, מקפים, נקודות).
- אם שדה לא קיים — החזר מחרוזת ריקה "".
- אל תמציא ואל תנחש!

חלץ את השדות הבאים מ-TITLE BLOCK (בדרך כלל בפינה הימנית/שמאלית התחתונה):

1. part_number — מספר פריט / Part Number / P/N / PART NO. / CATALOG NO. / NAME CATALOG NO. / מק"ט
   ⚠️ אורך מינימלי: לרוב 5+ תווים. 3-4 תווים נדירים מאוד.
   ⚠️ DATE ≠ Part Number ("01.02.24" זה תאריך!)
   ⚠️ CAGE CODE ≠ Part Number ("0439A", "0B7R6", "E0B7R6" — אלו קודי CAGE בני 5-6 תווים, לא מספרי פריט!)
   ⚠️ ASSEMBLY NUMBER ≠ Part Number (אם השדה אומר "ASSEMBLY" — זה לא part_number)
   ⚠️ DRAWING NO. ≠ PART NO.! לדוגמה:
        P.N.:        FTL504038A     ← זה part_number
        DRAWING NO.: 8H-A53274      ← זה drawing_number (שונה!)
   ✅ חלץ רק משדה שמסומן: PART NO. / PART NUMBER / CATALOG NO. / NAME CATALOG NO. / P/N / מק"ט
   אם אין שדה כזה → החזר "".

2. revision — גרסה / REV / Rev. / REVISION

3. drawing_number — מספר שרטוט / DWG NO / Drawing No. / DRAWING NUMBER
   ⚠️ אסור לבלבל עם CAGE CODE / ASSEMBLY / CATALOG NO.
   ✅ דוגמאות תקפות: "DD6875I2-03", "22-2288-0101-00", "8H-A53274", "236668-4"
   חלץ רק מהתא שמסומן DWG NO / DRAWING NO. / DRAWING NUMBER.

4. customer — שם לקוח / Customer / Client / Company (חפש לוגו או שם חברה ב-Title Block).

5. material — חומר גלם / Material / MAT'L / MAT / Raw Material / חומר.
   ⚠️ ציין במפורש את סוג החומר אם רשום: אלומיניום, פלדה, נחושת, נירוסטה, פליז, טיטניום וכו'.
   העתק בדיוק כפי שכתוב, למשל: "AL 7075-T6", "STEEL 4140", "STAINLESS 316",
   "ALUMINUM ALLOY 6061-T651", "TI-6AL-4V", "ALUMINIUM ALLOY 5083 H111".
   חפש בכמה מקומות (לפי הסדר):
     א) ב-Title Block בשדה MATERIAL / MAT'L / SPEC.
     ב) ב-NOTES — בשורה שמתחילה ב-"MATERIAL ..." או "MATERIAL:"
        (למשל "4. MATERIAL ALUMINIUM ALLOY 5083 H111").
     ג) ב-SPECIFICATION / MATERIAL SPEC.
   אם אין — "".

החזר JSON בלבד (ללא טקסט נוסף):
{
  "part_number": "",
  "revision": "",
  "drawing_number": "",
  "customer": "",
  "material": ""
}

═══════════════════════════════════════════════════════════════
🔵 RAFAEL — הוראות ייעודיות (אם רואים את הלוגו / השם "RAFAEL")
═══════════════════════════════════════════════════════════════
ב-Title Block של רפאל יש 3 מספרים נפרדים — אסור לבלבל ביניהם:

   ┌─────────┬─────┬─────────────────────────┐
   │ CAT NO. │ DIM │  RAFAEL [logo]          │
   │ 5010921…│     │                         │
   ├─────────┼─────┼──────────┬──────────────┤
   │ QTY     │ UM  │ ID/SIGN  │ DATE         │
   ├─────────┴─────┤   ...                   │
   │PROCESS/TREAT. │                         │
   │               │  TITLE                  │
   │               │  ControlBox Housing     │
   │               ├──────────┬──────────────┤
   │               │ P.N.     │ SHT OF       │
   │               │ PWRL30512A│ 1  1        │
   ├────┬────┬─────┼──────────┴───┬──────────┤
   │SURF│SCAL│CLASS│ SIZE │DRAWING NO│ REV   │
   │TEXT│ 2:1│Uncl │ A1   │8H-A33448 │  A    │
   └────┴────┴─────┴──────┴──────────┴───────┘

🔴 כללי זהב לרפאל:
   • CAT NO.    — מספר קטלוג פנימי. ❌ אינו part_number ואינו drawing_number!
   • P.N.       — ✅ הוא ה-part_number (למשל: PWRL30512A, BBLE4352A, HLTA10872A,
                   FTLS02016A, BG58498A, BO33303A, RF21MP614).
   • DRAWING NO.— ✅ הוא ה-drawing_number (למשל: 8H-A33448, 8H-A19237, R00-A49880).
   • REV        — אות (A, B, C, D) בעמודה REV ליד DRAWING NO.
   • customer   — "RAFAEL".
   • material   — מהשדה MATERIAL בפינה השמאלית-עליונה של ה-Title Block,
                   למשל "ALUMINUM ALLOY 6061-T651 PLATES 1.125 INCH PER: SPEC. SAE-AMS-QQ-A-250/11".

⚠️ קריאה תו-אחר-תו (טעויות שכיחות):
   • "0" (אפס) ≠ "O" (אות) — מספרי שרטוט של רפאל המתחילים ב-R הם תמיד עם ספרות:
       R00-A49880 ✅,  R01-B23456 ✅,  R10-C88888 ✅
       ROO לעולם לא מופיע!
   • "B" ≠ "8",  "1" ≠ "I",  "0" ≠ "O",  "6" ≠ "8",  "5" ≠ "S",  "2" ≠ "Z".
   • 🔍 ספור את הספרות פעמיים ב-part_number ו-drawing_number של רפאל!
     מספרי P.N. של רפאל בפורמט BPxxxxxX או PWRLxxxxxX הם **באורך קבוע**:
       BP70689A  (7 תווים לפני האות) ≠ BP7069A (6 תווים).
     אם אתה לא בטוח באורך — קרא שוב את התא, אל תקצר!
   • הסתכל גם על השדה השני (DRAWING NO.) — לרוב P.N. ו-DRAWING NO. ברפאל
     **זהים לחלוטין** בשרטוטי חלק בודד. אם הם נראים שונים — בדוק שזה לא
     בגלל שספרת אחת לא נקראה.

⚠️ פורמט חלופי של רפאל (שרטוטים ישנים — ללא תאי P.N. / DRAWING NO. מסומנים):
   • מופיע מספר גדול ובולט באמצע הדף (4-6 ספרות), למשל "51033", "1402".
   • במקרה זה: part_number = drawing_number = אותו מספר.
   • REV ייקח מטבלת REVISIONS.

⛔ טעויות אסורות:
   ❌ part_number = CAT NO. (זו טעות קריטית!)
   ❌ part_number = DRAWING NO. או להפך (אלא אם הם באמת זהים בתאים שלהם)
   ❌ revision = SIZE (A1/A2/A3 הם גודל דף, לא גרסה!)
   ❌ להחזיר part_number ריק כש-P.N. ברור בתא! ברפאל ה-P.N. תמיד מופיע.

⚠️ קבלת החלטה במקרה ספק:
   • אם P.N. ו-DRAWING NO. נראים זהים בשני התאים — שניהם אותו ערך, מלא את שניהם.
   • אם רואים את הערך רק ב-DRAWING NO. אבל לא ב-P.N. (תא ריק / לא קריא) —
     מלא את ה-part_number באותו ערך כמו DRAWING NO.
   • לעולם אל תחזיר part_number ריק כשיש לך drawing_number ברפאל!
"""


STAGE_2_PROMPT = """אתה מומחה לזיהוי תהליכי ייצור, ציפוי, צביעה ותקנים משרטוטים הנדסיים.

⚙️ כללי Evidence קשיחים:
- חלץ רק מה שמופיע במפורש ב-NOTES / GENERAL NOTES / Title Block / SPECIFICATIONS.
- אסור לנחש, להשלים, או להסיק לפי "היגיון הנדסי".
- אם אין מידע — החזר מערך ריק [] או "" לפי הסוג.
- העתק ערכים בדיוק כפי שכתובים, כולל קודי תקן, עוביים, צבעים וגוונים.
- ⚠️ קריאת ספרות: "II" ≠ "I", "13" ≠ "12", "III" ≠ "II". קרא תו-אחר-תו.
- ⚠️ NOTES בעברית RTL: ייתכן וה-NOTES כתובות מימין-לשמאל בעברית עם קודי תקן באנגלית.
  דוגמה: "עם ציפוי אבץ לפי ASTM B633 TYPE II, FE/ZN 13" — זהו ציפוי אבץ, תקן ASTM B633 TYPE II, עובי FE/ZN 13 (13µm).
  כשיש טקסט OCR — העדף אותו לחילוץ קודי התקן המדויקים על פני קריאת התמונה.

מה לחלץ:

1. coating_processes — תהליכי ציפוי / פלטינג / טיפול שטח (מערך אובייקטים):
   כל פריט:
   {
     "type": "<קטגוריית הציפוי באנגלית — קצר וסטנדרטי>",
     "type_he": "<אותה קטגוריה בעברית>",
     "name": "<תיאור מלא כפי שכתוב בשרטוט + גוון / צבע>",
     "thickness": "<עובי ציפוי אם מצוין, למשל '15µm', '45-55µm', '0.0005 IN'>",
     "standard": "<תקן מלא כולל CLASS / GRADE / TYPE / METHOD / COMPOSITION>",
     "rohs": true/false
   }

   🏷️ קטלוג סוגי ציפוי (type / type_he) — חובה לקטלג לסוג ציפוי ספציפי בלבד:
   • "Conversion" / "המרה כימית" — CONVERSION COATING, ALODINE, IRIDITE, CHEM FILM, MIL-DTL-5541, MIL-C-5541
   • "Anodize" / "אנודייז" — ANODIZE, ANODIZING, ANODIC, TYPE II ANODIZE, MIL-A-8625
   • "Hard Anodize" / "אנודייז קשה" — HARD ANODIZE, TYPE III ANODIZE
   • "Passivation" / "פסיבציה" — PASSIVATION, PASSIVATE, QQ-P-35, ASTM A967
   • "Electroless Nickel" / "ניקל אלקטרולס" — ELECTROLESS NICKEL, EN PLATING, MIL-C-26074, ASTM B733
   • "Nickel" / "ניקל" — NICKEL PLATING, QQ-N-290
   • "Zinc" / "אבץ" — ZINC PLATING, GALVANIZE, ASTM B633, FE/ZN, QQ-Z-325
   • "Cadmium" / "קדמיום" — CADMIUM PLATING, QQ-P-416
   • "Chrome" / "כרום" — CHROME / CHROMIUM PLATING
   • "Hard Chrome" / "כרום קשה" — HARD CHROME
   • "Tin" / "בדיל" — TIN PLATING
   • "Silver" / "כסף" — SILVER PLATING
   • "Gold" / "זהב" — GOLD PLATING
   • "Copper" / "נחושת" — COPPER PLATING
   • "Black Oxide" / "תחמוצת שחורה" — BLACK OXIDE, BLACKENING
   • "Phosphate" / "פוספט" — PHOSPHATE, PHOSPHATING
   • "Dry Film Lubricant" / "שימון יבש" — DRY FILM LUBRICANT
   ⚠️ חשוב: type חייב להיות סוג ציפוי ספציפי. אסור "Surface Treatment" / "טיפול שטח" — זה כללי מדי.
   ⚠️ אם אין התאמה ברורה לאחד הסוגים למעלה — type="" ו-type_he="".

   🧭 מדריך זיהוי לפי תקן (לפענוח נכון של קטגוריה):
   • ASTM B633  → Zinc / אבץ (FE/ZN codes = Zinc plating, לא Conversion!)
   • ASTM B733  → Electroless Nickel
   • MIL-DTL-5541 / MIL-C-5541 → Conversion / המרה כימית
   • MIL-A-8625 → Anodize / אנודייז (Type II=גופרתני, Type III=קשה)
   • MIL-C-26074 → Electroless Nickel
   • QQ-P-416   → Cadmium
   • QQ-N-290   → Nickel
   • QQ-Z-325   → Zinc
   • AMS 2700 / ASTM A967 / QQ-P-35 → Passivation

   📖 קוד FE/ZN XX — מייצג ציפוי אבץ על פלדה בעובי XX מיקרון (XX = thickness):
       FE/ZN 5=5µm, FE/ZN 8=8µm, FE/ZN 12=12µm, FE/ZN 13=13µm, FE/ZN 25=25µm.
       ⚠️ העתק את המספר בדיוק כפי שכתוב — 12 ו-13 אלו ערכים שונים!

   ⚠️ שדה rohs:
   - true רק אם מופיע ליד התהליך במפורש: "ACCORDING TO RoHS", "PER RoHS", "RoHS COMPLIANT",
     "RoHS REGULATIONS", "בהתאם ל-RoHS" וכו'.
   - false אם אין אזכור RoHS — אל תניח ברירת מחדל.
   - דוגמה מהשרטוט:
     "CONVERSION COATING ... PER PS-111.21. PERFORM PROCESS ACCORDING TO RoHS REGULATIONS"
     → rohs=true


   ⚠️ קריטי — פרטי התקן:
   חובה לכלול בתקן את כל הפרטים המופיעים בשרטוט:
   - CLASS (Class 1, Class 2, Class 1A, Class 3)
   - TYPE (Type I, Type II, Type III)
   - GRADE (Grade A, Grade B, Grade C)
   - METHOD / COMPOSITION / CATEGORY / FORM
   - עבור RAFDOCS / PS — כלול את המספר המלא

   פורמט הדוגמאות (ערכי דמה — אל תעתיק אותם!):
     {"name": "<COATING_NAME>", "thickness": "<N µm / IN>", "standard": "<SPEC-CODE> Type <X> Class <Y>"}
     {"name": "<COATING_NAME>", "thickness": "", "standard": "<SPEC-CODE> Grade <Z>"}

   🚫 איסור חמור:
   - אל תמציא תקן! אסור להחזיר MIL-C-5541, MIL-A-8625, AMS-XXXX, PS-XXX, RAFDOCS-XXX
     אלא אם הקוד המדויק הזה מופיע בפועל בטקסט השרטוט.
   - אם בשרטוט כתוב רק "PS-111.21" — החזר "PS-111.21" בלבד, אל תוסיף MIL-C-5541.
   - אם בשרטוט כתוב רק "Conversion Coating" בלי תקן — standard="" .
   - ערכי הדוגמאות לעיל הם placeholders בלבד, לא ערכים אמיתיים לשימוש.

   - אם אין עובי — "" ב-thickness.
   - אם אין תקן — "" ב-standard.
   - כלול גם STRIPPING / RE-PLATING אם מופיע.

2. painting_processes — תהליכי צביעה (מערך אובייקטים):
   אותו מבנה: {"type", "type_he", "name", "thickness", "standard", "rohs"}
   פורמט (ערכי דמה — אל תעתיק!):
     {"type": "Polyurethane Topcoat", "type_he": "צבע עליון פוליאוריתן", "name": "<PAINT_NAME> <COLOR/RAL>", "thickness": "", "standard": "<SPEC-CODE> Type <X> Class <Y>", "rohs": false}

   🏷️ קטלוג סוגי צביעה (type / type_he):
   • "Epoxy Primer" / "פריימר אפוקסי"
   • "Polyurethane Topcoat" / "צבע עליון פוליאוריתן"
   • "Acrylic Paint" / "צבע אקרילי"
   • "Enamel" / "אמייל"
   • "Powder Coating" / "ציפוי אבקה"
   אותו איסור: אל תוסיף קודי תקן שאינם כתובים בשרטוט.
   שדה rohs: true רק אם מוצמד לצביעה אזכור מפורש של RoHS.

3. additional_processes — תהליכים מלווים (מערך אובייקטים, ללא תקן):
   כל פריט:
   {
     "name_en": "<שם באנגלית>",
     "name_he": "<שם בעברית>"
   }

   כולל (לפי הסדר בו הם מופיעים בשרטוט):
   - Heat Treatment / טיפול תרמי (כולל טמפרטורה/זמן אם מצוין)
   - Sand Blasting / Grit Blasting / Surface Blasting → התזת חול
   - Masking / Mask Threads / Mask Surfaces → מיסוך (ציין מה ממוסך: הברגות, חורים, משטחים)
   - Demasking → הסרת מיסוך
   - Marking / Tag & Bag / Identification Marking → סימון ותיוג
   - Engraving → חריטה (ציין גובה תו / עומק / צבע אם מצוין)
   - Silk Screening → הדפסת משי (ציין צבע)
   - Ink Jet → הזרקת דיו
   - Groove Filling / Slot Filling → מילוי חריצה
   - Dry Film Lubricant → שימון יבש
   - Hydrogen Degassing → שיחרור מימן
   - Insert Installation / Helicoil → החדרת קשיחים
   - Deburring / Edge Break → ניקוי קצוות / הסרת גרדים
   - Visual Inspection → בדיקה ויזואלית (רק אם דרישה מיוחדת)

   ⛔ אל תכלול עיבוד שבבי רגיל (Milling/Turning/Drilling/Grinding).

   דוגמאות:
     {"name_en": "Mask Threads and Marked Surfaces", "name_he": "מיסוך הברגות ומשטחים מסומנים"}
     {"name_en": "Surface Blasting Alumina 50 Micron 1.5-2 ATM", "name_he": "התזת חול אלומינה 50 מיקרון בלחץ 1.5-2 אטמוספירות"}
     {"name_en": "Engraving 3.0mm Character Height with Black Epoxy", "name_he": "חריטה בגובה תו 3.0 מ\\\"מ עם אפוקסי שחור"}
     {"name_en": "Heat Treatment 180°C for 2 Hours", "name_he": "טיפול תרמי 180°C במשך שעתיים"}
     {"name_en": "Silk Screening Color Black", "name_he": "הדפסת משי שחורה"}

4. packaging_notes — הערות אריזה מיוחדות (אובייקט):
   {"en": "<באנגלית>", "he": "<בעברית>"}
   חפש בשרטוט אזכורים של:
   - Packing / Packaging / Preservation
   - VCI Bags, Anti-Corrosion Wrapping
   - Tag & Bag
   - Individual Packaging / Each Item Separately
   - "Packing shall prevent corrosion and physical damage..."

   דוגמה:
     {
       "en": "Packaging shall prevent corrosion and physical damage during process, storage and shipment. Each item separately wrapped in VCI bag.",
       "he": "האריזה תמנע קורוזיה ונזק פיזי בתהליך, אחסון ומשלוח. כל פריט ארוז בנפרד בשקית VCI."
     }
   אם אין הערות אריזה מיוחדות → {"en": "", "he": ""}

5. standards — רשימה שטוחה של כל התקנים שמופיעים בשרטוט (מערך מחרוזות, ללא כפילויות):
   - MIL-SPEC (עם Type/Class/Grade!): "MIL-A-8625 Type II Class 1"
   - AMS (עם Method אם יש): "AMS 2700 Method 1 Type 2"
   - ASTM, ISO, FED-STD, NAS, MS, AS9100, AMS-QQ-P-416
   - תקני רפאל פנימיים: PS-XXX.XX, RAFDOCS-XXXXXX, PS-TILDOCS#XXXXXX
   - העתק כל תקן בדיוק כפי שכתוב עם כל פרטי ה-Type/Class/Grade.

6. notes — הערות כלליות נוספות שלא נכנסות בשדות למעלה (מחרוזת אחת, ריבוי שורות):
   - דרישות בדיקה מיוחדות, סובלנויות קריטיות, CAGE CODE, דרישות מסירה.
   - אל תכפיל תוכן שכבר הופיע ב-additional_processes / packaging_notes.

⛔ אסור להמציא תקנים, עוביים, גוונים, Class/Type/Grade, או תהליכים שלא רואים בשרטוט.

החזר JSON בלבד (ללא טקסט נוסף):
{
  "coating_processes": [{"type": "", "type_he": "", "name": "", "thickness": "", "standard": "", "rohs": false}],
  "painting_processes": [{"type": "", "type_he": "", "name": "", "thickness": "", "standard": "", "rohs": false}],
  "additional_processes": [{"name_en": "", "name_he": ""}],
  "packaging_notes": {"en": "", "he": ""},
  "standards": [],
  "notes": ""
}
"""


STAGE_3_PROMPT_TEMPLATE = """על סמך הנתונים הבאים, צור סיכום קצר בעברית.

נתונים:
- חומר: {material}
- ציפויים: {coatings}
- צביעות: {paintings}

📐 פורמט קריא:
   • כל סעיף בשורה נפרדת (קו חדש בין סעיפים).
   • התחל כל שורה במילת-מפתח בעברית ואחריה נקודתיים.
   • פרטים טכניים באנגלית (תקנים, גוונים, קודים) שים בסוגריים בסוף השורה.

מבנה חובה (סעיפים שאין להם מידע — דלג עליהם, אל תכתוב "אין"):

חומר: <חומר וסגסוגת בעברית> (<קוד מקורי אם רלוונטי>)
ציפוי: <סוג הציפוי בעברית> (<תקן + עובי + RoHS אם יש>)
צביעה: <סוג הצבע בעברית> (<תקן + גוון>)

📖 מילון תרגום:
- Aluminum → אלומיניום
- Steel → פלדה
- Stainless → נירוסטה
- Anodize / Anodizing → אנודייז
- Hard Anodize / Type III → אנודייז קשה
- Type II → אנודייז גופרתני
- Type I → אנודייז כרומי
- Conversion Coating / Alodine / Chem Film → המרה כימית
- Zinc Plating / Galvanize → ציפוי אבץ
- Cadmium Plating → ציפוי קדמיום
- Nickel Plating → ציפוי ניקל
- Electroless Nickel → ניקל אלקטרולס
- Passivation → פסיבציה
- Electroless Nickel → ניקל אלקטרולס
- Hard Chrome → כרום קשה
- Zinc Plating → אבץ
- Primer → פריימר
- Topcoat / Polyurethane → צבע עליון פוליאוריתן
- Epoxy → אפוקסי

⚠️ כללים:
- אם קטגוריה ריקה — דלג עליה לגמרי.
- אל תמציא! רק על סמך הנתונים שניתנו.
- אם אין שום מידע — החזר "—".
- אל תערבב עברית ואנגלית באותו רצף — תקנים ואותיות לטיניות רק בתוך סוגריים.

דוגמת פורמט (לא ערכים אמיתיים):
חומר: אלומיניום 6061-T6
ציפוי: תמורה (PS-111.21, RoHS)
צביעה: פוליאוריתן (RAL 7040)

🚫 אל תמציא תקנים — השתמש רק במה שהועבר אליך ב-stage2_data.

החזר רק את הטקסט בעברית, ללא הסבר, ללא ציטוטים.
"""

