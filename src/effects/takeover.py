from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from src.effects.cs2 import kill_cs2
from src.effects.input_win import InputGuard


class TakeoverController:
    def __init__(self, guard: InputGuard) -> None:
        self.guard = guard
        self._proc: subprocess.Popen | None = None
        self._stop = False

    def cancel(self) -> None:
        self._stop = True
        self.guard.set_block_all(False)
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def run(self, video_path: Path, youtube_url: str, process_name: str, block_input: bool) -> None:
        self._stop = False
        kill_cs2(process_name)
        time.sleep(0.4)
        if block_input:
            self.guard.set_block_all(True)
        try:
            cmd = self._player_command(video_path, youtube_url)
            if not cmd:
                raise RuntimeError(
                    "Нет видеоплеера. Положи mp4 в assets/ или установи mpv/VLC."
                )
            self._proc = subprocess.Popen(cmd)
            while self._proc.poll() is None and not self._stop:
                time.sleep(0.2)
        finally:
            self.guard.set_block_all(False)
            if self._proc and self._proc.poll() is None and self._stop:
                self._proc.terminate()
            self._proc = None

    def _player_command(self, video_path: Path, youtube_url: str) -> list[str] | None:
        mpv = shutil.which("mpv")
        vlc = shutil.which("vlc") or shutil.which("vlc.exe")
        target = youtube_url.strip() if youtube_url.strip() else str(video_path)
        if youtube_url.strip() and not mpv:
            if video_path.exists():
                target = str(video_path)
            else:
                return None
        if not youtube_url.strip() and not video_path.exists():
            return None
        if mpv:
            return [
                mpv,
                "--fullscreen",
                "--ontop",
                "--no-osc",
                "--no-input-default-bindings",
                "--input-vo-keyboard=no",
                "--keep-open=no",
                "--force-window=yes",
                target,
            ]
        if vlc and not youtube_url.strip():
            return [
                vlc,
                "--fullscreen",
                "--play-and-exit",
                "--no-video-title-show",
                "--qt-minimal-view",
                str(video_path),
            ]
        return None
