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
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MOVE_NOCOALESCE = 0x2000
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
LLKHF_ALTDOWN = 0x20
MAPVK_VK_TO_VSC = 0
MAPVK_VSC_TO_VK = 1
LLKHF_INJECTED = 0x10
SW_RESTORE = 9
SW_SHOW = 5
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
GWL_EXSTYLE = -20

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_ESCAPE = 0x1B
VK_F4 = 0x73
VK_TAB = 0x09
VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_SNAPSHOT = 0x2C
VK_INSERT = 0x2D
VK_DELETE = 0x2E
VK_HOME = 0x24
VK_END = 0x23
VK_PRIOR = 0x21
VK_NEXT = 0x22
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_RMENU = 0xA5
VK_RCONTROL = 0xA3

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
LRESULT = ctypes.c_ssize_t
IS_64 = ctypes.sizeof(ctypes.c_void_p) == 8


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
    if IS_64:
        _fields_ = [("type", wintypes.DWORD), ("_pad", wintypes.DWORD), ("union", INPUT_UNION)]
    else:
        _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = wintypes.SHORT
user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
user32.VkKeyScanW.restype = wintypes.SHORT
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.SetActiveWindow.argtypes = [wintypes.HWND]
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
user32.LockSetForegroundWindow.argtypes = [wintypes.UINT]
user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
if IS_64:
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.restype = wintypes.BOOL
user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ULONG_PTR]
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ULONG_PTR]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.GetCurrentProcessId.restype = wintypes.DWORD
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ASFW_ANY = 0xFFFFFFFF
LSFW_UNLOCK = 2
EXTENDED_VKS = {
    VK_RMENU,
    VK_RCONTROL,
    VK_LWIN,
    VK_RWIN,
    VK_INSERT,
    VK_DELETE,
    VK_HOME,
    VK_END,
    VK_PRIOR,
    VK_NEXT,
    VK_LEFT,
    VK_UP,
    VK_RIGHT,
    VK_DOWN,
    VK_SNAPSHOT,
    VK_TAB,
}

SCAN_BY_NAME = {
    "esc": 0x01,
    "escape": 0x01,
    "1": 0x02,
    "2": 0x03,
    "3": 0x04,
    "4": 0x05,
    "5": 0x06,
    "tab": 0x0F,
    "q": 0x10,
    "w": 0x11,
    "e": 0x12,
    "r": 0x13,
    "t": 0x14,
    "a": 0x1E,
    "s": 0x1F,
    "d": 0x20,
    "f": 0x21,
    "g": 0x22,
    "h": 0x23,
    "z": 0x2C,
    "x": 0x2D,
    "c": 0x2E,
    "v": 0x2F,
    "b": 0x30,
    "ctrl": 0x1D,
    "control": 0x1D,
    "lctrl": 0x1D,
    "lcontrol": 0x1D,
    "shift": 0x2A,
    "space": 0x39,
    " ": 0x39,
    "enter": 0x1C,
}

_log_fn: Callable[[str], None] | None = None


def set_input_logger(fn: Callable[[str], None] | None) -> None:
    global _log_fn
    _log_fn = fn


def _log(text: str) -> None:
    if _log_fn:
        _log_fn(text)


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def get_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def window_size(hwnd: int) -> tuple[int, int]:
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return 0, 0
    return max(0, rect.right - rect.left), max(0, rect.bottom - rect.top)


def describe_hwnd(hwnd: int | None) -> str:
    if not hwnd:
        return "нет окна"
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    w, h = window_size(hwnd)
    title = get_window_title(hwnd) or "(без названия)"
    klass = get_class_name(hwnd) or "?"
    proc = _process_name(pid.value) or "?"
    return f"hwnd=0x{hwnd:X} title={title!r} class={klass!r} proc={proc} pid={pid.value} size={w}x{h}"


