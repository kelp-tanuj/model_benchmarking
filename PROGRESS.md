# Kelp Benchmark — Build Progress

Plan of record: `~/.claude/plans/i-am-building-v1-bright-pelican.md` (full design + decisions).

## Status (phases done + pushed to origin/main)
- **Phase 1 — eval loop ✅**: `claude -p` orchestrates a rep over the golden set via 6 stdio-MCP
  code tools; semantic judging in-session; Python aggregates `item_scores → scores_per_run →
  scores` (mean+range); drift rule; separate `claude -p` report. Verified with real Gemini N=3.
- **Phase 2 — leaderboard + drift ✅**: read-only Streamlit board, `drift_runner`, APScheduler
  off-hours cron. `benchmarks.is_drift` excludes drift re-runs from the board.
- **Phase 3 — Teams daemon-side ✅** (+ adversarial-review hardening): HTTP endpoint
  (`/enqueue` + `/callback/key` BOTH secret-guarded with `hmac.compare_digest`, fail-closed;
  `/health`), `teams.py` cards + post-to-flow (failure path scrubs the signed URL),
  `dispatcher.py` (claude -p intent parse, strict no-tools: `--tools "" --strict-mcp-config`
  + scrubbed env; untrusted output type-guarded), `teams_consumer.py` (polls `teams_inbox`,
  confirm-before-spend gate is exact-`True`, poison rows dead-letter via `attempts`/`last_error`
  after `teams_inbox_max_attempts`, network/parse done outside DB txns). Orchestrator `claude -p`
  also moved to allowlist + `--strict-mcp-config` (rep) / `--tools ""` (report). Migration 0003
  adds `teams_inbox.attempts`/`last_error`. User wires Power Automate flows.

- **Phase 4 — discovery ✅** (OpenRouter half): `daemon/discovery.py` syncs OpenRouter
  `/models` (idempotent upsert, `last_seen`), detects new models (fresh-insert join), applies
  the relevance pre-filter (text modality, ≥`relevance_min_context`, optional price cap),
  dedups via `candidates` (rejected stays rejected), and posts Benchmark/Skip cards. First sync
  is a baseline (no flood). Retirement = sync-diff on lagging `last_seen`, alerting only for
  benchmarked/baseline models, deduped via a run_logs `retirement` event (writes verified, but
  **dormant in real data** until `model_aliases` bridges the `google/…` vs `gemini/…` slug
  namespaces in phase 5). Wired into the nightly scheduler (discovery → drift, serial).
  **Live catalog populated: 340 real models.** Foundry presence-check catalog is the remaining
  half — blocked on Azure creds.

- **Teams + admin console ✅ (this milestone):** Outbound Teams is LIVE — daemon → Power
  Automate "When a Teams webhook request is received" flow → adaptive card in a 1:1 Flow-bot
  chat (verified end-to-end). Inbound interactive cards need premium Power Automate (the HTTP +
  Postgres connectors are both premium), so the **admin Streamlit console** (`apps/admin/app.py`,
  loopback-only) is the human-in-the-loop surface: candidate queue with Benchmark/Skip, manual
  enqueue, masked key entry/revoke, trigger discovery sync, benchmark monitor + drill-down,
  baseline config, run logs. The daemon inbound code (`/inbox` route + consumer) is built,
  tested through ngrok, and waits ready for the day premium PA or a Graph app-registration lands.
  Migration 0004 allows `candidates.source='admin'`.

- **Web discovery radar ✅ (second source):** `daemon/web_discovery.py` — the ONLY web-enabled
  `claude -p` call (WebSearch+WebFetch), isolated via its own `mcp_server/discovery_server.py`
  (`kelp_disc`) + `--strict-mcp-config` so the web agent can't reach the key-bearing eval tools.
  Identity resolution (`common/identity.py` slugify+normkey) dedups across candidates →
  `model_aliases` → OpenRouter (exact-normkey → writes an alias bridge, first use of that table);
  novel → `candidate(source='web')` + `discovered_models` intel row (migration 0005). Runs nightly
  (Sonnet), admin Discovery tab shows intel + Benchmark/Skip + "Run web discovery now". Eval/judge/
  report/dispatcher no-web hardening untouched (regression-tested).

- **Worker loop ✅:** `daemon/worker.py` — single serial worker polls `candidates(status='queued')`,
  atomically claims one (queued→running, `repo.claim_queued_candidate`), resolves provider/route,
  runs every on-disk use case via `run_benchmark` + `run_report`, sets done/failed (or `pending`
  + a key-request card when the provider has no key), posts a Teams summary. Closes the loop:
  admin/Teams "Benchmark" → queued → auto-run. Provider resolution is naive v1 (vendor/model split
  + key check); phase 5 replaces it. Verified end-to-end (mock run: queued→done→benchmark+report).

- **Phase 5 — provider resolution ✅ (native/HF half):** `daemon/resolver.py::resolve_candidate`
  resolves a slug in ANY namespace form to `{status, provider, model, route}`: model_aliases
  bridge → `VENDOR_TO_PROVIDER` map (OpenRouter `google/…`→`gemini`, `moonshotai`→`moonshot`, …)
  → stored-key match (bare slug == a key's provider or configured model — fixes the
  `gemini-2.5-flash-lite` no-prefix bug) → pending (known provider, needs key) vs deferred
  (unroutable). Worker uses it (native→run, pending→key card, deferred→alert). All gemini forms
  resolve to the one key. Foundry presence-check + a claude -p reconcile for unknown vendors are
  the remaining Phase-5 follow-ups (Foundry needs Azure creds).

## Next
- **Foundry presence-check** (Phase 5 remainder) — needs Azure creds; slots into `resolve_candidate`
  before the native route.
- **EnrichList use case** — drop in the real `usecases/enrichlist/{enrichlist.md,golden.jsonl}`
  to replace the synthetic fixture (blocked on the files).
- **Robustness/ops** — stale-`running` reset, retry/backoff on rate limits. (Worker heartbeat ✅:
  `daemon_status` table, worker beats on a daemon thread, admin shows a live **Worker** tile;
  the old "Daemon HTTP" tile is relabeled "HTTP (Teams inbound)" — it's the optional inbound server.)

## Run commands (from repo root; `.env` has DATABASE_URL)
- Tests: `uv run pytest -q`
- Migrate: `uv run alembic -c db/alembic.ini upgrade head`
- Benchmark: `uv run python -m daemon.orchestrator --use-case fixture_qa --slug gemini/gemini-2.5-flash-lite --provider gemini --model gemini-2.5-flash-lite --reps 3 --report`
- Drift: `uv run python -m daemon.drift_runner --use-case fixture_qa`
- Discovery sync: `uv run python -m daemon.discovery` (live) · `--fixture <json>` (offline) · `--no-cards`
- Web discovery: `uv run python -m daemon.web_discovery --target 2 --max-turns 8 --no-cards` (claude -p WebSearch)
- Worker (runs the queue): `uv run python -m daemon.worker` · `--once` · `--once --mock`
- Scheduler: `uv run python -m daemon.scheduler --list`
- HTTP endpoint: `uv run python -m daemon.http_app`   ·   Consumer: `uv run python -m daemon.teams_consumer`
- Leaderboard (user): `uv run streamlit run apps/user/app.py`
- Admin console: `uv run streamlit run apps/admin/app.py --server.address 127.0.0.1`
- Teams test post: `uv run python -c "from daemon import teams; teams.post('summary','chat','test', card=teams.summary_card('m','uc',['hi']))"`

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
