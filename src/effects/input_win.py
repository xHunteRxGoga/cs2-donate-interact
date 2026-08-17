from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
from typing import Callable, Iterable


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
LLKHF_ALTDOWN = 0x20

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_ESCAPE = 0x1B
VK_F4 = 0x73
VK_TAB = 0x09
VK_LBUTTON = 0x01

MAPVK_VK_TO_VSC = 0

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_long
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = wintypes.SHORT
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.restype = wintypes.BOOL

NAME_TO_VK = {
    "lbutton": VK_LBUTTON,
    "ctrl": VK_CONTROL,
    "control": VK_CONTROL,
    "alt": VK_MENU,
    "shift": VK_SHIFT,
    "esc": VK_ESCAPE,
    "escape": VK_ESCAPE,
    "tab": VK_TAB,
    "win": VK_LWIN,
    "lwin": VK_LWIN,
    "rwin": VK_RWIN,
    "f4": VK_F4,
    " ": 0x20,
    "space": 0x20,
    "enter": 0x0D,
}


def vk_from_name(name: str) -> int:
    key = name.strip().lower()
    if key in NAME_TO_VK:
        return NAME_TO_VK[key]
    if len(key) == 1:
        return ctypes.windll.user32.VkKeyScanW(ord(key)) & 0xFF
    if key.startswith("f") and key[1:].isdigit():
        return 0x70 + int(key[1:]) - 1
    raise ValueError(f"Неизвестная клавиша: {name}")


def _send(inputs: list[INPUT]) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _key_input(vk: int, up: bool = False) -> INPUT:
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    flags = KEYEVENTF_KEYUP if up else 0
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return inp


def tap_key(name: str, hold_sec: float = 0.04) -> None:
    vk = vk_from_name(name)
    if vk == VK_LBUTTON:
        click_mouse()
        return
    _send([_key_input(vk, False)])
    time.sleep(hold_sec)
    _send([_key_input(vk, True)])


def key_down(name: str) -> None:
    vk = vk_from_name(name)
    if vk == VK_LBUTTON:
        _send([_mouse_input(MOUSEEVENTF_LEFTDOWN)])
        return
    _send([_key_input(vk, False)])


def key_up(name: str) -> None:
    vk = vk_from_name(name)
    if vk == VK_LBUTTON:
        _send([_mouse_input(MOUSEEVENTF_LEFTUP)])
        return
    _send([_key_input(vk, True)])


def _mouse_input(flags: int, dx: int = 0, dy: int = 0) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi = MOUSEINPUT(dx, dy, 0, flags, 0, 0)
    return inp


def move_mouse(dx: int, dy: int) -> None:
    _send([_mouse_input(MOUSEEVENTF_MOVE, int(dx), int(dy))])


def click_mouse(hold_sec: float = 0.05) -> None:
    _send([_mouse_input(MOUSEEVENTF_LEFTDOWN)])
    time.sleep(hold_sec)
    _send([_mouse_input(MOUSEEVENTF_LEFTUP)])


def get_window_title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def find_window_by_title(part: str) -> int | None:
    found = {"hwnd": 0}
    needle = part.lower()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and needle in get_window_title(hwnd).lower():
            found["hwnd"] = hwnd
            return False
        return True

    user32.EnumWindows(callback, 0)
    return found["hwnd"] or None


def focus_window(hwnd: int) -> None:
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.05)


def foreground_title() -> str:
    return get_window_title(user32.GetForegroundWindow())


def parse_hotkey(combo: str) -> tuple[set[str], int]:
    parts = [p.strip().lower() for p in combo.replace(" ", "").split("+") if p.strip()]
    mods = {p for p in parts if p in {"ctrl", "alt", "shift", "win"}}
    keys = [p for p in parts if p not in mods]
    if len(keys) != 1:
        raise ValueError(f"Нужна одна основная клавиша в комбинации: {combo}")
    return mods, vk_from_name(keys[0])


def hotkey_pressed(combo: str, vk_code: int, flags: int) -> bool:
    try:
        mods, vk = parse_hotkey(combo)
    except ValueError:
        return False
    if vk_code != vk:
        return False
    alt = bool(flags & LLKHF_ALTDOWN) or bool(user32.GetAsyncKeyState(VK_MENU) & 0x8000)
    ctrl = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
    shift = bool(user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
    win = bool(user32.GetAsyncKeyState(VK_LWIN) & 0x8000) or bool(user32.GetAsyncKeyState(VK_RWIN) & 0x8000)
    have = set()
    if alt:
        have.add("alt")
    if ctrl:
        have.add("ctrl")
    if shift:
        have.add("shift")
    if win:
        have.add("win")
    return have == mods


class InputGuard:
    """Низкоуровневый хук: аварийный стоп, блок WASD и блок ввода на летсплее."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.blocked_vks: set[int] = set()
        self.block_all = False
        self.kill_switch = "alt+5"
        self.panic_hotkey = "ctrl+alt+5"
        self.on_kill: Callable[[], None] | None = None
        self.on_panic: Callable[[], None] | None = None
        self._hook = None
        self._proc = None
        self._thread: threading.Thread | None = None
        self._running = False

    def set_blocked_keys(self, names: Iterable[str]) -> None:
        with self._lock:
            self.blocked_vks = {vk_from_name(name) for name in names}

    def clear_blocked_keys(self) -> None:
        with self._lock:
            self.blocked_vks.clear()

    def set_block_all(self, value: bool) -> None:
        with self._lock:
            self.block_all = value

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="input-guard", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def _loop(self) -> None:
        self._proc = HOOKPROC(self._callback)
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        msg = wintypes.MSG()
        while self._running:
            user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1)
            time.sleep(0.01)
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def _callback(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code >= 0 and w_param in (WM_KEYDOWN, WM_SYSKEYDOWN, WM_KEYUP, WM_SYSKEYUP):
            info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            is_down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
            if is_down and hotkey_pressed(self.kill_switch, info.vkCode, info.flags):
                if self.on_kill:
                    threading.Thread(target=self.on_kill, daemon=True).start()
                return 1
            if is_down and hotkey_pressed(self.panic_hotkey, info.vkCode, info.flags):
                if self.on_panic:
                    threading.Thread(target=self.on_panic, daemon=True).start()
                return 1
            with self._lock:
                block_all = self.block_all
                blocked = info.vkCode in self.blocked_vks
            if block_all or blocked:
                return 1
        return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)
