from __future__ import annotations

import json
from typing import Callable
from urllib.parse import urlparse

import httpx
import websockets


def _origin(url: str) -> str:
    parsed = urlparse(url)
    scheme = "https" if parsed.scheme in {"wss", "https"} else "http"
    netloc = parsed.netloc
    return f"{scheme}://{netloc}"


def _socket_url(base: str, eio: int, sid: str = "") -> str:
    parsed = urlparse(base)
    if parsed.scheme in {"http", "https", "ws", "wss"}:
        host = parsed.netloc
        path = parsed.path.rstrip("/") or "/socket.io"
        if not path.endswith("socket.io"):
            path = path + "/socket.io"
        ws_scheme = "wss" if parsed.scheme in {"https", "wss"} else "ws"
    else:
        host = base.replace("https://", "").replace("http://", "").replace("wss://", "").replace("ws://", "")
        path = "/socket.io"
        ws_scheme = "wss"
    query = f"EIO={eio}&transport=websocket"
    if sid:
        query += f"&sid={sid}"
    return f"{ws_scheme}://{host}{path}/?{query}"


def _http_base(base: str) -> str:
    parsed = urlparse(base if "://" in base else f"https://{base}")
    scheme = "https" if parsed.scheme in {"https", "wss", ""} else "http"
    path = parsed.path.rstrip("/") or "/socket.io"
    if not path.endswith("socket.io"):
        path = path + "/socket.io"
    return f"{scheme}://{parsed.netloc}{path}/"


class RawSocketIO:
    """Engine.IO 3/4 + Socket.IO event client. Works with old DonationAlerts widgets."""

    def __init__(self, on_event: Callable[[str, object], None], on_status: Callable[[str], None] | None = None) -> None:
        self.on_event = on_event
        self.on_status = on_status or (lambda _msg: None)

    async def connect_and_listen(
        self,
        base: str,
        emit_on_connect: list[tuple[str, object]] | None = None,
        stop_event=None,
        label: str = "socket",
    ) -> None:
        last_error: Exception | None = None
        for eio in (3, 4):
            try:
                await self._listen(base, eio, emit_on_connect or [], stop_event, label)
                return
            except Exception as exc:
                last_error = exc
                self.on_status(f"{label}: EIO {eio} не подошёл ({exc})")
        if last_error:
            raise last_error

    async def _listen(
        self,
        base: str,
        eio: int,
        emit_on_connect: list[tuple[str, object]],
        stop_event,
        label: str,
    ) -> None:
        sid = ""
        ping_interval = 25
        http_url = _http_base(base)
        origin = _origin(base if "://" in base else f"https://{base}")
        try:
            async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
                resp = await client.get(http_url, params={"EIO": eio, "transport": "polling"})
                if resp.status_code < 400:
                    text = resp.text
                    if text[:1].isdigit() and ":" in text[:6]:
                        text = text.split(":", 1)[1]
                    if text.startswith("0"):
                        hello = json.loads(text[1:])
                        sid = str(hello.get("sid") or "")
                        ping_interval = int(hello.get("pingInterval") or 25000) / 1000
        except Exception:
            sid = ""

        ws_url = _socket_url(base, eio, sid)
        headers = {"Origin": origin}
        ws_kwargs = {}
        try:
            import inspect

            params = inspect.signature(websockets.connect).parameters
            if "additional_headers" in params:
                ws_kwargs["additional_headers"] = headers
            elif "extra_headers" in params:
                ws_kwargs["extra_headers"] = headers
        except Exception:
            ws_kwargs["additional_headers"] = headers
        async with websockets.connect(ws_url, ping_interval=None, ping_timeout=None, **ws_kwargs) as ws:
            if eio == 3 and sid:
                await ws.send("2probe")
                probe = await ws.recv()
                if isinstance(probe, bytes):
                    probe = probe.decode("utf-8", "ignore")
                if "3probe" in str(probe):
                    await ws.send("5")
            opened = False
            while stop_event is None or not stop_event.is_set():
                try:
                    raw = await ws.recv()
                except Exception:
                    break
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", "ignore")
                packet = str(raw)
                if packet.startswith("0"):
                    try:
                        hello = json.loads(packet[1:] or "{}")
                        ping_interval = int(hello.get("pingInterval") or ping_interval * 1000) / 1000
                    except json.JSONDecodeError:
                        pass
                    continue
                if packet == "2" or packet.startswith("2"):
                    await ws.send("3" + packet[1:])
                    continue
                if packet.startswith("40") and not opened:
                    opened = True
                    self.on_status(f"{label}: сокет подключен (EIO {eio})")
                    self.on_event("connect", None)
                    for event, payload in emit_on_connect:
                        await ws.send("42" + json.dumps([event, payload], ensure_ascii=False))
                    continue
                if packet.startswith("42"):
                    try:
                        data = json.loads(packet[2:])
                    except json.JSONDecodeError:
                        continue
                    if isinstance(data, list) and data:
                        event = str(data[0])
                        args = data[1] if len(data) > 1 else None
                        if len(data) > 2:
                            args = data[1:]
                        self.on_event(event, args)
            if not opened:
                raise RuntimeError("сокет открылся, но namespace не подключился")
