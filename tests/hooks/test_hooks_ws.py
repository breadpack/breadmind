import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from breadmind.hooks.trace import HookTraceEntry, get_trace_buffer
from breadmind.web.routes.hooks import router as hooks_router


@pytest.fixture
def ws_app():
    app = FastAPI()
    app.include_router(hooks_router)
    return app


def test_ws_trace_stream_receives_new_entries(ws_app):
    client = TestClient(ws_app)
    buf = get_trace_buffer()

    with client.websocket_connect("/ws/hooks/traces") as ws:
        buf.record(HookTraceEntry(
            timestamp=1.0, hook_id="ws-test", event="pre_tool_use",
            decision="proceed", duration_ms=5.0,
        ))
        msg = ws.receive_json()
        assert msg["hook_id"] == "ws-test"
        assert msg["event"] == "pre_tool_use"
