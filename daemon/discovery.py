"""Discovery: OpenRouter is the SOLE sourcing radar (Foundry is a presence check only).

Pipeline (all deterministic code; no agent):
  fetch /models  ->  idempotent catalog upsert (last_seen)  ->  new-model detection
  ->  relevance pre-filter  ->  candidate(discovered) + Teams Benchmark/Skip card.

`candidates` is the dedup ledger: a slug already there (discovered/rejected/queued/…) never
re-surfaces, so a rejected model stays rejected. The FIRST sync (empty catalog) is a baseline
— it populates the table but raises no discoveries, so we don't flood on day one.

Retirement = sync-diff: a model whose last_seen lags this sync's cutoff has dropped off the
catalog. We alert only for models we've benchmarked / that back a baseline, and only once each
(dedup via a run_logs 'retirement' event).
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

from common import repo
from common.config import settings
from common.db import connect
from daemon import teams

DEFAULT_MODELS_URL = "https://openrouter.ai/api/v1/models"


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "kelp-benchmark/0.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def fetch_openrouter_models(fetcher=None) -> list[dict]:
    """Return the raw list of model dicts. `fetcher` is injectable for offline tests."""
    data = (fetcher or (lambda: _http_get_json(DEFAULT_MODELS_URL)))()
    items = data.get("data") if isinstance(data, dict) else data
    return items if isinstance(items, list) else []


def _to_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def normalize_model(item) -> dict | None:
    if not isinstance(item, dict):
        return None
    slug = item.get("id")
    if not slug or not isinstance(slug, str):
        return None
    arch = item.get("architecture") or {}
    modality = arch.get("modality")
    if not modality:  # older payloads expose input/output modality lists instead
        ins = arch.get("input_modalities") or []
        outs = arch.get("output_modalities") or []
        if ins or outs:
            modality = f"{'+'.join(ins)}->{'+'.join(outs)}"
    pricing = item.get("pricing") or {}
    return {
        "slug": slug,
        "name": item.get("name"),
        "modality": modality,
        "context_length": item.get("context_length"),
        "price_prompt": _to_float(pricing.get("prompt")),
        "price_completion": _to_float(pricing.get("completion")),
        "raw": item,
    }


def passes_relevance(m: dict) -> bool:
    """Drop noise before the human gate: non-text modality, tiny context, (optional) price cap."""
    if settings.relevance_require_text:
        modality = m.get("modality") or ""
        parts = modality.split("->")
        ins = parts[0] if parts else ""
        outs = parts[1] if len(parts) > 1 else ins
        if "text" not in ins or "text" not in outs:
            return False
    if (m.get("context_length") or 0) < settings.relevance_min_context:
        return False
    cap = settings.relevance_max_price_prompt
    if cap is not None and m.get("price_prompt") is not None and m["price_prompt"] > cap:
        return False
    return True


def sync_openrouter(fetcher=None, *, post_cards: bool = True) -> dict:
    items = fetch_openrouter_models(fetcher)

    with connect() as c:
        cutoff = repo.db_now(c)                      # read BEFORE upserts (skew-free diff)
        first_sync = repo.count_openrouter_models(c) == 0

    new_slugs: list[str] = []
    skipped = 0
    with connect() as c:
        for item in items:
            m = normalize_model(item)
            if not m:
                skipped += 1
                continue
            if repo.upsert_openrouter_model(c, **m):
                new_slugs.append(m["slug"])

    discoveries: list[dict] = []
    filtered = 0
    if not first_sync:  # baseline sync surfaces nothing
        with connect() as c:
            for slug in new_slugs:
                m = repo.get_openrouter_model(c, slug)
                if not m or not passes_relevance(m):
                    filtered += 1
                    continue
                if repo.get_candidate(c, slug):     # dedup ledger
                    continue
                repo.upsert_candidate(c, slug=slug, source="openrouter", status="discovered")
                discoveries.append(m)

    retired_alerted: list[str] = []
    with connect() as c:
        for slug in repo.get_retired_important(c, cutoff):
            if repo.has_event(c, "retirement", slug):
                continue
            repo.log(c, benchmark_id=None, run_id=None, level="warning",
                     event="retirement", detail={"slug": slug})
            retired_alerted.append(slug)

    if post_cards:
        for m in discoveries:
            teams.post("discovery", "channel", f"New model discovered: {m['slug']}",
                       card=teams.discovery_card(m["slug"], m.get("name"), m.get("context_length")))
        for slug in retired_alerted:
            teams.post("alert", "channel", f"Model retired: {slug}",
                       card=teams.alert_card("Model retired",
                                             [f"{slug} dropped off the OpenRouter catalog."]))

    return {
        "synced": len(items),
        "normalize_skipped": skipped,
        "new_in_catalog": len(new_slugs),
        "relevance_filtered": filtered,
        "discoveries": [m["slug"] for m in discoveries],
        "retired_alerted": retired_alerted,
        "first_sync": first_sync,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Sync the OpenRouter catalog + surface candidates.")
    ap.add_argument("--fixture", help="path to a local /models JSON file (offline; no network)")
    ap.add_argument("--no-cards", action="store_true", help="don't post discovery/retirement cards")
    args = ap.parse_args()
    fetcher = None
    if args.fixture:
        text = Path(args.fixture).read_text()
        fetcher = lambda: json.loads(text)  # noqa: E731 - tiny injectable
    print(json.dumps(sync_openrouter(fetcher, post_cards=not args.no_cards), indent=2, default=str))


if __name__ == "__main__":
    main()
