from __future__ import annotations

import json
from pathlib import Path


class PluginRegistry:
    def __init__(self, registry_path: Path):
        self._path = registry_path
        self._data: dict = {}
        self._load()

    def _load(self):
        if self._path.exists():
            self._data = json.loads(self._path.read_text(encoding="utf-8"))
        else:
            self._data = {}

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    async def add(self, name: str, info: dict):
        self._data[name] = info
        self._save()

    async def remove(self, name: str):
        self._data.pop(name, None)
        self._save()

    async def list_all(self) -> dict:
        return dict(self._data)

    async def get(self, name: str) -> dict | None:
        return self._data.get(name)

    async def set_enabled(self, name: str, enabled: bool):
        if name in self._data:
            self._data[name]["enabled"] = enabled
            self._save()
