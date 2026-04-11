import logging

from breadmind.plugins.manager import PluginManager


def _make_manager(tmp_path):
    return PluginManager(plugins_dir=tmp_path)


async def test_apply_markets_stores_new_config(tmp_path):
    mgr = _make_manager(tmp_path)
    markets = [
        {"name": "official", "url": "https://plugins.example.com", "enabled": True},
        {"name": "internal", "url": "https://int.example.com", "enabled": False},
    ]
    await mgr.apply_markets(markets)
    assert mgr.get_markets_config() == markets


async def test_apply_markets_logs_restart_hint(tmp_path, caplog):
    mgr = _make_manager(tmp_path)
    with caplog.at_level(logging.INFO, logger="breadmind.plugins.manager"):
        await mgr.apply_markets([{"name": "official", "url": "x", "enabled": True}])
    messages = [rec.message for rec in caplog.records]
    assert any(
        "restart" in m.lower() or "markets updated" in m.lower()
        for m in messages
    )


async def test_apply_markets_empty_list_clears_config(tmp_path):
    mgr = _make_manager(tmp_path)
    await mgr.apply_markets([{"name": "a", "url": "x", "enabled": True}])
    await mgr.apply_markets([])
    assert mgr.get_markets_config() == []
