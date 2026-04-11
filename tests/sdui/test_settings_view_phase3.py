# tests/sdui/test_settings_view_phase3.py
"""Phase 3 SDUI settings view tests.

Covers the Memory and Advanced tabs.
"""
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


# ---------------------------------------------------------------------------
# Tab structure
# ---------------------------------------------------------------------------

async def test_seven_tabs_correct_order(test_db):
    """All 7 tab labels are present and in the correct order."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    tabs_comps = _walk(spec.root, lambda c: c.type == "tabs")
    assert len(tabs_comps) == 1
    labels = [ch.props.get("label", "") for ch in tabs_comps[0].children]
    assert labels == [
        "빠른 시작",
        "에이전트 동작",
        "통합",
        "안전 & 권한",
        "모니터링",
        "메모리",
        "고급",
    ]


# ---------------------------------------------------------------------------
# Memory tab
# ---------------------------------------------------------------------------

async def test_memory_tab_has_memory_gc_form(test_db):
    """Memory tab contains a form with key='memory_gc_config'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    forms = _walk(spec.root, lambda c: c.type == "form")
    gc_forms = [f for f in forms if (f.props.get("action") or {}).get("key") == "memory_gc_config"]
    assert len(gc_forms) == 1
    action = gc_forms[0].props["action"]
    assert action["kind"] == "settings_write"
    assert gc_forms[0].props.get("submit_label")


async def test_memory_tab_gc_form_has_five_fields(test_db):
    """Memory GC form has all 5 required fields."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    forms = _walk(spec.root, lambda c: c.type == "form")
    gc_form = next(f for f in forms if (f.props.get("action") or {}).get("key") == "memory_gc_config")
    fields = _walk(gc_form, lambda c: c.type in ("field", "select"))
    field_names = [f.props.get("name") for f in fields]
    assert "interval_seconds" in field_names
    assert "decay_threshold" in field_names
    assert "max_cached_notes" in field_names
    assert "kg_max_age_days" in field_names
    assert "env_refresh_interval" in field_names
    assert len(field_names) == 5


async def test_memory_tab_gc_form_uses_defaults_when_no_store(test_db):
    """Memory GC form falls back to schema defaults when no store is provided."""
    spec = await settings_view.build(test_db)
    forms = _walk(spec.root, lambda c: c.type == "form")
    gc_form = next(f for f in forms if (f.props.get("action") or {}).get("key") == "memory_gc_config")
    fields = _walk(gc_form, lambda c: c.type in ("field", "select"))
    by_name = {f.props.get("name"): f.props.get("value") for f in fields}
    assert by_name["interval_seconds"] == "3600"
    assert by_name["decay_threshold"] == "0.1"
    assert by_name["max_cached_notes"] == "500"
    assert by_name["kg_max_age_days"] == "90"
    assert by_name["env_refresh_interval"] == "6"


async def test_memory_tab_gc_form_uses_stored_values(test_db):
    """Memory GC form uses existing values from settings_store."""
    store = FakeStore({
        "memory_gc_config": {
            "interval_seconds": 7200,
            "decay_threshold": 0.25,
            "max_cached_notes": 1000,
            "kg_max_age_days": 30,
            "env_refresh_interval": 60,
        }
    })
    spec = await settings_view.build(test_db, settings_store=store)
    forms = _walk(spec.root, lambda c: c.type == "form")
    gc_form = next(f for f in forms if (f.props.get("action") or {}).get("key") == "memory_gc_config")
    fields = _walk(gc_form, lambda c: c.type in ("field", "select"))
    by_name = {f.props.get("name"): f.props.get("value") for f in fields}
    assert by_name["interval_seconds"] == "7200"
    assert by_name["decay_threshold"] == "0.25"
    assert by_name["max_cached_notes"] == "1000"
    assert by_name["kg_max_age_days"] == "30"
    assert by_name["env_refresh_interval"] == "60"


async def test_memory_tab_partial_stored_values_use_defaults_for_missing(test_db):
    """Memory GC form uses defaults for fields not present in store."""
    store = FakeStore({"memory_gc_config": {"interval_seconds": 7200}})
    spec = await settings_view.build(test_db, settings_store=store)
    forms = _walk(spec.root, lambda c: c.type == "form")
    gc_form = next(f for f in forms if (f.props.get("action") or {}).get("key") == "memory_gc_config")
    fields = _walk(gc_form, lambda c: c.type in ("field", "select"))
    by_name = {f.props.get("name"): f.props.get("value") for f in fields}
    assert by_name["interval_seconds"] == "7200"
    # Missing fields fall back to defaults
    assert by_name["decay_threshold"] == "0.1"
    assert by_name["max_cached_notes"] == "500"


# ---------------------------------------------------------------------------
# Advanced tab - forms present
# ---------------------------------------------------------------------------

async def test_advanced_tab_has_system_timeouts_form(test_db):
    """Advanced tab contains a form with key='system_timeouts'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    forms = _walk(spec.root, lambda c: c.type == "form")
    st_forms = [f for f in forms if (f.props.get("action") or {}).get("key") == "system_timeouts"]
    assert len(st_forms) == 1
    assert st_forms[0].props.get("submit_label")


