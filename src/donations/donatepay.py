from __future__ import annotations

import asyncio
import threading
from typing import Callable

import httpx

from src.donations.models import Donation


DP_API = "https://donatepay.ru/api/v1"


class DonatePayClient:
    def __init__(self, on_donation: Callable[[Donation], None], on_status: Callable[[str], None]) -> None:
        self.on_donation = on_donation
        self.on_status = on_status
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.api_token = ""
        self.poll_interval_sec = 20.0
        self.currency = "RUB"
        self._seen: set[str] = set()

    def start(self, api_token: str, poll_interval_sec: float = 20.0, currency: str = "RUB") -> None:
        self.stop()
        self.api_token = api_token.strip()
        self.poll_interval_sec = max(15.0, float(poll_interval_sec or 20))
        self.currency = currency or "RUB"
        if not self.api_token:
            self.on_status("DonatePay: нет API-токена")
            return
        self._stop.clear()
        self._seen.clear()
        self._thread = threading.Thread(target=self._run, name="donatepay", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        try:
            asyncio.run(self._poll_loop())
        except Exception as exc:
            self.on_status(f"DonatePay ошибка: {exc}")

    async def _poll_loop(self) -> None:
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
                if user.get("status") != "success":
                    self.on_status(f"DonatePay: {user.get('message') or user.get('status') or 'токен не принят'}")
                    return
                name = (user.get("data") or {}).get("name") or (user.get("data") or {}).get("id") or "стример"
                self.on_status(f"DonatePay: вход как {name}, опрос раз в {self.poll_interval_sec:.0f} сек")
            except Exception as exc:
                self.on_status(f"DonatePay: не удалось проверить токен ({exc}), пробую опрос донатов")

            while not self._stop.is_set():
                try:
                    resp = await client.get(f"{DP_API}/transactions", params=params)
                    resp.raise_for_status()
                    payload = resp.json()
                    if payload.get("status") not in (None, "success"):
                        self.on_status(f"DonatePay API: {payload.get('message') or payload.get('status')}")
                    for row in payload.get("data") or []:
                        self._handle_row(row, bootstrap)
                    bootstrap = False
                except Exception as exc:
                    self.on_status(f"DonatePay опрос: {exc}")
                await asyncio.sleep(self.poll_interval_sec)

    def _handle_row(self, row: dict, bootstrap: bool) -> None:
        if str(row.get("status") or "").lower() not in {"", "success"}:
            return
        if str(row.get("type") or "donation").lower() not in {"", "donation"}:
            return
        donation_id = str(row.get("id") or "")
        if donation_id and donation_id in self._seen:
            return
        if donation_id:
            self._seen.add(donation_id)
        if bootstrap:
            return
        vars_ = row.get("vars") if isinstance(row.get("vars"), dict) else {}
        username = str(vars_.get("name") or row.get("what") or row.get("name") or "Аноним")
        message = str(row.get("comment") or vars_.get("comment") or "")
        amount = float(row.get("sum") or vars_.get("sum") or 0)
        currency = str(row.get("currency") or vars_.get("currency") or self.currency)
        self.on_donation(
            Donation(
                username=username,
                amount=amount,
                currency=currency,
                message=message,
                source="donatepay",
                donation_id=donation_id,
            )
        )
