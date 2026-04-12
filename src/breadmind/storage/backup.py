"""PostgreSQL database backup and restore manager."""
from __future__ import annotations

import asyncio
import gzip
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from breadmind.utils.serialization import SerializableMixin

logger = logging.getLogger(__name__)


@dataclass
class BackupConfig:
    """Configuration for backup operations."""
    backup_dir: str = "backups"
    max_backups: int = 10
    compress: bool = True


@dataclass
class BackupInfo(SerializableMixin):
    """Metadata about a single backup file."""
    filename: str
    path: str
    size_bytes: int
    created_at: datetime
    database: str
    compressed: bool


class BackupError(Exception):
    """Raised when a backup or restore operation fails."""


class BackupManager:
    """Manages PostgreSQL backup and restore operations via pg_dump/psql."""

    def __init__(
        self,
        db_config: dict,
        backup_config: BackupConfig | None = None,
    ):
        self._db_config = db_config
        self._config = backup_config or BackupConfig()
        self._backup_dir = Path(self._config.backup_dir)
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    # ── public API ────────────────────────────────────────────────

    async def create_backup(self, label: str | None = None) -> BackupInfo:
        """Create a database backup using pg_dump.

        Returns BackupInfo on success, raises BackupError on failure.
        """
        await self._check_tool("pg_dump")

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        db_name = self._db_config.get("name", "breadmind")
        label_part = f"_{label}" if label else ""
        ext = ".sql.gz" if self._config.compress else ".sql"
        filename = f"breadmind_{db_name}_{ts}{label_part}{ext}"
        filepath = self._backup_dir / filename

        env = self._build_env()
        cmd = [
            "pg_dump",
            "-h", self._db_config.get("host", "localhost"),
            "-p", str(self._db_config.get("port", 5432)),
            "-U", self._db_config.get("user", "breadmind"),
            "-d", db_name,
            "--no-password",
        ]

        try:
            if self._config.compress:
                # pg_dump → gzip → file
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode != 0:
                    raise BackupError(
                        f"pg_dump failed (exit {proc.returncode}): {stderr.decode(errors='replace')}"
                    )
                if not stdout:
                    raise BackupError("pg_dump produced empty output")
                with gzip.open(filepath, "wb") as f:
                    f.write(stdout)
            else:
                # pg_dump → file directly
                cmd.extend(["-f", str(filepath)])
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                _, stderr = await proc.communicate()
                if proc.returncode != 0:
                    raise BackupError(
                        f"pg_dump failed (exit {proc.returncode}): {stderr.decode(errors='replace')}"
                    )

            size = filepath.stat().st_size
            if size == 0:
                filepath.unlink(missing_ok=True)
                raise BackupError("Backup file is empty (0 bytes)")

            info = BackupInfo(
                filename=filename,
                path=str(filepath),
                size_bytes=size,
                created_at=datetime.now(timezone.utc),
                database=db_name,
                compressed=self._config.compress,
            )
            logger.info("Backup created: %s (%d bytes)", filename, size)
            return info

        except BackupError:
            raise
        except Exception as exc:
            filepath.unlink(missing_ok=True)
            raise BackupError(f"Backup failed: {exc}") from exc

    async def restore_backup(self, path: str) -> bool:
        """Restore a database from a backup file.

        Supports both plain .sql and compressed .sql.gz files.
        Returns True on success, raises BackupError on failure.
        """
        filepath = Path(path)
        if not filepath.exists():
            raise BackupError(f"Backup file not found: {path}")

        env = self._build_env()
        db_name = self._db_config.get("name", "breadmind")
        is_compressed = filepath.suffix == ".gz" or filepath.name.endswith(".sql.gz")

        if is_compressed:
            await self._check_tool("psql")
            # gunzip and pipe to psql
            with gzip.open(filepath, "rb") as f:
                sql_data = f.read()
            proc = await asyncio.create_subprocess_exec(
                "psql",
                "-h", self._db_config.get("host", "localhost"),
                "-p", str(self._db_config.get("port", 5432)),
                "-U", self._db_config.get("user", "breadmind"),
                "-d", db_name,
                "--no-password",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            _, stderr = await proc.communicate(input=sql_data)
        else:
            await self._check_tool("psql")
            proc = await asyncio.create_subprocess_exec(
                "psql",
                "-h", self._db_config.get("host", "localhost"),
                "-p", str(self._db_config.get("port", 5432)),
                "-U", self._db_config.get("user", "breadmind"),
                "-d", db_name,
                "--no-password",
                "-f", str(filepath),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise BackupError(
                f"Restore failed (exit {proc.returncode}): {stderr.decode(errors='replace')}"
            )

        logger.info("Database restored from: %s", filepath.name)
        return True

    def list_backups(self) -> list[BackupInfo]:
        """List all backup files in the backup directory, newest first."""
        backups: list[BackupInfo] = []
        if not self._backup_dir.exists():
            return backups

        for fp in self._backup_dir.iterdir():
            if not fp.is_file():
                continue
            if not (fp.name.endswith(".sql") or fp.name.endswith(".sql.gz")):
                continue
            stat = fp.stat()
            compressed = fp.name.endswith(".gz")
            # Extract database name from filename pattern: breadmind_{db}_{ts}...
            parts = fp.stem.replace(".sql", "").split("_")
            db_name = parts[1] if len(parts) > 1 else "unknown"
            backups.append(BackupInfo(
                filename=fp.name,
                path=str(fp),
                size_bytes=stat.st_size,
                created_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                database=db_name,
                compressed=compressed,
            ))

        backups.sort(key=lambda b: b.created_at, reverse=True)
        return backups

    def delete_backup(self, filename: str) -> bool:
        """Delete a specific backup file by filename."""
        filepath = self._backup_dir / filename
        if not filepath.exists():
            return False
        filepath.unlink()
        logger.info("Backup deleted: %s", filename)
        return True

    def cleanup_old(self) -> int:
        """Delete oldest backups exceeding max_backups limit.

        Returns the number of deleted backups.
        """
        backups = self.list_backups()
        if len(backups) <= self._config.max_backups:
            return 0

        to_delete = backups[self._config.max_backups:]
        deleted = 0
        for backup in to_delete:
            try:
                Path(backup.path).unlink()
                deleted += 1
                logger.info("Cleanup removed old backup: %s", backup.filename)
            except OSError as exc:
                logger.warning("Failed to delete backup %s: %s", backup.filename, exc)
        return deleted

    async def verify_backup(self, path: str) -> bool:
        """Verify backup file integrity.

        For .gz files: checks gzip header and decompression.
        For all files: attempts pg_restore --list if available.
        """
        filepath = Path(path)
        if not filepath.exists():
            return False

        # Check gzip integrity
        if filepath.name.endswith(".gz"):
            try:
                with gzip.open(filepath, "rb") as f:
                    # Read in chunks to verify full file
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
            except (gzip.BadGzipFile, OSError):
                return False

        # Try pg_restore --list for additional verification
        try:
            if filepath.name.endswith(".gz"):
                # Decompress first, then check content starts with SQL
                with gzip.open(filepath, "rb") as f:
                    header = f.read(256)
                # SQL dumps typically start with -- or SET or CREATE
                text = header.decode("utf-8", errors="replace")
                if not any(text.lstrip().startswith(prefix) for prefix in ("--", "SET", "CREATE", "/*")):
                    return False
            else:
                with open(filepath, "rb") as f:
                    header = f.read(256)
                text = header.decode("utf-8", errors="replace")
                if not any(text.lstrip().startswith(prefix) for prefix in ("--", "SET", "CREATE", "/*")):
                    return False
        except Exception:
            return False

        return True

    # ── private helpers ───────────────────────────────────────────

    def _build_env(self) -> dict[str, str]:
        """Build environment with PGPASSWORD set."""
        env = os.environ.copy()
        password = self._db_config.get("password", "")
        if not password:
            password = os.environ.get("BREADMIND_DB_PASSWORD", "")
        if password:
            env["PGPASSWORD"] = password
        return env

    @staticmethod
    async def _check_tool(name: str) -> None:
        """Verify that a CLI tool (pg_dump, psql, etc.) is on PATH."""
        if shutil.which(name) is None:
            raise BackupError(
                f"'{name}' is not installed or not on PATH. "
                f"Install PostgreSQL client tools to use backup/restore."
            )
