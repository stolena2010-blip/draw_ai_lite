"""
יצירת דוח PDF מאוחד למוד "מכלולים מרובים".

מציג את כל השרטוטים ברצף — כל שרטוט בעמוד משלו עם מידע זהה לתצוגה
של מוד השרטוט הבודד: מזהים, חומר, ציפויים/צביעות (כולל מאסטר מוביל
לכל אחד), תקנים, תהליכים מלווים, אריזה, הערות.

משתמש ב-PyMuPDF (fitz) ובפונקציה Story.place התומכת ב-HTML/CSS
ובכיווניות RTL.
"""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF


def _h(s) -> str:
    """Escape ל-HTML, בטוח ל-None."""
    return html.escape(str(s if s is not None else ""), quote=True)


def _ltr(s) -> str:
    """עוטף ערך לועזי ב-bdi כדי להציג LTR בתוך פסקה RTL."""
    if s is None or s == "":
        return ""
    return f'<bdi dir="ltr">{_h(s)}</bdi>'


def _coating_match_key(c) -> tuple:
    """מפתח מבני לציפוי (עמיד ל-JSON round-trip, שלא כמו id())."""
    if not isinstance(c, dict):
        return (str(c), "", "", "")
    return (
        (c.get("type_he") or "").strip(),
        (c.get("type") or "").strip(),
        (c.get("standard") or "").strip(),
        (c.get("thickness") or "").strip(),
    )


_BASE_CSS = """
<style>
  * { font-family: 'Arial', 'Segoe UI', sans-serif; }
  body { color: #212529; }
  h1 { color: #7AB141; font-size: 22pt; margin: 0 0 8pt 0; }
  h2 { color: #7AB141; font-size: 14pt; margin: 10pt 0 4pt 0;
       border-bottom: 1px solid #C7DFA0; padding-bottom: 2pt;
       page-break-after: avoid; }
  h3 { color: #495057; font-size: 11pt; margin: 8pt 0 2pt 0;
       page-break-after: avoid; }
  p, div, td, th { font-size: 9.5pt; line-height: 1.5; }
  table { border-collapse: collapse; width: 100%; margin: 4pt 0 8pt 0;
          table-layout: fixed; }
  thead { display: table-header-group; }
  tr    { page-break-inside: avoid; }
  th { background: #e9ecef; color: #212529; padding: 4pt 6pt;
       border: 1px solid #adb5bd; text-align: right; font-size: 9pt;
       word-wrap: break-word; }
  td { padding: 3pt 6pt; border: 1px solid #ced4da; font-size: 9pt;
       vertical-align: top; word-wrap: break-word; overflow-wrap: anywhere; }
  .meta-card { background: #F3F9E8; border: 1pt solid #7AB141;
               border-radius: 6pt; padding: 8pt 10pt; margin: 4pt 0 8pt 0;
               page-break-inside: avoid; }
  .summary { background: #d4edda; color: #155724; padding: 8pt 10pt;
             border-radius: 5pt; margin: 4pt 0 8pt 0; line-height: 1.7;
             page-break-inside: avoid; }
  .pkg-he { background: #fff3cd; color: #664d03; padding: 6pt 9pt;
            border-radius: 5pt; margin: 3pt 0;
            page-break-inside: avoid; }
  .notes { background: #f8f9fa; border-right: 3pt solid #6c757d;
           padding: 6pt 10pt; margin: 4pt 0; white-space: pre-wrap;
           page-break-inside: avoid; }
  code { font-family: Consolas, monospace; background: #f1f3f5;
         padding: 1pt 4pt; border-radius: 3pt; font-size: 8.5pt;
         direction: ltr; unicode-bidi: bidi-override; }
  bdi  { unicode-bidi: isolate; }
  .muted { color: #6c757d; }
  .badge-ok { background: #198754; color: white; padding: 1pt 5pt;
              border-radius: 3pt; font-size: 8pt; }
  .master { background: #d1e7dd; color: #0a3622;
            border: 1pt solid #198754; border-radius: 4pt;
            padding: 4pt 8pt; margin: 2pt 0 6pt 1em;
            font-size: 9pt; page-break-inside: avoid; }
  .master-mid { background: #fff3cd; color: #664d03;
                border-color: #fd7e14; }
  .master-low { background: #f8d7da; color: #58151c;
                border-color: #dc3545; }
  .stds code { display: inline-block; margin: 1pt 2pt; }
  table.tbl-coat col.c-step   { width: 7%; }
  table.tbl-coat col.c-typeh  { width: 14%; }
  table.tbl-coat col.c-typee  { width: 12%; }
  table.tbl-coat col.c-name   { width: 24%; }
  table.tbl-coat col.c-std    { width: 19%; }
  table.tbl-coat col.c-thick  { width: 16%; }
  table.tbl-coat col.c-rohs   { width: 8%; }
</style>
"""


