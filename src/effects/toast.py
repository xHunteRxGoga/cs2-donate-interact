from __future__ import annotations

import threading
from typing import Callable


HWND_TOPMOST = -1
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_LAYERED = 0x00080000
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040


class ToastController:
    """Нижняя широкая табличка: имя донатера и эффект. Не забирает фокус у CS2."""

    def __init__(self, ui_call: Callable[..., None]) -> None:
        self.ui_call = ui_call
        self._close: Callable[[], None] | None = None
        self._hwnd = 0

    def cancel(self) -> None:
        closer = self._close
        self._close = None
        self._hwnd = 0
        if closer:
            self.ui_call(closer)

    def show(
        self,
        username: str,
        effect_title: str,
        amount_text: str = "",
        duration_sec: float = 5.5,
        wait: bool = False,
    ) -> None:
        ready = threading.Event()
        self.cancel()

        def create() -> None:
            import tkinter as tk

            from src.effects.input_win import user32
            from src.theme import ACCENT, BG, CARD, FG, FONT, FONT_TITLE, MUTED, PANEL, STRIPE

            win = tk.Toplevel()
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            try:
                win.attributes("-alpha", 0.97)
            except tk.TclError:
                pass
            win.configure(bg=BG)
            screen_w = win.winfo_screenwidth()
            screen_h = win.winfo_screenheight()
            width = max(720, min(screen_w - 64, 1480))
            height = 104
            x = max(24, (screen_w - width) // 2)
            y = max(16, screen_h - height - 40)
            win.geometry(f"{width}x{height}+{x}+{y}")

            shell = tk.Frame(win, bg=BG)
            shell.pack(fill="both", expand=True)
            tk.Frame(shell, bg=STRIPE, height=3).pack(fill="x")
            body = tk.Frame(shell, bg=PANEL)
            body.pack(fill="both", expand=True)

            amount_box = tk.Frame(body, bg=CARD, width=168)
            amount_box.pack(side="left", fill="y")
            amount_box.pack_propagate(False)
            tk.Label(
                amount_box,
                text=amount_text or "донат",
                bg=CARD,
                fg=ACCENT,
                font=(FONT_TITLE, 20),
                wraplength=150,
            ).pack(expand=True)

            text_box = tk.Frame(body, bg=PANEL)
            text_box.pack(side="left", fill="both", expand=True, padx=22)
            tk.Label(
                text_box,
                text=username or "Аноним",
                bg=PANEL,
                fg=FG,
                font=(FONT_TITLE, 22),
                anchor="w",
            ).pack(fill="x", pady=(14, 0))
            tk.Label(
                text_box,
                text=effect_title or "Донат получен",
                bg=PANEL,
                fg=MUTED,
                font=(FONT, 13),
                anchor="w",
            ).pack(fill="x", pady=(0, 14))

            win.update_idletasks()
            hwnd = int(win.winfo_id())
            parent = int(user32.GetParent(hwnd) or 0)
            if parent:
                hwnd = parent
            get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            style = get_long(hwnd, GWL_EXSTYLE)
            set_long(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_LAYERED)
            self._hwnd = hwnd

            def pin() -> None:
                if self._hwnd != hwnd:
                    return
                try:
                    win.attributes("-topmost", True)
                    win.lift()
                    user32.SetWindowPos(
                        hwnd,
                        HWND_TOPMOST,
                        0,
                        0,
                        0,
                        0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
                    )
                    win.after(200, pin)
                except tk.TclError:
                    return

            pin()

            def closer() -> None:
                if self._hwnd == hwnd:
                    self._hwnd = 0
                try:
                    win.destroy()
                except tk.TclError:
                    pass

            self._close = closer
            win.after(int(max(1.2, duration_sec) * 1000), closer)
            ready.set()

        self.ui_call(create)
        if wait:
            ready.wait(timeout=1.2)
