"""Tests for startup file loader."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from breadmind.cli.file_loader import (
    FileTooLargeError,
    FileResource,
    StartupFileLoader,
    TooManyFilesError,
)


async def test_parse_spec_plain_path():
    loader = StartupFileLoader()
    source, path = loader.parse_spec("src/main.py")
    assert source == "local"
    assert path == "src/main.py"


async def test_parse_spec_alias():
    loader = StartupFileLoader()
    source, path = loader.parse_spec("myalias:doc.txt")
    assert source == "alias"
    assert path == "doc.txt"


async def test_parse_spec_windows_drive():
    """Windows drive letters like C:\\ should be treated as local paths."""
    loader = StartupFileLoader()
    source, path = loader.parse_spec("C:\\Users\\test.py")
    assert source == "local"
    assert path == "C:\\Users\\test.py"


async def test_load_local_file():
    loader = StartupFileLoader()
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write("hello world")
        f.flush()
        path = f.name

    try:
        resource = loader.load_local(path)
        assert isinstance(resource, FileResource)
        assert resource.content == "hello world"
        assert resource.source == "local"
        assert resource.size > 0
        assert resource.name.endswith(".txt")
    finally:
        Path(path).unlink(missing_ok=True)


async def test_load_local_file_not_found():
    loader = StartupFileLoader()
    with pytest.raises(FileNotFoundError):
        loader.load_local("/nonexistent/file.txt")


async def test_load_local_file_too_large():
    loader = StartupFileLoader(max_file_size=5)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write("this content is longer than 5 bytes")
        f.flush()
        path = f.name

    try:
        with pytest.raises(FileTooLargeError):
            loader.load_local(path)
    finally:
        Path(path).unlink(missing_ok=True)


async def test_load_multiple_files():
    loader = StartupFileLoader()
    paths = []
    try:
        for i in range(3):
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as f:
                f.write(f"content {i}")
                f.flush()
                paths.append(f.name)

        resources = loader.load(paths)
        assert len(resources) == 3
        assert loader.total_size > 0
    finally:
        for p in paths:
            Path(p).unlink(missing_ok=True)


async def test_too_many_files():
    loader = StartupFileLoader(max_files=2)
    with pytest.raises(TooManyFilesError):
        loader.load(["a.py", "b.py", "c.py"])


async def test_build_context_messages():
    loader = StartupFileLoader()
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write("print('hello')")
        f.flush()
        path = f.name

    try:
        loader.load([path])
        messages = loader.build_context_messages()
        assert len(messages) == 1
        assert messages[0]["role"] == "system"
        assert "print('hello')" in messages[0]["content"]
    finally:
        Path(path).unlink(missing_ok=True)


async def test_resources_returns_copy():
    loader = StartupFileLoader()
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write("data")
        f.flush()
        path = f.name

    try:
        loader.load([path])
        res = loader.resources
        res.clear()
        assert len(loader.resources) == 1
    finally:
        Path(path).unlink(missing_ok=True)
