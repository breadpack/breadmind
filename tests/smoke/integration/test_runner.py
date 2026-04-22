import asyncio
from dataclasses import dataclass, field

from breadmind.smoke.checks.base import CheckOutcome, CheckStatus
from breadmind.smoke.runner import ExitCode, SmokeRunner


@dataclass
class FakeCheck:
    name: str
    status: CheckStatus
    depends_on: list[str] = field(default_factory=list)
    delay: float = 0.0

    async def run(self, targets, timeout):
        if self.delay:
            await asyncio.sleep(self.delay)
        return CheckOutcome(name=self.name, status=self.status,
                            detail=f"{self.status.value} detail",
                            duration_ms=1)


async def test_all_pass_exit_0():
    r = SmokeRunner(
        checks=[FakeCheck("a", CheckStatus.PASS),
                FakeCheck("b", CheckStatus.PASS, depends_on=["a"])],
        targets=object(),
        timeout=5.0,
    )
    exit_code, outcomes = await r.run()
    assert exit_code is ExitCode.GO
    assert [o.status for o in outcomes] == [CheckStatus.PASS, CheckStatus.PASS]


async def test_any_fail_exit_1():
    r = SmokeRunner(
        checks=[FakeCheck("a", CheckStatus.PASS),
                FakeCheck("b", CheckStatus.FAIL)],
        targets=object(),
        timeout=5.0,
    )
    exit_code, _ = await r.run()
    assert exit_code is ExitCode.NO_GO


async def test_config_fail_exit_2_and_skips_rest():
    r = SmokeRunner(
        checks=[FakeCheck("config", CheckStatus.FAIL),
                FakeCheck("database", CheckStatus.PASS, depends_on=["config"]),
                FakeCheck("vault", CheckStatus.PASS, depends_on=["config"])],
        targets=object(),
        timeout=5.0,
    )
    exit_code, outcomes = await r.run()
    assert exit_code is ExitCode.CONFIG_ERROR
    by_name = {o.name: o for o in outcomes}
    assert by_name["database"].status is CheckStatus.SKIP
    assert by_name["vault"].status is CheckStatus.SKIP


async def test_dependency_fail_cascades_skip():
    r = SmokeRunner(
        checks=[FakeCheck("config", CheckStatus.PASS),
                FakeCheck("a", CheckStatus.FAIL, depends_on=["config"]),
                FakeCheck("b", CheckStatus.PASS, depends_on=["a"])],
        targets=object(),
        timeout=5.0,
    )
    exit_code, outcomes = await r.run()
    assert exit_code is ExitCode.NO_GO
    by_name = {o.name: o for o in outcomes}
    assert by_name["b"].status is CheckStatus.SKIP


async def test_independent_checks_run_in_parallel():
    # If not parallelized, total wall time would be >= 0.6s.
    checks = [FakeCheck(f"slow-{i}", CheckStatus.PASS, delay=0.2)
              for i in range(3)]
    r = SmokeRunner(checks=checks, targets=object(), timeout=5.0)
    import time
    t0 = time.perf_counter()
    await r.run()
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.5, f"expected parallel execution, took {elapsed:.2f}s"


async def test_user_skip_list_marks_skip_not_fail():
    r = SmokeRunner(
        checks=[FakeCheck("a", CheckStatus.PASS),
                FakeCheck("b", CheckStatus.FAIL)],
        targets=object(), timeout=5.0, skip={"b"},
    )
    exit_code, outcomes = await r.run()
    by_name = {o.name: o for o in outcomes}
    assert by_name["b"].status is CheckStatus.SKIP
    assert "--skip" in by_name["b"].detail
    assert exit_code is ExitCode.GO
