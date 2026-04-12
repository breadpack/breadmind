import os
from dataclasses import dataclass
from pathlib import Path

from breadmind.cli.ui import get_ui


@dataclass
class CheckResult:
    name: str
    status: str  # "ok", "warn", "fail", "skip"
    detail: str = ""


async def run_doctor(args) -> None:
    """시스템 진단 실행."""
    ui = get_ui()
    ui.panel("BreadMind Doctor", "Running system diagnostics...")

    results: list[CheckResult] = []

    # 1. Config
    with ui.spinner("Checking configuration"):
        results.append(check_config())

    # 2. Python version
    with ui.spinner("Checking Python version"):
        results.append(check_python())

    # 3. Dependencies
    with ui.spinner("Checking dependencies"):
        results.extend(check_dependencies())

    # 4. LLM Providers
    with ui.spinner("Checking LLM providers"):
        results.extend(await check_providers())

    # 5. Database
    with ui.spinner("Checking database"):
        results.append(await check_database())

    # 6. MCP Servers
    with ui.spinner("Checking MCP servers"):
        results.extend(await check_mcp_servers())

    # 7. Disk space
    with ui.spinner("Checking disk space"):
        results.append(check_disk_space())

    # Print results as table
    ok = warn = fail = skip = 0
    table_rows: list[list[str]] = []
    for r in results:
        icon = {"ok": "[ok]", "warn": "[!]", "fail": "[x]", "skip": "[-]"}[r.status]
        table_rows.append([icon, r.name, r.detail])
        if r.status == "ok":
            ok += 1
        elif r.status == "warn":
            warn += 1
        elif r.status == "fail":
            fail += 1
        else:
            skip += 1

    ui.table(["Status", "Check", "Detail"], table_rows)

    summary = f"{ok} ok, {warn} warnings, {fail} failures, {skip} skipped"
    if fail > 0:
        ui.error(f"Summary: {summary}")
        ui.warning("Run 'breadmind setup' to fix configuration issues.")
    elif warn > 0:
        ui.warning(f"Summary: {summary}")
    else:
        ui.success(f"Summary: {summary}")


def check_config() -> CheckResult:
    """config.yaml 존재 및 유효성."""
    try:
        from breadmind.config import get_default_config_dir, load_config
        config_dir = get_default_config_dir()
        config_path = os.path.join(config_dir, "config.yaml")
        if not os.path.exists(config_path):
            # fallback to local ./config
            if os.path.exists("config/config.yaml"):
                return CheckResult("Config", "ok", "./config/config.yaml")
            return CheckResult("Config", "fail", f"Not found: {config_path}")
        load_config(config_dir)
        return CheckResult("Config", "ok", config_path)
    except Exception as e:
        return CheckResult("Config", "fail", str(e))


def check_python() -> CheckResult:
    """Python 버전 확인."""
    import sys
    ver = sys.version_info
    major, minor, micro = ver[0], ver[1], ver[2]
    if ver >= (3, 12):
        return CheckResult("Python", "ok", f"{major}.{minor}.{micro}")
    elif ver >= (3, 10):
        return CheckResult("Python", "warn", f"{major}.{minor} (3.12+ recommended)")
    return CheckResult("Python", "fail", f"{major}.{minor} (3.12+ required)")


def check_dependencies() -> list[CheckResult]:
    """핵심 의존성 설치 여부."""
    results = []
    deps = {
        "anthropic": ("Anthropic SDK", False),
        "asyncpg": ("PostgreSQL driver", True),
        "aiohttp": ("HTTP client", False),
        "fastapi": ("Web framework", False),
        "uvicorn": ("ASGI server", False),
    }
    for pkg, (name, optional) in deps.items():
        try:
            __import__(pkg)
            results.append(CheckResult(name, "ok", "installed"))
        except ImportError:
            if optional:
                results.append(CheckResult(name, "skip", "not installed (optional)"))
            else:
                results.append(CheckResult(name, "fail", "not installed"))
    return results


async def check_providers() -> list[CheckResult]:
    """등록된 LLM provider의 API key 확인."""
    results = []
    try:
        from breadmind.llm.factory import get_provider_options
        for opt in get_provider_options():
            env_key = opt.get("env_key")
            name = opt["name"]
            if not env_key:
                results.append(CheckResult(f"LLM: {name}", "ok", "no key needed"))
                continue
            key = os.environ.get(env_key, "")
            if not key:
                # .env 파일에서도 확인
                try:
                    from breadmind.config import get_default_config_dir
                    env_path = os.path.join(get_default_config_dir(), ".env")
                    if os.path.exists(env_path):
                        for line in Path(env_path).read_text().splitlines():
                            if line.startswith(f"{env_key}="):
                                key = line.split("=", 1)[1].strip()
                                break
                except Exception:
                    pass
            if key:
                masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
                results.append(CheckResult(f"LLM: {name}", "ok", f"key={masked}"))
            else:
                results.append(CheckResult(f"LLM: {name}", "skip", f"{env_key} not set"))
    except Exception as e:
        results.append(CheckResult("LLM Providers", "fail", str(e)))
    return results


async def check_database() -> CheckResult:
    """PostgreSQL 연결 확인."""
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        try:
            from breadmind.config import get_default_config_dir
            env_path = os.path.join(get_default_config_dir(), ".env")
            if os.path.exists(env_path):
                for line in Path(env_path).read_text().splitlines():
                    if line.startswith("DATABASE_URL="):
                        dsn = line.split("=", 1)[1].strip()
        except Exception:
            pass
    if not dsn:
        return CheckResult("PostgreSQL", "skip", "DATABASE_URL not set (file-based storage)")
    try:
        import asyncpg
        conn = await asyncpg.connect(dsn)
        version = await conn.fetchval("SELECT version()")
        await conn.close()
        short_ver = version.split(",")[0] if version else "connected"
        return CheckResult("PostgreSQL", "ok", short_ver)
    except ImportError:
        return CheckResult("PostgreSQL", "warn", "asyncpg not installed")
    except Exception as e:
        return CheckResult("PostgreSQL", "fail", str(e)[:80])


async def check_mcp_servers() -> list[CheckResult]:
    """설정된 MCP 서버 확인."""
    results = []
    try:
        from breadmind.config import get_default_config_dir, load_config
        config_dir = get_default_config_dir()
        if not os.path.exists(os.path.join(config_dir, "config.yaml")):
            if os.path.exists("config/config.yaml"):
                config_dir = "config"
            else:
                return [CheckResult("MCP Servers", "skip", "no config")]
        config = load_config(config_dir)
        servers = config.mcp.servers
        if not servers:
            return [CheckResult("MCP Servers", "skip", "none configured")]
        for name in servers:
            results.append(CheckResult(f"MCP: {name}", "ok", "configured"))
    except Exception as e:
        results.append(CheckResult("MCP Servers", "warn", str(e)[:60]))
    return results


def check_disk_space() -> CheckResult:
    """디스크 공간 확인."""
    import shutil
    try:
        usage = shutil.disk_usage(".")
        free_gb = usage.free / (1024**3)
        if free_gb > 5:
            return CheckResult("Disk Space", "ok", f"{free_gb:.1f} GB free")
        elif free_gb > 1:
            return CheckResult("Disk Space", "warn", f"{free_gb:.1f} GB free (low)")
        return CheckResult("Disk Space", "fail", f"{free_gb:.1f} GB free (critical)")
    except Exception:
        return CheckResult("Disk Space", "skip", "unable to check")
