from __future__ import annotations
import logging
from pathlib import Path

logger = logging.getLogger("breadmind.plugins.marketplace")


class MarketplaceClient:
    def __init__(self, registries: list[dict] | None = None):
        self._registries = registries or [
            {"name": "breadmind-official", "url": "https://plugins.breadmind.dev/registry.json"},
        ]
        self._cache: list[dict] = []

    async def search(self, query: str, tags: list[str] | None = None) -> list[dict]:
        all_plugins = await self._fetch_all()
        query_lower = query.lower()
        results = []
        for p in all_plugins:
            if query_lower in p.get("name", "").lower() or query_lower in p.get("description", "").lower():
                if tags:
                    if any(t in p.get("tags", []) for t in tags):
                        results.append(p)
                else:
                    results.append(p)
        return results

    async def get_info(self, plugin_name: str) -> dict | None:
        all_plugins = await self._fetch_all()
        for p in all_plugins:
            if p.get("name") == plugin_name:
                return p
        return None

    async def install(self, plugin_name: str, target_dir: Path) -> Path:
        info = await self.get_info(plugin_name)
        if not info:
            raise ValueError(f"Plugin not found in marketplace: {plugin_name}")
        source = info.get("source", "")
        if not source:
            raise ValueError(f"Plugin {plugin_name} has no source URL")
        # Git clone
        import asyncio
        target = target_dir / plugin_name
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", source, str(target),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git clone failed: {stderr.decode()}")
        return target

    async def check_updates(self, installed: dict) -> list[dict]:
        all_plugins = await self._fetch_all()
        updates = []
        for p in all_plugins:
            name = p.get("name", "")
            if name in installed:
                if p.get("version", "") != installed[name].get("version", ""):
                    updates.append({**p, "current_version": installed[name].get("version", "")})
        return updates

    async def _fetch_all(self) -> list[dict]:
        if self._cache:
            return self._cache
        all_plugins = []
        for reg in self._registries:
            try:
                plugins = await self._fetch_registry(reg["url"])
                all_plugins.extend(plugins)
            except Exception as e:
                logger.warning(f"Failed to fetch registry {reg['name']}: {e}")
        self._cache = all_plugins
        return all_plugins

    async def _fetch_registry(self, url: str) -> list[dict]:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("plugins", [])
                return []
