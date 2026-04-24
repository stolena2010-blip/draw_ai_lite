"""
DrawingAI Lite — Streamlit UI
אפליקציה למשתמש בודד לניתוח שרטוט PDF.
"""
import logging
from pathlib import Path

import streamlit as st

from core.extractor import extract_drawing
from core.azure_client import (
    get_deployment, is_reasoning_model, get_masters_xlsx_path, enabled_modes,
)
from core.ocr_fallback import is_ocr_available
from core.exceptions import format_error_for_ui, get_streamlit_level
from ui_single_view import (
    render_drawing_result,
    render_save_section_single,
)
from ui_admin import (
    maybe_open_admin_panel,
    render_sidebar_footer,
)

# ═══════════════════════════════════════════════════════════════
# הגדרות
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(level=logging.INFO)

st.set_page_config(
    page_title="DrawingAI Lite",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="expanded",
)

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


# פונקציות הרנדור המשותפות (מאסטרים, ולידציה, שלבי מודל, תצוגת שרטוט, שמירה)
# עברו ל-ui_single_view.py ומיובאות למעלה — משמשות גם את מוד המכלולים.


# ─── עיצוב גלובלי: RTL + טיפוגרפיה + פלטה אחידה ───
st.markdown(
    """
    <style>
    /* ── RTL בסיסי ── */
    .stApp, .main, [data-testid="stAppViewContainer"] { direction: rtl; text-align: right; }
    [data-testid="stMarkdownContainer"], .stAlert, .stMetric { direction: rtl; text-align: right; }
    [data-testid="stAlert"] { unicode-bidi: plaintext; }
    code, pre { direction: ltr; text-align: left; unicode-bidi: embed; }

    /* ── טיפוגרפיה ── */
    html, body, [class*="css"] {
        font-family: "Segoe UI", "Heebo", -apple-system, BlinkMacSystemFont, sans-serif;
    }
    h1, h2, h3, h4 { font-weight: 700; letter-spacing: -0.01em; }

    /* ── הסר את הריווח העליון הענק של Streamlit ── */
    .block-container { padding-top: 1.2rem !important; max-width: 1300px; }

    /* ── באנר ALGAT / GREEN COAT ── */
    .brand-banner {
        border-radius: 0.7em;
        overflow: hidden;
        margin-bottom: 0.4em;
        box-shadow: 0 4px 12px rgba(122, 177, 65, 0.18);
    }
    .brand-banner img { display: block; width: 100%; height: auto; }
    .brand-strip {
        background: linear-gradient(90deg, #7AB141 0%, #C0AE2B 50%, #E89A2A 100%);
        color: white;
        padding: 0.5em 1em;
        border-radius: 0.4em;
        margin: 0.2em 0 1em 0;
        font-size: 0.88em;
        display: flex; justify-content: space-between; align-items: center;
    }
    .brand-strip b { color: white; }

    /* ── כרטיס סקשן ── */
    [data-testid="stExpander"] {
        border: 1px solid #dee2e6; border-radius: 0.5em;
    }
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 0.6em !important;
    }

    /* ── מתג מצב (segmented control) ── */
    [data-testid="stSegmentedControl"] button {
        font-weight: 600 !important; padding: 0.6em 1.2em !important;
    }

    /* ── סיידבר ── */
    [data-testid="stSidebar"] {
        background: #f8f9fa; border-left: 1px solid #dee2e6;
    }
    [data-testid="stSidebar"] h3 {
        color: #495057; font-size: 0.85em;
        text-transform: uppercase; letter-spacing: 0.08em;
        margin-top: 1em; margin-bottom: 0.4em;
    }
    [data-testid="stSidebar"] hr {
        margin: 0.6em 0; border-color: #dee2e6;
    }

    /* ── כפתורים ── */
    .stButton > button {
        border-radius: 0.4em; font-weight: 600; transition: all 0.15s;
    }
    .stButton > button:hover {
        transform: translateY(-1px); box-shadow: 0 2px 6px rgba(0,0,0,0.1);
    }

    /* ── סקשן עם בורדר ── */
    .section-card {
        background: white; border: 1px solid #dee2e6;
        border-radius: 0.6em; padding: 1em 1.2em; margin-bottom: 1em;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ═══════════════════════════════════════════════════════════════
# כותרת עליונה — באנר ALGAT / GREEN COAT + חיווי מודל
# ═══════════════════════════════════════════════════════════════
_active = get_deployment()
_badge = "🧠 Reasoning" if is_reasoning_model() else "👁️ Vision"

_LOGO_PATH = Path(__file__).parent / "brand_banner.png"
if _LOGO_PATH.exists():
    st.image(str(_LOGO_PATH), use_container_width=True)

st.markdown(
    f'<div class="brand-strip">'
    f'<span>📐 <b>DrawingAI Lite</b> · ניתוח אוטומטי של שרטוטים טכניים בעזרת AI</span>'
    f'<span>מודל: <b>{_active}</b> · {_badge}</span>'
    f'</div>',
    unsafe_allow_html=True,
)


# ═══════════════════════════════════════════════════════════════
# סיידבר — מצב עבודה, הגדרות, מנהל, אודות
# ═══════════════════════════════════════════════════════════════

with st.sidebar:
    # ─── בורר מצב עבודה ───
    st.markdown("### 🧭 מצב עבודה")
    _allowed_modes = enabled_modes()
    _allowed_modes = [m for m in _allowed_modes if m in {"single", "assembly"}]
    if not _allowed_modes:
        _allowed_modes = ["single", "assembly"]

    _current_mode = st.session_state.get("app_mode", _allowed_modes[0])
    if _current_mode not in _allowed_modes:
        st.session_state["app_mode"] = _allowed_modes[0]

    _mode_btn_style = """
    <style>
    div[data-testid="stRadio"] > label { display: none; }
    div[data-testid="stRadio"] > div {
        display: flex; flex-direction: column; gap: 0.4em;
    }
    div[data-testid="stRadio"] > div > label {
        display: flex !important;
        align-items: center;
        background: #F3F9E8;
        border: 1.5px solid #C7DFA0;
        border-radius: 0.5em;
        padding: 0.65em 1em;
        font-size: 1.05em;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.15s;
        width: 100%;
    }
    div[data-testid="stRadio"] > div > label:hover {
        background: #E7F1D3; border-color: #7AB141;
    }
    div[data-testid="stRadio"] > div > label[data-checked="true"],
    div[data-testid="stRadio"] > div > label:has(input:checked) {
        background: #7AB141;
        border-color: #7AB141;
        color: white;
        box-shadow: 0 2px 6px rgba(122,177,65,0.3);
    }
    </style>
    """
    st.markdown(_mode_btn_style, unsafe_allow_html=True)
    if len(_allowed_modes) == 1:
        st.info(
            "🔒 מצב עבודה פעיל: "
            + ("🔍 שרטוט בודד" if _allowed_modes[0] == "single" else "🧩 מכלולים מרובים")
        )
        st.session_state["app_mode"] = _allowed_modes[0]
    else:
        st.radio(
            "מצב עבודה",
            options=_allowed_modes,
            index=0 if st.session_state.get("app_mode", "single") == _allowed_modes[0] else 1,
            format_func=lambda x: "🔍  שרטוט בודד" if x == "single" else "🧩  מכלולים מרובים",
            key="app_mode",
            label_visibility="collapsed",
        )

    st.divider()

    st.caption("⚙️ הגדרות מערכת נמצאות בפאנל מנהל")

    st.divider()

    # ─── אודות ───
    with st.expander("ℹ️ אודות DrawingAI Lite", expanded=False):
        st.markdown(
            """
            **DrawingAI Lite v1.0**

            ניתוח אוטומטי של שרטוטים טכניים:

            - 🔍 **שרטוט בודד** — ניתוח מלא של PDF יחיד
            - 🧩 **מכלולים מרובים** — ניתוח קשרי אבא/בן
            - 🤖 מנוע **Azure OpenAI** (GPT-4o / GPT-5.4)
            - 📄 **OCR Fallback** אוטומטי
            - 🎯 **Master Matcher** — התאמה ל-1,239 מאסטרים
            - 💰 מעקב **עלויות** לכל שרטוט
            """
        )


# ═══════════════════════════════════════════════════════════════
# פאנל מנהל + אזהרת Masters.xlsx חסר
# ═══════════════════════════════════════════════════════════════
maybe_open_admin_panel()

_current_masters_full_path = get_masters_xlsx_path() or "Masters.xlsx"
_current_masters_check = Path(_current_masters_full_path) if _current_masters_full_path else Path("Masters.xlsx")
if not _current_masters_check.exists():
    st.warning(
        f"⚠️ קובץ **Masters.xlsx** חסר! התאמת מאסטרים לא תפעל.  \n\n"
        f"**נתיב המחפוש:** `{_current_masters_check}`  \n\n"
        f"**פתרונות:**\n"
        f"1. העתק את הקובץ ל-`{_current_masters_check}`\n"
        f"2. או הגדר את הנתיב בפאנל הגדרות מנהל (⚙️) או ב-`.env`"
    )


# ═══════════════════════════════════════════════════════════════
# ניתוב למצב מכלולים (Assembly)
# ═══════════════════════════════════════════════════════════════
if st.session_state.get("app_mode") == "assembly":
    from ui_assembly import render_assembly_mode
    render_assembly_mode(OUTPUT_DIR)
    render_sidebar_footer()
    st.stop()


if "result" not in st.session_state:
    st.session_state.result = None
if "filename" not in st.session_state:
    st.session_state.filename = None

# ─────────────────────────────────────
# העלאת קובץ + אפשרויות
# ─────────────────────────────────────
st.markdown("### 1️⃣ העלה שרטוט PDF")

with st.container(border=True):
    col_upload, col_opts = st.columns([3, 1])

    with col_upload:
        uploaded_file = st.file_uploader(
            "גרור שרטוט או לחץ לבחירה",
            type=["pdf"],
            help="קבצי PDF בלבד, עד 20MB"
        )

    with col_opts:
        st.markdown("**אפשרויות:**")
        ocr_enabled = st.checkbox(
            "OCR Fallback",
            value=True,
            disabled=not is_ocr_available(),
            help="יפעל אוטומטית אם AI לא מזהה שדות קריטיים"
        )
        if not is_ocr_available():
            st.caption("⚠️ Tesseract לא מותקן")

    if uploaded_file is not None:
        temp_path = OUTPUT_DIR / f"_temp_{uploaded_file.name}"
        with open(temp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        st.session_state.filename = uploaded_file.name

        if st.button("🔍 נתח שרטוט", type="primary",
                     use_container_width=True):
            with st.spinner("🔄 מנתח... (עשוי לקחת 20-40 שניות)"):
                try:
                    result = extract_drawing(temp_path, use_ocr_fallback=ocr_enabled)
                    st.session_state.result = result
                    st.success("✅ ניתוח הושלם")
                except Exception as e:
                    logger.exception("Drawing extraction failed")
                    level = get_streamlit_level(e)
                    getattr(st, level)(format_error_for_ui(e, include_technical=True))
                    st.session_state.result = None
                finally:
                    if temp_path.exists():
                        temp_path.unlink()

# ─────────────────────────────────────
# תצוגת תוצאות
# ─────────────────────────────────────
if st.session_state.result:
    st.divider()

    r = st.session_state.result
    cost_info = r.get("_cost_info", {})
    ocr_used = r.get("_ocr_used", False)

    # ─── באנר OCR בלבד (עלויות מוסתרות למנהל) ───
    if ocr_used:
        st.info("🔍 OCR הופעל כגיבוי לניתוח")

    st.markdown("### 2️⃣ תוצאות הניתוח")
    render_drawing_result(r, key_prefix="single", with_toggle=True)
    render_save_section_single(r, OUTPUT_DIR, st.session_state.filename,
                               key_prefix="single")

# ─────────────────────────────────────
# Sidebar — פאנל מנהל + קבצים שמורים
# ─────────────────────────────────────
render_sidebar_footer()
