"""
DrawingAI Lite — Streamlit UI
אפליקציה למשתמש בודד לניתוח שרטוט PDF.
"""
import logging
from datetime import datetime
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
from storage.save_handler import save_to_json, save_to_excel

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


_SEVERITY_ICON = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}


def _render_validation_warnings(result: dict) -> None:
    """מציג אזהרות ולידציה (RAL, מותג, ציפוי, אריזה, two-pass) אם קיימות."""
    warnings = result.get("_validation_warnings") or []
    if not warnings:
        return
    critical = [w for w in warnings if w.get("severity") == "CRITICAL"]
    label = f"⚠️ {len(warnings)} אזהרות ולידציה"
    if critical:
        label += f" — {len(critical)} 🔴 קריטיות"
    with st.expander(label, expanded=bool(critical)):
        for w in warnings:
            icon = _SEVERITY_ICON.get(w.get("severity", ""), "⚪")
            st.markdown(
                f"{icon} **{w.get('type', '')}** | מקור: `{w.get('source', '')}` | "
                f"ערך: `{w.get('value', '')[:80]}`  \n"
                f"_{w.get('message', '')}_"
            )


def _render_stage_model_feedback(cost_info: dict,
                                 title: str = "🤖 מודל בפועל לכל שלב",
                                 expanded: bool = False) -> None:
    """מציג פירוט שלבים עם המודל בפועל, טוקנים ועלות."""
    stages = (cost_info or {}).get("stages") or []
    if not stages:
        return

    rows = []
    for s in stages:
        if not isinstance(s, dict):
            continue
        rows.append({
            "שלב": s.get("stage", ""),
            "מודל בפועל": s.get("model", ""),
            "Input": s.get("input_tokens", 0),
            "Output": s.get("output_tokens", 0),
            "עלות $": s.get("total_cost_usd", 0),
        })

    if not rows:
        return

    with st.expander(title, expanded=expanded):
        st.dataframe(rows, use_container_width=True, hide_index=True)
        models = sorted({r["מודל בפועל"] for r in rows if r["מודל בפועל"]})
        if models:
            st.caption("מודלים בשימוש: " + " | ".join(models))


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

    /* ── כותרת אפליקציה ── */
    .app-header {
        background: linear-gradient(135deg, #0d6efd 0%, #6610f2 100%);
        color: white;
        padding: 0.9em 1.4em;
        border-radius: 0.7em;
        margin-bottom: 1em;
        box-shadow: 0 4px 12px rgba(13, 110, 253, 0.18);
        display: flex; justify-content: space-between; align-items: center;
    }
    .app-header h1 {
        margin: 0; font-size: 1.5em; color: white;
        display: flex; align-items: center; gap: 0.4em;
    }
    .app-header .tagline {
        font-size: 0.85em; opacity: 0.9; margin-top: 0.15em;
    }

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
# כותרת עליונה — לוגו + חיווי מודל
# ═══════════════════════════════════════════════════════════════
_active = get_deployment()
_badge = "🧠 Reasoning" if is_reasoning_model() else "👁️ Vision"

st.markdown(
    f'<div class="app-header">'
    f'<div>'
    f'<h1>📐 DrawingAI Lite</h1>'
    f'<div class="tagline">ניתוח אוטומטי של שרטוטים טכניים בעזרת AI</div>'
    f'</div>'
    f'<div style="text-align:left; font-size:0.85em; opacity:0.95;">'
    f'<div>מודל פעיל: <b>{_active}</b></div>'
    f'<div style="margin-top:0.2em;">{_badge}</div>'
    f'</div>'
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
        background: #f0f4ff;
        border: 1.5px solid #c7d7fb;
        border-radius: 0.5em;
        padding: 0.65em 1em;
        font-size: 1.05em;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.15s;
        width: 100%;
    }
    div[data-testid="stRadio"] > div > label:hover {
        background: #dce8ff; border-color: #4a86e8;
    }
    div[data-testid="stRadio"] > div > label[data-checked="true"],
    div[data-testid="stRadio"] > div > label:has(input:checked) {
        background: #0d6efd;
        border-color: #0d6efd;
        color: white;
        box-shadow: 0 2px 6px rgba(13,110,253,0.3);
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

    # ═══════════════════════════════════════════════════════════
    # 🎯 מבט-על — כל המידע הקריטי בכרטיס אחד (Top-of-page)
    # ═══════════════════════════════════════════════════════════
    _ov_pn = r.get("part_number") or "—"
    _ov_dn = r.get("drawing_number") or "—"
    _ov_rev = r.get("revision") or "—"
    _ov_cust = r.get("customer") or "—"
    _ov_mat = r.get("material") or "—"
    _ov_coats = r.get("coating_processes", []) or []
    _ov_paints = r.get("painting_processes", []) or []
    _ov_matches = r.get("master_matches", []) or []
    _ov_match_by_id = {id(e.get("coating")): e.get("matches", []) for e in _ov_matches}
    _ov_add = r.get("additional_processes", []) or []
    _ov_pkg = r.get("packaging_notes") or {}
    _ov_pkg_he = (_ov_pkg.get("he") or "").strip() if isinstance(_ov_pkg, dict) else ""

    # ─── 📌 מאסטרים מובילים — כרטיסיות גדולות עם העתקה ───
    _ov_top_masters = []
    for _e in _ov_matches:
        _mlist = _e.get("matches") or []
        if _mlist:
            _ov_top_masters.append((_e.get("coating") or {}, _mlist[0]))
    if _ov_top_masters:
        st.markdown(
            '<div dir="rtl" style="unicode-bidi:plaintext; text-align:right; '
            'font-weight:700; color:#0d6efd; font-size:1.1em; '
            'margin:0.4em 0 0.5em 0;">📌 מאסטר מוביל</div>',
            unsafe_allow_html=True,
        )
        for _coat, _m in _ov_top_masters:
            _head = (_coat.get("type_he") or _coat.get("type") or _coat.get("name") or "")[:40]
            _sc = _m.get("score", 0)
            _mid = _m["master_id"]
            _desc = (_m.get("desc") or "").strip()[:80]
            _std_m = (_m.get("standard") or "").strip()
            _thk_m = (_m.get("thickness") or "").strip()

            if _sc >= 70:
                _bg, _fg, _border = "#d1e7dd", "#0a3622", "#198754"
            elif _sc >= 50:
                _bg, _fg, _border = "#fff3cd", "#664d03", "#fd7e14"
            else:
                _bg, _fg, _border = "#f8d7da", "#58151c", "#dc3545"

            # כרטיס מאסטר גדול ובולט: מספר מאסטר ענק משמאל, פרטים מימין
            _card_col, _copy_col = st.columns([4, 1])
            with _card_col:
                _meta_bits = []
                if _std_m:
                    _meta_bits.append(f'📜 <code>{_std_m}</code>')
                if _thk_m:
                    _meta_bits.append(f'📏 <code>{_thk_m}</code>')
                _meta_html = " &nbsp;·&nbsp; ".join(_meta_bits)
                st.markdown(
                    f'<div dir="rtl" style="unicode-bidi:plaintext; text-align:right; '
                    f'background:{_bg}; border:2px solid {_border}; '
                    f'border-radius:0.6em; padding:0.7em 1em; margin-bottom:0.4em; '
                    f'box-shadow:0 2px 4px rgba(0,0,0,0.08);">'
                    # שורה עליונה: ראש הציפוי + ציון
                    f'<div style="display:flex; justify-content:space-between; '
                    f'align-items:center; margin-bottom:0.45em;">'
                    f'<span style="font-weight:700; color:{_fg}; font-size:1.05em;">'
                    f'🏷️ {_head}</span>'
                    f'<span style="background:{_border}; color:white; '
                    f'padding:0.15em 0.7em; border-radius:0.4em; '
                    f'font-size:0.95em; font-weight:700;">ציון {_sc}</span>'
                    f'</div>'
                    # מספר המאסטר — ענק ובולט
                    f'<div style="font-family:Consolas,Monaco,monospace; '
                    f'font-size:1.8em; font-weight:700; color:{_border}; '
                    f'letter-spacing:0.05em; margin:0.2em 0; text-align:right; '
                    f'direction:ltr; unicode-bidi:plaintext;">'
                    f'{_mid}</div>'
                    # תיאור המאסטר
                    f'<div style="color:{_fg}; font-size:0.95em; '
                    f'margin-bottom:0.35em;">{_desc}</div>'
                    # תקן + עובי
                    + (f'<div style="font-size:0.88em;">{_meta_html}</div>' if _meta_html else '')
                    + '</div>',
                    unsafe_allow_html=True,
                )
            with _copy_col:
                # שדה העתקה — Streamlit מציג כפתור העתקה אוטומטי על st.code
                st.markdown(
                    '<div style="text-align:center; color:#6c757d; '
                    'font-size:0.8em; margin-top:0.4em;">📋 העתק:</div>',
                    unsafe_allow_html=True,
                )
                st.code(_mid, language=None)


    def _ov_chip(p):
        if not isinstance(p, dict):
            return f'<div style="margin:0.25em 0;">{p}</div>'
        type_he = (p.get("type_he") or "").strip()
        type_en = (p.get("type") or "").strip()
        name = (p.get("name") or "").strip()
        std = (p.get("standard") or "").strip()
        thick = (p.get("thickness") or "").strip()
        rohs_mark = " 🌱" if p.get("rohs") is True else ""
        head = type_he or type_en or name[:60]
        # שורה ראשונה: סוג + תקן + עובי + מאסטר
        bits = [f'<b>{head}</b>{rohs_mark}']
        if std:
            bits.append(f'📜 <code>{std}</code>')
        if thick:
            bits.append(f'📏 <code>{thick}</code>')
        top = _ov_match_by_id.get(id(p)) or []
        if top:
            m = top[0]
            sc = m.get("score", 0)
            color = "#198754" if sc >= 70 else ("#fd7e14" if sc >= 50 else "#dc3545")
            bits.append(
                f'🎯 <code>{m["master_id"]}</code> · {m["desc"][:40]} '
                f'<span style="background:{color}; color:white; padding:0.05em 0.45em; '
                f'border-radius:0.3em; font-size:0.82em; font-weight:600;">{sc}</span>'
            )
        line1 = f'<div style="margin:0.3em 0 0.1em 0; line-height:1.7;">{" &nbsp;·&nbsp; ".join(bits)}</div>'
        # שורה שנייה: תיאור מלא של הציפוי מתוך ה-NOTES
        line2 = ""
        if name and name.strip().upper() != head.strip().upper():
            line2 = (
                f'<div style="margin:0 0 0.5em 1.2em; color:#495057; '
                f'font-size:0.88em; line-height:1.5; word-break:break-word;">'
                f'📄 {name}</div>'
            )
        return line1 + line2

    _ov_procs_html = "".join(_ov_chip(c) for c in _ov_coats)
    _ov_procs_html += "".join(_ov_chip(p) for p in _ov_paints)
    if not _ov_procs_html:
        _ov_procs_html = '<div style="color:#6c757d;">— ללא ציפוי/צביעה —</div>'

    _ov_used_stds = {(it.get("standard") or "").strip()
                     for it in _ov_coats + _ov_paints if isinstance(it, dict)}
    _ov_extra = [s for s in (r.get("standards") or [])
                 if s and s.strip() and s.strip() not in _ov_used_stds]
    _ov_extra_html = ""
    if _ov_extra:
        _ov_extra_html = (
            '<div style="margin-top:0.4em;"><span style="color:#6c757d;">תקנים נוספים:</span> '
            + " ".join(f'<code>{s}</code>' for s in _ov_extra) + '</div>'
        )

    _ov_add_html = ""
    if _ov_add:
        _names = []
        for a in _ov_add:
            if isinstance(a, dict):
                he = (a.get("name_he") or "").strip()
                if he:
                    _names.append(he)
            else:
                t = str(a or "").strip()
                if t:
                    _names.append(t)
        if _names:
            _ov_add_html = (
                '<div style="margin-top:0.4em;"><span style="color:#6c757d;">🛠️ תהליכים נוספים:</span> '
                + " &nbsp;·&nbsp; ".join(_names) + '</div>'
            )

    _ov_pkg_html = ""
    if _ov_pkg_he:
        _ov_pkg_html = (
            '<div style="margin-top:0.4em;"><span style="color:#6c757d;">📦 אריזה:</span> '
            + _ov_pkg_he + '</div>'
        )

    st.markdown(
        f'<div dir="rtl" style="unicode-bidi:plaintext; text-align:right; '
        f'background:linear-gradient(135deg,#eef5ff 0%,#e8f5e9 100%); '
        f'border:2px solid #0d6efd; border-radius:0.7em; padding:1em 1.2em; '
        f'margin-bottom:1em; word-break:break-word; font-size:0.95em; line-height:1.7;">'
        f'<div style="font-size:1.1em; font-weight:700; color:#0d6efd; '
        f'margin-bottom:0.5em; border-bottom:1px solid #cfe2ff; padding-bottom:0.3em;">'
        f'🎯 מבט-על</div>'
        f'<div style="margin-bottom:0.4em;">'
        f'<span style="color:#6c757d;">פריט:</span> <b>{_ov_pn}</b> &nbsp;·&nbsp; '
        f'<span style="color:#6c757d;">שרטוט:</span> <b>{_ov_dn}</b> &nbsp;·&nbsp; '
        f'<span style="color:#6c757d;">גרסה:</span> <b>{_ov_rev}</b> &nbsp;·&nbsp; '
        f'<span style="color:#6c757d;">לקוח:</span> <b>{_ov_cust}</b>'
        f'</div>'
        f'<div style="margin-bottom:0.5em;">'
        f'<span style="color:#6c757d;">חומר גלם:</span> <b>{_ov_mat}</b>'
        f'</div>'
        f'<div style="border-top:1px dashed #adb5bd; padding-top:0.5em;">'
        f'<span style="color:#6c757d; font-weight:600;">🎨 ציפויים / צביעות:</span>'
        f'{_ov_procs_html}'
        f'{_ov_extra_html}'
        f'{_ov_add_html}'
        f'{_ov_pkg_html}'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    _ov_show_details = st.toggle("📋 הצג פירוט מלא", value=False, key="show_full_details")
    if not _ov_show_details:
        # שמור את כל הפירוט בלוקים מקופלים — דלג על הרינדור המפורט
        st.divider()
        st.markdown("### 3️⃣ שמור תוצאה")
        _render_stage_model_feedback(cost_info, expanded=False)
        _render_validation_warnings(r)
        _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _bn = Path(st.session_state.filename).stem
        _c1, _c2, _c3 = st.columns(3)
        with _c1:
            if st.button("💾 שמור JSON", use_container_width=True, key="save_json_ov"):
                p = save_to_json(r, OUTPUT_DIR / f"{_bn}_{_ts}.json")
                st.success(f"נשמר: `{p.name}`")
        with _c2:
            if st.button("📊 שמור Excel", use_container_width=True, key="save_xl_ov"):
                p = save_to_excel(r, OUTPUT_DIR / f"{_bn}_{_ts}.xlsx")
                st.success(f"נשמר: `{p.name}`")
        with _c3:
            if st.button("🔄 שרטוט חדש", use_container_width=True, key="new_ov"):
                st.session_state.result = None
                st.session_state.filename = None
                st.rerun()
        _render_sidebar_footer()
        st.stop()

    # ─── סרגל מזהים קומפקטי (פחות חשוב — מוצג קטן בשורה אחת) ───
    pn = r.get("part_number") or "—"
    dn = r.get("drawing_number") or "—"
    rev = r.get("revision") or "—"
    cust = r.get("customer") or "—"
    material_val = r.get("material") or "—"
    st.markdown(
        f'<div dir="rtl" style="unicode-bidi:plaintext; text-align:right; '
        f'background:#f8f9fa; border:1px solid #dee2e6; padding:0.4em 0.8em; '
        f'border-radius:0.4em; margin-bottom:0.4em; font-size:0.88em; line-height:1.6; '
        f'word-break:break-word;">'
        f'<span style="color:#6c757d;">פריט:</span> <b>{pn}</b> &nbsp;·&nbsp; '
        f'<span style="color:#6c757d;">שרטוט:</span> <b>{dn}</b> &nbsp;·&nbsp; '
        f'<span style="color:#6c757d;">גרסה:</span> <b>{rev}</b> &nbsp;·&nbsp; '
        f'<span style="color:#6c757d;">לקוח:</span> <b>{cust}</b><br>'
        f'<span style="color:#6c757d;">חומר גלם:</span> <b>{material_val}</b>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ─── סיכום עברי ───
    summary_text = r.get("process_summary_hebrew", "—")
    st.markdown(
        f'<div dir="rtl" style="unicode-bidi:plaintext; text-align:right; '
        f'background:#d4edda; color:#155724; padding:0.65em 0.95em; border-radius:0.5em; '
        f'font-size:1em; line-height:1.7; white-space:pre-line; '
        f'margin:0.4em 0 1em 0;">🇮🇱 <b>סיכום:</b>\n{summary_text}</div>',
        unsafe_allow_html=True,
    )

    def _render_proc(item):
        """מציג סוג ציפוי + שם מלא + עובי + תקן + RoHS."""
        if isinstance(item, dict):
            type_he = (item.get("type_he") or "").strip()
            type_en = (item.get("type") or "").strip()
            name = (item.get("name") or "").strip()
            std = (item.get("standard") or "").strip()
            thickness = (item.get("thickness") or "").strip()
            rohs = item.get("rohs")
            parts = []
            if type_he and type_en:
                parts.append(f"- 🏷️ **{type_he}** &nbsp;·&nbsp; `{type_en}`")
            elif type_he:
                parts.append(f"- 🏷️ **{type_he}**")
            elif type_en:
                parts.append(f"- 🏷️ **{type_en}**")
            elif name:
                parts.append(f"- **{name}**")
            if name and (type_he or type_en):
                parts.append(f"  &nbsp;&nbsp;📄 {name}")
            if thickness:
                parts.append(f"  &nbsp;&nbsp;📏 עובי: `{thickness}`")
            if std:
                parts.append(f"  &nbsp;&nbsp;📜 תקן: `{std}`")
            if rohs is True:
                parts.append("  &nbsp;&nbsp;🌱 **RoHS** ✓")
            if parts:
                st.markdown("  \n".join(parts))
        else:
            text = str(item or "").strip()
            if text:
                st.markdown(f"- {text}")

    # ═══════════════════════════════════════════════════
    # 🥇 בלוק #1 — ציפויים, צביעות ותקנים (הכי חשוב)
    # ═══════════════════════════════════════════════════
    st.markdown("### 🎨 ציפויים, צביעות ותקנים")

    # מיפוי ציפוי → רשימת מאסטרים מתאימים (לפי id של האובייקט)
    matches = r.get("master_matches", []) or []
    matches_by_id = {id(entry.get("coating")): entry.get("matches", []) for entry in matches}

    def _render_top_master(coat_obj):
        """מציג את המאסטר המוביל ליד הציפוי."""
        top = matches_by_id.get(id(coat_obj)) or []
        if not top:
            return
        m = top[0]
        score = m.get("score", 0)
        if score >= 70:
            bg, fg = "#d1e7dd", "#0a3622"
        elif score >= 50:
            bg, fg = "#fff3cd", "#664d03"
        else:
            bg, fg = "#f8d7da", "#58151c"
        st.markdown(
            f'<div dir="rtl" style="unicode-bidi:plaintext; background:{bg}; '
            f'color:{fg}; padding:0.45em 0.8em; border-radius:0.4em; '
            f'margin:0.25em 0 0.7em 1.5em; font-size:0.92em; line-height:1.5; '
            f'border-right:3px solid {fg};">'
            f'🎯 <b>מאסטר מוביל:</b> <code>{m["master_id"]}</code> '
            f'&nbsp;·&nbsp; {m["desc"]} '
            f'&nbsp;·&nbsp; 📜 <code>{m["standard"]}</code> '
            f'&nbsp;·&nbsp; 📏 <code>{m["thickness"] or "—"}</code> '
            f'&nbsp;·&nbsp; <b>ציון: {score}</b>'
            f'</div>',
            unsafe_allow_html=True,
        )

    coatings = r.get("coating_processes", []) or []
    paintings = r.get("painting_processes", []) or []
    if coatings:
        st.markdown("**ציפוי:**")
        for c in coatings:
            _render_proc(c)
            _render_top_master(c)
    if paintings:
        st.markdown("**צביעה:**")
        for p in paintings:
            _render_proc(p)
            _render_top_master(p)
    if not coatings and not paintings:
        st.caption("לא נמצאו תהליכי ציפוי/צביעה")

    # תקנים נוספים (שלא צמודים לתהליך)
    used_stds = set()
    for item in coatings + paintings:
        if isinstance(item, dict) and item.get("standard"):
            used_stds.add(item["standard"].strip())
    extra_stds = [s for s in (r.get("standards") or []) if s and s.strip() not in used_stds]
    if extra_stds:
        st.markdown("**תקנים נוספים:** " + " &nbsp;·&nbsp; ".join(f"`{s}`" for s in extra_stds))

    st.divider()

    # ═══════════════════════════════════════════════════
    # 🥈 בלוק #2 — חלופות מאסטרים נוספות (#2 ו-#3)
    # ═══════════════════════════════════════════════════
    matches = r.get("master_matches", []) or []
    has_alternatives = any(len(e.get("matches", [])) > 1 for e in matches)
    if has_alternatives:
        with st.expander("🎯 חלופות מאסטרים נוספות (#2-#3 לכל ציפוי)", expanded=False):
            for entry in matches:
                coat = entry.get("coating", {}) or {}
                top = entry.get("matches", []) or []
                if len(top) <= 1:
                    continue
                head_he = (coat.get("type_he") or coat.get("name") or "").strip()
                std = (coat.get("standard") or "").strip()
                std_sub = f" · 📜 `{std}`" if std else ""
                st.markdown(f"**🏷️ {head_he}**{std_sub}")
                for i, m in enumerate(top[1:], 2):
                    score = m.get("score", 0)
                    if score >= 70:
                        bg, fg = "#d1e7dd", "#0a3622"
                    elif score >= 50:
                        bg, fg = "#fff3cd", "#664d03"
                    else:
                        bg, fg = "#f8d7da", "#58151c"
                    st.markdown(
                        f'<div dir="rtl" style="unicode-bidi:plaintext; background:{bg}; '
                        f'color:{fg}; padding:0.5em 0.85em; border-radius:0.4em; '
                        f'margin-bottom:0.35em; line-height:1.5; font-size:0.95em;">'
                        f'<b>#{i} · {m["master_id"]}</b> &nbsp;·&nbsp; {m["desc"]}<br>'
                        f'📜 <code>{m["standard"]}</code> &nbsp;·&nbsp; '
                        f'📏 <code>{m["thickness"] or "—"}</code> &nbsp;·&nbsp; '
                        f'<b>ציון: {score}</b>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
        st.divider()

    # ═══════════════════════════════════════════════════
    # 🥉 בלוק #3 — אריזה
    # ═══════════════════════════════════════════════════
    pkg = r.get("packaging_notes") or {}
    pkg_he = (pkg.get("he") or "").strip() if isinstance(pkg, dict) else ""
    pkg_en = (pkg.get("en") or "").strip() if isinstance(pkg, dict) else ""
    if pkg_he or pkg_en:
        st.markdown("### 📦 הערות אריזה")
        if pkg_he:
            st.markdown(
                f'<div dir="rtl" style="unicode-bidi:plaintext; background:#fff3cd; '
                f'color:#664d03; padding:0.6em 0.9em; border-radius:0.4em; margin-bottom:0.4em;">'
                f'🇮🇱 {pkg_he}</div>',
                unsafe_allow_html=True,
            )
        if pkg_en:
            st.markdown(
                f'<div dir="ltr" style="background:#fff3cd; color:#664d03; '
                f'padding:0.6em 0.9em; border-radius:0.4em;">🇬🇧 {pkg_en}</div>',
                unsafe_allow_html=True,
            )
        st.divider()

    # ═══════════════════════════════════════════════════
    # בלוק #4 — תהליכים מלווים
    # ═══════════════════════════════════════════════════
    additional = r.get("additional_processes", []) or []
    if additional:
        st.markdown("### 🛠️ תהליכים מלווים / נוספים")
        for a in additional:
            if isinstance(a, dict):
                en = (a.get("name_en") or "").strip()
                he = (a.get("name_he") or "").strip()
                if he and en:
                    st.markdown(f"- **{he}**  \n  &nbsp;&nbsp;🇬🇧 `{en}`")
                elif he:
                    st.markdown(f"- **{he}**")
                elif en:
                    st.markdown(f"- `{en}`")
            else:
                text = str(a or "").strip()
                if text:
                    st.markdown(f"- {text}")
        st.divider()

    # ═══════════════════════════════════════════════════
    # בלוק #5 — NOTES (מתקפל, בסוף)
    # ═══════════════════════════════════════════════════
    notes = r.get("notes", "")
    with st.expander("📝 הערות השרטוט (NOTES) — לחץ להצגה", expanded=False):
        if notes:
            st.info(notes)
        else:
            st.caption("אין הערות")

    with st.expander("📄 JSON מלא"):
        display_data = {k: v for k, v in r.items() if not k.startswith("_")}
        st.json(display_data)

    # ─────────────────────────────────────
    # שמירה
    # ─────────────────────────────────────
    st.divider()
    st.markdown("### 3️⃣ שמור תוצאה")
    _render_stage_model_feedback(cost_info, expanded=False)
    _render_validation_warnings(r)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = Path(st.session_state.filename).stem

    col_s1, col_s2, col_s3 = st.columns(3)

    with col_s1:
        if st.button("💾 שמור JSON", use_container_width=True):
            path = save_to_json(r, OUTPUT_DIR / f"{base_name}_{timestamp}.json")
            st.success(f"נשמר: `{path.name}`")

    with col_s2:
        if st.button("📊 שמור Excel", use_container_width=True):
            path = save_to_excel(r, OUTPUT_DIR / f"{base_name}_{timestamp}.xlsx")
            st.success(f"נשמר: `{path.name}`")

    with col_s3:
        if st.button("🔄 שרטוט חדש", use_container_width=True):
            st.session_state.result = None
            st.session_state.filename = None
            st.rerun()

# ─────────────────────────────────────
# Sidebar — פאנל מנהל + קבצים שמורים
# ─────────────────────────────────────
_render_sidebar_footer()
