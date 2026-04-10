import pytest

from breadmind.sdui.spec import UISpec, Component
from breadmind.sdui.schema import validate_spec, SpecValidationError


def test_component_to_dict():
    c = Component(type="text", id="t1", props={"value": "hi"}, children=[])
    d = c.to_dict()
    assert d == {"type": "text", "id": "t1", "props": {"value": "hi"}, "children": []}


def test_component_from_dict_roundtrip():
    d = {"type": "text", "id": "t1", "props": {"value": "hi"}, "children": []}
    c = Component.from_dict(d)
    assert c.type == "text"
    assert c.id == "t1"
    assert c.props == {"value": "hi"}
    assert c.to_dict() == d


def test_uispec_to_dict():
    spec = UISpec(
        schema_version=1,
        root=Component(type="page", id="p", props={}, children=[
            Component(type="text", id="t", props={"value": "hello"}, children=[]),
        ]),
    )
    d = spec.to_dict()
    assert d["schema_version"] == 1
    assert d["root"]["type"] == "page"
    assert d["root"]["children"][0]["type"] == "text"


def test_uispec_from_dict_roundtrip():
    d = {
        "schema_version": 1,
        "root": {"type": "page", "id": "p", "props": {}, "children": []},
        "bindings": {},
    }
    spec = UISpec.from_dict(d)
    assert spec.schema_version == 1
    assert spec.root.type == "page"


def test_validate_spec_accepts_known_components():
    spec = UISpec(
        schema_version=1,
        root=Component(type="page", id="p", props={}, children=[
            Component(type="button", id="b", props={"label": "Click"}, children=[]),
        ]),
    )
    validate_spec(spec)  # should not raise


def test_validate_spec_rejects_unknown_component():
    spec = UISpec(
        schema_version=1,
        root=Component(type="page", id="p", props={}, children=[
            Component(type="nonexistent", id="x", props={}, children=[]),
        ]),
    )
    with pytest.raises(SpecValidationError):
        validate_spec(spec)


def test_validate_spec_rejects_nonstring_props():
    spec = UISpec(
        schema_version=1,
        root=Component(type="page", id="p", props="not a dict", children=[]),
    )
    with pytest.raises(SpecValidationError):
        validate_spec(spec)
