from harness.scorers import score_value
from harness.types import DeterministicMetric


def m(comparison, **kw):
    return DeterministicMetric(name="t", comparison=comparison, **kw)


def test_exact_match_and_normalization():
    assert score_value("Paris", "paris", m("exact")) == 1.0
    assert score_value("  Paris ", "paris", m("exact")) == 1.0
    assert score_value("Paris", "London", m("exact")) == 0.0
    assert score_value("Paris", "paris", m("exact", normalize=False)) == 0.0


def test_field_full_and_partial():
    out = {"name": "Acme", "ceo": "Jane", "hq": "NYC"}
    ref = {"name": "acme", "ceo": "jane", "hq": "nyc"}
    assert score_value(out, ref, m("field")) == 1.0
    ref2 = {"name": "acme", "ceo": "jane", "hq": "LA"}
    assert score_value(out, ref2, m("field")) == 2 / 3
    # restrict to a subset of fields
    assert score_value(out, ref2, m("field", fields=("name", "ceo"))) == 1.0


def test_field_parses_json_string_output():
    out = '{"name": "Acme", "ceo": "Jane"}'
    ref = {"name": "acme", "ceo": "jane"}
    assert score_value(out, ref, m("field")) == 1.0
    assert score_value("not json", ref, m("field")) == 0.0


def test_schema_valid_invalid():
    schema = {
        "type": "object",
        "required": ["name", "count"],
        "properties": {"name": {"type": "string"}, "count": {"type": "integer"}},
    }
    metric = m("schema", json_schema=schema)
    assert score_value({"name": "x", "count": 3}, None, metric) == 1.0
    assert score_value({"name": "x"}, None, metric) == 0.0
    assert score_value({"name": "x", "count": "nope"}, None, metric) == 0.0
    assert score_value('{"name":"x","count":5}', None, metric) == 1.0


def test_numeric_absolute_and_relative_tolerance():
    assert score_value(100, 100, m("numeric")) == 1.0
    assert score_value(102, 100, m("numeric", tolerance=5)) == 1.0
    assert score_value(106, 100, m("numeric", tolerance=5)) == 0.0
    assert score_value(105, 100, m("numeric", rel_tolerance=0.05)) == 1.0
    assert score_value(106, 100, m("numeric", rel_tolerance=0.05)) == 0.0
    assert score_value("abc", 100, m("numeric")) == 0.0
