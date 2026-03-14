import asyncio
from dataclasses import dataclass


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


class RegistrySearchEngine:
    def __init__(self, registries: list[RegistryConfig]):
        self._registries = registries

    async def search(self, query: str, limit: int = 10) -> list[RegistrySearchResult]:
        tasks = []
        for reg in self._registries:
            if not reg.enabled:
                continue
            if reg.type == "clawhub":
                tasks.append(self._safe_search(self._search_clawhub, query, limit))
            elif reg.type == "mcp_registry":
                tasks.append(self._safe_search(self._search_mcp_registry, query, limit))
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
            return []

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
                    # Build install command from package info
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
