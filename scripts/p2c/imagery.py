"""Whole-page PDF-to-PNG extraction for reused slide images.

Whole pages, not agent-cropped regions: the only agent that ever views slide
pixels is the summarizer, and asking it to name a precise bounding box for a
page it may not even be the one rendering later would be an unverifiable
guess. Extraction happens here, at build time, from a page ref an agent only
ever *names* (``deck.pdf#12``).

pypdfium2 because it is a pure pip install with its own bundled binary -- no
system poppler or headless Chromium required for a feature meant to work by
default.
"""

import io
from pathlib import Path

import pypdfium2 as pdfium


class ImageryError(Exception):
    """A page could not be extracted from the given PDF."""


def extract_page_png(pdf_path: Path, page_number: int, dpi: int = 96) -> bytes:
    """page_number is 1-based, matching outline.json's slide_refs convention."""
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise ImageryError(f"{pdf_path}: no such file")

    try:
        pdf = pdfium.PdfDocument(str(pdf_path))
    except Exception as exc:
        raise ImageryError(f"{pdf_path}: not a readable PDF ({exc})") from exc

    try:
        page_count = len(pdf)
        if not 1 <= page_number <= page_count:
            raise ImageryError(
                f"{pdf_path}: page {page_number} out of range (1-{page_count})"
            )
        try:
            page = pdf[page_number - 1]
            bitmap = page.render(scale=dpi / 72)
            pil_image = bitmap.to_pil()
        except Exception as exc:
            raise ImageryError(
                f"{pdf_path}: page {page_number} could not be rendered ({exc})"
            ) from exc
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        return buf.getvalue()
    finally:
        pdf.close()