async def test_advanced_tab_has_retry_config_form(test_db):
    """Advanced tab contains a form with key='retry_config'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    forms = _walk(spec.root, lambda c: c.type == "form")
    rc_forms = [f for f in forms if (f.props.get("action") or {}).get("key") == "retry_config"]
    assert len(rc_forms) == 1
    assert rc_forms[0].props.get("submit_label")


async def test_advanced_tab_has_limits_config_form(test_db):
    """Advanced tab contains a form with key='limits_config'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    forms = _walk(spec.root, lambda c: c.type == "form")
    lc_forms = [f for f in forms if (f.props.get("action") or {}).get("key") == "limits_config"]
    assert len(lc_forms) == 1
    assert lc_forms[0].props.get("submit_label")


async def test_advanced_tab_has_polling_config_form(test_db):
    """Advanced tab contains a form with key='polling_config'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    forms = _walk(spec.root, lambda c: c.type == "form")
    pc_forms = [f for f in forms if (f.props.get("action") or {}).get("key") == "polling_config"]
    assert len(pc_forms) == 1
    assert pc_forms[0].props.get("submit_label")


async def test_advanced_tab_has_agent_timeouts_form(test_db):
    """Advanced tab contains a form with key='agent_timeouts'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    forms = _walk(spec.root, lambda c: c.type == "form")
    at_forms = [f for f in forms if (f.props.get("action") or {}).get("key") == "agent_timeouts"]
    assert len(at_forms) == 1
    assert at_forms[0].props.get("submit_label")


async def test_advanced_tab_has_logging_config_form(test_db):
    """Advanced tab contains a form with key='logging_config'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    forms = _walk(spec.root, lambda c: c.type == "form")
    log_forms = [f for f in forms if (f.props.get("action") or {}).get("key") == "logging_config"]
    assert len(log_forms) == 1
    assert log_forms[0].props.get("submit_label")


# ---------------------------------------------------------------------------
# Advanced tab - field counts
# ---------------------------------------------------------------------------

async def test_system_timeouts_form_has_seven_fields(test_db):
    """system_timeouts form has all 7 required fields."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    forms = _walk(spec.root, lambda c: c.type == "form")
    form = next(f for f in forms if (f.props.get("action") or {}).get("key") == "system_timeouts")
    fields = _walk(form, lambda c: c.type in ("field", "select"))
    field_names = [f.props.get("name") for f in fields]
    for name in ("tool_call", "llm_api", "ssh_command", "health_check", "pypi_check", "http_default", "skill_discovery"):
        assert name in field_names, f"missing field: {name}"
    assert len(field_names) == 7


