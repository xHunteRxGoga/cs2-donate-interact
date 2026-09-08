from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

CREATE_NO_WINDOW = 0x08000000


class YoutubeAudio:
    """Играет YouTube только звуком, без окна и без закрытия CS2."""

    def __init__(self, log: Callable[[str], None] | None = None) -> None:
        self.log = log or (lambda _msg: None)
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._gen = 0

    def play(self, url: str, volume: int = 80) -> None:
        clean = (url or "").strip()
        if not clean:
            return
        self._gen += 1
        gen = self._gen
        threading.Thread(target=self._run, args=(clean, max(0, min(100, int(volume))), gen), daemon=True, name="yt-audio").start()

    def stop(self) -> None:
        self._gen += 1
        self._kill()

    def _run(self, url: str, volume: int, gen: int) -> None:
        cmd = self._command(url, volume)
        if not cmd:
            self.log(
                "музыка: нет плеера. Поставь mpv (https://mpv.io/) и перезапусти программу — "
                "YouTube из доната Trula заиграет в наушниках."
            )
            return
        if gen != self._gen:
            return
        self.log(f"музыка: играю {url}")
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
        proc.wait()
        with self._lock:
            if self._proc is proc:
                self._proc = None
        if gen == self._gen:
            self.log("музыка: трек закончился")

    def _command(self, url: str, volume: int) -> list[str] | None:
        mpv = shutil.which("mpv")
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
                "--no-input-default-bindings",
                url,
            ]
            if ytdlp:
                cmd.insert(1, f"--script-opts=ytdl_hook-ytdl_path={ytdlp}")
            return cmd
        vlc = shutil.which("vlc") or shutil.which("vlc.exe")
        if vlc:
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

    def _kill(self) -> None:
        with self._lock:
            self._kill_locked()

    def _kill_locked(self) -> None:
        proc = self._proc
        self._proc = None
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


def _player_env() -> dict[str, str]:
    env = os.environ.copy()
    scripts = Path(sys.executable).parent / "Scripts"
    extra = [str(scripts), str(Path(sys.executable).parent)]
    env["PATH"] = os.pathsep.join([*extra, env.get("PATH", "")])
    return env
