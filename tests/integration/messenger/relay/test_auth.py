# tests/integration/messenger/relay/test_auth.py
import pytest
import websockets

pytestmark = pytest.mark.relay_integration


@pytest.mark.asyncio
async def test_ws_rejects_invalid_token(compose_stack):
    _, ws_base = compose_stack
    with pytest.raises(websockets.exceptions.InvalidStatus) as ei:
        async with websockets.connect(f"{ws_base}/ws?token=bogus"):
            pass
    assert ei.value.response.status_code == 401


@pytest.mark.asyncio
async def test_ws_accepts_valid_token(compose_stack, valid_user_token):
    _, ws_base = compose_stack
    async with websockets.connect(f"{ws_base}/ws?token={valid_user_token}") as ws:
        await ws.send('{"type":"ping"}')
        msg = await ws.recv()
        assert '"pong"' in msg
