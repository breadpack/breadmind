import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RegistryConfig:
    name: str
    type: str
    enabled: bool = True
    url: str | None = None


@dataclass
class RegistrySearchResult:
    name: str
    slug: str
    description: str
    source: str
    install_command: str | None
    installs: int = 0


class RegistrySearchEngine:
    def __init__(self, registries: list[RegistryConfig]):
        self._registries = registries
        self._skills_sh_cache: list[dict] = []
        self._skills_sh_cache_time: float = 0
        self._skills_sh_cache_ttl: int = 3600  # 1 hour

    def get_registries(self) -> list[RegistryConfig]:
        return list(self._registries)

    def set_registries(self, registries: list[RegistryConfig]):
        self._registries = registries

    def add_registry(self, config: RegistryConfig):
        # Replace if same name exists
        self._registries = [r for r in self._registries if r.name != config.name]
        self._registries.append(config)

    def remove_registry(self, name: str) -> bool:
        before = len(self._registries)
        self._registries = [r for r in self._registries if r.name != name]
        return len(self._registries) < before

    def toggle_registry(self, name: str, enabled: bool) -> bool:
        for r in self._registries:
            if r.name == name:
                r.enabled = enabled
                return True
        return False

    async def search(self, query: str, limit: int = 10) -> list[RegistrySearchResult]:
        tasks = []
        for reg in self._registries:
            if not reg.enabled:
                continue
            if reg.type == "clawhub":
                tasks.append(self._safe_search(self._search_clawhub, query, limit))
            elif reg.type == "mcp_registry":
                tasks.append(self._safe_search(self._search_mcp_registry, query, limit))
            elif reg.type == "skills_sh":
                tasks.append(self._safe_search(self._search_skills_sh, query, limit))
            elif reg.type == "skillsmp":
                api_key = getattr(reg, "_api_key", None)
                tasks.append(self._safe_search(
                    lambda q, l: self._search_skillsmp(q, l, reg.url, api_key),
                    query, limit,
                ))
        all_results = await asyncio.gather(*tasks)
        merged = []
        seen_names = set()
        for results in all_results:
            for r in results:
                if r.name not in seen_names:
                    seen_names.add(r.name)
                    merged.append(r)
        return merged[:limit]

    async def _safe_search(self, func, query, limit) -> list[RegistrySearchResult]:
        try:
            return await func(query, limit)
        except Exception:
            logger.exception("Registry search failed")
            return []

    # ── skills.sh ──

    async def _fetch_skills_sh_data(self) -> list[dict]:
        """Fetch and cache skills.sh leaderboard data (SSR embedded)."""
        now = time.monotonic()
        if self._skills_sh_cache and (now - self._skills_sh_cache_time) < self._skills_sh_cache_ttl:
            return self._skills_sh_cache

        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get("https://skills.sh", timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return self._skills_sh_cache
                html = await resp.text()

        # Parse SSR-embedded initialSkills JSON
        try:
            idx = html.index("initialSkills")
            start = html.index("[{", idx)
            depth = 0
            end = start
            for i in range(start, min(start + 200000, len(html))):
                if html[i] == "[":
                    depth += 1
                elif html[i] == "]":
                    depth -= 1
                if depth == 0:
                    end = i + 1
                    break
            raw = html[start:end]
            raw = raw.encode().decode("unicode_escape", errors="replace")
            skills = json.loads(raw)
            self._skills_sh_cache = skills
            self._skills_sh_cache_time = now
            logger.info(f"skills.sh: cached {len(skills)} skills")
            return skills
        except (ValueError, json.JSONDecodeError):
            logger.warning("Failed to parse skills.sh data")
            return self._skills_sh_cache

    async def _search_skills_sh(self, query: str, limit: int) -> list[RegistrySearchResult]:
        skills = await self._fetch_skills_sh_data()
        if not skills:
            return []

        query_lower = query.lower()
        query_words = set(query_lower.split())

        scored: list[tuple[float, dict]] = []
        for skill in skills:
            name = skill.get("name", "").lower()
            source = skill.get("source", "").lower()
            full = f"{source}/{name}"

            # Score: exact match > word match > substring
            score = 0.0
            if query_lower == name:
                score = 100.0
            elif query_lower in name:
                score = 50.0
            elif any(w in name for w in query_words):
                score = 20.0
            elif any(w in source for w in query_words):
                score = 10.0

            if score > 0:
                # Boost by popularity
                installs = skill.get("installs", 0)
                score += min(installs / 10000, 10.0)
                scored.append((score, skill))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for _, skill in scored[:limit]:
            source = skill.get("source", "")
            name = skill.get("name", "")
            installs = skill.get("installs", 0)
            results.append(RegistrySearchResult(
                name=name,
                slug=f"{source}/{name}",
                description=f"{source} | {installs:,} installs",
                source="skills.sh",
                install_command=f"npx skills add {source}",
                installs=installs,
            ))
        return results

    # ── SkillsMP ──

    async def _search_skillsmp(self, query: str, limit: int,
                                url: str | None = None, api_key: str | None = None) -> list[RegistrySearchResult]:
        if not api_key:
            return []
        import aiohttp
        base = url or "https://skillsmp.com"
        headers = {"Authorization": f"Bearer {api_key}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{base}/api/v1/skills/search",
                params={"q": query, "limit": limit},
                headers=headers,
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return [
                    RegistrySearchResult(
                        name=item.get("name", ""),
                        slug=item.get("slug", ""),
                        description=item.get("description", ""),
                        source="skillsmp",
                        install_command=item.get("install_command"),
                        installs=item.get("installs", 0),
                    )
                    for item in data.get("skills", data.get("results", []))
                ]

    # ── ClewHub ──

    async def _search_clawhub(self, query: str, limit: int) -> list[RegistrySearchResult]:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://clawhub.ai/api/search",
                params={"q": query, "limit": limit},
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return [
                    RegistrySearchResult(
                        name=item.get("displayName", item.get("name", "")),
                        slug=item.get("slug", ""),
                        description=item.get("summary", item.get("description", "")),
                        source="clawhub",
                        install_command=f"clawhub install {item.get('slug', '')}",
                    )
                    for item in data.get("results", [])
                ]

    # ── MCP Registry ──

    async def _search_mcp_registry(self, query: str, limit: int) -> list[RegistrySearchResult]:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://registry.modelcontextprotocol.io/v0.1/servers",
                params={"q": query, "limit": limit},
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                results = []
                for item in data.get("servers", []):
                    srv = item.get("server", item)
                    name = srv.get("name", "")
                    desc = srv.get("description", "")
                    pkg = srv.get("packages", [{}])[0] if srv.get("packages") else {}
                    install_cmd = pkg.get("registry_name", "")
                    if not install_cmd and name:
                        install_cmd = f"npx -y {name}"
                    results.append(RegistrySearchResult(
                        name=srv.get("title", name),
                        slug=name,
                        description=desc,
                        source="mcp_registry",
                        install_command=install_cmd,
                    ))
                return results
