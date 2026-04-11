import json

import pytest

from breadmind.settings.service import SetResult
from breadmind.tools.settings_tools import build_settings_tools


class StubService:
    def __init__(self):
        self.calls = []

    def _record(self, name, **kwargs):
        self.calls.append((name, kwargs))

    async def get(self, key):
        self._record("get", key=key)
        return {"default_provider": "claude"}

    async def set(self, key, value, *, actor):
        self._record("set", key=key, value=value, actor=actor)
        return SetResult(ok=True, operation="set", key=key, persisted=True, hot_reloaded=True, audit_id=1)

    async def append(self, key, item, *, actor):
        self._record("append", key=key, item=item, actor=actor)
        return SetResult(ok=True, operation="append", key=key, persisted=True, hot_reloaded=True, audit_id=2)

    async def update_item(self, key, *, match_field, match_value, patch, actor):
        self._record("update_item", key=key, match_field=match_field,
                     match_value=match_value, patch=patch, actor=actor)
        return SetResult(ok=True, operation="update_item", key=key, persisted=True, hot_reloaded=True, audit_id=3)

    async def delete_item(self, key, *, match_field, match_value, actor):
        self._record("delete_item", key=key, match_field=match_field,
                     match_value=match_value, actor=actor)
        return SetResult(ok=True, operation="delete_item", key=key, persisted=True, hot_reloaded=True, audit_id=4)

    async def set_credential(self, key, value, *, actor, description=""):
        self._record("set_credential", key=key, value=value,
                     actor=actor, description=description)
        return SetResult(ok=True, operation="credential_store", key=key, persisted=True, hot_reloaded=True, audit_id=5)

    async def delete_credential(self, key, *, actor):
        self._record("delete_credential", key=key, actor=actor)
        return SetResult(ok=True, operation="credential_delete", key=key, persisted=True, hot_reloaded=True, audit_id=6)


@pytest.fixture
def tools():
    svc = StubService()
    return svc, build_settings_tools(service=svc, actor="agent:core")


async def test_get_setting_returns_json_string(tools):
    svc, t = tools
    result = await t["breadmind_get_setting"](key="llm")
    parsed = json.loads(result)
    assert parsed["key"] == "llm"
    assert parsed["value"] == {"default_provider": "claude"}


async def test_set_setting_parses_json_value(tools):
    svc, t = tools
    result = await t["breadmind_set_setting"](
        key="persona", value='"friendly"'
    )
    assert result.startswith("OK")
    assert svc.calls[-1] == ("set", {"key": "persona", "value": "friendly", "actor": "agent:core"})


async def test_set_setting_accepts_complex_json(tools):
    svc, t = tools
    payload = '{"default_provider":"gemini","default_model":"gemini-2.0-flash"}'
    result = await t["breadmind_set_setting"](key="llm", value=payload)
    assert result.startswith("OK")
    assert svc.calls[-1][1]["value"] == {
        "default_provider": "gemini",
        "default_model": "gemini-2.0-flash",
    }


async def test_set_setting_invalid_json_returns_error(tools):
    svc, t = tools
    result = await t["breadmind_set_setting"](key="persona", value="not-json")
    assert result.startswith("ERROR")
    assert "json" in result.lower()
    assert svc.calls == []


async def test_append_setting_parses_item_json(tools):
    svc, t = tools
    item_json = '{"name":"github","command":"npx","args":["-y","gh"],"env":{},"enabled":true}'
    result = await t["breadmind_append_setting"](key="mcp_servers", item=item_json)
    assert result.startswith("OK")
    assert svc.calls[-1][1]["item"]["name"] == "github"


async def test_update_setting_item(tools):
    svc, t = tools
    result = await t["breadmind_update_setting_item"](
        key="mcp_servers",
        match_field="name",
        match_value="github",
        patch='{"enabled":false}',
    )
    assert result.startswith("OK")
    call = svc.calls[-1][1]
    assert call["patch"] == {"enabled": False}


async def test_delete_setting_item(tools):
    svc, t = tools
    result = await t["breadmind_delete_setting_item"](
        key="mcp_servers", match_field="name", match_value="github"
    )
    assert result.startswith("OK")


async def test_set_credential_passes_through(tools):
    svc, t = tools
    result = await t["breadmind_set_credential"](
        key="apikey:anthropic", value="sk-ant-xxx", description="primary"
    )
    assert result.startswith("OK")
    assert svc.calls[-1][1]["value"] == "sk-ant-xxx"
    assert svc.calls[-1][1]["description"] == "primary"


async def test_delete_credential(tools):
    svc, t = tools
    result = await t["breadmind_delete_credential"](key="apikey:anthropic")
    assert result.startswith("OK")


async def test_list_settings_uses_catalogue(tools):
    svc, t = tools
    result = await t["breadmind_list_settings"](query="llm")
    parsed = json.loads(result)
    assert isinstance(parsed, list)
    assert any(entry["key"] == "llm" for entry in parsed)
