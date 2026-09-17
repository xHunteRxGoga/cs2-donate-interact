from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx

from src.config import ROOT, SESSION_PATH


@dataclass(slots=True)
class AccessUser:
    id: int
    username: str
    token: str
    is_admin: bool
    access_until: str | None
    access_active: bool

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> AccessUser:
        return cls(
            id=int(data.get("id") or 0),
            username=str(data.get("username") or ""),
            token=str(data.get("token") or ""),
            is_admin=bool(data.get("is_admin")),
            access_until=data.get("access_until"),
            access_active=bool(data.get("access_active")),
        )


def _friendly_http_error(base_url: str, exc: Exception) -> str:
    host = base_url or "сервер"
    if "127.0.0.1" in host or "localhost" in host.lower():
        hint = (
            f"Не достучались до {host}. Сейчас в config.json указан этот компьютер, "
            "а API должен крутиться на VPS. Поставь server/install_access.sh на Ubuntu и пропиши "
            '"access": { "server": "http://IP_СЕРВЕРА:8767" }.'
        )
    else:
        hint = (
            f"Не достучались до {host}. Проверь: на VPS запущен access-api (порт 8767), "
            "в панели Jino открыт TCP 8767, curl http://IP:8767/health с ПК."
        )
    code = getattr(getattr(exc, "response", None), "status_code", None)
    if code:
        return f"{hint} (ответ сервера: {code})"
    return f"{hint} ({exc})"


def _normalize_base(url: str) -> str:
    raw = (url or "").strip().rstrip("/")
    if not raw:
        return ""
    if not raw.startswith("http"):
        raw = "http://" + raw
    return raw


class AccessClient:
    def __init__(self, base_url: str, log: Callable[[str], None] | None = None) -> None:
        self.base_url = _normalize_base(base_url)
        self.log = log or (lambda _m: None)
        self.user: AccessUser | None = None
        self._load_session()

    def _headers(self) -> dict[str, str]:
        if not self.user or not self.user.token:
            return {}
        return {"Authorization": f"Bearer {self.user.token}"}

    def _post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.base_url:
            return {"ok": False, "error": "не указан адрес сервера доступа"}
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(f"{self.base_url}{path}", json=payload or {}, headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, dict) else {"ok": False, "error": "bad response"}
        except httpx.HTTPStatusError as exc:
            return {"ok": False, "error": _friendly_http_error(self.base_url, exc)}
        except httpx.HTTPError as exc:
            return {"ok": False, "error": _friendly_http_error(self.base_url, exc)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _get(self, path: str) -> dict[str, Any]:
        if not self.base_url:
            return {"ok": False, "error": "не указан адрес сервера доступа"}
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(f"{self.base_url}{path}", headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, dict) else {"ok": False, "error": "bad response"}
        except httpx.HTTPStatusError as exc:
            return {"ok": False, "error": _friendly_http_error(self.base_url, exc)}
        except httpx.HTTPError as exc:
            return {"ok": False, "error": _friendly_http_error(self.base_url, exc)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def register(self, username: str, password: str) -> tuple[bool, str]:
        data = self._post("/register", {"username": username, "password": password})
        if data.get("ok"):
            return True, str(data.get("message") or "зарегистрировано")
        return False, str(data.get("error") or "ошибка регистрации")

    def login(self, username: str, password: str, *, admin: bool = False) -> tuple[bool, str]:
        path = "/admin/login" if admin else "/login"
        data = self._post(path, {"username": username, "password": password})
        if not data.get("ok"):
            return False, str(data.get("error") or "ошибка входа")
        user = data.get("user") or {}
        token = str(user.get("token") or "")
        if not token:
            return False, "сервер не вернул токен"
        self.user = AccessUser.from_payload({**user, "token": token})
        self._save_session()
        return True, "ok"

    def refresh(self) -> tuple[bool, str]:
        if not self.user:
            return False, "не авторизован"
        data = self._get("/me")
        if not data.get("ok"):
            self.logout()
            return False, str(data.get("error") or "сессия истекла")
        user = data.get("user") or {}
        self.user = AccessUser.from_payload({**user, "token": self.user.token})
        self._save_session()
        return True, "ok"

    def list_users(self) -> tuple[list[dict[str, Any]], str]:
        data = self._get("/admin/users")
        if not data.get("ok"):
            return [], str(data.get("error") or "ошибка")
        users = data.get("users") or []
        return list(users) if isinstance(users, list) else [], ""

    def grant(self, user_id: int, days: int) -> tuple[bool, str]:
        data = self._post("/admin/grant", {"user_id": user_id, "days": days})
        if data.get("ok"):
            return True, "доступ выдан"
        return False, str(data.get("error") or "ошибка")

    def revoke(self, user_id: int) -> tuple[bool, str]:
        data = self._post("/admin/revoke", {"user_id": user_id})
        if data.get("ok"):
            return True, "доступ снят"
        return False, str(data.get("error") or "ошибка")

    @property
    def access_active(self) -> bool:
        return bool(self.user and (self.user.is_admin or self.user.access_active))

    def logout(self) -> None:
        self.user = None
        try:
            if SESSION_PATH.exists():
                SESSION_PATH.unlink()
        except OSError:
            pass

    def _save_session(self) -> None:
        if not self.user:
            return
        payload = {
            "base_url": self.base_url,
            "user": {
                "id": self.user.id,
                "username": self.user.username,
                "token": self.user.token,
                "is_admin": self.user.is_admin,
                "access_until": self.user.access_until,
                "access_active": self.user.access_active,
            },
        }
        SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        SESSION_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_session(self) -> None:
        if not SESSION_PATH.exists():
            return
        try:
            raw = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if str(raw.get("base_url") or "") != self.base_url:
            return
        user = raw.get("user") or {}
        token = str(user.get("token") or "")
        if not token:
            return
        self.user = AccessUser.from_payload({**user, "token": token})
