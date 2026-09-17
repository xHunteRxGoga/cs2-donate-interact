from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from src.access_client import AccessClient
from src.admin_app import AdminApp
from src.app import run as run_main_app
from src.config import load_config
from src.theme import ACCENT, BG, CARD, ENTRY_BG, FG, FONT, FONT_TITLE, MUTED, WHITE


def _open_after_login(client: AccessClient) -> None:
    client.refresh()
    if client.user and client.user.is_admin:
        AdminApp(client).mainloop()
    else:
        run_main_app(client)


def try_auto_login() -> bool:
    """Если сохранённая сессия жива — сразу в программу, без лишних экранов."""
    cfg = load_config()
    access = cfg.get("access") or {}
    if not access.get("enabled", True):
        return False
    client = AccessClient(str(access.get("server") or ""))
    if not client.user:
        return False
    ok, _msg = client.refresh()
    if not ok:
        client.logout()
        return False
    _open_after_login(client)
    return True


class LoginApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = load_config()
        access = self.cfg.get("access") or {}
        self.client = AccessClient(str(access.get("server") or ""))
        self._register_mode = False
        self.title("CS2 Donate Interact")
        self.geometry("440x340")
        self.minsize(400, 300)
        self.configure(bg=BG)
        self._build()
        if self.client.user:
            self.username.insert(0, self.client.user.username)

    def _entry(self, parent: tk.Widget, width: int = 26, show: str = "") -> tk.Entry:
        return tk.Entry(
            parent,
            width=width,
            bg=ENTRY_BG,
            fg=FG,
            insertbackground=ACCENT,
            relief="flat",
            font=(FONT, 11),
            show=show,
            highlightthickness=1,
            highlightbackground=MUTED,
            highlightcolor=ACCENT,
        )

    def _build(self) -> None:
        card = tk.Frame(self, bg=CARD, highlightbackground=MUTED, highlightthickness=1)
        card.pack(fill="both", expand=True, padx=20, pady=20)
        self.title_lbl = tk.Label(card, text="Вход", bg=CARD, fg=WHITE, font=(FONT_TITLE, 16))
        self.title_lbl.pack(anchor="w", padx=16, pady=(16, 4))
        tk.Label(
            card,
            text="Ник и пароль. После оплаты админ включит доступ — тогда заработают донаты и эффекты.",
            bg=CARD,
            fg=MUTED,
            font=(FONT, 9),
            wraplength=360,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 12))

        form = tk.Frame(card, bg=CARD)
        form.pack(fill="x", padx=16)
        tk.Label(form, text="Ник", bg=CARD, fg=FG, font=(FONT, 10)).grid(row=0, column=0, sticky="e", padx=(0, 8), pady=6)
        self.username = self._entry(form, 24)
        self.username.grid(row=0, column=1, sticky="we", pady=6)
        tk.Label(form, text="Пароль", bg=CARD, fg=FG, font=(FONT, 10)).grid(row=1, column=0, sticky="e", padx=(0, 8), pady=6)
        self.password = self._entry(form, 24, show="•")
        self.password.grid(row=1, column=1, sticky="we", pady=6)
        self.password.bind("<Return>", lambda _e: self._submit())
        form.columnconfigure(1, weight=1)

        self.main_btn = ttk.Button(card, text="Войти", command=self._submit)
        self.main_btn.pack(padx=16, pady=(16, 6), anchor="w")

        row = ttk.Frame(card)
        row.pack(fill="x", padx=16, pady=(0, 12))
        self.toggle_btn = ttk.Button(row, text="Нет аккаунта — создать", command=self._toggle_mode)
        self.toggle_btn.pack(side="left")
        if self.client.user:
            ttk.Button(row, text="Продолжить", command=self._continue_session).pack(side="right")

    def _toggle_mode(self) -> None:
        self._register_mode = not self._register_mode
        if self._register_mode:
            self.title_lbl.configure(text="Регистрация")
            self.main_btn.configure(text="Создать аккаунт")
            self.toggle_btn.configure(text="Уже есть аккаунт — войти")
        else:
            self.title_lbl.configure(text="Вход")
            self.main_btn.configure(text="Войти")
            self.toggle_btn.configure(text="Нет аккаунта — создать")

    def _values(self) -> tuple[str, str]:
        return self.username.get().strip(), self.password.get()

    def _submit(self) -> None:
        name, pwd = self._values()
        if self._register_mode:
            ok, msg = self.client.register(name, pwd)
            if not ok:
                messagebox.showerror("Регистрация", msg)
                return
            messagebox.showinfo("Готово", msg + "\n\nТеперь нажми «Войти».")
            if self._register_mode:
                self._toggle_mode()
            return
        ok, msg = self.client.login(name, pwd, admin=False)
        if not ok:
            messagebox.showerror("Вход", msg)
            return
        self.destroy()
        _open_after_login(self.client)

    def _continue_session(self) -> None:
        ok, msg = self.client.refresh()
        if not ok:
            messagebox.showerror("Сессия", msg)
            return
        self.destroy()
        _open_after_login(self.client)


def run_login() -> None:
    if try_auto_login():
        return
    LoginApp().mainloop()
