import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_capture_stdout_redacts_and_appends():
    from breadmind.coding.job_executor import _capture_stream_to_tracker

    class FakeStream:
        def __init__(self, lines: list[bytes]):
            self._lines = list(lines)
        async def readline(self):
            if not self._lines:
                return b""
            return self._lines.pop(0)

    stream = FakeStream([
        b"normal line\n",
        b"secret xoxb-1234567890-1234567890-AAAAAA\n",
        b"another ok\n",
        b"",  # EOF
    ])
    tracker = MagicMock()
    tracker.append_log = AsyncMock()

    await _capture_stream_to_tracker(stream, tracker, job_id="j1", step=1)

    calls = [c.args for c in tracker.append_log.await_args_list]
    texts = [c[2] for c in calls]
    assert texts[0] == "normal line"
    assert "xoxb-1234567890" not in texts[1]  # raw token body gone
    assert "REDACTED" in texts[1]
    assert texts[2] == "another ok"
    assert len(texts) == 3
