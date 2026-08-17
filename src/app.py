from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from src.config import EFFECT_ORDER, EFFECT_TITLES, load_config, save_config
from src.donations.donationalerts import DonationAlertsClient, oauth_login
from src.donations.models import Donation
from src.donations.webhook import WebhookServer
from src.effects.cs2 import is_cs2_running
from src.effects.engine import EffectEngine


BG = "#101218"
PANEL = "#171b24"
CARD = "#1e2430"
FG = "#e8eaed"
MUTED = "#8b93a7"
ACCENT = "#f0b429"
OK = "#3dd68c"
BAD = "#ff6b6b"
ENTRY_BG = "#0c0f14"


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
        def append() -> None:
            self.log_box.configure(state="normal")
            self.log_box.insert("end", text + "\n")
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
        style.configure("Title.TLabel", background=BG, foreground=FG, font=("Segoe UI Semibold", 16))
        style.configure("Card.TLabel", background=PANEL, foreground=FG, font=("Segoe UI", 10))
        style.configure("CardMuted.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("TCheckbutton", background=PANEL, foreground=FG, font=("Segoe UI", 10))
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=CARD, foreground=FG, padding=(14, 8), font=("Segoe UI", 10))
        style.map("TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", "#1a1203")])
        style.configure("Accent.TButton", font=("Segoe UI Semibold", 10), padding=8)
        style.configure("TButton", font=("Segoe UI", 9), padding=6)
        style.configure("TEntry", fieldbackground=ENTRY_BG, foreground=FG)
        style.configure("TCombobox", fieldbackground=ENTRY_BG, foreground=FG)

    def _build(self) -> None:
        head = ttk.Frame(self)
        head.pack(fill="x", padx=18, pady=(16, 8))
        ttk.Label(head, text="CS2 Donate Interact", style="Title.TLabel").pack(side="left")
        self.status_da = ttk.Label(head, text="DA: нет", style="Muted.TLabel")
        self.status_cs2 = ttk.Label(head, text="CS2: —", style="Muted.TLabel")
        self.status_sys = ttk.Label(head, text="эффекты: вкл", style="Muted.TLabel")
        self.status_sys.pack(side="right", padx=8)
        self.status_cs2.pack(side="right", padx=8)
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
        nb.add(self.tab_da, text="DonationAlerts")
        nb.add(self.tab_keys, text="Клавиши CS2")
        nb.add(self.tab_log, text="Лог")
        self._build_effects()
        self._build_general()
        self._build_da()
        self._build_keys()
        self._build_log()

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=18, pady=(0, 14))
        ttk.Button(bar, text="Сохранить настройки", command=self._save).pack(side="left")
        ttk.Button(bar, text="Аварийный стоп (Alt+5)", command=self.engine.emergency_stop).pack(side="left", padx=8)
        ttk.Button(bar, text="Паника: выключить всё", command=self._panic).pack(side="left")
        ttk.Button(bar, text="Включить эффекты", command=self._resume).pack(side="left", padx=8)

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
            insertbackground=FG,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#2a3140",
        )
        return entry

    def _build_effects(self) -> None:
        ttk.Label(
            self.tab_effects,
            text="Сумма доната запускает один эффект. Кнопка «Тест» срабатывает сразу, без DonationAlerts.",
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

        ttk.Label(grid, text="Макс. очередь").grid(row=3, column=1, sticky="e", padx=8)
        self.max_queue = self._entry(grid, 8)
        self.max_queue.insert(0, str(g["max_queue"]))
        self.max_queue.grid(row=3, column=2, sticky="w")

        ttk.Label(grid, text="Аварийный стоп").grid(row=4, column=1, sticky="e", padx=8)
        self.kill_switch = self._entry(grid, 14)
        self.kill_switch.insert(0, g["kill_switch"])
        self.kill_switch.grid(row=4, column=2, sticky="w")

        ttk.Label(grid, text="Паника").grid(row=5, column=1, sticky="e", padx=8)
        self.panic_hotkey = self._entry(grid, 14)
        self.panic_hotkey.insert(0, g["panic_hotkey"])
        self.panic_hotkey.grid(row=5, column=2, sticky="w")

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

    def _build_da(self) -> None:
        da = self.cfg["donationalerts"]
        box = ttk.Frame(self.tab_da)
        box.pack(fill="x", pady=12)
        ttk.Label(
            box,
            text="Стример создаёт приложение на donationalerts.com/application/clients и вставляет данные сюда. Токен в git не попадает.",
            style="Muted.TLabel",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        ttk.Label(box, text="Access token").grid(row=1, column=0, sticky="e", padx=8, pady=4)
        self.da_token = self._entry(box, 64)
        self.da_token.insert(0, da.get("access_token", ""))
        self.da_token.grid(row=1, column=1, sticky="we", pady=4)

        ttk.Label(box, text="Client ID").grid(row=2, column=0, sticky="e", padx=8, pady=4)
        self.da_client = self._entry(box, 32)
        self.da_client.insert(0, da.get("client_id", ""))
        self.da_client.grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(box, text="Client secret").grid(row=3, column=0, sticky="e", padx=8, pady=4)
        self.da_secret = self._entry(box, 48)
        self.da_secret.insert(0, da.get("client_secret", ""))
        self.da_secret.grid(row=3, column=1, sticky="we", pady=4)

        ttk.Label(box, text="Режим").grid(row=4, column=0, sticky="e", padx=8, pady=4)
        self.da_mode = ttk.Combobox(box, values=["websocket", "poll"], state="readonly", width=16)
        self.da_mode.set(da.get("mode", "websocket"))
        self.da_mode.grid(row=4, column=1, sticky="w")

        ttk.Button(box, text="Войти через DonationAlerts", command=self._oauth).grid(row=5, column=1, sticky="w", pady=10)
        ttk.Button(box, text="Подключить заново", command=self._reconnect_da).grid(row=5, column=1, sticky="e", pady=10)

        ttk.Label(
            box,
            text="Без OAuth можно вставить готовый access_token. Для тестов без доната: кнопки «Тест» или GET http://127.0.0.1:8765/donate?amount=100",
            style="Muted.TLabel",
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=8)
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
        ttk.Label(box, text="Заголовок окна CS2").grid(row=10, column=0, sticky="e", padx=8, pady=10)
        self.window_title = self._entry(box, 28)
        self.window_title.insert(0, self.cfg["cs2"]["window_title"])
        self.window_title.grid(row=10, column=1, sticky="w", pady=10)

    def _build_log(self) -> None:
        self.log_box = tk.Text(
            self.tab_log,
            bg=ENTRY_BG,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            state="disabled",
            font=("Consolas", 10),
        )
        self.log_box.pack(fill="both", expand=True, pady=8)
        self.log("Приложение запущено. Сначала нажми «Тест» на флешке — так проще проверить, что оверлей виден поверх CS2.")
        self.log("Для CS2 лучше режим отображения «Во весь экран в окне», иначе белый оверлей может быть под игрой.")

    def _collect(self) -> None:
        self.cfg["general"]["enabled"] = self.enabled_var.get()
        self.cfg["general"]["require_cs2_running"] = self.require_running.get()
        self.cfg["general"]["require_cs2_focused"] = self.require_focus.get()
        self.cfg["general"]["amount_mode"] = self.amount_mode.get()
        self.cfg["general"]["queue_mode"] = self.queue_mode.get()
        self.cfg["general"]["global_cooldown_sec"] = float(self.global_cd.get() or 0)
        self.cfg["general"]["max_queue"] = int(self.max_queue.get() or 5)
        self.cfg["general"]["kill_switch"] = self.kill_switch.get().strip() or "alt+5"
        self.cfg["general"]["panic_hotkey"] = self.panic_hotkey.get().strip() or "ctrl+alt+5"
        self.cfg["effects"]["flash"]["mode"] = self.flash_mode.get()
        self.cfg["effects"]["mouse_jerk"]["intensity"] = int(self.jerk_intensity.get() or 900)
        self.cfg["effects"]["nade_and_crouch"]["look_down_pixels"] = int(self.look_down.get() or 3200)
        self.cfg["effects"]["minecraft_takeover"]["video_path"] = self.video_path.get().strip()
        self.cfg["effects"]["minecraft_takeover"]["youtube_url"] = self.youtube_url.get().strip()
        self.cfg["donationalerts"]["access_token"] = self.da_token.get().strip()
        self.cfg["donationalerts"]["client_id"] = self.da_client.get().strip()
        self.cfg["donationalerts"]["client_secret"] = self.da_secret.get().strip()
        self.cfg["donationalerts"]["mode"] = self.da_mode.get()
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

    def _reconnect_da(self) -> None:
        self._collect()
        self.da.start(self.cfg["donationalerts"]["access_token"], self.cfg["donationalerts"]["mode"])

    def _start_services(self) -> None:
        if self.cfg["donationalerts"].get("access_token"):
            self.da.start(self.cfg["donationalerts"]["access_token"], self.cfg["donationalerts"]["mode"])
        if self.cfg["webhook"].get("enabled"):
            self.webhook.start(self.cfg["webhook"]["host"], int(self.cfg["webhook"]["port"]))

    def _on_donation(self, donation: Donation) -> None:
        self.log(f"Донат: {donation.username} — {donation.amount:g} {donation.currency} ({donation.source})")
        self.engine.enqueue_donation(donation)

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
        self.status_da.configure(text="DA: токен есть" if token else "DA: нет токена")
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
        self.webhook.stop()
        self.destroy()


def run() -> None:
    app = App()
    app.mainloop()
