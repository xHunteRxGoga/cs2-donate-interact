from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from src.config import EFFECT_ORDER, EFFECT_TITLES, get_effect, resolve_video_path
from src.donations.models import Donation
from src.effects.cs2 import (
    drop_weapon,
    is_cs2_focused,
    is_cs2_running,
    kill_cs2,
    mouse_jerk,
    nade_and_crouch,
)
from src.effects.flash import FlashController
from src.effects.input_win import InputGuard
from src.effects.takeover import TakeoverController


@dataclass(slots=True)
class Job:
    effect_id: str
    donation: Donation | None
    reason: str


class EffectEngine:
    def __init__(self, get_config: Callable[[], dict[str, Any]], log: Callable[[str], None], ui_call: Callable[..., None]) -> None:
        self.get_config = get_config
        self.log = log
        self.ui_call = ui_call
        self.guard = InputGuard()
        self.flash = FlashController(ui_call)
        self.takeover = TakeoverController(self.guard)
        self.paused = False
        self.busy = False
        self.current_effect = ""
        self._queue: queue.Queue[Job] = queue.Queue()
        self._cooldowns: dict[str, float] = {}
        self._global_ready_at = 0.0
        self._stop = False
        self._worker = threading.Thread(target=self._loop, name="effects", daemon=True)
        self.guard.on_kill = self.emergency_stop
        self.guard.on_panic = self.panic

    def start(self) -> None:
        cfg = self.get_config()
        self.guard.kill_switch = cfg["general"]["kill_switch"]
        self.guard.panic_hotkey = cfg["general"]["panic_hotkey"]
        self.guard.start()
        self._worker.start()

    def shutdown(self) -> None:
        self._stop = True
        self.emergency_stop()
        self.guard.stop()

    def panic(self) -> None:
        self.paused = True
        self.emergency_stop()
        self.log("Паника: все эффекты выключены. Включи обратно в приложении.")

    def emergency_stop(self) -> None:
        self._clear_queue()
        self.flash.cancel()
        self.takeover.cancel()
        self.guard.clear_blocked_keys()
        self.guard.set_block_all(False)
        self.busy = False
        self.current_effect = ""
        self.log("Аварийный стоп: эффекты сброшены.")

    def enqueue_donation(self, donation: Donation) -> None:
        cfg = self.get_config()
        if not cfg["general"]["enabled"] or self.paused:
            self.log(f"Донат {donation.amount:g} {donation.currency} от {donation.username} пропущен: система выключена")
            return
        effect_id = self._match_effect(cfg, donation)
        if not effect_id:
            self.log(f"Донат {donation.amount:g} {donation.currency} от {donation.username}: нет подходящего эффекта")
            return
        self.enqueue_effect(effect_id, donation, f"донат {donation.amount:g} {donation.currency}")

    def enqueue_effect(self, effect_id: str, donation: Donation | None = None, reason: str = "тест") -> None:
        cfg = self.get_config()
        if self.paused and reason != "тест":
            return
        mode = cfg["general"]["queue_mode"]
        if mode == "skip" and (self.busy or not self._queue.empty()):
            self.log(f"{EFFECT_TITLES[effect_id]} пропущен: уже идёт другой эффект")
            return
        if mode == "replace":
            self._clear_queue()
        if self._queue.qsize() >= int(cfg["general"]["max_queue"]):
            self.log(f"{EFFECT_TITLES[effect_id]} пропущен: очередь полная")
            return
        self._queue.put(Job(effect_id, donation, reason))
        who = f" от {donation.username}" if donation else ""
        self.log(f"В очередь: {EFFECT_TITLES[effect_id]} ({reason}{who})")

    def _match_effect(self, cfg: dict[str, Any], donation: Donation) -> str | None:
        wanted = str(cfg["general"].get("currency") or "").upper()
        if wanted and donation.currency.upper() != wanted:
            return None
        mode = cfg["general"]["amount_mode"]
        matches: list[tuple[float, str]] = []
        for effect_id in EFFECT_ORDER:
            effect = get_effect(cfg, effect_id)
            if not effect.get("enabled"):
                continue
            amount = float(effect["amount"])
            if mode == "exact" and abs(donation.amount - amount) < 0.009:
                matches.append((amount, effect_id))
            elif mode == "threshold" and donation.amount + 1e-9 >= amount:
                matches.append((amount, effect_id))
        if not matches:
            return None
        matches.sort(key=lambda item: item[0], reverse=True)
        return matches[0][1]

    def _loop(self) -> None:
        while not self._stop:
            try:
                job = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._run_job(job)
            except Exception as exc:
                self.log(f"Ошибка эффекта {job.effect_id}: {exc}")
                self.emergency_stop()
            finally:
                self.busy = False
                self.current_effect = ""

    def _run_job(self, job: Job) -> None:
        cfg = self.get_config()
        self.guard.kill_switch = cfg["general"]["kill_switch"]
        self.guard.panic_hotkey = cfg["general"]["panic_hotkey"]
        effect = get_effect(cfg, job.effect_id)
        now = time.time()
        if now < self._global_ready_at:
            wait = self._global_ready_at - now
            self.log(f"{EFFECT_TITLES[job.effect_id]} ждёт глобальный кулдаун {wait:.1f}с")
            return
        ready_at = self._cooldowns.get(job.effect_id, 0)
        if now < ready_at:
            self.log(f"{EFFECT_TITLES[job.effect_id]} на кулдауне ещё {ready_at - now:.1f}с")
            return
        if job.effect_id != "minecraft_takeover":
            if cfg["general"]["require_cs2_running"] and not is_cs2_running(cfg["cs2"]["process_name"]):
                self.log("CS2 не запущен — эффект пропущен")
                return
            if cfg["general"]["require_cs2_focused"] and not is_cs2_focused(cfg["cs2"]["window_title"]):
                self.log("CS2 не в фокусе — эффект пропущен")
                return

        self.busy = True
        self.current_effect = job.effect_id
        self.log(f"Старт: {EFFECT_TITLES[job.effect_id]}")
        self._dispatch(job.effect_id, cfg)
        self._cooldowns[job.effect_id] = time.time() + float(effect.get("cooldown_sec") or 0)
        self._global_ready_at = time.time() + float(cfg["general"].get("global_cooldown_sec") or 0)
        self.log(f"Готово: {EFFECT_TITLES[job.effect_id]}")

    def _dispatch(self, effect_id: str, cfg: dict[str, Any]) -> None:
        if effect_id == "flash":
            effect = cfg["effects"]["flash"]
            self.flash.run(
                float(effect.get("duration_sec", 8)),
                str(effect.get("mode", "gamma_and_overlay")),
                float(effect.get("fade_out_sec", 1.5)),
            )
        elif effect_id == "drop_weapon":
            drop_weapon(cfg)
        elif effect_id == "mouse_jerk":
            mouse_jerk(cfg)
        elif effect_id == "block_wasd":
            keys = cfg["cs2"]["keys"]
            self.guard.set_blocked_keys([keys["forward"], keys["back"], keys["left"], keys["right"]])
            time.sleep(float(cfg["effects"]["block_wasd"].get("duration_sec", 10)))
            self.guard.clear_blocked_keys()
        elif effect_id == "nade_and_crouch":
            nade_and_crouch(cfg)
        elif effect_id == "kill_cs2":
            kill_cs2(cfg["cs2"]["process_name"])
        elif effect_id == "minecraft_takeover":
            self.takeover.run(
                resolve_video_path(cfg),
                str(cfg["effects"]["minecraft_takeover"].get("youtube_url") or ""),
                cfg["cs2"]["process_name"],
                bool(cfg["effects"]["minecraft_takeover"].get("block_input", True)),
            )

    def _clear_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def cooldown_left(self, effect_id: str) -> float:
        return max(0.0, self._cooldowns.get(effect_id, 0) - time.time())
