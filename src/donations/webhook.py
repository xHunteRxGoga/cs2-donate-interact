from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlparse

from src.donations.models import Donation


class WebhookServer:
    def __init__(self, on_donation: Callable[[Donation], None], on_status: Callable[[str], None]) -> None:
        self.on_donation = on_donation
        self.on_status = on_status
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self, host: str, port: int) -> None:
        self.stop()
        handler_on_donation = self.on_donation

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                if path not in {"/donate", "/donation", "/"}:
                    self.send_response(404)
                    self.end_headers()
                    return
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    body = json.loads(raw.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    self.send_response(400)
                    self.end_headers()
                    return
                donation = Donation(
                    username=str(body.get("username") or "Тест"),
                    amount=float(body.get("amount") or 0),
                    currency=str(body.get("currency") or "RUB"),
                    message=str(body.get("message") or ""),
                    source="webhook",
                )
                handler_on_donation(donation)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

            def do_GET(self) -> None:  # noqa: N802
                query = parse_qs(urlparse(self.path).query)
                if "amount" in query:
                    handler_on_donation(
                        Donation(
                            username=query.get("username", ["Тест"])[0],
                            amount=float(query["amount"][0]),
                            currency=query.get("currency", ["RUB"])[0],
                            message=query.get("message", [""])[0],
                            source="webhook",
                        )
                    )
                    body = b'{"ok":true}'
                else:
                    body = (
                        b"CS2 Donate Interact webhook. "
                        b"POST /donate {\"amount\":100,\"username\":\"test\"}"
                    )
                self.send_response(200)
                self.send_header("Content-Type", "application/json" if b"{" in body else "text/plain")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args) -> None:
                return

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="webhook", daemon=True)
        self._thread.start()
        self.on_status(f"Локальный тест: http://{host}:{port}/donate")

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
