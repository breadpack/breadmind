"""PDF and image reading tools with multimodal support."""

import base64
import json
import os

from breadmind.tools.registry import tool


def _parse_page_range(pages: str, total: int) -> tuple[int, int]:
    """Parse a page range string like '1-5' or '3' into (start, end) indices."""
    if "-" in pages:
        parts = pages.split("-", 1)
        start = max(0, int(parts[0]) - 1)
        end = min(total, int(parts[1]))
    else:
        p = int(pages) - 1
        start, end = max(0, p), min(total, p + 1)
    return start, end


def _pdf_fallback(file_path: str, pages: str) -> str:
    """Fallback when PyMuPDF is not installed."""
    return (
        "PDF reading requires PyMuPDF (pip install pymupdf). "
        "Install it for PDF support."
    )


@tool(
    description="Read a PDF file, optionally specifying page range",
    read_only=True,
)
def pdf_read(file_path: str, pages: str = "") -> str:
    """Read PDF. pages can be '1-5', '3', '10-20'. Max 20 pages per call."""
    try:
        import fitz  # PyMuPDF  # noqa: F811
    except ImportError:
        return _pdf_fallback(file_path, pages)

    doc = fitz.open(file_path)
    total = len(doc)

    if pages:
        start, end = _parse_page_range(pages, total)
    else:
        if total > 10:
            doc.close()
            return (
                f"PDF has {total} pages. Specify pages parameter "
                f"(e.g. '1-5'). Max 20 per request."
            )
        start, end = 0, min(total, 20)

    if end - start > 20:
        doc.close()
        return "Error: max 20 pages per request."

    parts = [f"PDF: {file_path} ({total} pages, showing {start + 1}-{end})"]
    for i in range(start, end):
        page = doc[i]
        text = page.get_text()
        parts.append(f"\n--- Page {i + 1} ---\n{text.strip()}")
    doc.close()
    return "\n".join(parts)


@tool(
    description="Read an image file and return base64 for multimodal LLM processing",
    read_only=True,
)
def image_read(file_path: str) -> str:
    """Read image file. Returns description metadata + base64 for vision models."""
    ext = os.path.splitext(file_path)[1].lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    mime = mime_map.get(ext)
    if not mime:
        return f"Unsupported image format: {ext}"

    size = os.path.getsize(file_path)
    if size > 20 * 1024 * 1024:  # 20MB limit
        return f"Image too large: {size / 1024 / 1024:.1f}MB (max 20MB)"

    with open(file_path, "rb") as f:
        data = base64.b64encode(f.read()).decode()

    return json.dumps(
        {
            "type": "image",
            "file": file_path,
            "mime": mime,
            "size_bytes": size,
            "base64": data[:100] + "...",  # truncated for text output
            "_full_base64": data,  # full data for multimodal processing
        }
    )
