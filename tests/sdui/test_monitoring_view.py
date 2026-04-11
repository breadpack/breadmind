"""Tests for the monitoring_view SDUI view."""
from __future__ import annotations

from breadmind.sdui.views import monitoring_view


def _find_by_type(component, type_name):
    found = []
    if component.type == type_name:
        found.append(component)
    for child in component.children:
        found.extend(_find_by_type(child, type_name))
    return found


async def test_monitoring_view_renders_with_empty_db(test_db):
    spec = await monitoring_view.build(test_db, severity="all")
    assert spec.root.type == "page"
    tables = _find_by_type(spec.root, "table")
    assert len(tables) == 1
    # Rows must be a list (possibly empty) — never None.
    assert isinstance(tables[0].props["rows"], list)
    # Columns should be defined.
    assert tables[0].props["columns"] == ["시각", "심각도", "소스", "대상", "메시지"]


async def test_monitoring_view_has_filter_buttons(test_db):
    spec = await monitoring_view.build(test_db, severity="warning")
    buttons = _find_by_type(spec.root, "button")
    # Should have 4 filter buttons.
    assert len(buttons) == 4
    labels = {b.props["label"] for b in buttons}
    assert "전체" in labels
    assert "심각" in labels
    assert "경고" in labels
    assert "정보" in labels
    # The 'warning' button should be the primary variant.
    warning_btn = next(b for b in buttons if b.props["label"] == "경고")
    assert warning_btn.props.get("variant") == "primary"
    # Others should not be primary.
    others = [b for b in buttons if b.props["label"] != "경고"]
    assert all(b.props.get("variant") != "primary" for b in others)


async def test_monitoring_view_default_severity_is_all(test_db):
    spec = await monitoring_view.build(test_db)
    buttons = _find_by_type(spec.root, "button")
    all_btn = next(b for b in buttons if b.props["label"] == "전체")
    assert all_btn.props.get("variant") == "primary"


async def test_monitoring_view_filter_buttons_reissue_view_request(test_db):
    spec = await monitoring_view.build(test_db, severity="all")
    buttons = _find_by_type(spec.root, "button")
    for btn in buttons:
        action = btn.props.get("action")
        assert action is not None
        assert action["kind"] == "view_request"
        assert action["view_key"] == "monitoring_view"
        assert "severity" in action["params"]


async def test_monitoring_view_invalid_severity_falls_back_to_all(test_db):
    spec = await monitoring_view.build(test_db, severity="bogus")
    buttons = _find_by_type(spec.root, "button")
    all_btn = next(b for b in buttons if b.props["label"] == "전체")
    assert all_btn.props.get("variant") == "primary"


async def test_monitoring_view_via_projector(test_db):
    from breadmind.sdui.projector import UISpecProjector

    projector = UISpecProjector(db=test_db, bus=None)
    spec = await projector.build_view("monitoring_view", severity="all")
    assert spec.root.type == "page"
    assert spec.root.props.get("title") == "모니터링"


async def test_monitoring_view_spec_validates(test_db):
    from breadmind.sdui.schema import validate_spec

    spec = await monitoring_view.build(test_db, severity="all")
    # Should not raise — all components must be in KNOWN_COMPONENTS.
    validate_spec(spec)
