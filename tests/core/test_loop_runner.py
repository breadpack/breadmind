"""Tests for in-session recurring prompt execution (LoopRunner)."""
from __future__ import annotations
import asyncio

from breadmind.core.loop_runner import LoopRunner, LoopJob


async def _echo_handler(prompt: str) -> str:
    return f"echo: {prompt}"


async def test_start_loop():
    runner = LoopRunner()
    job = runner.start_loop("check status", "5m", _echo_handler)
    assert job.id == "loop_1"
    assert job.prompt == "check status"
    assert job.interval_seconds == 300
    assert job.running is True
    runner.stop_all()


async def test_stop_loop():
    runner = LoopRunner()
    job = runner.start_loop("test", "1s", _echo_handler)
    assert runner.stop_loop(job.id) is True
    assert job.running is False
    assert runner.stop_loop("nonexistent") is False


async def test_stop_all():
    runner = LoopRunner()
    runner.start_loop("a", "1s", _echo_handler)
    runner.start_loop("b", "1s", _echo_handler)
    count = runner.stop_all()
    assert count == 2


async def test_list_loops():
    runner = LoopRunner()
    runner.start_loop("check", "10m", _echo_handler)
    loops = runner.list_loops()
    assert len(loops) == 1
    assert loops[0]["id"] == "loop_1"
    assert loops[0]["prompt"] == "check"
    assert loops[0]["interval"] == 600
    runner.stop_all()


async def test_parse_interval_minutes():
    assert LoopRunner._parse_interval("5m") == 300


async def test_parse_interval_seconds():
    assert LoopRunner._parse_interval("30s") == 30


async def test_parse_interval_default():
    assert LoopRunner._parse_interval("invalid") == 600
