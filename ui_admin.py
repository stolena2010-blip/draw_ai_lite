"""
פאנל מנהל מערכת — דיאלוג מודאלי עם מידע עלויות + הגדרות.

מוצג ע"י app.py כש-st.session_state["_show_admin"] == True.
חולץ מ-app.py כדי לצמצם את גודל הקובץ המרכזי.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from core.azure_client import (
    MODEL_GPT_4O,
    MODEL_GPT_5_4,
    SUPPORTED_MODELS,
    _active_model,
    enabled_modes,
    get_masters_xlsx_path,
    is_fallback_enabled,
    save_runtime_settings,
)
from core.cost_tracker import get_aggregate_stats


_MODEL_LABELS = {
    MODEL_GPT_4O: "🟢 GPT-4o Vision (פשוט, מהיר)",
    MODEL_GPT_5_4: "🧠 GPT-5.4 (Reasoning, חזק)",
}

_STAGE_COLUMN_MAP = {
    "stage": "שלב",
    "model": "מודל בפועל",
    "input_tokens": "Input tokens",
    "output_tokens": "Output tokens",
    "total_cost_usd": "עלות $",
}


def _render_stages_df(stages: list) -> None:
    if not stages:
        return
    df = pd.DataFrame(stages)
    cols = [c for c in _STAGE_COLUMN_MAP if c in df.columns]
    df = df[cols].rename(columns=_STAGE_COLUMN_MAP)
    st.dataframe(df, use_container_width=True, hide_index=True)


def _render_aggregate_stats() -> None:
    st.markdown("#### 📊 עלויות מצטברות (כל השרטוטים שנותחו)")
    stats = get_aggregate_stats()
    if stats:
        a1, a2, a3 = st.columns(3)
        a1.metric("שרטוטים שנותחו", stats["count"])
        a2.metric("סה\"כ עלות", f"${stats['total_cost_usd']:.2f}")
        a3.metric("ממוצע לשרטוט", f"${stats['avg_cost_usd']:.4f}")
    else:
        st.caption("עדיין לא נותחו שרטוטים")


def _render_assembly_costs(asm_results: list) -> None:
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
            _render_stages_df(ci.get("stages", []))


def _render_single_costs(r: dict) -> None:
    cost_info = r.get("_cost_info", {})
    if not cost_info:
        st.caption("אין נתוני עלויות לשרטוט הנוכחי")
        return
    st.markdown("#### 🎯 עלות השרטוט הנוכחי")
    c1, c2, c3 = st.columns(3)
    c1.metric("💰 עלות $", f"${cost_info.get('total_cost_usd', 0):.4f}")
    c2.metric("💱 בשקלים", f"₪{cost_info.get('total_cost_ils', 0):.3f}")
    c3.metric(
        "🔤 טוקנים",
        f"{cost_info.get('input_tokens', 0):,} + {cost_info.get('output_tokens', 0):,}",
    )
    st.markdown("##### פירוט לפי שלב")
    _render_stages_df(cost_info.get("stages", []))


def _render_settings_section() -> None:
    st.markdown("#### ⚙️ הגדרות מערכת (מנהל)")

    current_model = _active_model()
    model_idx = (
        SUPPORTED_MODELS.index(current_model)
        if current_model in SUPPORTED_MODELS else 0
    )

    cset1, cset2 = st.columns([2, 1])
    with cset1:
        new_model = st.radio(
            "מודל AI פעיל",
            options=list(SUPPORTED_MODELS),
            index=model_idx,
            format_func=lambda x: _MODEL_LABELS.get(x, x),
            key="admin_active_model",
        )
    with cset2:
        new_fb = st.checkbox(
            "Fallback אוטומטי",
            value=is_fallback_enabled(),
            key="admin_fallback",
            help="מעבר אוטומטי למודל השני אם הראשי נכשל",
        )

    current_modes = enabled_modes()
    mode_options = ["single", "assembly"]
    new_modes = st.multiselect(
        "גישה למצבי עבודה",
        options=mode_options,
        default=[m for m in current_modes if m in mode_options] or mode_options,
        format_func=lambda x: "🔍 שרטוט בודד" if x == "single" else "🧩 מכלולים מרובים",
        key="admin_enabled_modes",
        help="בחר אילו מצבים יוצגו למשתמש בממשק",
    )

    st.divider()
    st.markdown("#### 📁 נתיבים")
    current_masters_path = get_masters_xlsx_path()
    new_masters_path = st.text_input(
        "📄 נתיב ל-Masters.xlsx",
        value=current_masters_path,
        placeholder="C:\\Data\\Masters.xlsx או השאר ריק לברירת מחדל",
        help="נתיב מוחלט או יחסי לקובץ Masters.xlsx. אם ריק, יחפש ב-root ב-.env",
        key="admin_masters_path",
    )

    if not new_modes:
        st.error("חובה לבחור לפחות מצב עבודה אחד")
        return

    changed = (
        new_model != current_model
        or new_fb != is_fallback_enabled()
        or set(new_modes) != set(current_modes)
        or new_masters_path != current_masters_path
    )
    if changed:
        if st.button("💾 שמור הגדרות מערכת", use_container_width=True):
            save_runtime_settings(
                active_model=new_model,
                fallback_enabled=new_fb,
                enabled_modes=new_modes,
                masters_xlsx_path=new_masters_path,
            )
            if st.session_state.get("app_mode") not in new_modes:
                st.session_state["app_mode"] = new_modes[0]
            st.success("✅ הגדרות נשמרו")
            st.rerun()
    else:
        st.caption("אין שינויים להגדרה")


@st.dialog("🛠️ פאנל מנהל מערכת", width="large")
def show_admin_panel():
    """דיאלוג מודאלי — עלויות + הגדרות מערכת."""
    r = st.session_state.get("result") or {}
    asm_results = st.session_state.get("asm_results") or []
    is_assembly = st.session_state.get("app_mode") == "assembly"

    _render_aggregate_stats()
    st.divider()

    if is_assembly and asm_results:
        _render_assembly_costs(asm_results)
    else:
        _render_single_costs(r)

    st.divider()
    _render_settings_section()

    if st.button("סגור", use_container_width=True):
        st.session_state["_show_admin"] = False
        st.rerun()


def render_sidebar_footer() -> None:
    """סרגל צד תחתון — כפתור פתיחת פאנל מנהל."""
    with st.sidebar:
        st.divider()
        st.markdown("### 📊 פאנל מנהל")
        if st.button("🛠️ פתח פאנל מנהל", use_container_width=True,
                     key="open_admin_btn"):
            st.session_state["_show_admin"] = True
            st.rerun()


def maybe_open_admin_panel() -> None:
    """נקרא בכל rerun — פותח את הדיאלוג אם הדגל דולק."""
    if st.session_state.get("_show_admin"):
        st.session_state["_show_admin"] = False
        show_admin_panel()
