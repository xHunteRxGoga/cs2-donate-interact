#!/usr/bin/env python3
"""API регистрации, входа и выдачи доступа. SQLite, без лишних зависимостей."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DB_PATH = Path(os.environ.get("ACCESS_DB", Path(__file__).resolve().parent / "access.db"))
ADMIN_USER = os.environ.get("ACCESS_ADMIN_USER", "Rundelman")
ADMIN_SECRET_PATH = Path(
    os.environ.get("ACCESS_ADMIN_SECRET", str(DB_PATH.parent / "admin.secret"))
)
TOKEN_TTL_DAYS = 30
PBKDF2_ITERS = 260_000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERS)
    return digest.hex(), salt.hex()


def _check_password(password: str, digest_hex: str, salt_hex: str) -> bool:
    got, _ = _hash_password(password, bytes.fromhex(salt_hex))
    return secrets.compare_digest(got, digest_hex)


def _admin_password() -> str | None:
    env = (os.environ.get("ACCESS_ADMIN_PASSWORD") or "").strip()
    if env:
        return env
    if ADMIN_SECRET_PATH.is_file():
        try:
            line = ADMIN_SECRET_PATH.read_text(encoding="utf-8").strip()
            return line or None
        except OSError:
            return None
    return None


def _write_admin_secret(password: str) -> None:
    ADMIN_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    ADMIN_SECRET_PATH.write_text(password + "\n", encoding="utf-8")
    try:
        ADMIN_SECRET_PATH.chmod(0o600)
    except OSError:
        pass


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                access_until TEXT,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            """
        )
        row = conn.execute("SELECT id FROM users WHERE username = ? COLLATE NOCASE", (ADMIN_USER,)).fetchone()
        if not row:
            pwd = _admin_password()
            if not pwd:
                pwd = secrets.token_urlsafe(16)
                _write_admin_secret(pwd)
                print(
                    f"[access] Создан админ «{ADMIN_USER}». Пароль только в файле {ADMIN_SECRET_PATH} — "
                    "не клади его в git и не в README.",
                    flush=True,
                )
            digest, salt = _hash_password(pwd)
            conn.execute(
                "INSERT INTO users (username, password_hash, salt, is_admin, access_until, created_at) VALUES (?, ?, ?, 1, NULL, ?)",
                (ADMIN_USER, digest, salt, _iso(_utcnow())),
            )
            conn.commit()


def _user_active(row: sqlite3.Row) -> bool:
    if int(row["is_admin"] or 0):
        return True
    until = _parse_iso(row["access_until"])
    return bool(until and until > _utcnow())


def _public_user(row: sqlite3.Row) -> dict[str, Any]:
    until = row["access_until"]
    active = _user_active(row)
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "is_admin": bool(row["is_admin"]),
        "access_until": until,
        "access_active": active,
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
    }


def _new_token(conn: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    exp = _utcnow() + timedelta(days=TOKEN_TTL_DAYS)
    conn.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, _iso(exp)),
    )
    return token


def _session_user(conn: sqlite3.Connection, token: str) -> sqlite3.Row | None:
    if not token:
        return None
    row = conn.execute(
        """
        SELECT u.* FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token = ? AND s.expires_at > ?
        """,
        (token, _iso(_utcnow())),
    ).fetchone()
    return row


