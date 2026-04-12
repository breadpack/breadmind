from breadmind.sdui.views.hooks_view import build_hooks_view


def test_view_is_dict():
    schema = build_hooks_view()
    assert isinstance(schema, dict)


def test_view_references_three_tabs_by_label():
    schema = build_hooks_view()
    s = str(schema)
    # The three tab labels must appear somewhere in the schema
    assert "Hooks" in s
    assert "Traces" in s
    assert "Stats" in s


def test_view_references_api_endpoints():
    schema = build_hooks_view()
    s = str(schema)
    assert "/api/hooks/list" in s
    assert "/api/hooks/stats" in s
    # Either HTTP traces or WS stream (WS is preferred for Phase 3)
    assert "/api/hooks/traces" in s or "/ws/hooks/traces" in s
