import pytest

from daemon import teams_consumer as tc
from daemon.teams_consumer import PermanentError, _is_true, _process_row, _require


def test_is_true_only_real_true_or_literal_true_string():
    assert _is_true(True) is True
    assert _is_true("true") is True
    assert _is_true("  True ") is True
    # The bug this guards: a truthy string must NOT confirm a spend.
    for v in (False, "false", "0", "no", "yes", 0, 1, None, "", [], {}):
        assert _is_true(v) is False


def test_require_raises_permanent_on_missing_or_blank():
    with pytest.raises(PermanentError):
        _require({}, "slug")
    with pytest.raises(PermanentError):
        _require({"slug": "   "}, "slug")
    assert _require({"slug": "x"}, "slug") == "x"


def test_process_row_non_dict_payload_is_permanent():
    outcome, _ = _process_row({"kind": "confirm", "payload": ["nope"], "id": 1})
    assert outcome == "permanent"


def test_process_row_unknown_kind_is_permanent():
    outcome, _ = _process_row({"kind": "gibberish", "payload": {}, "id": 1})
    assert outcome == "permanent"


def test_process_row_handler_keyerror_is_transient(monkeypatch):
    monkeypatch.setitem(tc.HANDLERS, "boom", lambda payload: (_ for _ in ()).throw(KeyError("x")))
    outcome, err = _process_row({"kind": "boom", "payload": {}, "id": 1})
    assert outcome == "transient"
    assert "KeyError" in err


def test_process_row_permanent_error_posts_help(monkeypatch):
    posted = []
    monkeypatch.setattr(tc.teams, "post", lambda *a, **k: posted.append(a))

    def bad(payload):
        raise PermanentError("missing slug")

    monkeypatch.setitem(tc.HANDLERS, "bad", bad)
    outcome, err = _process_row({"kind": "bad", "payload": {}, "id": 1})
    assert outcome == "permanent"
    assert posted, "a help card should be posted on a permanent failure"


def test_process_row_success(monkeypatch):
    monkeypatch.setitem(tc.HANDLERS, "ok", lambda payload: None)
    outcome, err = _process_row({"kind": "ok", "payload": {}, "id": 1})
    assert outcome == "done" and err is None