NAME_TO_VK = {
    "lbutton": VK_LBUTTON,
    "rbutton": VK_RBUTTON,
    "mouse2": VK_RBUTTON,
    "ctrl": VK_CONTROL,
    "control": VK_CONTROL,
    "lctrl": VK_CONTROL,
    "rctrl": VK_RCONTROL,
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

for _code in range(ord("a"), ord("z") + 1):
    NAME_TO_VK[chr(_code)] = _code - 32  # VK_A=0x41
for _digit, _vk in enumerate(range(0x30, 0x3A)):
    NAME_TO_VK[str(_digit)] = _vk


def vk_from_name(name: str) -> int:
    key = name.strip().lower()
    if key in NAME_TO_VK:
        return NAME_TO_VK[key]
    if key in SCAN_BY_NAME:
        mapped = int(user32.MapVirtualKeyW(SCAN_BY_NAME[key], MAPVK_VSC_TO_VK) or 0)
        if mapped:
            return mapped
    if len(key) == 1:
        scanned = user32.VkKeyScanW(key) & 0xFF
        if scanned and scanned != 0xFF:
            return scanned
        if key in SCAN_BY_NAME:
            return int(user32.MapVirtualKeyW(SCAN_BY_NAME[key], MAPVK_VSC_TO_VK) or 0)
    if key.startswith("f") and key[1:].isdigit():
        return 0x70 + int(key[1:]) - 1
    raise ValueError(f"Неизвестная клавиша: {name}")


def scan_from_name(name: str, vk: int) -> int:
    key = name.strip().lower()
    if key in SCAN_BY_NAME:
        return SCAN_BY_NAME[key]
    return int(user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC) or 0)


def _send(inputs: list[INPUT]) -> int:
    if not inputs:
        return 0
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        err = ctypes.get_last_error()
        raise RuntimeError(
            f"SendInput отправил {sent}/{len(inputs)}, код {err}, sizeof(INPUT)={ctypes.sizeof(INPUT)}"
        )
    return sent


def _key_input(vk: int, scan: int, up: bool = False, scancode: bool = True) -> INPUT:
    flags = 0
    if scancode:
        flags |= KEYEVENTF_SCANCODE
    if vk in EXTENDED_VKS:
        flags |= KEYEVENTF_EXTENDEDKEY
    if up:
        flags |= KEYEVENTF_KEYUP
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki = KEYBDINPUT(0 if scancode else vk, scan, flags, 0, 0)
    return inp


def tap_key(name: str, hold_sec: float = 0.08) -> None:
    vk = vk_from_name(name)
    if vk == VK_LBUTTON:
        click_mouse("left", hold_sec)
        return
    if vk == VK_RBUTTON:
        click_mouse("right", hold_sec)
        return
    scan = scan_from_name(name, vk)
    fg = describe_hwnd(user32.GetForegroundWindow())
    _log(f"ввод: tap {name!r} vk=0x{vk:02X} scan=0x{scan:02X} hold={hold_sec:.3f}c | фокус {fg}")
    _send([_key_input(vk, scan, False, True)])
    time.sleep(hold_sec)
    _send([_key_input(vk, scan, True, True)])


def key_down(name: str) -> None:
    vk = vk_from_name(name)
    if vk == VK_LBUTTON:
        _send([_mouse_input(MOUSEEVENTF_LEFTDOWN)])
        return
    if vk == VK_RBUTTON:
        _send([_mouse_input(MOUSEEVENTF_RIGHTDOWN)])
        return
    scan = scan_from_name(name, vk)
    _log(f"ввод: down {name!r} vk=0x{vk:02X} scan=0x{scan:02X}")
    _send([_key_input(vk, scan, False, True)])


def key_up(name: str) -> None:
    vk = vk_from_name(name)
    if vk == VK_LBUTTON:
        _send([_mouse_input(MOUSEEVENTF_LEFTUP)])
        return
    if vk == VK_RBUTTON:
        _send([_mouse_input(MOUSEEVENTF_RIGHTUP)])
        return
    scan = scan_from_name(name, vk)
    _log(f"ввод: up {name!r} vk=0x{vk:02X} scan=0x{scan:02X}")
    _send([_key_input(vk, scan, True, True)])


def _mouse_input(flags: int, dx: int = 0, dy: int = 0) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi = MOUSEINPUT(int(dx), int(dy), 0, flags, 0, 0)
    return inp


def move_mouse(dx: int, dy: int) -> None:
    dx_i, dy_i = int(dx), int(dy)
    flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_MOVE_NOCOALESCE
    _send([_mouse_input(flags, dx_i, dy_i)])


def click_mouse(button: str = "left", hold_sec: float = 0.07) -> None:
    kind = (button or "left").strip().lower().replace(" ", "")
    if kind in {"right", "rbutton", "mouse2", "мышь2", "мышка2", "пкм"}:
        down, up = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
        kind = "right"
    else:
        down, up = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
        kind = "left"
    _log(f"ввод: click {kind} hold={hold_sec:.3f}c")
    _send([_mouse_input(down)])
    time.sleep(hold_sec)
    _send([_mouse_input(up)])


