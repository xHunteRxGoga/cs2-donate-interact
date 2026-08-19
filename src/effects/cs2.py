from __future__ import annotations

import random
import subprocess
import time
from typing import Any

from src.effects.input_win import (
    click_mouse,
    find_window_by_process,
    find_window_by_title,
    force_foreground,
    foreground_title,
    key_down,
    key_up,
    move_mouse,
    tap_key,
    user32,
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


def find_cs2_hwnd(cfg: dict[str, Any]) -> int | None:
    return find_window_by_process(cfg["cs2"]["process_name"]) or find_window_by_title(cfg["cs2"]["window_title"])


def prepare_cs2_input(cfg: dict[str, Any]) -> None:
    hwnd = find_cs2_hwnd(cfg)
    if not hwnd:
        raise RuntimeError("Окно CS2 не найдено. Включи игру в режиме «Во весь экран в окне».")
    if user32.GetForegroundWindow() == hwnd:
        return
    force_foreground(hwnd)
    time.sleep(0.12)


def drop_weapon(cfg: dict[str, Any]) -> None:
    prepare_cs2_input(cfg)
    tap_key(cfg["cs2"]["keys"]["drop"], 0.09)
    time.sleep(0.05)
    tap_key(cfg["cs2"]["keys"]["drop"], 0.09)


def mouse_jerk(cfg: dict[str, Any]) -> None:
    effect = cfg["effects"]["mouse_jerk"]
    prepare_cs2_input(cfg)
    intensity = int(effect.get("intensity", 900))
    jerks = int(effect.get("jerks", 7))
    interval = int(effect.get("interval_ms", 40)) / 1000
    for _ in range(jerks):
        dx = random.randint(-intensity, intensity)
        dy = random.randint(-intensity, intensity)
        if abs(dx) < intensity // 4:
            dx = intensity if dx >= 0 else -intensity
        steps = 4
        for _step in range(steps):
            move_mouse(dx // steps, dy // steps)
            time.sleep(0.008)
        time.sleep(interval)


def nade_and_crouch(cfg: dict[str, Any]) -> None:
    keys = cfg["cs2"]["keys"]
    effect = cfg["effects"]["nade_and_crouch"]
    prepare_cs2_input(cfg)
    tap_key(keys["grenade"], 0.1)
    time.sleep(0.18)
    look = int(effect.get("look_down_pixels", 3200))
    chunk = max(200, look // 8)
    remaining = look
    while remaining > 0:
        step = min(chunk, remaining)
        move_mouse(0, step)
        remaining -= step
        time.sleep(0.01)
    time.sleep(0.08)
    click_mouse(0.1)
    time.sleep(0.06)
    key_down(keys["crouch"])
    time.sleep(float(effect.get("crouch_hold_sec", 1.2)))
    key_up(keys["crouch"])


def kill_cs2(process_name: str = "cs2.exe") -> None:
    subprocess.run(
        ["taskkill", "/IM", process_name, "/F"],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
