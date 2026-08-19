from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Callable
from urllib.parse import urlencode
from http.server import BaseHTTPRequestHandler, HTTPServer
import webbrowser

import httpx
import websockets

from src.donations.trula import extract_token
from src.donations.models import Donation


def _parse_amount(value) -> float:
    if value is None or value is False:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "").replace("\xa0", "").replace(",", ".")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _truthy(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _unwrap_payload(args) -> dict | list | None:
    if not args:
        return None
    data = args[0] if len(args) == 1 else next((item for item in args if item not in (None, "")), args[0])
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8", "ignore")
    if isinstance(data, str):
        text = data.strip()
        if not text:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
    return data


def _iter_donation_dicts(payload) -> list[dict]:
    if payload is None:
        return []
    if isinstance(payload, list):
        result = []
        for item in payload:
            result.extend(_iter_donation_dicts(item))
        return result
    if not isinstance(payload, dict):
        return []
    nested = payload.get("donation") or payload.get("donate") or payload.get("alert")
    if isinstance(nested, dict) and ("amount" in nested or "amount_main" in nested or "amount_formatted" in nested):
        return [nested]
    if "data" in payload and payload["data"] is not payload:
        inner = _iter_donation_dicts(payload["data"])
        if inner:
            return inner
    if any(key in payload for key in ("amount", "amount_main", "amount_formatted", "username", "_is_test_alert")):
        return [payload]
    return []


def donation_from_payload(payload: dict, source: str = "donationalerts") -> Donation | None:
    amount = _parse_amount(payload.get("amount_main"))
    if amount <= 0:
        amount = _parse_amount(payload.get("amount"))
    if amount <= 0:
        amount = _parse_amount(payload.get("amount_formatted") or payload.get("sum"))
    currency = str(payload.get("currency") or payload.get("currency_code") or "RUB").upper().replace("RUR", "RUB")
    if currency in {"", "₽", "РУБ", "RUBLES"}:
        currency = "RUB"
    username = str(payload.get("username") or payload.get("name") or payload.get("user_name") or "Аноним")
    message = str(payload.get("message") or payload.get("comment") or "")
    donation_id = str(payload.get("id") or payload.get("donation_id") or payload.get("alert_id") or "").strip()
    is_test = _truthy(payload.get("_is_test_alert") or payload.get("is_test") or payload.get("test"))
    alert_type = str(payload.get("alert_type") or "1")
    if alert_type not in {"", "1", "donation", "donate"} and amount <= 0:
        return None
    if amount <= 0 and not is_test:
        return None
    return Donation(
        username=username,
        amount=amount,
        currency=currency,
        message=message,
        source=source + ("-test" if is_test else ""),
        donation_id=donation_id,
        is_test=is_test,
    )


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
        self._last_test: dict[str, float] = {}
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
        self.on_donation(item)

    def _accept_socket_args(self, event: str, args) -> None:
        payload = _unwrap_payload(args)
        found = False
        for row in _iter_donation_dicts(payload):
            found = True
            self._emit_donation(row, "donationalerts")
        if not found and event not in {"update-alert_widget", "update-widget", "reload"}:
            preview = str(payload)[:220]
            self.on_status(f"DonationAlerts событие «{event}»: {preview}")

    def _run(self) -> None:
        try:
            if self.widget_token:
                self._run_widget_socket()
                return
            asyncio.run(self._main())
        except Exception as exc:
            self.on_status(f"DonationAlerts ошибка: {exc}")

    def _run_widget_socket(self) -> None:
        try:
            import socketio
        except ImportError:
            self.on_status("DonationAlerts: установи зависимости через run.bat")
            return
        sio = socketio.Client(reconnection=True, reconnection_delay=3, reconnection_delay_max=15)
        self._sio = sio

        def subscribe() -> None:
            for kind in ("alert_widget", "minor"):
                sio.emit("add-user", {"token": self.widget_token, "type": kind})
            self.on_status("DonationAlerts: виджет подключен, жду донаты и тестовые алерты")

        @sio.event
        def connect() -> None:
            subscribe()

        @sio.event
        def reconnect() -> None:
            subscribe()

        @sio.event
        def connect_error(data) -> None:
            self.on_status(f"DonationAlerts: ошибка сокета {data}")

        @sio.on("donation")
        def donation(*args) -> None:
            try:
                self._accept_socket_args("donation", args)
            except Exception as exc:
                self.on_status(f"DonationAlerts donation: {exc}")

        @sio.on("alert")
        def alert(*args) -> None:
            try:
                self._accept_socket_args("alert", args)
            except Exception as exc:
                self.on_status(f"DonationAlerts alert: {exc}")

        @sio.on("donate")
        def donate(*args) -> None:
            try:
                self._accept_socket_args("donate", args)
            except Exception as exc:
                self.on_status(f"DonationAlerts donate: {exc}")

        @sio.on("*")
        def any_event(event, *args) -> None:
            if event in {"donation", "alert", "donate", "connect", "disconnect", "reconnect", "connect_error"}:
                return
            try:
                self._accept_socket_args(str(event), args)
            except Exception as exc:
                self.on_status(f"DonationAlerts: {event}: {exc}")

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
        if isinstance(donation, dict) and any(
            key in donation for key in ("amount", "amount_main", "amount_formatted", "_is_test_alert")
        ):
            self._emit_donation(donation, "donationalerts")

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
                        if bootstrap:
                            if donation_id:
                                self._seen.add(donation_id)
                            continue
                        self._emit_donation(row, "donationalerts-poll")
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
