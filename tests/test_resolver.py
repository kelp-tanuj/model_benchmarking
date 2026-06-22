import daemon.resolver as r


def _setup(monkeypatch, keys: dict):
    """keys: {provider: configured_model}. Presence of a provider == a stored key exists."""
    monkeypatch.setattr(r, "get_key", lambda p: ("k" if p in keys else None))
    monkeypatch.setattr(r, "list_providers",
                        lambda: [{"provider": p, "model": m} for p, m in keys.items()])
    monkeypatch.setattr(r, "_alias_match", lambda slug: (None, None))


def test_native_form_resolves(monkeypatch):
    _setup(monkeypatch, {"gemini": "gemini-2.5-flash-lite"})
    assert r.resolve_candidate("gemini/gemini-2.5-flash-lite") == {
        "status": "native", "provider": "gemini", "model": "gemini-2.5-flash-lite",
        "route": "native"}


def test_openrouter_vendor_maps_to_provider(monkeypatch):
    # google/… (OpenRouter namespace) must resolve to our gemini key
    _setup(monkeypatch, {"gemini": "gemini-2.5-flash-lite"})
    res = r.resolve_candidate("google/gemini-2.5-flash-lite")
    assert res["status"] == "native" and res["provider"] == "gemini"
    assert res["model"] == "gemini-2.5-flash-lite"


def test_bare_slug_matches_stored_model(monkeypatch):
    # the exact bug: no vendor prefix, matched via the stored key's configured model
    _setup(monkeypatch, {"gemini": "gemini-2.5-flash-lite"})
    res = r.resolve_candidate("gemini-2.5-flash-lite")
    assert res["status"] == "native" and res["provider"] == "gemini"


def test_known_provider_without_key_is_pending(monkeypatch):
    _setup(monkeypatch, {})
    res = r.resolve_candidate("cohere/north-mini-code-1.0")
    assert res["status"] == "pending" and res["provider"] == "cohere"


def test_vendor_alias_maps_then_pending(monkeypatch):
    _setup(monkeypatch, {})
    res = r.resolve_candidate("moonshotai/kimi-k2")
    assert res["status"] == "pending" and res["provider"] == "moonshot"


def test_unknown_vendor_is_deferred(monkeypatch):
    _setup(monkeypatch, {})
    assert r.resolve_candidate("weirdvendor/some-model")["status"] == "deferred"


def test_alias_bridge_resolves(monkeypatch):
    _setup(monkeypatch, {"gemini": "x"})
    monkeypatch.setattr(r, "_alias_match",
                        lambda slug: ("google", "gemini-2.5-flash-lite") if slug == "or/foo"
                        else (None, None))
    res = r.resolve_candidate("or/foo")
    assert res["status"] == "native" and res["provider"] == "gemini"
    assert res["model"] == "gemini-2.5-flash-lite"
