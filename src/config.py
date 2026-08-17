from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_PATH = ROOT / "config.example.json"
CONFIG_PATH = ROOT / "config.json"
SECRETS_PATH = ROOT / "secrets.json"

DEFAULTS: dict[str, Any] = {
    "general": {
        "enabled": True,
        "require_cs2_running": True,
        "require_cs2_focused": False,
        "queue_mode": "queue",
        "max_queue": 5,
        "global_cooldown_sec": 8,
        "amount_mode": "exact",
        "currency": "RUB",
        "kill_switch": "alt+5",
        "panic_hotkey": "ctrl+alt+5",
    },
    "donationalerts": {
        "access_token": "",
        "client_id": "",
        "client_secret": "",
        "redirect_uri": "http://127.0.0.1:53682/callback",
        "mode": "websocket",
    },
    "webhook": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8765,
    },
    "cs2": {
        "process_name": "cs2.exe",
        "window_title": "Counter-Strike 2",
        "keys": {
            "drop": "g",
            "grenade": "4",
            "crouch": "ctrl",
            "fire": "lbutton",
            "forward": "w",
            "back": "s",
            "left": "a",
            "right": "d",
        },
    },
    "effects": {
        "flash": {
            "enabled": True,
            "amount": 100,
            "duration_sec": 8,
            "cooldown_sec": 20,
            "mode": "gamma_and_overlay",
            "fade_out_sec": 1.5,
        },
        "drop_weapon": {"enabled": True, "amount": 200, "cooldown_sec": 15},
        "mouse_jerk": {
            "enabled": True,
            "amount": 300,
            "cooldown_sec": 15,
            "intensity": 900,
            "jerks": 7,
            "interval_ms": 40,
        },
        "block_wasd": {
            "enabled": True,
            "amount": 400,
            "duration_sec": 10,
            "cooldown_sec": 25,
        },
        "nade_and_crouch": {
            "enabled": True,
            "amount": 500,
            "cooldown_sec": 30,
            "look_down_pixels": 3200,
            "crouch_hold_sec": 1.2,
        },
        "kill_cs2": {"enabled": True, "amount": 1000, "cooldown_sec": 180},
        "minecraft_takeover": {
            "enabled": True,
            "amount": 10000,
            "cooldown_sec": 600,
            "video_path": "assets/minecraft_letsplay.mp4",
            "youtube_url": "",
            "block_input": True,
        },
    },
}

EFFECT_ORDER = [
    "flash",
    "drop_weapon",
    "mouse_jerk",
    "block_wasd",
    "nade_and_crouch",
    "kill_cs2",
    "minecraft_takeover",
]

EFFECT_TITLES = {
    "flash": "Флешка на весь экран",
    "drop_weapon": "Дроп оружия",
    "mouse_jerk": "Срыв сенсы",
    "block_wasd": "Блок WASD",
    "nade_and_crouch": "Граната под ноги + присед",
    "kill_cs2": "Вылет CS2",
    "minecraft_takeover": "Minecraft летсплей",
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def ensure_config() -> Path:
    if not CONFIG_PATH.exists():
        if EXAMPLE_PATH.exists():
            shutil.copy(EXAMPLE_PATH, CONFIG_PATH)
        else:
            CONFIG_PATH.write_text(
                json.dumps(DEFAULTS, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    return CONFIG_PATH


def load_config() -> dict[str, Any]:
    ensure_config()
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    data = _merge(DEFAULTS, raw)
    if SECRETS_PATH.exists():
        secrets = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
        token = secrets.get("donationalerts_access_token", "")
        if token:
            data["donationalerts"]["access_token"] = token
        for key in ("client_id", "client_secret"):
            if secrets.get(f"donationalerts_{key}"):
                data["donationalerts"][key] = secrets[f"donationalerts_{key}"]
    return data


def save_config(data: dict[str, Any]) -> None:
    payload = deepcopy(data)
    secrets = {
        "donationalerts_access_token": payload["donationalerts"].get("access_token", ""),
        "donationalerts_client_id": payload["donationalerts"].get("client_id", ""),
        "donationalerts_client_secret": payload["donationalerts"].get("client_secret", ""),
    }
    payload["donationalerts"]["access_token"] = ""
    payload["donationalerts"]["client_id"] = ""
    payload["donationalerts"]["client_secret"] = ""
    CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    SECRETS_PATH.write_text(json.dumps(secrets, ensure_ascii=False, indent=2), encoding="utf-8")


def get_effect(data: dict[str, Any], effect_id: str) -> dict[str, Any]:
    return data["effects"][effect_id]


def resolve_video_path(data: dict[str, Any]) -> Path:
    raw = data["effects"]["minecraft_takeover"].get("video_path") or "assets/minecraft_letsplay.mp4"
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path
