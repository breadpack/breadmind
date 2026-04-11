"""Built-in agent tools for reading and modifying BreadMind runtime settings.

Each tool is a thin wrapper around :class:`breadmind.settings.service.SettingsService`.
Values that may be scalars, lists, or dicts travel as JSON strings so a single
``str``-typed parameter is enough for the LLM to express any shape.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from breadmind.settings.service import SetResult
from breadmind.tools.registry import tool


def _parse_json(raw: str, field: str) -> tuple[Any, str | None]:
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as exc:
        return None, f"ERROR: invalid JSON for {field} - {exc.msg}"


def _format(result: SetResult) -> str:
    return result.summary()


def build_settings_tools(
    *,
    service: Any,
    actor: str = "agent:core",
) -> dict[str, Callable[..., Any]]:
    """Create tool callables bound to the given service and actor.

    Returns a name->callable map. The caller is expected to register each entry
    with a :class:`breadmind.tools.registry.ToolRegistry`.
    """

    @tool(
        description=(
            "Read a BreadMind runtime setting. Returns a JSON string with the "
            "key and its current value. Credential keys (apikey:*, vault:*) "
            "always return masked placeholders."
        ),
        read_only=True,
        concurrency_safe=True,
    )
    async def breadmind_get_setting(key: str) -> str:
        value = await service.get(key)
        return json.dumps({"key": key, "value": value}, ensure_ascii=False)

    @tool(
        description=(
            "Search the settings catalogue. Returns matching entries as JSON: "
            "[{label, key, tab, field_id}, ...]. Use to discover the correct "
            "settings key before calling set/append."
        ),
        read_only=True,
        concurrency_safe=True,
    )
    async def breadmind_list_settings(query: str = "", tab: str = "") -> str:
        from breadmind.sdui.settings_index import search_settings
        entries = search_settings(query or "")
        if tab:
            entries = [e for e in entries if e.get("tab") == tab]
        return json.dumps(entries, ensure_ascii=False)

    @tool(
        description=(
            "Overwrite a BreadMind runtime setting. `value` is a JSON-encoded "
            "string: '\"friendly\"', '{\"default_provider\":\"gemini\"}', "
            "'[1,2,3]', etc. Triggers hot reload when the setting's owner "
            "subscribes. Returns 'OK ...' on success or 'ERROR: ...' otherwise."
        ),
    )
    async def breadmind_set_setting(key: str, value: str) -> str:
        parsed, err = _parse_json(value, "value")
        if err:
            return err
        result = await service.set(key, parsed, actor=actor)
        return _format(result)

    @tool(
        description=(
            "Append an item to a list-valued setting (e.g. mcp_servers, "
            "skill_markets, safety_blacklist). `item` is a JSON object or "
            "scalar. Returns 'OK ...' or 'ERROR: ...'."
        ),
    )
    async def breadmind_append_setting(key: str, item: str) -> str:
        parsed, err = _parse_json(item, "item")
        if err:
            return err
        result = await service.append(key, parsed, actor=actor)
        return _format(result)

    @tool(
        description=(
            "Update a single item inside a list-valued setting by matching "
            "one field. `patch` is a JSON object merged into the matched item. "
            "Example: update_setting_item('mcp_servers', 'name', 'github', "
            "'{\"enabled\":false}')."
        ),
    )
    async def breadmind_update_setting_item(
        key: str, match_field: str, match_value: str, patch: str
    ) -> str:
        parsed_patch, err = _parse_json(patch, "patch")
        if err:
            return err
        result = await service.update_item(
            key,
            match_field=match_field,
            match_value=match_value,
            patch=parsed_patch,
            actor=actor,
        )
        return _format(result)

    @tool(
        description=(
            "Delete a single item from a list-valued setting by matching one "
            "field. Example: delete_setting_item('mcp_servers','name','github')."
        ),
    )
    async def breadmind_delete_setting_item(
        key: str, match_field: str, match_value: str
    ) -> str:
        result = await service.delete_item(
            key,
            match_field=match_field,
            match_value=match_value,
            actor=actor,
        )
        return _format(result)

    @tool(
        description=(
            "Store a secret credential (apikey:anthropic, vault:ssh:host, ...). "
            "Plaintext is written to the encrypted CredentialVault and never "
            "logged. Writes that target sensitive keys may require user "
            "approval - in that case the return starts with 'PENDING:'."
        ),
    )
    async def breadmind_set_credential(
        key: str, value: str, description: str = ""
    ) -> str:
        result = await service.set_credential(
            key, value, actor=actor, description=description
        )
        return _format(result)

    @tool(
        description="Delete a stored credential by its full key.",
    )
    async def breadmind_delete_credential(key: str) -> str:
        result = await service.delete_credential(key, actor=actor)
        return _format(result)

    return {
        "breadmind_get_setting": breadmind_get_setting,
        "breadmind_list_settings": breadmind_list_settings,
        "breadmind_set_setting": breadmind_set_setting,
        "breadmind_append_setting": breadmind_append_setting,
        "breadmind_update_setting_item": breadmind_update_setting_item,
        "breadmind_delete_setting_item": breadmind_delete_setting_item,
        "breadmind_set_credential": breadmind_set_credential,
        "breadmind_delete_credential": breadmind_delete_credential,
    }
