"""Tests for @-mention file reference parsing."""

from __future__ import annotations

from pathlib import Path

from breadmind.core.mention_parser import FileMention, MentionParser


def test_parse_whole_file(tmp_path: Path):
    parser = MentionParser(project_root=tmp_path)
    mentions = parser.parse("Look at @src/main.py for details")
    assert len(mentions) == 1
    m = mentions[0]
    assert m.raw == "@src/main.py"
    assert m.start_line is None
    assert m.end_line is None


def test_parse_single_line(tmp_path: Path):
    parser = MentionParser(project_root=tmp_path)
    mentions = parser.parse("Check @utils.py:42 please")
    assert len(mentions) == 1
    m = mentions[0]
    assert m.start_line == 42
    assert m.end_line == 42


def test_parse_line_range(tmp_path: Path):
    parser = MentionParser(project_root=tmp_path)
    mentions = parser.parse("See @src/lib.py:10-20")
    assert len(mentions) == 1
    m = mentions[0]
    assert m.start_line == 10
    assert m.end_line == 20


def test_parse_l_prefix_range(tmp_path: Path):
    parser = MentionParser(project_root=tmp_path)
    mentions = parser.parse("@core/app.py:L5-L15 has the bug")
    assert len(mentions) == 1
    m = mentions[0]
    assert m.start_line == 5
    assert m.end_line == 15


def test_parse_multiple_mentions(tmp_path: Path):
    parser = MentionParser(project_root=tmp_path)
    mentions = parser.parse("Compare @a.py:1-5 and @b.py:10-20")
    assert len(mentions) == 2
    assert mentions[0].raw == "@a.py:1-5"
    assert mentions[1].raw == "@b.py:10-20"


def test_resolve_content_whole_file(tmp_path: Path):
    f = tmp_path / "hello.py"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")
    parser = MentionParser(project_root=tmp_path)
    mention = FileMention(raw="@hello.py", file_path="hello.py")
    content = parser.resolve_content(mention)
    assert content == "line1\nline2\nline3\n"


def test_resolve_content_line_range(tmp_path: Path):
    f = tmp_path / "data.py"
    f.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")
    parser = MentionParser(project_root=tmp_path)
    mention = FileMention(
        raw="@data.py:2-4", file_path="data.py", start_line=2, end_line=4
    )
    content = parser.resolve_content(mention)
    assert content == "b\nc\nd\n"


def test_resolve_content_missing_file(tmp_path: Path):
    parser = MentionParser(project_root=tmp_path)
    mention = FileMention(raw="@missing.py", file_path="missing.py")
    assert parser.resolve_content(mention) is None


def test_expand_mentions(tmp_path: Path):
    f = tmp_path / "code.py"
    f.write_text("print('hello')\n", encoding="utf-8")
    parser = MentionParser(project_root=tmp_path)
    cleaned, contexts = parser.expand_mentions("Review @code.py please")
    assert "@code.py" not in cleaned
    assert "Review" in cleaned
    assert len(contexts) == 1
    assert contexts[0]["content"] == "print('hello')\n"


def test_parse_terminal_mention(tmp_path: Path):
    parser = MentionParser(project_root=tmp_path)
    terminals = parser.parse_terminals("See output from @terminal:build")
    assert len(terminals) == 1
    assert terminals[0].name == "build"


def test_resolve_path_is_absolute_when_given_root(tmp_path: Path):
    parser = MentionParser(project_root=tmp_path)
    mentions = parser.parse("@foo.py")
    assert len(mentions) == 1
    assert str(tmp_path) in mentions[0].file_path
