"""
שמירת תוצאות ל-JSON ו-Excel.
"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd


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
