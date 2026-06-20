"""CandidateCaller implementations.

The real adapters (litellm / openai lib / provider SDK) do a timed HTTP round-trip and
report measured numbers; they're added when a provider key + route are available. The mock
here returns canned data so the whole loop, idempotent writes, and aggregation can be tested
offline in CI — no provider keys, no subscription cap.
"""

from __future__ import annotations

from collections.abc import Mapping

from harness.types import MeasuredResult


class MockCandidateCaller:
    """Returns canned MeasuredResults keyed by input_id. For tests + the synthetic fixture."""

    def __init__(self, canned: Mapping[str, MeasuredResult]):
        self._canned = dict(canned)

    def call(self, input_id: str, request: dict) -> MeasuredResult:
        if input_id not in self._canned:
            raise KeyError(f"MockCandidateCaller has no canned result for input_id={input_id!r}")
        return self._canned[input_id]