async def test_retry_config_form_has_six_fields(test_db):
    """retry_config form has all 6 required fields."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    forms = _walk(spec.root, lambda c: c.type == "form")
    form = next(f for f in forms if (f.props.get("action") or {}).get("key") == "retry_config")
    fields = _walk(form, lambda c: c.type in ("field", "select"))
    field_names = [f.props.get("name") for f in fields]
    for name in ("max_retries", "llm_max_retries", "gateway_max_retries", "base_backoff", "max_backoff", "health_check_interval"):
        assert name in field_names, f"missing field: {name}"
    assert len(field_names) == 6


async def test_limits_config_form_has_nine_fields(test_db):
    """limits_config form has all 9 required fields (8 int + 1 float)."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    forms = _walk(spec.root, lambda c: c.type == "form")
    form = next(f for f in forms if (f.props.get("action") or {}).get("key") == "limits_config")
    fields = _walk(form, lambda c: c.type in ("field", "select"))
    field_names = [f.props.get("name") for f in fields]
    for name in (
        "max_tools", "max_context_tokens", "max_per_domain_skills", "audit_log_recent",
        "embedding_cache_size", "top_roles_limit", "smart_retriever_token_budget",
        "smart_retriever_limit", "low_performance_threshold",
    ):
        assert name in field_names, f"missing field: {name}"
    assert len(field_names) == 9


async def test_polling_config_form_has_five_fields(test_db):
    """polling_config form has all 5 required fields."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    forms = _walk(spec.root, lambda c: c.type == "form")
    form = next(f for f in forms if (f.props.get("action") or {}).get("key") == "polling_config")
    fields = _walk(form, lambda c: c.type in ("field", "select"))
    field_names = [f.props.get("name") for f in fields]
    for name in ("signal_interval", "gmail_interval", "update_check_interval", "data_flush_interval", "auto_cleanup_interval"):
        assert name in field_names, f"missing field: {name}"
    assert len(field_names) == 5


async def test_agent_timeouts_form_has_three_fields(test_db):
    """agent_timeouts form has all 3 required fields."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    forms = _walk(spec.root, lambda c: c.type == "form")
    form = next(f for f in forms if (f.props.get("action") or {}).get("key") == "agent_timeouts")
    fields = _walk(form, lambda c: c.type in ("field", "select"))
    field_names = [f.props.get("name") for f in fields]
    for name in ("tool_timeout", "chat_timeout", "max_turns"):
        assert name in field_names, f"missing field: {name}"
    assert len(field_names) == 3


# ---------------------------------------------------------------------------
# Logging config selects
# ---------------------------------------------------------------------------

async def test_logging_form_level_select_has_five_options(test_db):
    """logging_config form has a select with name='level' and 5 options."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    forms = _walk(spec.root, lambda c: c.type == "form")
    log_form = next(f for f in forms if (f.props.get("action") or {}).get("key") == "logging_config")
    selects = _walk(log_form, lambda c: c.type == "select")
    level_sel = next((s for s in selects if s.props.get("name") == "level"), None)
    assert level_sel is not None
    options = level_sel.props.get("options", [])
    option_values = [o["value"] for o in options]
    assert set(option_values) == {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    assert len(options) == 5


async def test_logging_form_format_select_has_two_options(test_db):
    """logging_config form has a select with name='format' and 2 options."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    forms = _walk(spec.root, lambda c: c.type == "form")
    log_form = next(f for f in forms if (f.props.get("action") or {}).get("key") == "logging_config")
    selects = _walk(log_form, lambda c: c.type == "select")
    format_sel = next((s for s in selects if s.props.get("name") == "format"), None)
    assert format_sel is not None
    options = format_sel.props.get("options", [])
    option_values = [o["value"] for o in options]
    assert set(option_values) == {"json", "text"}
    assert len(options) == 2


async def test_logging_form_uses_stored_values(test_db):
    """logging_config form uses existing values from settings_store."""
    store = FakeStore({"logging_config": {"level": "DEBUG", "format": "json"}})
    spec = await settings_view.build(test_db, settings_store=store)
    forms = _walk(spec.root, lambda c: c.type == "form")
    log_form = next(f for f in forms if (f.props.get("action") or {}).get("key") == "logging_config")
    selects = _walk(log_form, lambda c: c.type == "select")
    by_name = {s.props.get("name"): s.props.get("value") for s in selects}
    assert by_name["level"] == "DEBUG"
    assert by_name["format"] == "json"


# ---------------------------------------------------------------------------
# Vault card
# ---------------------------------------------------------------------------

