# tests/sdui/test_settings_view_phase1.py
from breadmind.sdui.views import settings_view


def _walk(component, predicate):
    out = []
    if predicate(component):
        out.append(component)
    for ch in component.children:
        out.extend(_walk(ch, predicate))
    return out


class FakeStore:
    def __init__(self, data=None):
        self.data = data or {}

    async def get_setting(self, key):
        return self.data.get(key)


async def test_settings_view_seven_tabs(test_db):
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    tabs_components = _walk(spec.root, lambda c: c.type == "tabs")
    assert len(tabs_components) == 1
    tab_labels = [
        ch.props.get("label", "")
        for ch in tabs_components[0].children
    ]
    assert tab_labels == [
        "빠른 시작",
        "에이전트 동작",
        "통합",
        "안전 & 권한",
        "모니터링",
        "메모리",
        "고급",
    ]


async def test_quick_start_tab_has_llm_form(test_db):
    store = FakeStore({"llm": {"default_provider": "gemini", "default_model": "gemini-2.5-pro"}})
    spec = await settings_view.build(test_db, settings_store=store)
    forms = _walk(spec.root, lambda c: c.type == "form")
    llm_forms = [
        f for f in forms
        if (f.props.get("action") or {}).get("key") == "llm"
    ]
    assert len(llm_forms) == 1
    action = llm_forms[0].props["action"]
    assert action["kind"] == "settings_write"
    fields = _walk(llm_forms[0], lambda c: c.type in ("field", "select"))
    field_names = [f.props.get("name") for f in fields]
    assert "default_provider" in field_names
    assert "default_model" in field_names
    assert "tool_call_max_turns" in field_names


async def test_quick_start_tab_has_apikey_forms(test_db):
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    forms = _walk(spec.root, lambda c: c.type == "form")
    apikey_forms = [
        f for f in forms
        if (f.props.get("action") or {}).get("key", "").startswith("apikey:")
    ]
    keys = sorted((f.props["action"]["key"] for f in apikey_forms))
    assert keys == [
        "apikey:ANTHROPIC_API_KEY",
        "apikey:GEMINI_API_KEY",
        "apikey:OPENAI_API_KEY",
        "apikey:XAI_API_KEY",
    ]


async def test_apikey_form_uses_password_field(test_db):
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    forms = _walk(spec.root, lambda c: c.type == "form")
    gemini = next(
        f for f in forms
        if (f.props.get("action") or {}).get("key") == "apikey:GEMINI_API_KEY"
    )
    fields = _walk(gemini, lambda c: c.type == "field")
    assert any(f.props.get("type") == "password" for f in fields)


async def test_quick_start_masks_existing_apikey(test_db):
    store = FakeStore({"apikey:GEMINI_API_KEY": {"encrypted": "ignored"}})
    # Mask is shown via a kv item rather than prefilled form value
    spec = await settings_view.build(test_db, settings_store=store)
    kvs = _walk(spec.root, lambda c: c.type == "kv")
    # at least one kv must mention GEMINI status
    found = False
    for k in kvs:
        for item in k.props.get("items", []):
            if "GEMINI" in str(item.get("key", "")):
                found = True
                break
    assert found


async def test_persona_tab_has_preset_select(test_db):
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    forms = _walk(spec.root, lambda c: c.type == "form")
    persona = next(
        f for f in forms
        if (f.props.get("action") or {}).get("key") == "persona"
    )
    selects = _walk(persona, lambda c: c.type == "select")
    assert any(s.props.get("name") == "preset" for s in selects)
    preset_select = next(s for s in selects if s.props.get("name") == "preset")
    options = preset_select.props.get("options", [])
    values = {o.get("value") for o in options}
    assert {"professional", "friendly", "concise", "humorous"} <= values


async def test_agent_behavior_tab_has_prompt_forms(test_db):
    store = FakeStore({"custom_prompts": {"main_system_prompt": "You are X"}})
    spec = await settings_view.build(test_db, settings_store=store)
    forms = _walk(spec.root, lambda c: c.type == "form")
    keys = {(f.props.get("action") or {}).get("key") for f in forms}
    assert "custom_prompts" in keys
    assert "custom_instructions" in keys
    assert "embedding_config" in keys


async def test_embedding_form_shows_restart_warning(test_db):
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    texts = _walk(spec.root, lambda c: c.type == "text")
    text_values = [t.props.get("value", "") for t in texts]
    assert any("재시작" in v for v in text_values)


async def test_view_renders_without_store(test_db):
    spec = await settings_view.build(test_db)
    assert spec.root.type == "page"
    forms = _walk(spec.root, lambda c: c.type == "form")
    assert len(forms) >= 4  # quick start + agent behavior have multiple forms
