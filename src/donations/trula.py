from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Callable
from urllib.parse import urlparse

import httpx
import websockets

from src.donations.linkstate import LinkState
from src.donations.models import Donation
from src.donations.parse import donation_from_payload, extract_token, iter_donation_dicts, unwrap_payload


TRULA_EVENTS = "https://trula.io/api/v1/widget/panel/events"
TRULA_ORDERS = "https://trula.io/api/v1/widget/panel/orders"
TRULA_PANEL = "https://trula.io/api/v1/widget/panel/"
TRULA_WS = "wss://trula.io/api/v1/widget/panel/{token}"


class _GenStop:
    def __init__(self, client: "TrulaClient", gen: int) -> None:
        self.client = client
        self.gen = gen

    def is_set(self) -> bool:
        return self.client._stop.is_set() or (self.gen and self.client._generation != self.gen)


class TrulaClient:
    def __init__(self, on_donation: Callable[[Donation], None], on_status: Callable[[str], None]) -> None:
        self.on_donation = on_donation
        self.on_status = on_status
        self._stop = threading.Event()
        self._seen: set[str] = set()
        self.widget = ""
        self.connected = False
        self._generation = 0
        self._last_notes: dict[str, float] = {}
        self.link = LinkState("Trula")

    def _note(self, text: str, every: float = 35.0) -> None:
        now = time.monotonic()
        key = text[:90]
        if now - self._last_notes.get(key, 0) < every:
            return
        self._last_notes[key] = now
        self.on_status(text)

    def start(self, widget: str) -> None:
        self._generation += 1
        gen = self._generation
        self._stop.set()
        self.widget = (widget or "").strip()
        self.connected = False
        if not self.widget:
            self.link.set("off", "не привязана — вставь ссылку панели /cp/?token=… или OBS-виджет")
            self.on_status("Trula: нет ссылки. Вставь ссылку и нажми «Сохранить и проверить связь».")
            return
        low = self.widget.lower()
        if "/dp/" in low and "/cp/" not in low:
            self.on_status("Trula: это страница доната /dp/.... Лучше ссылка панели https://trula.io/cp/?token=…")
        self.link.set("wait", "подключаюсь к панели Trula…")
        self._stop.clear()
        threading.Thread(target=self._run, args=(gen,), name="trula", daemon=True).start()

    def stop(self) -> None:
        self._generation += 1
        self._stop.set()
        self.connected = False
        self.link.set("off", "остановлена")

    def _alive(self, gen: int) -> bool:
        return (not self._stop.is_set()) and gen == self._generation

    def _run(self, gen: int = 0) -> None:
        if gen and gen != self._generation:
            return
        try:
            asyncio.run(self._main(gen))
        except Exception as exc:
            if gen == self._generation:
                self.link.set("bad", f"ошибка Trula: {exc}")
                self.on_status(f"Trula ошибка: {exc}")

    async def _main(self, gen: int) -> None:
        token = extract_token(self.widget)
        if not token:
            self.link.set("bad", "в ссылке нет token=")
            self.on_status("Trula: в ссылке нет token=. Нужна ссылка вида https://trula.io/cp/?token=…")
            return
        headers = {"token": token, "Accept": "application/json", "Origin": "https://trula.io"}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            try:
                resp = await client.get(TRULA_PANEL, headers=headers)
                if resp.status_code >= 400:
                    self.link.set("bad", f"панель Trula ответила {resp.status_code} — неверный token")
                    self.on_status(f"Trula: панель не открылась ({resp.status_code}). Это не тот token.")
                    return
            except Exception as exc:
                self.link.set("bad", f"не достучался до Trula ({exc})")
                self.on_status(f"Trula: не достучался до API ({exc})")
                return
        self.connected = True
        self.link.set("live", "панель Trula открыта, жду донаты")
        self.on_status("Trula: панель подключена, слушаю события")
        stop = _GenStop(self, gen)
        await asyncio.gather(
            self._poll_events(token, gen),
            self._listen_ws(token, stop),
            return_exceptions=True,
        )

    async def _poll_events(self, token: str, gen: int) -> None:
        headers = {"token": token, "Accept": "application/json", "Origin": "https://trula.io"}
        bootstrap = True
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            while self._alive(gen):
                try:
                    resp = await client.get(TRULA_EVENTS, headers=headers)
                    if resp.status_code < 400:
                        payload = resp.json()
                        rows = payload.get("data") if isinstance(payload, dict) else payload
                        if not isinstance(rows, list):
                            rows = iter_donation_dicts(payload)
                        self.connected = True
                        if self.link.state != "live":
                            self.link.set("live", "опрос событий Trula работает")
                        for row in rows or []:
                            if not isinstance(row, dict):
                                continue
                            marker = str(row.get("id") or "")
                            if bootstrap:
                                if marker:
                                    self._seen.add(marker)
                                continue
                            self._emit(row)
                        bootstrap = False
                    else:
                        self._note(f"Trula events HTTP {resp.status_code}")
                except Exception as exc:
                    self._note(f"Trula опрос: {exc}")
                await asyncio.sleep(3)

    async def _listen_ws(self, token: str, stop: _GenStop) -> None:
        url = TRULA_WS.format(token=token)
        headers = {"token": token, "Origin": "https://trula.io"}
        while not stop.is_set():
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    additional_headers=headers,
                    open_timeout=8,
                ) as ws:
                    self.connected = True
                    self.link.set("live", "сокет Trula подключен, жду донаты")
                    self.on_status(f"Trula: WebSocket {url.split(token)[0]}…")
                    while not stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        except asyncio.TimeoutError:
                            continue
                        payload = unwrap_payload(raw)
                        if payload is None:
                            continue
                        rows = iter_donation_dicts(payload)
                        if not rows and isinstance(payload, dict):
                            rows = [payload]
                        for row in rows:
                            self._emit(row)
            except Exception as exc:
                self._note(f"Trula WS: {exc}")
            if stop.is_set():
                return
            await asyncio.sleep(4)

    def _emit(self, payload: dict) -> None:
        item = donation_from_payload(payload, "trula")
        if item is None:
            if str(payload.get("type") or "").lower() not in {"donate", "donation", ""}:
                return
            self._note(f"Trula: пакет без суммы {str(payload)[:180]}")
            return
        if item.donation_id:
            if item.donation_id in self._seen:
                return
            self._seen.add(item.donation_id)
            if len(self._seen) > 4000:
                self._seen = set(list(self._seen)[-2000:])
        self.connected = True
        self.link.mark_donation(item.username, item.amount, item.currency)
        self.on_donation(item)
