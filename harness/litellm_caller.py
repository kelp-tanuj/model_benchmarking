"""litellm-backed CandidateCaller — the real measured call.

Times a genuine HTTP round-trip and reports measured numbers off the response. NO tools are
ever passed (no web search). The key is read from the key store and handed to litellm; it
never enters a `claude -p` prompt.

Cost: for the POC we use litellm's cost map when available; the plan's OpenRouter-catalog-first
ordering is wired in once the catalog is synced (phase 4). Cost is None ("unavailable") rather
than fabricated when no price is known.
"""

from __future__ import annotations

import time
from typing import Any

import litellm

from common.keys import get_key, get_model
from harness.types import MeasuredResult


class LiteLLMCandidateCaller:
    def __init__(
        self,
        provider: str,
        model: str | None = None,
        temperature: float = 0.0,
        api_key: str | None = None,
    ):
        self.provider = provider
        self.model = model or get_model(provider)
        if not self.model:
            raise ValueError(f"no model configured for provider {provider!r}")
        self.temperature = temperature
        self._api_key = api_key or get_key(provider)
        if not self._api_key:
            raise ValueError(f"no API key stored for provider {provider!r}")

    def _model_str(self) -> str:
        return self.model if "/" in self.model else f"{self.provider}/{self.model}"

    def call(self, input_id: str, request: dict) -> MeasuredResult:
        messages = request["messages"]
        temperature = request.get("temperature", self.temperature)

        t0 = time.perf_counter()
        resp = litellm.completion(
            model=self._model_str(),
            messages=messages,
            temperature=temperature,
            api_key=self._api_key,
            # No `tools` — plain completion only (no web search).
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0

        output = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        tokens_in = getattr(usage, "prompt_tokens", None) if usage else None
        tokens_out = getattr(usage, "completion_tokens", None) if usage else None

        cost: float | None
        try:
            cost = litellm.completion_cost(completion_response=resp)
        except Exception:
            cost = None  # "cost unavailable" — never fabricated

        return MeasuredResult(
            output=output,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=cost,
            call_breakdown=[
                {"step": "completion", "latency_ms": latency_ms,
                 "tokens_in": tokens_in, "tokens_out": tokens_out, "cost": cost}
            ],
        )

    @staticmethod
    def build_request(prompt_template: str, input_obj: dict, temperature: float) -> dict:
        """Render the use-case prompt template with the golden input → a messages request.

        Built by code (not the agent) so prompt + temperature stay fixed for reproducibility.
        """
        content = prompt_template.format(**input_obj)
        return {"messages": [{"role": "user", "content": content}], "temperature": temperature}
