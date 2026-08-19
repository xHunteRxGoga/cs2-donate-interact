from __future__ import annotations

import json
import time
import uuid
from typing import Callable

import websockets


def _as_dict(raw: str | bytes) -> dict | list | None:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "ignore")
    text = str(raw).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


class CentrifugeJSON:
    """Talks both Centrifugo v1 (DonatePay widget) and v2 JSON protocols."""

    def __init__(self, on_publication: Callable[[dict], None], on_status: Callable[[str], None] | None = None) -> None:
        self.on_publication = on_publication
        self.on_status = on_status or (lambda _msg: None)

    async def listen_v1(
        self,
        url: str,
        user: str,
        timestamp: str,
        token: str,
        channel: str,
        stop_event=None,
        label: str = "centrifugo",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        uid_connect = str(uuid.uuid4())
        uid_sub = str(uuid.uuid4())
        async with websockets.connect(url, ping_interval=25, ping_timeout=20, additional_headers=extra_headers or {}) as ws:
            await ws.send(
                json.dumps(
                    {
                        "uid": uid_connect,
                        "method": "connect",
                        "params": {
                            "user": str(user),
                            "timestamp": str(timestamp),
                            "info": "",
                            "token": token,
                        },
                    }
                )
            )
            await ws.send(
                json.dumps(
                    {
                        "uid": uid_sub,
                        "method": "subscribe",
                        "params": {"channel": channel},
                    }
                )
            )
            self.on_status(f"{label}: subscribed {channel}")
            while stop_event is None or not stop_event.is_set():
                try:
                    raw = await ws.recv()
                except Exception:
                    break
                self._dispatch(raw)

    async def listen_v2(
        self,
        url: str,
        token: str,
        channel: str,
        stop_event=None,
        label: str = "centrifugo",
        extra_headers: dict[str, str] | None = None,
        subscribe_token: str = "",
    ) -> None:
        async with websockets.connect(url, ping_interval=25, ping_timeout=20, additional_headers=extra_headers or {}) as ws:
            await ws.send(json.dumps({"id": 1, "connect": {"token": token, "name": "cs2-donate"}}))
            hello = _as_dict(await ws.recv()) or {}
            if hello.get("error"):
                raise RuntimeError(str(hello.get("error")))
            sub: dict = {"channel": channel}
            if subscribe_token:
                sub["token"] = subscribe_token
            await ws.send(json.dumps({"id": 2, "subscribe": sub}))
            self.on_status(f"{label}: subscribed {channel}")
            while stop_event is None or not stop_event.is_set():
                try:
                    raw = await ws.recv()
                except Exception:
                    break
                self._dispatch(raw)

    def _dispatch(self, raw: str | bytes) -> None:
        payload = _as_dict(raw)
        if payload is None:
            return
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict):
                continue
            method = str(item.get("method") or "")
            if method in {"message", "publication", "pub"}:
                body = item.get("body") or item.get("params") or item
                data = body.get("data") if isinstance(body, dict) else body
                if isinstance(data, dict):
                    self.on_publication(data)
                continue
            result = item.get("result")
            if isinstance(result, dict):
                data = result.get("data") or result.get("pub") or result
                if isinstance(data, dict):
                    inner = data.get("data") if isinstance(data.get("data"), dict) else data
                    if isinstance(inner, dict) and inner:
                        self.on_publication(inner)
            push = item.get("push")
            if isinstance(push, dict):
                pub = push.get("pub") or push.get("data") or push
                if isinstance(pub, dict):
                    data = pub.get("data") if isinstance(pub.get("data"), dict) else pub
                    if isinstance(data, dict):
                        self.on_publication(data)


def unix_ts() -> str:
    return str(int(time.time()))
