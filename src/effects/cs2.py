from __future__ import annotations

import random
import subprocess
import time
from typing import Any

from src.effects.input_win import (
    click_mouse,
    find_window_by_title,
    focus_window,
    foreground_title,
    key_down,
    key_up,
    move_mouse,
    tap_key,
)


def is_cs2_running(process_name: str = "cs2.exe") -> bool:
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {process_name}"],
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        return False
    return process_name.lower() in out.lower()


def is_cs2_focused(window_title: str = "Counter-Strike 2") -> bool:
    return window_title.lower() in foreground_title().lower()


def focus_cs2(window_title: str = "Counter-Strike 2") -> bool:
    hwnd = find_window_by_title(window_title)
    if not hwnd:
        return False
    focus_window(hwnd)
    return True


def drop_weapon(cfg: dict[str, Any]) -> None:
    focus_cs2(cfg["cs2"]["window_title"])
    tap_key(cfg["cs2"]["keys"]["drop"], 0.06)


def mouse_jerk(cfg: dict[str, Any]) -> None:
    effect = cfg["effects"]["mouse_jerk"]
    focus_cs2(cfg["cs2"]["window_title"])
    intensity = int(effect.get("intensity", 900))
    jerks = int(effect.get("jerks", 7))
    interval = int(effect.get("interval_ms", 40)) / 1000
    for _ in range(jerks):
        dx = random.randint(-intensity, intensity)
        dy = random.randint(-intensity, intensity)
        if abs(dx) < intensity // 4:
            dx = intensity if dx >= 0 else -intensity
        move_mouse(dx, dy)
        time.sleep(interval)


def nade_and_crouch(cfg: dict[str, Any]) -> None:
    keys = cfg["cs2"]["keys"]
    effect = cfg["effects"]["nade_and_crouch"]
    focus_cs2(cfg["cs2"]["window_title"])
    tap_key(keys["grenade"], 0.05)
    time.sleep(0.12)
    move_mouse(0, int(effect.get("look_down_pixels", 3200)))
    time.sleep(0.08)
    click_mouse(0.08)
    time.sleep(0.05)
    key_down(keys["crouch"])
    time.sleep(float(effect.get("crouch_hold_sec", 1.2)))
    key_up(keys["crouch"])


def kill_cs2(process_name: str = "cs2.exe") -> None:
    subprocess.run(
        ["taskkill", "/IM", process_name, "/F"],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
