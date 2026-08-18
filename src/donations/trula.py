from __future__ import annotations

import json
import re
import threading
import time
from typing import Callable
from urllib.parse import parse_qs, urlparse

import httpx

from src.donations.models import Donation


def extract_token(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if "://" in raw or "token=" in raw:
        query = parse_qs(urlparse(raw).query)
        for key in ("token", "api_token", "access_token", "key"):
            if query.get(key):
                return query[key][0].strip()
        path = urlparse(raw).path.rstrip("/").split("/")
        if path and path[-1] and path[-1] not in {"widget", "widgets", "alert", "alerts", "overlay"}:
            return path[-1]
    return raw


class TrulaClient:
    def __init__(self, on_donation: Callable[[Donation], None], on_status: Callable[[str], None]) -> None:
        self.on_donation = on_donation
        self.on_status = on_status
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sio = None
        self._seen: set[str] = set()
        self.widget = ""

    def start(self, widget: str) -> None:
        self.stop()
        self.widget = (widget or "").strip()
        if not self.widget:
            self.on_status("Trula: нет ссылки виджета или токена")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="trula", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._sio is not None:
            try:
                self._sio.disconnect()
            except Exception:
                pass
            self._sio = None

    def _run(self) -> None:
        token = extract_token(self.widget)
        page_url = self.widget if self.widget.startswith("http") else ""
        try:
            if page_url:
                self._inspect_widget_page(page_url)
            self._listen_socket(token)
        except Exception as exc:
            self.on_status(f"Trula ошибка: {exc}")

    def _inspect_widget_page(self, url: str) -> None:
        try:
            html = httpx.get(url, timeout=20, follow_redirects=True).text
        except Exception as exc:
            self.on_status(f"Trula: не открылась ссылка виджета ({exc})")
            return
        sockets = re.findall(r"wss://[a-zA-Z0-9._:/-]+", html)
        if sockets:
            self.on_status(f"Trula: в виджете найден сокет {sockets[0]}")

    def _listen_socket(self, token: str) -> None:
        try:
            import socketio
        except ImportError:
            self.on_status("Trula: установи зависимости через run.bat (нужен python-socketio)")
            return
        if not token:
            self.on_status("Trula: не удалось вытащить токен из ссылки")
            return

        sio = socketio.Client(reconnection=True, reconnection_delay=3, reconnection_delay_max=15)
        self._sio = sio

        @sio.event
        def connect() -> None:
            for payload in (
                {"token": token, "type": "alert_widget"},
                {"token": token},
                {"api_token": token},
            ):
                try:
                    sio.emit("add-user", payload)
                    sio.emit("subscribe", payload)
                    sio.emit("join", payload)
                except Exception:
                    continue
            self.on_status("Trula: сокет подключен, жду донаты")

        @sio.event
        def disconnect() -> None:
            if not self._stop.is_set():
                self.on_status("Trula: сокет отключился, переподключаюсь")

        def handle(data) -> None:
            self._emit_donation(data)

        for event_name in ("donation", "donate", "alert", "notification", "new_donation", "message"):
            sio.on(event_name, handle)

        @sio.on("*")
        def catch_all(event, data=None) -> None:
            if event in {"connect", "disconnect", "ping", "pong"}:
                return
            if data:
                self._emit_donation(data)

        hosts = [
            "https://trula.io",
            "wss://trula.io",
            "https://widget.trula.io",
            "https://ws.trula.io",
        ]
        last_error = None
        for host in hosts:
            if self._stop.is_set():
                return
            try:
                sio.connect(host, transports=["websocket"], wait_timeout=8)
                last_error = None
                break
            except Exception as exc:
                last_error = exc
        if last_error and not sio.connected:
            self.on_status(
                "Trula: не удалось подключить сокет. Проверь, что вставлена ссылка виджета алертов из кабинета Trula → Виджеты."
            )
            self.on_status(f"Trula подробности: {last_error}")
            return
        while not self._stop.is_set():
            time.sleep(0.2)
        try:
            sio.disconnect()
        except Exception:
            pass

    def _emit_donation(self, data) -> None:
        if isinstance(data, (list, tuple)) and data:
            data = data[0]
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return
        if not isinstance(data, dict):
            return
        payload = data.get("donation") or data.get("data") or data.get("vars") or data
        if not isinstance(payload, dict):
            return
        amount = payload.get("amount") or payload.get("sum") or payload.get("value")
        if amount is None:
            return
        donation_id = str(payload.get("id") or payload.get("donation_id") or "")
        if donation_id and donation_id in self._seen:
            return
        if donation_id:
            self._seen.add(donation_id)
        self.on_donation(
            Donation(
                username=str(payload.get("username") or payload.get("name") or payload.get("nickname") or "Аноним"),
                amount=float(amount),
                currency=str(payload.get("currency") or "RUB"),
                message=str(payload.get("message") or payload.get("comment") or payload.get("text") or ""),
                source="trula",
                donation_id=donation_id,
            )
        )
