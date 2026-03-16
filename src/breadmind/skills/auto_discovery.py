"""Auto-discover and install skills from marketplace based on detected environment.

Flow:
1. Detect installed software (package managers, services, tools)
2. Search marketplace (skills.sh, clawhub, etc.) for matching skills
3. Install top matches
4. Fall back to builtin skills if marketplace is unavailable

This runs during bootstrap and periodically (e.g., after env refresh).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Search queries per detected software → marketplace search terms
_SOFTWARE_TO_QUERIES: dict[str, list[str]] = {
    # Web servers
    "nginx": ["nginx administration", "nginx management"],
    "apache": ["apache httpd administration"],
    "caddy": ["caddy server"],
    "traefik": ["traefik proxy"],
    # Databases
    "mysql": ["mysql database administration"],
    "postgresql": ["postgresql database"],
    "redis": ["redis administration"],
    "mongodb": ["mongodb administration"],
    # Security
    "certbot": ["ssl certificate management"],
    "fail2ban": ["fail2ban intrusion prevention"],
    # Virtualization
    "proxmox": ["proxmox virtualization"],
    "virsh": ["kvm qemu virtualization"],
    "docker": ["docker container management"],
    "kubectl": ["kubernetes administration"],
    # Monitoring
    "prometheus": ["prometheus monitoring"],
    "grafana": ["grafana dashboard"],
    "zabbix": ["zabbix monitoring"],
    # CI/CD
    "jenkins": ["jenkins ci cd"],
    "gitlab-runner": ["gitlab ci runner"],
    "gh": ["github cli actions"],
    # Storage
    "zfs": ["zfs storage management"],
    "nfs": ["nfs network storage"],
    # Network
    "wireguard": ["wireguard vpn"],
    "openvpn": ["openvpn"],
    "haproxy": ["haproxy load balancer"],
    "named": ["bind dns server"],
}


@dataclass
class DiscoveryResult:
    """Result of auto-discovery process."""
    searched: int = 0
    installed: int = 0
    failed: int = 0
    fallback_used: int = 0
    details: list[str] = field(default_factory=list)


async def auto_discover_skills(
    detected_tools: list[str],
    search_engine,
    skill_store,
    max_per_domain: int = 1,
    timeout: float = 30,
) -> DiscoveryResult:
    """Search marketplace for skills matching detected tools and install them.

    Args:
        detected_tools: List of detected tool/software names (e.g., ["nginx", "psql", "docker"]).
        search_engine: RegistrySearchEngine instance for marketplace search.
        skill_store: SkillStore to install skills into.
        max_per_domain: Max skills to install per detected tool.
        timeout: Total timeout for all marketplace searches.

    Returns:
        DiscoveryResult with stats.
    """
    import asyncio

    result = DiscoveryResult()

    if not search_engine or not skill_store:
        return result

    # Build search queries from detected tools
    queries: list[tuple[str, str]] = []  # (tool_name, search_query)
    for tool in detected_tools:
        tool_lower = tool.lower()
        if tool_lower in _SOFTWARE_TO_QUERIES:
            for q in _SOFTWARE_TO_QUERIES[tool_lower]:
                queries.append((tool_lower, q))

    if not queries:
        return result

    # Deduplicate queries
    seen_queries: set[str] = set()
    unique_queries: list[tuple[str, str]] = []
    for tool, query in queries:
        if query not in seen_queries:
            seen_queries.add(query)
            unique_queries.append((tool, query))

    # Search marketplace with overall timeout
    try:
        results_map = await asyncio.wait_for(
            _search_all(unique_queries, search_engine, max_per_domain),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("Skill auto-discovery timed out after %.0fs", timeout)
        result.details.append("Marketplace search timed out")
        return result

    # Install found skills
    for tool_name, search_results in results_map.items():
        for sr in search_results[:max_per_domain]:
            result.searched += 1
            try:
                installed = await _install_from_result(sr, skill_store)
                if installed:
                    result.installed += 1
                    result.details.append(f"Installed '{sr.name}' for {tool_name}")
                    logger.info("Auto-installed skill '%s' for detected tool '%s'", sr.name, tool_name)
            except Exception as e:
                result.failed += 1
                logger.warning("Failed to install skill '%s': %s", sr.name, e)

    return result


async def _search_all(queries, search_engine, max_per_domain):
    """Search marketplace for all queries concurrently."""
    import asyncio

    results_map: dict[str, list] = {}

    async def _search_one(tool_name: str, query: str):
        try:
            hits = await search_engine.search(query, limit=max_per_domain)
            if hits:
                if tool_name not in results_map:
                    results_map[tool_name] = []
                results_map[tool_name].extend(hits)
        except Exception:
            logger.debug("Search failed for query: %s", query)

    await asyncio.gather(*[_search_one(t, q) for t, q in queries])
    return results_map


async def _install_from_result(search_result, skill_store) -> bool:
    """Install a skill from a marketplace search result.

    Tries slug-based install (GitHub SKILL.md download) if slug is available.
    Otherwise creates a minimal skill from the search result metadata.
    """
    # Skip if already installed
    existing = await skill_store.get_skill(search_result.name)
    if existing is not None:
        return False

    slug = getattr(search_result, "slug", "")

    # Try GitHub-based install if slug is in owner/repo/skill format
    if slug and "/" in slug:
        try:
            installed = await _install_from_github(slug, skill_store)
            if installed:
                return True
        except Exception:
            logger.debug("GitHub install failed for %s, using metadata", slug)

    # Fallback: create skill from search result metadata
    description = getattr(search_result, "description", "") or ""
    if not description:
        return False

    import re
    words = re.findall(r'[a-zA-Z0-9가-힣_-]+', f"{search_result.name} {description}".lower())
    keywords = list(set(w for w in words if len(w) > 2))[:15]

    await skill_store.add_skill(
        name=search_result.name,
        description=description,
        prompt_template=description,  # Minimal — description as prompt
        trigger_keywords=keywords,
        source=f"marketplace:{getattr(search_result, 'source', 'unknown')}",
    )
    return True


async def _install_from_github(slug: str, skill_store) -> bool:
    """Download and install skill from GitHub via SKILL.md."""
    import aiohttp

    parts = slug.strip().split("/")
    if len(parts) < 3:
        return False

    owner, repo = parts[0], parts[1]
    skill_name = "/".join(parts[2:])

    paths = [
        f"skills/{skill_name}/SKILL.md",
        f"{skill_name}/SKILL.md",
        f"skills/{skill_name}.md",
    ]

    content = None
    async with aiohttp.ClientSession() as session:
        for path in paths:
            url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/{path}"
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        break
            except Exception:
                continue

    if not content:
        return False

    # Parse YAML frontmatter
    description = ""
    prompt_template = content
    if content.startswith("---"):
        parts_md = content.split("---", 2)
        if len(parts_md) >= 3:
            try:
                import yaml
                meta = yaml.safe_load(parts_md[1])
                if isinstance(meta, dict):
                    description = meta.get("description", "")
                    meta_name = meta.get("name", "")
                    if meta_name:
                        skill_name = meta_name
            except Exception:
                pass
            prompt_template = parts_md[2].strip()

    import re
    words = re.findall(r'[a-zA-Z0-9_-]+', f"{skill_name} {description}".lower())
    trigger_keywords = list(set(w for w in words if len(w) > 2))[:15]

    existing = await skill_store.get_skill(skill_name)
    if existing:
        return False

    await skill_store.add_skill(
        name=skill_name,
        description=description,
        prompt_template=prompt_template,
        trigger_keywords=trigger_keywords,
        source=f"marketplace:{slug}",
    )
    return True


async def apply_fallback_skills(
    detected_tools: list[str],
    skill_store,
):
    """Register builtin domain skills as fallback when marketplace is unavailable.

    Only registers skills for domains that have no marketplace-installed skill.
    """
    from breadmind.skills.domain_skills import ALL_DOMAIN_SKILLS, _DETECTION_MAP

    for domain_name, tool_checks in _DETECTION_MAP.items():
        # Check if any tool in this domain is detected
        domain_detected = False
        for tool_name in tool_checks:
            if tool_name in detected_tools:
                domain_detected = True
                break

        if not domain_detected:
            continue

        # Check if a skill for this domain already exists (from marketplace)
        skill_def = ALL_DOMAIN_SKILLS.get(domain_name)
        if skill_def is None:
            continue

        existing = await skill_store.get_skill(skill_def.name)
        if existing is not None:
            continue  # Marketplace skill already installed, skip builtin

        await skill_store.add_skill(
            name=skill_def.name,
            description=skill_def.description,
            prompt_template=skill_def.prompt_template,
            trigger_keywords=skill_def.trigger_keywords,
            source="builtin-fallback",
        )
        logger.info("Registered fallback skill '%s' (no marketplace match)", skill_def.name)
