from __future__ import annotations

import asyncio
import json
import threading
from typing import Callable
from urllib.parse import urlparse, urlunparse

import websockets

from src.donations.linkstate import LinkState


class VoiceLink:
    def __init__(
        self,
        on_say: Callable[[str, str], None],
        on_status: Callable[[str], None],
        role: str = "streamer",
        name: str = "",
    ) -> None:
        self.on_say = on_say
        self.on_status = on_status
        self.role = role
        self.name = name or ("стример" if role == "streamer" else "чат")
        self.link = LinkState("Голос")
        self.connected = False
        self._stop = threading.Event()
        self._generation = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws = None
        self.url = ""
        self.token = ""

    def start(self, url: str, token: str) -> None:
        self._generation += 1
        gen = self._generation
        self._stop.set()
        self.url = normalize_ws_url(url)
        self.token = (token or "").strip()
        self.connected = False
        if not self.url or not self.token:
            self.link.set("off", "нет адреса сервера или ключа")
            self.on_status("Голос: вставь адрес сервера и общий ключ.")
            return
        self.link.set("wait", "подключаюсь к голосовому серверу…")
        self._stop.clear()
        threading.Thread(target=self._run, args=(gen,), name=f"voice-{self.role}", daemon=True).start()

    def stop(self) -> None:
        self._generation += 1
        self._stop.set()
        self.connected = False
        self.link.set("off", "остановлен")
        loop = self._loop
        ws = self._ws
        if loop and ws:
            try:
                asyncio.run_coroutine_threadsafe(ws.close(), loop)
            except Exception:
                pass

    def send_say(self, text: str) -> bool:
        clean = " ".join((text or "").split())
        if not clean:
            return False
        loop = self._loop
        ws = self._ws
        if not loop or not ws:
            self.on_status("Голос: нет связи со стримером / сервером")
            return False
        try:
            asyncio.run_coroutine_threadsafe(
                ws.send(json.dumps({"type": "say", "text": clean, "from": self.name}, ensure_ascii=False)),
                loop,
            )
            return True
        except Exception as exc:
            self.on_status(f"Голос: не отправилось ({exc})")
            return False

    def _run(self, gen: int) -> None:
        try:
            asyncio.run(self._main(gen))
        except Exception as exc:
            if gen == self._generation:
                self.link.set("bad", str(exc))
                self.on_status(f"Голос ошибка: {exc}")

    async def _main(self, gen: int) -> None:
        self._loop = asyncio.get_running_loop()
        while gen == self._generation and not self._stop.is_set():
            try:
                async with websockets.connect(
                    self.url,
                    ping_interval=20,
                    ping_timeout=20,
                    open_timeout=10,
                    additional_headers={"Origin": "https://cs2-donate-interact"},
                ) as ws:
                    self._ws = ws
                    await ws.send(
                        json.dumps(
                            {
                                "type": "hello",
                                "role": self.role,
                                "token": self.token,
                                "name": self.name,
                            },
                            ensure_ascii=False,
                        )
                    )
                    raw = await asyncio.wait_for(ws.recv(), timeout=8)
                    hello = json.loads(raw) if isinstance(raw, str) else {}
                    if hello.get("type") == "error":
                        self.link.set("bad", str(hello.get("message") or "отклонено"))
                        self.on_status(f"Голос: {hello.get('message')}")
                        return
                    self.connected = True
                    n = int(hello.get("streamers") or 0)
                    self.link.set("live", f"сервер на связи, стримеров: {n}")
                    if self.role == "director":
                        if n:
                            self.on_status(f"Голос: подключено, стример онлайн")
                        else:
                            self.on_status("Голос: подключено, стример ещё не зашёл")
                    else:
                        self.on_status("Голос: подключено к серверу")
                    async for message in ws:
                        if gen != self._generation:
                            return
                        self._handle(message)
            except Exception as exc:
                self.connected = False
                self._ws = None
                if gen != self._generation or self._stop.is_set():
                    return
                self.link.set("wait", f"переподключение ({exc})")
                self.on_status(f"Голос: связь оборвалась, повтор через 4 сек ({exc})")
                await asyncio.sleep(4)
        self._ws = None

    def _handle(self, raw) -> None:
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict):
            return
        kind = str(data.get("type") or "")
        if kind == "say":
            text = str(data.get("text") or "")
            who = str(data.get("from") or "чат")
            self.link.set("live", f"последнее: {who}")
            self.on_say(who, text)
        elif kind == "status":
            n = int(data.get("streamers") or 0)
            self.link.set("live", f"стримеров онлайн: {n}")
            if self.role == "director":
                if n:
                    self.on_status("Голос: подключено, стример онлайн")
                else:
                    self.on_status("Голос: подключено, стример ещё не зашёл")
        elif kind == "error":
            self.on_status(f"Голос: {data.get('message')}")
        elif kind == "delivered":
            n = int(data.get("streamers") or 0)
            if n <= 0:
                self.on_status("Голос: стример сейчас не в сети")


def normalize_ws_url(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if raw.startswith("http://"):
        raw = "ws://" + raw[len("http://") :]
    elif raw.startswith("https://"):
        raw = "wss://" + raw[len("https://") :]
    elif "://" not in raw:
        raw = "ws://" + raw
    parsed = urlparse(raw)
    if not parsed.hostname:
        return raw
    port = parsed.port or (443 if parsed.scheme == "wss" else 8766)
    netloc = parsed.hostname
    if port not in (80, 443) or parsed.port:
        netloc = f"{parsed.hostname}:{port}"
    path = parsed.path or ""
    if path == "/":
        path = ""
    return urlunparse((parsed.scheme, netloc, path, "", parsed.query, ""))
