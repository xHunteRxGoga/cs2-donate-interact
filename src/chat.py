from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from src.config import load_config, save_config
from src.theme import (
    ACCENT,
    ACCENT_DARK,
    BAD,
    BG,
    BUTTON,
    BUTTON_HOVER,
    CARD,
    CHIP_LINE,
    ENTRY_BG,
    FG,
    FONT,
    FONT_TITLE,
    MUTED,
    OK,
    WARN,
    WHITE,
)
from src.voice_link import VoiceLink, normalize_ws_url


class ChatApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Чат → озвучка стримера")
        self.geometry("640x560")
        self.minsize(520, 420)
        self.configure(bg=BG)
        self.cfg = load_config()
        voice = self.cfg.setdefault("voice", {})
        self.link = VoiceLink(self._on_say, self._status, role="director", name=str(voice.get("name") or "чат"))
        self._build_style()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if voice.get("server") and voice.get("token"):
            self._connect()

    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG, font=(FONT, 10))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(FONT, 9))
        style.configure("Title.TLabel", background=BG, foreground=WHITE, font=(FONT_TITLE, 16))
        style.configure("TButton", font=(FONT, 9), padding=(10, 8), background=BUTTON, foreground=FG, borderwidth=0)
        style.map("TButton", background=[("active", BUTTON_HOVER)])
        style.configure("Accent.TButton", font=(FONT_TITLE, 10), padding=(12, 8), background=ACCENT_DARK, foreground=WHITE)
        style.map("Accent.TButton", background=[("active", "#6d28d9")])

    def _build(self) -> None:
        head = ttk.Frame(self)
        head.pack(fill="x", padx=18, pady=(16, 8))
        ttk.Label(head, text="Чат стримеру", style="Title.TLabel").pack(anchor="w")
        ttk.Label(head, text="Пишешь здесь — у него играет системный голос Windows.", style="Muted.TLabel").pack(anchor="w")
        self.status = tk.Label(head, text="нет связи", bg=BG, fg=BAD, font=(FONT, 9, "bold"))
        self.status.pack(anchor="w", pady=(6, 0))

        box = tk.Frame(self, bg=CARD, highlightbackground=CHIP_LINE, highlightthickness=1)
        box.pack(fill="x", padx=18, pady=8)
        inner = ttk.Frame(box)
        inner.pack(fill="x", padx=12, pady=10)
        ttk.Label(inner, text="Сервер").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        self.server = self._entry(inner, 42)
        self.server.insert(0, self.cfg["voice"].get("server", "ws://"))
        self.server.grid(row=0, column=1, sticky="we", pady=4)
        ttk.Label(inner, text="Ключ").grid(row=1, column=0, sticky="e", padx=6, pady=4)
        self.token = self._entry(inner, 42, secret=True)
        self.token.insert(0, self.cfg["voice"].get("token", ""))
        self.token.grid(row=1, column=1, sticky="we", pady=4)
        ttk.Label(inner, text="Твоё имя").grid(row=2, column=0, sticky="e", padx=6, pady=4)
        self.name = self._entry(inner, 24)
        self.name.insert(0, self.cfg["voice"].get("name", "чат"))
        self.name.grid(row=2, column=1, sticky="w", pady=4)
        ttk.Button(inner, text="Подключиться", style="Accent.TButton", command=self._connect).grid(row=3, column=1, sticky="w", pady=8)
        inner.columnconfigure(1, weight=1)

        self.log_box = tk.Text(
            self,
            bg=ENTRY_BG,
            fg=FG,
            insertbackground=ACCENT,
            relief="flat",
            state="disabled",
            font=(FONT, 11),
            highlightthickness=1,
            highlightbackground=CHIP_LINE,
            wrap="word",
            padx=10,
            pady=8,
        )
        self.log_box.pack(fill="both", expand=True, padx=18, pady=8)

        row = ttk.Frame(self)
        row.pack(fill="x", padx=18, pady=(0, 16))
        self.msg = self._entry(row, 40)
        self.msg.pack(side="left", fill="x", expand=True, ipady=6)
        self.msg.bind("<Return>", lambda _e: self._send())
        ttk.Button(row, text="Сказать", style="Accent.TButton", command=self._send).pack(side="left", padx=(8, 0))
        self.msg.focus_set()

    def _entry(self, parent, width: int, secret: bool = False) -> tk.Entry:
        return tk.Entry(
            parent,
            width=width,
            bg=ENTRY_BG,
            fg=FG,
            insertbackground=ACCENT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=CHIP_LINE,
            highlightcolor=ACCENT,
            font=(FONT, 10),
            show="•" if secret else "",
        )

    def _connect(self) -> None:
        self._save_fields()
        self.link.name = self.cfg["voice"].get("name") or "чат"
        self.link.start(self.cfg["voice"].get("server", ""), self.cfg["voice"].get("token", ""))
        self._status("подключаюсь…")

    def _save_fields(self) -> None:
        self.cfg.setdefault("voice", {})
        self.cfg["voice"]["server"] = normalize_ws_url(self.server.get())
        self.cfg["voice"]["token"] = self.token.get().strip()
        self.cfg["voice"]["name"] = self.name.get().strip() or "чат"
        save_config(self.cfg)

    def _send(self) -> None:
        text = self.msg.get().strip()
        if not text:
            return
        if not self.link.send_say(text):
            return
        self._append("я", text, ACCENT)
        self.msg.delete(0, "end")

    def _on_say(self, who: str, text: str) -> None:
        self.after(0, lambda: self._append(who, text, MUTED))

    def _status(self, text: str) -> None:
        def paint() -> None:
            if "не в сети" in text or "ещё не зашёл" in text:
                color = WARN
            elif self.link.connected or "подключено" in text:
                color = OK
            elif "подключа" in text or "повтор" in text:
                color = WARN
            else:
                color = BAD
            self.status.configure(text=text, fg=color)

        if threading.current_thread() is threading.main_thread():
            paint()
        else:
            self.after(0, paint)

    def _append(self, who: str, text: str, _color: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{who}: {text}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _on_close(self) -> None:
        try:
            self._save_fields()
        except Exception:
            pass
        self.link.stop()
        self.destroy()


def run() -> None:
    ChatApp().mainloop()


if __name__ == "__main__":
    run()
