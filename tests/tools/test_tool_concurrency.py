"""Tests for tool concurrency safety classification."""

from breadmind.tools.registry import ToolMetadata, ToolRegistry, tool


def test_classify_batch_separates_readonly():
    reg = ToolRegistry()

    @tool("Read-only tool", read_only=True, concurrency_safe=True)
    def reader(path: str):
        return path

    @tool("Writer tool", read_only=False, concurrency_safe=True)
    def writer(path: str, data: str):
        return "ok"

    reg.register(reader)
    reg.register(writer)

    parallel, sequential = reg.classify_batch(["reader", "writer"])
    assert parallel == ["reader"]
    assert sequential == ["writer"]


def test_default_metadata_is_concurrent():
    reg = ToolRegistry()
    meta = reg.get_metadata("nonexistent_tool")
    assert meta.read_only is False
    assert meta.concurrency_safe is True


def test_tool_decorator_with_read_only():
    @tool("A read-only tool", read_only=True)
    def my_reader(name: str):
        return name

    assert hasattr(my_reader, "_tool_metadata")
    assert my_reader._tool_metadata.read_only is True
    assert my_reader._tool_metadata.concurrency_safe is True


def test_register_stores_metadata():
    reg = ToolRegistry()

    @tool("Test tool", read_only=True, concurrency_safe=False)
    def special_tool(x: str):
        return x

    reg.register(special_tool)
    meta = reg.get_metadata("special_tool")
    assert meta.read_only is True
    assert meta.concurrency_safe is False


def test_get_metadata_default():
    reg = ToolRegistry()

    @tool("Plain tool")
    def plain(x: str):
        return x

    reg.register(plain)
    meta = reg.get_metadata("plain")
    assert meta.read_only is False
    assert meta.concurrency_safe is True
