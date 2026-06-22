"""Model identity helpers: turn a messy web-found name into a stable slug, and a normalized
match key for cross-namespace dedup (web ↔ candidates ledger ↔ OpenRouter catalog).

These are deliberately pure + deterministic so the dedup logic in the discovery MCP tool is
unit-testable without a DB. The slug mirrors the OpenRouter `vendor/model` convention so a
web-found slug is directly comparable to OpenRouter slugs.
"""

from __future__ import annotations

import re

# Role / packaging tokens that don't distinguish a model identity.
_DROP_TOKENS = {"instruct", "chat", "base", "it", "hf", "gguf", "preview", "latest"}
_SLUG_RE = re.compile(r"^[a-z0-9._-]+/[a-z0-9._-]+$")


def _slug_part(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9.]+", "-", s)   # keep dots (version numbers), everything else -> '-'
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def slugify(provider: str | None, name: str) -> str:
    """Build a stable `vendor/model` slug from provider + canonical name."""
    p = _slug_part(provider or "")
    n = _slug_part(name or "")
    return f"{p}/{n}" if p and n else (n or p)


def clean_suggested_slug(suggested: str | None) -> str | None:
    """Accept an agent-supplied slug only if it's `vendor/model`-shaped, re-slugified per half."""
    if not suggested or not isinstance(suggested, str):
        return None
    s = suggested.strip().lower()
    if not _SLUG_RE.match(s):
        return None
    vendor, model = s.split("/", 1)
    return slugify(vendor, model)


def normkey(s: str) -> str:
    """Normalized identity key for fuzzy cross-namespace matching.

    Drops the vendor prefix, splits on separators, removes role/packaging tokens, and strips
    to alphanumerics. e.g. 'google/gemini-2.5-flash-lite', 'Gemini 2.5 Flash Lite' -> 'gemini25flashlite'.
    """
    s = (s or "").lower()
    if "/" in s:
        s = s.rsplit("/", 1)[1]  # model part only
    tokens = [t for t in re.split(r"[\s\-_./]+", s) if t and t not in _DROP_TOKENS]
    return re.sub(r"[^a-z0-9]", "", "".join(tokens))
