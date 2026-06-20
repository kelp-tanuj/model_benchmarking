"""Inbound Teams consumer: polls the teams_inbox table (Power Automate flows write rows there)
and drives the conversation. CODE executes; the dispatcher only classifies.

Confirm-before-spend: a benchmark_request never queues directly — it walks the user through
model reconciliation → use-case selection → an explicit confirm card. Only `handle_confirm`
(with confirmed === True) writes candidate(status='queued').

Robustness contract for each row:
  - handlers take ONLY the (untrusted) payload; they open short DB transactions internally and
    do network/subprocess I/O (parse_request, teams.post) OUTSIDE any transaction, so a hung
    claude call can never pin a DB connection.
  - a bad payload (missing field, wrong type, non-dict) is a PERMANENT failure: post a help
    card and mark the row processed (dead-lettered) so it never loops.
  - any other exception is TRANSIENT (DB/network blip): bump an attempts counter and retry,
    dead-lettering after settings.teams_inbox_max_attempts so a poison row can't loop forever.
"""

from __future__ import annotations

import argparse
import time

from common import repo
from common.config import settings
from common.db import connect
from daemon import teams
from daemon.dispatcher import as_use_case_list, parse_request


class PermanentError(Exception):
    """A row that can never succeed as written (bad/missing fields). Dead-letter it, don't retry."""


def _require(payload: dict, key: str):
    value = payload.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise PermanentError(f"missing required field {key!r}")
    return value


def _is_true(value) -> bool:
    """Confirm gate: only a real boolean True or the literal string 'true' confirms a spend.

    Adaptive-Card / Power Automate round-trips can deliver the value as a string, so a naive
    truthiness check would let Cancel (confirmed='false') fall through and SPEND.
    """
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def handle_discovery_decision(payload: dict) -> None:
    slug = _require(payload, "slug")
    user = payload.get("user", "teams")
    if payload.get("decision") == "benchmark":
        with connect() as c:
            updated = repo.set_candidate_status(c, slug, "queued", decided_by=user)
        if updated:
            teams.post("ack", "channel", f"Queued {slug} for benchmarking.")
        else:  # no candidate row — don't claim success
            teams.post("alert", "channel", f"Couldn't queue {slug}.",
                       card=teams.alert_card("Unknown model", [f"No candidate row for {slug}."]))
    else:
        with connect() as c:
            repo.set_candidate_status(c, slug, "rejected", decided_by=user)


def handle_benchmark_request(payload: dict) -> None:
    intent = parse_request(payload.get("text", ""))  # subprocess I/O — no DB txn held
    if intent.get("action") != "benchmark" or not intent.get("model_query"):
        teams.post("help", "channel", "I didn't catch a model to benchmark.", card=teams.help_card())
        return
    with connect() as c:
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
    use_cases = as_use_case_list(intent.get("use_cases"))
    if not use_cases:
        with connect() as c:
            ucs = repo.list_use_cases(c)
        teams.post("usecase_select", "channel", f"Which use case(s) for {slug}?",
                   card=teams.usecase_select_card(slug, ucs))
        return
    teams.post("confirm", "channel", f"Benchmark {slug}?",
               card=teams.confirm_card(slug, use_cases))


def handle_usecase_select(payload: dict) -> None:
    slug = _require(payload, "slug")
    use_cases = as_use_case_list(payload.get("use_cases"))
    if not use_cases:
        with connect() as c:
            ucs = repo.list_use_cases(c)
        teams.post("usecase_select", "channel", "Pick at least one use case.",
                   card=teams.usecase_select_card(slug, ucs))
        return
    teams.post("confirm", "channel", f"Benchmark {slug}?",
               card=teams.confirm_card(slug, use_cases))


def handle_confirm(payload: dict) -> None:
    if not _is_true(payload.get("confirmed")):
        teams.post("ack", "channel", "Cancelled.")
        return
    slug = _require(payload, "slug")
    use_cases = as_use_case_list(payload.get("use_cases"))
    with connect() as c:
        repo.upsert_candidate(c, slug=slug, source="teams", status="queued",
                              decided_by=payload.get("user", "teams"))
    teams.post("ack", "channel",
               f"Queued {slug} (use cases: {use_cases}).")


HANDLERS = {
    "discovery_decision": handle_discovery_decision,
    "benchmark_request": handle_benchmark_request,
    "usecase_select": handle_usecase_select,
    "confirm": handle_confirm,
}


def _process_row(row: dict) -> tuple[str, str | None]:
    """Run one inbox row's handler. Returns (outcome, error) where outcome is
    'done' | 'permanent' | 'transient'. Never raises."""
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return ("permanent", "payload is not a JSON object")
    handler = HANDLERS.get(row["kind"])
    if handler is None:
        return ("permanent", f"unknown kind {row['kind']!r}")
    try:
        handler(payload)
        return ("done", None)
    except PermanentError as exc:
        teams.post("help", "channel", "I couldn't process that request.", card=teams.help_card())
        return ("permanent", str(exc))
    except Exception as exc:  # transient: DB/network blip — retry
        return ("transient", f"{type(exc).__name__}: {exc}")


def poll_once() -> int:
    with connect() as c:
        rows = repo.get_unprocessed_inbox(c)
    for row in rows:
        outcome, err = _process_row(row)
        # Bookkeeping is a SEPARATE transaction so a handler's failure can't roll back the
        # processed/attempts mark (the original poison-row loop bug).
        try:
            with connect() as c:
                if outcome == "transient":
                    attempts = repo.bump_inbox_attempt(c, row["id"], err)
                    if attempts >= settings.teams_inbox_max_attempts:
                        repo.mark_inbox_processed(c, row["id"], error=f"dead-lettered: {err}")
                        print(f"[consumer] row {row['id']} dead-lettered after {attempts} attempts")
                    else:
                        print(f"[consumer] row {row['id']} transient failure "
                              f"({attempts}/{settings.teams_inbox_max_attempts}): {err}")
                else:  # done | permanent — terminal
                    repo.mark_inbox_processed(c, row["id"], error=err)
                    if outcome == "permanent":
                        print(f"[consumer] row {row['id']} dead-lettered (permanent): {err}")
        except Exception as exc:
            print(f"[consumer] bookkeeping error on row {row['id']} ({type(exc).__name__})")
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
