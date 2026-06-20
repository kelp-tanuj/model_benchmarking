"""Daemon HTTP endpoint (control + key ingest).

Bind to 127.0.0.1. Only /callback/key is meant to be exposed via a dev tunnel, and it requires
a shared-secret header because the tunnel exposes it. Request bodies are NEVER logged (they can
contain a key), and the key value is never echoed back.

Routes:
  GET  /health           -> {"status": "ok"}
  POST /enqueue          -> {model, source?, decided_by?}  -> candidate(queued)
  POST /callback/key     -> {provider, key, model?} + header X-Kelp-Secret  -> keys.json
"""

from __future__ import annotations

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

    def _read_json(self) -> dict | None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > _MAX_BODY:
            self._send(413, {"error": "payload too large"})
            return None
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid json"})
            return None

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path == "/enqueue":
            data = self._read_json()
            if data is None:
                return
            slug = data.get("model")
            if not slug:
                self._send(400, {"error": "model required"})
                return
            with connect() as c:
                repo.upsert_candidate(
                    c, slug=slug, source=data.get("source", "teams"), status="queued",
                    decided_by=data.get("decided_by"),
                )
            self._send(200, {"queued": slug})

        elif self.path == "/callback/key":
            # Shared-secret guard (the tunnel exposes this route). Closed until configured.
            secret = self.headers.get("X-Kelp-Secret")
            if not settings.key_ingest_secret or secret != settings.key_ingest_secret:
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
        else:
            self._send(404, {"error": "not found"})


def serve() -> None:
    srv = ThreadingHTTPServer((settings.http_host, settings.http_port), Handler)
    print(f"[http] listening on {settings.http_host}:{settings.http_port}")
    srv.serve_forever()


if __name__ == "__main__":
    serve()
