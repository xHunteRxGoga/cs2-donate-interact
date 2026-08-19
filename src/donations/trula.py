from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from typing import Callable
from urllib.parse import urljoin, urlparse

import httpx
import websockets

from src.donations.centrifuge_json import CentrifugeJSON
from src.donations.models import Donation
from src.donations.parse import (
    donation_from_payload,
    extract_token,
    iter_donation_dicts,
    payloads_from_html,
    unwrap_payload,
)
from src.donations.socketio_raw import RawSocketIO


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
            self.on_status("Trula: нет ссылки виджета. Нажми «Привязать аккаунт».")
            return
        low = self.widget.lower()
        if "/dp/" in low and not any(key in low for key in ("widget", "overlay", "alert", "obs")):
            self.on_status("Trula: это страница доната /dp/..., не OBS-виджет. Слушаю её как запасной вариант, но лучше вставить ссылку алерта из кабинета.")
        self._stop.clear()
        threading.Thread(target=self._run, args=(gen,), name="trula", daemon=True).start()

    def stop(self) -> None:
        self._generation += 1
        self._stop.set()
        self.connected = False

    def _alive(self, gen: int) -> bool:
        return (not self._stop.is_set()) and gen == self._generation

    def _run(self, gen: int = 0) -> None:
        if gen and gen != self._generation:
            return
        try:
            asyncio.run(self._main(gen))
        except Exception as exc:
            if gen == self._generation:
                self.on_status(f"Trula ошибка: {exc}")

    async def _main(self, gen: int) -> None:
        page_url = self.widget if self.widget.startswith("http") else ""
        token = extract_token(self.widget)
        discovered = await self._inspect(page_url, token, gen)
        if not self._alive(gen):
            return
        stop = _GenStop(self, gen)
        tasks = [
            asyncio.create_task(self._listen_sockets(discovered, token, stop)),
            asyncio.create_task(self._listen_raw_ws(discovered, token, stop)),
            asyncio.create_task(self._poll_apis(discovered, token, gen)),
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _inspect(self, page_url: str, token: str, gen: int) -> dict:
        info: dict = {"sockets": [], "raw_ws": [], "apis": [], "scripts": [], "html": ""}
        if not page_url:
            info["apis"].extend(_guess_api_urls(token))
            info["sockets"].extend(["https://trula.io", "wss://trula.io"])
            info["raw_ws"].extend(_guess_ws_urls(token))
            return info
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(page_url)
                html = resp.text
                info["html"] = html
                origin = f"{urlparse(str(resp.url)).scheme}://{urlparse(str(resp.url)).netloc}"
                info["raw_ws"].extend(re.findall(r"wss?://[a-zA-Z0-9._:/-]+", html))
                info["sockets"].extend(info["raw_ws"])
                info["apis"].extend(_urls_from_text(html, origin, token))
                for payload in payloads_from_html(html):
                    info["apis"].extend(_urls_from_text(json.dumps(payload, ensure_ascii=False), origin, token))
                    self._ingest_payload(payload, bootstrap=True)
                scripts = re.findall(r'src=["\']([^"\']+\.js[^"\']*)["\']', html)
                for src in scripts[:16]:
                    if not self._alive(gen):
                        return info
                    abs_url = urljoin(str(resp.url), src)
                    info["scripts"].append(abs_url)
                    try:
                        js = (await client.get(abs_url)).text
                    except Exception:
                        continue
                    info["raw_ws"].extend(re.findall(r"wss?://[a-zA-Z0-9._:/-]+", js))
                    info["apis"].extend(_urls_from_text(js, origin, token))
                    if "socket.io" in js:
                        info["sockets"].append(origin)
                        info["sockets"].append(origin + "/socket.io")
                    if "reconnecting-websocket" in js or "WebSocket" in js:
                        info["raw_ws"].extend(_guess_ws_urls(token, origin))
        except Exception as exc:
            self.on_status(f"Trula: не открылась ссылка виджета ({exc})")
        info["sockets"] = list(dict.fromkeys(info["sockets"]))
        info["raw_ws"] = list(dict.fromkeys([*info["raw_ws"], *_guess_ws_urls(token)]))
        info["apis"] = list(dict.fromkeys(info["apis"]))
        if info["raw_ws"] or info["sockets"]:
            self.on_status(f"Trula: слушаю сокеты {', '.join((info['raw_ws'] or info['sockets'])[:3])}")
        else:
            self.on_status("Trula: сокет в ссылке не найден — опрашиваю страницу и API каждые 4 сек")
        if info["apis"]:
            self.on_status(f"Trula: найдены API {', '.join(info['apis'][:3])}")
        return info

    async def _listen_sockets(self, discovered: dict, token: str, stop: _GenStop) -> None:
        hosts = list(dict.fromkeys([*(discovered.get("sockets") or []), "https://trula.io", "wss://trula.io"]))
        raw = RawSocketIO(self._on_raw_event, self._note)
        emits = [
            ("add-user", {"token": token, "type": "alert_widget"}),
            ("join", {"token": token}),
            ("subscribe", {"token": token}),
            ("auth", {"token": token}),
            ("widget", {"token": token}),
        ]
        centrifuge = CentrifugeJSON(self._on_publication, self._note)
        while not stop.is_set():
            connected = False
            for host in hosts:
                if stop.is_set():
                    return
                if host.startswith("ws"):
                    try:
                        await centrifuge.listen_v2(
                            host if host.endswith("websocket") else host.rstrip("/") + "/connection/websocket",
                            token=token,
                            channel=f"notifications#{token}",
                            stop_event=stop,
                            label="Trula",
                        )
                        connected = True
                        self.connected = True
                        break
                    except Exception:
                        pass
                try:
                    await raw.connect_and_listen(host, emit_on_connect=emits, stop_event=stop, label="Trula")
                    connected = True
                    self.connected = True
                    break
                except Exception:
                    continue
            if stop.is_set():
                return
            if not connected:
                self._note("Trula: socket.io не найден, оставляю raw WS и опрос")
                await asyncio.sleep(20)
            else:
                self._note("Trula: сокет отключился, переподключаюсь")
                await asyncio.sleep(4)

    async def _listen_raw_ws(self, discovered: dict, token: str, stop: _GenStop) -> None:
        urls = list(dict.fromkeys(discovered.get("raw_ws") or []))
        if not urls:
            urls = _guess_ws_urls(token)
        hello = [
            {"token": token},
            {"type": "subscribe", "token": token},
            {"event": "join", "token": token},
            {"action": "subscribe", "channel": "donations", "token": token},
        ]
        while not stop.is_set():
            connected = False
            for url in urls:
                if stop.is_set():
                    return
                if not url.startswith("ws"):
                    continue
                try:
                    await self._raw_ws_once(url, hello, stop)
                    connected = True
                    self.connected = True
                except Exception as exc:
                    self._note(f"Trula raw WS {url}: {exc}")
            if stop.is_set():
                return
            if not connected:
                await asyncio.sleep(12)
            else:
                await asyncio.sleep(3)

    async def _raw_ws_once(self, url: str, hello: list[dict], stop: _GenStop) -> None:
        async with websockets.connect(url, ping_interval=20, ping_timeout=20, open_timeout=8) as ws:
            self.on_status(f"Trula: raw WebSocket {url}")
            for msg in hello:
                await ws.send(json.dumps(msg, ensure_ascii=False))
            while not stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                payload = unwrap_payload(raw)
                if payload is None:
                    continue
                found = False
                for row in iter_donation_dicts(payload):
                    found = True
                    self._emit(row)
                if not found and isinstance(payload, dict):
                    self._note(f"Trula WS: {str(payload)[:180]}")

    async def _poll_apis(self, discovered: dict, token: str, gen: int) -> None:
        urls = list(discovered.get("apis") or [])
        urls.extend(_guess_api_urls(token))
        if self.widget.startswith("http"):
            urls.append(self.widget)
        urls = list(dict.fromkeys(urls))
        bootstrap: dict[str, set[str]] = {}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            while self._alive(gen):
                for url in urls:
                    if not self._alive(gen):
                        return
                    try:
                        resp = await client.get(url, headers={"Accept": "application/json, text/html"})
                        if resp.status_code >= 400:
                            continue
                        payloads = []
                        try:
                            payloads.append(resp.json())
                        except Exception:
                            payloads.extend(payloads_from_html(resp.text))
                        first = url not in bootstrap
                        seen = bootstrap.setdefault(url, set())
                        for payload in payloads:
                            rows = iter_donation_dicts(payload)
                            if not rows and isinstance(payload, dict):
                                for key in ("items", "results", "donations", "alerts", "events"):
                                    if isinstance(payload.get(key), list):
                                        rows = iter_donation_dicts(payload[key])
                                        break
                            for row in rows:
                                marker = str(row.get("id") or row.get("donation_id") or "") or json.dumps(
                                    row, sort_keys=True, ensure_ascii=False
                                )[:180]
                                if marker in seen:
                                    continue
                                seen.add(marker)
                                if first:
                                    continue
                                item = donation_from_payload(row, "trula")
                                if item:
                                    self.connected = True
                                    self.on_donation(item)
                            if rows:
                                self.connected = True
                    except Exception:
                        continue
                await asyncio.sleep(4)

    def _ingest_payload(self, payload, bootstrap: bool) -> None:
        for row in iter_donation_dicts(payload):
            if bootstrap:
                item = donation_from_payload(row, "trula")
                if item and item.donation_id:
                    self._seen.add(item.donation_id)
                continue
            self._emit(row)

    def _on_raw_event(self, event: str, args) -> None:
        self.connected = True
        if event in {"connect", "disconnect", "ping", "pong"}:
            return
        payload = unwrap_payload(args)
        found = False
        for row in iter_donation_dicts(payload):
            found = True
            self._emit(row)
        if not found:
            self._note(f"Trula событие «{event}»: {str(payload)[:200]}")

    def _on_publication(self, data: dict) -> None:
        for row in iter_donation_dicts(data):
            self._emit(row)

    def _emit(self, payload: dict) -> None:
        item = donation_from_payload(payload, "trula")
        if item is None:
            self._note(f"Trula: пакет без суммы {str(payload)[:180]}")
            return
        if item.donation_id:
            if item.donation_id in self._seen:
                return
            self._seen.add(item.donation_id)
            if len(self._seen) > 4000:
                self._seen = set(list(self._seen)[-2000:])
        self.connected = True
        self.on_donation(item)


def _guess_api_urls(token: str) -> list[str]:
    if not token:
        return []
    return [
        f"https://trula.io/v1/me/donate?token={token}",
        f"https://trula.io/v1/donate?token={token}",
        f"https://trula.io/v1/me?token={token}",
        f"https://trula.io/api/v1/donations?token={token}",
        f"https://trula.io/api/donations?token={token}",
        f"https://trula.io/v1/widgets/{token}",
        f"https://trula.io/v1/widgets/{token}/events",
        f"https://api.trula.io/v1/donate?token={token}",
    ]


def _guess_ws_urls(token: str, origin: str = "https://trula.io") -> list[str]:
    parsed = urlparse(origin if "://" in origin else f"https://{origin}")
    host = parsed.netloc or "trula.io"
    return [
        f"wss://{host}/ws",
        f"wss://{host}/ws?token={token}",
        f"wss://{host}/v1/ws?token={token}",
        f"wss://{host}/socket?token={token}",
        f"wss://{host}/connection/websocket",
    ]


def _urls_from_text(text: str, origin: str, token: str) -> list[str]:
    found: list[str] = []
    for raw in re.findall(r"https?://[a-zA-Z0-9._:/-]+", text):
        low = raw.lower()
        if any(key in low for key in ("donate", "donation", "alert", "widget", "notif", "/v1/", "/api")):
            found.append(raw)
    for path in re.findall(r"['\"](/[a-zA-Z0-9_\-./]{3,80})['\"]", text):
        low = path.lower()
        if any(key in low for key in ("donate", "donation", "alert", "widget", "/v1/", "/api")):
            url = origin + path
            if token and "token=" not in url:
                url += ("&" if "?" in url else "?") + "token=" + token
            found.append(url)
    return found
