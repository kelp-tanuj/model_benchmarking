"""Isolated stdio MCP server for the WEB DISCOVERY workflow (`FastMCP("kelp_disc")`).

This is deliberately SEPARATE from `mcp_server/server.py`: the web-research agent is pinned to
this server via `--strict-mcp-config`, so it can never reach the eval tools (which hold provider
keys via `measured_candidate_call`). This server only reads the catalog/ledger and records
discovered models — no keys, no candidate calls.

Identity resolution + dedup is done HERE in code (the agent just submits raw findings):
candidates ledger → model_aliases → OpenRouter catalog (normkey equality), auto-merging only on
an exact match (writes a model_aliases bridge), else recording a novel candidate.

Env: KELP_DISC_TARGET (hard cap on models recorded per run).
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from common import repo
from common.config import settings
from common.db import connect
from common.identity import clean_suggested_slug, normkey, slugify

mcp = FastMCP("kelp_disc")

TARGET = int(os.environ.get("KELP_DISC_TARGET") or settings.web_discovery_target)
_recorded = 0  # process-lifetime counter (one process == one run); the hard budget backstop

# Clear non-text-generation signals — backstop to the prompt's instructions.
_REJECT_KW = (
    "embedding", "rerank", "reranker", "whisper", "text-to-speech", "speech-to-text",
    "diffusion", "image generation", "image-generation", "upscaler", "tts model",
)


def _passes_keyword_filter(canonical_name: str | None, attributes: str | None) -> bool:
    blob = f"{canonical_name or ''} {attributes or ''}".lower()
    return not any(k in blob for k in _REJECT_KW)


def resolve_discovery(
    conn,
    *,
    canonical_name: str,
    provider: str | None = None,
    est_cost: str | None = None,
    performance: str | None = None,
    attributes: str | None = None,
    source_urls=None,
    suggested_slug: str | None = None,
) -> dict:
    """Dedup + persist one discovered model. Returns {status, slug, ...}. Does the DB writes.

    status: recorded | duplicate | filtered. Never raises on a dup."""
    slug = clean_suggested_slug(suggested_slug) or slugify(provider, canonical_name)
    if not slug:
        return {"status": "filtered", "slug": "", "reason": "no resolvable slug"}
    nk = normkey(slug if "/" in slug else f"{provider or ''}/{canonical_name}")

    if not _passes_keyword_filter(canonical_name, attributes):
        return {"status": "filtered", "slug": slug, "reason": "non-text-gen model"}

    # (a) exact candidate slug — rejected stays rejected, discovered stays discovered, etc.
    if repo.get_candidate(conn, slug):
        return {"status": "duplicate", "slug": slug, "reason": "already a candidate"}

    # (b) known alias (by slug or normkey over either side of the bridge)
    for a in repo.all_aliases(conn):
        if slug in (a["openrouter_slug"], a["native_model_id"]) \
           or normkey(a["openrouter_slug"] or "") == nk \
           or normkey(a["native_model_id"] or "") == nk:
            return {"status": "duplicate", "slug": slug, "reason": "known alias",
                    "matched_openrouter_slug": a["openrouter_slug"]}

    # (c) OpenRouter catalog — exact normkey match => bridge via alias, don't double-surface
    near = None
    for m in repo.all_openrouter_identities(conn):
        mnk = normkey(m["slug"])
        if mnk and mnk == nk:
            repo.add_alias(conn, openrouter_slug=m["slug"], native_provider=provider,
                           native_model_id=slug)
            return {"status": "duplicate", "slug": slug, "reason": "in OpenRouter catalog",
                    "matched_openrouter_slug": m["slug"]}
        # light near-miss flag (substring overlap), never auto-merged
        if near is None and mnk and min(len(mnk), len(nk)) >= 6 and (mnk in nk or nk in mnk):
            near = m["slug"]

    # (d) novel — file as a candidate for the human gate + store the intel
    repo.upsert_candidate(conn, slug=slug, source="web", status="discovered")
    repo.upsert_discovered_model(
        conn, slug=slug, canonical_name=canonical_name, provider=provider, est_cost=est_cost,
        performance=performance, attributes=attributes, source_urls=source_urls,
        possible_duplicate_of=near,
        raw={"canonical_name": canonical_name, "provider": provider, "est_cost": est_cost,
             "performance": performance, "attributes": attributes, "source_urls": source_urls,
             "suggested_slug": suggested_slug},
    )
    return {"status": "recorded", "slug": slug, "possible_duplicate_of": near}


@mcp.tool()
def lookup_known_models(query: str) -> list:
    """Check whether a model is already known BEFORE researching it further (saves web turns).
    Searches the OpenRouter catalog + candidates ledger by name/slug and normalized key."""
    nk = normkey(query)
    out: list[dict] = []
    with connect() as c:
        cand = repo.get_candidate(c, query)
        if cand:
            out.append({"slug": query, "status": cand["status"], "source": cand["source"],
                        "match": "candidate"})
        for m in repo.search_openrouter(c, query):
            out.append({"slug": m["slug"], "name": m.get("name"), "match": "openrouter"})
        if nk:
            for m in repo.all_openrouter_identities(c):
                if normkey(m["slug"]) == nk:
                    out.append({"slug": m["slug"], "match": "openrouter-normkey"})
    seen, uniq = set(), []
    for o in out:
        if o["slug"] in seen:
            continue
        seen.add(o["slug"])
        uniq.append(o)
    return uniq[:10]


@mcp.tool()
def record_discovered_model(
    canonical_name: str,
    provider: str | None = None,
    est_cost: str | None = None,
    performance: str | None = None,
    attributes: str | None = None,
    source_urls: list | None = None,
    suggested_slug: str | None = None,
) -> dict:
    """Persist ONE discovered model as a candidate for the human Benchmark/Skip gate.
    Dedup is done in code; never raises on a dup. Returns {status, slug, recorded, target}."""
    global _recorded
    if _recorded >= TARGET:
        return {"status": "budget_reached", "recorded": _recorded, "target": TARGET}
    with connect() as c:
        res = resolve_discovery(
            c, canonical_name=canonical_name, provider=provider, est_cost=est_cost,
            performance=performance, attributes=attributes, source_urls=source_urls,
            suggested_slug=suggested_slug,
        )
    if res["status"] == "recorded":
        _recorded += 1
    return {**res, "recorded": _recorded, "target": TARGET}


@mcp.tool()
def discovery_budget() -> dict:
    """How many models recorded this run vs the hard cap. STOP when remaining == 0."""
    return {"recorded": _recorded, "target": TARGET, "remaining": max(0, TARGET - _recorded)}


if __name__ == "__main__":
    mcp.run()
