"""
המרת PDF לתמונות base64 לצורך שליחה ל-Vision API.
משתמש ב-PyMuPDF (fitz) — לא דורש בינארים חיצוניים (Poppler).
"""
import base64
import io
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

from .exceptions import PDFError, ImageError


def _render_pdf_to_pil(pdf_source, dpi: int = 200) -> list[Image.Image]:
    """ממיר PDF לרשימת תמונות PIL באמצעות PyMuPDF."""
    try:
        if isinstance(pdf_source, (str, Path)):
            doc = fitz.open(str(pdf_source))
        else:
            doc = fitz.open(stream=pdf_source, filetype="pdf")
    except Exception as exc:
        name = Path(pdf_source).name if isinstance(pdf_source, (str, Path)) else "PDF"
        raise PDFError(
            f"Failed to open PDF: {exc}",
            user_message=f"לא ניתן לפתוח את ה-PDF: {name}",
            suggestion="ייתכן שהקובץ פגום או מוגן בסיסמה. נסי קובץ אחר.",
            context={"source": str(pdf_source), "original_error": str(exc)},
        ) from exc

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    images: list[Image.Image] = []
    try:
        for page in doc:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            images.append(img)
    finally:
        doc.close()

    return images


def pdf_to_images(pdf_source, dpi: int = 400) -> list[str]:
    """
    ממיר PDF לרשימת תמונות base64.

    Args:
        pdf_source: נתיב לקובץ PDF או bytes
        dpi: רזולוציה (ברירת מחדל 400 — קריטי לקריאת ספרות קטנות
             ב-title block של שרטוטים הנדסיים)

    Returns:
        רשימה של תמונות base64 PNG (אחת לכל עמוד)
    """
    images = _render_pdf_to_pil(pdf_source, dpi=dpi)

    base64_images = []
    for img in images:
        if img.mode != "RGB":
            img = img.convert("RGB")

        # מגבלת GPT-4o היא 2048 על הצד הקצר ו-768 על הצד הארוך במצב "high".
        # אנחנו לא מקטינים מתחת ל-4000 — Vision מקטין בעצמו אך משמר את הרזולוציה
        # היחסית של אזור ה-title block. הקטנה מוקדמת מאבדת ספרות.
        max_dim = 4096
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)

        # PNG חסר-אובדן — קריטי לטקסט קטן (JPEG מוסיף ארטיפקטים סביב ספרות).
        buffer = io.BytesIO()
        img.save(buffer, format="PNG", optimize=True)
        b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        base64_images.append(b64)

    return base64_images


def image_file_to_b64(image_path) -> list[str]:
    """ממיר קובץ תמונה (PNG/JPG/JPEG/WEBP) ל-base64 PNG בודד.

    משמש לטעינת תמונות תרשים-מכלול (Exploded View) במצב המכלולים.
    מחזיר רשימה בת איבר אחד כדי להתאים ל-API של ‎pdf_to_images‎.
    """
    try:
        img = Image.open(image_path)
    except Exception as exc:
        raise ImageError(
            f"Failed to open image: {exc}",
            user_message=f"לא ניתן לפתוח את התמונה: {Path(image_path).name}",
            suggestion="ודאי שהקובץ בפורמט PNG/JPG/WEBP ואינו פגום.",
            context={"path": str(image_path), "original_error": str(exc)},
        ) from exc
    if img.mode != "RGB":
        img = img.convert("RGB")

    max_dim = 4096
    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.LANCZOS)

    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return [b64]
