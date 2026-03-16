"""MCP server management and skill search routes."""
from __future__ import annotations

import asyncio
import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mcp"])


def setup_mcp_routes(r: APIRouter, app_state):
    """Register /api/mcp/* and /api/skills/search, /api/skills/featured routes."""

    @r.get("/api/mcp/servers")
    async def list_mcp_servers():
        if app_state._mcp_manager:
            servers = await app_state._mcp_manager.list_servers()
            return {"servers": [
                {"name": s.name, "transport": s.transport, "status": s.status, "tools": s.tools, "source": s.source}
                for s in servers
            ]}
        return {"servers": []}

    @r.get("/api/mcp/search")
    async def mcp_search(q: str = "", limit: int = 10, source: str = ""):
        if not app_state._mcp_store:
            return {"results": []}
        results = await app_state._mcp_store.search(q, limit=limit)
        # Exclude skill-only sources from MCP search
        results = [r for r in results if r.get("source") not in ("skills.sh", "skillsmp")]
        if source:
            results = [r for r in results if r.get("source") == source]
        return {"results": results}

    @r.get("/api/mcp/featured")
    async def mcp_featured(source: str = ""):
        """Return featured/recommended MCP servers by category."""
        if not app_state._mcp_store:
            return {"categories": []}
        categories = [
            {"name": "Infrastructure", "icon": "\U0001f3d7\ufe0f", "query": "kubernetes docker"},
            {"name": "Development", "icon": "\U0001f4bb", "query": "github git code"},
            {"name": "Database", "icon": "\U0001f5c4\ufe0f", "query": "database sql postgres"},
            {"name": "AI & LLM", "icon": "\U0001f916", "query": "ai llm openai"},
            {"name": "Monitoring", "icon": "\U0001f4ca", "query": "monitoring metrics"},
            {"name": "Cloud", "icon": "\u2601\ufe0f", "query": "aws azure cloud"},
            {"name": "Network", "icon": "\U0001f310", "query": "network http api"},
            {"name": "File & Storage", "icon": "\U0001f4c1", "query": "file storage s3"},
        ]

        async def fetch_category(cat):
            results = await app_state._mcp_store.search(cat["query"], limit=4)
            # Exclude skill-only sources from MCP store
            results = [r for r in results if r.get("source") not in ("skills.sh", "skillsmp")]
            if source:
                results = [r for r in results if r.get("source") == source]
            return {**cat, "servers": results}
        tasks = [fetch_category(c) for c in categories]
        filled = await asyncio.gather(*tasks)
        # Only return categories that have results
        return {"categories": [c for c in filled if c.get("servers")]}

    # --- Skill Store endpoints ---

    @r.get("/api/skills/search")
    async def skill_search(q: str = "", limit: int = 10):
        """Search skills from skill markets (skills.sh etc.)."""
        if not app_state._search_engine:
            return {"results": []}
        results = await app_state._search_engine.search(q, limit=limit)
        # Filter to skill-type sources only (not MCP)
        skill_sources = {"skills_sh", "skillsmp"}
        filtered = [
            {"name": r.name, "slug": r.slug, "description": r.description,
             "source": r.source, "install_command": r.install_command, "installs": r.installs}
            for r in results if r.source in skill_sources or any(
                reg.type in skill_sources for reg in app_state._search_engine.get_registries()
                if reg.name == r.source
            )
        ]
        return {"results": filtered}

    @r.get("/api/skills/featured")
    async def skill_featured():
        """Return featured skills by category from skill markets."""
        if not app_state._search_engine:
            return {"categories": []}
        categories = [
            {"name": "Frontend", "icon": "\U0001f3a8", "queries": ["react", "css", "frontend", "design"]},
            {"name": "Backend", "icon": "\u2699\ufe0f", "queries": ["api", "server", "backend", "database"]},
            {"name": "DevOps", "icon": "\U0001f680", "queries": ["docker", "kubernetes", "deploy", "ci"]},
            {"name": "AI & ML", "icon": "\U0001f916", "queries": ["ai", "llm", "machine learning"]},
            {"name": "Testing", "icon": "\U0001f9ea", "queries": ["test", "quality", "lint"]},
            {"name": "Security", "icon": "\U0001f512", "queries": ["security", "auth", "crypto"]},
            {"name": "Best Practices", "icon": "\U0001f4da", "queries": ["best-practices", "review", "guidelines"]},
            {"name": "Cloud", "icon": "\u2601\ufe0f", "queries": ["aws", "azure", "cloud", "gcp"]},
        ]
        skill_sources = {"skills.sh", "skillsmp"}

        async def fetch_cat(cat):
            all_results = []
            seen = set()
            for q in cat["queries"]:
                results = await app_state._search_engine.search(q, limit=4)
                for r in results:
                    if r.source in skill_sources and r.name not in seen:
                        seen.add(r.name)
                        all_results.append({
                            "name": r.name, "slug": r.slug, "description": r.description,
                            "source": r.source, "install_command": r.install_command,
                            "installs": r.installs,
                        })
            # Sort by installs, take top 4
            all_results.sort(key=lambda x: x.get("installs", 0), reverse=True)
            return {**cat, "skills": all_results[:4]}
        tasks = [fetch_cat(c) for c in categories]
        filled = await asyncio.gather(*tasks)
        return {"categories": [c for c in filled if c.get("skills")]}

    @r.get("/api/mcp/server-detail")
    async def mcp_detail(source: str = "", slug: str = ""):
        """Get detailed info for an MCP server."""
        import aiohttp
        detail = {"slug": slug, "source": source, "name": slug, "description": "", "version": "",
                  "website": "", "repository": "", "install_command": "",
                  "trust": {"level": "community", "verified": False, "official": False, "owner": "", "has_repo": False, "updated_at": ""}}
        try:
            if source == "clawhub":
                detail["website"] = f"https://clawhub.ai/skills/{slug}"
                detail["install_command"] = f"clawhub install {slug}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        "https://clawhub.ai/api/search",
                        params={"q": slug, "limit": 5},
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for r in data.get("results", []):
                                if r.get("slug") == slug:
                                    detail["name"] = r.get("displayName", slug)
                                    detail["description"] = r.get("summary", "")
                                    detail["version"] = r.get("version") or ""
                                    # Trust info from ClawHub
                                    updated = r.get("updatedAt")
                                    if updated:
                                        from datetime import datetime, timezone
                                        try:
                                            dt = datetime.fromtimestamp(updated / 1000, tz=timezone.utc)
                                            detail["trust"]["updated_at"] = dt.strftime("%Y-%m-%d")
                                        except Exception:
                                            pass
                                    break
                    # Check owner via page URL pattern
                    detail["trust"]["owner"] = "clawhub"
                    # Official ClawHub skills are under @skills owner
                    if slug.startswith("openclaw") or slug in ("docker-essentials", "git-essentials", "kubernetes-devops"):
                        detail["trust"]["official"] = True
                        detail["trust"]["verified"] = True
                        detail["trust"]["level"] = "official"
                    else:
                        detail["trust"]["level"] = "community"

            elif source == "mcp_registry":
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"https://registry.modelcontextprotocol.io/v0.1/servers/{slug}/versions/latest",
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            srv = data.get("server", data)
                            detail["name"] = srv.get("title", srv.get("name", slug))
                            detail["description"] = srv.get("description", "")
                            detail["version"] = srv.get("version", "")
                            detail["website"] = srv.get("websiteUrl", "")
                            repo = srv.get("repository", {})
                            detail["repository"] = repo.get("url", "") if isinstance(repo, dict) else ""
                            detail["install_command"] = f"npx -y {slug}"
                            # Trust info from MCP Registry _meta
                            meta = data.get("_meta", {})
                            official_meta = meta.get("io.modelcontextprotocol.registry/official", {})
                            if official_meta.get("status") == "active":
                                detail["trust"]["verified"] = True
                                detail["trust"]["official"] = True
                                detail["trust"]["level"] = "verified"
                            detail["trust"]["has_repo"] = bool(detail["repository"])
                            detail["trust"]["owner"] = repo.get("source", "") if isinstance(repo, dict) else ""
                            updated = official_meta.get("updatedAt", "")
                            if updated:
                                detail["trust"]["updated_at"] = updated[:10]
        except Exception as e:
            logger.warning(f"Failed to fetch detail for {source}/{slug}: {e}")
        return {"detail": detail}

    @r.post("/api/mcp/install/analyze")
    async def mcp_install_analyze(request: Request):
        if not app_state._mcp_store:
            return JSONResponse(status_code=503, content={"error": "MCP Store not configured"})
        data = await request.json()
        analysis = await app_state._mcp_store.analyze_server(data)
        return {"analysis": analysis}

    @r.post("/api/mcp/install/execute")
    async def mcp_install_execute(request: Request):
        if not app_state._mcp_store:
            return JSONResponse(status_code=503, content={"error": "MCP Store not configured"})
        data = await request.json()
        result = await app_state._mcp_store.install_server(
            name=data.get("name", ""),
            slug=data.get("slug", ""),
            command=data.get("command", ""),
            args=data.get("args", []),
            env=data.get("env", {}),
            source=data.get("source", ""),
            runtime=data.get("runtime", ""),
        )
        # Broadcast install event to WebSocket clients
        if result.get("status") == "ok":
            await app_state.broadcast_event({"type": "mcp_installed", "server": result})
        return result

    @r.post("/api/mcp/install/troubleshoot")
    async def mcp_install_troubleshoot(request: Request):
        if not app_state._mcp_store:
            return JSONResponse(status_code=503, content={"error": "MCP Store not configured"})
        data = await request.json()
        if not app_state._mcp_store._assistant:
            return JSONResponse(status_code=503, content={"error": "LLM not available for troubleshooting"})
        fix = await app_state._mcp_store._assistant.troubleshoot(
            data.get("server_name", ""), data.get("command", ""),
            data.get("args", []), data.get("error_log", ""),
        )
        return {"fix": fix}

    @r.get("/api/mcp/installed")
    async def mcp_installed():
        if not app_state._mcp_store:
            return {"servers": []}
        servers = await app_state._mcp_store.list_installed()
        return {"servers": servers}

    @r.post("/api/mcp/servers/{name}/start")
    async def mcp_server_start(name: str):
        if not app_state._mcp_store:
            return JSONResponse(status_code=503, content={"error": "MCP Store not configured"})
        result = await app_state._mcp_store.start_server(name)
        return result

    @r.post("/api/mcp/servers/{name}/stop")
    async def mcp_server_stop(name: str):
        if not app_state._mcp_store:
            return JSONResponse(status_code=503, content={"error": "MCP Store not configured"})
        result = await app_state._mcp_store.stop_server(name)
        return result

    @r.delete("/api/mcp/servers/{name}")
    async def mcp_server_remove(name: str):
        if not app_state._mcp_store:
            return JSONResponse(status_code=503, content={"error": "MCP Store not configured"})
        result = await app_state._mcp_store.remove_server(name)
        return result

    @r.get("/api/mcp/servers/{name}/tools")
    async def mcp_server_tools(name: str):
        if not app_state._mcp_store:
            return {"tools": []}
        tools = await app_state._mcp_store.get_server_tools(name)
        return {"tools": tools}
