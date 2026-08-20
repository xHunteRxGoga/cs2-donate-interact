from __future__ import annotations


class LinkState:
    """Человеческий статус привязки: не путать «токен вставлен» с «донаты реально приходят»."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.state = "off"  # off | wait | live | bad
        self.detail = "не привязан"
        self.last = "донатов ещё не было"

    def set(self, state: str, detail: str) -> None:
        self.state = state
        self.detail = detail

    def mark_donation(self, username: str, amount: float, currency: str) -> None:
        self.state = "live"
        self.last = f"{username} — {amount:g} {currency}"
        self.detail = f"последний донат: {self.last}"

    def label(self) -> str:
        names = {"off": "не привязан", "wait": "подключаюсь", "live": "подключено", "bad": "ошибка"}
        return f"{self.name}: {names.get(self.state, self.state)}"
