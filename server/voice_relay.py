#!/usr/bin/env python3
"""Релей голосового чата для Ubuntu. Стример и ты подключаетесь сюда."""

from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import os
import time
from collections import defaultdict

import websockets

MAX_TEXT = 400
RATE_N = 8
RATE_SEC = 10.0


class Relay:
    def __init__(self, token: str) -> None:
        self.token = token
        self.streamers: set = set()
        self.directors: set = set()
        self.hits: dict[int, list[float]] = defaultdict(list)

    async def handler(self, ws) -> None:
        role = ""
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=12)
            hello = json.loads(raw)
        except Exception:
            await _send(ws, {"type": "error", "message": "нет hello"})
            return
        if not _token_ok(self.token, str(hello.get("token") or "")):
            await _send(ws, {"type": "error", "message": "неверный ключ"})
            return
        role = str(hello.get("role") or "")
        name = str(hello.get("name") or role)[:40]
        if role not in {"streamer", "director"}:
            await _send(ws, {"type": "error", "message": "role = streamer или director"})
            return
        bucket = self.streamers if role == "streamer" else self.directors
        bucket.add(ws)
        await _send(ws, {"type": "welcome", "streamers": len(self.streamers), "directors": len(self.directors)})
        await self._broadcast_status()
        print(f"+ {role} {name}  streamers={len(self.streamers)} directors={len(self.directors)}", flush=True)
        try:
            async for message in ws:
                await self._on_message(ws, role, name, message)
        except Exception:
            pass
        finally:
            bucket.discard(ws)
            await self._broadcast_status()
            print(f"- {role} {name}  streamers={len(self.streamers)} directors={len(self.directors)}", flush=True)

    async def _on_message(self, ws, role: str, name: str, raw) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict) or data.get("type") != "say":
            return
        if role != "director":
            await _send(ws, {"type": "error", "message": "говорить может только чат"})
            return
        if not self._rate_ok(id(ws)):
            await _send(ws, {"type": "error", "message": "слишком часто"})
            return
        text = " ".join(str(data.get("text") or "").split())[:MAX_TEXT]
        if not text:
            return
        who = str(data.get("from") or name)[:40]
        packet = json.dumps({"type": "say", "text": text, "from": who}, ensure_ascii=False)
        if not self.streamers:
            await _send(ws, {"type": "delivered", "streamers": 0})
            return
        await asyncio.gather(*(_safe_send(s, packet) for s in list(self.streamers)))
        await _send(ws, {"type": "delivered", "streamers": len(self.streamers)})

    async def _broadcast_status(self) -> None:
        packet = json.dumps({"type": "status", "streamers": len(self.streamers), "directors": len(self.directors)})
        peers = list(self.streamers | self.directors)
        if peers:
            await asyncio.gather(*(_safe_send(ws, packet) for ws in peers))

    def _rate_ok(self, key: int) -> bool:
        now = time.monotonic()
        stamp = [t for t in self.hits[key] if now - t < RATE_SEC]
        if len(stamp) >= RATE_N:
            self.hits[key] = stamp
            return False
        stamp.append(now)
        self.hits[key] = stamp
        return True


async def _send(ws, payload: dict) -> None:
    await _safe_send(ws, json.dumps(payload, ensure_ascii=False))


async def _safe_send(ws, text: str) -> None:
    try:
        await ws.send(text)
    except Exception:
        pass


def _token_ok(expected: str, got: str) -> bool:
    a = (got or "").encode("utf-8")
    b = (expected or "").encode("utf-8")
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


async def main() -> None:
    parser = argparse.ArgumentParser(description="CS2 Donate Interact voice relay")
    parser.add_argument("--host", default=os.environ.get("VOICE_RELAY_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("VOICE_RELAY_PORT", "8766")))
    parser.add_argument("--token", default=os.environ.get("VOICE_RELAY_TOKEN", ""))
    args = parser.parse_args()
    token = (args.token or "").strip()
    if not token:
        raise SystemExit("Задай ключ: --token ... или переменная VOICE_RELAY_TOKEN")
    relay = Relay(token)
    print(f"voice relay ws://{args.host}:{args.port}  token set, waiting…", flush=True)
    async with websockets.serve(relay.handler, args.host, args.port, max_size=8192):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
