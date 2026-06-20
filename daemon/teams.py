"""Outbound Teams via Power Automate Workflows.

The daemon POSTs a small envelope {kind, target, text, card} to the flow's "When a Teams
webhook request is received" URL; the flow renders the adaptive card as the Flow bot. If no
URL is configured yet, post() is a logged no-op so the daemon runs without Teams wired.

Card builders embed their context in Action.Submit `data` so multi-step responses carry state
back through the flow (no server-side conversation state needed).
"""

from __future__ import annotations

import json
import urllib.request

from common.config import settings


def post(kind: str, target: str, text: str, card: dict | None = None) -> dict:
    """Send to the post-to-Teams flow. target is 'channel' or 'chat'.

    Every message goes out as an adaptive card (plain text is wrapped in a minimal one) so the
    Power Automate flow only ever needs a single "Post card" action — no card/text branching.
    """
    card = card or _text_card(text)
    payload = {"kind": kind, "target": target, "text": text, "card": card}
    if not settings.teams_post_flow_url:
        print(f"[teams] (no flow URL) would post [{kind}->{target}]: {text}")
        return {"posted": False, "reason": "no_flow_url"}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        settings.teams_post_flow_url, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return {"posted": True, "status": resp.status}
    except Exception as exc:  # never raise into the daemon loop over a Teams hiccup
        # Log only the exception TYPE — str(exc) can embed the signed flow URL (a credential).
        print(f"[teams] post failed ({type(exc).__name__})")
        return {"posted": False, "error": type(exc).__name__}


def _card(title: str, body: list, actions: list | None = None) -> dict:
    return {
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": [{"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium"},
                 *body],
        "actions": actions or [],
    }


def _text(t: str) -> dict:
    return {"type": "TextBlock", "text": t, "wrap": True}


def _text_card(text: str) -> dict:
    """Minimal card so even plain-text messages travel as an adaptive card."""
    return {"type": "AdaptiveCard", "version": "1.5", "body": [_text(text)]}


def discovery_card(slug: str, name: str | None = None, context_length: int | None = None) -> dict:
    body = [_text(f"**{slug}**" + (f" — {name}" if name else "")),
            _text(f"context: {context_length:,}" if context_length else "context: n/a")]
    actions = [
        {"type": "Action.Submit", "title": "Benchmark",
         "data": {"kind": "discovery_decision", "slug": slug, "decision": "benchmark"}},
        {"type": "Action.Submit", "title": "Skip",
         "data": {"kind": "discovery_decision", "slug": slug, "decision": "skip"}},
    ]
    return _card("New model discovered", body, actions)


def disambig_card(query: str, matches: list[dict]) -> dict:
    actions = [
        {"type": "Action.Submit", "title": m["slug"],
         "data": {"kind": "usecase_select", "slug": m["slug"]}}
        for m in matches[:6]
    ]
    return _card(f"Did you mean…? (for '{query}')", [_text("Pick the model:")], actions)


def usecase_select_card(slug: str, use_cases: list[str]) -> dict:
    choices = [{"title": uc, "value": uc} for uc in use_cases] + [{"title": "all", "value": "all"}]
    body = [
        _text(f"Which use case(s) to benchmark **{slug}** on?"),
        {"type": "Input.ChoiceSet", "id": "use_cases", "isMultiSelect": True,
         "choices": choices},
    ]
    actions = [{"type": "Action.Submit", "title": "Next",
                "data": {"kind": "usecase_select", "slug": slug}}]
    return _card("Select use case", body, actions)


def confirm_card(slug: str, use_cases: list[str]) -> dict:
    body = [_text(f"Benchmark **{slug}** on **{', '.join(use_cases)}**? This will spend on a "
                  f"rate-limited model run.")]
    actions = [
        {"type": "Action.Submit", "title": "Confirm",
         "data": {"kind": "confirm", "slug": slug, "use_cases": use_cases, "confirmed": True}},
        {"type": "Action.Submit", "title": "Cancel",
         "data": {"kind": "confirm", "slug": slug, "use_cases": use_cases, "confirmed": False}},
    ]
    return _card("Confirm benchmark", body, actions)


def key_request_card(provider: str) -> dict:
    """Masked key entry (1:1 chat). The flow POSTs the value to the daemon /callback/key."""
    body = [
        _text(f"A provider key is needed for **{provider}**."),
        {"type": "Input.Text", "id": "key", "style": "password",
         "placeholder": f"{provider} API key"},
    ]
    actions = [{"type": "Action.Submit", "title": "Submit key",
                "data": {"kind": "key", "provider": provider}}]
    return _card("API key request", body, actions)


def help_card() -> dict:
    return _card("I didn't catch that", [
        _text("I can: **request a benchmark** (e.g. \"benchmark <model> on <use case>\"), "
              "or you can answer a pending card."),
    ])


def summary_card(slug: str, use_case: str, lines: list[str], report_url: str | None = None) -> dict:
    body = [_text(f"**{slug}** on **{use_case}**"), *[_text(line) for line in lines]]
    actions = ([{"type": "Action.OpenUrl", "title": "Open report", "url": report_url}]
               if report_url else [])
    return _card("Benchmark complete", body, actions)


def alert_card(title: str, lines: list[str]) -> dict:
    return _card(f"⚠️ {title}", [_text(line) for line in lines])
