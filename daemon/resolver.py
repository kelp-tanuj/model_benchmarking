"""Provider resolution (phase 5): turn a candidate slug — in ANY namespace form — into a
callable {provider, model, route}, or a clear pending/deferred verdict.

Resolution order (plan: Foundry presence → native/HF → defer):
  0. Foundry presence-check — slots in here once Azure creds + the foundry_models catalog land
     (the table is empty for now, so this is a no-op).
  1. model_aliases — an explicit bridge (e.g. written by the web-discovery OpenRouter match).
  2. vendor-prefix mapping — OpenRouter/native vendor (`google`, `moonshotai`, …) → our
     litellm/key provider name (`gemini`, `moonshot`, …).
  3. stored-key match — a bare slug (no vendor) that equals a stored key's provider or its
     configured model (this is the `gemini-2.5-flash-lite` case that tripped the naive resolver).
  4. pending (known provider, just missing a key) vs deferred (no callable route at all).

The model id returned is the BARE model (no vendor prefix); the caller forms litellm's
"provider/model" string. Phase-5 follow-ups: a `claude -p` reconcile for unknown vendors, and
the real Foundry route — both noted, not built (Foundry needs Azure creds).
"""

from __future__ import annotations

from common import repo
from common.db import connect
from common.identity import normkey
from common.keys import get_key, list_providers

# OpenRouter / common vendor prefix -> the litellm/key provider name we'd call natively.
VENDOR_TO_PROVIDER = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "gemini", "gemini": "gemini", "google-ai-studio": "gemini",
    "mistralai": "mistral", "mistral": "mistral",
    "cohere": "cohere",
    "deepseek": "deepseek",
    "moonshotai": "moonshot", "moonshot": "moonshot",
    "x-ai": "xai", "xai": "xai",
    "groq": "groq",
    "perplexity": "perplexity",
    "together": "together_ai", "togethercomputer": "together_ai",
    "fireworks": "fireworks_ai", "fireworks-ai": "fireworks_ai",
}
# Providers litellm can call natively -> a missing key means 'pending' (ask for it), not 'deferred'.
NATIVE_PROVIDERS = set(VENDOR_TO_PROVIDER.values())


def _split(slug: str) -> tuple[str | None, str]:
    if "/" in slug:
        vendor, model = slug.split("/", 1)
        return vendor.lower(), model
    return None, slug


def _bare(model: str | None) -> str | None:
    """Strip any vendor prefix so the model id is litellm-ready as `provider/<bare>`."""
    if model and "/" in model:
        return model.split("/", 1)[1]
    return model


def _native(provider: str, model: str | None) -> dict:
    return {"status": "native", "provider": provider, "model": _bare(model), "route": "native"}


def _pending(provider: str) -> dict:
    return {"status": "pending", "provider": provider, "model": None, "route": None}


def _deferred(provider: str | None) -> dict:
    return {"status": "deferred", "provider": provider, "model": None, "route": None}


def _alias_match(slug: str) -> tuple[str | None, str | None]:
    """Find a model_aliases row matching this slug by exact id or normalized key."""
    nk = normkey(slug)
    with connect() as c:
        for a in repo.all_aliases(c):
            if slug in (a["openrouter_slug"], a["native_model_id"]) \
               or normkey(a["openrouter_slug"] or "") == nk \
               or normkey(a["native_model_id"] or "") == nk:
                prov = (a["native_provider"] or "").lower().strip()
                return (prov or None), a["native_model_id"]
    return None, None


def resolve_candidate(slug: str) -> dict:
    """Resolve a candidate slug to {status, provider, model, route}.

    status: 'native' (ready to run), 'pending' (known provider, needs a key), 'deferred'
    (no callable route)."""
    vendor, model = _split(slug)

    # 1. explicit alias bridge
    aprov, amodel = _alias_match(slug)
    if aprov:
        prov = VENDOR_TO_PROVIDER.get(aprov, aprov)
        if get_key(prov):
            return _native(prov, amodel or model)
        if prov in NATIVE_PROVIDERS:
            return _pending(prov)

    # 2. vendor-prefix mapping
    if vendor:
        prov = VENDOR_TO_PROVIDER.get(vendor, vendor)
        if get_key(prov):
            return _native(prov, model)

    # 3. stored-key match (bare slug == a stored provider or its configured model)
    for p in list_providers():
        if slug == p["provider"] or (p.get("model") and slug == p["model"]):
            return _native(p["provider"], model)
        if vendor and vendor == p["provider"]:
            return _native(p["provider"], model)

    # 4. pending (known provider, just no key) vs deferred (unroutable)
    guess = VENDOR_TO_PROVIDER.get(vendor, vendor) if vendor else slug
    if guess in NATIVE_PROVIDERS:
        return _pending(guess)
    return _deferred(guess)
