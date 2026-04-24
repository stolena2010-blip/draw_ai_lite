"""
שמירת תוצאות ל-JSON ו-Excel.
"""
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd


# openpyxl דוחה תווי בקרה ב-worksheets (ASCII 0-8, 11, 12, 14-31, 127).
# OCR לפעמים מחזיר תווים כאלה (למשל U+FFFD במקום ±) — נסנן לפני כתיבה.
_ILLEGAL_EXCEL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_for_excel(value):
    """מסיר תווי בקרה שאסורים ב-Excel worksheets. פועל רקורסיבית."""
    if isinstance(value, str):
        return _ILLEGAL_EXCEL_CHARS.sub("", value)
    if isinstance(value, dict):
        return {k: _sanitize_for_excel(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_excel(v) for v in value]
    return value


def save_to_json(data: dict, path: Path) -> Path:
    """שמירה ל-JSON בפורמט קריא עם UTF-8 מלא."""
    path = Path(path)
    data_with_meta = {
        **data,
        "_saved_at": datetime.now().isoformat(),
    }
    path.write_text(
        json.dumps(data_with_meta, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return path


def save_to_excel(data: dict, path: Path) -> Path:
    """שמירה ל-Excel רב-גיליוני:
      Summary        — שורה אחת עם שדות בסיסיים
      Coatings       — ציפויים (כל ציפוי בשורה משלו)
      Paintings      — צביעות
      Master_Matches — התאמות מאסטר (Top-3 לכל ציפוי)
      Standards      — תקנים
      Warnings       — אזהרות ולידציה
    """
    path = Path(path)
    data = _sanitize_for_excel(data)
    # keys ש-flatten-ם ל-Summary sheet
    simple_keys = {
        "part_number", "drawing_number", "revision", "customer",
        "material", "quantity", "assembly_role",
        "final_approval", "packaging_notes", "source_filename",
        "process_summary_hebrew",
    }

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        # ─── Summary ───
        summary_row = {k: data.get(k, "") for k in simple_keys if k in data}
        summary_row["notes"] = data.get("notes", "")
        summary_row["_saved_at"] = datetime.now().isoformat()
        pd.DataFrame([summary_row]).to_excel(
            writer, sheet_name="Summary", index=False
        )

        # ─── Coatings ───
        _write_process_sheet(writer, "Coatings", data.get("coating_processes"))

        # ─── Paintings ───
        _write_process_sheet(writer, "Paintings", data.get("painting_processes"))

        # ─── Master Matches ───
        master_matches = data.get("master_matches") or []
        mm_rows = []
        for mm in master_matches:
            proc = mm.get("coating_process", {}) if isinstance(mm, dict) else {}
            for rank, match in enumerate(mm.get("matches", []) or [], 1):
                mm_rows.append({
                    "coating": _proc_label(proc),
                    "rank": rank,
                    "master_id": match.get("master_id", ""),
                    "score": match.get("score", ""),
                    "description": match.get("description", ""),
                    "reasons": " | ".join(match.get("reasons", []) or []),
                })
        if mm_rows:
            pd.DataFrame(mm_rows).to_excel(
                writer, sheet_name="Master_Matches", index=False
            )

        # ─── Standards ───
        standards = data.get("standards") or []
        if standards:
            std_rows = [
                {"standard": s} if isinstance(s, str)
                else {
                    "standard": s.get("name", ""),
                    "type": s.get("type", ""),
                    "class": s.get("class", ""),
                    "grade": s.get("grade", ""),
                }
                for s in standards
            ]
            pd.DataFrame(std_rows).to_excel(
                writer, sheet_name="Standards", index=False
            )

        # ─── Warnings ───
        warnings = data.get("_validation_warnings") or []
        if warnings:
            w_rows = [
                {
                    "severity": w.get("severity", ""),
                    "type": w.get("type", ""),
                    "message": w.get("message", ""),
                    "suggestion": w.get("suggestion", ""),
                }
                for w in warnings if isinstance(w, dict)
            ]
            pd.DataFrame(w_rows).to_excel(
                writer, sheet_name="Warnings", index=False
            )

    return path


def _proc_label(proc) -> str:
    """תווית קצרה לציפוי/צביעה בטבלת Master Matches."""
    if isinstance(proc, dict):
        return (proc.get("type_he") or proc.get("type")
                or proc.get("name") or "").strip()
    return str(proc or "")


def _write_process_sheet(writer, sheet_name: str, processes) -> None:
    """כותב גיליון ציפויים/צביעות (שורה לכל תהליך) אם קיים."""
    if not processes:
        return
    rows = []
    for p in processes:
        if isinstance(p, dict):
            rows.append({
                "type": p.get("type", ""),
                "type_he": p.get("type_he", ""),
                "thickness": p.get("thickness", ""),
                "standard": p.get("standard", ""),
                "spec_type": p.get("type_code", ""),
                "class": p.get("class", ""),
                "grade": p.get("grade", ""),
                "color": p.get("color", ""),
                "ral": p.get("ral", ""),
                "rohs": p.get("rohs", ""),
                "brand": p.get("brand", ""),
            })
        else:
            rows.append({"raw": str(p)})
    if rows:
        pd.DataFrame(rows).to_excel(writer, sheet_name=sheet_name, index=False)


def save_batch_to_excel(drawings: list[dict], path: Path) -> Path:
    """שמירת דוח Excel מאוחד למוד מכלולים (רשימת שרטוטים שכל אחד בפורמט single).

    מבנה גיליונות:
      Summary        — שורה אחת לכל שרטוט עם שדות הבסיס
      Coatings       — כל הציפויים מכל השרטוטים, עם עמודת Source
      Paintings      — כל הצביעות מכל השרטוטים, עם עמודת Source
      Master_Matches — Top-3 מאסטרים לכל ציפוי (עם Source)
      Standards      — כל התקנים (עם Source)
      Warnings       — אזהרות ולידציה (עם Source)
    """
    path = Path(path)
    drawings = [_sanitize_for_excel(d) for d in (drawings or [])]

    summary_cols = [
        "source_filename", "part_number", "drawing_number", "revision",
        "customer", "material", "quantity", "process_summary_hebrew",
        "notes",
    ]

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        # ─── Summary ───
        rows = []
        for d in drawings:
            if not isinstance(d, dict):
                continue
            row = {k: d.get(k, "") for k in summary_cols}
            rows.append(row)
        if rows:
            pd.DataFrame(rows, columns=summary_cols).to_excel(
                writer, sheet_name="Summary", index=False
            )

        # ─── Coatings ───
        _write_batch_process_sheet(writer, "Coatings", drawings, "coating_processes")

        # ─── Paintings ───
        _write_batch_process_sheet(writer, "Paintings", drawings, "painting_processes")

        # ─── Master Matches ───
        mm_rows = []
        for d in drawings:
            if not isinstance(d, dict):
                continue
            src = d.get("source_filename", "")
            for mm in d.get("master_matches") or []:
                if not isinstance(mm, dict):
                    continue
                proc = mm.get("coating") or {}
                for rank, match in enumerate(mm.get("matches") or [], 1):
                    mm_rows.append({
                        "source": src,
                        "coating": _proc_label(proc),
                        "rank": rank,
                        "master_id": match.get("master_id", ""),
                        "score": match.get("score", ""),
                        "description": match.get("desc", ""),
                        "standard": match.get("standard", ""),
                        "thickness": match.get("thickness", ""),
                    })
        if mm_rows:
            pd.DataFrame(mm_rows).to_excel(
                writer, sheet_name="Master_Matches", index=False
            )

        # ─── Standards ───
        std_rows = []
        for d in drawings:
            if not isinstance(d, dict):
                continue
            src = d.get("source_filename", "")
            for s in d.get("standards") or []:
                if isinstance(s, str):
                    std_rows.append({"source": src, "standard": s})
                elif isinstance(s, dict):
                    std_rows.append({
                        "source": src,
                        "standard": s.get("name", ""),
                        "type": s.get("type", ""),
                        "class": s.get("class", ""),
                        "grade": s.get("grade", ""),
                    })
        if std_rows:
            pd.DataFrame(std_rows).to_excel(
                writer, sheet_name="Standards", index=False
            )

        # ─── Warnings ───
        w_rows = []
        for d in drawings:
            if not isinstance(d, dict):
                continue
            src = d.get("source_filename", "")
            for w in d.get("_validation_warnings") or []:
                if not isinstance(w, dict):
                    continue
                w_rows.append({
                    "source": src,
                    "severity": w.get("severity", ""),
                    "type": w.get("type", ""),
                    "message": w.get("message", ""),
                    "suggestion": w.get("suggestion", ""),
                })
        if w_rows:
            pd.DataFrame(w_rows).to_excel(
                writer, sheet_name="Warnings", index=False
            )

    return path


def _write_batch_process_sheet(writer, sheet_name: str, drawings: list[dict],
                                field: str) -> None:
    """כותב גיליון ציפויים/צביעות מאוחד עם עמודת source לכל שרטוט."""
    rows = []
    for d in drawings:
        if not isinstance(d, dict):
            continue
        src = d.get("source_filename", "")
        for p in d.get(field) or []:
            if isinstance(p, dict):
                rows.append({
                    "source": src,
                    "step_no": p.get("step_no", ""),
                    "type": p.get("type", ""),
                    "type_he": p.get("type_he", ""),
                    "name": p.get("name", ""),
                    "thickness": p.get("thickness", ""),
                    "standard": p.get("standard", ""),
                    "class": p.get("class", ""),
                    "grade": p.get("grade", ""),
                    "color": p.get("color", ""),
                    "ral": p.get("ral", ""),
                    "rohs": p.get("rohs", ""),
                    "brand": p.get("brand", ""),
                })
            else:
                rows.append({"source": src, "raw": str(p)})
    if rows:
        pd.DataFrame(rows).to_excel(writer, sheet_name=sheet_name, index=False)


def append_to_log(data: dict, log_path: Path = Path("output/history.jsonl")) -> None:
    """הוסף שורה ל-JSONL לתיעוד היסטורי."""
    log_path = Path(log_path)
    log_path.parent.mkdir(exist_ok=True)

    entry = {
        "timestamp": datetime.now().isoformat(),
        **data,
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
