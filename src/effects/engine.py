from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

try:
    import winsound
except ImportError:
    winsound = None  # type: ignore

from src.config import EFFECT_ORDER, EFFECT_TITLES, get_effect, resolve_video_path
from src.donations.models import Donation
from src.effects.cs2 import (
    diagnose_cs2,
    drop_weapon,
    is_cs2_focused,
    is_cs2_running,
    kill_cs2,
    mouse_jerk,
    nade_and_crouch,
)
from src.effects.flash import FlashController
from src.effects.input_win import InputGuard, foreground_title, is_admin, set_input_logger
from src.effects.takeover import TakeoverController
from src.effects.toast import ToastController


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
        self.toast = ToastController(ui_call)
        self.takeover = TakeoverController(self.guard)
        self.paused = False
        self.busy = False
        self.current_effect = ""
        self._queue: queue.Queue[Job] = queue.Queue()
        self._cooldowns: dict[str, float] = {}
        self._global_ready_at = 0.0
        self._stop = False
        self._generation = 0
        self._worker = threading.Thread(target=self._loop, name="effects", daemon=True)
        self.guard.on_kill = self.emergency_stop
        self.guard.on_panic = self.panic

    def start(self) -> None:
        cfg = self.get_config()
        self.guard.kill_switch = cfg["general"]["kill_switch"]
        self.guard.panic_hotkey = cfg["general"]["panic_hotkey"]
        set_input_logger(self.log)
        self.guard.start()
        self._worker.start()
        self.log(f"Диагностика при старте: {diagnose_cs2(cfg, self.guard.hook_ok())}")
        if not is_admin():
            self.log("ВАЖНО: приложение без прав администратора. CS2 часто игнорирует G/мышь. Закрой и запусти run-admin.bat.")

    def shutdown(self) -> None:
        self._stop = True
        self.emergency_stop()
        self.guard.stop()

    def panic(self) -> None:
        self.paused = True
        self.emergency_stop()
        self.log("Паника: все эффекты выключены. Включи обратно в приложении.")

    def emergency_stop(self) -> None:
        self._generation += 1
        self._clear_queue()
        self.flash.cancel()
        self.takeover.cancel()
        self.toast.cancel()
        self.guard.clear_blocked_keys()
        self.guard.set_block_all(False)
        self.busy = False
        self.current_effect = ""
        self.log("Аварийный стоп: эффекты сброшены.")

    def announce_donation(self, donation: Donation, effect_id: str | None) -> None:
        cfg = self.get_config()
        overlay = cfg.get("overlay") or {}
        title = EFFECT_TITLES.get(effect_id or "", "") or "Донат получен"
        if not effect_id:
            title = "Донат получен — сумма не совпала с эффектом"
        amount = f"{donation.amount:g} {donation.currency}"
        self.log(
            f"приложение увидело донат: {donation.username} — {amount} "
            f"[{donation.source}] id={donation.donation_id or '-'} → {title}"
        )
        if overlay.get("enabled", True):
            self.toast.show(
                donation.username,
                title,
                amount,
                float(overlay.get("duration_sec") or 5.5),
                wait=False,
            )
        if overlay.get("beep", True):
            threading.Thread(target=self._beep, daemon=True).start()
        if overlay.get("ping_flash", True) and effect_id != "flash":
            threading.Thread(target=lambda: self.flash.ping(0.45), daemon=True).start()

    def _beep(self) -> None:
        try:
            if winsound:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass

    def enqueue_donation(self, donation: Donation) -> None:
        cfg = self.get_config()
        effect_id = self._match_effect(cfg, donation)
        self.announce_donation(donation, effect_id)
        if not cfg["general"]["enabled"] or self.paused:
            self.log("эффект не запущен: система выключена или паника. Табличка уже должна быть на экране.")
            return
        if not effect_id:
            return
        reason = "тест" if donation.is_test else f"донат {donation.amount:g} {donation.currency}"
        self.enqueue_effect(effect_id, donation, reason)

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
        delay = float(cfg["general"].get("test_delay_sec") or 0) if reason == "тест" else 0
        if delay > 0:
            self.log(
                f"Тест «{EFFECT_TITLES[effect_id]}»: сейчас переключись в CS2. "
                f"Сработает через {delay:.0f} сек."
            )
        else:
            self.log(f"В очередь: {EFFECT_TITLES[effect_id]} ({reason}{who})")

    def _match_effect(self, cfg: dict[str, Any], donation: Donation) -> str | None:
        wanted = str(cfg["general"].get("currency") or "").upper().replace("RUR", "RUB")
        got = (donation.currency or "RUB").upper().replace("RUR", "RUB")
        if got in {"", "₽", "РУБ"}:
            got = "RUB"
        if wanted and got and wanted != got:
            self.log(f"Донат пропущен: валюта {donation.currency}, в настройках {wanted}")
            return None
        mode = cfg["general"]["amount_mode"]
        tolerance = float(cfg["general"].get("amount_tolerance_rub") or 0)
        matches: list[tuple[float, str]] = []
        for effect_id in EFFECT_ORDER:
            effect = get_effect(cfg, effect_id)
            if not effect.get("enabled"):
                continue
            amount = float(effect["amount"])
            if mode == "exact" and _amount_close(donation.amount, amount, tolerance):
                matches.append((amount, effect_id))
            elif mode == "threshold" and donation.amount + 1e-9 >= amount:
                matches.append((amount, effect_id))
        if not matches:
            amounts = [
                f"{float(get_effect(cfg, eid)['amount']):g}"
                for eid in EFFECT_ORDER
                if get_effect(cfg, eid).get("enabled")
            ]
            self.log(
                f"Донат {donation.amount:g} {donation.currency} от {donation.username}: "
                f"нет эффекта на эту сумму (сейчас {', '.join(amounts) or 'нет включённых'})"
            )
            return None
        if mode == "exact":
            matches.sort(key=lambda item: (abs(donation.amount - item[0]), item[0]))
        else:
            matches.sort(key=lambda item: item[0], reverse=True)
        picked = matches[0]
        if len(matches) > 1:
            others = ", ".join(f"{amt:g}={EFFECT_TITLES[eid]}" for amt, eid in matches[1:])
            self.log(
                f"сумма {donation.amount:g}: беру ближайшее {picked[0]:g} ({EFFECT_TITLES[picked[1]]}), "
                f"ещё подходило: {others}"
            )
        return picked[1]

    def _loop(self) -> None:
        while not self._stop:
            try:
                job = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._run_job(job)
            except Exception as exc:
                self.log(f"Ошибка эффекта {job.effect_id}: {type(exc).__name__}: {exc}")
                self.log(f"Диагностика после ошибки: {diagnose_cs2(self.get_config(), self.guard.hook_ok())}")
                self.flash.cancel()
                self.toast.cancel()
                self.guard.clear_blocked_keys()
                self.guard.set_block_all(False)
                self.log("Эффект оборван, остальные тесты можно жать сразу. Аварийный стоп не нужен.")
            finally:
                self.busy = False
                self.current_effect = ""

    def _wait_interruptible(self, seconds: float, generation: int) -> bool:
        deadline = time.time() + max(0.0, seconds)
        while time.time() < deadline:
            if self._stop or self._generation != generation:
                return False
            remaining = deadline - time.time()
            time.sleep(min(0.1, remaining))
        return not (self._stop or self._generation != generation)

    def _run_job(self, job: Job) -> None:
        cfg = self.get_config()
        self.guard.kill_switch = cfg["general"]["kill_switch"]
        self.guard.panic_hotkey = cfg["general"]["panic_hotkey"]
        effect = get_effect(cfg, job.effect_id)
        is_test = job.reason == "тест"
        generation = self._generation
        now = time.time()
        if not is_test and now < self._global_ready_at:
            wait = self._global_ready_at - now
            self.log(f"{EFFECT_TITLES[job.effect_id]} ждёт глобальный кулдаун {wait:.1f}с")
            return
        ready_at = self._cooldowns.get(job.effect_id, 0)
        if not is_test and now < ready_at:
            self.log(f"{EFFECT_TITLES[job.effect_id]} на кулдауне ещё {ready_at - now:.1f}с")
            return

        needs_game = job.effect_id not in {"flash", "kill_cs2", "minecraft_takeover"}
        delay = float(cfg["general"].get("test_delay_sec") or 0) if is_test else 0
        if delay <= 0 and needs_game and not is_cs2_focused(cfg["cs2"]["window_title"]):
            delay = float(cfg["general"].get("test_delay_sec") or 0)
            if delay > 0:
                self.log(
                    f"{EFFECT_TITLES[job.effect_id]}: CS2 не в фокусе. "
                    f"Переключись в игру, старт через {delay:.0f} сек."
                )
        if delay > 0:
            self.busy = True
            self.current_effect = job.effect_id
            whole = int(delay)
            for left in range(whole, 0, -1):
                self.log(f"Переключись в CS2, старт через {left}...")
                if not self._wait_interruptible(1.0, generation):
                    self.log("Эффект отменён")
                    return
            leftover = delay - whole
            if leftover > 0 and not self._wait_interruptible(leftover, generation):
                self.log("Эффект отменён")
                return
            if self._stop or self._generation != generation:
                self.log("Эффект отменён")
                return

        self.busy = True
        self.current_effect = job.effect_id
        overlay_cfg = cfg.get("overlay") or {}
        if overlay_cfg.get("enabled", True) and (is_test or not job.donation):
            who = job.donation.username if job.donation else "Тест"
            amount = ""
            if job.donation:
                amount = f"{job.donation.amount:g} {job.donation.currency}"
            else:
                amount = "тест"
            self.toast.show(who, EFFECT_TITLES[job.effect_id], amount, float(overlay_cfg.get("duration_sec") or 5.5), wait=False)
            self.log(f"оверлей: {who} → {EFFECT_TITLES[job.effect_id]} {amount}")

        needs_game = job.effect_id not in {"flash", "minecraft_takeover"}
        if needs_game and cfg["general"]["require_cs2_running"] and not is_cs2_running(cfg["cs2"]["process_name"]):
            self.log("CS2 не запущен — клавиши пропущены. Табличка уже должна быть видна.")
            return
        if needs_game and (not is_test) and delay <= 0 and cfg["general"]["require_cs2_focused"] and not is_cs2_focused(cfg["cs2"]["window_title"]):
            self.log("CS2 не в фокусе — клавиши пропущены. Табличка уже должна быть видна.")
            return

        self.log(f"Диагностика перед эффектом: {diagnose_cs2(cfg, self.guard.hook_ok())}")
        active = foreground_title() or "(нет)"
        if job.effect_id not in {"flash", "kill_cs2", "minecraft_takeover"}:
            if not is_cs2_focused(cfg["cs2"]["window_title"]):
                self.log(
                    f"CS2 не в фокусе (сейчас «{active}»). "
                    "Клавиши уйдут не в игру. Запусти run-admin.bat, CS2 — «во весь экран в окне», на тесте сразу Alt+Tab."
                )
        self.log(f"Старт: {EFFECT_TITLES[job.effect_id]} → окно «{active}»")
        self._dispatch(job.effect_id, cfg)
        if not is_test:
            self._cooldowns[job.effect_id] = time.time() + float(effect.get("cooldown_sec") or 0)
            self._global_ready_at = time.time() + float(cfg["general"].get("global_cooldown_sec") or 0)
        self.log(f"Готово: {EFFECT_TITLES[job.effect_id]} | фокус «{foreground_title() or '(нет)'}»")

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
            if not self.guard.hook_ok():
                raise RuntimeError(
                    "Хук клавиатуры не встал, WASD не заблокируются. Закрой приложение и запусти run.bat от имени администратора."
                )
            keys = cfg["cs2"]["keys"]
            names = [keys["forward"], keys["back"], keys["left"], keys["right"]]
            self.log(f"WASD блок {cfg['effects']['block_wasd'].get('duration_sec', 10)}с, клавиши {names}")
            self.guard.set_blocked_keys(names)
            gen = self._generation
            deadline = time.time() + float(cfg["effects"]["block_wasd"].get("duration_sec", 10))
            while time.time() < deadline:
                if self._stop or self._generation != gen:
                    break
                time.sleep(0.05)
            self.guard.clear_blocked_keys()
            self.log("WASD снова работают")
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


def _amount_close(got: float, wanted: float, tolerance: float = 0.0) -> bool:
    """Точное совпадение. Допуск по умолчанию — копейки, не ±1₽."""
    fuzz = max(0.005, float(tolerance or 0))
    return abs(got - wanted) <= fuzz + 1e-12
