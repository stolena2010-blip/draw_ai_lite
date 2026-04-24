"""
רנדור תוצאת שרטוט בודד — משותף בין מוד "שרטוט בודד" למוד "מכלולים".

מכיל את כל ההיגיון להצגת שרטוט אחד (מבט-על, מאסטרים מובילים,
ציפויים/צביעות, חלופות, אריזה, הערות, ולידציה, פירוט מודלים).

Key prefixes: כל widget מקבל `key_prefix` כדי שאפשר יהיה לרנדר את
אותו שרטוט מספר פעמים באותו דף (למשל מוד מכלולים עם דפדוף).
"""
from __future__ import annotations

from pathlib import Path
from datetime import datetime

import streamlit as st


def _coating_match_key(c) -> tuple:
    """מפתח מבני לציפוי לצורך שיוך מ-master_matches.

    משתמש ב-type/type_he/standard/thickness במקום id() — עמיד בפני
    round-trip דרך JSON (cache), שבו זהות האובייקט אובדת.
    """
    if not isinstance(c, dict):
        return (str(c), "", "", "")
    return (
        (c.get("type_he") or "").strip(),
        (c.get("type") or "").strip(),
        (c.get("standard") or "").strip(),
        (c.get("thickness") or "").strip(),
    )


def _build_match_lookup(master_matches: list) -> dict:
    """בונה מיפוי מפתח־מבני → רשימת מאסטרים לכל ציפוי."""
    lookup: dict = {}
    for entry in master_matches or []:
        if not isinstance(entry, dict):
            continue
        key = _coating_match_key(entry.get("coating"))
        lookup.setdefault(key, entry.get("matches") or [])
    return lookup


_SEVERITY_ICON = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}

_MATCH_ICON = {"full": "✅", "partial": "🟡", "none": "❌", "na": "⚪"}
_MATCH_LABEL = {
    "full": "התאמה מלאה",
    "partial": "התאמה חלקית",
    "none": "ללא התאמה",
    "na": "לא רלוונטי",
}
_MATCH_BG = {
    "full": "#d1e7dd",
    "partial": "#fff3cd",
    "none": "#f8d7da",
    "na": "#e9ecef",
}
_CRIT_LABEL = {
    "coating_type": "סוג ציפוי / תהליך",
    "standards": "מפרטים (תקנים)",
    "thickness": "עובי",
    "rohs": "RoHS",
    "phosphorus": "רמת זרחן",
}


def _format_criterion_detail(crit_key: str, info: dict) -> str:
    status = info.get("status", "na")
    parts: list[str] = []

    if crit_key == "coating_type":
        coat = info.get("coat", "")
        master = info.get("master") or info.get("note", "")
        if status == "full":
            parts.append(f"<code>{coat}</code> ↔ <code>{master or coat}</code>")
        elif status == "partial":
            parts.append(f"<code>{coat}</code> ~ <code>{master}</code>")
        elif status == "none":
            parts.append(f"<code>{coat}</code> ≠ <code>{master}</code>")
        else:
            parts.append(info.get("reason", ""))

    elif crit_key == "standards":
        if info.get("matched"):
            parts.append("✓ התאימו: " + ", ".join(f"<code>{s}</code>" for s in info["matched"]))
        if info.get("only_in_coat"):
            parts.append("⚠️ רק בשרטוט: " + ", ".join(f"<code>{s}</code>" for s in info["only_in_coat"]))
        if info.get("only_in_master"):
            parts.append("ℹ️ רק במאסטר: " + ", ".join(f"<code>{s}</code>" for s in info["only_in_master"]))
        if not parts:
            parts.append(info.get("reason", ""))

    elif crit_key == "thickness":
        coat_range = info.get("coat_range")
        master_range = info.get("master_range")
        if coat_range and master_range:
            cr = f"{coat_range[0]:.0f}-{coat_range[1]:.0f}μm"
            mr = f"{master_range[0]:.0f}-{master_range[1]:.0f}μm"
            parts.append(f"שרטוט <code>{cr}</code> ↔ מאסטר <code>{mr}</code>")
            if info.get("overlap_pct") is not None:
                parts.append(f"חפיפה {info['overlap_pct']}%")
        elif coat_range:
            cr = f"{coat_range[0]:.0f}-{coat_range[1]:.0f}μm"
            parts.append(f"שרטוט <code>{cr}</code>")
            parts.append(info.get("reason", ""))
        else:
            parts.append(info.get("reason", ""))

    elif crit_key == "rohs":
        parts.append(info.get("note") or info.get("reason", ""))

    elif crit_key == "phosphorus":
        if info.get("coat_phos"):
            parts.append(f"שרטוט: <code>{info['coat_phos']}</code>")
        if info.get("master_phos"):
            parts.append(f"מאסטר: <code>{info['master_phos']}</code>")
        if not parts:
            parts.append(info.get("reason", ""))

    return " &nbsp;·&nbsp; ".join(p for p in parts if p)


