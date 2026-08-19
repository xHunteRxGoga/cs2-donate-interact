from __future__ import annotations

import asyncio
import threading
import time
from typing import Callable
from urllib.parse import urlencode
from http.server import BaseHTTPRequestHandler, HTTPServer
import webbrowser

import json

import httpx
import websockets

from src.donations.models import Donation
from src.donations.parse import donation_from_payload, extract_token, iter_donation_dicts, unwrap_payload
from src.donations.socketio_raw import RawSocketIO


DA_API = "https://www.donationalerts.com/api/v1"
DA_OAUTH = "https://www.donationalerts.com/oauth/authorize"
DA_TOKEN = "https://www.donationalerts.com/oauth/token"
DA_WS = "wss://centrifugo.donationalerts.com/connection/websocket"
SCOPES = "oauth-user-show oauth-donation-index oauth-donation-subscribe"
DA_WIDGET_HOSTS = (
    "https://socket.donationalerts.ru",
    "https://socket6.donationalerts.ru",
    "https://socket7.donationalerts.ru",
    "wss://socket.donationalerts.ru:443",
)


class _GenStop:
    def __init__(self, client: "DonationAlertsClient", gen: int) -> None:
        self.client = client
        self.gen = gen

    def is_set(self) -> bool:
        return self.client._stop.is_set() or (self.gen and self.client._generation != self.gen)


