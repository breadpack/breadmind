"""Tests for structured output / JSON schema validation."""
from __future__ import annotations

import json

from breadmind.core.structured_output import SchemaConstraint, StructuredOutputManager


async def test_inactive_by_default():
    mgr = StructuredOutputManager()
    assert mgr.active is False
    assert mgr.constraint is None


async def test_set_and_clear_schema():
    mgr = StructuredOutputManager()
    mgr.set_schema({"type": "object"})
    assert mgr.active is True
    mgr.clear()
    assert mgr.active is False


async def test_build_instruction_empty():
    mgr = StructuredOutputManager()
    assert mgr.build_instruction() == ""


async def test_build_instruction_with_schema():
    mgr = StructuredOutputManager()
    mgr.set_schema({"type": "object", "properties": {"name": {"type": "string"}}})
    instr = mgr.build_instruction()
    assert "IMPORTANT" in instr
    assert '"type": "object"' in instr
    assert "ONLY the JSON object" in instr


async def test_extract_json_direct():
    mgr = StructuredOutputManager()
    result = mgr.extract_json('{"key": "value"}')
    assert result is not None
    assert json.loads(result) == {"key": "value"}


async def test_extract_json_from_code_block():
    mgr = StructuredOutputManager()
    text = 'Here is the result:\n```json\n{"count": 42}\n```\nDone.'
    result = mgr.extract_json(text)
    assert result is not None
    assert json.loads(result) == {"count": 42}


async def test_extract_json_from_plain_code_block():
    mgr = StructuredOutputManager()
    text = '```\n[1, 2, 3]\n```'
    result = mgr.extract_json(text)
    assert result is not None
    assert json.loads(result) == [1, 2, 3]


async def test_extract_json_no_json():
    mgr = StructuredOutputManager()
    assert mgr.extract_json("no json here at all") is None


async def test_validate_no_constraint():
    mgr = StructuredOutputManager()
    ok, data, err = mgr.validate("anything")
    assert ok is True
    assert data is None


async def test_validate_valid_object():
    schema = {
        "type": "object",
        "required": ["name", "age"],
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
    }
    mgr = StructuredOutputManager(SchemaConstraint(schema=schema))
    ok, data, err = mgr.validate('{"name": "Alice", "age": 30}')
    assert ok is True
    assert data == {"name": "Alice", "age": 30}
    assert err == ""


async def test_validate_missing_required():
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }
    mgr = StructuredOutputManager(SchemaConstraint(schema=schema))
    ok, data, err = mgr.validate("{}")
    assert ok is False
    assert "required field missing" in err


async def test_validate_wrong_type():
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    mgr = StructuredOutputManager(SchemaConstraint(schema=schema))
    ok, data, err = mgr.validate('{"x": "notint"}')
    assert ok is False
    assert "expected type" in err


async def test_validate_enum():
    schema = {"type": "string", "enum": ["a", "b", "c"]}
    mgr = StructuredOutputManager(SchemaConstraint(schema=schema))
    ok, data, err = mgr.validate('"d"')
    assert ok is False
    assert "not in enum" in err


async def test_validate_array_items():
    schema = {"type": "array", "items": {"type": "integer"}}
    mgr = StructuredOutputManager(SchemaConstraint(schema=schema))
    ok, data, err = mgr.validate("[1, 2, 3]")
    assert ok is True
    assert data == [1, 2, 3]

    ok2, _, err2 = mgr.validate('[1, "two", 3]')
    assert ok2 is False
    assert "expected type" in err2


async def test_validate_not_json():
    schema = {"type": "object"}
    mgr = StructuredOutputManager(SchemaConstraint(schema=schema))
    ok, data, err = mgr.validate("this is not json")
    assert ok is False
    assert "No valid JSON" in err


async def test_boolean_not_integer():
    """Booleans must not pass as integers."""
    schema = {"type": "object", "properties": {"flag": {"type": "integer"}}}
    mgr = StructuredOutputManager(SchemaConstraint(schema=schema))
    ok, data, err = mgr.validate('{"flag": true}')
    assert ok is False
