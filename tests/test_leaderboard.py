from common.leaderboard import format_cell


def test_format_quality_flat_and_range():
    assert format_cell("helpfulness", 1.0, 1.0, 1.0) == "1.000"
    assert format_cell("helpfulness", 0.8, 0.7, 0.9) == "0.800 [0.700–0.900]"


def test_format_latency():
    assert format_cell("latency_ms", 1344.9, 1344.9, 1344.9) == "1345 ms"
    assert format_cell("latency_ms", 1344.9, 1236.0, 1522.0) == "1345 ms [1236–1522]"


def test_format_cost_and_tokens():
    assert format_cell("cost", 0.0, 0.0, 0.0) == "$0"
    assert format_cell("cost", 2e-5, 2e-5, 2e-5) == "$2.00e-05"
    assert format_cell("tokens_in", 175.0, 175.0, 175.0) == "175"
