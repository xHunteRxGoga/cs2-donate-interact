from __future__ import annotations

import ctypes
import random
import subprocess
import time
from typing import Any

from src.effects.input_win import (
    INPUT,
    click_mouse,
    describe_hwnd,
    find_window_by_process,
    find_window_by_title,
    force_foreground,
    foreground_title,
    is_admin,
    kernel32,
    key_down,
    key_up,
    move_mouse,
    tap_key,
    user32,
    _log,
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


def diagnose_cs2(cfg: dict[str, Any], hook_ok: bool | None = None) -> str:
    hwnd = find_cs2_hwnd(cfg)
    fg = user32.GetForegroundWindow()
    parts = [
        f"админ={'да' if is_admin() else 'НЕТ — запусти run-admin.bat'}",
        f"sizeof(INPUT)={ctypes.sizeof(INPUT)}",
        f"CS2 процесс={'да' if is_cs2_running(cfg['cs2']['process_name']) else 'нет'}",
        f"окно CS2: {describe_hwnd(hwnd)}",
        f"фокус: {describe_hwnd(fg)}",
        f"CS2_в_фокусе={'да' if hwnd and fg == hwnd else 'нет'}",
        f"наш_PID={kernel32.GetCurrentProcessId()}",
    ]
    if hook_ok is not None:
        parts.append(f"хук={'да' if hook_ok else 'нет'}")
    return " | ".join(parts)


def prepare_cs2_input(cfg: dict[str, Any]) -> None:
    hwnd = find_cs2_hwnd(cfg)
    if not hwnd:
        raise RuntimeError("Окно CS2 не найдено. Включи игру в режиме «Во весь экран в окне».")
    _log(f"prepare: {diagnose_cs2(cfg)}")
    if user32.GetForegroundWindow() == hwnd:
        _log("CS2 уже в фокусе, клавиши пойдут в игру")
        return
    ok = force_foreground(hwnd)
    time.sleep(0.15)
    fg = user32.GetForegroundWindow()
    if fg != hwnd:
        _log(f"ВНИМАНИЕ: CS2 не в фокусе после попытки. Клавиши уйдут в: {describe_hwnd(fg)}")
    elif ok:
        _log("CS2 поднят в фокус")


def drop_weapon(cfg: dict[str, Any]) -> None:
    key = cfg["cs2"]["keys"]["drop"]
    prepare_cs2_input(cfg)
    _log(f"дроп: жму {key!r} два раза (скан-код G=0x22)")
    tap_key(key, 0.12)
    time.sleep(0.18)
    tap_key(key, 0.12)
    _log(f"дроп: готово, фокус {describe_hwnd(user32.GetForegroundWindow())}")


def mouse_jerk(cfg: dict[str, Any]) -> None:
    effect = cfg["effects"]["mouse_jerk"]
    prepare_cs2_input(cfg)
    intensity = int(effect.get("intensity", 900))
    jerks = int(effect.get("jerks", 7))
    interval = int(effect.get("interval_ms", 40)) / 1000
    _log(f"срыв сенсы: jerks={jerks} intensity={intensity}")
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
    _log(f"срыв сенсы: готово, фокус {describe_hwnd(user32.GetForegroundWindow())}")


def nade_and_crouch(cfg: dict[str, Any]) -> None:
    keys = cfg["cs2"]["keys"]
    effect = cfg["effects"]["nade_and_crouch"]
    prepare_cs2_input(cfg)
    throw = keys.get("nade_throw") or "rbutton"
    select = keys["grenade"]
    crouch = keys["crouch"]
    _log(f"граната: слот={select!r} бросок={throw!r} присед={crouch!r}")
    crouched = False
    try:
        tap_key(select, 0.12)
        time.sleep(float(effect.get("draw_sec", 0.65)))
        key_down(crouch)
        crouched = True
        time.sleep(0.12)
        look = int(effect.get("look_down_pixels", 4200))
        chunk = max(180, look // 10)
        remaining = look
        while remaining > 0:
            step = min(chunk, remaining)
            move_mouse(0, step)
            remaining -= step
            time.sleep(0.012)
        time.sleep(0.12)
        click_mouse(throw, float(effect.get("throw_hold_sec", 0.28)))
        time.sleep(0.08)
        click_mouse("left", 0.14)
        time.sleep(float(effect.get("crouch_hold_sec", 1.2)))
    finally:
        if crouched:
            try:
                key_up(crouch)
            except Exception:
                pass
    _log(f"граната: готово, фокус {describe_hwnd(user32.GetForegroundWindow())}")


def kill_cs2(process_name: str = "cs2.exe") -> None:
    _log(f"закрываю процесс {process_name}")
    subprocess.run(
        ["taskkill", "/IM", process_name, "/F"],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
