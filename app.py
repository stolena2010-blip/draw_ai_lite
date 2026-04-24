"""
DrawingAI Lite — Streamlit UI
אפליקציה למשתמש בודד לניתוח שרטוט PDF.
"""
import logging
from pathlib import Path

import pandas as pd
import streamlit as st

from core.extractor import extract_drawing
from core.azure_client import (
    get_deployment, is_reasoning_model, 
    save_runtime_settings, get_masters_xlsx_path,
    is_fallback_enabled, enabled_modes, SUPPORTED_MODELS,
    MODEL_GPT_4O, MODEL_GPT_5_4
)
from core.cost_tracker import get_aggregate_stats
from core.ocr_fallback import is_ocr_available
from core.exceptions import format_error_for_ui, get_streamlit_level
from ui_single_view import (
    render_drawing_result,
    render_save_section_single,
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

_LOGO_PATH = Path(__file__).parent / "TEMPLATE FOR COLORS.png"
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
from core.azure_client import (
    MODEL_GPT_4O, MODEL_GPT_5_4, SUPPORTED_MODELS,
    _active_model, is_fallback_enabled, save_runtime_settings, enabled_modes,
)

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
# פאנל עלויות למנהל מערכת
# ═══════════════════════════════════════════════════════════════
@st.dialog("🛠️ פאנל מנהל מערכת", width="large")
def _show_admin_cost_panel():
    """פאנל מוסתר המציג את כל מידע העלויות והטוקנים."""
    # ב-Single mode: result. ב-Assembly mode: asm_results (מחבר כולם)
    r = st.session_state.get("result") or {}
    asm_results = st.session_state.get("asm_results") or []
    is_assembly = st.session_state.get("app_mode") == "assembly"

    st.markdown("#### 📊 עלויות מצטברות (כל השרטוטים שנותחו)")
    stats = get_aggregate_stats()
    if stats:
        a1, a2, a3 = st.columns(3)
        a1.metric("שרטוטים שנותחו", stats["count"])
        a2.metric("סה\"כ עלות", f"${stats['total_cost_usd']:.2f}")
        a3.metric("ממוצע לשרטוט", f"${stats['avg_cost_usd']:.4f}")
    else:
        st.caption("עדיין לא נותחו שרטוטים")

    st.divider()

    if is_assembly and asm_results:
        # ─── Assembly mode: עלות לכל שרטוט ───
        st.markdown("#### 🎯 עלויות סשן המכלול")
        total_usd = sum(
            (res.get("_cost_info") or {}).get("total_cost_usd", 0)
            for res in asm_results
        )
        total_ils = sum(
            (res.get("_cost_info") or {}).get("total_cost_ils", 0)
            for res in asm_results
        )
        t1, t2 = st.columns(2)
        t1.metric("💰 סה\"כ עלות $", f"${total_usd:.4f}")
        t2.metric("💱 סה\"כ בשקלים", f"₪{total_ils:.3f}")

        for res in asm_results:
            ci = res.get("_cost_info") or {}
            if not ci:
                continue
            fname = res.get("source_filename", "שרטוט")
            with st.expander(f"📄 {fname}", expanded=False):
                c1, c2, c3 = st.columns(3)
                c1.metric("💰 עלות $", f"${ci.get('total_cost_usd', 0):.4f}")
                c2.metric("💱 בשקלים", f"₪{ci.get('total_cost_ils', 0):.3f}")
                c3.metric(
                    "🔤 טוקנים",
                    f"{ci.get('input_tokens', 0):,} + {ci.get('output_tokens', 0):,}",
                )
                stages = ci.get("stages", [])
                if stages:
                    df = pd.DataFrame(stages)
                    cols = [c for c in ["stage", "model", "input_tokens", "output_tokens", "total_cost_usd"] if c in df.columns]
                    df = df[cols].rename(columns={
                        "stage": "שלב", "model": "מודל בפועל",
                        "input_tokens": "Input tokens",
                        "output_tokens": "Output tokens",
                        "total_cost_usd": "עלות $",
                    })
                    st.dataframe(df, use_container_width=True, hide_index=True)

    else:
        # ─── Single mode ───
        cost_info = r.get("_cost_info", {})
        if cost_info:
            st.markdown("#### 🎯 עלות השרטוט הנוכחי")
            c1, c2, c3 = st.columns(3)
            c1.metric("💰 עלות $", f"${cost_info.get('total_cost_usd', 0):.4f}")
            c2.metric("💱 בשקלים", f"₪{cost_info.get('total_cost_ils', 0):.3f}")
            c3.metric(
                "🔤 טוקנים",
                f"{cost_info.get('input_tokens', 0):,} + {cost_info.get('output_tokens', 0):,}",
            )

            st.markdown("##### פירוט לפי שלב")
            stages = cost_info.get("stages", [])
            if stages:
                df = pd.DataFrame(stages)
                cols = [c for c in ["stage", "model", "input_tokens", "output_tokens", "total_cost_usd"] if c in df.columns]
                df = df[cols]
                col_map = {
                    "stage": "שלב",
                    "model": "מודל בפועל",
                    "input_tokens": "Input tokens",
                    "output_tokens": "Output tokens",
                    "total_cost_usd": "עלות $",
                }
                df = df.rename(columns=col_map)
                st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.caption("אין נתוני עלויות לשרטוט הנוכחי")

    st.divider()
    st.markdown("#### ⚙️ הגדרות מערכת (מנהל)")

    _current_model = _active_model()
    _model_idx = SUPPORTED_MODELS.index(_current_model) if _current_model in SUPPORTED_MODELS else 0
    _model_label = {
        MODEL_GPT_4O: "🟢 GPT-4o Vision (פשוט, מהיר)",
        MODEL_GPT_5_4: "🧠 GPT-5.4 (Reasoning, חזק)",
    }

    cset1, cset2 = st.columns([2, 1])
    with cset1:
        _new_model = st.radio(
            "מודל AI פעיל",
            options=list(SUPPORTED_MODELS),
            index=_model_idx,
            format_func=lambda x: _model_label.get(x, x),
            key="admin_active_model",
        )
    with cset2:
        _new_fb = st.checkbox(
            "Fallback אוטומטי",
            value=is_fallback_enabled(),
            key="admin_fallback",
            help="מעבר אוטומטי למודל השני אם הראשי נכשל",
        )

    _current_modes = enabled_modes()
    _mode_options = ["single", "assembly"]
    _new_modes = st.multiselect(
        "גישה למצבי עבודה",
        options=_mode_options,
        default=[m for m in _current_modes if m in _mode_options] or _mode_options,
        format_func=lambda x: "🔍 שרטוט בודד" if x == "single" else "🧩 מכלולים מרובים",
        key="admin_enabled_modes",
        help="בחר אילו מצבים יוצגו למשתמש בממשק",
    )

    st.divider()
    st.markdown("#### 📁 נתיבים")
    _current_masters_path = get_masters_xlsx_path()
    _new_masters_path = st.text_input(
        "📄 נתיב ל-Masters.xlsx",
        value=_current_masters_path,
        placeholder="C:\\Data\\Masters.xlsx או השאר ריק לברירת מחדל",
        help="נתיב מוחלט או יחסי לקובץ Masters.xlsx. אם ריק, יחפש ב-root ב-.env",
        key="admin_masters_path",
    )

    if not _new_modes:
        st.error("חובה לבחור לפחות מצב עבודה אחד")
    else:
        _settings_changed = (
            _new_model != _current_model
            or _new_fb != is_fallback_enabled()
            or set(_new_modes) != set(_current_modes)
            or _new_masters_path != _current_masters_path
        )
        if _settings_changed:
            if st.button("💾 שמור הגדרות מערכת", use_container_width=True):
                save_runtime_settings(
                    active_model=_new_model,
                    fallback_enabled=_new_fb,
                    enabled_modes=_new_modes,
                    masters_xlsx_path=_new_masters_path,
                )
                if st.session_state.get("app_mode") not in _new_modes:
                    st.session_state["app_mode"] = _new_modes[0]
                st.success("✅ הגדרות נשמרו")
                st.rerun()
        else:
            st.caption("אין שינויים להגדרה")

    if st.button("סגור", use_container_width=True):
        st.session_state["_show_admin"] = False
        st.rerun()


if st.session_state.get("_show_admin"):
    # מאפסים מיד את הדגל כדי שהדיאלוג ייפתח פעם אחת בלבד
    st.session_state["_show_admin"] = False
    _show_admin_cost_panel()

# ─── אזהרה אם Masters.xlsx חסר ───
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
# סרגל צד תחתון משותף — מנהל + קבצים שמורים
# ═══════════════════════════════════════════════════════════════
def _render_sidebar_footer():
    with st.sidebar:
        st.divider()
        st.markdown("### 📊 פאנל מנהל")
        if st.button("🛠️ פתח פאנל מנהל", use_container_width=True,
                     key="open_admin_btn"):
            st.session_state["_show_admin"] = True
            st.rerun()


# ═══════════════════════════════════════════════════════════════
# ניתוב למצב מכלולים (Assembly)
# ═══════════════════════════════════════════════════════════════
if st.session_state.get("app_mode") == "assembly":
    from ui_assembly import render_assembly_mode
    render_assembly_mode(OUTPUT_DIR)
    _render_sidebar_footer()
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
_render_sidebar_footer()
