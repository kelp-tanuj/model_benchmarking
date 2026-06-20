"""Daemon HTTP endpoint (control + key ingest).

Bind to 127.0.0.1. A dev tunnel forwards the WHOLE port (not one path), so every route must
defend itself: both /enqueue and /callback/key require the X-Kelp-Secret shared secret and fail
CLOSED when the secret is unset. Request bodies are NEVER logged (they can contain a key), and
the key value is never echoed back.

Routes:
  GET  /health           -> {"status": "ok"}                         (no secret)
  POST /enqueue          -> {model, source?, decided_by?}            -> candidate(queued)
  POST /callback/key     -> {provider, key, model?}                  -> keys.json
  POST /inbox            -> {kind, ...}  (Teams card/response data)  -> teams_inbox row
                            all POSTs require header X-Kelp-Secret
"""

from __future__ import annotations

import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from common import repo
from common.config import settings
from common.db import connect
from common.keys import set_key

_MAX_BODY = 64 * 1024


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # silence: never log bodies (may carry a key)
        pass

    def _authorized(self) -> bool:
        """Constant-time shared-secret check; fail closed when no secret is configured."""
        expected = settings.key_ingest_secret or ""
        if not expected:
            return False
        provided = self.headers.get("X-Kelp-Secret") or ""
        return hmac.compare_digest(provided.encode(), expected.encode())

    def _read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            self._send(400, {"error": "invalid content-length"})
            return None
        if length > _MAX_BODY:
            self._send(413, {"error": "payload too large"})
            return None
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid json"})
            return None
        if not isinstance(data, dict):
            self._send(400, {"error": "body must be a json object"})
            return None
        return data

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        try:
            if self.path == "/enqueue":
                if not self._authorized():
                    self._send(401, {"error": "unauthorized"})
                    return
                data = self._read_json()
                if data is None:
                    return
                slug = data.get("model")
                if not slug or not isinstance(slug, str):
                    self._send(400, {"error": "model required"})
                    return
                with connect() as c:
                    repo.upsert_candidate(
                        c, slug=slug, source=data.get("source", "teams"), status="queued",
                        decided_by=data.get("decided_by"),
                    )
                self._send(200, {"queued": slug})

            elif self.path == "/callback/key":
                if not self._authorized():
                    self._send(401, {"error": "unauthorized"})
                    return
                data = self._read_json()
                if data is None:
                    return
                provider, key = data.get("provider"), data.get("key")
                if not provider or not key:
                    self._send(400, {"error": "provider and key required"})
                    return
                set_key(provider, key, model=data.get("model"))
                self._send(200, {"stored": provider})  # never echo the key

            elif self.path == "/inbox":
                # Power Automate inbound: a card's Action.Submit data (or a free-text request)
                # lands here and becomes a teams_inbox row the consumer processes. The whole
                # body is the payload; `kind` selects the handler.
                if not self._authorized():
                    self._send(401, {"error": "unauthorized"})
                    return
                data = self._read_json()
                if data is None:
                    return
                kind = data.get("kind")
                if not kind or not isinstance(kind, str):
                    self._send(400, {"error": "kind required"})
                    return
                with connect() as c:
                    inbox_id = repo.add_teams_inbox(c, kind, data)
                self._send(200, {"inbox_id": inbox_id})
            else:
                self._send(404, {"error": "not found"})
        except Exception:
            # Always return JSON; never leak a traceback or partial body to the wire.
            try:
                self._send(500, {"error": "internal error"})
            except Exception:
                pass


def serve() -> None:
    if settings.http_host not in ("127.0.0.1", "localhost", "::1"):
        print(f"[http] WARNING: binding to non-loopback {settings.http_host!r}; both POST routes "
              "are secret-gated, but ensure KEY_INGEST_SECRET is strong.")
    srv = ThreadingHTTPServer((settings.http_host, settings.http_port), Handler)
    print(f"[http] listening on {settings.http_host}:{settings.http_port}")
    srv.serve_forever()


if __name__ == "__main__":
    serve()
