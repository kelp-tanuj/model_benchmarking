"""Inbound Teams consumer: polls the teams_inbox table (Power Automate flows write rows there)
and drives the conversation. CODE executes; the dispatcher only classifies.

Confirm-before-spend: a benchmark_request never queues directly — it walks the user through
model reconciliation → use-case selection → an explicit confirm card. Only `handle_confirm`
(with confirmed=True) writes candidate(status='queued').
"""

from __future__ import annotations

import argparse
import time

from common import repo
from common.config import settings
from common.db import connect
from daemon import teams
from daemon.dispatcher import parse_request


def handle_discovery_decision(c, payload: dict) -> None:
    slug = payload["slug"]
    if payload.get("decision") == "benchmark":
        repo.set_candidate_status(c, slug, "queued", decided_by=payload.get("user", "teams"))
        teams.post("ack", "channel", f"Queued {slug} for benchmarking.")
    else:
        repo.set_candidate_status(c, slug, "rejected", decided_by=payload.get("user", "teams"))


def handle_benchmark_request(c, payload: dict) -> None:
    intent = parse_request(payload.get("text", ""))
    if intent.get("action") != "benchmark" or not intent.get("model_query"):
        teams.post("help", "channel", "I didn't catch a model to benchmark.", card=teams.help_card())
        return
    matches = repo.search_openrouter(c, intent["model_query"])
    if not matches:
        teams.post("help", "channel",
                   f"No model in the catalog matched '{intent['model_query']}'.")
        return
    if len(matches) > 1:
        teams.post("disambig", "channel", "Did you mean…?",
                   card=teams.disambig_card(intent["model_query"], matches))
        return
    slug = matches[0]["slug"]
    use_cases = intent.get("use_cases")
    if not use_cases:
        teams.post("usecase_select", "channel", f"Which use case(s) for {slug}?",
                   card=teams.usecase_select_card(slug, repo.list_use_cases(c)))
        return
    teams.post("confirm", "channel", f"Benchmark {slug}?",
               card=teams.confirm_card(slug, use_cases))


def handle_usecase_select(c, payload: dict) -> None:
    slug = payload["slug"]
    use_cases = payload.get("use_cases") or []
    if not use_cases:
        teams.post("usecase_select", "channel", "Pick at least one use case.",
                   card=teams.usecase_select_card(slug, repo.list_use_cases(c)))
        return
    teams.post("confirm", "channel", f"Benchmark {slug}?",
               card=teams.confirm_card(slug, use_cases))


def handle_confirm(c, payload: dict) -> None:
    if not payload.get("confirmed"):
        teams.post("ack", "channel", "Cancelled.")
        return
    slug = payload["slug"]
    repo.upsert_candidate(c, slug=slug, source="teams", status="queued",
                          decided_by=payload.get("user", "teams"))
    teams.post("ack", "channel",
               f"Queued {slug} (use cases: {payload.get('use_cases')}).")


HANDLERS = {
    "discovery_decision": handle_discovery_decision,
    "benchmark_request": handle_benchmark_request,
    "usecase_select": handle_usecase_select,
    "confirm": handle_confirm,
}


def poll_once() -> int:
    with connect() as c:
        rows = repo.get_unprocessed_inbox(c)
    for row in rows:
        handler = HANDLERS.get(row["kind"])
        try:
            with connect() as c:
                if handler:
                    handler(c, row["payload"])
                else:
                    print(f"[consumer] unknown kind {row['kind']!r}, skipping")
                repo.mark_inbox_processed(c, row["id"])
        except Exception as exc:  # isolate one bad row from the rest of the batch
            print(f"[consumer] error on row {row['id']} ({row['kind']}): {exc}")
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Poll teams_inbox and drive the Teams flow.")
    ap.add_argument("--once", action="store_true", help="process the backlog once and exit")
    args = ap.parse_args()
    if args.once:
        print(f"[consumer] processed {poll_once()} rows")
        return
    print(f"[consumer] polling teams_inbox every {settings.teams_poll_seconds}s")
    while True:
        poll_once()
        time.sleep(settings.teams_poll_seconds)


if __name__ == "__main__":
    main()