def _render_criteria(details: dict) -> None:
    for crit_key, info in details.items():
        status = info.get("status", "na")
        icon = _MATCH_ICON.get(status, "")
        label = _MATCH_LABEL.get(status, "?")
        bg = _MATCH_BG.get(status, "#f8f9fa")
        crit_name = _CRIT_LABEL.get(crit_key, crit_key)
        detail_html = _format_criterion_detail(crit_key, info)

        st.markdown(
            f'<div dir="rtl" style="unicode-bidi:plaintext; background:{bg}; '
            f'padding:0.4em 0.85em; border-radius:0.35em; margin-bottom:0.3em; '
            f'font-size:0.92em; line-height:1.5;">'
            f'<span style="font-weight:700;">{icon} {crit_name}:</span> '
            f'<span style="opacity:0.85;">{label}</span>'
            + (f' &nbsp;·&nbsp; <span style="opacity:0.9;">{detail_html}</span>' if detail_html else '')
            + '</div>',
            unsafe_allow_html=True,
        )


def _render_match_breakdown(match: dict) -> None:
    layer_details = match.get("layer_details") or []
    if layer_details:
        for ld in layer_details:
            coat = ld.get("coating") or {}
            layer_label = (coat.get("type_he") or coat.get("type")
                           or ld.get("layer") or "").strip() or "שכבה"
            st.markdown(
                f'<div dir="rtl" style="unicode-bidi:plaintext; font-weight:700; '
                f'color:#7AB141; margin:0.5em 0 0.3em 0;">🧪 שכבה: {layer_label}</div>',
                unsafe_allow_html=True,
            )
            _render_criteria(ld.get("details") or {})
    else:
        details = match.get("match_details") or {}
        if details:
            _render_criteria(details)
        else:
            st.caption("אין פירוט התאמה זמין (תוצאה מ-cache ישן — נסי לרוץ מחדש).")


def render_validation_warnings(result: dict) -> None:
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


