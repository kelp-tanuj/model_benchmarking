from daemon import teams


def test_discovery_card_has_benchmark_skip_with_data():
    c = teams.discovery_card("openai/gpt-x", "GPT X", 128000)
    assert c["type"] == "AdaptiveCard"
    titles = [a["title"] for a in c["actions"]]
    assert "Benchmark" in titles and "Skip" in titles
    data = [a["data"] for a in c["actions"]]
    assert any(d["kind"] == "discovery_decision" and d["decision"] == "benchmark" for d in data)
    assert all(d["slug"] == "openai/gpt-x" for d in data)


def test_confirm_card_carries_state():
    c = teams.confirm_card("gemini/x", ["fixture_qa"])
    confirm = next(a for a in c["actions"] if a["title"] == "Confirm")
    assert confirm["data"]["confirmed"] is True
    assert confirm["data"]["slug"] == "gemini/x"
    assert confirm["data"]["use_cases"] == ["fixture_qa"]
    cancel = next(a for a in c["actions"] if a["title"] == "Cancel")
    assert cancel["data"]["confirmed"] is False


def test_usecase_select_card_includes_all_option():
    c = teams.usecase_select_card("m", ["a", "b"])
    choiceset = next(b for b in c["body"] if b.get("type") == "Input.ChoiceSet")
    values = [ch["value"] for ch in choiceset["choices"]]
    assert "a" in values and "b" in values and "all" in values
    assert choiceset["isMultiSelect"] is True


def test_key_request_card_is_masked():
    c = teams.key_request_card("gemini")
    field = next(b for b in c["body"] if b.get("type") == "Input.Text")
    assert field["style"] == "password"


def test_help_card_is_valid():
    assert teams.help_card()["type"] == "AdaptiveCard"
