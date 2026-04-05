"""4-tier settings scope hierarchy with managed > local > project > user precedence."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path


class SettingsScope(IntEnum):
    USER = 0  # ~/.breadmind/settings.json (global defaults)
    PROJECT = 1  # .breadmind/settings.json (team-shared, committed)
    LOCAL = 2  # .breadmind/settings.local.json (personal project, gitignored)
    MANAGED = 3  # managed-settings.json (enterprise IT, cannot override)


@dataclass
class ScopedSettings:
    scope: SettingsScope
    data: dict = field(default_factory=dict)
    source_path: Path | None = None


class SettingsHierarchy:
    """4-tier settings with managed > local > project > user precedence.

    Scalar values: higher scope wins.
    Array values (permissions.allow, permissions.deny): concatenated and
    deduplicated across scopes.
    """

    ARRAY_KEYS = {"permissions.allow", "permissions.deny", "mcp.servers", "rules"}

    def __init__(self) -> None:
        self._layers: dict[SettingsScope, ScopedSettings] = {}

    def load_scope(self, scope: SettingsScope, path: Path) -> None:
        """Load settings from a JSON file for the given scope."""
        path = Path(path)
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        self._layers[scope] = ScopedSettings(
            scope=scope, data=data, source_path=path
        )

    def set_scope(
        self,
        scope: SettingsScope,
        data: dict,
        source_path: Path | None = None,
    ) -> None:
        """Directly set data for a scope."""
        self._layers[scope] = ScopedSettings(
            scope=scope, data=dict(data), source_path=source_path
        )

    def get(self, dotted_key: str, default=None):
        """Get a resolved value. Managed > Local > Project > User.

        For ARRAY_KEYS, concatenate+dedup across all scopes.
        """
        if dotted_key in self.ARRAY_KEYS:
            return self._get_array(dotted_key, default)
        # Scalar: highest scope wins
        for scope in sorted(self._layers, reverse=True):
            layer = self._layers[scope]
            val = self._deep_get(layer.data, dotted_key)
            if val is not None:
                return val
        return default

    def is_managed(self, dotted_key: str) -> bool:
        """Check if a key is locked by managed settings."""
        if SettingsScope.MANAGED not in self._layers:
            return False
        val = self._deep_get(
            self._layers[SettingsScope.MANAGED].data, dotted_key
        )
        return val is not None

    def resolve_all(self) -> dict:
        """Return fully merged settings dict."""
        result: dict = {}
        for scope in sorted(self._layers):
            layer = self._layers[scope]
            result = self._merge_dicts(result, layer.data)
        return result

    def _get_array(self, dotted_key: str, default):
        """Concatenate and deduplicate array values across all scopes."""
        combined: list = []
        for scope in sorted(self._layers):
            layer = self._layers[scope]
            val = self._deep_get(layer.data, dotted_key)
            if isinstance(val, list):
                combined.extend(val)
        if not combined:
            return default
        # Deduplicate preserving order
        seen: set = set()
        deduped: list = []
        for item in combined:
            key = json.dumps(item, sort_keys=True) if isinstance(item, dict) else item
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        return deduped

    def _deep_get(self, data: dict, dotted_key: str, default=None):
        """Navigate nested dict with dotted key."""
        keys = dotted_key.split(".")
        current = data
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
        return current

    def _merge_dicts(self, base: dict, override: dict) -> dict:
        """Deep merge, arrays concatenated for ARRAY_KEYS, otherwise overridden."""
        result = dict(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_dicts(result[key], value)
            elif key in result and isinstance(result[key], list) and isinstance(value, list):
                # Check if this key path is an ARRAY_KEY
                # For top-level merge, concatenate lists
                result[key] = self._deduplicate_list(result[key] + value)
            else:
                result[key] = value
        return result

    @staticmethod
    def _deduplicate_list(items: list) -> list:
        seen: set = set()
        deduped: list = []
        for item in items:
            key = json.dumps(item, sort_keys=True) if isinstance(item, dict) else item
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        return deduped

    @classmethod
    def load_default(
        cls,
        user_dir: Path | None = None,
        project_dir: Path | None = None,
    ) -> SettingsHierarchy:
        """Load settings from standard paths."""
        h = cls()
        # User scope
        if user_dir is None:
            user_dir = Path.home() / ".breadmind"
        h.load_scope(SettingsScope.USER, user_dir / "settings.json")

        # Project scope
        if project_dir is not None:
            h.load_scope(SettingsScope.PROJECT, project_dir / ".breadmind" / "settings.json")
            h.load_scope(SettingsScope.LOCAL, project_dir / ".breadmind" / "settings.local.json")

        # Managed scope
        managed_path = os.environ.get("BREADMIND_MANAGED_SETTINGS")
        if managed_path:
            h.load_scope(SettingsScope.MANAGED, Path(managed_path))
        else:
            # System-wide default paths
            for candidate in [
                Path("/etc/breadmind/managed-settings.json"),
                Path("C:/ProgramData/breadmind/managed-settings.json"),
            ]:
                if candidate.is_file():
                    h.load_scope(SettingsScope.MANAGED, candidate)
                    break

        return h
