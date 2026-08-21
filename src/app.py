from __future__ import annotations

import threading
import time
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from src.config import EFFECT_ORDER, EFFECT_TITLES, load_config, save_config
from src.debuglog import LOG_PATH, read_tail, write as write_log
from src.donations.donatepay import DonatePayClient
from src.donations.donationalerts import DonationAlertsClient, oauth_login
from src.donations.models import Donation
from src.donations.trula import TrulaClient
from src.donations.webhook import WebhookServer
from src.effects.cs2 import is_cs2_running
from src.effects.engine import EffectEngine
from src.updater import CHECK_EVERY_SEC, check_and_apply, restart_process
from src.theme import (
    ACCENT,
    ACCENT_DARK,
    BAD,
    BG,
    BUTTON,
    BUTTON_HOVER,
    CARD,
    CHIP_BG,
    CHIP_FILL,
    CHIP_LINE,
    DANGER,
    DANGER_HOVER,
    ENTRY_BG,
    FG,
    FONT,
    FONT_MONO,
    FONT_TITLE,
    HIGHLIGHT,
    MUTED,
    OK,
    PANEL,
    STRIPE,
    WARN,
    WHITE,
)

EFFECT_HINTS = {
    "flash": "белый экран",
    "drop_weapon": "клавиша дропа",
    "mouse_jerk": "рывок мыши",
    "block_wasd": "ход отключается",
    "nade_and_crouch": "HE + присед",
    "kill_cs2": "закрыть игру",
    "minecraft_takeover": "ролик на весь экран",
}


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("CS2 Donate Interact")
        self.geometry("1120x780")
        self.minsize(960, 640)
        self.configure(bg=BG)
        self.cfg = load_config()
        self.engine = EffectEngine(lambda: self.cfg, self.log, self.ui_call)
        self.da = DonationAlertsClient(self._on_donation, self.log)
        self.dp = DonatePayClient(self._on_donation, self.log)
        self.trula = TrulaClient(self._on_donation, self.log)
        self.webhook = WebhookServer(self._on_donation, self.log)
        self._quiet_log_until: dict[str, float] = {}
        self._build_style()
        self._build()
        self._dark_titlebar()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.engine.start()
        self._start_services()
        self._start_updater()
        self.after(1000, self._tick)

    def ui_call(self, fn) -> None:
        self.after(0, fn)

    def log(self, text: str) -> None:
        noisy = any(
            marker in text
            for marker in ("429", "Too Many Requests", "Incorrect token", "DonatePay опрос:", "DonatePay API:")
        )
        if noisy:
            now = time.monotonic()
            if now < self._quiet_log_until.get("dp", 0):
                write_log(text)
                return
            self._quiet_log_until["dp"] = now + 30
            text = text + "  (одинаковые ошибки DonatePay 30 сек не спамлю в окно)"
        line = write_log(text)

        def append() -> None:
            if not hasattr(self, "log_box"):
                return
            self.log_box.configure(state="normal")
            self.log_box.insert("end", line + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")

        if threading.current_thread() is threading.main_thread():
            append()
        else:
            self.after(0, append)

    def _dark_titlebar(self) -> None:
        try:
            import ctypes

            self.update_idletasks()
            hwnd = int(self.winfo_id())
            parent = ctypes.windll.user32.GetParent(hwnd)
            if parent:
                hwnd = parent
            value = ctypes.c_int(1)
            dwm = ctypes.windll.dwmapi
            for attr in (20, 19):
                dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), 4)
        except Exception:
            pass

    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=FG, font=(FONT, 10))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(FONT, 9))
        style.configure("Title.TLabel", background=BG, foreground=WHITE, font=(FONT_TITLE, 18))
        style.configure("Sub.TLabel", background=BG, foreground=ACCENT, font=(FONT, 9))
        style.configure("Card.TLabel", background=CARD, foreground=FG, font=(FONT, 10))
        style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED, font=(FONT, 9))
        style.configure(
            "TCheckbutton",
            background=BG,
            foreground=FG,
            font=(FONT, 10),
            indicatorcolor=ENTRY_BG,
            indicatorrelief="flat",
        )
        style.map(
            "TCheckbutton",
            background=[("active", PANEL)],
            foreground=[("active", ACCENT)],
            indicatorcolor=[("selected", ACCENT_DARK), ("active", HIGHLIGHT)],
        )
        style.configure(
            "Card.TCheckbutton",
            background=CARD,
            foreground=FG,
            font=(FONT, 10),
            indicatorcolor=ENTRY_BG,
            indicatorrelief="flat",
        )
        style.map(
            "Card.TCheckbutton",
            background=[("active", PANEL)],
            foreground=[("active", ACCENT)],
            indicatorcolor=[("selected", ACCENT_DARK), ("active", HIGHLIGHT)],
        )
        style.configure(
            "Vertical.TScrollbar",
            background=PANEL,
            troughcolor=BG,
            bordercolor=BG,
            arrowcolor=ACCENT,
        )
        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(4, 6, 4, 0))
        style.configure(
            "TNotebook.Tab",
            background=PANEL,
            foreground=MUTED,
            padding=(18, 10),
            font=(FONT, 10),
            borderwidth=0,
            lightcolor=BG,
            darkcolor=BG,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", ACCENT_DARK), ("active", BUTTON_HOVER)],
            foreground=[("selected", WHITE), ("active", FG)],
        )
        style.configure(
            "TButton",
            font=(FONT, 9),
            padding=(10, 8),
            background=BUTTON,
            foreground=FG,
            borderwidth=0,
            focusthickness=0,
            relief="flat",
        )
        style.map(
            "TButton",
            background=[("active", BUTTON_HOVER), ("pressed", ACCENT_DARK)],
            foreground=[("active", WHITE)],
        )
        style.configure(
            "Accent.TButton",
            font=(FONT_TITLE, 10),
            padding=(12, 8),
            background=ACCENT_DARK,
            foreground=WHITE,
        )
        style.map("Accent.TButton", background=[("active", HIGHLIGHT), ("pressed", BUTTON)])
        style.configure(
            "Danger.TButton",
            font=(FONT, 9),
            padding=(10, 8),
            background=DANGER,
            foreground=WHITE,
        )
        style.map("Danger.TButton", background=[("active", DANGER_HOVER), ("pressed", "#7f1d1d")])
        style.configure("TEntry", fieldbackground=ENTRY_BG, foreground=FG, insertcolor=FG)
        style.configure(
            "TCombobox",
            fieldbackground=ENTRY_BG,
            background=CARD,
            foreground=FG,
            arrowcolor=ACCENT,
            bordercolor=HIGHLIGHT,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", ENTRY_BG)],
            foreground=[("readonly", FG)],
            background=[("active", CARD)],
        )
        self.option_add("*TCombobox*Listbox.background", ENTRY_BG)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT_DARK)
        self.option_add("*TCombobox*Listbox.selectForeground", WHITE)
        self.option_add("*Menu.background", PANEL)
        self.option_add("*Menu.foreground", FG)
        self.option_add("*Menu.activeBackground", ACCENT_DARK)
        self.option_add("*Menu.activeForeground", WHITE)

    def _chip(self, parent: tk.Widget, text: str) -> tuple[tk.Frame, tk.Label]:
        chip = tk.Frame(parent, bg=CHIP_BG, highlightbackground=CHIP_LINE, highlightthickness=1)
        lbl = tk.Label(chip, text=text, bg=CHIP_BG, fg=BAD, font=(FONT, 9, "bold"), padx=11, pady=5)
        lbl.pack()
        return chip, lbl

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        head = ttk.Frame(self)
        head.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 0))
        titles = ttk.Frame(head)
        titles.pack(side="left")
        ttk.Label(titles, text="CS2 Donate Interact", style="Title.TLabel").pack(anchor="w")
        ttk.Label(titles, text="донаты → эффекты в игре", style="Sub.TLabel").pack(anchor="w", pady=(2, 0))
        chips = ttk.Frame(head)
        chips.pack(side="right")
        self.status_upd_chip, self.status_upd = self._chip(chips, "GH: …")
        self.status_sys_chip, self.status_sys = self._chip(chips, "эффекты: вкл")
        self.status_cs2_chip, self.status_cs2 = self._chip(chips, "CS2: —")
        self.status_trula_chip, self.status_trula = self._chip(chips, "Trula: нет")
        self.status_dp_chip, self.status_dp = self._chip(chips, "DP: нет")
        self.status_da_chip, self.status_da = self._chip(chips, "DA: нет")
        self.status_sys.configure(fg=OK)
        self.status_upd_chip.pack(side="right", padx=(6, 0))
        self.status_sys_chip.pack(side="right", padx=6)
        self.status_cs2_chip.pack(side="right", padx=6)
        self.status_trula_chip.pack(side="right", padx=6)
        self.status_dp_chip.pack(side="right", padx=6)
        self.status_da_chip.pack(side="right", padx=6)

        accent = tk.Frame(self, bg=STRIPE, height=2)
        accent.grid(row=1, column=0, sticky="ew", padx=20, pady=(12, 4))

        bar = ttk.Frame(self)
        bar.grid(row=3, column=0, sticky="ew", padx=20, pady=(6, 12))
        ttk.Button(bar, text="Сохранить настройки", style="Accent.TButton", command=self._save).pack(side="left")
        ttk.Button(bar, text="Включить эффекты", command=self._resume).pack(side="left", padx=8)
        ttk.Button(bar, text="Аварийный стоп (Alt+5)", command=self.engine.emergency_stop).pack(side="left", padx=(16, 8))
        ttk.Button(bar, text="Паника: выключить всё", style="Danger.TButton", command=self._panic).pack(side="left")
        ttk.Button(bar, text="Скопировать лог", command=self._copy_log).pack(side="right")
        ttk.Button(bar, text="Проверить табличку", command=self._test_overlay).pack(side="right", padx=8)
        self.btn_restart_update = ttk.Button(
            bar,
            text="Перезапустить с обновлением",
            style="Accent.TButton",
            command=self._restart_for_update,
        )

        nb = ttk.Notebook(self)
        nb.grid(row=2, column=0, sticky="nsew", padx=20, pady=(4, 4))
        self.tab_effects = ttk.Frame(nb)
        self.tab_general = ttk.Frame(nb)
        self.tab_da = ttk.Frame(nb)
        self.tab_keys = ttk.Frame(nb)
        self.tab_log = ttk.Frame(nb)
        nb.add(self.tab_effects, text="Эффекты")
        nb.add(self.tab_general, text="Кулдауны и работа")
        nb.add(self.tab_da, text="Донаты")
        nb.add(self.tab_keys, text="Клавиши CS2")
        nb.add(self.tab_log, text="Лог")
        self._build_effects()
        self._build_general()
        self._build_da()
        self._build_keys()
        self._build_log()
        self.bind_all("<MouseWheel>", self._on_mousewheel)

    def _scroll_area(self, parent: tk.Widget) -> tk.Frame:
        shell = tk.Frame(parent, bg=BG)
        shell.pack(fill="both", expand=True)
        canvas = tk.Canvas(shell, bg=BG, highlightthickness=0, bd=0)
        scroll = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        shell._scroll_canvas = canvas  # type: ignore[attr-defined]
        inner._scroll_canvas = canvas  # type: ignore[attr-defined]
        canvas._scroll_canvas = canvas  # type: ignore[attr-defined]

        def inner_cfg(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all") or (0, 0, 0, 0))

        def canvas_cfg(event) -> None:
            canvas.itemconfigure(window_id, width=max(1, event.width))

        inner.bind("<Configure>", inner_cfg)
        canvas.bind("<Configure>", canvas_cfg)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return inner

    def _on_mousewheel(self, event: tk.Event) -> str | None:
        try:
            widget = self.winfo_containing(*self.winfo_pointerxy())
        except tk.TclError:
            return None
        current = widget
        while current is not None:
            if isinstance(current, tk.Text):
                return None
            canvas = getattr(current, "_scroll_canvas", None)
            if canvas is not None:
                canvas.yview_scroll(int(-event.delta / 120), "units")
                return "break"
            current = getattr(current, "master", None)
        return None

    def _card(self, parent: tk.Widget) -> tk.Frame:
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="x", pady=5)
        stripe = tk.Frame(outer, bg=STRIPE, width=3)
        stripe.pack(side="left", fill="y")
        inner = tk.Frame(outer, bg=CARD)
        inner.pack(side="left", fill="both", expand=True)
        return inner

    def _entry(self, parent: tk.Widget, width: int = 10, secret: bool = False) -> tk.Entry:
        entry = tk.Entry(
            parent,
            width=width,
            bg=ENTRY_BG,
            fg=FG,
            insertbackground=ACCENT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=CHIP_LINE,
            highlightcolor=ACCENT,
            exportselection=False,
            font=(FONT, 10),
            show="•" if secret else "",
        )
        self._bind_clipboard(entry)
        return entry

    def _bind_clipboard(self, widget: tk.Entry) -> None:
        def paste(_event=None, target: tk.Entry = widget) -> str:
            self._paste_into(target)
            return "break"

        for seq in ("<<Paste>>", "<Control-v>", "<Control-V>", "<Shift-Insert>", "<Control-м>", "<Control-М>"):
            widget.bind(seq, paste)
        widget.bind("<Button-3>", lambda event, target=widget: self._entry_menu(event, target))

    def _paste_into(self, entry: tk.Entry) -> None:
        text = ""
        try:
            text = self.clipboard_get()
        except tk.TclError:
            text = ""
        if not text:
            try:
                import ctypes

                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32
                CF_UNICODETEXT = 13
                if user32.OpenClipboard(None):
                    try:
                        handle = user32.GetClipboardData(CF_UNICODETEXT)
                        if handle:
                            locked = kernel32.GlobalLock(handle)
                            if locked:
                                text = ctypes.wstring_at(locked)
                                kernel32.GlobalUnlock(handle)
                    finally:
                        user32.CloseClipboard()
            except Exception:
                text = text or ""
        if not text:
            return
        text = text.strip().replace("\r", "").replace("\n", "")
        try:
            if entry.selection_present():
                entry.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        entry.insert("insert", text)
        entry.focus_set()
        entry.icursor("end")
        entry.xview_moveto(1)

    def _entry_menu(self, event: tk.Event, entry: tk.Entry) -> None:
        menu = tk.Menu(
            self,
            tearoff=0,
            bg=PANEL,
            fg=FG,
            activebackground=ACCENT_DARK,
            activeforeground=WHITE,
            bd=0,
        )
        menu.add_command(label="Вставить", command=lambda: self._paste_into(entry))
        menu.add_command(label="Копировать", command=lambda: self._copy_from(entry))
        menu.add_command(label="Вырезать", command=lambda: self._cut_from(entry))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _copy_from(self, entry: tk.Entry) -> None:
        try:
            text = entry.selection_get()
        except tk.TclError:
            text = entry.get()
        self.clipboard_clear()
        self.clipboard_append(text)

    def _cut_from(self, entry: tk.Entry) -> None:
        self._copy_from(entry)
        try:
            entry.delete("sel.first", "sel.last")
        except tk.TclError:
            entry.delete(0, "end")

    def _paste_button(self, parent: tk.Widget, entry: tk.Entry) -> ttk.Button:
        return ttk.Button(parent, text="Вставить", command=lambda: self._paste_into(entry))

    def _build_effects(self) -> None:
        ttk.Label(
            self.tab_effects,
            text="Сумма доната запускает один эффект. «Тест»: 3 сек на переход в CS2, потом эффект.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(10, 8))
        body = self._scroll_area(self.tab_effects)
        self.effect_vars: dict[str, dict[str, Any]] = {}
        for effect_id in EFFECT_ORDER:
            effect = self.cfg["effects"][effect_id]
            card = self._card(body)
            inner = tk.Frame(card, bg=CARD)
            inner.pack(fill="x", padx=12, pady=10)

            amount = self._entry(inner, 7)
            amount.insert(0, str(effect.get("amount", 0)))
            amount.configure(font=(FONT_TITLE, 14), fg=ACCENT, justify="center")
            amount.pack(side="left", padx=(0, 4), ipady=4)
            tk.Label(inner, text="₽", bg=CARD, fg=MUTED, font=(FONT, 11)).pack(side="left", padx=(0, 14))

            names = tk.Frame(inner, bg=CARD)
            names.pack(side="left", fill="x", expand=True)
            tk.Label(
                names,
                text=EFFECT_TITLES[effect_id],
                bg=CARD,
                fg=FG,
                font=(FONT_TITLE, 11),
                anchor="w",
            ).pack(fill="x")
            tk.Label(
                names,
                text=EFFECT_HINTS.get(effect_id, ""),
                bg=CARD,
                fg=MUTED,
                font=(FONT, 8),
                anchor="w",
            ).pack(fill="x")

            extra: dict[str, tk.Entry] = {}
            controls = tk.Frame(inner, bg=CARD)
            controls.pack(side="right")
            enabled = tk.BooleanVar(value=bool(effect.get("enabled", True)))
            ttk.Checkbutton(controls, text="вкл", variable=enabled, style="Card.TCheckbutton").pack(side="left", padx=(0, 8))
            tk.Label(controls, text="кд", bg=CARD, fg=MUTED, font=(FONT, 8)).pack(side="left", padx=(0, 4))
            cooldown = self._entry(controls, 5)
            cooldown.insert(0, str(effect.get("cooldown_sec", 0)))
            cooldown.pack(side="left")
            if effect_id in {"flash", "block_wasd"}:
                tk.Label(controls, text="сек", bg=CARD, fg=MUTED, font=(FONT, 8)).pack(side="left", padx=(10, 4))
                duration = self._entry(controls, 5)
                duration.insert(0, str(effect.get("duration_sec", 8 if effect_id == "flash" else 10)))
                extra["duration_sec"] = duration
                duration.pack(side="left")
            ttk.Button(
                controls,
                text="Тест",
                command=lambda eid=effect_id: self.engine.enqueue_effect(eid, reason="тест"),
            ).pack(side="left", padx=(10, 0))
            self.effect_vars[effect_id] = {"enabled": enabled, "amount": amount, "cooldown_sec": cooldown, **extra}

        mine = self.cfg["effects"]["minecraft_takeover"]
        video_card = self._card(body)
        row = tk.Frame(video_card, bg=CARD)
        row.pack(fill="x", padx=12, pady=10)
        tk.Label(row, text="Видео для 10000₽", bg=CARD, fg=FG, font=(FONT, 10)).pack(side="left")
        self.video_path = self._entry(row, 48)
        self.video_path.insert(0, str(mine.get("video_path") or ""))
        self.video_path.pack(side="left", padx=8, fill="x", expand=True)
        ttk.Button(row, text="Файл…", command=self._pick_video).pack(side="left")
        row2 = tk.Frame(video_card, bg=CARD)
        row2.pack(fill="x", padx=12, pady=(0, 10))
        tk.Label(row2, text="или YouTube URL (нужен mpv)", bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="left")
        self.youtube_url = self._entry(row2, 48)
        self.youtube_url.insert(0, str(mine.get("youtube_url") or ""))
        self.youtube_url.pack(side="left", padx=8, fill="x", expand=True)

    def _build_general(self) -> None:
        g = self.cfg["general"]
        page = self._scroll_area(self.tab_general)
        grid = ttk.Frame(page)
        grid.pack(fill="x", pady=12)
        self.enabled_var = tk.BooleanVar(value=bool(g["enabled"]))
        self.require_running = tk.BooleanVar(value=bool(g["require_cs2_running"]))
        self.require_focus = tk.BooleanVar(value=bool(g["require_cs2_focused"]))
        ttk.Checkbutton(grid, text="Эффекты включены", variable=self.enabled_var).grid(row=0, column=0, sticky="w", pady=4)
        ttk.Checkbutton(grid, text="Только если CS2 запущен", variable=self.require_running).grid(row=1, column=0, sticky="w", pady=4)
        ttk.Checkbutton(grid, text="Только если CS2 в фокусе", variable=self.require_focus).grid(row=2, column=0, sticky="w", pady=4)
        overlay = self.cfg.get("overlay") or {}
        self.overlay_enabled = tk.BooleanVar(value=bool(overlay.get("enabled", True)))
        self.overlay_beep = tk.BooleanVar(value=bool(overlay.get("beep", True)))
        self.overlay_ping = tk.BooleanVar(value=bool(overlay.get("ping_flash", True)))
        ttk.Checkbutton(grid, text="Табличка на каждый донат", variable=self.overlay_enabled).grid(row=3, column=0, sticky="w", pady=4)
        ttk.Checkbutton(grid, text="Звук при донате", variable=self.overlay_beep).grid(row=4, column=0, sticky="w", pady=4)
        ttk.Checkbutton(grid, text="Короткая вспышка, если табличка под игрой", variable=self.overlay_ping).grid(row=5, column=0, sticky="w", pady=4)
        self.auto_update = tk.BooleanVar(value=bool(g.get("auto_update", True)))
        ttk.Checkbutton(grid, text="Автообновление с GitHub", variable=self.auto_update).grid(row=6, column=0, sticky="w", pady=4)
        ttk.Button(grid, text="Проверить сейчас", command=self._check_update_now).grid(row=7, column=0, sticky="w", pady=6)

        ttk.Label(grid, text="Режим суммы").grid(row=0, column=1, sticky="e", padx=8)
        self.amount_mode = ttk.Combobox(grid, values=["exact", "threshold"], state="readonly", width=14)
        self.amount_mode.set(g["amount_mode"])
        self.amount_mode.grid(row=0, column=2, sticky="w")
        ttk.Label(grid, text="exact = строго эта сумма (100 не равно 101). threshold = самый дорогой, который донат покрывает").grid(
            row=0, column=3, sticky="w", padx=8
        )

        ttk.Label(grid, text="Очередь").grid(row=1, column=1, sticky="e", padx=8)
        self.queue_mode = ttk.Combobox(grid, values=["queue", "skip", "replace"], state="readonly", width=14)
        self.queue_mode.set(g["queue_mode"])
        self.queue_mode.grid(row=1, column=2, sticky="w")
        ttk.Label(grid, text="queue — копить, skip — игнор пока занято, replace — новый вытесняет очередь").grid(
            row=1, column=3, sticky="w", padx=8
        )

        ttk.Label(grid, text="Допуск суммы, ₽").grid(row=2, column=1, sticky="e", padx=8)
        self.amount_tolerance = self._entry(grid, 8)
        self.amount_tolerance.insert(0, str(g.get("amount_tolerance_rub", 0)))
        self.amount_tolerance.grid(row=2, column=2, sticky="w")
        ttk.Label(grid, text="0 = только точное число. 1 = 100₽ сработает и на 99–101, но возьмётся ближайший эффект").grid(
            row=2, column=3, sticky="w", padx=8
        )

        ttk.Label(grid, text="Глобальный кулдаун, сек").grid(row=3, column=1, sticky="e", padx=8)
        self.global_cd = self._entry(grid, 8)
        self.global_cd.insert(0, str(g["global_cooldown_sec"]))
        self.global_cd.grid(row=3, column=2, sticky="w")

        ttk.Label(grid, text="Пауза теста, сек").grid(row=4, column=1, sticky="e", padx=8)
        self.test_delay = self._entry(grid, 8)
        self.test_delay.insert(0, str(g.get("test_delay_sec", 3)))
        self.test_delay.grid(row=4, column=2, sticky="w")
        ttk.Label(grid, text="после «Тест» или фейк-алерта DA успей перейти в CS2").grid(
            row=4, column=3, sticky="w", padx=8
        )

        ttk.Label(grid, text="Макс. очередь").grid(row=5, column=1, sticky="e", padx=8)
        self.max_queue = self._entry(grid, 8)
        self.max_queue.insert(0, str(g["max_queue"]))
        self.max_queue.grid(row=5, column=2, sticky="w")

        ttk.Label(grid, text="Аварийный стоп").grid(row=6, column=1, sticky="e", padx=8)
        self.kill_switch = self._entry(grid, 14)
        self.kill_switch.insert(0, g["kill_switch"])
        self.kill_switch.grid(row=6, column=2, sticky="w")

        ttk.Label(grid, text="Паника").grid(row=7, column=1, sticky="e", padx=8)
        self.panic_hotkey = self._entry(grid, 14)
        self.panic_hotkey.insert(0, g["panic_hotkey"])
        self.panic_hotkey.grid(row=7, column=2, sticky="w")

        ttk.Label(
            page,
            text="Alt+5 снимает флешку, возвращает WASD, закрывает летсплей и чистит очередь. Ctrl+Alt+5 полностью глушит эффекты до ручного включения.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=10)

        flash = self.cfg["effects"]["flash"]
        jerk = self.cfg["effects"]["mouse_jerk"]
        nade = self.cfg["effects"]["nade_and_crouch"]
        extra = ttk.Frame(page)
        extra.pack(fill="x", pady=8)
        ttk.Label(extra, text="Флешка: режим").grid(row=0, column=0, sticky="e", padx=8)
        self.flash_mode = ttk.Combobox(extra, values=["gamma_and_overlay", "gamma", "overlay"], state="readonly", width=22)
        self.flash_mode.set(flash.get("mode", "gamma_and_overlay"))
        self.flash_mode.grid(row=0, column=1, sticky="w")
        ttk.Label(extra, text="Срыв сенсы: сила").grid(row=1, column=0, sticky="e", padx=8, pady=6)
        self.jerk_intensity = self._entry(extra, 8)
        self.jerk_intensity.insert(0, str(jerk.get("intensity", 900)))
        self.jerk_intensity.grid(row=1, column=1, sticky="w")
        ttk.Label(extra, text="Граната: пиксели вниз").grid(row=2, column=0, sticky="e", padx=8)
        self.look_down = self._entry(extra, 8)
        self.look_down.insert(0, str(nade.get("look_down_pixels", 3200)))
        self.look_down.grid(row=2, column=1, sticky="w")

    def _open(self, url: str) -> None:
        webbrowser.open(url)

    def _build_da(self) -> None:
        ttk.Label(
            self.tab_da,
            text="Можно включить одну площадку или все сразу. Токены хранятся только на этом компьютере.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(8, 8))
        sub = ttk.Notebook(self.tab_da)
        sub.pack(fill="both", expand=True)
        tab_how = ttk.Frame(sub)
        tab_da = ttk.Frame(sub)
        tab_dp = ttk.Frame(sub)
        tab_trula = ttk.Frame(sub)
        sub.add(tab_how, text="Как подключить")
        sub.add(tab_da, text="DonationAlerts")
        sub.add(tab_dp, text="DonatePay")
        sub.add(tab_trula, text="Trula")
        self._build_how(tab_how)
        self._build_da_fields(tab_da)
        self._build_dp_fields(tab_dp)
        self._build_trula_fields(tab_trula)

    def _build_how(self, parent: tk.Widget) -> None:
        dash = tk.Frame(parent, bg=CARD, highlightbackground=CHIP_LINE, highlightthickness=1)
        dash.pack(fill="x", pady=(8, 10), padx=2)
        tk.Label(
            dash,
            text="Живой статус. Зелёный = донаты реально могут прийти. «Токен вставлен» само по себе ничего не значит.",
            bg=CARD,
            fg=MUTED,
            font=(FONT, 9),
            wraplength=980,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(12, 6))
        row = tk.Frame(dash, bg=CARD)
        row.pack(fill="x", padx=14, pady=(0, 8))
        self.dash_da = tk.Label(row, text="DonationAlerts: не привязан", bg=CARD, fg=BAD, font=(FONT, 10, "bold"), anchor="w", justify="left")
        self.dash_dp = tk.Label(row, text="DonatePay: не привязан", bg=CARD, fg=BAD, font=(FONT, 10, "bold"), anchor="w", justify="left")
        self.dash_trula = tk.Label(row, text="Trula: не привязана", bg=CARD, fg=BAD, font=(FONT, 10, "bold"), anchor="w", justify="left")
        self.dash_da.pack(fill="x")
        self.dash_dp.pack(fill="x")
        self.dash_trula.pack(fill="x")
        self.dash_da_d = tk.Label(dash, text="", bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w", wraplength=980, justify="left")
        self.dash_dp_d = tk.Label(dash, text="", bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w", wraplength=980, justify="left")
        self.dash_trula_d = tk.Label(dash, text="", bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w", wraplength=980, justify="left")
        self.dash_da_d.pack(fill="x", padx=14)
        self.dash_dp_d.pack(fill="x", padx=14)
        self.dash_trula_d.pack(fill="x", padx=14)
        self.last_don_lbl = tk.Label(
            dash,
            text="Последний донат, который увидело приложение: ещё не было",
            bg=CARD,
            fg=ACCENT,
            font=(FONT, 10, "bold"),
            anchor="w",
            wraplength=980,
            justify="left",
        )
        self.last_don_lbl.pack(fill="x", padx=14, pady=(8, 14))

        lines = [
            "1. Нажми «Открыть кабинет», скопируй токен/ссылку.",
            "2. Вставь в поле на вкладке площадки.",
            "3. Нажми «Сохранить и проверить связь» — через несколько секунд будет «подключено» или ошибка.",
            "4. В кабинете площадки отправь тестовый алерт на 100₽. В логе должна появиться строка «приложение увидело донат».",
            "Кнопка «Тест» на вкладке Эффекты CS2 не проверяет донаты.",
        ]
        for line in lines:
            ttk.Label(parent, text=line, style="Muted.TLabel").pack(anchor="w", pady=2)
        btns = ttk.Frame(parent)
        btns.pack(anchor="w", pady=12)
        ttk.Button(btns, text="Открыть кабинет DonationAlerts", command=lambda: self._open_cabinet("da")).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="Открыть кабинет DonatePay", command=lambda: self._open_cabinet("dp")).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="Открыть кабинет Trula", command=lambda: self._open_cabinet("trula")).pack(side="left")
        checks = ttk.Frame(parent)
        checks.pack(anchor="w", pady=(0, 8))
        ttk.Button(checks, text="Проверить DonationAlerts", style="Accent.TButton", command=lambda: self._check_link("da")).pack(side="left", padx=(0, 8))
        ttk.Button(checks, text="Проверить DonatePay", style="Accent.TButton", command=lambda: self._check_link("dp")).pack(side="left", padx=(0, 8))
        ttk.Button(checks, text="Проверить Trula", style="Accent.TButton", command=lambda: self._check_link("trula")).pack(side="left")

    def _build_da_fields(self, parent: tk.Widget) -> None:
        da = self.cfg["donationalerts"]
        box = ttk.Frame(parent)
        box.pack(fill="x", pady=8)
        ttk.Label(box, text="Самый простой путь: секретный токен виджета из кабинета DonationAlerts.").grid(row=0, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Label(
            box,
            text="Кабинет → Настройки / Оповещения → «Секретный токен» или ссылка виджета с token=. Потом «Привязать аккаунт».",
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))
        ttk.Button(box, text="Открыть кабинет DonationAlerts", command=lambda: self._open_cabinet("da")).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(box, text="Секретный токен или ссылка виджета").grid(row=3, column=0, sticky="e", padx=8, pady=6)
        da_wrap = ttk.Frame(box)
        da_wrap.grid(row=3, column=1, sticky="we", pady=6)
        self.da_widget = self._entry(da_wrap, 64, secret=True)
        self.da_widget.insert(0, da.get("widget_token", ""))
        self.da_widget.pack(side="left", fill="x", expand=True)
        self._paste_button(da_wrap, self.da_widget).pack(side="left", padx=(8, 0))
        ttk.Button(box, text="Сохранить и проверить связь", style="Accent.TButton", command=lambda: self._check_link("da")).grid(row=4, column=1, sticky="w", pady=8)

        ttk.Label(box, text="Дополнительно, если виджет не подходит — OAuth API", style="Muted.TLabel").grid(row=5, column=0, columnspan=3, sticky="w", pady=(12, 4))
        ttk.Label(box, text="Access token").grid(row=6, column=0, sticky="e", padx=8, pady=4)
        da_token_wrap = ttk.Frame(box)
        da_token_wrap.grid(row=6, column=1, sticky="we", pady=4)
        self.da_token = self._entry(da_token_wrap, 64, secret=True)
        self.da_token.insert(0, da.get("access_token", ""))
        self.da_token.pack(side="left", fill="x", expand=True)
        self._paste_button(da_token_wrap, self.da_token).pack(side="left", padx=(8, 0))
        ttk.Label(box, text="Client ID").grid(row=7, column=0, sticky="e", padx=8, pady=4)
        self.da_client = self._entry(box, 32)
        self.da_client.insert(0, da.get("client_id", ""))
        self.da_client.grid(row=7, column=1, sticky="w", pady=4)
        ttk.Label(box, text="Client secret").grid(row=8, column=0, sticky="e", padx=8, pady=4)
        self.da_secret = self._entry(box, 48, secret=True)
        self.da_secret.insert(0, da.get("client_secret", ""))
        self.da_secret.grid(row=8, column=1, sticky="we", pady=4)
        ttk.Label(box, text="Режим API").grid(row=9, column=0, sticky="e", padx=8, pady=4)
        self.da_mode = ttk.Combobox(box, values=["websocket", "poll"], state="readonly", width=16)
        self.da_mode.set(da.get("mode", "websocket"))
        self.da_mode.grid(row=9, column=1, sticky="w")
        ttk.Button(box, text="Войти через DonationAlerts OAuth", command=self._oauth).grid(row=10, column=1, sticky="w", pady=8)
        ttk.Label(box, text="Тестовый алерт из кабинета тоже ловится. Сумма должна совпасть с эффектом (100, 200…). После теста — 3 сек, успей в CS2.", style="Muted.TLabel").grid(row=11, column=0, columnspan=3, sticky="w", pady=8)
        box.columnconfigure(1, weight=1)

    def _build_dp_fields(self, parent: tk.Widget) -> None:
        dp = self.cfg["donatepay"]
        box = ttk.Frame(parent)
        box.pack(fill="x", pady=8)
        ttk.Label(box, text="Нужны два куска из кабинета DonatePay: API-ключ и ссылка виджета оповещений.").grid(row=0, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Label(box, text="API даёт историю, виджет даёт донат сразу. Лучше вставить оба и нажать «Привязать аккаунт».", style="Muted.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))
        ttk.Button(box, text="Открыть кабинет DonatePay", command=lambda: self._open_cabinet("dp")).grid(row=2, column=1, sticky="w", pady=4)
        self.dp_enabled = tk.BooleanVar(value=bool(dp.get("enabled", True)))
        ttk.Checkbutton(box, text="Слушать DonatePay", variable=self.dp_enabled).grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(box, text="API-ключ").grid(row=4, column=0, sticky="e", padx=8, pady=6)
        dp_wrap = ttk.Frame(box)
        dp_wrap.grid(row=4, column=1, sticky="we", pady=6)
        self.dp_token = self._entry(dp_wrap, 64, secret=True)
        self.dp_token.insert(0, dp.get("api_token", ""))
        self.dp_token.pack(side="left", fill="x", expand=True)
        self._paste_button(dp_wrap, self.dp_token).pack(side="left", padx=(8, 0))
        ttk.Label(box, text="Ссылка виджета оповещений").grid(row=5, column=0, sticky="e", padx=8, pady=6)
        dp_w_wrap = ttk.Frame(box)
        dp_w_wrap.grid(row=5, column=1, sticky="we", pady=6)
        self.dp_widget = self._entry(dp_w_wrap, 64, secret=True)
        self.dp_widget.insert(0, dp.get("widget_token", ""))
        self.dp_widget.pack(side="left", fill="x", expand=True)
        self._paste_button(dp_w_wrap, self.dp_widget).pack(side="left", padx=(8, 0))
        ttk.Label(box, text="Интервал опроса API, сек").grid(row=6, column=0, sticky="e", padx=8, pady=4)
        self.dp_interval = self._entry(box, 8)
        self.dp_interval.insert(0, str(dp.get("poll_interval_sec", 8)))
        self.dp_interval.grid(row=6, column=1, sticky="w", pady=4)
        ttk.Button(box, text="Сохранить и проверить связь", style="Accent.TButton", command=lambda: self._check_link("dp")).grid(row=7, column=1, sticky="w", pady=8)
        ttk.Label(box, text="Виджет: donatepay.ru/donation/notifications → скопируй ссылку widget.donatepay.ru/alert-box/widget/…", style="Muted.TLabel").grid(row=8, column=0, columnspan=3, sticky="w", pady=8)
        box.columnconfigure(1, weight=1)

    def _build_trula_fields(self, parent: tk.Widget) -> None:
        trula = self.cfg["trula"]
        box = ttk.Frame(parent)
        box.pack(fill="x", pady=8)
        ttk.Label(box, text="Нужна ссылка панели Trula: https://trula.io/cp/?token=… (её же ставят в OBS).").grid(row=0, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Label(box, text="Страница доната /dp/... не подойдёт. Кабинет /cp/?token= — как раз то, что нужно.", style="Muted.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))
        ttk.Button(box, text="Открыть кабинет Trula", command=lambda: self._open_cabinet("trula")).grid(row=2, column=1, sticky="w", pady=4)
        self.trula_enabled = tk.BooleanVar(value=bool(trula.get("enabled", True)))
        ttk.Checkbutton(box, text="Слушать Trula", variable=self.trula_enabled).grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(box, text="Ссылка виджета или токен").grid(row=4, column=0, sticky="e", padx=8, pady=6)
        trula_wrap = ttk.Frame(box)
        trula_wrap.grid(row=4, column=1, sticky="we", pady=6)
        self.trula_widget = self._entry(trula_wrap, 64, secret=True)
        self.trula_widget.insert(0, trula.get("widget_url", ""))
        self.trula_widget.pack(side="left", fill="x", expand=True)
        self._paste_button(trula_wrap, self.trula_widget).pack(side="left", padx=(8, 0))
        ttk.Button(box, text="Сохранить и проверить связь", style="Accent.TButton", command=lambda: self._check_link("trula")).grid(row=5, column=1, sticky="w", pady=8)
        box.columnconfigure(1, weight=1)

    def _build_keys(self) -> None:
        keys = self.cfg["cs2"]["keys"]
        box = ttk.Frame(self.tab_keys)
        box.pack(fill="x", pady=12)
        ttk.Label(
            box,
            text="Если у стримера кастомные бинды — пропиши их здесь. Для гранаты лучше отдельный HE-бинд, а не колесо 4.",
            style="Muted.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self.key_entries: dict[str, tk.Entry] = {}
        labels = {
            "drop": "Дроп оружия",
            "grenade": "Граната / HE",
            "crouch": "Присед",
            "fire": "Выстрел / бросок",
            "forward": "Вперёд",
            "back": "Назад",
            "left": "Влево",
            "right": "Вправо",
        }
        for i, (key, title) in enumerate(labels.items(), start=1):
            ttk.Label(box, text=title).grid(row=i, column=0, sticky="e", padx=8, pady=4)
            entry = self._entry(box, 12)
            entry.insert(0, keys.get(key, ""))
            entry.grid(row=i, column=1, sticky="w")
            self.key_entries[key] = entry
        ttk.Label(box, text="Бросок гранаты под ноги").grid(row=9, column=0, sticky="e", padx=8, pady=4)
        entry = self._entry(box, 12)
        entry.insert(0, keys.get("nade_throw", "rbutton"))
        entry.grid(row=9, column=1, sticky="w")
        self.key_entries["nade_throw"] = entry
        ttk.Label(box, text="Заголовок окна CS2").grid(row=10, column=0, sticky="e", padx=8, pady=10)
        self.window_title = self._entry(box, 28)
        self.window_title.insert(0, self.cfg["cs2"]["window_title"])
        self.window_title.grid(row=10, column=1, sticky="w", pady=10)

    def _build_log(self) -> None:
        row = ttk.Frame(self.tab_log)
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(
            row,
            text="Этот лог пишется в файл. Скопируй и пришли, если эффект не сработал.",
            style="Muted.TLabel",
        ).pack(side="left")
        ttk.Button(row, text="Скопировать лог", command=self._copy_log).pack(side="right")
        ttk.Button(row, text="Открыть файл лога", command=self._open_log_file).pack(side="right", padx=8)
        self.log_box = tk.Text(
            self.tab_log,
            bg=ENTRY_BG,
            fg="#ddd6fe",
            insertbackground=ACCENT,
            relief="flat",
            state="disabled",
            font=(FONT_MONO, 10),
            highlightthickness=1,
            highlightbackground=CHIP_LINE,
            selectbackground=ACCENT_DARK,
            selectforeground=WHITE,
            padx=10,
            pady=8,
        )
        self.log_box.pack(fill="both", expand=True, pady=8)
        self.log("Приложение запущено. Дроп/мышь/граната работают только если CS2 в фокусе.")
        self.log("Для клавиш в CS2 запусти run-admin.bat. Игра — «Во весь экран в окне», не эксклюзивный полный экран.")
        self.log("Живой донат: зелёный статус «подключено», потом тест 100₽ в кабинете. В логе должно быть «приложение увидело донат».")
        self.log(f"Файл лога: {LOG_PATH}")
        self.log("Автообновление: при старте и раз в 45 мин смотрит GitHub. Токены и видео не затирает. На стриме само окно не закрывает.")

    def _collect(self) -> None:
        self.cfg["general"]["enabled"] = self.enabled_var.get()
        self.cfg["general"]["require_cs2_running"] = self.require_running.get()
        self.cfg["general"]["require_cs2_focused"] = self.require_focus.get()
        self.cfg["general"]["amount_mode"] = self.amount_mode.get()
        self.cfg["general"]["amount_tolerance_rub"] = float(
            self.amount_tolerance.get() or 0
        ) if hasattr(self, "amount_tolerance") else 0
        self.cfg["general"]["queue_mode"] = self.queue_mode.get()
        self.cfg["general"]["global_cooldown_sec"] = float(self.global_cd.get() or 0)
        self.cfg["general"]["test_delay_sec"] = float(self.test_delay.get() or 0)
        self.cfg["general"]["max_queue"] = int(self.max_queue.get() or 5)
        self.cfg["general"]["kill_switch"] = self.kill_switch.get().strip() or "alt+5"
        self.cfg["general"]["panic_hotkey"] = self.panic_hotkey.get().strip() or "ctrl+alt+5"
        self.cfg["general"]["auto_update"] = self.auto_update.get() if hasattr(self, "auto_update") else True
        self.cfg["overlay"]["enabled"] = self.overlay_enabled.get() if hasattr(self, "overlay_enabled") else True
        self.cfg["overlay"]["beep"] = self.overlay_beep.get() if hasattr(self, "overlay_beep") else True
        self.cfg["overlay"]["ping_flash"] = self.overlay_ping.get() if hasattr(self, "overlay_ping") else True
        self.cfg["effects"]["flash"]["mode"] = self.flash_mode.get()
        self.cfg["effects"]["mouse_jerk"]["intensity"] = int(self.jerk_intensity.get() or 900)
        self.cfg["effects"]["nade_and_crouch"]["look_down_pixels"] = int(self.look_down.get() or 3200)
        self.cfg["effects"]["minecraft_takeover"]["video_path"] = self.video_path.get().strip()
        self.cfg["effects"]["minecraft_takeover"]["youtube_url"] = self.youtube_url.get().strip()
        self.cfg["donationalerts"]["access_token"] = self.da_token.get().strip()
        self.cfg["donationalerts"]["widget_token"] = self.da_widget.get().strip()
        self.cfg["donationalerts"]["client_id"] = self.da_client.get().strip()
        self.cfg["donationalerts"]["client_secret"] = self.da_secret.get().strip()
        self.cfg["donationalerts"]["mode"] = self.da_mode.get()
        self.cfg["donatepay"]["enabled"] = self.dp_enabled.get()
        self.cfg["donatepay"]["api_token"] = self.dp_token.get().strip()
        self.cfg["donatepay"]["widget_token"] = self.dp_widget.get().strip() if hasattr(self, "dp_widget") else ""
        self.cfg["donatepay"]["poll_interval_sec"] = float(self.dp_interval.get() or 8)
        self.cfg["trula"]["enabled"] = self.trula_enabled.get()
        self.cfg["trula"]["widget_url"] = self.trula_widget.get().strip()
        self.cfg["cs2"]["window_title"] = self.window_title.get().strip() or "Counter-Strike 2"
        for key, entry in self.key_entries.items():
            self.cfg["cs2"]["keys"][key] = entry.get().strip()
        for effect_id, vars_ in self.effect_vars.items():
            self.cfg["effects"][effect_id]["enabled"] = vars_["enabled"].get()
            self.cfg["effects"][effect_id]["amount"] = float(vars_["amount"].get() or 0)
            self.cfg["effects"][effect_id]["cooldown_sec"] = float(vars_["cooldown_sec"].get() or 0)
            if "duration_sec" in vars_:
                self.cfg["effects"][effect_id]["duration_sec"] = float(vars_["duration_sec"].get() or 0)

    def _save(self) -> None:
        try:
            self._collect()
            save_config(self.cfg)
            self.engine.guard.kill_switch = self.cfg["general"]["kill_switch"]
            self.engine.guard.panic_hotkey = self.cfg["general"]["panic_hotkey"]
            self.log("Настройки сохранены.")
            da = self.cfg["donationalerts"]
            if da.get("widget_token") or da.get("access_token"):
                self._reconnect_da()
            if self.cfg["donatepay"].get("enabled") and (
                self.cfg["donatepay"].get("api_token") or self.cfg["donatepay"].get("widget_token")
            ):
                self._reconnect_dp()
            if self.cfg["trula"].get("enabled") and self.cfg["trula"].get("widget_url"):
                self._reconnect_trula()
        except Exception as exc:
            messagebox.showerror("Ошибка", str(exc))

    def _pick_video(self) -> None:
        path = filedialog.askopenfilename(
            title="Minecraft летсплей",
            filetypes=[("Видео", "*.mp4 *.mkv *.webm *.avi"), ("Все файлы", "*.*")],
        )
        if path:
            self.video_path.delete(0, "end")
            self.video_path.insert(0, path)

    def _oauth(self) -> None:
        self._collect()
        cid = self.cfg["donationalerts"]["client_id"]
        secret = self.cfg["donationalerts"]["client_secret"]
        redirect = self.cfg["donationalerts"]["redirect_uri"]
        if not cid or not secret:
            messagebox.showinfo("DonationAlerts", "Сначала вставь Client ID и Client secret.")
            return

        def worker() -> None:
            try:
                token = oauth_login(cid, secret, redirect)
            except Exception as exc:
                self.log(f"OAuth не удался: {exc}")
                return
            def apply() -> None:
                self.da_token.delete(0, "end")
                self.da_token.insert(0, token)
                self._save()
                self._reconnect_da()
            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()
        self.log("Открой браузер и подтверди доступ DonationAlerts.")

    def _open_cabinet(self, kind: str) -> None:
        pages = {
            "da": [
                "https://www.donationalerts.com/dashboard/general",
                "https://www.donationalerts.com/dashboard/alert-widget",
            ],
            "dp": [
                "https://donatepay.ru/donation/notifications/",
                "https://donatepay.ru/page/api",
            ],
            "trula": [
                "https://trula.io/login",
                "https://trula.io/",
            ],
        }
        hints = {
            "da": "Скопируй «Секретный токен» или ссылку виджета с token=, вставь в поле и нажми «Сохранить и проверить связь».",
            "dp": "Скопируй ссылку widget.donatepay.ru/alert-box/widget/… и отдельно API-ключ со страницы /page/api. Вставь оба поля, потом «Сохранить и проверить связь».",
            "trula": "Скопируй ссылку панели https://trula.io/cp/?token=… (её же вставляют в OBS). Вставь в поле и нажми «Сохранить и проверить связь».",
        }
        titles = {"da": "DonationAlerts", "dp": "DonatePay", "trula": "Trula"}
        for url in pages[kind]:
            self._open(url)
        messagebox.showinfo(titles[kind], hints[kind])

    def _check_link(self, kind: str) -> None:
        titles = {"da": "DonationAlerts", "dp": "DonatePay", "trula": "Trula"}
        title = titles[kind]
        try:
            self._collect()
            save_config(self.cfg)
        except Exception as exc:
            messagebox.showerror(title, str(exc))
            return
        if kind == "da":
            if not (self.cfg["donationalerts"].get("widget_token") or self.cfg["donationalerts"].get("access_token")):
                messagebox.showinfo(title, "Сначала вставь секретный токен или ссылку виджета в поле.")
                return
            self._reconnect_da()
            client = self.da
        elif kind == "dp":
            if not (
                self.cfg["donatepay"].get("api_token") or self.cfg["donatepay"].get("widget_token")
            ):
                messagebox.showinfo(title, "Сначала вставь API-ключ и/или ссылку виджета.")
                return
            self.dp_enabled.set(True)
            self.cfg["donatepay"]["enabled"] = True
            self._reconnect_dp()
            client = self.dp
        else:
            if not self.cfg["trula"].get("widget_url"):
                messagebox.showinfo(title, "Сначала вставь ссылку виджета Trula.")
                return
            self.trula_enabled.set(True)
            self.cfg["trula"]["enabled"] = True
            self._reconnect_trula()
            client = self.trula
        self.log(f"{title}: проверяю связь, жду до 12 сек…")

        def wait() -> None:
            deadline = time.time() + 12
            while time.time() < deadline:
                if client.link.state == "live" or client.connected:
                    def ok() -> None:
                        messagebox.showinfo(
                            title,
                            "Подключено.\n\n"
                            f"{client.link.detail}\n\n"
                            "Теперь в кабинете площадки отправь тестовый алерт на 100₽.\n"
                            "В логе должна появиться строка «приложение увидело донат».\n"
                            "Если её нет — приложение донат не получило.",
                        )
                    self.after(0, ok)
                    return
                if client.link.state == "bad":
                    detail = client.link.detail
                    self.after(0, lambda d=detail: messagebox.showerror(title, d))
                    return
                time.sleep(0.3)
            detail = client.link.detail or "сокет не подтвердился"
            def late() -> None:
                messagebox.showwarning(
                    title,
                    "За 12 секунд не получил «подключено».\n\n"
                    f"Сейчас: {detail}\n\n"
                    "Чаще всего вставлен не тот токен/ссылка. Проверь лог и вставь заново.",
                )
            self.after(0, late)

        threading.Thread(target=wait, daemon=True).start()

    def _reconnect_da(self) -> None:
        self._collect()
        save_config(self.cfg)
        self.da.start(
            self.cfg["donationalerts"]["access_token"],
            self.cfg["donationalerts"]["mode"],
            self.cfg["donationalerts"].get("widget_token", ""),
        )

    def _reconnect_dp(self) -> None:
        self._collect()
        save_config(self.cfg)
        if not self.cfg["donatepay"].get("enabled"):
            self.dp.stop()
            self.log("DonatePay выключен в настройках.")
            return
        self.dp.start(
            self.cfg["donatepay"]["api_token"],
            float(self.cfg["donatepay"].get("poll_interval_sec") or 8),
            str(self.cfg["general"].get("currency") or "RUB"),
            self.cfg["donatepay"].get("widget_token", ""),
        )

    def _reconnect_trula(self) -> None:
        self._collect()
        save_config(self.cfg)
        if not self.cfg["trula"].get("enabled"):
            self.trula.stop()
            self.log("Trula выключена в настройках.")
            return
        self.trula.start(self.cfg["trula"].get("widget_url", ""))

    def _start_services(self) -> None:
        da = self.cfg["donationalerts"]
        if da.get("widget_token") or da.get("access_token"):
            self.da.start(da.get("access_token", ""), da.get("mode", "websocket"), da.get("widget_token", ""))
        else:
            self.log("DonationAlerts не привязан. Вкладка Донаты → вставь токен и нажми «Сохранить и проверить связь».")
        dp = self.cfg["donatepay"]
        if dp.get("enabled") and (dp.get("api_token") or dp.get("widget_token")):
            self.dp.start(
                dp.get("api_token", ""),
                float(dp.get("poll_interval_sec") or 8),
                str(self.cfg["general"].get("currency") or "RUB"),
                dp.get("widget_token", ""),
            )
        elif dp.get("enabled"):
            self.log("DonatePay не привязан. Вкладка Донаты → вставь ключ и ссылку виджета, затем «Сохранить и проверить связь».")
        if self.cfg["trula"].get("enabled") and self.cfg["trula"].get("widget_url"):
            self.trula.start(self.cfg["trula"]["widget_url"])
        elif self.cfg["trula"].get("enabled"):
            self.log("Trula не привязана. Вкладка Донаты → вставь ссылку виджета и нажми «Сохранить и проверить связь».")
        if self.cfg["webhook"].get("enabled"):
            self.webhook.start(self.cfg["webhook"]["host"], int(self.cfg["webhook"]["port"]))

    def _on_donation(self, donation: Donation) -> None:
        kind = "тест-алерт" if donation.is_test else "ДОНАТ"
        self.log(
            f"{kind}: {donation.username} — {donation.amount:g} {donation.currency} "
            f"id={donation.donation_id or '-'} source={donation.source} msg={donation.message!r}"
        )
        text = (
            f"Последний донат, который увидело приложение: {donation.username} — "
            f"{donation.amount:g} {donation.currency} ({donation.source})"
        )

        def show() -> None:
            if hasattr(self, "last_don_lbl"):
                self.last_don_lbl.configure(text=text, fg=OK)

        if threading.current_thread() is threading.main_thread():
            show()
        else:
            self.after(0, show)
        self.engine.enqueue_donation(donation)

    def _test_overlay(self) -> None:
        donation = Donation(username="Проверка", amount=100, currency="RUB", source="manual", is_test=True)
        self.engine.announce_donation(donation, "flash")
        self.log(
            "Проверка таблички: снизу должна появиться широкая плашка и короткий звук. "
            "Если её не видно поверх CS2 — поставь игру «Во весь экран в окне». "
            "С античитом клавиши могут не идти, табличка и вспышка должны."
        )

    def _copy_log(self) -> None:
        text = read_tail()
        if not text and hasattr(self, "log_box"):
            text = self.log_box.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("Лог", "Лог пока пустой.")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.log("Лог скопирован в буфер. Вставь его в чат, если эффект не сработал.")

    def _open_log_file(self) -> None:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.touch(exist_ok=True)
        webbrowser.open(LOG_PATH.as_uri())

    def _panic(self) -> None:
        self.engine.panic()
        self.enabled_var.set(False)
        self.cfg["general"]["enabled"] = False

    def _resume(self) -> None:
        self.engine.paused = False
        self.enabled_var.set(True)
        self.cfg["general"]["enabled"] = True
        self.log("Эффекты снова включены.")

    def _paint_link(
        self,
        head_lbl: tk.Label,
        chip: tk.Frame | None,
        dash_lbl: tk.Label | None,
        dash_detail: tk.Label | None,
        client,
        short: str,
    ) -> None:
        colors = {"off": BAD, "wait": WARN, "live": OK, "bad": BAD}
        words = {"off": "нет", "wait": "подключаюсь", "live": "подключено", "bad": "ошибка"}
        state = getattr(getattr(client, "link", None), "state", "off")
        detail = getattr(getattr(client, "link", None), "detail", "")
        color = colors.get(state, MUTED)
        fill = CHIP_FILL.get(state, CHIP_BG)
        head_lbl.configure(text=f"{short}: {words.get(state, state)}", fg=color, bg=fill)
        if chip is not None:
            chip.configure(bg=fill)
        if dash_lbl is not None:
            dash_lbl.configure(text=client.link.label(), fg=color)
        if dash_detail is not None:
            extra = client.link.last if client.link.last else ""
            dash_detail.configure(text=f"    {detail}" + (f"  |  {extra}" if extra and extra not in detail else ""))

    def _tick(self) -> None:
        running = is_cs2_running(self.cfg["cs2"]["process_name"])
        cs2_fill = CHIP_FILL["live"] if running else CHIP_BG
        self.status_cs2.configure(
            text="CS2: запущена" if running else "CS2: нет",
            fg=OK if running else MUTED,
            bg=cs2_fill,
        )
        self.status_cs2_chip.configure(bg=cs2_fill)
        self._paint_link(
            self.status_da,
            self.status_da_chip,
            getattr(self, "dash_da", None),
            getattr(self, "dash_da_d", None),
            self.da,
            "DA",
        )
        self._paint_link(
            self.status_dp,
            self.status_dp_chip,
            getattr(self, "dash_dp", None),
            getattr(self, "dash_dp_d", None),
            self.dp,
            "DP",
        )
        self._paint_link(
            self.status_trula,
            self.status_trula_chip,
            getattr(self, "dash_trula", None),
            getattr(self, "dash_trula_d", None),
            self.trula,
            "Trula",
        )
        if self.engine.paused or not self.cfg["general"]["enabled"]:
            fill = CHIP_FILL["bad"]
            self.status_sys.configure(text="эффекты: выкл", fg=BAD, bg=fill)
            self.status_sys_chip.configure(bg=fill)
        elif self.engine.busy:
            fill = CHIP_FILL["wait"]
            self.status_sys.configure(
                text=f"эффект: {EFFECT_TITLES.get(self.engine.current_effect, '…')}",
                fg=WARN,
                bg=fill,
            )
            self.status_sys_chip.configure(bg=fill)
        else:
            fill = CHIP_FILL["live"]
            self.status_sys.configure(text="эффекты: вкл", fg=OK, bg=fill)
            self.status_sys_chip.configure(bg=fill)
        self.after(500, self._tick)

    def _paint_update(self, status: str, detail: str = "") -> None:
        labels = {
            "current": "GH: ок",
            "updated": "GH: перезапуск",
            "pending": "GH: перезапуск",
            "skipped": "GH: git",
            "error": "GH: нет сети",
            "off": "GH: выкл",
            "checking": "GH: …",
        }
        colors = {
            "current": (OK, CHIP_FILL["live"]),
            "updated": (WARN, CHIP_FILL["wait"]),
            "pending": (WARN, CHIP_FILL["wait"]),
            "skipped": (MUTED, CHIP_BG),
            "error": (MUTED, CHIP_BG),
            "off": (MUTED, CHIP_BG),
            "checking": (WARN, CHIP_FILL["wait"]),
        }
        fg, fill = colors.get(status, (MUTED, CHIP_BG))
        if hasattr(self, "status_upd"):
            self.status_upd.configure(text=labels.get(status, "GH: …"), fg=fg, bg=fill)
            self.status_upd_chip.configure(bg=fill)
        pending = status in {"updated", "pending"}
        self._update_pending = pending
        if hasattr(self, "btn_restart_update"):
            if pending and not self.btn_restart_update.winfo_ismapped():
                self.btn_restart_update.pack(side="right", padx=8)
            elif not pending and self.btn_restart_update.winfo_ismapped():
                self.btn_restart_update.pack_forget()
        if detail and status not in {"current", "checking"}:
            self.log(f"обновление: {detail}")

    def _start_updater(self) -> None:
        self._update_pending = False
        self._update_stop = threading.Event()
        if not bool(self.cfg["general"].get("auto_update", True)):
            self._paint_update("off")
        else:
            self._paint_update("checking")
        threading.Thread(target=self._updater_loop, name="updater", daemon=True).start()

    def _updater_loop(self) -> None:
        first = True
        while not self._update_stop.is_set():
            if first:
                first = False
            else:
                if self._update_stop.wait(CHECK_EVERY_SEC):
                    return
            if not bool(self.cfg["general"].get("auto_update", True)):
                self.after(0, lambda: self._paint_update("off"))
                continue
            try:
                result = check_and_apply(apply=True)
            except Exception as exc:
                result_status, result_detail = "error", str(exc)
            else:
                result_status, result_detail = result.status, result.detail
                if result.changed:
                    result_status = "updated"
            self.after(0, lambda s=result_status, d=result_detail: self._paint_update(s, d))

    def _check_update_now(self) -> None:
        try:
            self._collect()
            save_config(self.cfg)
        except Exception:
            pass
        self._paint_update("checking")

        def worker() -> None:
            try:
                result = check_and_apply(apply=True, on_status=lambda text: self.log(text))
                status = "updated" if result.changed else result.status
                self.after(0, lambda: self._paint_update(status, result.detail))
            except Exception as exc:
                self.after(0, lambda: self._paint_update("error", str(exc)))

        threading.Thread(target=worker, name="updater-now", daemon=True).start()

    def _restart_for_update(self) -> None:
        self.log("Перезапуск, чтобы подхватить обновление с GitHub…")
        try:
            self._collect()
            save_config(self.cfg)
        except Exception:
            pass
        self.engine.shutdown()
        self.da.stop()
        self.dp.stop()
        self.trula.stop()
        self.webhook.stop()
        try:
            self.destroy()
        except tk.TclError:
            pass
        restart_process()

    def _on_close(self) -> None:
        if hasattr(self, "_update_stop"):
            self._update_stop.set()
        try:
            self.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass
        try:
            self._collect()
            save_config(self.cfg)
        except Exception:
            pass
        self.engine.shutdown()
        self.da.stop()
        self.dp.stop()
        self.trula.stop()
        self.webhook.stop()
        self.destroy()


def run() -> None:
    app = App()
    app.mainloop()
