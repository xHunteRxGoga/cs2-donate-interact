from __future__ import annotations

import threading
from typing import Callable


HWND_TOPMOST = -1
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040


class ToastController:
    """Нижний оверлей как у Фени: имя донатера и какая награда сработала, без кражи фокуса CS2."""

    def __init__(self, ui_call: Callable[..., None]) -> None:
        self.ui_call = ui_call
        self._close: Callable[[], None] | None = None
        self._hide_job = None

    def cancel(self) -> None:
        closer = self._close
        self._close = None
        if closer:
            self.ui_call(closer)

    def show(self, username: str, effect_title: str, amount_text: str = "", duration_sec: float = 4.5) -> None:
        ready = threading.Event()
        self.cancel()

        def create() -> None:
            import tkinter as tk

            from src.effects.input_win import user32

            win = tk.Toplevel()
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            try:
                win.attributes("-alpha", 0.94)
            except tk.TclError:
                pass
            win.configure(bg="#120815")
            screen_w = win.winfo_screenwidth()
            screen_h = win.winfo_screenheight()
            width, height = 420, 92
            x = max(12, (screen_w - width) // 2)
            y = max(12, screen_h - height - 48)
            win.geometry(f"{width}x{height}+{x}+{y}")

            inner = tk.Frame(win, bg="#27183a", highlightbackground="#c4b5fd", highlightthickness=2)
            inner.pack(fill="both", expand=True, padx=2, pady=2)
            tk.Label(
                inner,
                text=username or "Аноним",
                bg="#27183a",
                fg="#ffffff",
                font=("Segoe UI", 16, "bold"),
                anchor="w",
            ).pack(fill="x", padx=16, pady=(12, 0))
            sub = effect_title
            if amount_text:
                sub = f"{effect_title}   ·   {amount_text}"
            tk.Label(
                inner,
                text=sub,
                bg="#27183a",
                fg="#c4b5fd",
                font=("Segoe UI", 12),
                anchor="w",
            ).pack(fill="x", padx=16, pady=(2, 12))

            win.update_idletasks()
            hwnd = int(win.winfo_id())
            get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            style = get_long(hwnd, GWL_EXSTYLE)
            set_long(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
            user32.SetWindowPos(
                hwnd,
                HWND_TOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )

            def closer() -> None:
                try:
                    win.destroy()
                except tk.TclError:
                    pass

            self._close = closer
            win.after(int(max(0.8, duration_sec) * 1000), closer)
            ready.set()

        self.ui_call(create)
        ready.wait(timeout=1.5)