def get_window_title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def _process_name(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.split("\\")[-1].lower()
    finally:
        kernel32.CloseHandle(handle)
    return ""


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


def find_window_by_process(process_name: str) -> int | None:
    found: list[tuple[int, int, int]] = []
    want = process_name.lower()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if _process_name(pid.value) != want:
            return True
        title = get_window_title(hwnd)
        klass = get_class_name(hwnd).lower()
        w, h = window_size(hwnd)
        area = w * h
        score = area
        if "counter-strike" in title.lower():
            score += 10_000_000
        if klass in {"sdl_app", "valve001", "sdl_app"}:
            score += 1_000_000
        if title:
            found.append((score, area, hwnd))
        return True

    user32.EnumWindows(callback, 0)
    if not found:
        return None
    found.sort(reverse=True)
    return found[0][2]


def force_foreground(hwnd: int) -> bool:
    if user32.GetForegroundWindow() == hwnd:
        return True
    try:
        user32.AllowSetForegroundWindow(ASFW_ANY)
        user32.LockSetForegroundWindow(LSFW_UNLOCK)
    except Exception:
        pass
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    current = kernel32.GetCurrentThreadId()
    fg = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    target_tid = user32.GetWindowThreadProcessId(hwnd, None)
    attached_fg = False
    attached_target = False
    if fg_tid and fg_tid != current:
        attached_fg = bool(user32.AttachThreadInput(current, fg_tid, True))
    if target_tid and target_tid != current:
        attached_target = bool(user32.AttachThreadInput(current, target_tid, True))
    try:
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    finally:
        if attached_target:
            user32.AttachThreadInput(current, target_tid, False)
        if attached_fg:
            user32.AttachThreadInput(current, fg_tid, False)
    time.sleep(0.12)
    ok = user32.GetForegroundWindow() == hwnd
    _log(f"фокус CS2: {'ок' if ok else 'не удалось'} → {describe_hwnd(user32.GetForegroundWindow())}")
    return ok


def focus_window(hwnd: int) -> None:
    force_foreground(hwnd)


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
        self.blocked_scans: set[int] = set()
        self.block_all = False
        self.kill_switch = "alt+5"
        self.panic_hotkey = "ctrl+alt+5"
        self.on_kill: Callable[[], None] | None = None
        self.on_panic: Callable[[], None] | None = None
        self._hook = None
        self._proc = None
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._running = False

    def hook_ok(self) -> bool:
        return bool(self._hook)

    def set_blocked_keys(self, names: Iterable[str]) -> None:
        vks: set[int] = set()
        scans: set[int] = set()
        details = []
        for name in names:
            vk = vk_from_name(name)
            scan = scan_from_name(name, vk)
            vks.add(vk)
            if scan:
                scans.add(scan)
            details.append(f"{name!r} vk=0x{vk:02X} scan=0x{scan:02X}")
        with self._lock:
            self.blocked_vks = vks
            self.blocked_scans = scans
        _log("WASD хук блокирует: " + ", ".join(details))

    def clear_blocked_keys(self) -> None:
        with self._lock:
            self.blocked_vks.clear()
            self.blocked_scans.clear()

    def set_block_all(self, value: bool) -> None:
        with self._lock:
            self.block_all = value

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="input-guard", daemon=True)
        self._thread.start()
        for _ in range(50):
            if self._hook:
                break
            time.sleep(0.02)

    def stop(self) -> None:
        self._running = False
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def _loop(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        self._proc = HOOKPROC(self._callback)
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        msg = wintypes.MSG()
        while self._running:
            ret = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
            if ret == 0 or ret == -1:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
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
            # Не трогаем Ctrl+C/V/X/A и ввод в нашем окне — иначе нельзя вставить ссылку.
            ctrl = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
            if ctrl and info.vkCode in {0x41, 0x43, 0x56, 0x58, 0x5A}:  # A C V X Z
                return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)
            if self._app_is_foreground():
                return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)
            injected = bool(info.flags & LLKHF_INJECTED)
            with self._lock:
                block_all = self.block_all
                blocked = (info.vkCode in self.blocked_vks) or (info.scanCode in self.blocked_scans)
            if block_all or (blocked and not injected):
                return 1
        return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)

    def _app_is_foreground(self) -> bool:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value == kernel32.GetCurrentProcessId()