async def test_advanced_tab_has_vault_card_heading(test_db):
    """Advanced tab contains a card with heading '자격증명 금고'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    headings = _walk(spec.root, lambda c: c.type == "heading")
    vault_headings = [h for h in headings if h.props.get("value") == "자격증명 금고"]
    assert len(vault_headings) >= 1


async def test_vault_card_renders_without_list_method(test_db):
    """Vault card renders cleanly even when store has no list_settings_by_prefix."""
    store = FakeStore()  # No list_settings_by_prefix method
    spec = await settings_view.build(test_db, settings_store=store)
    assert spec.root.type == "page"
    headings = _walk(spec.root, lambda c: c.type == "heading")
    vault_headings = [h for h in headings if h.props.get("value") == "자격증명 금고"]
    assert len(vault_headings) >= 1


async def test_vault_card_renders_with_db_having_list_method(test_db):
    """Vault card renders when db has list_settings_by_prefix returning vault keys."""

    class FakeStoreWithList:
        def __init__(self):
            self.data = {}

        async def get_setting(self, key):
            return self.data.get(key)

        async def list_settings_by_prefix(self, prefix):
            return ["vault:MY_API_KEY", "vault:OTHER_KEY"]

    spec = await settings_view.build(FakeStoreWithList(), settings_store=FakeStoreWithList())
    assert spec.root.type == "page"
    headings = _walk(spec.root, lambda c: c.type == "heading")
    vault_headings = [h for h in headings if h.props.get("value") == "자격증명 금고"]
    assert len(vault_headings) >= 1


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------

async def test_view_renders_with_no_store_phase3(test_db):
    """View renders cleanly when settings_store is None (Phase 3 tabs included)."""
    spec = await settings_view.build(test_db)
    assert spec.root.type == "page"
    tabs_comps = _walk(spec.root, lambda c: c.type == "tabs")
    assert len(tabs_comps) == 1
    assert len(tabs_comps[0].children) == 7


async def test_view_renders_with_full_phase3_store(test_db):
    """View renders cleanly with all Phase 3 store values populated."""
    store = FakeStore({
        "memory_gc_config": {
            "interval_seconds": 1800,
            "decay_threshold": 0.2,
            "max_cached_notes": 200,
            "kg_max_age_days": 60,
            "env_refresh_interval": 12,
        },
        "system_timeouts": {
            "tool_call": 30, "llm_api": 60, "ssh_command": 120,
            "health_check": 10, "pypi_check": 15, "http_default": 20, "skill_discovery": 45,
        },
        "retry_config": {
            "max_retries": 3, "llm_max_retries": 5, "gateway_max_retries": 2,
            "base_backoff": 5, "max_backoff": 60, "health_check_interval": 30,
        },
        "limits_config": {
            "max_tools": 50, "max_context_tokens": 100000, "max_per_domain_skills": 10,
            "audit_log_recent": 500, "embedding_cache_size": 1000, "top_roles_limit": 20,
            "smart_retriever_token_budget": 5000, "smart_retriever_limit": 10,
            "low_performance_threshold": 0.8,
        },
        "polling_config": {
            "signal_interval": 60, "gmail_interval": 300, "update_check_interval": 86400,
            "data_flush_interval": 30, "auto_cleanup_interval": 3600,
        },
        "agent_timeouts": {"tool_timeout": 60, "chat_timeout": 300, "max_turns": 20},
        "logging_config": {"level": "INFO", "format": "text"},
    })
    spec = await settings_view.build(test_db, settings_store=store)
    assert spec.root.type == "page"


async def test_advanced_tab_stored_values_reflected(test_db):
    """Advanced tab reflects stored values for system_timeouts."""
    store = FakeStore({"system_timeouts": {"tool_call": 99, "llm_api": 200}})
    spec = await settings_view.build(test_db, settings_store=store)
    forms = _walk(spec.root, lambda c: c.type == "form")
    form = next(f for f in forms if (f.props.get("action") or {}).get("key") == "system_timeouts")
    fields = _walk(form, lambda c: c.type in ("field", "select"))
    by_name = {f.props.get("name"): f.props.get("value") for f in fields}
    assert by_name["tool_call"] == "99"
    assert by_name["llm_api"] == "200"
