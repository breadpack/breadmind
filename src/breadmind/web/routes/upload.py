"""File upload and download routes."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse

from breadmind.web.dependencies import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["files"])


@dataclass
class UploadConfig:
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    allowed_types: list[str] = field(default_factory=lambda: [
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "application/pdf",
        "text/plain",
        "text/csv",
        "application/json",
    ])
    upload_dir: str = "uploads"


_config = UploadConfig()


def _safe_extension(filename: str | None) -> str:
    """Extract a safe file extension from the original filename.

    Strips path traversal components and returns only the final extension
    (e.g. '.png').  Returns empty string when no safe extension is found.
    """
    if not filename:
        return ""
    # Take only the basename to prevent path traversal
    basename = Path(filename).name
    # Remove any remaining path separators
    basename = basename.replace("/", "").replace("\\", "").replace("..", "")
    if not basename:
        return ""
    suffix = Path(basename).suffix
    # Only allow alphanumeric extensions
    if suffix and suffix[1:].isalnum():
        return suffix
    return ""


def _get_upload_dir() -> Path:
    """Return the upload directory, creating it if needed."""
    upload_path = Path(_config.upload_dir)
    upload_path.mkdir(parents=True, exist_ok=True)
    return upload_path


@router.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    db=Depends(get_db),
):
    """Upload a file (multipart/form-data)."""
    # Validate MIME type
    content_type = file.content_type or "application/octet-stream"
    if content_type not in _config.allowed_types:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported media type: {content_type}. "
                   f"Allowed: {', '.join(_config.allowed_types)}",
        )

    # Read file content and validate size
    content = await file.read()
    if len(content) > _config.max_file_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {len(content)} bytes. "
                   f"Maximum: {_config.max_file_size} bytes",
        )

    # Generate safe filename
    file_id = uuid.uuid4()
    ext = _safe_extension(file.filename)
    safe_name = f"{file_id}{ext}"

    # Save to filesystem
    upload_dir = _get_upload_dir()
    file_path = upload_dir / safe_name
    file_path.write_bytes(content)

    # Save metadata to DB if available
    if db:
        try:
            async with db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO files_meta (id, name, path_or_url, mime_type, size_bytes, source, user_id)
                    VALUES ($1, $2, $3, $4, $5, 'upload', '')
                    """,
                    file_id,
                    file.filename or safe_name,
                    str(file_path),
                    content_type,
                    len(content),
                )
        except Exception:
            logger.warning("Failed to save file metadata to DB", exc_info=True)

    return JSONResponse(
        status_code=201,
        content={
            "id": str(file_id),
            "filename": file.filename or safe_name,
            "size": len(content),
            "mime_type": content_type,
            "url": f"/api/files/{file_id}",
        },
    )


@router.get("/api/files")
async def list_files(db=Depends(get_db)):
    """List uploaded files (most recent 50)."""
    if not db:
        # Fallback: list from filesystem
        upload_dir = _get_upload_dir()
        items = []
        for p in sorted(upload_dir.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)[:50]:
            if p.is_file():
                stat = p.stat()
                items.append({
                    "id": p.stem,
                    "filename": p.name,
                    "size": stat.st_size,
                    "mime_type": None,
                })
        return {"files": items}

    try:
        async with db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, name, mime_type, size_bytes, created_at
                FROM files_meta
                WHERE source = 'upload'
                ORDER BY created_at DESC
                LIMIT 50
                """
            )
        return {
            "files": [
                {
                    "id": str(row["id"]),
                    "filename": row["name"],
                    "size": row["size_bytes"],
                    "mime_type": row["mime_type"],
                    "url": f"/api/files/{row['id']}",
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                }
                for row in rows
            ]
        }
    except Exception:
        logger.warning("Failed to list files from DB", exc_info=True)
        return {"files": []}


@router.get("/api/files/{file_id}")
async def get_file(file_id: str):
    """Download a file by ID."""
    # Validate UUID format
    try:
        uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="File not found")

    upload_dir = _get_upload_dir()
    # Find file matching the UUID (any extension)
    matches = list(upload_dir.glob(f"{file_id}*"))
    if not matches:
        raise HTTPException(status_code=404, detail="File not found")

    file_path = matches[0]
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
    )


@router.delete("/api/files/{file_id}")
async def delete_file(file_id: str, db=Depends(get_db)):
    """Delete a file by ID (filesystem + DB)."""
    # Validate UUID format
    try:
        parsed_id = uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="File not found")

    upload_dir = _get_upload_dir()
    matches = list(upload_dir.glob(f"{file_id}*"))
    if not matches:
        raise HTTPException(status_code=404, detail="File not found")

    # Delete from filesystem
    for match in matches:
        if match.is_file():
            match.unlink()

    # Delete from DB if available
    if db:
        try:
            async with db.acquire() as conn:
                await conn.execute("DELETE FROM files_meta WHERE id = $1", parsed_id)
        except Exception:
            logger.warning("Failed to delete file metadata from DB", exc_info=True)

    return {"status": "deleted", "id": file_id}
