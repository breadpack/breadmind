import asyncio
import pytest
from breadmind.coding.executors.local import LocalExecutor


@pytest.mark.asyncio
async def test_run_phase_async_returns_process():
    ex = LocalExecutor()
    # Fake adapter with a simple echo command
    class EchoAdapter:
        def build_phase_command(self, phase):
            return ["python", "-c", "print('hi'); print('bye')"]

    proc = await ex.run_phase_async(
        phase={"step": 1, "title": "t"}, adapter=EchoAdapter(),
    )
    await proc.wait()
    assert proc.returncode == 0


@pytest.mark.asyncio
async def test_cancel_sends_sigterm_then_sigkill():
    ex = LocalExecutor()
    class SleepAdapter:
        def build_phase_command(self, phase):
            return ["python", "-c", "import time; time.sleep(30)"]

    proc = await ex.run_phase_async(
        phase={"step": 1, "title": "t"}, adapter=SleepAdapter(),
    )
    await asyncio.sleep(0.1)
    await ex.cancel(proc, grace_seconds=0.5)
    rc = await proc.wait()
    assert rc != 0  # killed
