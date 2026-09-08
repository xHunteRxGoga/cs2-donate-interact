from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

CREATE_NO_WINDOW = 0x08000000
_DEVICE_LINE = re.compile(r"^(?:'([^']+)'|(\S+))\s+\((.*)\)\s*$")


class YoutubeAudio:
    """Играет YouTube только звуком, без окна и без закрытия CS2."""

    def __init__(self, log: Callable[[str], None] | None = None) -> None:
        self.log = log or (lambda _msg: None)
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._gen = 0
        self._volume = 80
        self._device = ""
        self._pipe = ""

    def playing(self) -> bool:
        with self._lock:
            proc = self._proc
        return bool(proc) and proc.poll() is None

    def volume(self) -> int:
        return self._volume

    def set_volume(self, volume: int) -> int:
        self._volume = max(0, min(100, int(volume)))
        self._ipc(["set_property", "volume", self._volume])
        return self._volume

    def nudge(self, delta: int) -> int:
        return self.set_volume(self._volume + int(delta))

    def set_device(self, device: str) -> None:
        self._device = (device or "").strip()
        self._ipc(["set_property", "audio-device", self._device or "auto"])

    def play(self, url: str, volume: int | None = None, device: str | None = None) -> None:
        clean = (url or "").strip()
        if not clean:
            return
        if volume is not None:
            self._volume = max(0, min(100, int(volume)))
        if device is not None:
            self._device = (device or "").strip()
        self._gen += 1
        gen = self._gen
        threading.Thread(
            target=self._run,
            args=(clean, self._volume, self._device, gen),
            daemon=True,
            name="yt-audio",
        ).start()

    def play_test(self, volume: int | None = None, device: str | None = None) -> None:
        if self.playing():
            self.log("музыка: уже играет трек — если его слышно, устройство выбрано верно")
            return
        self.play("av://lavfi:sine=frequency=880:duration=1.6", volume, device)

    def stop(self) -> None:
        self._gen += 1
        self._kill()

    def _run(self, url: str, volume: int, device: str, gen: int) -> None:
        pipe = rf"\\.\pipe\cs2donateyt{os.getpid()}_{gen}"
        cmd = self._command(url, volume, device, pipe)
        if not cmd:
            self.log(
                "музыка: нет плеера. Поставь mpv (https://mpv.io/) и перезапусти программу — "
                "YouTube из доната Trula заиграет в выбранных наушниках."
            )
            return
        if gen != self._gen:
            return
        where = device or "устройство Windows по умолчанию"
        self.log(f"музыка: играю {url} → {where}")
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_player_env(),
                creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except Exception as exc:
            self.log(f"музыка ошибка запуска: {exc}")
            return
        with self._lock:
            self._kill_locked()
            self._proc = proc
            self._pipe = pipe
        code = proc.wait()
        with self._lock:
            if self._proc is proc:
                self._proc = None
                self._pipe = ""
        if gen != self._gen:
            return
        if code not in (0, None):
            self.log(f"музыка: mpv вышел с кодом {code}. Проверь устройство вывода и что mpv видит YouTube.")
            return
        self.log("музыка: трек закончился")

    def _command(self, url: str, volume: int, device: str, pipe: str) -> list[str] | None:
        mpv = find_mpv()
        ytdlp = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
        if not ytdlp:
            hint = Path(sys.executable).parent / "Scripts" / ("yt-dlp.exe" if sys.platform == "win32" else "yt-dlp")
            if hint.exists():
                ytdlp = str(hint)
        if mpv:
            cmd = [
                mpv,
                "--no-video",
                "--force-window=no",
                "--no-terminal",
                "--really-quiet",
                "--ytdl=yes",
                f"--volume={volume}",
                "--volume-max=100",
                "--no-input-default-bindings",
                "--audio-exclusive=no",
                "--audio-client-name=Trula music",
                f"--input-ipc-server={pipe}",
                url,
            ]
            if device:
                cmd.insert(1, f"--audio-device={device}")
            if ytdlp:
                cmd.insert(1, f"--script-opts=ytdl_hook-ytdl_path={ytdlp}")
            return cmd
        vlc = shutil.which("vlc") or shutil.which("vlc.exe")
        if vlc:
            self.log("музыка: VLC не умеет смену устройства и Alt± по треку. Лучше поставить mpv.")
            return [
                vlc,
                "--intf",
                "dummy",
                "--play-and-exit",
                "--no-video",
                f"--volume={int(volume * 2.56)}",
                url,
            ]
        return None

    def _ipc(self, command: list) -> None:
        payload = (json.dumps({"command": command}) + "\n").encode("utf-8")
        with self._lock:
            pipe = self._pipe
            alive = bool(self._proc) and self._proc.poll() is None
        if not pipe or not alive:
            return
        for _ in range(12):
            try:
                with open(pipe, "wb", buffering=0) as handle:
                    handle.write(payload)
                return
            except OSError:
                time.sleep(0.05)

    def _kill(self) -> None:
        with self._lock:
            self._kill_locked()

    def _kill_locked(self) -> None:
        proc = self._proc
        self._proc = None
        self._pipe = ""
        if not proc or proc.poll() is not None:
            return
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def find_mpv() -> str | None:
    found = shutil.which("mpv") or shutil.which("mpv.exe")
    if found:
        return found
    roots = [
        Path(os.environ.get("ProgramFiles") or r"C:\Program Files"),
        Path(os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"),
        Path(os.environ.get("LOCALAPPDATA") or ""),
        Path(__file__).resolve().parents[2],
    ]
    for root in roots:
        if not root:
            continue
        for cand in (
            root / "mpv" / "mpv.exe",
            root / "mpv.net" / "mpv.exe",
            root / "Programs" / "mpv" / "mpv.exe",
        ):
            if cand.exists():
                return str(cand)
    return None


def list_audio_devices() -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = [("", "По умолчанию Windows")]
    mpv = find_mpv()
    if not mpv:
        return items
    try:
        proc = subprocess.run(
            [mpv, "--audio-device=help"],
            capture_output=True,
            text=True,
            timeout=10,
            env=_player_env(),
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except Exception:
        return items
    seen = {""}
    text = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    for raw in text.splitlines():
        line = raw.strip()
        match = _DEVICE_LINE.match(line)
        if not match:
            continue
        dev_id = (match.group(1) or match.group(2) or "").strip()
        title = (match.group(3) or "").strip()
        if not dev_id or dev_id.lower() in {"auto", "help"} or dev_id in seen:
            continue
        seen.add(dev_id)
        items.append((dev_id, title or dev_id))
    return items


def _player_env() -> dict[str, str]:
    env = os.environ.copy()
    scripts = Path(sys.executable).parent / "Scripts"
    extra = [str(scripts), str(Path(sys.executable).parent)]
    env["PATH"] = os.pathsep.join([*extra, env.get("PATH", "")])
    return env
