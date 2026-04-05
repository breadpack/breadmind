"""CLI backup and restore: archive/restore BreadMind configuration, sessions, and credentials."""
from __future__ import annotations

import json
import logging
import platform
import tarfile
import time
from dataclasses import asdict, dataclass, field
from io import BytesIO
from pathlib import Path

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "manifest.json"


@dataclass
class BackupManifest:
    version: str = "1.0"
    created_at: float = field(default_factory=time.time)
    hostname: str = field(default_factory=platform.node)
    includes: list[str] = field(default_factory=list)
    file_count: int = 0
    total_size: int = 0


@dataclass
class BackupOptions:
    include_config: bool = True
    include_sessions: bool = True
    include_credentials: bool = False  # Opt-in for security
    include_memory: bool = True
    include_plugins: bool = False
    only_config: bool = False  # Shorthand: only config files


class CLIBackupManager:
    """Backup and restore BreadMind state.

    Commands:
    - backup create [--only-config] [--include-credentials]
    - backup verify <archive>
    - backup restore <archive> [--dry-run]
    """

    def __init__(
        self,
        user_dir: Path | None = None,
        project_dir: Path | None = None,
    ) -> None:
        self._user_dir = user_dir or Path.home() / ".breadmind"
        self._project_dir = project_dir or Path.cwd() / ".breadmind"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(
        self,
        output_dir: Path | None = None,
        options: BackupOptions | None = None,
    ) -> Path:
        """Create a backup archive.  Returns path to the archive."""
        opts = options or BackupOptions()
        if opts.only_config:
            opts = BackupOptions(
                include_config=True,
                include_sessions=False,
                include_credentials=False,
                include_memory=False,
                include_plugins=False,
            )

        files = self._collect_files(opts)
        manifest = self._create_manifest(files, opts)

        out = output_dir or Path.cwd()
        out.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime(manifest.created_at))
        archive_path = out / f"breadmind_backup_{ts}.tar.gz"

        with tarfile.open(str(archive_path), "w:gz") as tar:
            # Add manifest
            manifest_bytes = json.dumps(asdict(manifest), indent=2).encode()
            info = tarfile.TarInfo(name=MANIFEST_FILENAME)
            info.size = len(manifest_bytes)
            tar.addfile(info, BytesIO(manifest_bytes))

            # Add collected files
            for fpath in files:
                arcname = self._arcname(fpath)
                tar.add(str(fpath), arcname=arcname)

        logger.info("Backup created: %s (%d files)", archive_path, manifest.file_count)
        return archive_path

    def verify(self, archive_path: Path) -> tuple[bool, BackupManifest | None, str]:
        """Verify archive integrity.  Returns (valid, manifest, message)."""
        if not archive_path.exists():
            return False, None, f"Archive not found: {archive_path}"

        try:
            with tarfile.open(str(archive_path), "r:gz") as tar:
                names = tar.getnames()
                if MANIFEST_FILENAME not in names:
                    return False, None, "Missing manifest in archive"

                mf = tar.extractfile(MANIFEST_FILENAME)
                if mf is None:
                    return False, None, "Cannot read manifest"
                manifest = BackupManifest(**json.loads(mf.read()))

                # file_count should match (members minus manifest)
                actual = len([n for n in names if n != MANIFEST_FILENAME])
                if actual != manifest.file_count:
                    return (
                        False,
                        manifest,
                        f"File count mismatch: manifest says {manifest.file_count}, "
                        f"archive has {actual}",
                    )

            return True, manifest, "Archive is valid"
        except (tarfile.TarError, json.JSONDecodeError, TypeError) as exc:
            return False, None, f"Corrupt archive: {exc}"

    def restore(self, archive_path: Path, dry_run: bool = False) -> list[str]:
        """Restore from archive.  Returns list of restored file paths.

        In dry_run mode, only lists what would be restored.
        """
        valid, manifest, msg = self.verify(archive_path)
        if not valid:
            raise ValueError(f"Cannot restore: {msg}")

        restored: list[str] = []
        with tarfile.open(str(archive_path), "r:gz") as tar:
            for member in tar.getmembers():
                if member.name == MANIFEST_FILENAME:
                    continue
                dest = self._restore_dest(member.name)
                restored.append(str(dest))
                if not dry_run:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    src = tar.extractfile(member)
                    if src is not None and member.isfile():
                        dest.write_bytes(src.read())

        return restored

    def list_backups(
        self, directory: Path | None = None
    ) -> list[tuple[Path, BackupManifest]]:
        """List available backups in a directory."""
        search_dir = directory or Path.cwd()
        results: list[tuple[Path, BackupManifest]] = []
        if not search_dir.is_dir():
            return results

        for p in sorted(search_dir.glob("breadmind_backup_*.tar.gz")):
            valid, manifest, _ = self.verify(p)
            if valid and manifest is not None:
                results.append((p, manifest))
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_files(self, options: BackupOptions) -> list[Path]:
        """Collect files to include in backup based on options."""
        files: list[Path] = []
        if options.include_config:
            files.extend(self._glob_existing(self._user_dir, "config*"))
            files.extend(self._glob_existing(self._project_dir, "config*"))
            files.extend(self._glob_existing(self._user_dir, "*.yaml"))
            files.extend(self._glob_existing(self._project_dir, "*.yaml"))
        if options.include_sessions:
            files.extend(self._glob_existing(self._user_dir, "sessions/**/*"))
            files.extend(self._glob_existing(self._project_dir, "sessions/**/*"))
        if options.include_credentials:
            files.extend(self._glob_existing(self._user_dir, "credentials*"))
            files.extend(self._glob_existing(self._project_dir, "credentials*"))
        if options.include_memory:
            files.extend(self._glob_existing(self._user_dir, "memory/**/*"))
            files.extend(self._glob_existing(self._project_dir, "memory/**/*"))
        if options.include_plugins:
            files.extend(self._glob_existing(self._user_dir, "plugins/**/*"))
            files.extend(self._glob_existing(self._project_dir, "plugins/**/*"))

        # Deduplicate while preserving order
        seen: set[Path] = set()
        unique: list[Path] = []
        for f in files:
            resolved = f.resolve()
            if resolved not in seen and f.is_file():
                seen.add(resolved)
                unique.append(f)
        return unique

    def _create_manifest(
        self, files: list[Path], options: BackupOptions
    ) -> BackupManifest:
        includes: list[str] = []
        if options.include_config:
            includes.append("config")
        if options.include_sessions:
            includes.append("sessions")
        if options.include_credentials:
            includes.append("credentials")
        if options.include_memory:
            includes.append("memory")
        if options.include_plugins:
            includes.append("plugins")

        total_size = sum(f.stat().st_size for f in files if f.is_file())
        return BackupManifest(
            includes=includes,
            file_count=len(files),
            total_size=total_size,
        )

    def _arcname(self, fpath: Path) -> str:
        """Compute archive member name relative to user_dir or project_dir."""
        resolved = fpath.resolve()
        for prefix_label, base in [
            ("user", self._user_dir.resolve()),
            ("project", self._project_dir.resolve()),
        ]:
            try:
                rel = resolved.relative_to(base)
                return f"{prefix_label}/{rel.as_posix()}"
            except ValueError:
                continue
        return f"other/{fpath.name}"

    def _restore_dest(self, arcname: str) -> Path:
        """Map archive member name back to filesystem path."""
        if arcname.startswith("user/"):
            return self._user_dir / arcname[len("user/"):]
        if arcname.startswith("project/"):
            return self._project_dir / arcname[len("project/"):]
        return self._project_dir / arcname

    @staticmethod
    def _glob_existing(base: Path, pattern: str) -> list[Path]:
        if not base.is_dir():
            return []
        return list(base.glob(pattern))
