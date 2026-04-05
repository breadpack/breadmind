"""Backup/restore API routes for database management."""
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["backup"])


class RestoreRequest(BaseModel):
    filename: str


class CreateBackupRequest(BaseModel):
    label: str | None = None


def setup_backup_routes(app, app_state):
    """Register backup/restore routes on the FastAPI app."""

    def _get_backup_manager():
        db_config = {}
        config = getattr(app_state, "_config", None)
        if config and hasattr(config, "database"):
            db_cfg = config.database
            db_config = {
                "host": db_cfg.host,
                "port": db_cfg.port,
                "name": db_cfg.name,
                "user": db_cfg.user,
                "password": db_cfg.password,
            }

        from breadmind.storage.backup import BackupManager, BackupConfig
        return BackupManager(db_config, BackupConfig())

    @app.post("/api/admin/backup")
    async def create_backup(body: CreateBackupRequest | None = None):
        """Create a new database backup."""
        try:
            mgr = _get_backup_manager()
            label = body.label if body else None
            info = await mgr.create_backup(label=label)
            return JSONResponse(200, info.to_dict())
        except Exception as exc:
            logger.error("Backup creation failed: %s", exc)
            return JSONResponse(500, {"error": str(exc)})

    @app.get("/api/admin/backups")
    async def list_backups():
        """List all available backups."""
        try:
            mgr = _get_backup_manager()
            backups = mgr.list_backups()
            return JSONResponse(200, [b.to_dict() for b in backups])
        except Exception as exc:
            logger.error("Backup listing failed: %s", exc)
            return JSONResponse(500, {"error": str(exc)})

    @app.post("/api/admin/restore")
    async def restore_backup(body: RestoreRequest):
        """Restore database from a backup file."""
        try:
            mgr = _get_backup_manager()
            # Resolve filename to full path
            from pathlib import Path
            backup_path = Path(mgr._backup_dir) / body.filename
            if not backup_path.exists():
                return JSONResponse(404, {"error": f"Backup file not found: {body.filename}"})
            await mgr.restore_backup(str(backup_path))
            return JSONResponse(200, {"status": "restored", "filename": body.filename})
        except Exception as exc:
            logger.error("Restore failed: %s", exc)
            return JSONResponse(500, {"error": str(exc)})

    @app.delete("/api/admin/backups/{filename}")
    async def delete_backup(filename: str):
        """Delete a specific backup file."""
        try:
            mgr = _get_backup_manager()
            if mgr.delete_backup(filename):
                return JSONResponse(200, {"status": "deleted", "filename": filename})
            return JSONResponse(404, {"error": f"Backup not found: {filename}"})
        except Exception as exc:
            logger.error("Backup deletion failed: %s", exc)
            return JSONResponse(500, {"error": str(exc)})
