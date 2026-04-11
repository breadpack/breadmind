from breadmind.sdui.spec import UISpec, Component
from breadmind.sdui.patches import diff_specs, apply_patch


def test_diff_empty():
    spec = UISpec(1, Component("page", "p", {}, []))
    patch = diff_specs(spec, spec)
    assert patch == []


def test_diff_adds_child():
    old = UISpec(1, Component("page", "p", {}, []))
    new = UISpec(1, Component("page", "p", {}, [
        Component("text", "t", {"value": "hi"}, []),
    ]))
    patch = diff_specs(old, new)
    assert len(patch) >= 1
    result = apply_patch(old.to_dict(), patch)
    assert result == new.to_dict()


def test_diff_replaces_prop():
    old = UISpec(1, Component("page", "p", {"title": "Old"}, []))
    new = UISpec(1, Component("page", "p", {"title": "New"}, []))
    patch = diff_specs(old, new)
    result = apply_patch(old.to_dict(), patch)
    assert result["root"]["props"]["title"] == "New"


def test_diff_removes_child():
    old = UISpec(1, Component("page", "p", {}, [
        Component("text", "t1", {"value": "a"}, []),
        Component("text", "t2", {"value": "b"}, []),
    ]))
    new = UISpec(1, Component("page", "p", {}, [
        Component("text", "t1", {"value": "a"}, []),
    ]))
    patch = diff_specs(old, new)
    result = apply_patch(old.to_dict(), patch)
    assert len(result["root"]["children"]) == 1
