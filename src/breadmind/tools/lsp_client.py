"""LSP client for code navigation tools (go-to-definition, find-references, hover)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class LSPLocation:
    """A location in source code."""
    file_path: str
    line: int  # 0-indexed
    character: int  # 0-indexed
    end_line: int | None = None
    end_character: int | None = None
    preview: str = ""  # line content for context


@dataclass
class LSPHoverInfo:
    """Hover information for a symbol."""
    content: str  # Markdown content
    language: str = ""
    range_start: tuple[int, int] | None = None  # (line, char)
    range_end: tuple[int, int] | None = None


@dataclass
class LSPSymbol:
    """A symbol in the document."""
    name: str
    kind: str  # "function", "class", "variable", "method", etc.
    location: LSPLocation
    container: str = ""  # parent symbol name


class LSPClient:
    """Lightweight LSP client for code navigation.

    Communicates with a language server via stdio JSON-RPC.
    Falls back to regex-based search when no LSP server is available.
    """

    def __init__(self, language: str = "python",
                 server_command: str | None = None,
                 workspace_path: str | None = None) -> None:
        self._language = language
        self._server_command = server_command or self._default_server(language)
        self._workspace = workspace_path or os.getcwd()
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._responses: dict[int, asyncio.Future] = {}
        self._initialized = False
        self._reader_task: asyncio.Task | None = None

    def _default_server(self, language: str) -> str:
        """Return default LSP server command for a language."""
        servers = {
            "python": "pyright-langserver --stdio",
            "typescript": "typescript-language-server --stdio",
            "javascript": "typescript-language-server --stdio",
            "go": "gopls",
            "rust": "rust-analyzer",
            "java": "jdtls",
        }
        return servers.get(language, "")

    async def start(self) -> bool:
        """Start the LSP server process."""
        if not self._server_command:
            logger.warning("No LSP server configured for %s", self._language)
            return False

        try:
            parts = self._server_command.split()
            self._process = await asyncio.create_subprocess_exec(
                *parts,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._reader_task = asyncio.create_task(self._read_responses())
            await self._initialize()
            self._initialized = True
            return True
        except (FileNotFoundError, OSError) as e:
            logger.warning("Failed to start LSP server: %s", e)
            return False

    async def stop(self) -> None:
        """Stop the LSP server."""
        if self._process and self._process.returncode is None:
            await self._send_request("shutdown", {})
            self._send_notification("exit", {})
            self._process.terminate()
            if self._reader_task:
                self._reader_task.cancel()
        self._initialized = False

    async def goto_definition(self, file_path: str, line: int, character: int) -> list[LSPLocation]:
        """Go to definition of symbol at position."""
        if not self._initialized:
            return await self._fallback_definition(file_path, line, character)

        uri = self._path_to_uri(file_path)
        result = await self._send_request("textDocument/definition", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        })
        return self._parse_locations(result)

    async def find_references(self, file_path: str, line: int, character: int,
                               include_declaration: bool = True) -> list[LSPLocation]:
        """Find all references to symbol at position."""
        if not self._initialized:
            return await self._fallback_references(file_path, line, character)

        uri = self._path_to_uri(file_path)
        result = await self._send_request("textDocument/references", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
            "context": {"includeDeclaration": include_declaration},
        })
        return self._parse_locations(result)

    async def hover(self, file_path: str, line: int, character: int) -> LSPHoverInfo | None:
        """Get hover information for symbol at position."""
        if not self._initialized:
            return None

        uri = self._path_to_uri(file_path)
        result = await self._send_request("textDocument/hover", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        })

        if result is None:
            return None

        contents = result.get("contents", {})
        if isinstance(contents, str):
            return LSPHoverInfo(content=contents)
        if isinstance(contents, dict):
            return LSPHoverInfo(
                content=contents.get("value", ""),
                language=contents.get("language", ""),
            )
        if isinstance(contents, list):
            parts = []
            for c in contents:
                if isinstance(c, str):
                    parts.append(c)
                elif isinstance(c, dict):
                    parts.append(c.get("value", ""))
            return LSPHoverInfo(content="\n".join(parts))
        return None

    async def document_symbols(self, file_path: str) -> list[LSPSymbol]:
        """Get all symbols in a document."""
        if not self._initialized:
            return await self._fallback_symbols(file_path)

        uri = self._path_to_uri(file_path)
        result = await self._send_request("textDocument/documentSymbol", {
            "textDocument": {"uri": uri},
        })
        return self._parse_symbols(result or [], file_path)

    # -- Fallback methods (regex-based) --

    async def _fallback_definition(self, file_path: str, line: int, character: int) -> list[LSPLocation]:
        """Fallback: try to find definition using simple text search."""
        import re
        # Read the file to get the symbol at position
        try:
            with open(file_path) as f:
                lines = f.readlines()
            if line >= len(lines):
                return []

            line_text = lines[line]
            # Extract word at character position
            word = self._extract_word(line_text, character)
            if not word:
                return []

            # Search for definition patterns
            patterns = [
                rf"^\s*def\s+{re.escape(word)}\s*\(",       # function
                rf"^\s*class\s+{re.escape(word)}\s*[:(]",    # class
                rf"^\s*{re.escape(word)}\s*=",                # variable
                rf"^\s*async\s+def\s+{re.escape(word)}\s*\(", # async function
            ]

            results = []
            for i, l in enumerate(lines):
                for pattern in patterns:
                    if re.search(pattern, l):
                        results.append(LSPLocation(
                            file_path=file_path, line=i, character=0,
                            preview=l.rstrip(),
                        ))
            return results
        except (IOError, IndexError):
            return []

    async def _fallback_references(self, file_path: str, line: int, character: int) -> list[LSPLocation]:
        """Fallback: simple grep for symbol."""
        try:
            with open(file_path) as f:
                lines = f.readlines()
            if line >= len(lines):
                return []

            word = self._extract_word(lines[line], character)
            if not word:
                return []

            results = []
            for i, l in enumerate(lines):
                if word in l:
                    col = l.index(word)
                    results.append(LSPLocation(
                        file_path=file_path, line=i, character=col,
                        preview=l.rstrip(),
                    ))
            return results
        except (IOError, IndexError):
            return []

    async def _fallback_symbols(self, file_path: str) -> list[LSPSymbol]:
        """Fallback: extract symbols using regex."""
        import re
        try:
            with open(file_path) as f:
                lines = f.readlines()

            symbols = []
            for i, line in enumerate(lines):
                # Functions
                m = re.match(r"^\s*(async\s+)?def\s+(\w+)", line)
                if m:
                    symbols.append(LSPSymbol(
                        name=m.group(2), kind="function",
                        location=LSPLocation(file_path=file_path, line=i, character=0, preview=line.rstrip()),
                    ))
                # Classes
                m = re.match(r"^\s*class\s+(\w+)", line)
                if m:
                    symbols.append(LSPSymbol(
                        name=m.group(1), kind="class",
                        location=LSPLocation(file_path=file_path, line=i, character=0, preview=line.rstrip()),
                    ))
            return symbols
        except IOError:
            return []

    # -- LSP Protocol helpers --

    async def _initialize(self) -> None:
        """Send LSP initialize request."""
        await self._send_request("initialize", {
            "processId": os.getpid(),
            "rootUri": self._path_to_uri(self._workspace),
            "capabilities": {},
        })
        self._send_notification("initialized", {})

    async def _send_request(self, method: str, params: dict, timeout: float = 10.0) -> Any:
        """Send a JSON-RPC request and wait for response."""
        if self._process is None or self._process.stdin is None:
            return None

        self._request_id += 1
        req_id = self._request_id

        msg = json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        })

        content = f"Content-Length: {len(msg)}\r\n\r\n{msg}"

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._responses[req_id] = future

        self._process.stdin.write(content.encode())
        await self._process.stdin.drain()

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self._responses.pop(req_id, None)
            return None

    def _send_notification(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if self._process is None or self._process.stdin is None:
            return

        msg = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        })
        content = f"Content-Length: {len(msg)}\r\n\r\n{msg}"
        self._process.stdin.write(content.encode())

    async def _read_responses(self) -> None:
        """Background task: read LSP responses from stdout."""
        if self._process is None or self._process.stdout is None:
            return

        while True:
            try:
                # Read Content-Length header
                header = await self._process.stdout.readline()
                if not header:
                    break

                header_str = header.decode().strip()
                if not header_str.startswith("Content-Length:"):
                    continue

                content_length = int(header_str.split(":")[1].strip())

                # Read empty line
                await self._process.stdout.readline()

                # Read content
                data = await self._process.stdout.readexactly(content_length)
                msg = json.loads(data)

                req_id = msg.get("id")
                if req_id is not None and req_id in self._responses:
                    self._responses[req_id].set_result(msg.get("result"))
                    del self._responses[req_id]
            except (asyncio.CancelledError, asyncio.IncompleteReadError):
                break
            except Exception as e:
                logger.debug("LSP read error: %s", e)

    def _path_to_uri(self, path: str) -> str:
        """Convert file path to URI."""
        path = os.path.abspath(path).replace("\\", "/")
        if not path.startswith("/"):
            path = "/" + path
        return f"file://{path}"

    def _parse_locations(self, result: Any) -> list[LSPLocation]:
        """Parse LSP location response."""
        if result is None:
            return []
        if isinstance(result, dict):
            result = [result]

        locations = []
        for loc in result:
            uri = loc.get("uri", "")
            range_ = loc.get("range", {})
            start = range_.get("start", {})
            end = range_.get("end", {})

            file_path = self._uri_to_path(uri)
            locations.append(LSPLocation(
                file_path=file_path,
                line=start.get("line", 0),
                character=start.get("character", 0),
                end_line=end.get("line"),
                end_character=end.get("character"),
            ))
        return locations

    def _parse_symbols(self, result: list, file_path: str) -> list[LSPSymbol]:
        """Parse LSP document symbols."""
        symbol_kinds = {
            1: "file", 2: "module", 3: "namespace", 5: "class",
            6: "method", 7: "property", 8: "field", 9: "constructor",
            10: "enum", 12: "function", 13: "variable", 14: "constant",
        }
        symbols = []
        for item in result:
            kind_num = item.get("kind", 0)
            location = item.get("location", {})
            range_ = location.get("range", item.get("range", {}))
            start = range_.get("start", {})

            symbols.append(LSPSymbol(
                name=item.get("name", ""),
                kind=symbol_kinds.get(kind_num, "unknown"),
                location=LSPLocation(
                    file_path=file_path,
                    line=start.get("line", 0),
                    character=start.get("character", 0),
                ),
                container=item.get("containerName", ""),
            ))
        return symbols

    def _uri_to_path(self, uri: str) -> str:
        """Convert URI to file path."""
        if uri.startswith("file://"):
            path = uri[7:]
            # Windows: file:///C:/path
            if len(path) > 2 and path[0] == "/" and path[2] == ":":
                path = path[1:]
            return path.replace("/", os.sep)
        return uri

    @staticmethod
    def _extract_word(line: str, character: int) -> str:
        """Extract the word at a given character position."""
        if character >= len(line):
            return ""

        # Find word boundaries
        start = character
        while start > 0 and (line[start - 1].isalnum() or line[start - 1] == "_"):
            start -= 1

        end = character
        while end < len(line) and (line[end].isalnum() or line[end] == "_"):
            end += 1

        return line[start:end]
