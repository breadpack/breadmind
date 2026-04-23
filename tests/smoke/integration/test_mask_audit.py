import io

from breadmind.smoke.checks.base import CheckOutcome, CheckStatus
from breadmind.smoke.runner import SmokeRunner, render_table


class LeakyCheck:
    name = "leaky"
    depends_on: list[str] = []

    async def run(self, targets, timeout):
        return CheckOutcome(
            name=self.name, status=CheckStatus.FAIL,
            detail=(
                "leaked xoxb-111-222-SECRETDEADBEEF and "
                "ATATT_secrettoken_1234567890abcdef and "
                "sk-ant-apitoken-ABCDEFGHIJ and "
                "AKIAIOSFODNN7EXAMPLE and "
                "Bearer eyJxxxxxxxxxxxxxxxxxxxxxxxxx and "
                "ops@acme.com"
            ),
        )


async def test_no_secret_survives_in_progress_or_table():
    progress = io.StringIO()
    r = SmokeRunner(checks=[LeakyCheck()], targets=object(),
                    timeout=5.0, progress=progress)
    _, outcomes = await r.run()
    table = render_table(outcomes)

    for forbidden in (
        "xoxb-111-222-SECRETDEADBEEF",
        "ATATT_secrettoken_1234567890abcdef",
        "sk-ant-apitoken-ABCDEFGHIJ",
        "AKIAIOSFODNN7EXAMPLE",
        "eyJxxxxxxxxxxxxxxxxxxxxxxxxx",
        "ops@acme.com",
    ):
        assert forbidden not in progress.getvalue(), f"leaked in progress: {forbidden}"
        assert forbidden not in table, f"leaked in table: {forbidden}"
