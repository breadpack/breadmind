"""Tests for file_edit tool with uniqueness enforcement."""


from breadmind.tools.file_edit import (
    file_edit,
    file_read_tracked,
    mark_file_read,
    reset_read_tracking,
)


def setup_function():
    """Reset read tracking before each test."""
    reset_read_tracking()


def test_edit_unique_string_succeeds(tmp_path):
    """Editing a unique string should succeed."""
    f = tmp_path / "test.txt"
    f.write_text("hello world\n", encoding="utf-8")
    mark_file_read(str(f))

    result = file_edit(str(f), "hello", "goodbye")
    assert "Successfully edited" in result
    assert "1 replacement(s)" in result
    assert f.read_text(encoding="utf-8") == "goodbye world\n"


def test_edit_non_unique_string_fails(tmp_path):
    """Editing a non-unique string without replace_all should fail."""
    f = tmp_path / "test.txt"
    f.write_text("aaa bbb aaa\n", encoding="utf-8")
    mark_file_read(str(f))

    result = file_edit(str(f), "aaa", "ccc")
    assert "found 2 times" in result
    # File should be unchanged
    assert f.read_text(encoding="utf-8") == "aaa bbb aaa\n"


def test_edit_replace_all(tmp_path):
    """replace_all=True should replace all occurrences."""
    f = tmp_path / "test.txt"
    f.write_text("aaa bbb aaa\n", encoding="utf-8")
    mark_file_read(str(f))

    result = file_edit(str(f), "aaa", "ccc", replace_all=True)
    assert "2 replacement(s)" in result
    assert f.read_text(encoding="utf-8") == "ccc bbb ccc\n"


def test_edit_not_found(tmp_path):
    """Editing a string not in the file should fail."""
    f = tmp_path / "test.txt"
    f.write_text("hello world\n", encoding="utf-8")
    mark_file_read(str(f))

    result = file_edit(str(f), "xyz", "abc")
    assert "not found" in result


def test_edit_requires_read_first(tmp_path):
    """Editing without reading first should fail."""
    f = tmp_path / "test.txt"
    f.write_text("hello world\n", encoding="utf-8")

    result = file_edit(str(f), "hello", "goodbye")
    assert "requires reading the file first" in result
    # File should be unchanged
    assert f.read_text(encoding="utf-8") == "hello world\n"


def test_edit_same_string_error(tmp_path):
    """old_string == new_string should return error."""
    f = tmp_path / "test.txt"
    f.write_text("hello world\n", encoding="utf-8")
    mark_file_read(str(f))

    result = file_edit(str(f), "hello", "hello")
    assert "identical" in result


def test_read_tracked_marks_file(tmp_path):
    """file_read_tracked should mark the file so editing works."""
    f = tmp_path / "test.txt"
    f.write_text("line one\nline two\n", encoding="utf-8")

    read_result = file_read_tracked(str(f))
    assert "2 lines total" in read_result
    assert "line one" in read_result

    # Now edit should work without explicit mark_file_read
    edit_result = file_edit(str(f), "line one", "LINE ONE")
    assert "Successfully edited" in edit_result
    assert f.read_text(encoding="utf-8") == "LINE ONE\nline two\n"