class DonationAlertsClient:
    def __init__(self, on_donation: Callable[[Donation], None], on_status: Callable[[str], None]) -> None:
        self.on_donation = on_donation
        self.on_status = on_status
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.access_token = ""
        self.widget_token = ""
        self.mode = "websocket"
        self.connected = False
        self._seen: set[str] = set()
        self._last_test: dict[str, float] = {}
        self._generation = 0

    def start(self, access_token: str = "", mode: str = "websocket", widget_token: str = "") -> None:
        self._generation += 1
        gen = self._generation
        self._stop.set()
        self.access_token = (access_token or "").strip()
        self.widget_token = extract_token(widget_token or "")
        self.mode = mode or "websocket"
        self.connected = False
        if not self.widget_token and not self.access_token:
            self.on_status("DonationAlerts: нет токена. Нажми «Привязать аккаунт».")
            return
        self._stop.clear()
        if self.widget_token:
            self._spawn("da-widget", lambda: self._run_widget(gen))
        if self.access_token:
            self._spawn("da-api", lambda: self._run_api(gen))
        self.on_status("DonationAlerts: слушатели запущены, жду донаты")

    def stop(self) -> None:
        self._generation += 1
        self._stop.set()
        self.connected = False

    def _spawn(self, name: str, target) -> None:
        thread = threading.Thread(target=target, name=name, daemon=True)
        self._threads.append(thread)
        thread.start()

    def _emit_donation(self, payload: dict, source: str = "donationalerts") -> None:
        item = donation_from_payload(payload, source)
        if item is None:
            preview = str({k: payload.get(k) for k in list(payload)[:8]})[:240]
            self.on_status(f"DonationAlerts: событие без суммы, пропуск ({preview})")
            return
        if item.is_test:
            stamp = f"test:{item.amount}:{item.username}:{item.message}:{item.donation_id}"
            now = time.monotonic()
            last = self._last_test.get(stamp, 0)
            if now - last < 1.5:
                return
            self._last_test[stamp] = now
        elif item.donation_id:
            if item.donation_id in self._seen:
                return
            self._seen.add(item.donation_id)
            if len(self._seen) > 4000:
                self._seen = set(list(self._seen)[-2000:])
        self.connected = True
        self.on_donation(item)

    def _accept_socket_args(self, event: str, args) -> None:
        payload = unwrap_payload(args)
        found = False
        for row in iter_donation_dicts(payload):
            found = True
            self._emit_donation(row, "donationalerts")
        if not found and event not in {"update-alert_widget", "update-widget", "reload", "update-alert_widget-settings"}:
            preview = str(payload)[:220]
            self.on_status(f"DonationAlerts событие «{event}»: {preview}")

    def _run_widget(self, gen: int = 0) -> None:
        if gen and gen != self._generation:
            return
        try:
            asyncio.run(self._widget_loop(gen))
        except Exception as exc:
            if gen == self._generation:
                self.on_status(f"DonationAlerts виджет: {exc}")

    def _run_api(self, gen: int = 0) -> None:
        if gen and gen != self._generation:
            return
        try:
            asyncio.run(self._api_main(gen))
        except Exception as exc:
            if gen == self._generation:
                self.on_status(f"DonationAlerts API: {exc}")

    async def _widget_loop(self, gen: int = 0) -> None:
        await asyncio.gather(
            self._widget_socket(gen),
            self._widget_poll(gen),
            return_exceptions=True,
        )

    async def _widget_socket(self, gen: int = 0) -> None:
        hosts = list(DA_WIDGET_HOSTS)
        raw = RawSocketIO(self._on_raw_event, self.on_status)
        emits = [
            ("add-user", {"token": self.widget_token, "type": "alert_widget"}),
            ("add-user", {"token": self.widget_token, "type": "minor"}),
        ]
        last_error: Exception | None = None
        stop = _GenStop(self, gen)
        while stop.is_set() is False:
            connected_any = False
            for host in hosts:
                if stop.is_set():
                    return
                try:
                    await raw.connect_and_listen(
                        host,
                        emit_on_connect=emits,
                        stop_event=stop,
                        label="DonationAlerts",
                    )
                    connected_any = True
                    self.connected = True
                    break
                except Exception as exc:
                    last_error = exc
            if not connected_any:
                self.on_status(f"DonationAlerts виджет не подключился ({last_error}), повтор через 8 сек")
                await asyncio.sleep(8)
            else:
                if not stop.is_set():
                    self.on_status("DonationAlerts: сокет отключился, переподключаюсь")
                    await asyncio.sleep(3)

    async def _widget_poll(self, gen: int = 0) -> None:
        token = self.widget_token
        if not token:
            return
        stop = _GenStop(self, gen)
        urls = [
            f"{DA_API}/alerts/donations",
            f"https://www.donationalerts.com/widget/lastdonations?alert_type=1&limit=20&token={token}",
        ]
        headers_list = [
            {"Authorization": f"Bearer {token}", "Accept": "application/json"},
            {"Accept": "application/json, text/html"},
        ]
        bootstrap: dict[str, set[str]] = {}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            while not stop.is_set():
                for url, headers in zip(urls, headers_list):
                    try:
                        resp = await client.get(url, headers=headers)
                        if resp.status_code >= 400:
                            continue
                        try:
                            payload = resp.json()
                        except Exception:
                            payload = None
                        rows = []
                        if isinstance(payload, dict):
                            rows = payload.get("data") or []
                            if not rows:
                                rows = iter_donation_dicts(payload)
                        elif isinstance(payload, list):
                            rows = payload
                        first = url not in bootstrap
                        seen = bootstrap.setdefault(url, set())
                        for row in rows:
                            if not isinstance(row, dict):
                                continue
                            marker = str(row.get("id") or row.get("donation_id") or "") or str(row)[:120]
                            if marker in seen:
                                continue
                            seen.add(marker)
                            if first:
                                continue
                            self._emit_donation(row, "donationalerts-widget-poll")
                    except Exception:
                        continue
                await asyncio.sleep(5)

    def _on_raw_event(self, event: str, args) -> None:
        self.connected = True
        if event in {"connect", "disconnect", "ping", "pong"}:
            return
        try:
            self._accept_socket_args(event, args)
        except Exception as exc:
            self.on_status(f"DonationAlerts {event}: {exc}")

    async def _api_main(self, gen: int = 0) -> None:
        if self.mode == "poll":
            await self._poll_loop(gen)
            return
        try:
            await asyncio.gather(self._websocket_loop(gen), self._poll_loop(gen), return_exceptions=True)
        except Exception as exc:
            self.on_status(f"DonationAlerts WebSocket: {exc}, оставляю опрос")
            await self._poll_loop(gen)

    async def _websocket_loop(self, gen: int = 0) -> None:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        stop = _GenStop(self, gen)
        while not stop.is_set():
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    user = (await client.get(f"{DA_API}/user/oauth", headers=headers)).json()["data"]
                user_id = user["id"]
                socket_token = user["socket_connection_token"]
                self.on_status(f"DonationAlerts: вход как {user.get('name') or user.get('code')}")
                self.connected = True
                async with websockets.connect(DA_WS, ping_interval=25, ping_timeout=20) as ws:
                    await ws.send(json.dumps({"params": {"token": socket_token}, "id": 1}))
                    raw_hello = await ws.recv()
                    if isinstance(raw_hello, bytes):
                        raw_hello = raw_hello.decode("utf-8", "ignore")
                    hello = json.loads(raw_hello)
                    client_id = hello["result"]["client"]
                    channel = f"$alerts:donation_{user_id}"
                    async with httpx.AsyncClient(timeout=20) as client:
                        sub = (
                            await client.post(
                                f"{DA_API}/centrifuge/subscribe",
                                headers=headers,
                                json={"channels": [channel], "client": client_id},
                            )
                        ).json()
                    sub_token = sub["channels"][0]["token"]
                    await ws.send(
                        json.dumps({"params": {"channel": channel, "token": sub_token}, "method": 1, "id": 2})
                    )
                    self.on_status("DonationAlerts: API WebSocket подключен")
                    self.connected = True
                    while not stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        except asyncio.TimeoutError:
                            continue
                        self._handle_ws_message(raw)
            except Exception as exc:
                if stop.is_set():
                    return
                self.on_status(f"DonationAlerts API сокет: {exc}, повтор")
                await asyncio.sleep(5)

    def _handle_ws_message(self, raw: str) -> None:
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "ignore")
            payload = json.loads(raw)
        except Exception:
            return
        data = payload.get("result", {}).get("data", {})
        donation = data.get("data") or data.get("donation") or data
        if isinstance(donation, dict) and any(
            key in donation for key in ("amount", "amount_main", "amount_formatted", "_is_test_alert")
        ):
            self._emit_donation(donation, "donationalerts")

    async def _poll_loop(self, gen: int = 0) -> None:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        self.on_status("DonationAlerts: опрос API каждые 4 сек (подстраховка)")
        bootstrap = True
        stop = _GenStop(self, gen)
        async with httpx.AsyncClient(timeout=20) as client:
            while not stop.is_set():
                try:
                    resp = await client.get(f"{DA_API}/alerts/donations", headers=headers)
                    resp.raise_for_status()
                    for row in resp.json().get("data", []):
                        donation_id = str(row.get("id") or "")
                        if donation_id and donation_id in self._seen:
                            continue
                        if bootstrap:
                            if donation_id:
                                self._seen.add(donation_id)
                            continue
                        self._emit_donation(row, "donationalerts-poll")
                    bootstrap = False
                    self.connected = True
                except Exception as exc:
                    self.on_status(f"DonationAlerts опрос: {exc}")
                await asyncio.sleep(4)


def oauth_login(client_id: str, client_secret: str, redirect_uri: str) -> str:
    parsed_port = int(redirect_uri.rsplit(":", 1)[-1].split("/", 1)[0])
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            from urllib.parse import parse_qs, urlparse

            query = parse_qs(urlparse(self.path).query)
            if "code" in query:
                result["code"] = query["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("Можно закрыть вкладку и вернуться в приложение.".encode("utf-8"))
            else:
                self.send_response(400)
                self.end_headers()

        def log_message(self, *_args) -> None:
            return

    server = HTTPServer(("127.0.0.1", parsed_port), Handler)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
    }
    webbrowser.open(f"{DA_OAUTH}?{urlencode(params)}")
    server.timeout = 120
    server.handle_request()
    server.server_close()
    if "code" not in result:
        raise RuntimeError("Не получен код авторизации DonationAlerts")
    resp = httpx.post(
        DA_TOKEN,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code": result["code"],
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]
