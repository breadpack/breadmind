"""Tests for the browser_view SDUI view."""
from __future__ import annotations

from breadmind.sdui.views import browser_view


def _all_types(c) -> set[str]:
    out = {c.type}
    for ch in c.children:
        out |= _all_types(ch)
    return out


def _find_by_text(c, needle: str) -> bool:
    if c.type in ("text", "heading") and needle in str(c.props.get("value", "")):
        return True
    return any(_find_by_text(ch, needle) for ch in c.children)


def _find_by_type(c, type_name: str) -> list:
    found = []
    if c.type == type_name:
        found.append(c)
    for ch in c.children:
        found.extend(_find_by_type(ch, type_name))
    return found


async def test_browser_view_renders_without_engine(test_db):
    spec = await browser_view.build(test_db)
    assert spec.root.type == "page"
    types = _all_types(spec.root)
    assert "tabs" in types
    assert _find_by_text(spec.root, "브라우저 자동화")
    assert _find_by_text(spec.root, "라이브 뷰는 곧 지원 예정입니다.")


async def test_browser_view_with_fake_engine(test_db):
    class FakeEngine:
        def list_sessions(self):
            return [
                {
                    "id": "s1",
                    "name": "test session",
                    "mode": "playwright",
                    "tab_count": 1,
                    "persistent": False,
                }
            ]

        def list_macros(self):
            return [
                {
                    "id": "m1",
                    "name": "google-search",
                    "steps": [{}, {}],
                    "execution_count": 5,
                }
            ]

    spec = await browser_view.build(test_db, browser_engine=FakeEngine())
    assert _find_by_text(spec.root, "test session")
    assert _find_by_text(spec.root, "google-search")
    types = _all_types(spec.root)
    assert "button" in types
    # There must be a close button for the session and run button for the macro.
    buttons = _find_by_type(spec.root, "button")
    labels = {b.props.get("label") for b in buttons}
    assert "닫기" in labels
    assert "실행" in labels
    assert "+ 새 세션" in labels


async def test_browser_view_with_broken_engine(test_db):
    class Broken:
        def list_sessions(self):
            raise RuntimeError("nope")

        def list_macros(self):
            raise RuntimeError("nope")

    spec = await browser_view.build(test_db, browser_engine=Broken())
    assert spec.root.type == "page"
    # Degrades to empty-state text for both sections.
    assert _find_by_text(spec.root, "활성 세션 없음")
    assert _find_by_text(spec.root, "저장된 매크로 없음")


async def test_browser_view_spec_validates(test_db):
    from breadmind.sdui.schema import validate_spec

    spec = await browser_view.build(test_db)
    validate_spec(spec)


async def test_browser_view_intervention_actions(test_db):
    class FakeEngine:
        def list_sessions(self):
            return [{"id": "abc", "name": "s", "mode": "playwright", "tab_count": 0, "persistent": True}]

        def list_macros(self):
            return [{"id": "xyz", "name": "macro", "steps": [], "execution_count": 0}]

    spec = await browser_view.build(test_db, browser_engine=FakeEngine())
    buttons = _find_by_type(spec.root, "button")
    actions = [b.props.get("action") for b in buttons if b.props.get("action")]
    ops = {a.get("operation") for a in actions}
    assert "new_session" in ops
    assert "close_session" in ops
    assert "run_macro" in ops
    close_action = next(a for a in actions if a.get("operation") == "close_session")
    assert close_action.get("session_id") == "abc"
    run_action = next(a for a in actions if a.get("operation") == "run_macro")
    assert run_action.get("macro_id") == "xyz"
