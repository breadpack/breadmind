import asyncio
from pathlib import Path
from breadmind.tools.registry import tool


@tool(description="Execute a shell command locally or via SSH. Use host='localhost' for local commands.")
async def shell_exec(command: str, host: str = "localhost", timeout: int = 30) -> str:
    if host == "localhost":
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(f"Command timed out after {timeout}s: {command}")
        output = stdout.decode("utf-8", errors="replace")
        errors = stderr.decode("utf-8", errors="replace")
        result = output
        if errors:
            result += f"\nSTDERR: {errors}"
        if proc.returncode != 0:
            result += f"\nExit code: {proc.returncode}"
        return result.strip()
    else:
        try:
            import asyncssh
        except ImportError:
            return "Error: asyncssh not installed. Install with: pip install asyncssh"
        try:
            async with asyncssh.connect(host) as conn:
                result = await asyncio.wait_for(conn.run(command), timeout=timeout)
                output = result.stdout or ""
                if result.stderr:
                    output += f"\nSTDERR: {result.stderr}"
                return output.strip()
        except Exception as e:
            return f"SSH error: {e}"


@tool(description="Search the web for information using DuckDuckGo")
async def web_search(query: str, limit: int = 5) -> str:
    results = await _duckduckgo_search(query, limit)
    if not results:
        return "No results found."
    lines = []
    for r in results:
        lines.append(f"**{r.get('title', 'No title')}**")
        lines.append(f"  URL: {r.get('href', '')}")
        lines.append(f"  {r.get('body', '')}")
        lines.append("")
    return "\n".join(lines).strip()


async def _duckduckgo_search(query: str, limit: int) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=limit))
    except ImportError:
        return [{"title": "Error", "href": "", "body": "duckduckgo-search not installed"}]
    except Exception as e:
        return [{"title": "Error", "href": "", "body": str(e)}]


@tool(description="Read content from a file")
async def file_read(path: str, encoding: str = "utf-8") -> str:
    try:
        p = Path(path)
        if not p.exists():
            return f"Error: File not found: {path}"
        return p.read_text(encoding=encoding)
    except Exception as e:
        return f"Error reading file: {e}"


@tool(description="Write content to a file")
async def file_write(path: str, content: str, encoding: str = "utf-8") -> str:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        return f"Written {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error writing file: {e}"
