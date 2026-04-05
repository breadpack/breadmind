"""Aider-inspired repository map for codebase structure overview."""

from __future__ import annotations

import ast
import fnmatch
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SymbolInfo:
    """A symbol extracted from source code."""

    name: str
    kind: str  # "class", "function", "method", "variable"
    signature: str  # e.g., "def foo(x: int, y: str) -> bool"
    line: int
    parent: str | None = None  # Parent class name for methods


@dataclass
class FileMap:
    """Symbols and metadata for a single file."""

    path: str
    symbols: list[SymbolInfo] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """One-line summary: path (N classes, M functions)."""
        classes = sum(1 for s in self.symbols if s.kind == "class")
        functions = sum(1 for s in self.symbols if s.kind in ("function", "method"))
        parts = []
        if classes:
            parts.append(f"{classes} class{'es' if classes != 1 else ''}")
        if functions:
            parts.append(f"{functions} function{'s' if functions != 1 else ''}")
        detail = ", ".join(parts) if parts else "empty"
        return f"{self.path} ({detail})"


class RepoMapper:
    """Generates a structural overview of the codebase.

    Inspired by Aider's repo-map: provides function signatures and
    file structure for whole-codebase context without full file content.
    Keeps token count low while giving the LLM an architectural overview.
    """

    def __init__(
        self,
        root: Path,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        max_depth: int = 10,
    ):
        self._root = root
        self._includes = include_patterns or ["**/*.py"]
        self._excludes = exclude_patterns or [
            "**/__pycache__/**",
            "**/node_modules/**",
            "**/.git/**",
            "**/venv/**",
            "**/.venv/**",
        ]
        self._max_depth = max_depth

    def build_map(self) -> list[FileMap]:
        """Scan the codebase and build file maps with symbols."""
        file_maps: list[FileMap] = []
        for pattern in self._includes:
            for path in sorted(self._root.glob(pattern)):
                if not path.is_file():
                    continue
                if self._is_excluded(path):
                    continue
                # Check depth
                try:
                    rel = path.relative_to(self._root)
                except ValueError:
                    continue
                if len(rel.parts) - 1 > self._max_depth:
                    continue

                fm = self._extract_symbols(path)
                file_maps.append(fm)
        return file_maps

    def render_tree(
        self, file_maps: list[FileMap] | None = None, max_tokens: int = 8000
    ) -> str:
        """Render the repo map as a compact text tree.

        Truncates to stay within approximate token budget
        (estimated as chars / 4).
        """
        if file_maps is None:
            file_maps = self.build_map()

        lines: list[str] = []
        max_chars = max_tokens * 4  # rough token estimate

        for fm in file_maps:
            rendered = self.render_file(fm)
            lines.append(rendered)
            total = sum(len(l) for l in lines)
            if total > max_chars:
                lines.append("... (truncated)")
                break

        return "\n".join(lines)

    def render_file(self, file_map: FileMap) -> str:
        """Render a single file's symbols."""
        parts: list[str] = [f"## {file_map.path}"]
        for sym in file_map.symbols:
            indent = "  " if sym.parent else ""
            parts.append(f"{indent}{sym.signature}")
        return "\n".join(parts)

    def _extract_symbols(self, path: Path) -> FileMap:
        """Extract symbols from a Python file using AST."""
        try:
            rel_path = str(path.relative_to(self._root))
        except ValueError:
            rel_path = str(path)

        fm = FileMap(path=rel_path)

        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (SyntaxError, UnicodeDecodeError, OSError):
            return fm

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    fm.imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                fm.imports.append(module)
            elif isinstance(node, ast.ClassDef):
                sig = f"class {node.name}"
                bases = [ast.unparse(b) for b in node.bases]
                if bases:
                    sig += f"({', '.join(bases)})"
                fm.symbols.append(
                    SymbolInfo(
                        name=node.name,
                        kind="class",
                        signature=sig,
                        line=node.lineno,
                    )
                )
                # Extract methods
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        msig = self._get_function_signature(item)
                        fm.symbols.append(
                            SymbolInfo(
                                name=item.name,
                                kind="method",
                                signature=msig,
                                line=item.lineno,
                                parent=node.name,
                            )
                        )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                sig = self._get_function_signature(node)
                fm.symbols.append(
                    SymbolInfo(
                        name=node.name,
                        kind="function",
                        signature=sig,
                        line=node.lineno,
                    )
                )
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        fm.symbols.append(
                            SymbolInfo(
                                name=target.id,
                                kind="variable",
                                signature=f"{target.id} = ...",
                                line=node.lineno,
                            )
                        )

        return fm

    def _get_function_signature(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> str:
        """Extract function signature string from AST node."""
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        args = ast.unparse(node.args)
        sig = f"{prefix} {node.name}({args})"
        if node.returns:
            sig += f" -> {ast.unparse(node.returns)}"
        return sig

    def _is_excluded(self, path: Path) -> bool:
        """Check if a path matches any exclude pattern."""
        try:
            rel = str(path.relative_to(self._root))
        except ValueError:
            rel = str(path)
        # Normalize to forward slashes for pattern matching
        rel = rel.replace("\\", "/")
        parts = rel.split("/")
        for pattern in self._excludes:
            # Handle ** glob patterns by checking path components
            # e.g., "**/__pycache__/**" should exclude any path containing __pycache__
            clean = pattern.replace("**/", "").replace("/**", "")
            if clean and any(part == clean for part in parts):
                return True
            if fnmatch.fnmatch(rel, pattern):
                return True
        return False
