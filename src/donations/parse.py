from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse

from src.donations.models import Donation


_AMOUNT_KEYS = (
    "amount_main",
    "amount",
    "amount_formatted",
    "sum",
    "summa",
    "value",
    "to_cash",
    "cash",
    "price",
    "paid",
    "payed",
    "donation_amount",
    "donate_amount",
    "sum_rub",
    "amount_rub",
)

_NAME_KEYS = (
    "username",
    "name",
    "user_name",
    "nickname",
    "nick",
    "what",
    "from",
    "donor",
    "donator",
    "sender",
)

_MESSAGE_KEYS = ("message", "comment", "text", "msg", "donation_message")

_ID_KEYS = ("id", "donation_id", "alert_id", "transaction_id", "uuid", "event_id")


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
    raw = re.sub(r"(?i)секретный\s*токен\s*:?\s*", "", raw).strip()
    raw = re.sub(r"(?i)api[-\s]*ключ\s*:?\s*", "", raw).strip()
    raw = raw.replace("\r", "").replace("\n", "").strip(" '\"")
    if not raw:
        return ""
    if "://" in raw or "token=" in raw or "access_token=" in raw:
        parsed = urlparse(raw)
        query = parse_qs(parsed.query)
        fragment = parse_qs(parsed.fragment)
        for key in (
            "token",
            "api_token",
            "access_token",
            "key",
            "widget_token",
            "secret",
            "widget_id",
            "id",
            "hash",
        ):
            if query.get(key):
                return query[key][0].strip()
            if fragment.get(key):
                return fragment[key][0].strip()
        path = [part for part in parsed.path.rstrip("/").split("/") if part]
        skip = {
            "widget",
            "widgets",
            "alert",
            "alerts",
            "overlay",
            "alert-box",
            "notifications",
            "dp",
            "donate",
            "donation",
            "v1",
            "api",
            "me",
            "w",
            "o",
        }
        if path and path[-1] and path[-1].lower() not in skip:
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
    for _ in range(3):
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
            continue
        break
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
    for key in ("notification", "donation", "donate", "alert", "vars", "event", "payload"):
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
    for key in ("items", "results", "donations", "alerts", "events", "transactions", "last"):
        nested = payload.get(key)
        if isinstance(nested, list) and nested:
            inner = iter_donation_dicts(nested)
            if inner:
                return inner
    if _looks_like_donation(payload):
        return [payload]
    return []


def _looks_like_donation(payload: dict) -> bool:
    keys = set(payload)
    return any(key in keys for key in (*_AMOUNT_KEYS, *_NAME_KEYS, "_is_test_alert", *_MESSAGE_KEYS))


def donation_from_payload(payload: dict, source: str) -> Donation | None:
    if not isinstance(payload, dict):
        return None
    extra = payload.get("additional_data")
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except json.JSONDecodeError:
            extra = None
    nested = payload.get("vars") if isinstance(payload.get("vars"), dict) else {}
    extra_dict = extra if isinstance(extra, dict) else {}
    merged = {**extra_dict, **nested, **payload}
    amount = 0.0
    for key in _AMOUNT_KEYS:
        amount = parse_amount(merged.get(key))
        if amount > 0:
            break
    currency = str(merged.get("currency") or merged.get("currency_code") or "RUB").upper().replace("RUR", "RUB")
    if currency in {"", "₽", "РУБ", "RUBLES", "RUBLE"}:
        currency = "RUB"
    username = "Аноним"
    for key in _NAME_KEYS:
        value = merged.get(key)
        if value not in (None, ""):
            username = str(value)
            break
    message = ""
    for key in _MESSAGE_KEYS:
        value = merged.get(key)
        if value not in (None, ""):
            message = str(value)
            break
    donation_id = ""
    for key in _ID_KEYS:
        value = merged.get(key)
        if value not in (None, ""):
            donation_id = str(value).strip()
            break
    is_test = truthy(merged.get("_is_test_alert") or merged.get("is_test") or merged.get("test"))
    alert_type = str(merged.get("alert_type") or merged.get("type") or "1").lower()
    if alert_type in {"follow", "subscription", "subscriber", "raid", "host", "cheer", "media", "music"} and amount <= 0:
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


def payloads_from_html(html: str) -> list:
    if not html:
        return []
    found: list = []
    for match in re.finditer(
        r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html,
        re.S | re.I,
    ):
        try:
            found.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            continue
    for match in re.finditer(
        r"window\.__[A-Z0-9_]+__\s*=\s*(\{.*?\});\s*(?:</script>|$)",
        html,
        re.S,
    ):
        try:
            found.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            continue
    for match in re.finditer(r"(?:var|let|const)\s+\w*(?:donation|alert|widget)\w*\s*=\s*(\{.*?\}|\[.*?\]);", html, re.S | re.I):
        try:
            found.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            continue
    if not found:
        match = re.search(r"(\{.*\}|\[.*\])", html, re.S)
        if match:
            blob = match.group(1)
            if len(blob) < 400000:
                try:
                    found.append(json.loads(blob))
                except json.JSONDecodeError:
                    pass
    return found
