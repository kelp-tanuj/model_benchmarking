from daemon.dispatcher import _coerce_intent, as_use_case_list


def test_as_use_case_list_handles_csv_string():
    # Adaptive-Card multi-select returns a comma-joined string, not a list.
    assert as_use_case_list("a, b ,c") == ["a", "b", "c"]


def test_as_use_case_list_handles_list_and_strips():
    assert as_use_case_list(["a", " b ", ""]) == ["a", "b"]


def test_as_use_case_list_none_and_bad_types():
    assert as_use_case_list(None) == []
    assert as_use_case_list(123) == []
    assert as_use_case_list({"a": 1}) == []
    assert as_use_case_list("all") == ["all"]


def test_coerce_intent_rejects_non_dict():
    safe = {"action": "unknown", "model_query": None, "use_cases": None}
    for bad in ("benchmark", ["benchmark"], 123, None):
        assert _coerce_intent(bad) == safe


def test_coerce_intent_normalizes_string_use_cases():
    out = _coerce_intent({"action": "benchmark", "model_query": "kimi", "use_cases": "a,b"})
    assert out == {"action": "benchmark", "model_query": "kimi", "use_cases": ["a", "b"]}


def test_coerce_intent_non_string_model_query_becomes_none():
    out = _coerce_intent({"action": "benchmark", "model_query": ["x"], "use_cases": None})
    assert out["model_query"] is None
    assert out["action"] == "benchmark"


def test_coerce_intent_unknown_action_collapses():
    out = _coerce_intent({"action": "rm -rf", "model_query": "x"})
    assert out["action"] == "unknown"
