"""Tests for the Aider-inspired repository map."""

from __future__ import annotations

from pathlib import Path

from breadmind.tools.repo_map import FileMap, RepoMapper, SymbolInfo


def _create_py_file(root: Path, rel_path: str, content: str) -> Path:
    """Helper to create a Python file in the test tree."""
    p = root / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_extract_class_and_function(tmp_path: Path):
    _create_py_file(
        tmp_path,
        "mod.py",
        "class Foo:\n    def bar(self, x: int) -> str:\n        pass\n\ndef baz():\n    pass\n",
    )
    mapper = RepoMapper(root=tmp_path)
    maps = mapper.build_map()
    assert len(maps) == 1
    fm = maps[0]
    names = [s.name for s in fm.symbols]
    assert "Foo" in names
    assert "bar" in names
    assert "baz" in names


def test_extract_async_function(tmp_path: Path):
    _create_py_file(
        tmp_path,
        "async_mod.py",
        "async def fetch(url: str) -> bytes:\n    pass\n",
    )
    mapper = RepoMapper(root=tmp_path)
    maps = mapper.build_map()
    assert len(maps) == 1
    sigs = [s.signature for s in maps[0].symbols]
    assert any("async def fetch" in s for s in sigs)


def test_file_map_summary():
    fm = FileMap(
        path="src/foo.py",
        symbols=[
            SymbolInfo(name="A", kind="class", signature="class A", line=1),
            SymbolInfo(name="b", kind="function", signature="def b()", line=5),
            SymbolInfo(
                name="c", kind="method", signature="def c(self)", line=3, parent="A"
            ),
        ],
    )
    s = fm.summary()
    assert "1 class" in s
    assert "2 functions" in s
    assert "src/foo.py" in s


def test_render_tree_respects_max_tokens(tmp_path: Path):
    # Create many files
    for i in range(50):
        _create_py_file(
            tmp_path, f"pkg/mod_{i}.py", f"def func_{i}():\n    pass\n"
        )
    mapper = RepoMapper(root=tmp_path)
    tree = mapper.render_tree(max_tokens=200)  # very small budget
    assert "truncated" in tree


def test_excludes_pycache(tmp_path: Path):
    _create_py_file(tmp_path, "__pycache__/cached.py", "x = 1\n")
    _create_py_file(tmp_path, "real.py", "y = 2\n")
    mapper = RepoMapper(root=tmp_path)
    maps = mapper.build_map()
    paths = [fm.path for fm in maps]
    assert not any("__pycache__" in p for p in paths)
    assert any("real.py" in p for p in paths)


def test_render_file():
    fm = FileMap(
        path="foo.py",
        symbols=[
            SymbolInfo(name="Cls", kind="class", signature="class Cls", line=1),
            SymbolInfo(
                name="method",
                kind="method",
                signature="def method(self)",
                line=2,
                parent="Cls",
            ),
        ],
    )
    mapper = RepoMapper(root=Path("."))
    rendered = mapper.render_file(fm)
    assert "## foo.py" in rendered
    assert "class Cls" in rendered
    assert "  def method(self)" in rendered


def test_imports_extracted(tmp_path: Path):
    _create_py_file(
        tmp_path,
        "imp.py",
        "import os\nfrom pathlib import Path\n\ndef f():\n    pass\n",
    )
    mapper = RepoMapper(root=tmp_path)
    maps = mapper.build_map()
    assert len(maps) == 1
    assert "os" in maps[0].imports
    assert "pathlib" in maps[0].imports


def test_syntax_error_file_handled(tmp_path: Path):
    _create_py_file(tmp_path, "bad.py", "def broken(\n")
    _create_py_file(tmp_path, "good.py", "def ok():\n    pass\n")
    mapper = RepoMapper(root=tmp_path)
    maps = mapper.build_map()
    # Should have both files but bad.py has no symbols
    assert len(maps) == 2
    bad = [m for m in maps if "bad.py" in m.path][0]
    assert len(bad.symbols) == 0
