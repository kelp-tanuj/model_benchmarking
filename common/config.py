"""Central configuration (env / .env driven). No secrets are hard-coded here.

DATABASE_URL and the key-ingest shared secret come from the environment or a gitignored
`.env`. Provider API keys do NOT live here — they're in `keys.json` via `common.keys`.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Database (Neon Postgres) ---
    database_url: str | None = None

    # --- Judge ---
    judge_model: str = "claude-opus-4-8"  # pinned; recorded per benchmark
    n_reps_default: int = 3

    # --- Scheduling (off-hours window for discovery/drift) ---
    offhours_start: str = "01:00"
    offhours_end: str = "05:00"
    timezone: str = "UTC"

    # --- Relevance pre-filter (discovery) ---
    relevance_require_text: bool = True
    relevance_min_context: int = 8000
    relevance_max_price_prompt: float | None = None  # off by default

    # --- Web discovery radar (claude -p web research; runs nightly) ---
    web_discovery_enabled: bool = True
    web_discovery_model: str = "claude-sonnet-4-6"  # balanced quota vs research quality
    web_discovery_target: int = 10                  # max new models recorded per run (hard cap)
    web_discovery_max_turns: int = 40
    web_discovery_timeout: int = 1200
    web_discovery_window_days: int = 14

    # --- Secrets plumbing ---
    keys_path: str = "keys.json"
    key_ingest_secret: str | None = None  # guards the dev-tunnel key-ingest route

    # --- Teams (Power Automate Workflows) ---
    teams_post_flow_url: str | None = None  # outbound: informational cards (fire-and-forget)
    teams_card_flow_url: str | None = None  # outbound: interactive cards (post-and-wait -> /inbox)
    http_host: str = "127.0.0.1"
    http_port: int = 8765
    teams_poll_seconds: int = 10
    teams_inbox_max_attempts: int = 5  # dead-letter an inbox row after this many transient failures


settings = Settings()