class AccessAPI:
    lock = threading.Lock()

    @classmethod
    def register(cls, username: str, password: str) -> dict[str, Any]:
        username = (username or "").strip()
        password = password or ""
        if len(username) < 3:
            return {"ok": False, "error": "ник минимум 3 символа"}
        if len(password) < 4:
            return {"ok": False, "error": "пароль минимум 4 символа"}
        digest, salt = _hash_password(password)
        with cls.lock, _connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO users (username, password_hash, salt, created_at) VALUES (?, ?, ?, ?)",
                    (username, digest, salt, _iso(_utcnow())),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return {"ok": False, "error": "такой ник уже занят"}
        return {"ok": True, "message": "аккаунт создан. Дождись выдачи доступа админом."}

    @classmethod
    def login(cls, username: str, password: str, admin_only: bool = False) -> dict[str, Any]:
        username = (username or "").strip()
        with cls.lock, _connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                (username,),
            ).fetchone()
            if not row or not _check_password(password, row["password_hash"], row["salt"]):
                return {"ok": False, "error": "неверный логин или пароль"}
            if admin_only and not int(row["is_admin"]):
                return {"ok": False, "error": "это не админский аккаунт"}
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (_iso(_utcnow()), row["id"]))
            token = _new_token(conn, int(row["id"]))
            conn.commit()
            user = _public_user(row)
            user["token"] = token
            return {"ok": True, "user": user}

    @classmethod
    def me(cls, token: str) -> dict[str, Any]:
        with cls.lock, _connect() as conn:
            row = _session_user(conn, token)
            if not row:
                return {"ok": False, "error": "сессия истекла — войди снова"}
            return {"ok": True, "user": _public_user(row)}

    @classmethod
    def list_users(cls, token: str) -> dict[str, Any]:
        with cls.lock, _connect() as conn:
            admin = _session_user(conn, token)
            if not admin or not int(admin["is_admin"]):
                return {"ok": False, "error": "нужен вход админа"}
            rows = conn.execute("SELECT * FROM users WHERE is_admin = 0 ORDER BY id DESC").fetchall()
            return {"ok": True, "users": [_public_user(r) for r in rows]}

    @classmethod
    def grant(cls, token: str, user_id: int, days: int) -> dict[str, Any]:
        days = max(1, min(3650, int(days)))
        with cls.lock, _connect() as conn:
            admin = _session_user(conn, token)
            if not admin or not int(admin["is_admin"]):
                return {"ok": False, "error": "нужен вход админа"}
            row = conn.execute("SELECT * FROM users WHERE id = ? AND is_admin = 0", (user_id,)).fetchone()
            if not row:
                return {"ok": False, "error": "пользователь не найден"}
            base = _parse_iso(row["access_until"])
            now = _utcnow()
            if base and base > now:
                new_until = base + timedelta(days=days)
            else:
                new_until = now + timedelta(days=days)
            conn.execute("UPDATE users SET access_until = ? WHERE id = ?", (_iso(new_until), user_id))
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return {"ok": True, "user": _public_user(row)}

    @classmethod
    def revoke(cls, token: str, user_id: int) -> dict[str, Any]:
        with cls.lock, _connect() as conn:
            admin = _session_user(conn, token)
            if not admin or not int(admin["is_admin"]):
                return {"ok": False, "error": "нужен вход админа"}
            conn.execute("UPDATE users SET access_until = NULL WHERE id = ? AND is_admin = 0", (user_id,))
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                return {"ok": False, "error": "пользователь не найден"}
            return {"ok": True, "user": _public_user(row)}


class Handler(BaseHTTPRequestHandler):
    server_version = "AccessAPI/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[access] {self.address_string()} {fmt % args}", flush=True)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(min(length, 65536))
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _token(self) -> str:
        auth = self.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return (self.headers.get("X-Access-Token") or "").strip()

    def _send(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Access-Token")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Access-Token")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._send(200, {"ok": True})
            return
        if path == "/me":
            self._send(200, AccessAPI.me(self._token()))
            return
        if path == "/admin/users":
            self._send(200, AccessAPI.list_users(self._token()))
            return
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        data = self._read_json()
        if path == "/register":
            self._send(200, AccessAPI.register(str(data.get("username") or ""), str(data.get("password") or "")))
            return
        if path == "/login":
            self._send(
                200,
                AccessAPI.login(str(data.get("username") or ""), str(data.get("password") or ""), admin_only=False),
            )
            return
        if path == "/admin/login":
            self._send(
                200,
                AccessAPI.login(str(data.get("username") or ""), str(data.get("password") or ""), admin_only=True),
            )
            return
        if path == "/admin/grant":
            self._send(
                200,
                AccessAPI.grant(self._token(), int(data.get("user_id") or 0), int(data.get("days") or 0)),
            )
            return
        if path == "/admin/revoke":
            self._send(200, AccessAPI.revoke(self._token(), int(data.get("user_id") or 0)))
            return
        self._send(404, {"ok": False, "error": "not found"})


def main() -> None:
    parser = argparse.ArgumentParser(description="Access API for CS2 Donate Interact")
    parser.add_argument("--host", default=os.environ.get("ACCESS_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("ACCESS_PORT", "8767")))
    args = parser.parse_args()
    init_db()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Access API on http://{args.host}:{args.port}  db={DB_PATH}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
