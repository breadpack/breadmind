"""Tests for PDF and image multimodal reader tools."""

import json
import struct
from unittest.mock import patch

from breadmind.tools.multimodal_reader import image_read, pdf_read


def test_pdf_read_fallback_no_pymupdf():
    """Without PyMuPDF, pdf_read should return a helpful message."""
    with patch.dict("sys.modules", {"fitz": None}):
        # Force reimport to trigger ImportError
        import importlib
        import breadmind.tools.multimodal_reader as mod
        importlib.reload(mod)
        result = mod.pdf_read("test.pdf")
        assert "PyMuPDF" in result
        assert "pip install" in result


def test_image_read_png(tmp_path):
    """Reading a valid PNG should return base64 JSON."""
    f = tmp_path / "test.png"
    # Minimal valid PNG: 8-byte signature + IHDR + IEND
    png_sig = b"\x89PNG\r\n\x1a\n"
    # IHDR chunk: length(13) + type + data + crc
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr_crc = b"\x00" * 4  # Simplified CRC (not valid but enough for test)
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + ihdr_crc
    iend = struct.pack(">I", 0) + b"IEND" + b"\x00" * 4
    f.write_bytes(png_sig + ihdr + iend)

    result = image_read(str(f))
    data = json.loads(result)
    assert data["type"] == "image"
    assert data["mime"] == "image/png"
    assert "_full_base64" in data
    assert data["size_bytes"] > 0


def test_image_too_large(tmp_path):
    """Images over 20MB should be rejected."""
    f = tmp_path / "big.png"
    f.write_bytes(b"\x00" * 100)  # Small file but we mock getsize

    with patch("os.path.getsize", return_value=25 * 1024 * 1024):
        result = image_read(str(f))
        assert "too large" in result
        assert "max 20MB" in result


def test_unsupported_format(tmp_path):
    """Unsupported image formats should be rejected."""
    f = tmp_path / "test.tiff"
    f.write_bytes(b"\x00")

    result = image_read(str(f))
    assert "Unsupported image format" in result
