from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
from typing import Callable


gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.GetDeviceGammaRamp.argtypes = [wintypes.HDC, ctypes.c_void_p]
gdi32.SetDeviceGammaRamp.argtypes = [wintypes.HDC, ctypes.c_void_p]

RampArray = ctypes.c_ushort * 256 * 3


class FlashController:
    def __init__(self, ui_call: Callable[..., None]) -> None:
        self.ui_call = ui_call
        self._stop = threading.Event()
        self._original: RampArray | None = None
        self._overlay_closer: Callable[[], None] | None = None
        self._busy = False

    def cancel(self) -> None:
        self._stop.set()
        self._restore_gamma()
        self._close_overlay()

    def ping(self, duration_sec: float = 0.45) -> None:
        """Короткая гамма-вспышка: видна даже если табличка спряталась под exclusive fullscreen / античитом."""
        if self._busy:
            return
        self._busy = True
        self._stop.clear()
        try:
            self._save_gamma()
            self._apply_gamma(1.0)
            end = time.time() + max(0.15, duration_sec)
            while time.time() < end and not self._stop.is_set():
                time.sleep(0.03)
            self._restore_gamma()
        finally:
            self._busy = False

    def run(self, duration_sec: float, mode: str, fade_out_sec: float) -> None:
        self._busy = True
        self._stop.clear()
        try:
            self._run(duration_sec, mode, fade_out_sec)
        finally:
            self._busy = False

    def _run(self, duration_sec: float, mode: str, fade_out_sec: float) -> None:
        use_gamma = mode in {"gamma", "gamma_and_overlay"}
        use_overlay = mode in {"overlay", "gamma_and_overlay"}
        if use_gamma:
            self._save_gamma()
            self._apply_gamma(1.0)
        if use_overlay:
            self._open_overlay()

        hold = max(0.0, duration_sec - fade_out_sec)
        end_hold = time.time() + hold
        while time.time() < end_hold and not self._stop.is_set():
            time.sleep(0.05)

        if fade_out_sec > 0 and not self._stop.is_set():
            steps = 20
            for i in range(steps):
                if self._stop.is_set():
                    break
                progress = 1.0 - ((i + 1) / steps)
                if use_gamma:
                    self._apply_gamma(progress)
                if use_overlay:
                    self._set_overlay_alpha(progress)
                time.sleep(fade_out_sec / steps)

        self._restore_gamma()
        self._close_overlay()

    def _save_gamma(self) -> None:
        hdc = user32.GetDC(0)
        ramp = RampArray()
        ok = gdi32.GetDeviceGammaRamp(hdc, ctypes.byref(ramp))
        user32.ReleaseDC(0, hdc)
        self._original = ramp if ok else None

    def _apply_gamma(self, white_amount: float) -> None:
        hdc = user32.GetDC(0)
        ramp = RampArray()
        for i in range(256):
            base = i * 256
            flashed = 65535
            value = int(base + (flashed - base) * max(0.0, min(1.0, white_amount)))
            value = max(0, min(65535, value))
            ramp[0][i] = ramp[1][i] = ramp[2][i] = value
        gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp))
        user32.ReleaseDC(0, hdc)

    def _restore_gamma(self) -> None:
        if self._original is None:
            return
        hdc = user32.GetDC(0)
        gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(self._original))
        user32.ReleaseDC(0, hdc)

    def _open_overlay(self) -> None:
        ready = threading.Event()

        def create() -> None:
            import tkinter as tk

            win = tk.Toplevel()
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            try:
                win.attributes("-alpha", 1.0)
            except tk.TclError:
                pass
            win.configure(bg="white")
            win.geometry(f"{win.winfo_screenwidth()}x{win.winfo_screenheight()}+0+0")
            win.lift()
            label = tk.Label(win, bg="white")
            label.pack(fill="both", expand=True)

            def closer() -> None:
                try:
                    win.destroy()
                except tk.TclError:
                    pass

            def set_alpha(value: float) -> None:
                try:
                    win.attributes("-alpha", max(0.0, min(1.0, value)))
                except tk.TclError:
                    pass

            self._overlay_closer = closer
            self._set_overlay_alpha_impl = set_alpha
            ready.set()

        self.ui_call(create)
        ready.wait(timeout=1.5)

    def _set_overlay_alpha(self, value: float) -> None:
        impl = getattr(self, "_set_overlay_alpha_impl", None)
        if impl:
            self.ui_call(lambda: impl(value))

    def _close_overlay(self) -> None:
        closer = self._overlay_closer
        self._overlay_closer = None
        if closer:
            self.ui_call(closer)
