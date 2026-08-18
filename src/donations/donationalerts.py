from __future__ import annotations

import asyncio
import json
import threading
from typing import Callable
from urllib.parse import urlencode
from http.server import BaseHTTPRequestHandler, HTTPServer
import webbrowser

import httpx
import websockets

from src.donations.trula import extract_token
from src.donations.models import Donation


DA_API = "https://www.donationalerts.com/api/v1"
DA_OAUTH = "https://www.donationalerts.com/oauth/authorize"
DA_TOKEN = "https://www.donationalerts.com/oauth/token"
DA_WS = "wss://centrifugo.donationalerts.com/connection/websocket"
SCOPES = "oauth-user-show oauth-donation-index oauth-donation-subscribe"


class DonationAlertsClient:
    def __init__(self, on_donation: Callable[[Donation], None], on_status: Callable[[str], None]) -> None:
        self.on_donation = on_donation
        self.on_status = on_status
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.access_token = ""
        self.widget_token = ""
        self.mode = "websocket"
        self._seen: set[str] = set()
        self._sio = None

    def start(self, access_token: str = "", mode: str = "websocket", widget_token: str = "") -> None:
        self.stop()
        self.access_token = (access_token or "").strip()
        self.widget_token = extract_token(widget_token or "")
        self.mode = mode
        if not self.widget_token and not self.access_token:
            self.on_status("DonationAlerts: нет токена")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="donationalerts", daemon=True)
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
        try:
            if self.widget_token:
                self._run_widget_socket()
                return
            asyncio.run(self._main())
        except Exception as exc:
            self.on_status(f"DonationAlerts ошибка: {exc}")

    def _run_widget_socket(self) -> None:
        import time

        try:
            import socketio
        except ImportError:
            self.on_status("DonationAlerts: установи зависимости через run.bat")
            return
        sio = socketio.Client(reconnection=True, reconnection_delay=3, reconnection_delay_max=15)
        self._sio = sio

        @sio.event
        def connect() -> None:
            sio.emit("add-user", {"token": self.widget_token, "type": "alert_widget"})
            self.on_status("DonationAlerts: виджет подключен, жду донаты")

        @sio.on("donation")
        def donation(data) -> None:
            payload = json.loads(data) if isinstance(data, str) else data
            if not isinstance(payload, dict):
                return
            donation_id = str(payload.get("id") or "")
            if donation_id:
                if donation_id in self._seen:
                    return
                self._seen.add(donation_id)
            self.on_donation(
                Donation(
                    username=str(payload.get("username") or "Аноним"),
                    amount=float(payload.get("amount") or payload.get("amount_main") or 0),
                    currency=str(payload.get("currency") or "RUB"),
                    message=str(payload.get("message") or ""),
                    source="donationalerts",
                    donation_id=donation_id,
                )
            )

        hosts = [
            "wss://socket.donationalerts.ru:443",
            "https://socket.donationalerts.ru",
            "wss://socket6.donationalerts.ru",
            "wss://socket7.donationalerts.ru",
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
            self.on_status(f"DonationAlerts виджет: {last_error}")
            if self.access_token:
                self.on_status("DonationAlerts: пробую API-токен")
                asyncio.run(self._main())
            return
        while not self._stop.is_set():
            time.sleep(0.2)
        try:
            sio.disconnect()
        except Exception:
            pass

    async def _main(self) -> None:
        if self.mode == "poll":
            await self._poll_loop()
            return
        try:
            await self._websocket_loop()
        except Exception as exc:
            self.on_status(f"WebSocket недоступен ({exc}), переключаюсь на опрос")
            await self._poll_loop()

    async def _websocket_loop(self) -> None:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with httpx.AsyncClient(timeout=20) as client:
            user = (await client.get(f"{DA_API}/user/oauth", headers=headers)).json()["data"]
            user_id = user["id"]
            socket_token = user["socket_connection_token"]
            self.on_status(f"DonationAlerts: вход как {user.get('name') or user.get('code')}")

        async with websockets.connect(DA_WS, ping_interval=25, ping_timeout=20) as ws:
            await ws.send(json.dumps({"params": {"token": socket_token}, "id": 1}))
            hello = json.loads(await ws.recv())
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
            self.on_status("DonationAlerts: WebSocket подключен")
            while not self._stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                self._handle_ws_message(raw)

    def _handle_ws_message(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        data = payload.get("result", {}).get("data", {})
        donation = data.get("data") or data.get("donation") or data
        if not isinstance(donation, dict) or "amount" not in donation:
            return
        item = Donation(
            username=str(donation.get("username") or "Аноним"),
            amount=float(donation.get("amount") or 0),
            currency=str(donation.get("currency") or "RUB"),
            message=str(donation.get("message") or ""),
            source="donationalerts",
            donation_id=str(donation.get("id") or ""),
        )
        if item.donation_id:
            if item.donation_id in self._seen:
                return
            self._seen.add(item.donation_id)
        self.on_donation(item)

    async def _poll_loop(self) -> None:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        self.on_status("DonationAlerts: опрос донатов каждые 3 сек")
        bootstrap = True
        async with httpx.AsyncClient(timeout=20) as client:
            while not self._stop.is_set():
                try:
                    resp = await client.get(f"{DA_API}/alerts/donations", headers=headers)
                    resp.raise_for_status()
                    for row in resp.json().get("data", []):
                        donation_id = str(row.get("id") or "")
                        if donation_id and donation_id in self._seen:
                            continue
                        if donation_id:
                            self._seen.add(donation_id)
                        if bootstrap:
                            continue
                        self.on_donation(
                            Donation(
                                username=str(row.get("username") or "Аноним"),
                                amount=float(row.get("amount") or 0),
                                currency=str(row.get("currency") or "RUB"),
                                message=str(row.get("message") or ""),
                                source="donationalerts-poll",
                                donation_id=donation_id,
                            )
                        )
                    bootstrap = False
                except Exception as exc:
                    self.on_status(f"DonationAlerts опрос: {exc}")
                await asyncio.sleep(3)


def oauth_login(client_id: str, client_secret: str, redirect_uri: str) -> str:
    """Открывает браузер, ловит code на localhost и возвращает access_token."""
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
