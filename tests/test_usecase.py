import pytest

from harness.usecase import load_golden, load_usecase, validate


def test_load_fixture_usecase():
    uc = load_usecase("fixture_qa")
    assert uc.id == "fixture_qa"
    assert uc.n_reps == 3
    assert uc.temperature == 0.0
    assert uc.invocation["shape"] == "single_call"
    assert {m.name for m in uc.metrics} == {"exact_answer", "helpfulness"}
    assert [m.name for m in uc.deterministic_metrics] == ["exact_answer"]
    assert [m.name for m in uc.semantic_metrics] == ["helpfulness"]
    assert "0.0–1.0" in uc.judge_prompt or "0.0" in uc.judge_prompt
    assert uc.baseline_model == "gemini-2.5-flash-lite"


def test_deterministic_metric_conversion():
    uc = load_usecase("fixture_qa")
    dm = uc.deterministic_metrics[0]
    assert dm.comparison == "exact"
    assert dm.normalize is True


def test_load_golden_validates():
    golden = load_golden("fixture_qa")
    assert len(golden) == 5
    assert golden[0]["input_id"] == "q1"
    assert golden[0]["references"]["exact_answer"] == "Paris"


def test_validate_cross_checks_references(tmp_path):
    # a deterministic metric without a matching reference should fail fast
    uc_dir = tmp_path / "broken"
    uc_dir.mkdir()
    (uc_dir / "broken.md").write_text(
        "---\nid: broken\nmetrics:\n  - name: exact_answer\n    mode: deterministic\n"
        "    comparison: exact\n---\n# broken\n"
    )
    (uc_dir / "golden.jsonl").write_text(
        '{"input_id": "x", "input": {"q": "1"}, "references": {}}\n'
    )
    with pytest.raises(ValueError, match="missing reference"):
        validate("broken", root=tmp_path)


def test_load_golden_rejects_duplicate_ids(tmp_path):
    uc_dir = tmp_path / "dup"
    uc_dir.mkdir()
    (uc_dir / "golden.jsonl").write_text(
        '{"input_id": "a", "input": {}, "references": {}}\n'
        '{"input_id": "a", "input": {}, "references": {}}\n'
    )
    with pytest.raises(ValueError, match="duplicate input_id"):
        load_golden("dup", root=tmp_path)
