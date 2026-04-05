"""Tests for file upload / download routes."""
from __future__ import annotations

import uuid
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from breadmind.web.app import WebApp
from breadmind.web.routes import upload as upload_mod


def _make_app(**kwargs) -> TestClient:
    """Create a minimal WebApp and return a TestClient."""
    app = WebApp(
        message_handler=AsyncMock(return_value="test response"),
        **kwargs,
    )
    return TestClient(app.app)


def _png_bytes(size: int = 64) -> bytes:
    """Return minimal valid-ish PNG bytes of the given size."""
    # 8-byte PNG signature + padding
    header = b"\x89PNG\r\n\x1a\n"
    return header + b"\x00" * max(0, size - len(header))


class TestUploadImage:
    """POST /api/upload with a valid image."""

    def test_upload_image(self, tmp_path: Path):
        upload_mod._config.upload_dir = str(tmp_path)
        client = _make_app()

        data = _png_bytes(128)
        resp = client.post(
            "/api/upload",
            files={"file": ("test.png", BytesIO(data), "image/png")},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["filename"] == "test.png"
        assert body["size"] == 128
        assert body["mime_type"] == "image/png"
        assert body["url"].startswith("/api/files/")
        # Verify UUID
        uuid.UUID(body["id"])
        # Verify file was actually written
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].stat().st_size == 128


class TestUploadTooLarge:
    """POST /api/upload with a file exceeding the size limit."""

    def test_upload_too_large(self, tmp_path: Path):
        upload_mod._config.upload_dir = str(tmp_path)
        # Temporarily lower the limit
        original = upload_mod._config.max_file_size
        upload_mod._config.max_file_size = 100
        try:
            client = _make_app()
            data = b"\x00" * 200
            resp = client.post(
                "/api/upload",
                files={"file": ("big.png", BytesIO(data), "image/png")},
            )
            assert resp.status_code == 413
        finally:
            upload_mod._config.max_file_size = original


class TestUploadInvalidType:
    """POST /api/upload with a disallowed MIME type."""

    def test_upload_invalid_type(self, tmp_path: Path):
        upload_mod._config.upload_dir = str(tmp_path)
        client = _make_app()
        resp = client.post(
            "/api/upload",
            files={"file": ("script.exe", BytesIO(b"MZ"), "application/x-msdownload")},
        )
        assert resp.status_code == 415


class TestGetFile:
    """GET /api/files/{file_id} download."""

    def test_get_file(self, tmp_path: Path):
        upload_mod._config.upload_dir = str(tmp_path)
        client = _make_app()

        # Upload first
        data = _png_bytes(64)
        upload_resp = client.post(
            "/api/upload",
            files={"file": ("img.png", BytesIO(data), "image/png")},
        )
        file_id = upload_resp.json()["id"]

        # Download
        resp = client.get(f"/api/files/{file_id}")
        assert resp.status_code == 200
        assert len(resp.content) == 64


class TestGetFileNotFound:
    """GET /api/files/{file_id} for a missing file."""

    def test_get_file_not_found(self, tmp_path: Path):
        upload_mod._config.upload_dir = str(tmp_path)
        client = _make_app()
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/files/{fake_id}")
        assert resp.status_code == 404


class TestListFiles:
    """GET /api/files listing."""

    def test_list_files(self, tmp_path: Path):
        upload_mod._config.upload_dir = str(tmp_path)
        client = _make_app()

        # Upload two files
        for name in ("a.png", "b.png"):
            client.post(
                "/api/upload",
                files={"file": (name, BytesIO(_png_bytes(32)), "image/png")},
            )

        resp = client.get("/api/files")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["files"]) == 2


class TestDeleteFile:
    """DELETE /api/files/{file_id}."""

    def test_delete_file(self, tmp_path: Path):
        upload_mod._config.upload_dir = str(tmp_path)
        client = _make_app()

        # Upload
        data = _png_bytes(48)
        upload_resp = client.post(
            "/api/upload",
            files={"file": ("del.png", BytesIO(data), "image/png")},
        )
        file_id = upload_resp.json()["id"]

        # Delete
        resp = client.delete(f"/api/files/{file_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        # Confirm gone
        resp = client.get(f"/api/files/{file_id}")
        assert resp.status_code == 404


class TestSafeFilename:
    """Ensure path traversal attempts are neutralized."""

    def test_safe_filename_traversal(self, tmp_path: Path):
        upload_mod._config.upload_dir = str(tmp_path)
        client = _make_app()

        resp = client.post(
            "/api/upload",
            files={"file": ("../../etc/passwd", BytesIO(b"root:x:0"), "text/plain")},
        )
        assert resp.status_code == 201
        # File should be stored under tmp_path, not escaped
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        # The stored filename must not contain path separators
        stored = files[0].name
        assert "/" not in stored
        assert "\\" not in stored
        assert ".." not in stored

    def test_safe_extension_empty(self):
        from breadmind.web.routes.upload import _safe_extension
        assert _safe_extension(None) == ""
        assert _safe_extension("") == ""
        assert _safe_extension("noext") == ""

    def test_safe_extension_normal(self):
        from breadmind.web.routes.upload import _safe_extension
        assert _safe_extension("photo.jpg") == ".jpg"
        assert _safe_extension("doc.PDF") == ".PDF"

    def test_safe_extension_traversal(self):
        from breadmind.web.routes.upload import _safe_extension
        ext = _safe_extension("../../../etc/passwd")
        assert ".." not in ext
