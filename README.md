# 📐 DrawingAI Lite

[![CI](https://github.com/stolena2010-blip/draw_ai_lite/actions/workflows/ci.yml/badge.svg)](https://github.com/stolena2010-blip/draw_ai_lite/actions/workflows/ci.yml)

אפליקציית Streamlit לניתוח שרטוטים טכניים (PDF) באמצעות Azure OpenAI Vision / Reasoning.

## תכולה

### 🔍 מצב 'שרטוט בודד'
- העלאת PDF יחיד → חילוץ אוטומטי של שדות טכניים (P/N, revision, customer, material, תהליכי ציפוי/צביעה, תקנים, הערות)
- סיכום בעברית
- **התאמה למאסטרים** מ-Masters.xlsx (Top-3 לכל ציפוי, ציון 0-150)
- **OCR מותנה** (Tesseract) — מופעל רק כש-Stage 1 חלש (חוסך זמן ברוב המקרים)
- **Two-Pass אימות** לשדות קריטיים בצביעה (RAL / מותגים) לזיהוי אי-עקביות בין הרצות
- **שכבת ולידציה בקוד**: RAL תקני, מותגי צבע, סיווג ציפויים, והוראות אריזה חשודות
- הצגת **אזהרות ולידציה** ו-**המודל בפועל לכל שלב** במסך התוצאות
- **Drawing Cache** אוטומטי לפי MD5 — חיסכון משמעותי ב-API runs חוזרים
- שמירת תוצאות ל-**JSON** או **Excel רב-גיליוני** (Summary / Coatings / Paintings / Master_Matches / Standards / Warnings)

### 🧩 מצב 'מכלולים מרובים'
- העלאת מספר PDFים יחד **או** תמונת Exploded View (PNG/JPG/WEBP)
- ניתוח כל שרטוט בנפרד + ניתוח קשרי אבא/בן בין השרטוטים
- תמונת מכלול ממוינת אוטומטית לראש (לא משנה סדר ההעלאה)
- גיליון **עץ מתמונה** נבנה עם קישור שמרני:
  - התאמה לפי `Item No.` בעדיפות ראשונה (עם fallback ל-`part_number`)
  - תיקון `P/N` שגוי מהתמונה לפי התאמת BOM מאומתת (למשל טעויות OCR)
  - `קושר ל-P/N` / `קושר ל-Drawing` מתמלאים רק אם קיים שרטוט שהועלה בפועל
  - `כמות לפי BOM` / `תיאור BOM` נשמרים כשיש התאמת BOM, גם אם אין שרטוט קיים
  - ללא ניחוש קישורים: עמודת `נמצא בקבצים?` מסמנת רק `כן/לא` לפי קבצים אמיתיים
- ייצוא:
  - 📕 דוח PDF מלא (RTL עברית)
  - 🌳 דוח עץ מוצר מקוצר (טבלה + סכמה ויזואלית)
  - 📊 עץ מוצר ל-Excel (כולל עמודות אב ישיר/נתיב)
  - 🧭 גיליון נפרד לעץ מהתמונה (ללא ערבוב עם עץ מוצר אמיתי)
  - 💾 JSON מאוחד

### 💰 מעקב עלויות
- כל קריאת API נמדדת ונשמרת ב-`output/costs.jsonl`
- תוסף Azure ניתן להגדרה דרך `AZURE_SURCHARGE` ב-`.env`
- **Drawing Cache** לפי MD5 של הקובץ + גרסת מודל → runs חוזרים חינמיים
  (ניתן לכיבוי עם `DRAWING_CACHE_DISABLED=true`)

### 🛡️ יציבות
- **Custom Exceptions** עם הודעות עברית ידידותיות למשתמש (לא stack traces)
- **Retry אוטומטי** על שגיאות רשת/API זמניות (exponential backoff)
- **Fallback מודל** אוטומטי — אם gpt-4o נכשל, עובר ל-gpt-5.4 (ולהפך)

## התקנה

### 1. דרישות מוקדמות
- Python 3.10+ (מומלץ 3.13)
- חשבון Azure OpenAI עם deployment של `gpt-4o` או `gpt-5.4`
- (אופציונלי) [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) — לפעולת OCR Fallback (התקן גם חבילת שפה עברית)

### 2. venv + חבילות
```powershell
cd C:\DrawingLight
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. הגדרת Azure
```powershell
Copy-Item .env.example .env
# ערוך .env ומלא את הפרטים שלך
```

## הרצה

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

או הרצה מהירה: `Run_Web.bat`

הדפדפן יפתח ב-http://localhost:8501

## בדיקות

```powershell
.\.venv\Scripts\Activate.ps1
pytest tests/ -v
```

## מבנה

```
DrawingLight/
├── app.py                  ← Streamlit entry (מצב 'שרטוט בודד')
├── ui_assembly.py          ← מסך 'מכלולים מרובים'
├── core/
│   ├── azure_client.py     ← Azure OpenAI wrapper
│   ├── ai_helpers.py       ← call_vision/call_text/safe_call + retry
│   ├── exceptions.py       ← היררכיית custom exceptions (עברית ידידותית)
│   ├── drawing_cache.py    ← cache לפי MD5 (חיסכון ב-API)
│   ├── pdf_utils.py        ← PDF/Image → base64
│   ├── prompts.py          ← Stage 1/2/3 prompts
│   ├── extractor.py        ← extract_drawing() — pipeline מלא (משותף לשני המודים)
│   ├── master_matcher.py   ← התאמה למאסטרים (1239 פריטים)
│   ├── cost_tracker.py     ← מעקב עלויות
│   ├── ocr_fallback.py     ← Tesseract fallback
│   ├── validators.py       ← ולידציה לאחר חילוץ (RAL/brands/coating/packing)
│   └── two_pass.py         ← השוואת שתי הרצות לשדות קריטיים
├── prompts/
│   └── single/             ← קבצי פרומפטים חיצוניים (משמשים את שני המודים)
├── storage/
│   ├── save_handler.py     ← save_to_json/excel + save_batch_to_excel
│   └── pdf_report.py       ← build_batch_pdf() — דוח PDF מאוחד
├── app.py                  ← Streamlit main — router, sidebar, header
├── ui_single_view.py       ← רנדור משותף של תוצאת שרטוט + כפתורי שמירה
├── ui_assembly.py          ← מוד מכלולים: loop + pagination + batch exports
├── ui_admin.py             ← פאנל מנהל (עלויות, הגדרות, מודל AI)
├── tests/
│   ├── test_master_matcher.py  ← בדיקות ל-Master Matcher
│   └── test_exceptions.py      ← בדיקות ל-exceptions
├── output/                 ← תוצאות + costs.jsonl + .cache/
├── Masters.xlsx            ← מאגר ציפויים (חובה להתאמת מאסטרים)
├── brand_banner.png        ← לוגו ALGAT / GREEN COAT
├── requirements.txt
├── .env.example
├── PROJECT_OVERVIEW.md     ← סקירה מפורטת
└── CHANGELOG.md            ← שינויים אחרונים
```

ראה [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) לסקירה טכנית מלאה.

