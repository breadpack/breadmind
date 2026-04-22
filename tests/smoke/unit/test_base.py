from breadmind.smoke.checks.base import CheckOutcome, CheckStatus, SmokeCheck


def test_check_outcome_pass_defaults():
    o = CheckOutcome(name="x", status=CheckStatus.PASS)
    assert o.detail == ""
    assert o.duration_ms == 0


def test_check_outcome_fail_with_detail():
    o = CheckOutcome(name="x", status=CheckStatus.FAIL, detail="boom", duration_ms=42)
    assert o.status is CheckStatus.FAIL
    assert o.detail == "boom"
    assert o.duration_ms == 42


def test_check_outcome_is_failing():
    assert CheckOutcome(name="x", status=CheckStatus.FAIL).is_failing
    assert not CheckOutcome(name="x", status=CheckStatus.PASS).is_failing
    assert not CheckOutcome(name="x", status=CheckStatus.SKIP).is_failing


def test_smoke_check_is_protocol():
    class Dummy:
        name = "dummy"
        depends_on: list[str] = []

        async def run(self, t, timeout: float) -> CheckOutcome:
            return CheckOutcome(name=self.name, status=CheckStatus.PASS)

    d: SmokeCheck = Dummy()  # type: ignore[assignment]
    assert d.name == "dummy"
