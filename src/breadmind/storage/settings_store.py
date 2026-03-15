"""File-based settings store — DB-free fallback for persisting UI settings.

Stores all settings in a single JSON file (settings.json) in the config directory.
Used when no database is available. The web app's set_setting/get_setting calls
are routed here transparently.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FileSettingsStore:
    """Simple JSON file-based key-value store for settings."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load settings from {self._path}: {e}")
                self._data = {}

    def _save(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as e:
            logger.error(f"Failed to save settings to {self._path}: {e}")

    async def get_setting(self, key: str) -> Any:
        return self._data.get(key)

    async def set_setting(self, key: str, value: Any):
        self._data[key] = value
        self._save()

    async def delete_setting(self, key: str):
        self._data.pop(key, None)
        self._save()

    async def connect(self):
        """No-op for interface compatibility with Database."""
        pass

    async def disconnect(self):
        """No-op for interface compatibility with Database."""
        pass
