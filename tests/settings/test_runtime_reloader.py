from breadmind.settings.reload_registry import SettingsReloadRegistry
from breadmind.settings.runtime_config import RuntimeConfigHolder


async def test_runtime_holder_updates_on_each_key():
    holder = RuntimeConfigHolder(initial={
        "retry_config": {"max_attempts": 3},
        "limits_config": {"max_turns": 10},
        "polling_config": {"interval_seconds": 5},
        "agent_timeouts": {"tool_seconds": 30},
        "system_timeouts": {"chat_seconds": 120},
        "logging_config": {"level": "INFO"},
        "memory_gc_config": {"interval_minutes": 60},
    })
    registry = SettingsReloadRegistry()
    holder.register(registry)

    await registry.dispatch(
        key="retry_config", operation="set",
        old={"max_attempts": 3}, new={"max_attempts": 5},
    )
    assert holder.get("retry_config") == {"max_attempts": 5}

    await registry.dispatch(
        key="limits_config", operation="set",
        old={"max_turns": 10}, new={"max_turns": 20},
    )
    assert holder.get("limits_config") == {"max_turns": 20}

    await registry.dispatch(
        key="logging_config", operation="set",
        old={"level": "INFO"}, new={"level": "DEBUG"},
    )
    assert holder.get("logging_config") == {"level": "DEBUG"}


async def test_runtime_holder_logging_config_updates_root_logger():
    import logging

    original_level = logging.getLogger().level
    try:
        holder = RuntimeConfigHolder(initial={"logging_config": {"level": "INFO"}})
        registry = SettingsReloadRegistry()
        holder.register(registry)

        await registry.dispatch(
            key="logging_config", operation="set",
            old={"level": "INFO"}, new={"level": "WARNING"},
        )
        assert logging.getLogger().level == logging.WARNING
    finally:
        logging.getLogger().setLevel(original_level)
