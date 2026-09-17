from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from src.access_client import AccessClient
from src.theme import ACCENT, BG, BAD, CARD, ENTRY_BG, FG, FONT, FONT_TITLE, MUTED, OK, WHITE


class AdminApp(tk.Tk):
    def __init__(self, client: AccessClient) -> None:
        super().__init__()
        self.client = client
        self.title("CS2 Donate Interact — админка")
        self.geometry("900x560")
        self.minsize(760, 420)
        self.configure(bg=BG)
        self._rows: list[dict] = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        head = tk.Frame(self, bg=CARD, highlightbackground=MUTED, highlightthickness=1)
        head.pack(fill="x", padx=16, pady=(16, 8))
        tk.Label(head, text="Кому выдать доступ", bg=CARD, fg=WHITE, font=(FONT_TITLE, 15)).pack(side="left", padx=12, pady=10)
        ttk.Button(head, text="Обновить", command=self.refresh).pack(side="right", padx=12, pady=8)

        cols = ("id", "username", "access_until", "status", "created_at")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=16)
        for col, title, w in (
            ("id", "ID", 50),
            ("username", "Ник", 140),
            ("access_until", "Доступ до", 180),
            ("status", "Статус", 120),
            ("created_at", "Регистрация", 180),
        ):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=16, pady=8)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: None)

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=16, pady=(0, 16))
        tk.Label(bar, text="Выдать дней", bg=BG, fg=FG, font=(FONT, 10)).pack(side="left")
        self.days = tk.Entry(bar, width=6, bg=ENTRY_BG, fg=FG, relief="flat")
        self.days.insert(0, "30")
        self.days.pack(side="left", padx=8)
        ttk.Button(bar, text="Выдать доступ", command=self.grant).pack(side="left", padx=4)
        ttk.Button(bar, text="Снять доступ", command=self.revoke).pack(side="left", padx=4)
        ttk.Button(bar, text="Закрыть", command=self.destroy).pack(side="right")

    def _selected_id(self) -> int | None:
        sel = self.tree.selection()
        if not sel:
            return None
        item = self.tree.item(sel[0])
        vals = item.get("values") or []
        if not vals:
            return None
        try:
            return int(vals[0])
        except (TypeError, ValueError):
            return None

    def refresh(self) -> None:
        users, err = self.client.list_users()
        if err:
            messagebox.showerror("Админка", err)
            return
        self._rows = users
        for row in self.tree.get_children():
            self.tree.delete(row)
        for u in users:
            active = bool(u.get("access_active"))
            status = "активен" if active else "ждёт оплату"
            self.tree.insert(
                "",
                "end",
                values=(
                    u.get("id"),
                    u.get("username"),
                    u.get("access_until") or "—",
                    status,
                    u.get("created_at") or "",
                ),
            )

    def grant(self) -> None:
        uid = self._selected_id()
        if uid is None:
            messagebox.showinfo("Админка", "Выбери пользователя в списке.")
            return
        try:
            days = int(self.days.get().strip() or "0")
        except ValueError:
            messagebox.showerror("Админка", "Укажи число дней.")
            return
        ok, msg = self.client.grant(uid, days)
        if ok:
            self.refresh()
            messagebox.showinfo("Админка", msg)
        else:
            messagebox.showerror("Админка", msg)

    def revoke(self) -> None:
        uid = self._selected_id()
        if uid is None:
            messagebox.showinfo("Админка", "Выбери пользователя.")
            return
        if not messagebox.askyesno("Админка", "Снять доступ у этого пользователя?"):
            return
        ok, msg = self.client.revoke(uid)
        if ok:
            self.refresh()
            messagebox.showinfo("Админка", msg)
        else:
            messagebox.showerror("Админка", msg)
