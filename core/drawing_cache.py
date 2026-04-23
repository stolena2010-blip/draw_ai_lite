"""
Drawing Cache — שומר תוצאות חילוץ לפי MD5 של קובץ ה-PDF.

מטרה: חסוך כסף ב-API בעת עיבוד חוזר של אותו שרטוט (בדיקות, שרטוטים
חוזרים במכלולים, debugging).

מבנה:
  output/.cache/<md5>.json — תוצאת החילוץ השלמה
  Cache key = MD5 של תוכן הקובץ + גרסת המודל + version pipeline

ניתן לכבות דרך environment variable:
  DRAWING_CACHE_DISABLED=true
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from core.azure_client import _active_model  # noqa — internal use

logger = logging.getLogger(__name__)

# העלאה כשמשנים את pipeline — מבטל cache ישן
# v2: החזרת OCR-always-on ב-Stage 1 (תיקון regression: material wrong)
# v3: Compound master matching (Silver over Nickel וכו') — מחייב הרצה מחדש
# v4: תיקון _detect_primary_type — משתמש ב-type/type_he בלבד (Silver OVER Nickel)
CACHE_VERSION = "v4"

_CACHE_DIR = Path("output/.cache")


def is_cache_enabled() -> bool:
    return os.getenv("DRAWING_CACHE_DISABLED", "").lower() != "true"


def _compute_file_hash(file_path: Path) -> str:
    """MD5 של תוכן הקובץ (לא של השם — כדי שאותו קובץ עם שם אחר יזוהה)."""
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _cache_key(file_path: Path, extra: str = "") -> str:
    """
    מפתח cache = md5(file) + model + version + extra.
    שינוי במודל/pipeline → cache miss → הרצה טרייה.
    """
    file_hash = _compute_file_hash(file_path)
    model = _active_model()
    return f"{CACHE_VERSION}_{model}_{file_hash}_{extra}".replace("/", "_")


def _cache_path(key: str) -> Path:
    return _CACHE_DIR / f"{key}.json"


def get_cached_result(file_path: str | Path, extra: str = "") -> dict | None:
    """מחזיר תוצאה שמורה אם קיימת, אחרת None."""
    if not is_cache_enabled():
        return None

    file_path = Path(file_path)
    if not file_path.exists():
        return None

    try:
        key = _cache_key(file_path, extra)
        path = _cache_path(key)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        logger.info("🎯 Cache HIT: %s (key=%s)", file_path.name, key[:40])
        # סמן שזו תוצאה cached
        data["_cache_hit"] = True
        return data
    except Exception as exc:
        logger.warning("Cache read failed: %s", exc)
        return None


def save_cached_result(file_path: str | Path, result: dict, extra: str = "") -> None:
    """שומר תוצאה ל-cache. שקט במקרה של כישלון (cache הוא בונוס, לא חובה)."""
    if not is_cache_enabled():
        return
    if not result:
        return

    file_path = Path(file_path)
    if not file_path.exists():
        return

    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        key = _cache_key(file_path, extra)
        path = _cache_path(key)
        # אל תשמור את דגל ה-cache עצמו
        clean = {k: v for k, v in result.items() if k != "_cache_hit"}
        path.write_text(
            json.dumps(clean, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("💾 Cache SAVED: %s (key=%s)", file_path.name, key[:40])
    except Exception as exc:
        logger.warning("Cache write failed: %s", exc)


def clear_cache() -> int:
    """מוחק את כל ה-cache. מחזיר מספר קבצים שנמחקו."""
    if not _CACHE_DIR.exists():
        return 0
    count = 0
    for f in _CACHE_DIR.glob("*.json"):
        try:
            f.unlink()
            count += 1
        except OSError:
            pass
    logger.info("Cache cleared: %d files removed", count)
    return count


def cache_stats() -> dict:
    """מחזיר סטטיסטיקות על ה-cache: # קבצים, נפח כולל."""
    if not _CACHE_DIR.exists():
        return {"count": 0, "size_mb": 0.0, "enabled": is_cache_enabled()}
    files = list(_CACHE_DIR.glob("*.json"))
    total_size = sum(f.stat().st_size for f in files)
    return {
        "count": len(files),
        "size_mb": round(total_size / 1024 / 1024, 2),
        "enabled": is_cache_enabled(),
    }
