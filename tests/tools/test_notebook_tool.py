"""Tests for Jupyter notebook tool."""

import json

from breadmind.tools.notebook_tool import notebook_edit, notebook_read


def _make_notebook(cells):
    """Create a minimal notebook dict."""
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": cells,
    }


def _write_notebook(path, cells):
    """Write a notebook file with given cells."""
    nb = _make_notebook(cells)
    path.write_text(json.dumps(nb), encoding="utf-8")
    return nb


def test_read_notebook(tmp_path):
    """Reading a notebook should return all cells."""
    f = tmp_path / "test.ipynb"
    _write_notebook(f, [
        {
            "cell_type": "code",
            "source": ["print('hello')\n"],
            "metadata": {},
            "outputs": [{"text": ["hello\n"]}],
        },
        {
            "cell_type": "markdown",
            "source": ["# Title\n"],
            "metadata": {},
            "outputs": [],
        },
    ])

    result = notebook_read(str(f))
    assert "2 cells" in result
    assert "print('hello')" in result
    assert "[Output] hello" in result
    assert "# Title" in result


def test_read_single_cell(tmp_path):
    """Reading a specific cell by number."""
    f = tmp_path / "test.ipynb"
    _write_notebook(f, [
        {"cell_type": "code", "source": ["x = 1\n"], "metadata": {}, "outputs": []},
        {"cell_type": "code", "source": ["y = 2\n"], "metadata": {}, "outputs": []},
    ])

    result = notebook_read(str(f), cell_number=1)
    assert "Cell 1" in result
    assert "y = 2" in result
    assert "x = 1" not in result


def test_edit_replace_cell(tmp_path):
    """Replacing a cell should update its source and clear outputs."""
    f = tmp_path / "test.ipynb"
    _write_notebook(f, [
        {
            "cell_type": "code",
            "source": ["old code\n"],
            "metadata": {},
            "outputs": [{"text": ["old output\n"]}],
        },
    ])

    result = notebook_edit(str(f), cell_number=0, action="replace", new_source="new code\n")
    assert "replace on cell 0 successful" in result

    with open(str(f), "r", encoding="utf-8") as fh:
        nb = json.load(fh)
    assert nb["cells"][0]["source"] == ["new code\n"]
    assert nb["cells"][0]["outputs"] == []


def test_edit_insert_after(tmp_path):
    """insert_after should add a cell after the specified index."""
    f = tmp_path / "test.ipynb"
    _write_notebook(f, [
        {"cell_type": "code", "source": ["first\n"], "metadata": {}, "outputs": []},
    ])

    notebook_edit(str(f), cell_number=0, action="insert_after", new_source="second\n")

    with open(str(f), "r", encoding="utf-8") as fh:
        nb = json.load(fh)
    assert len(nb["cells"]) == 2
    assert "".join(nb["cells"][1]["source"]) == "second\n"


def test_edit_delete_cell(tmp_path):
    """delete should remove the cell at the specified index."""
    f = tmp_path / "test.ipynb"
    _write_notebook(f, [
        {"cell_type": "code", "source": ["a\n"], "metadata": {}, "outputs": []},
        {"cell_type": "code", "source": ["b\n"], "metadata": {}, "outputs": []},
    ])

    result = notebook_edit(str(f), cell_number=0, action="delete")
    assert "delete on cell 0 successful" in result

    with open(str(f), "r", encoding="utf-8") as fh:
        nb = json.load(fh)
    assert len(nb["cells"]) == 1
    assert "".join(nb["cells"][0]["source"]) == "b\n"


def test_read_nonexistent_cell(tmp_path):
    """Reading a cell beyond the notebook length should error."""
    f = tmp_path / "test.ipynb"
    _write_notebook(f, [
        {"cell_type": "code", "source": ["x\n"], "metadata": {}, "outputs": []},
    ])

    result = notebook_read(str(f), cell_number=5)
    assert "Error" in result
    assert "1 cells" in result
