"""
UI של מוד "מכלולים מרובים".

מנתח מספר שרטוטי PDF בלולאה — כל אחד עובר את אותו pipeline מלא כמו
במוד "שרטוט בודד" (Stage 1 → Stage 2 → Stage 3 → התאמה למאסטר).
אין קשר בין השרטוטים, אין עץ מוצר ואין ניתוח קשרים.

התצוגה לכל שרטוט זהה לחלוטין לזו שבמוד הבודד (ui_single_view), עם דפדוף
בין השרטוטים. בסוף הדף — הורדת דוחות מאוחדים (JSON / Excel / PDF).
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import streamlit as st

from core.extractor import extract_drawing
from core.exceptions import format_error_for_ui, get_streamlit_level
from storage.save_handler import save_to_json, save_batch_to_excel
from storage.pdf_report import build_batch_pdf
from ui_single_view import (
    render_drawing_result,
    render_validation_warnings,
    render_stage_model_feedback,
)

logger = logging.getLogger(__name__)


def _show_error(exc: Exception, *, prefix: str = "") -> None:
    """מציג שגיאה ידידותית למשתמש."""
    level = get_streamlit_level(exc)
    msg = format_error_for_ui(exc, include_technical=True)
    if prefix:
        msg = f"**{prefix}**\n\n{msg}"
    getattr(st, level)(msg)


def _init_state():
    if "asm_results" not in st.session_state:
        st.session_state["asm_results"] = []  # list[dict]
    if "asm_index" not in st.session_state:
        st.session_state["asm_index"] = 0


def _process_pdf(uploaded_file, output_dir: Path, ocr_enabled: bool) -> dict | None:
    """מנתח קובץ PDF יחיד באמצעות ה-pipeline של מוד שרטוט בודד."""
    temp_path = output_dir / f"_asm_temp_{uploaded_file.name}"
    with open(temp_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    try:
        result = extract_drawing(temp_path, use_ocr_fallback=ocr_enabled)
        # שומר את שם הקובץ המקורי (extract_drawing משתמש בשם הקובץ הזמני)
        result["source_filename"] = uploaded_file.name
        return result
    except Exception as exc:
        logger.exception("Assembly extract failed for %s", uploaded_file.name)
        _show_error(exc, prefix=f"שגיאה ב-{uploaded_file.name}")
        return None
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _render_export_pair(*, button_label: str, spinner_text: str,
                        build_fn, out_path: Path, state_key: str,
                        mime: str, btn_key: str, dl_key: str,
                        err_label: str):
    """מציג "צור קובץ → הורד" עם state בין reruns של Streamlit."""
    if st.button(button_label, use_container_width=True,
                 type="primary", key=btn_key):
        try:
            with st.spinner(spinner_text):
                build_fn(out_path)
            st.session_state[state_key] = str(out_path)
            st.success(f"נוצר: `{out_path.name}`")
        except Exception as exc:
            logger.exception("%s export failed", err_label)
            _show_error(exc, prefix=f"שגיאה ביצירת {err_label}")

    saved = st.session_state.get(state_key)
    if saved and Path(saved).exists():
        with open(saved, "rb") as fh:
            st.download_button(
                label=f"⬇️ הורד {Path(saved).name}",
                data=fh.read(),
                file_name=Path(saved).name,
                mime=mime,
                use_container_width=True,
                key=dl_key,
            )


# ═══════════════════════════════════════════════════════════════
# נקודת כניסה
# ═══════════════════════════════════════════════════════════════
def render_assembly_mode(output_dir: Path):
    """מצייר את כל מסך מוד המכלולים."""
    _init_state()

    st.caption("🧩 **מצב מכלולים** — העלה מספר שרטוטי PDF · "
               "כל שרטוט ינותח בנפרד (כמו במוד בודד) · "
               "בסוף — הורדת דוחות מאוחדים")

    # ─── 1. העלאת קבצים ───
    st.markdown("### 1️⃣ העלה שרטוטי PDF")
    files = st.file_uploader(
        "גרור שרטוטי PDF או לחץ לבחירה",
        type=["pdf"],
        accept_multiple_files=True,
        key="asm_uploader",
    )

    col_a, col_b = st.columns([3, 1])
    with col_a:
        do_analyze = st.button(
            f"🔍 נתח {len(files) if files else 0} שרטוטים",
            type="primary",
            disabled=not files,
            use_container_width=True,
        )
    with col_b:
        if st.button("🗑️ נקה", use_container_width=True):
            st.session_state["asm_results"] = []
            st.session_state["asm_index"] = 0
            # איפוס state של הורדות
            for key in ("asm_pdf_path", "asm_xlsx_path", "asm_json_path"):
                st.session_state.pop(key, None)
            st.rerun()

    # ─── 2. ניתוח ───
    if do_analyze and files:
        progress = st.progress(0.0, text="מתחיל ניתוח...")
        results: list[dict] = []
        for i, f in enumerate(files, 1):
            progress.progress(
                (i - 1) / len(files),
                text=f"🔄 מנתח {i}/{len(files)}: {f.name}",
            )
            res = _process_pdf(f, output_dir, ocr_enabled=True)
            if res is not None:
                results.append(res)
        progress.progress(1.0, text="✅ ניתוח הסתיים")
        st.session_state["asm_results"] = results
        st.session_state["asm_index"] = 0
        # איפוס state של קבצים שנוצרו בסשן קודם
        for key in ("asm_pdf_path", "asm_xlsx_path", "asm_json_path"):
            st.session_state.pop(key, None)
        st.success(f"✅ נותחו {len(results)} שרטוטים")

    results = st.session_state["asm_results"]
    if not results:
        st.info("📥 העלה שרטוטי PDF ולחץ 'נתח' כדי להתחיל.")
        return

    # ─── 3. דפדוף בין שרטוטים ───
    st.divider()
    st.markdown("### 2️⃣ דפדוף בין שרטוטים")

    n = len(results)
    idx = max(0, min(st.session_state["asm_index"], n - 1))

    def _goto(new_idx: int):
        new_idx = max(0, min(new_idx, n - 1))
        st.session_state["asm_index"] = new_idx

    def _on_jump_change():
        st.session_state["asm_index"] = st.session_state["asm_jump"]

    if st.session_state.get("asm_jump") != idx:
        st.session_state["asm_jump"] = idx

    nav_a, nav_b, nav_c, nav_d, nav_e = st.columns([1, 1, 3, 1, 1])
    with nav_a:
        if st.button("⏮️ ראשון", use_container_width=True, disabled=idx == 0):
            _goto(0)
            st.rerun()
    with nav_b:
        if st.button("◀️ הקודם", use_container_width=True, disabled=idx == 0):
            _goto(idx - 1)
            st.rerun()
    with nav_c:
        labels = [
            f"{i+1}. {(r.get('part_number') or r.get('source_filename') or '?')[:40]}"
            for i, r in enumerate(results)
        ]
        st.selectbox(
            "קפוץ לשרטוט", options=list(range(n)),
            format_func=lambda i: labels[i],
            key="asm_jump",
            on_change=_on_jump_change,
            label_visibility="collapsed",
        )
    with nav_d:
        if st.button("▶️ הבא", use_container_width=True, disabled=idx == n - 1):
            _goto(idx + 1)
            st.rerun()
    with nav_e:
        if st.button("⏭️ אחרון", use_container_width=True, disabled=idx == n - 1):
            _goto(n - 1)
            st.rerun()

    st.caption(f"📄 מציג שרטוט **{idx + 1}** מתוך **{n}** · "
               f"`{results[idx].get('source_filename', '')}`")

    # ─── 4. תצוגת השרטוט הנבחר (זהה למוד בודד) ───
    current = results[idx]
    if current.get("_ocr_used"):
        st.info("🔍 OCR הופעל כגיבוי לניתוח שרטוט זה")

    render_drawing_result(current, key_prefix=f"asm_{idx}", with_toggle=True)
    render_validation_warnings(current)
    render_stage_model_feedback(
        current.get("_cost_info") or {},
        title="🤖 מודל בפועל בשלבי ניתוח השרטוט הזה",
        expanded=False,
    )

    # ─── 5. הורדת דוחות מאוחדים ───
    st.divider()
    st.markdown("### 3️⃣ הורדת דוחות מאוחדים")
    st.caption("דוחות שמקבצים את כל השרטוטים שנותחו בסשן זה.")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    tab_json, tab_xlsx, tab_pdf = st.tabs([
        "💾 JSON",
        "📊 Excel",
        "📕 PDF",
    ])

    with tab_json:
        st.caption("קובץ JSON יחיד שמכיל את כל התוצאות של השרטוטים שנותחו.")
        _render_export_pair(
            button_label="💾 צור JSON מאוחד",
            spinner_text="💾 שומר JSON...",
            build_fn=lambda p: save_to_json({"drawings": results}, p),
            out_path=output_dir / f"_assembly_{ts}.json",
            state_key="asm_json_path",
            mime="application/json",
            btn_key="btn_json",
            dl_key="dl_json",
            err_label="JSON",
        )

    with tab_xlsx:
        st.caption("קובץ Excel מאוחד עם גיליון מרכזי לכל שרטוט + "
                   "גיליונות מצטברים (ציפויים, מאסטרים, תקנים, אזהרות).")
        _render_export_pair(
            button_label="📊 צור Excel מאוחד",
            spinner_text="📊 מייצר Excel...",
            build_fn=lambda p: save_batch_to_excel(results, p),
            out_path=output_dir / f"_assembly_{ts}.xlsx",
            state_key="asm_xlsx_path",
            mime="application/vnd.openxmlformats-officedocument."
                 "spreadsheetml.sheet",
            btn_key="btn_xlsx",
            dl_key="dl_xlsx",
            err_label="Excel",
        )

    with tab_pdf:
        st.caption("דוח PDF שמציג את כל השרטוטים ברצף — כל שרטוט "
                   "בעמוד משלו עם פירוט מלא (פריט, חומר, ציפויים, "
                   "תקנים, הערות, מאסטר מוביל).")
        _render_export_pair(
            button_label="📕 צור PDF מאוחד",
            spinner_text="📄 מייצר PDF...",
            build_fn=lambda p: build_batch_pdf(results, p),
            out_path=output_dir / f"_assembly_{ts}.pdf",
            state_key="asm_pdf_path",
            mime="application/pdf",
            btn_key="btn_pdf",
            dl_key="dl_pdf",
            err_label="PDF",
        )
