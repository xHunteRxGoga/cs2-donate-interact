from __future__ import annotations

import asyncio
import re
import threading
import time
from typing import Callable

import httpx

from src.donations.centrifuge_json import CentrifugeJSON
from src.donations.models import Donation
from src.donations.parse import donation_from_payload, extract_token, iter_donation_dicts, parse_amount
from src.donations.linkstate import LinkState


DP_API = "https://donatepay.ru/api/v1"
DP_WIDGET = "https://widget.donatepay.ru/alert-box/widget/{}"
DP_SOCKET_TOKEN = "https://widget.donatepay.ru/socket/token"
DP_SOCKETS = (
    "wss://widget.donatepay.ru/connection/websocket",
    "wss://centrifugo.donatepay.ru/connection/websocket",
    "wss://136.243.1.101:3002/connection/websocket",
    "ws://136.243.1.101:3002/connection/websocket",
)

_SUCCESS = {"", "success", "1", "ok", "paid", "done", "true"}
_SKIP_TYPES = {"media", "music", "follow", "subscription", "subscriber", "raid", "host", "cheer", "sticker"}


class DonatePayClient:
    def __init__(self, on_donation: Callable[[Donation], None], on_status: Callable[[str], None]) -> None:
        self.on_donation = on_donation
        self.on_status = on_status
        self._stop = threading.Event()
        self.api_token = ""
        self.widget_token = ""
        self.poll_interval_sec = 8.0
        self.currency = "RUB"
        self.connected = False
        self._seen: set[str] = set()
        self._generation = 0
        self._last_notes: dict[str, float] = {}
        self.link = LinkState("DonatePay")

    def _note(self, text: str, every: float = 40.0) -> None:
        now = time.monotonic()
        key = text[:80]
        if now - self._last_notes.get(key, 0) < every:
            return
        self._last_notes[key] = now
        self.on_status(text)

    def start(
        self,
        api_token: str = "",
        poll_interval_sec: float = 8.0,
        currency: str = "RUB",
        widget_token: str = "",
    ) -> None:
        self._generation += 1
        gen = self._generation
        self._stop.set()
        raw_api = api_token or ""
        raw_widget = widget_token or ""
        self.widget_token = extract_token(raw_widget)
        self.api_token = extract_token(raw_api)
        if "widget.donatepay" in raw_api.lower() or "alert-box" in raw_api.lower() or raw_api.strip().startswith("http"):
            self.widget_token = self.widget_token or extract_token(raw_api)
            self.api_token = ""
            self.on_status("DonatePay: в поле API была ссылка виджета — слушаю виджет, API не трогаю")
        self.poll_interval_sec = max(8.0, float(poll_interval_sec or 8)) if self.api_token else max(5.0, float(poll_interval_sec or 8))
        self.currency = currency or "RUB"
        self.connected = False
        if not self.api_token and not self.widget_token:
            self.link.set("off", "не привязан — нужны API-ключ и ссылка виджета")
            self.on_status("DonatePay: нет API-ключа и токена виджета. Вставь оба и нажми «Сохранить и проверить связь».")
            return
        self.link.set("wait", "подключаюсь к DonatePay…")
        self._stop.clear()
        self._seen.clear()
        threading.Thread(target=self._run, args=(gen,), name="donatepay", daemon=True).start()

    def stop(self) -> None:
        self._generation += 1
        self._stop.set()
        self.connected = False
        self.link.set("off", "остановлен")

    def _run(self, gen: int) -> None:
        if gen != self._generation:
            return
        try:
            asyncio.run(self._main(gen))
        except Exception as exc:
            if gen == self._generation:
                self.on_status(f"DonatePay ошибка: {exc}")

    def _alive(self, gen: int) -> bool:
        return (not self._stop.is_set()) and gen == self._generation

    async def _nap(self, seconds: float, gen: int) -> bool:
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            if not self._alive(gen):
                return False
            await asyncio.sleep(0.25)
        return self._alive(gen)

    async def _main(self, gen: int) -> None:
        tasks = []
        if self.api_token:
            tasks.append(asyncio.create_task(self._poll_loop(gen)))
        if self.widget_token:
            tasks.append(asyncio.create_task(self._widget_loop(gen)))
            tasks.append(asyncio.create_task(self._widget_poll(gen)))
        if not tasks:
            return
        await asyncio.gather(*tasks)

    async def _poll_loop(self, gen: int) -> None:
        params = {
            "access_token": self.api_token,
            "limit": 25,
            "type": "donation",
            "status": "success",
        }
        bootstrap = True
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                user = (await client.get(f"{DP_API}/user", params={"access_token": self.api_token})).json()
                message = str(user.get("message") or user.get("status") or "")
                if "incorrect" in message.lower() or str(user.get("status") or "").lower() not in {"success", "ok", "1"}:
                    self.on_status(
                        "DonatePay: это не API-ключ. Вставь ключ со страницы donatepay.ru/page/api. "
                        "Ссылку виджета — в соседнее поле."
                    )
                    self.link.set("bad", "в поле API не ключ, а что-то другое")
                    if not self.widget_token:
                        self.widget_token = self.api_token
                        await self._widget_loop(gen)
                    return
                name = (user.get("data") or {}).get("name") or (user.get("data") or {}).get("id") or "стример"
                self.on_status(f"DonatePay: вход как {name}, опрос раз в {self.poll_interval_sec:.0f} сек")
                self.connected = True
                self.link.set("live", f"API подключен как {name}")
            except Exception as exc:
                self._note(f"DonatePay: не удалось проверить токен ({exc}), пробую опрос донатов")

            while self._alive(gen):
                try:
                    resp = await client.get(f"{DP_API}/transactions", params=params)
                    if resp.status_code == 429:
                        self._note("DonatePay API: слишком часто, жду 45 сек")
                        if not await self._nap(45, gen):
                            return
                        continue
                    resp.raise_for_status()
                    payload = resp.json()
                    status = str(payload.get("status") or "").lower()
                    if status not in {"", "success", "ok", "1"}:
                        self._note(f"DonatePay API: {payload.get('message') or payload.get('status')}")
                        if "incorrect" in str(payload.get("message") or "").lower():
                            return
                    rows = payload.get("data") or payload.get("transactions") or []
                    if isinstance(rows, dict):
                        rows = rows.get("data") or []
                    for row in rows:
                        self._handle_row(row, bootstrap, "donatepay-poll")
                    bootstrap = False
                    self.connected = True
                except Exception as exc:
                    text = str(exc)
                    if "429" in text:
                        self._note("DonatePay API: лимит запросов, жду 45 сек")
                        if not await self._nap(45, gen):
                            return
                        continue
                    self._note(f"DonatePay опрос: {exc}")
                if not await self._nap(self.poll_interval_sec, gen):
                    return

    async def _widget_loop(self, gen: int) -> None:
        while self._alive(gen):
            try:
                await self._listen_widget_once()
            except Exception as exc:
                self._note(f"DonatePay виджет: {exc}")
            if not self._alive(gen):
                return
            self._note("DonatePay виджет: переподключение через 6 сек")
            if not await self._nap(6, gen):
                return

    async def _widget_poll(self, gen: int) -> None:
        urls = [
            DP_WIDGET.format(self.widget_token),
            f"https://widget.donatepay.ru/alert-box/data/{self.widget_token}",
            f"https://donatepay.ru/api/v1/notifications?access_token={self.widget_token}",
        ]
        bootstrap: dict[str, set[str]] = {}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            while self._alive(gen):
                for url in urls:
                    try:
                        resp = await client.get(url, headers={"Accept": "application/json, text/html"})
                        if resp.status_code >= 400:
                            continue
                        try:
                            payload = resp.json()
                        except Exception:
                            payload = None
                        rows = iter_donation_dicts(payload) if payload is not None else []
                        first = url not in bootstrap
                        seen = bootstrap.setdefault(url, set())
                        for row in rows:
                            marker = str(row.get("id") or row.get("donation_id") or "") or str(row)[:120]
                            if marker in seen:
                                continue
                            seen.add(marker)
                            if first:
                                continue
                            self._handle_row(row, bootstrap=False, source="donatepay-widget-poll")
                    except Exception:
                        continue
                if not await self._nap(5, gen):
                    return

    async def _listen_widget_once(self) -> None:
        token = self.widget_token
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            html = (await client.get(DP_WIDGET.format(token))).text
            user_id = _extract_user_id(html)
            csrf = _extract_csrf(html)
            sockets = re.findall(r"wss?://[a-zA-Z0-9._:/-]+", html)
            auth = {}
            if csrf:
                resp = await client.post(DP_SOCKET_TOKEN, data={"token": token, "_token": csrf})
                try:
                    auth = resp.json()
                except Exception:
                    auth = {}
            if not auth.get("token"):
                resp = await client.post(DP_SOCKET_TOKEN, json={"token": token, "_token": csrf})
                try:
                    auth = resp.json() if not auth.get("token") else auth
                except Exception:
                    pass
        if not user_id:
            self.link.set("bad", "не та ссылка виджета — скопируй из «Оповещения», widget.donatepay.ru/alert-box/widget/…")
            raise RuntimeError("не удалось прочитать userId из виджета — нужна ссылка из «Оповещения»")
        socket_token = str(auth.get("token") or auth.get("socket_token") or "")
        timestamp = str(auth.get("time") or auth.get("timestamp") or "")
        channel = f"notifications#{user_id}"
        hosts = list(dict.fromkeys([*sockets, *DP_SOCKETS]))
        last_error: Exception | None = None
        def status(msg: str) -> None:
            if "subscribed" in msg.lower():
                self.connected = True
                self.link.set("live", "виджет подписан, жду донаты")
            self.on_status(msg)

        centrifuge = CentrifugeJSON(self._on_publication, status)
        for url in hosts:
            if self._stop.is_set():
                return
            try:
                if socket_token and timestamp:
                    await centrifuge.listen_v1(
                        url,
                        user=str(user_id),
                        timestamp=timestamp,
                        token=socket_token,
                        channel=channel,
                        stop_event=self._stop,
                        label="DonatePay",
                    )
                    return
                if socket_token:
                    await centrifuge.listen_v2(
                        url,
                        token=socket_token,
                        channel=channel,
                        stop_event=self._stop,
                        label="DonatePay",
                    )
                    return
            except Exception as exc:
                last_error = exc
        raise RuntimeError(last_error or "нет сокета DonatePay")

    def _on_publication(self, data: dict) -> None:
        self.connected = True
        if self.link.state != "live":
            self.link.set("live", "виджет подписан, жду донаты")
        rows = iter_donation_dicts(data)
        if not rows and isinstance(data.get("notification"), dict):
            rows = iter_donation_dicts(data["notification"])
        if not rows:
            vars_ = (data.get("notification") or {}).get("vars") if isinstance(data.get("notification"), dict) else None
            if isinstance(vars_, dict):
                rows = [vars_]
        for row in rows:
            self._handle_row(row, bootstrap=False, source="donatepay")

    def _handle_row(self, row: dict, bootstrap: bool, source: str) -> None:
        if not isinstance(row, dict):
            return
        vars_ = row.get("vars") if isinstance(row.get("vars"), dict) else {}
        status = str(row.get("status") or vars_.get("status") or "").lower()
        if status not in _SUCCESS:
            return
        dtype = str(row.get("type") or vars_.get("type") or "donation").lower()
        if dtype in _SKIP_TYPES:
            return
        donation_id = str(row.get("id") or row.get("donation_id") or "")
        if donation_id and donation_id in self._seen:
            return
        if donation_id:
            self._seen.add(donation_id)
            if len(self._seen) > 4000:
                self._seen = set(list(self._seen)[-2000:])
        if bootstrap:
            return
        vars_ = row.get("vars") if isinstance(row.get("vars"), dict) else {}
        merged = {**vars_, **row}
        item = donation_from_payload(merged, source)
        if item is None:
            amount = parse_amount(row.get("sum") or vars_.get("sum"))
            if amount <= 0:
                return
            item = Donation(
                username=str(vars_.get("name") or row.get("what") or row.get("name") or "Аноним"),
                amount=amount,
                currency=str(row.get("currency") or vars_.get("currency") or self.currency),
                message=str(row.get("comment") or vars_.get("comment") or ""),
                source=source,
                donation_id=donation_id,
            )
        self.connected = True
        self.link.mark_donation(item.username, item.amount, item.currency)
        self.on_donation(item)


def _extract_user_id(html: str) -> str:
    patterns = (
        r"function\s+getUserId\(\)\s*\{\s*return\s+parseInt\('(\d+)'",
        r"getUserId\(\)\s*\{\s*return\s+parseInt\('(\d+)'",
        r"userId['\"]?\s*[:=]\s*['\"]?(\d+)",
        r"user_id['\"]?\s*[:=]\s*['\"]?(\d+)",
        r"parseInt\('(\d+)'\)",
    )
    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match:
            return match.group(1)
    return ""


def _extract_csrf(html: str) -> str:
    patterns = (
        r"function\s+csrf\(\)\s*\{\s*return\s+'([^']+)'",
        r"csrf\(\)\s*\{\s*return\s+'([^']+)'",
        r"csrf-token['\"]?\s*content=['\"]([^'\"]+)",
        r"name=['\"]csrf-token['\"]\s+content=['\"]([^'\"]+)",
        r"_token['\"]?\s*[:=]\s*['\"]([^'\"]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match:
            return match.group(1)
    return ""