def _wrap_rtl(inner_html: str) -> str:
    return (
        '<html dir="rtl" lang="he"><head><meta charset="utf-8">'
        + _BASE_CSS
        + '</head><body dir="rtl" style="text-align:right; '
        + 'unicode-bidi:plaintext;">'
        + inner_html
        + "</body></html>"
    )


_LOGO_PATH = Path(__file__).resolve().parent.parent / "brand_banner.png"


def _logo_html() -> str:
    """באנר ALGAT / GREEN COAT בראש הדוח (אם קובץ הלוגו קיים)."""
    if not _LOGO_PATH.exists():
        return ""
    # PyMuPDF Story מקבל file:// URIs
    uri = _LOGO_PATH.as_uri()
    return (
        f'<div style="margin:0 0 10pt 0; text-align:center;">'
        f'<img src="{uri}" style="width:100%; max-height:60pt;"/>'
        f'</div>'
    )


def _cover_html(n_drawings: int) -> str:
    ts = datetime.now().strftime("%d/%m/%Y %H:%M")
    return (
        _logo_html()
        + f"<h1>📐 דוח ניתוח מכלול</h1>"
        f'<div class="meta-card">'
        f'<p><span class="muted">📅 תאריך הפקה:</span> <b>{ts}</b></p>'
        f'<p><span class="muted">📄 מספר שרטוטים בניתוח:</span> '
        f'<b>{n_drawings}</b></p>'
        f"</div>"
    )


def _top_master_html(match: dict) -> str:
    """שורת מאסטר מוביל מתחת לציפוי."""
    score = match.get("score", 0)
    if score >= 70:
        cls = "master"
    elif score >= 50:
        cls = "master master-mid"
    else:
        cls = "master master-low"
    mid = _ltr(match.get("master_id", ""))
    desc = _h((match.get("desc") or "")[:80])
    std = _ltr(match.get("standard") or "")
    thk = _ltr(match.get("thickness") or "—")
    return (
        f'<div class="{cls}">'
        f'🎯 <b>מאסטר מוביל:</b> {mid} &nbsp;·&nbsp; {desc} '
        f'&nbsp;·&nbsp; 📜 {std} &nbsp;·&nbsp; 📏 {thk} '
        f'&nbsp;·&nbsp; <b>ציון: {score}</b>'
        f'</div>'
    )


def _processes_table_html(title: str, items: list, match_lookup: dict) -> str:
    """טבלה של ציפויים/צביעות + שורת מאסטר מוביל מתחת לכל שורה."""
    if not items:
        return ""
    parts = [f"<h3>{title}</h3>"]
    head = (
        "<thead><tr><th>שלב</th><th>סוג (HE)</th><th>סוג (EN)</th>"
        "<th>תיאור</th><th>תקן</th><th>עובי</th><th>RoHS</th></tr></thead>"
    )
    rows = ""
    for it in items:
        if not isinstance(it, dict):
            continue
        rohs = '<span class="badge-ok">✓</span>' if it.get("rohs") else ""
        rows += (
            f"<tr>"
            f"<td>{_ltr(it.get('step_no',''))}</td>"
            f"<td>{_h(it.get('type_he',''))}</td>"
            f"<td>{_ltr(it.get('type',''))}</td>"
            f"<td>{_h(it.get('name',''))}</td>"
            f"<td>{_ltr(it.get('standard',''))}</td>"
            f"<td>{_ltr(it.get('thickness',''))}</td>"
            f"<td>{rohs}</td>"
            f"</tr>"
        )
    parts.append(
        '<table class="tbl-coat">'
        '<colgroup>'
        '<col class="c-step"><col class="c-typeh"><col class="c-typee">'
        '<col class="c-name"><col class="c-std"><col class="c-thick">'
        '<col class="c-rohs">'
        '</colgroup>'
        f"{head}<tbody>{rows}</tbody></table>"
    )

    # מאסטר מוביל לכל ציפוי (אם קיים)
    for it in items:
        if not isinstance(it, dict):
            continue
        top = match_lookup.get(_coating_match_key(it)) or []
        if top:
            parts.append(_top_master_html(top[0]))
    return "".join(parts)


