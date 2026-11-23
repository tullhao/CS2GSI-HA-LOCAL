"""Kleiner HTTP-Server, der die Game-State-Daten von CS2 empfängt (nur auf 127.0.0.1)."""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

log = logging.getLogger(__name__)


class _Server(ThreadingHTTPServer):
    allow_reuse_address = False  # unter Windows sonst doppelt belegbar
    daemon_threads = True

    def __init__(self, addr, handler, token: str, on_payload: Callable[[dict], None]):
        super().__init__(addr, handler)
        self.token = token
        self.on_payload = on_payload


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", "0")
        self.end_headers()
        try:
            data = json.loads(body.decode("utf-8"))
        except ValueError:
            return
        if not isinstance(data, dict):
            return
        token = (data.get("auth") or {}).get("token")
        if self.server.token and token != self.server.token:
            return
        try:
            self.server.on_payload(data)
        except Exception:  # noqa: BLE001
            log.exception("Fehler beim Verarbeiten der GSI-Daten")

    def log_message(self, *args):  # Konsole sauber halten
        pass


class GSIServer:
    def __init__(self, token: str, on_payload: Callable[[dict], None]):
        self.token = token
        self.on_payload = on_payload
        self.port: int | None = None
        self._server: _Server | None = None

    def start(self, preferred_port: int, tries: int = 10) -> int:
        last_error: OSError | None = None
        for port in range(preferred_port, preferred_port + tries):
            try:
                self._server = _Server(("127.0.0.1", port), _Handler, self.token, self.on_payload)
            except OSError as exc:
                last_error = exc
                continue
            self.port = port
            threading.Thread(target=self._server.serve_forever, name="gsi", daemon=True).start()
            log.info("GSI-Server läuft auf Port %s", port)
            return port
        raise OSError(f"Kein freier Port ab {preferred_port}: {last_error}")

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
