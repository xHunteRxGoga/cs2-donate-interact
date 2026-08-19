from __future__ import annotations

import asyncio
import json
import re
import threading
from typing import Callable
from urllib.parse import urljoin, urlparse

import httpx

from src.donations.centrifuge_json import CentrifugeJSON
from src.donations.models import Donation
from src.donations.parse import donation_from_payload, extract_token, iter_donation_dicts, unwrap_payload
from src.donations.socketio_raw import RawSocketIO


class TrulaClient:
    def __init__(self, on_donation: Callable[[Donation], None], on_status: Callable[[str], None]) -> None:
        self.on_donation = on_donation
        self.on_status = on_status
        self._stop = threading.Event()
        self._seen: set[str] = set()
        self.widget = ""
        self.connected = False
        self._generation = 0

    def start(self, widget: str) -> None:
        self._generation += 1
        gen = self._generation
        self._stop.set()
        self.widget = (widget or "").strip()
        self.connected = False
        if not self.widget:
            self.on_status("Trula: нет ссылки виджета. Нажми «Привязать аккаунт».")
            return
        if "/dp/" in self.widget and "widget" not in self.widget.lower() and "overlay" not in self.widget.lower():
            self.on_status("Trula: это страница доната /dp/..., а нужна OBS-ссылка виджета алертов.")
        self._stop.clear()
        threading.Thread(target=self._run, args=(gen,), name="trula", daemon=True).start()

    def stop(self) -> None:
        self._generation += 1
        self._stop.set()
        self.connected = False

    def _run(self, gen: int = 0) -> None:
        if gen and gen != self._generation:
            return
        try:
            asyncio.run(self._main())
        except Exception as exc:
            if gen == self._generation:
                self.on_status(f"Trula ошибка: {exc}")

    async def _main(self) -> None:
        page_url = self.widget if self.widget.startswith("http") else ""
        token = extract_token(self.widget)
        discovered = await self._inspect(page_url, token)
        tasks = [
            asyncio.create_task(self._listen_sockets(discovered, token)),
            asyncio.create_task(self._poll_apis(discovered, token)),
        ]
        await asyncio.gather(*tasks)

    async def _inspect(self, page_url: str, token: str) -> dict:
        info: dict = {"sockets": [], "apis": [], "scripts": [], "html": ""}
        if not page_url:
            info["apis"].extend(_guess_api_urls(token))
            info["sockets"].extend(
                [
                    "https://trula.io",
                    "https://trula.io/socket.io",
                    "wss://trula.io",
                ]
            )
            return info
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(page_url)
                html = resp.text
                info["html"] = html
                origin = f"{urlparse(str(resp.url)).scheme}://{urlparse(str(resp.url)).netloc}"
                info["sockets"].extend(re.findall(r"wss?://[a-zA-Z0-9._:/-]+", html))
                info["apis"].extend(_urls_from_text(html, origin, token))
                scripts = re.findall(r'src=["\']([^"\']+\.js[^"\']*)["\']', html)
                for src in scripts[:12]:
                    abs_url = urljoin(str(resp.url), src)
                    info["scripts"].append(abs_url)
                    try:
                        js = (await client.get(abs_url)).text
                    except Exception:
                        continue
                    info["sockets"].extend(re.findall(r"wss?://[a-zA-Z0-9._:/-]+", js))
                    info["apis"].extend(_urls_from_text(js, origin, token))
                    if "socket.io" in js:
                        info["sockets"].append(origin)
                        info["sockets"].append(origin + "/socket.io")
        except Exception as exc:
            self.on_status(f"Trula: не открылась ссылка виджета ({exc})")
        info["sockets"] = list(dict.fromkeys(info["sockets"]))
        info["apis"] = list(dict.fromkeys(info["apis"]))
        if info["sockets"]:
            self.on_status(f"Trula: в виджете найдены сокеты {', '.join(info['sockets'][:3])}")
        if info["apis"]:
            self.on_status(f"Trula: найдены API {', '.join(info['apis'][:3])}")
        return info

    async def _listen_sockets(self, discovered: dict, token: str) -> None:
        hosts = discovered.get("sockets") or []
        hosts.extend(
            [
                "https://trula.io",
                "wss://trula.io",
            ]
        )
        hosts = list(dict.fromkeys(hosts))
        raw = RawSocketIO(self._on_raw_event, self.on_status)
        emits = [
            ("add-user", {"token": token, "type": "alert_widget"}),
            ("join", {"token": token}),
            ("subscribe", {"token": token}),
            ("auth", {"token": token}),
        ]
        centrifuge = CentrifugeJSON(self._on_publication, self.on_status)
        while not self._stop.is_set():
            connected = False
            for host in hosts:
                if self._stop.is_set():
                    return
                if host.startswith("ws"):
                    try:
                        await centrifuge.listen_v2(
                            host if host.endswith("websocket") else host.rstrip("/") + "/connection/websocket",
                            token=token,
                            channel=f"notifications#{token}",
                            stop_event=self._stop,
                            label="Trula",
                        )
                        connected = True
                        self.connected = True
                        break
                    except Exception:
                        pass
                try:
                    await raw.connect_and_listen(host, emit_on_connect=emits, stop_event=self._stop, label="Trula")
                    connected = True
                    self.connected = True
                    break
                except Exception:
                    continue
            if not connected:
                self.on_status("Trula: realtime-сокет не найден, оставляю опрос страницы/API")
                await asyncio.sleep(12)
            elif not self._stop.is_set():
                self.on_status("Trula: сокет отключился, переподключаюсь")
                await asyncio.sleep(4)

    async def _poll_apis(self, discovered: dict, token: str) -> None:
        urls = list(discovered.get("apis") or [])
        urls.extend(_guess_api_urls(token))
        if self.widget.startswith("http"):
            urls.append(self.widget)
        urls = list(dict.fromkeys(urls))
        bootstrap: dict[str, set[str]] = {}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            while not self._stop.is_set():
                for url in urls:
                    try:
                        resp = await client.get(url, headers={"Accept": "application/json"})
                        if resp.status_code >= 400:
                            continue
                        payload = None
                        try:
                            payload = resp.json()
                        except Exception:
                            text = resp.text
                            match = re.search(r"(\{.*\}|\[.*\])", text, re.S)
                            if match:
                                try:
                                    payload = json.loads(match.group(1)[:200000])
                                except json.JSONDecodeError:
                                    payload = None
                        if payload is None:
                            continue
                        rows = iter_donation_dicts(payload)
                        if not rows and isinstance(payload, dict):
                            for key in ("items", "results", "donations", "alerts"):
                                if isinstance(payload.get(key), list):
                                    rows = iter_donation_dicts(payload[key])
                                    break
                        first = url not in bootstrap
                        seen = bootstrap.setdefault(url, set())
                        for row in rows:
                            donation_id = str(row.get("id") or row.get("donation_id") or "")
                            marker = donation_id or json.dumps(row, sort_keys=True, ensure_ascii=False)[:180]
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
                await asyncio.sleep(5)

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
            self.on_status(f"Trula событие «{event}»: {str(payload)[:200]}")

    def _on_publication(self, data: dict) -> None:
        for row in iter_donation_dicts(data):
            self._emit(row)

    def _emit(self, payload: dict) -> None:
        item = donation_from_payload(payload, "trula")
        if item is None:
            return
        if item.donation_id:
            if item.donation_id in self._seen:
                return
            self._seen.add(item.donation_id)
        self.connected = True
        self.on_donation(item)


def _guess_api_urls(token: str) -> list[str]:
    if not token:
        return []
    return [
        f"https://trula.io/v1/me/donate?token={token}",
        f"https://trula.io/api/v1/donations?token={token}",
        f"https://trula.io/api/donations?token={token}",
        f"https://trula.io/v1/donate?token={token}",
    ]


def _urls_from_text(text: str, origin: str, token: str) -> list[str]:
    found: list[str] = []
    for raw in re.findall(r"https?://[a-zA-Z0-9._:/-]+", text):
        low = raw.lower()
        if any(key in low for key in ("donate", "donation", "alert", "widget", "notif", "/v1/")):
            found.append(raw)
    for path in re.findall(r"['\"](/[a-zA-Z0-9_\-./]{3,80})['\"]", text):
        low = path.lower()
        if any(key in low for key in ("donate", "donation", "alert", "widget", "/v1/", "/api")):
            url = origin + path
            if token and "token=" not in url:
                url += ("&" if "?" in url else "?") + "token=" + token
            found.append(url)
    return found
