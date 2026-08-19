from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse

from src.donations.models import Donation


def parse_amount(value) -> float:
    if value is None or value is False:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "").replace("\xa0", "").replace("₽", "")
    text = text.replace("RUB", "").replace("RUR", "").replace("руб.", "").replace("руб", "")
    text = text.replace(",", ".")
    if not text:
        return 0.0
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return 0.0
    try:
        return float(match.group(0))
    except ValueError:
        return 0.0


def truthy(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def extract_token(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if "://" in raw or "token=" in raw or "access_token=" in raw:
        parsed = urlparse(raw)
        query = parse_qs(parsed.query)
        fragment = parse_qs(parsed.fragment)
        for key in ("token", "api_token", "access_token", "key", "widget_token", "secret"):
            if query.get(key):
                return query[key][0].strip()
            if fragment.get(key):
                return fragment[key][0].strip()
        path = parsed.path.rstrip("/").split("/")
        if path and path[-1] and path[-1] not in {
            "widget",
            "widgets",
            "alert",
            "alerts",
            "overlay",
            "alert-box",
            "notifications",
        }:
            return path[-1]
    return raw


def unwrap_payload(args) -> dict | list | None:
    if args is None:
        return None
    if isinstance(args, (list, tuple)):
        if not args:
            return None
        data = args[0] if len(args) == 1 else next((item for item in args if item not in (None, "")), args[0])
    else:
        data = args
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


def iter_donation_dicts(payload) -> list[dict]:
    if payload is None:
        return []
    if isinstance(payload, list):
        result: list[dict] = []
        for item in payload:
            result.extend(iter_donation_dicts(item))
        return result
    if not isinstance(payload, dict):
        return []
    for key in ("notification", "donation", "donate", "alert", "vars"):
        nested = payload.get(key)
        if isinstance(nested, dict) and _looks_like_donation(nested):
            return [nested]
        if isinstance(nested, dict):
            inner = iter_donation_dicts(nested)
            if inner:
                return inner
    if "data" in payload and payload["data"] is not payload:
        inner = iter_donation_dicts(payload["data"])
        if inner:
            return inner
    if _looks_like_donation(payload):
        return [payload]
    return []


def _looks_like_donation(payload: dict) -> bool:
    keys = {
        "amount",
        "amount_main",
        "amount_formatted",
        "sum",
        "value",
        "username",
        "_is_test_alert",
        "comment",
        "message",
    }
    return any(key in payload for key in keys)


def donation_from_payload(payload: dict, source: str) -> Donation | None:
    if not isinstance(payload, dict):
        return None
    amount = parse_amount(payload.get("amount_main"))
    if amount <= 0:
        amount = parse_amount(payload.get("amount"))
    if amount <= 0:
        amount = parse_amount(
            payload.get("amount_formatted")
            or payload.get("sum")
            or payload.get("value")
            or payload.get("to_cash")
        )
    currency = str(payload.get("currency") or payload.get("currency_code") or "RUB").upper().replace("RUR", "RUB")
    if currency in {"", "₽", "РУБ", "RUBLES"}:
        currency = "RUB"
    username = str(
        payload.get("username")
        or payload.get("name")
        or payload.get("user_name")
        or payload.get("nickname")
        or payload.get("what")
        or "Аноним"
    )
    message = str(payload.get("message") or payload.get("comment") or payload.get("text") or "")
    donation_id = str(
        payload.get("id")
        or payload.get("donation_id")
        or payload.get("alert_id")
        or payload.get("transaction_id")
        or ""
    ).strip()
    is_test = truthy(payload.get("_is_test_alert") or payload.get("is_test") or payload.get("test"))
    alert_type = str(payload.get("alert_type") or payload.get("type") or "1")
    if alert_type.lower() in {"follow", "subscription", "raid", "host", "cheer"} and amount <= 0:
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
