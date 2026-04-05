"""Tests for tool input schema validation."""

from breadmind.tools.schema_validator import SchemaValidator


def _validator() -> SchemaValidator:
    return SchemaValidator()


def test_valid_input_passes():
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "count": {"type": "integer"},
        },
        "required": ["name"],
    }
    result = _validator().validate({"name": "test", "count": 5}, schema)
    assert result.valid
    assert result.errors == []


def test_missing_required_field():
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    result = _validator().validate({}, schema)
    assert not result.valid
    assert any("name" in e.field for e in result.errors)


def test_wrong_type_detected():
    schema = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
    }
    result = _validator().validate({"count": "not_a_number"}, schema)
    assert not result.valid
    assert result.errors[0].field == "count"
    assert "integer" in result.errors[0].expected_type


def test_enum_validation():
    schema = {
        "type": "object",
        "properties": {
            "color": {"type": "string", "enum": ["red", "green", "blue"]},
        },
    }
    result = _validator().validate({"color": "red"}, schema)
    assert result.valid

    result = _validator().validate({"color": "purple"}, schema)
    assert not result.valid


def test_string_length_constraints():
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 2, "maxLength": 10},
        },
    }
    assert _validator().validate({"name": "ok"}, schema).valid
    assert not _validator().validate({"name": "x"}, schema).valid
    assert not _validator().validate({"name": "x" * 11}, schema).valid


def test_numeric_range_constraints():
    schema = {
        "type": "object",
        "properties": {
            "age": {"type": "integer", "minimum": 0, "maximum": 150},
        },
    }
    assert _validator().validate({"age": 25}, schema).valid
    assert not _validator().validate({"age": -1}, schema).valid
    assert not _validator().validate({"age": 200}, schema).valid


def test_unknown_fields_rejected():
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "additionalProperties": False,
    }
    result = _validator().validate({"name": "ok", "extra": "bad"}, schema)
    assert not result.valid
    assert any("extra" in e.field for e in result.errors)


def test_nested_object_validation():
    schema = {
        "type": "object",
        "properties": {
            "config": {
                "type": "object",
                "properties": {
                    "timeout": {"type": "integer"},
                },
                "required": ["timeout"],
            },
        },
    }
    assert _validator().validate({"config": {"timeout": 30}}, schema).valid

    result = _validator().validate({"config": {}}, schema)
    assert not result.valid
    assert any("config.timeout" in e.field for e in result.errors)


def test_empty_schema_allows_anything():
    schema: dict = {}
    result = _validator().validate({"any": "thing", "goes": 123}, schema)
    assert result.valid
