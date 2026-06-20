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

    # --- Secrets plumbing ---
    keys_path: str = "keys.json"
    key_ingest_secret: str | None = None  # guards the dev-tunnel key-ingest route

    # --- Teams (Power Automate Workflows) ---
    teams_post_flow_url: str | None = None  # outbound: daemon POSTs cards to this flow
    http_host: str = "127.0.0.1"
    http_port: int = 8765
    teams_poll_seconds: int = 10
    teams_inbox_max_attempts: int = 5  # dead-letter an inbox row after this many transient failures


settings = Settings()