def _drawing_html(d: dict, idx: int, total: int) -> str:
    pn = _ltr(d.get("part_number") or "—")
    dn = _ltr(d.get("drawing_number") or "—")
    rev = _ltr(d.get("revision") or "—")
    cust = _h(d.get("customer") or "—")
    mat = _h(d.get("material") or "—")
    src = _ltr(d.get("source_filename") or "")

    parts = [
        f"<h2>📄 שרטוט {idx}/{total} — {pn}</h2>",
        '<div class="meta-card">',
        f'<p><span class="muted">קובץ:</span> {src}</p>',
        f'<p><span class="muted">פריט:</span> <b>{pn}</b> · '
        f'<span class="muted">שרטוט:</span> <b>{dn}</b> · '
        f'<span class="muted">גרסה:</span> <b>{rev}</b> · '
        f'<span class="muted">לקוח:</span> <b>{cust}</b></p>'
        f'<p><span class="muted">חומר גלם:</span> <b>{mat}</b></p>'
        "</div>",
    ]

    # סיכום עברי
    summary = (d.get("process_summary_hebrew") or "").strip()
    if summary:
        parts.append(f'<div class="summary">🇮🇱 <b>סיכום:</b><br>{_h(summary)}</div>')

    # מיפוי ציפוי → התאמות (לפי id של אובייקט הציפוי)
    matches = d.get("master_matches") or []
    match_lookup = {}
    for e in matches:
        if isinstance(e, dict):
            match_lookup.setdefault(
                _coating_match_key(e.get("coating")),
                e.get("matches") or [],
            )

    # ציפויים + מאסטר מוביל
    parts.append(_processes_table_html(
        "🎨 ציפויים / טיפול שטח",
        d.get("coating_processes") or [],
        match_lookup,
    ))

    # צביעות + מאסטר מוביל
    parts.append(_processes_table_html(
        "🖌️ צביעות",
        d.get("painting_processes") or [],
        match_lookup,
    ))

    # תקנים נוספים שלא צמודים לתהליך
    used_stds = set()
    for p in (d.get("coating_processes") or []) + (d.get("painting_processes") or []):
        if isinstance(p, dict) and p.get("standard"):
            used_stds.add(p["standard"].strip())
    extra_stds = [s for s in (d.get("standards") or [])
                  if s and s.strip() not in used_stds]
    if extra_stds:
        parts.append("<h3>📜 תקנים נוספים</h3>")
        chips = " ".join(f"<code>{_h(s)}</code>" for s in extra_stds)
        parts.append(f'<p class="stds">{chips}</p>')

    # תהליכים מלווים
    additional = d.get("additional_processes") or []
    if additional:
        parts.append("<h3>🛠️ תהליכים מלווים</h3>")
        names = []
        for a in additional:
            if isinstance(a, dict):
                he = (a.get("name_he") or "").strip()
                en = (a.get("name_en") or "").strip()
                if he and en:
                    names.append(f"{_h(he)} ({_ltr(en)})")
                elif he:
                    names.append(_h(he))
                elif en:
                    names.append(_ltr(en))
        if names:
            parts.append("<p>" + " · ".join(names) + "</p>")

    # אריזה
    pkg = d.get("packaging_notes") or {}
    if isinstance(pkg, dict) and (pkg.get("he") or pkg.get("en")):
        parts.append("<h3>📦 אריזה</h3>")
        if pkg.get("he"):
            parts.append(f'<div class="pkg-he">🇮🇱 {_h(pkg["he"])}</div>')
        if pkg.get("en"):
            parts.append(
                f'<div class="pkg-he" dir="ltr" style="text-align:left;">'
                f'🇬🇧 {_h(pkg["en"])}</div>'
            )

    # הערות
    notes = (d.get("notes") or "").strip()
    if notes:
        parts.append("<h3>📝 הערות השרטוט</h3>")
        parts.append(f'<div class="notes">{_h(notes)}</div>')

    return "".join(parts)


def build_batch_pdf(drawings: list[dict], out_path: Path) -> Path:
    """בונה PDF מאוחד עם כל השרטוטים — כל שרטוט מתחיל בעמוד חדש."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    page_w, page_h = fitz.paper_size("a4")
    margin = 36
    mediabox = fitz.Rect(0, 0, page_w, page_h)
    where = fitz.Rect(margin, margin, page_w - margin, page_h - margin)

    sections: list[str] = [_wrap_rtl(_cover_html(len(drawings)))]
    total = len(drawings)
    for i, d in enumerate(drawings, 1):
        sections.append(_wrap_rtl(_drawing_html(d, i, total)))

    writer = fitz.DocumentWriter(str(out_path))
    try:
        for html_content in sections:
            story = fitz.Story(html=html_content)
            more = 1
            while more:
                dev = writer.begin_page(mediabox)
                more, _filled = story.place(where)
                story.draw(dev)
                writer.end_page()
    finally:
        writer.close()

    return out_path