def render_stage_model_feedback(cost_info: dict,
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


def _render_top_masters_cards(r: dict, key_prefix: str) -> None:
    """📌 מאסטר מוביל — כרטיסיות גדולות עם העתקה לכל ציפוי."""
    matches = r.get("master_matches", []) or []
    top_masters = []
    for entry in matches:
        mlist = entry.get("matches") or []
        if mlist:
            top_masters.append((entry.get("coating") or {}, mlist[0]))
    if not top_masters:
        return

    st.markdown(
        '<div dir="rtl" style="unicode-bidi:plaintext; text-align:right; '
        'font-weight:700; color:#7AB141; font-size:1.1em; '
        'margin:0.4em 0 0.5em 0;">📌 מאסטר מוביל</div>',
        unsafe_allow_html=True,
    )
    for i, (coat, m) in enumerate(top_masters):
        head = (coat.get("type_he") or coat.get("type") or coat.get("name") or "")[:40]
        sc = m.get("score", 0)
        mid = m["master_id"]
        desc = (m.get("desc") or "").strip()[:80]
        std_m = (m.get("standard") or "").strip()
        thk_m = (m.get("thickness") or "").strip()

        if sc >= 70:
            bg, fg, border = "#d1e7dd", "#0a3622", "#198754"
        elif sc >= 50:
            bg, fg, border = "#fff3cd", "#664d03", "#fd7e14"
        else:
            bg, fg, border = "#f8d7da", "#58151c", "#dc3545"

        card_col, copy_col = st.columns([4, 1])
        with card_col:
            meta_bits = []
            if std_m:
                meta_bits.append(f'📜 <code>{std_m}</code>')
            if thk_m:
                meta_bits.append(f'📏 <code>{thk_m}</code>')
            meta_html = " &nbsp;·&nbsp; ".join(meta_bits)
            st.markdown(
                f'<div dir="rtl" style="unicode-bidi:plaintext; text-align:right; '
                f'background:{bg}; border:2px solid {border}; '
                f'border-radius:0.6em; padding:0.7em 1em; margin-bottom:0.4em; '
                f'box-shadow:0 2px 4px rgba(0,0,0,0.08);">'
                f'<div style="display:flex; justify-content:space-between; '
                f'align-items:center; margin-bottom:0.45em;">'
                f'<span style="font-weight:700; color:{fg}; font-size:1.05em;">'
                f'🏷️ {head}</span>'
                f'<span style="background:{border}; color:white; '
                f'padding:0.15em 0.7em; border-radius:0.4em; '
                f'font-size:0.95em; font-weight:700;">ציון {sc}</span>'
                f'</div>'
                f'<div style="font-family:Consolas,Monaco,monospace; '
                f'font-size:1.8em; font-weight:700; color:{border}; '
                f'letter-spacing:0.05em; margin:0.2em 0; text-align:right; '
                f'direction:ltr; unicode-bidi:plaintext;">'
                f'{mid}</div>'
                f'<div style="color:{fg}; font-size:0.95em; '
                f'margin-bottom:0.35em;">{desc}</div>'
                + (f'<div style="font-size:0.88em;">{meta_html}</div>' if meta_html else '')
                + '</div>',
                unsafe_allow_html=True,
            )
        with copy_col:
            st.markdown(
                '<div style="text-align:center; color:#6c757d; '
                'font-size:0.8em; margin-top:0.4em;">📋 העתק:</div>',
                unsafe_allow_html=True,
            )
            st.code(mid, language=None)

        if m.get("match_details") or m.get("layer_details"):
            with st.expander(f"🔍 פירוט התאמה למאסטר {mid}", expanded=False):
                _render_match_breakdown(m)


def _render_overview_card(r: dict) -> None:
    """🎯 מבט-על — כרטיס גדול עם פריט/שרטוט/חומר/ציפויים/צביעות/תקנים/אריזה."""
    ov_pn = r.get("part_number") or "—"
    ov_dn = r.get("drawing_number") or "—"
    ov_rev = r.get("revision") or "—"
    ov_cust = r.get("customer") or "—"
    ov_mat = r.get("material") or "—"
    ov_coats = r.get("coating_processes", []) or []
    ov_paints = r.get("painting_processes", []) or []
    ov_matches = r.get("master_matches", []) or []
    ov_match_by_key = _build_match_lookup(ov_matches)
    ov_add = r.get("additional_processes", []) or []
    ov_pkg = r.get("packaging_notes") or {}
    ov_pkg_he = (ov_pkg.get("he") or "").strip() if isinstance(ov_pkg, dict) else ""

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
        bits = [f'<b>{head}</b>{rohs_mark}']
        if std:
            bits.append(f'📜 <code>{std}</code>')
        if thick:
            bits.append(f'📏 <code>{thick}</code>')
        top = ov_match_by_key.get(_coating_match_key(p)) or []
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
        line2 = ""
        if name and name.strip().upper() != head.strip().upper():
            line2 = (
                f'<div style="margin:0 0 0.5em 1.2em; color:#495057; '
                f'font-size:0.88em; line-height:1.5; word-break:break-word;">'
                f'📄 {name}</div>'
            )
        return line1 + line2

    procs_html = "".join(_ov_chip(c) for c in ov_coats)
    procs_html += "".join(_ov_chip(p) for p in ov_paints)
    if not procs_html:
        procs_html = '<div style="color:#6c757d;">— ללא ציפוי/צביעה —</div>'

    used_stds = {(it.get("standard") or "").strip()
                 for it in ov_coats + ov_paints if isinstance(it, dict)}
    extra = [s for s in (r.get("standards") or [])
             if s and s.strip() and s.strip() not in used_stds]
    extra_html = ""
    if extra:
        extra_html = (
            '<div style="margin-top:0.4em;"><span style="color:#6c757d;">תקנים נוספים:</span> '
            + " ".join(f'<code>{s}</code>' for s in extra) + '</div>'
        )

    add_html = ""
    if ov_add:
        names = []
        for a in ov_add:
            if isinstance(a, dict):
                he = (a.get("name_he") or "").strip()
                if he:
                    names.append(he)
            else:
                t = str(a or "").strip()
                if t:
                    names.append(t)
        if names:
            add_html = (
                '<div style="margin-top:0.4em;"><span style="color:#6c757d;">🛠️ תהליכים נוספים:</span> '
                + " &nbsp;·&nbsp; ".join(names) + '</div>'
            )

    pkg_html = ""
    if ov_pkg_he:
        pkg_html = (
            '<div style="margin-top:0.4em;"><span style="color:#6c757d;">📦 אריזה:</span> '
            + ov_pkg_he + '</div>'
        )

    st.markdown(
        f'<div dir="rtl" style="unicode-bidi:plaintext; text-align:right; '
        f'background:linear-gradient(135deg,#F3F9E8 0%,#FDF1DA 100%); '
        f'border:2px solid #7AB141; border-radius:0.7em; padding:1em 1.2em; '
        f'margin-bottom:1em; word-break:break-word; font-size:0.95em; line-height:1.7;">'
        f'<div style="font-size:1.1em; font-weight:700; color:#7AB141; '
        f'margin-bottom:0.5em; border-bottom:1px solid #C7DFA0; padding-bottom:0.3em;">'
        f'🎯 מבט-על</div>'
        f'<div style="margin-bottom:0.4em;">'
        f'<span style="color:#6c757d;">פריט:</span> <b>{ov_pn}</b> &nbsp;·&nbsp; '
        f'<span style="color:#6c757d;">שרטוט:</span> <b>{ov_dn}</b> &nbsp;·&nbsp; '
        f'<span style="color:#6c757d;">גרסה:</span> <b>{ov_rev}</b> &nbsp;·&nbsp; '
        f'<span style="color:#6c757d;">לקוח:</span> <b>{ov_cust}</b>'
        f'</div>'
        f'<div style="margin-bottom:0.5em;">'
        f'<span style="color:#6c757d;">חומר גלם:</span> <b>{ov_mat}</b>'
        f'</div>'
        f'<div style="border-top:1px dashed #adb5bd; padding-top:0.5em;">'
        f'<span style="color:#6c757d; font-weight:600;">🎨 ציפויים / צביעות:</span>'
        f'{procs_html}'
        f'{extra_html}'
        f'{add_html}'
        f'{pkg_html}'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_proc(item):
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


def _render_top_master_inline(coat_obj, match_lookup) -> None:
    top = match_lookup.get(_coating_match_key(coat_obj)) or []
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


def _render_full_details(r: dict, key_prefix: str) -> None:
    """פירוט מלא: מזהים מקוצר, סיכום עברי, ציפויים+מאסטרים, חלופות, אריזה, נוספים, הערות, JSON."""
    # ─── סרגל מזהים קומפקטי ───
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

    # ═══ ציפויים, צביעות ותקנים ═══
    st.markdown("### 🎨 ציפויים, צביעות ותקנים")
    matches = r.get("master_matches", []) or []
    match_lookup = _build_match_lookup(matches)

    coatings = r.get("coating_processes", []) or []
    paintings = r.get("painting_processes", []) or []
    if coatings:
        st.markdown("**ציפוי:**")
        for c in coatings:
            _render_proc(c)
            _render_top_master_inline(c, match_lookup)
    if paintings:
        st.markdown("**צביעה:**")
        for p in paintings:
            _render_proc(p)
            _render_top_master_inline(p, match_lookup)
    if not coatings and not paintings:
        st.caption("לא נמצאו תהליכי ציפוי/צביעה")

    used_stds = set()
    for item in coatings + paintings:
        if isinstance(item, dict) and item.get("standard"):
            used_stds.add(item["standard"].strip())
    extra_stds = [s for s in (r.get("standards") or []) if s and s.strip() not in used_stds]
    if extra_stds:
        st.markdown("**תקנים נוספים:** " + " &nbsp;·&nbsp; ".join(f"`{s}`" for s in extra_stds))

    st.divider()

    # ═══ חלופות מאסטרים נוספות ═══
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
                    if m.get("match_details") or m.get("layer_details"):
                        with st.expander(
                            f"🔍 פירוט התאמה למאסטר {m['master_id']}",
                            expanded=False,
                        ):
                            _render_match_breakdown(m)
        st.divider()

    # ═══ אריזה ═══
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

    # ═══ תהליכים מלווים ═══
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

    # ═══ NOTES ═══
    notes = r.get("notes", "")
    with st.expander("📝 הערות השרטוט (NOTES) — לחץ להצגה", expanded=False):
        if notes:
            st.info(notes)
        else:
            st.caption("אין הערות")

    with st.expander("📄 JSON מלא"):
        display_data = {k: v for k, v in r.items() if not k.startswith("_")}
        st.json(display_data)


def render_drawing_result(r: dict, *, key_prefix: str = "", with_toggle: bool = True) -> None:
    """רנדור מלא של תוצאת שרטוט — מבט-על, מאסטרים מובילים, ופירוט מלא.

    Args:
        r: dict התוצאה מ-extract_drawing()
        key_prefix: prefix לכל widget key (למנוע התנגשויות ב-Streamlit)
        with_toggle: אם True, מציג toggle "הצג פירוט מלא" שמסתיר/חושף את הפירוט.
                     אם False, הפירוט תמיד מוצג (מצב מכלולים).
    """
    _render_top_masters_cards(r, key_prefix=key_prefix)
    _render_overview_card(r)

    if with_toggle:
        show_full = st.toggle(
            "📋 הצג פירוט מלא",
            value=False,
            key=f"{key_prefix}_show_full" if key_prefix else "show_full_details",
        )
        if not show_full:
            return

    _render_full_details(r, key_prefix=key_prefix)


def _render_export_button(*, label: str, spinner_text: str,
                          build_fn, out_path: Path, state_key: str,
                          mime: str, btn_key: str, dl_key: str,
                          err_label: str):
    """כפתור "צור קובץ → הורד" יחיד שנשאר זמין בין reruns של Streamlit."""
    if st.button(label, use_container_width=True, key=btn_key):
        try:
            with st.spinner(spinner_text):
                build_fn(out_path)
            st.session_state[state_key] = str(out_path)
        except Exception as exc:
            st.error(f"שגיאה ביצירת {err_label}: {exc}")
            st.session_state.pop(state_key, None)

    saved = st.session_state.get(state_key)
    if saved and Path(saved).exists():
        with open(saved, "rb") as fh:
            st.download_button(
                label=f"⬇️ {Path(saved).name}",
                data=fh.read(),
                file_name=Path(saved).name,
                mime=mime,
                use_container_width=True,
                key=dl_key,
            )


def render_save_section_single(r: dict, output_dir: Path, filename: str,
                               *, key_prefix: str = "") -> None:
    """סעיף שמירה של מוד שרטוט בודד — JSON / Excel / PDF עם הורדה + חדש."""
    from storage.save_handler import save_to_json, save_to_excel
    from storage.pdf_report import build_batch_pdf

    st.divider()
    st.markdown("### 3️⃣ שמור תוצאה")
    render_stage_model_feedback(r.get("_cost_info", {}), expanded=False)
    render_validation_warnings(r)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = Path(filename).stem

    col_s1, col_s2, col_s3, col_s4 = st.columns(4)

    with col_s1:
        _render_export_button(
            label="💾 JSON",
            spinner_text="💾 שומר JSON...",
            build_fn=lambda p: save_to_json(r, p),
            out_path=output_dir / f"{base_name}_{timestamp}.json",
            state_key=f"{key_prefix}_json_path",
            mime="application/json",
            btn_key=f"{key_prefix}_save_json",
            dl_key=f"{key_prefix}_dl_json",
            err_label="JSON",
        )

    with col_s2:
        _render_export_button(
            label="📊 Excel",
            spinner_text="📊 מייצר Excel...",
            build_fn=lambda p: save_to_excel(r, p),
            out_path=output_dir / f"{base_name}_{timestamp}.xlsx",
            state_key=f"{key_prefix}_xlsx_path",
            mime="application/vnd.openxmlformats-officedocument."
                 "spreadsheetml.sheet",
            btn_key=f"{key_prefix}_save_xlsx",
            dl_key=f"{key_prefix}_dl_xlsx",
            err_label="Excel",
        )

    with col_s3:
        _render_export_button(
            label="📕 PDF",
            spinner_text="📄 מייצר PDF...",
            build_fn=lambda p: build_batch_pdf([r], p),
            out_path=output_dir / f"{base_name}_{timestamp}.pdf",
            state_key=f"{key_prefix}_pdf_path",
            mime="application/pdf",
            btn_key=f"{key_prefix}_save_pdf",
            dl_key=f"{key_prefix}_dl_pdf",
            err_label="PDF",
        )

    with col_s4:
        if st.button("🔄 שרטוט חדש", use_container_width=True,
                     key=f"{key_prefix}_new"):
            # איפוס נתיבי הקבצים כדי שהכפתורים הורדה יעלמו בניתוח הבא
            for k in ("_json_path", "_xlsx_path", "_pdf_path"):
                st.session_state.pop(f"{key_prefix}{k}", None)
            st.session_state.result = None
            st.session_state.filename = None
            st.rerun()
