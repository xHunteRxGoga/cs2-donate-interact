from __future__ import annotations

import threading
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


BG = "#120815"
PANEL = "#1c1228"
CARD = "#27183a"
FG = "#f4eefe"
MUTED = "#b7a6cc"
ACCENT = "#c4b5fd"
ACCENT_DARK = "#7c5cbf"
BUTTON = "#3a2458"
BUTTON_HOVER = "#4e3174"
OK = "#7ee0b8"
BAD = "#ff7b9c"
ENTRY_BG = "#0e0816"
HIGHLIGHT = "#8b6cc9"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("CS2 Donate Interact")
        self.geometry("1100x720")
        self.minsize(980, 640)
        self.configure(bg=BG)
        self.cfg = load_config()
        self.engine = EffectEngine(lambda: self.cfg, self.log, self.ui_call)
        self.da = DonationAlertsClient(self._on_donation, self.log)
        self.dp = DonatePayClient(self._on_donation, self.log)
        self.trula = TrulaClient(self._on_donation, self.log)
        self.webhook = WebhookServer(self._on_donation, self.log)
        self._build_style()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.engine.start()
        self._start_services()
        self.after(1000, self._tick)

    def ui_call(self, fn) -> None:
        self.after(0, fn)

    def log(self, text: str) -> None:
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

    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=FG, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=BG, foreground=ACCENT, font=("Segoe UI Semibold", 18))
        style.configure("Card.TLabel", background=PANEL, foreground=FG, font=("Segoe UI", 10))
        style.configure("CardMuted.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        style.configure(
            "TCheckbutton",
            background=PANEL,
            foreground=FG,
            font=("Segoe UI", 10),
            indicatorcolor=ENTRY_BG,
            indicatorrelief="flat",
        )
        style.map(
            "TCheckbutton",
            background=[("active", CARD)],
            foreground=[("active", ACCENT)],
            indicatorcolor=[("selected", ACCENT_DARK), ("active", HIGHLIGHT)],
        )
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=CARD,
            foreground=MUTED,
            padding=(16, 9),
            font=("Segoe UI", 10),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", ACCENT_DARK), ("active", BUTTON_HOVER)],
            foreground=[("selected", "#f8f4ff"), ("active", FG)],
        )
        style.configure(
            "TButton",
            font=("Segoe UI", 9),
            padding=8,
            background=BUTTON,
            foreground=FG,
            borderwidth=0,
            focusthickness=0,
            relief="flat",
        )
        style.map(
            "TButton",
            background=[("active", BUTTON_HOVER), ("pressed", ACCENT_DARK)],
            foreground=[("active", "#ffffff")],
        )
        style.configure(
            "Accent.TButton",
            font=("Segoe UI Semibold", 10),
            padding=8,
            background=ACCENT_DARK,
            foreground="#f8f4ff",
        )
        style.map("Accent.TButton", background=[("active", HIGHLIGHT), ("pressed", BUTTON)])
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
        self.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

    def _build(self) -> None:
        head = ttk.Frame(self)
        head.pack(fill="x", padx=18, pady=(16, 8))
        ttk.Label(head, text="CS2 Donate Interact", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="  донат-интерактив", style="Muted.TLabel").pack(side="left", pady=(6, 0))
        self.status_da = ttk.Label(head, text="DA: нет", style="Muted.TLabel")
        self.status_dp = ttk.Label(head, text="DP: нет", style="Muted.TLabel")
        self.status_trula = ttk.Label(head, text="Trula: нет", style="Muted.TLabel")
        self.status_cs2 = ttk.Label(head, text="CS2: —", style="Muted.TLabel")
        self.status_sys = ttk.Label(head, text="эффекты: вкл", style="Muted.TLabel")
        self.status_sys.pack(side="right", padx=8)
        self.status_cs2.pack(side="right", padx=8)
        self.status_trula.pack(side="right", padx=8)
        self.status_dp.pack(side="right", padx=8)
        self.status_da.pack(side="right", padx=8)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=18, pady=8)
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

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=18, pady=(0, 14))
        ttk.Button(bar, text="Сохранить настройки", style="Accent.TButton", command=self._save).pack(side="left")
        ttk.Button(bar, text="Аварийный стоп (Alt+5)", command=self.engine.emergency_stop).pack(side="left", padx=8)
        ttk.Button(bar, text="Паника: выключить всё", command=self._panic).pack(side="left")
        ttk.Button(bar, text="Включить эффекты", command=self._resume).pack(side="left", padx=8)
        ttk.Button(bar, text="Скопировать лог", command=self._copy_log).pack(side="right")

    def _card(self, parent: tk.Widget) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Card.TFrame")
        frame.pack(fill="x", pady=6)
        return frame

    def _entry(self, parent: tk.Widget, width: int = 10) -> tk.Entry:
        entry = tk.Entry(
            parent,
            width=width,
            bg=ENTRY_BG,
            fg=FG,
            insertbackground=ACCENT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=HIGHLIGHT,
            highlightcolor=ACCENT,
            exportselection=False,
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
        menu = tk.Menu(self, tearoff=0)
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
        ).pack(anchor="w", pady=(8, 10))
        self.effect_vars: dict[str, dict[str, Any]] = {}
        for effect_id in EFFECT_ORDER:
            effect = self.cfg["effects"][effect_id]
            card = self._card(self.tab_effects)
            inner = ttk.Frame(card, style="Card.TFrame")
            inner.pack(fill="x", padx=12, pady=10)
            enabled = tk.BooleanVar(value=bool(effect.get("enabled", True)))
            ttk.Checkbutton(inner, text=EFFECT_TITLES[effect_id], variable=enabled).pack(side="left")
            ttk.Label(inner, text="сумма", style="CardMuted.TLabel").pack(side="left", padx=(16, 4))
            amount = self._entry(inner, 8)
            amount.insert(0, str(effect.get("amount", 0)))
            amount.pack(side="left")
            ttk.Label(inner, text="кд, сек", style="CardMuted.TLabel").pack(side="left", padx=(12, 4))
            cooldown = self._entry(inner, 6)
            cooldown.insert(0, str(effect.get("cooldown_sec", 0)))
            cooldown.pack(side="left")
            extra: dict[str, tk.Entry] = {}
            if effect_id == "flash":
                ttk.Label(inner, text="длительность", style="CardMuted.TLabel").pack(side="left", padx=(12, 4))
                duration = self._entry(inner, 6)
                duration.insert(0, str(effect.get("duration_sec", 8)))
                duration.pack(side="left")
                extra["duration_sec"] = duration
            if effect_id == "block_wasd":
                ttk.Label(inner, text="длительность", style="CardMuted.TLabel").pack(side="left", padx=(12, 4))
                duration = self._entry(inner, 6)
                duration.insert(0, str(effect.get("duration_sec", 10)))
                duration.pack(side="left")
                extra["duration_sec"] = duration
            ttk.Button(
                inner,
                text="Тест",
                command=lambda eid=effect_id: self.engine.enqueue_effect(eid, reason="тест"),
            ).pack(side="right")
            self.effect_vars[effect_id] = {"enabled": enabled, "amount": amount, "cooldown_sec": cooldown, **extra}

        mine = self.cfg["effects"]["minecraft_takeover"]
        video_card = self._card(self.tab_effects)
        row = ttk.Frame(video_card, style="Card.TFrame")
        row.pack(fill="x", padx=12, pady=10)
        ttk.Label(row, text="Видео для 10000₽", style="Card.TLabel").pack(side="left")
        self.video_path = self._entry(row, 48)
        self.video_path.insert(0, str(mine.get("video_path") or ""))
        self.video_path.pack(side="left", padx=8, fill="x", expand=True)
        ttk.Button(row, text="Файл…", command=self._pick_video).pack(side="left")
        row2 = ttk.Frame(video_card, style="Card.TFrame")
        row2.pack(fill="x", padx=12, pady=(0, 10))
        ttk.Label(row2, text="или YouTube URL (нужен mpv)", style="CardMuted.TLabel").pack(side="left")
        self.youtube_url = self._entry(row2, 48)
        self.youtube_url.insert(0, str(mine.get("youtube_url") or ""))
        self.youtube_url.pack(side="left", padx=8, fill="x", expand=True)

    def _build_general(self) -> None:
        g = self.cfg["general"]
        grid = ttk.Frame(self.tab_general)
        grid.pack(fill="x", pady=12)
        self.enabled_var = tk.BooleanVar(value=bool(g["enabled"]))
        self.require_running = tk.BooleanVar(value=bool(g["require_cs2_running"]))
        self.require_focus = tk.BooleanVar(value=bool(g["require_cs2_focused"]))
        ttk.Checkbutton(grid, text="Эффекты включены", variable=self.enabled_var).grid(row=0, column=0, sticky="w", pady=4)
        ttk.Checkbutton(grid, text="Только если CS2 запущен", variable=self.require_running).grid(row=1, column=0, sticky="w", pady=4)
        ttk.Checkbutton(grid, text="Только если CS2 в фокусе", variable=self.require_focus).grid(row=2, column=0, sticky="w", pady=4)

        ttk.Label(grid, text="Режим суммы").grid(row=0, column=1, sticky="e", padx=8)
        self.amount_mode = ttk.Combobox(grid, values=["exact", "threshold"], state="readonly", width=14)
        self.amount_mode.set(g["amount_mode"])
        self.amount_mode.grid(row=0, column=2, sticky="w")
        ttk.Label(grid, text="exact = только точная сумма, threshold = срабатывает самый дорогой подходящий эффект").grid(
            row=0, column=3, sticky="w", padx=8
        )

        ttk.Label(grid, text="Очередь").grid(row=1, column=1, sticky="e", padx=8)
        self.queue_mode = ttk.Combobox(grid, values=["queue", "skip", "replace"], state="readonly", width=14)
        self.queue_mode.set(g["queue_mode"])
        self.queue_mode.grid(row=1, column=2, sticky="w")
        ttk.Label(grid, text="queue — копить, skip — игнор пока занято, replace — новый вытесняет очередь").grid(
            row=1, column=3, sticky="w", padx=8
        )

        ttk.Label(grid, text="Глобальный кулдаун, сек").grid(row=2, column=1, sticky="e", padx=8)
        self.global_cd = self._entry(grid, 8)
        self.global_cd.insert(0, str(g["global_cooldown_sec"]))
        self.global_cd.grid(row=2, column=2, sticky="w")

        ttk.Label(grid, text="Пауза теста, сек").grid(row=3, column=1, sticky="e", padx=8)
        self.test_delay = self._entry(grid, 8)
        self.test_delay.insert(0, str(g.get("test_delay_sec", 3)))
        self.test_delay.grid(row=3, column=2, sticky="w")
        ttk.Label(grid, text="после «Тест» или фейк-алерта DA успей перейти в CS2").grid(
            row=3, column=3, sticky="w", padx=8
        )

        ttk.Label(grid, text="Макс. очередь").grid(row=4, column=1, sticky="e", padx=8)
        self.max_queue = self._entry(grid, 8)
        self.max_queue.insert(0, str(g["max_queue"]))
        self.max_queue.grid(row=4, column=2, sticky="w")

        ttk.Label(grid, text="Аварийный стоп").grid(row=5, column=1, sticky="e", padx=8)
        self.kill_switch = self._entry(grid, 14)
        self.kill_switch.insert(0, g["kill_switch"])
        self.kill_switch.grid(row=5, column=2, sticky="w")

        ttk.Label(grid, text="Паника").grid(row=6, column=1, sticky="e", padx=8)
        self.panic_hotkey = self._entry(grid, 14)
        self.panic_hotkey.insert(0, g["panic_hotkey"])
        self.panic_hotkey.grid(row=6, column=2, sticky="w")

        ttk.Label(
            self.tab_general,
            text="Alt+5 снимает флешку, возвращает WASD, закрывает летсплей и чистит очередь. Ctrl+Alt+5 полностью глушит эффекты до ручного включения.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=10)

        flash = self.cfg["effects"]["flash"]
        jerk = self.cfg["effects"]["mouse_jerk"]
        nade = self.cfg["effects"]["nade_and_crouch"]
        extra = ttk.Frame(self.tab_general)
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
        lines = [
            "Кнопка «Привязать аккаунт» открывает кабинет площадки. Скопируй токен/ссылку, вернись сюда и подтверди —",
            "приложение само вставит из буфера, сохранит и начнёт слушать донаты. Можно подключить одну площадку или все три.",
            "Тест на вкладке «Эффекты» проверяет только CS2. Живой донат идёт другим путём — без привязки эффекта не будет.",
        ]
        for line in lines:
            ttk.Label(parent, text=line, style="Muted.TLabel").pack(anchor="w", pady=3)
        btns = ttk.Frame(parent)
        btns.pack(anchor="w", pady=12)
        ttk.Button(btns, text="Привязать DonationAlerts", style="Accent.TButton", command=lambda: self._bind_account("da")).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="Привязать DonatePay", style="Accent.TButton", command=lambda: self._bind_account("dp")).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="Привязать Trula", style="Accent.TButton", command=lambda: self._bind_account("trula")).pack(side="left")

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
        ttk.Button(box, text="Привязать аккаунт DonationAlerts", style="Accent.TButton", command=lambda: self._bind_account("da")).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(box, text="Секретный токен или ссылка виджета").grid(row=3, column=0, sticky="e", padx=8, pady=6)
        da_wrap = ttk.Frame(box)
        da_wrap.grid(row=3, column=1, sticky="we", pady=6)
        self.da_widget = self._entry(da_wrap, 64)
        self.da_widget.insert(0, da.get("widget_token", ""))
        self.da_widget.pack(side="left", fill="x", expand=True)
        self._paste_button(da_wrap, self.da_widget).pack(side="left", padx=(8, 0))
        ttk.Button(box, text="Подключить DonationAlerts", command=self._reconnect_da).grid(row=4, column=1, sticky="w", pady=8)

        ttk.Label(box, text="Дополнительно, если виджет не подходит — OAuth API", style="Muted.TLabel").grid(row=5, column=0, columnspan=3, sticky="w", pady=(12, 4))
        ttk.Label(box, text="Access token").grid(row=6, column=0, sticky="e", padx=8, pady=4)
        da_token_wrap = ttk.Frame(box)
        da_token_wrap.grid(row=6, column=1, sticky="we", pady=4)
        self.da_token = self._entry(da_token_wrap, 64)
        self.da_token.insert(0, da.get("access_token", ""))
        self.da_token.pack(side="left", fill="x", expand=True)
        self._paste_button(da_token_wrap, self.da_token).pack(side="left", padx=(8, 0))
        ttk.Label(box, text="Client ID").grid(row=7, column=0, sticky="e", padx=8, pady=4)
        self.da_client = self._entry(box, 32)
        self.da_client.insert(0, da.get("client_id", ""))
        self.da_client.grid(row=7, column=1, sticky="w", pady=4)
        ttk.Label(box, text="Client secret").grid(row=8, column=0, sticky="e", padx=8, pady=4)
        self.da_secret = self._entry(box, 48)
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
        ttk.Button(box, text="Привязать аккаунт DonatePay", style="Accent.TButton", command=lambda: self._bind_account("dp")).grid(row=2, column=1, sticky="w", pady=4)
        self.dp_enabled = tk.BooleanVar(value=bool(dp.get("enabled", True)))
        ttk.Checkbutton(box, text="Слушать DonatePay", variable=self.dp_enabled).grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(box, text="API-ключ").grid(row=4, column=0, sticky="e", padx=8, pady=6)
        dp_wrap = ttk.Frame(box)
        dp_wrap.grid(row=4, column=1, sticky="we", pady=6)
        self.dp_token = self._entry(dp_wrap, 64)
        self.dp_token.insert(0, dp.get("api_token", ""))
        self.dp_token.pack(side="left", fill="x", expand=True)
        self._paste_button(dp_wrap, self.dp_token).pack(side="left", padx=(8, 0))
        ttk.Label(box, text="Ссылка виджета оповещений").grid(row=5, column=0, sticky="e", padx=8, pady=6)
        dp_w_wrap = ttk.Frame(box)
        dp_w_wrap.grid(row=5, column=1, sticky="we", pady=6)
        self.dp_widget = self._entry(dp_w_wrap, 64)
        self.dp_widget.insert(0, dp.get("widget_token", ""))
        self.dp_widget.pack(side="left", fill="x", expand=True)
        self._paste_button(dp_w_wrap, self.dp_widget).pack(side="left", padx=(8, 0))
        ttk.Label(box, text="Интервал опроса API, сек").grid(row=6, column=0, sticky="e", padx=8, pady=4)
        self.dp_interval = self._entry(box, 8)
        self.dp_interval.insert(0, str(dp.get("poll_interval_sec", 8)))
        self.dp_interval.grid(row=6, column=1, sticky="w", pady=4)
        ttk.Button(box, text="Подключить DonatePay", command=self._reconnect_dp).grid(row=7, column=1, sticky="w", pady=8)
        ttk.Label(box, text="Виджет: donatepay.ru/donation/notifications → скопируй ссылку widget.donatepay.ru/alert-box/widget/…", style="Muted.TLabel").grid(row=8, column=0, columnspan=3, sticky="w", pady=8)
        box.columnconfigure(1, weight=1)

    def _build_trula_fields(self, parent: tk.Widget) -> None:
        trula = self.cfg["trula"]
        box = ttk.Frame(parent)
        box.pack(fill="x", pady=8)
        ttk.Label(box, text="Нужна ссылка виджета алертов, которую вставляют в OBS как Browser Source.").grid(row=0, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Label(box, text="Не страница доната /dp/..., а именно overlay/alerts виджет. «Привязать аккаунт» откроет кабинет.", style="Muted.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))
        ttk.Button(box, text="Привязать аккаунт Trula", style="Accent.TButton", command=lambda: self._bind_account("trula")).grid(row=2, column=1, sticky="w", pady=4)
        self.trula_enabled = tk.BooleanVar(value=bool(trula.get("enabled", True)))
        ttk.Checkbutton(box, text="Слушать Trula", variable=self.trula_enabled).grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(box, text="Ссылка виджета или токен").grid(row=4, column=0, sticky="e", padx=8, pady=6)
        trula_wrap = ttk.Frame(box)
        trula_wrap.grid(row=4, column=1, sticky="we", pady=6)
        self.trula_widget = self._entry(trula_wrap, 64)
        self.trula_widget.insert(0, trula.get("widget_url", ""))
        self.trula_widget.pack(side="left", fill="x", expand=True)
        self._paste_button(trula_wrap, self.trula_widget).pack(side="left", padx=(8, 0))
        ttk.Button(box, text="Подключить Trula", command=self._reconnect_trula).grid(row=5, column=1, sticky="w", pady=8)
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
            fg="#e4d7f5",
            insertbackground=ACCENT,
            relief="flat",
            state="disabled",
            font=("Consolas", 10),
            highlightthickness=1,
            highlightbackground=HIGHLIGHT,
            selectbackground=ACCENT_DARK,
            selectforeground="#ffffff",
        )
        self.log_box.pack(fill="both", expand=True, pady=8)
        self.log("Приложение запущено. Дроп/мышь/граната работают только если CS2 в фокусе.")
        self.log("Для клавиш в CS2 запусти run-admin.bat. Игра — «Во весь экран в окне».")
        self.log(f"Файл лога: {LOG_PATH}")

    def _collect(self) -> None:
        self.cfg["general"]["enabled"] = self.enabled_var.get()
        self.cfg["general"]["require_cs2_running"] = self.require_running.get()
        self.cfg["general"]["require_cs2_focused"] = self.require_focus.get()
        self.cfg["general"]["amount_mode"] = self.amount_mode.get()
        self.cfg["general"]["queue_mode"] = self.queue_mode.get()
        self.cfg["general"]["global_cooldown_sec"] = float(self.global_cd.get() or 0)
        self.cfg["general"]["test_delay_sec"] = float(self.test_delay.get() or 0)
        self.cfg["general"]["max_queue"] = int(self.max_queue.get() or 5)
        self.cfg["general"]["kill_switch"] = self.kill_switch.get().strip() or "alt+5"
        self.cfg["general"]["panic_hotkey"] = self.panic_hotkey.get().strip() or "ctrl+alt+5"
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

    def _bind_account(self, kind: str) -> None:
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
        titles = {
            "da": "DonationAlerts",
            "dp": "DonatePay",
            "trula": "Trula",
        }
        hints = {
            "da": (
                "В браузере откроется кабинет DonationAlerts.\n\n"
                "1. Войди в аккаунт, куда кидают донаты.\n"
                "2. Скопируй «Секретный токен» или ссылку виджета с token=.\n"
                "3. Нажми OK — приложение вставит токен из буфера и начнёт слушать донаты.\n\n"
                "Проверка: в кабинете DA отправь тестовый алерт на 100₽."
            ),
            "dp": (
                "Откроются две страницы DonatePay.\n\n"
                "1. Со страницы оповещений скопируй ссылку виджета "
                "(widget.donatepay.ru/alert-box/widget/…).\n"
                "2. Со страницы API скопируй ключ.\n"
                "3. Нажми OK — сначала вставится то, что сейчас в буфере.\n"
                "   Если это ссылка виджета, она попадёт в поле виджета; если ключ — в API.\n"
                "4. Скопируй второй кусок и нажми «Подключить DonatePay».\n\n"
                "Виджет даёт донат сразу, API — подстраховка."
            ),
            "trula": (
                "Откроется кабинет Trula.\n\n"
                "1. Войди аккаунтом стримера.\n"
                "2. Виджеты → алерты/оповещения.\n"
                "3. Скопируй ссылку, которую вставляют в OBS (Browser Source).\n"
                "4. Нажми OK — приложение вставит ссылку и начнёт слушать.\n\n"
                "Не копируй страницу доната /dp/..."
            ),
        }
        for url in pages[kind]:
            self._open(url)
        if not messagebox.askokcancel(titles[kind], hints[kind]):
            return
        text = ""
        try:
            text = (self.clipboard_get() or "").strip().replace("\r", "").replace("\n", "")
        except tk.TclError:
            text = ""
        if not text:
            messagebox.showinfo(titles[kind], "В буфере пусто. Скопируй токен ещё раз и нажми «Подключить».")
            return
        low = text.lower()
        if kind == "da":
            self.da_widget.delete(0, "end")
            self.da_widget.insert(0, text)
            self._save()
            self._reconnect_da()
        elif kind == "dp":
            if "widget.donatepay" in low or "alert-box" in low:
                self.dp_widget.delete(0, "end")
                self.dp_widget.insert(0, text)
            else:
                self.dp_token.delete(0, "end")
                self.dp_token.insert(0, text)
            self.dp_enabled.set(True)
            self._save()
            self._reconnect_dp()
        else:
            self.trula_widget.delete(0, "end")
            self.trula_widget.insert(0, text)
            self.trula_enabled.set(True)
            self._save()
            self._reconnect_trula()
        self.log(f"{titles[kind]}: аккаунт привязан, жду донаты. В логе должно появиться «подключен» / «слушатели запущены».")

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
            self.log("DonationAlerts не привязан. Вкладка Донаты → Привязать аккаунт.")
        dp = self.cfg["donatepay"]
        if dp.get("enabled") and (dp.get("api_token") or dp.get("widget_token")):
            self.dp.start(
                dp.get("api_token", ""),
                float(dp.get("poll_interval_sec") or 8),
                str(self.cfg["general"].get("currency") or "RUB"),
                dp.get("widget_token", ""),
            )
        elif dp.get("enabled"):
            self.log("DonatePay не привязан. Вкладка Донаты → Привязать аккаунт.")
        if self.cfg["trula"].get("enabled") and self.cfg["trula"].get("widget_url"):
            self.trula.start(self.cfg["trula"]["widget_url"])
        elif self.cfg["trula"].get("enabled"):
            self.log("Trula не привязана. Вкладка Донаты → Привязать аккаунт.")
        if self.cfg["webhook"].get("enabled"):
            self.webhook.start(self.cfg["webhook"]["host"], int(self.cfg["webhook"]["port"]))

    def _on_donation(self, donation: Donation) -> None:
        kind = "тест-алерт" if donation.is_test else "донат"
        self.log(
            f"{kind}: {donation.username} — {donation.amount:g} {donation.currency} "
            f"id={donation.donation_id or '-'} source={donation.source} msg={donation.message!r}"
        )
        self.engine.enqueue_donation(donation)

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

    def _tick(self) -> None:
        running = is_cs2_running(self.cfg["cs2"]["process_name"])
        self.status_cs2.configure(text="CS2: запущена" if running else "CS2: нет")
        token = self.da_token.get().strip() if hasattr(self, "da_token") else ""
        widget = self.da_widget.get().strip() if hasattr(self, "da_widget") else ""
        dp_token = self.dp_token.get().strip() if hasattr(self, "dp_token") else ""
        dp_widget = self.dp_widget.get().strip() if hasattr(self, "dp_widget") else ""
        dp_on = self.dp_enabled.get() if hasattr(self, "dp_enabled") else False
        trula_url = self.trula_widget.get().strip() if hasattr(self, "trula_widget") else ""
        trula_on = self.trula_enabled.get() if hasattr(self, "trula_enabled") else False
        if self.da.connected:
            self.status_da.configure(text="DA: слушаю")
        elif token or widget:
            self.status_da.configure(text="DA: токен есть")
        else:
            self.status_da.configure(text="DA: нет токена")
        if not dp_on:
            self.status_dp.configure(text="DP: выкл")
        elif self.dp.connected:
            self.status_dp.configure(text="DP: слушаю")
        elif dp_token or dp_widget:
            self.status_dp.configure(text="DP: токен есть")
        else:
            self.status_dp.configure(text="DP: нет токена")
        if not trula_on:
            self.status_trula.configure(text="Trula: выкл")
        elif self.trula.connected:
            self.status_trula.configure(text="Trula: слушаю")
        elif trula_url:
            self.status_trula.configure(text="Trula: ссылка есть")
        else:
            self.status_trula.configure(text="Trula: нет ссылки")
        if self.engine.paused or not self.cfg["general"]["enabled"]:
            self.status_sys.configure(text="эффекты: выкл")
        elif self.engine.busy:
            self.status_sys.configure(text=f"эффект: {EFFECT_TITLES.get(self.engine.current_effect, '…')}")
        else:
            self.status_sys.configure(text="эффекты: вкл")
        self.after(1000, self._tick)

    def _on_close(self) -> None:
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
