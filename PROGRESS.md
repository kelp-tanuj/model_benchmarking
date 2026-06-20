# Kelp Benchmark — Build Progress

Plan of record: `~/.claude/plans/i-am-building-v1-bright-pelican.md` (full design + decisions).

## Status (phases done + pushed to origin/main)
- **Phase 1 — eval loop ✅**: `claude -p` orchestrates a rep over the golden set via 6 stdio-MCP
  code tools; semantic judging in-session; Python aggregates `item_scores → scores_per_run →
  scores` (mean+range); drift rule; separate `claude -p` report. Verified with real Gemini N=3.
- **Phase 2 — leaderboard + drift ✅**: read-only Streamlit board, `drift_runner`, APScheduler
  off-hours cron. `benchmarks.is_drift` excludes drift re-runs from the board.
- **Phase 3 — Teams daemon-side ✅**: HTTP endpoint (`/enqueue`, `/callback/key` secret-guarded,
  `/health`), `teams.py` cards + post-to-flow, `dispatcher.py` (claude -p intent parse, no tools),
  `teams_consumer.py` (polls `teams_inbox`, confirm-before-spend). User wires Power Automate flows.

## Next
- **Phase 4 — discovery**: OpenRouter `/models` sync + new-model SQL join + dedup ledger +
  relevance filter + discovery cards (buildable now, no key). Foundry presence-check catalog
  needs Azure creds. Retirement = sync-diff on lagging `last_seen`.
- **Phase 5 — provider resolution** (Foundry→native/HF→defer) + generalize to more use cases.

## Run commands (from repo root; `.env` has DATABASE_URL)
- Tests: `uv run pytest -q`
- Migrate: `uv run alembic -c db/alembic.ini upgrade head`
- Benchmark: `uv run python -m daemon.orchestrator --use-case fixture_qa --slug gemini/gemini-2.5-flash-lite --provider gemini --model gemini-2.5-flash-lite --reps 3 --report`
- Drift: `uv run python -m daemon.drift_runner --use-case fixture_qa`
- Scheduler: `uv run python -m daemon.scheduler --list`
- HTTP endpoint: `uv run python -m daemon.http_app`   ·   Consumer: `uv run python -m daemon.teams_consumer`
- Leaderboard: `uv run streamlit run apps/user/app.py`

## Secrets / config (never commit)
- `.env` (gitignored): `DATABASE_URL` (Neon), `TEAMS_POST_FLOW_URL`, `KEY_INGEST_SECRET`.
- `keys.json` (gitignored, 600): provider keys via `uv run python -m common.keys set-file <provider> <file> <model>`.

## Constraints (also in agent memory)
- **No web search** anywhere (no quota): candidate calls have no tools; every `claude -p` call
  passes `--disallowedTools WebSearch,WebFetch,...` (+ fs/shell denied).
- Billing is **quota-based** (Max subscription), not per-token.
- Judge is **uncalibrated** — quality scores are a stability gauge, not accuracy.

## User follow-ups to go fully live
- Power Automate: 4 Workflows + `TEAMS_POST_FLOW_URL` + dev tunnel to `/callback/key`.
- Azure Foundry creds (subscription id, location, ARM token) for the presence-check catalog.
- EnrichList use-case MD + `usecases/enrichlist/golden.jsonl` to replace the synthetic fixture.
