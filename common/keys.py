"""Provider key store — the single indirection point for secrets (decision: keys.json now,
Key Vault later is a one-function swap).

keys.json schema:  { "<provider>": {"key": str, "model": str|None,
                                    "created": iso, "last_used": iso|null, "expiry": iso|null} }

The key value is NEVER logged, never passed on a CLI arg, and never placed in a `claude -p`
prompt. The measured-call layer injects it into the candidate subprocess env at call time.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from common.config import settings

# The key store is mutated from the ThreadingHTTPServer (/callback/key) and read elsewhere.
# Serialize every read-modify-write so two concurrent ingests can't clobber the file.
_LOCK = threading.RLock()


def _path() -> Path:
    return Path(settings.keys_path)


def _load() -> dict:
    p = _path()
    if not p.exists():
        return {}
    return json.loads(p.read_text() or "{}")


def _save(data: dict) -> None:
    """Crash-atomic write: temp file in the same dir (mode 600), then os.replace()."""
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".keys-", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)  # owner read/write only, before any bytes hit disk
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, p)  # atomic on POSIX; never leaves a truncated keys.json
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_key(provider: str) -> str | None:
    """Return the stored key for a provider, or None. Updates last_used as a side effect."""
    with _LOCK:
        data = _load()
        entry = data.get(provider)
        if not entry:
            return None
        entry["last_used"] = _now()
        _save(data)
        return entry["key"]


def get_model(provider: str) -> str | None:
    return (_load().get(provider) or {}).get("model")


def set_key(provider: str, key: str, model: str | None = None, expiry: str | None = None) -> None:
    with _LOCK:
        data = _load()
        existing = data.get(provider, {})
        data[provider] = {
            "key": key,
            "model": model if model is not None else existing.get("model"),
            "created": existing.get("created", _now()),
            "last_used": existing.get("last_used"),
            "expiry": expiry if expiry is not None else existing.get("expiry"),
        }
        _save(data)


def revoke(provider: str) -> bool:
    with _LOCK:
        data = _load()
        if provider in data:
            del data[provider]
            _save(data)
            return True
        return False


def is_expired(provider: str) -> bool:
    entry = _load().get(provider)
    if not entry or not entry.get("expiry"):
        return False
    return datetime.fromisoformat(entry["expiry"]) < datetime.now(timezone.utc)


def list_providers() -> list[dict]:
    """Non-secret metadata for the admin UI (no key values)."""
    return [
        {"provider": p, "model": e.get("model"), "created": e.get("created"),
         "last_used": e.get("last_used"), "expiry": e.get("expiry")}
        for p, e in _load().items()
    ]


def _cli() -> None:
    """Masked key entry from the terminal: `uv run python -m common.keys set <provider>`."""
    import getpass
    import sys

    args = sys.argv[1:]
    if args and args[0] == "set-file" and len(args) >= 3:
        # set-file <provider> <path-to-keyfile> [model]
        # The key lives only in a local file the user creates; it never enters the transcript.
        provider, path = args[1], args[2]
        model = args[3] if len(args) >= 4 else None
        from pathlib import Path as _P

        key = _P(path).read_text().strip()
        if not key:
            print(f"Key file {path!r} is empty; aborting.")
            return
        set_key(provider, key, model=model)
        print(
            f"Stored key for '{provider}' (model={model}) in {settings.keys_path} (mode 600). "
            f"Now delete the key file: rm -f {path}"
        )
    elif len(args) >= 2 and args[0] == "set":
        provider = args[1]
        # Prefer a hidden prompt; fall back to stdin when there's no TTY (e.g. piped input).
        if sys.stdin.isatty():
            key = getpass.getpass(f"Paste the API key for '{provider}' (input hidden): ").strip()
            model = input(f"Default model id for '{provider}' (optional, Enter to skip): ").strip()
        else:
            key = sys.stdin.readline().strip()
            model = ""
        if not key:
            print("No key entered; aborting.")
            return
        set_key(provider, key, model=model or None)
        print(f"Stored key for '{provider}' in {settings.keys_path} (mode 600).")
    elif len(args) >= 1 and args[0] == "list":
        for row in list_providers():
            print(row)
    elif len(args) >= 2 and args[0] == "revoke":
        print("revoked" if revoke(args[1]) else "no such provider")
    else:
        print("usage: python -m common.keys [set <provider> | list | revoke <provider>]")


if __name__ == "__main__":
    _cli()
