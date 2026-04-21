from breadmind.kb.cost import DAILY_BUDGET_USD, PRICE_PER_1K, estimate_daily_cost_usd


def test_price_table_covers_required_providers():
    providers_in_table = {key[0] for key in PRICE_PER_1K}
    for provider in ("anthropic", "azure", "ollama"):
        assert provider in providers_in_table


def test_estimate_daily_cost_simple_sum():
    # 1,000,000 input tokens at $3/1k + 200,000 output at $15/1k
    usd = estimate_daily_cost_usd(
        {("anthropic", "input"): 1_000_000, ("anthropic", "output"): 200_000}
    )
    # 1000 * 3 + 200 * 15 = 3000 + 3000 = 6000
    assert usd == 6000.0


def test_daily_budget_constant_present():
    assert DAILY_BUDGET_USD > 0
