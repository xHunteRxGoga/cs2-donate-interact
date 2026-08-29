from __future__ import annotations

import base64
import queue
import subprocess
import sys
import threading
from typing import Callable


CREATE_NO_WINDOW = 0x08000000

_PS = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$ru = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'ru*' } | Select-Object -First 1
if ($ru) { $s.SelectVoice($ru.VoiceInfo.Name) }
[Console]::Out.WriteLine('READY ' + $s.Voice.Name)
[Console]::Out.Flush()
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($null -eq $line) { break }
  if ($line -eq 'QUIT') { break }
  if ($line.StartsWith('VOL ')) {
    $n = 0
    if ([int]::TryParse($line.Substring(4), [ref]$n)) {
      if ($n -lt 0) { $n = 0 }
      if ($n -gt 100) { $n = 100 }
      $s.Volume = $n
    }
    continue
  }
  if ($line.StartsWith('SAY ')) {
    $text = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($line.Substring(4)))
    $s.Speak($text)
    [Console]::Out.WriteLine('OK')
    [Console]::Out.Flush()
  }
}
"""


class Voice:
    """Очередь озвучки через стандартный Windows SAPI (как системный голос)."""

    def __init__(self, log: Callable[[str], None] | None = None) -> None:
        self.log = log or (lambda _msg: None)
        self.volume = 80
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._proc: subprocess.Popen[str] | None = None
        self._voice_name = ""
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, name="tts", daemon=True)
        self._thread.start()

    def set_volume(self, value: int) -> None:
        self.volume = max(0, min(100, int(value)))

    def say(self, text: str) -> None:
        clean = _clean(text)
        if not clean:
            return
        self._queue.put(clean)

    def stop(self) -> None:
        self._queue.put(None)
        proc = self._proc
        if proc and proc.stdin:
            try:
                proc.stdin.write("QUIT\n")
                proc.stdin.flush()
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass

    def _loop(self) -> None:
        if sys.platform != "win32":
            self.log("озвучка: не Windows — голос недоступен")
            return
        while True:
            item = self._queue.get()
            if item is None:
                return
            try:
                self._speak(item)
            except Exception as exc:
                self.log(f"озвучка ошибка: {exc}")
                self._close_proc()

    def _speak(self, text: str) -> None:
        proc = self._ensure()
        if not proc or not proc.stdin:
            return
        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
        proc.stdin.write(f"VOL {self.volume}\nSAY {payload}\n")
        proc.stdin.flush()
        if proc.stdout:
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError("процесс озвучки закрылся")

    def _ensure(self) -> subprocess.Popen[str] | None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return self._proc
            self._proc = subprocess.Popen(
                [
                    "powershell",
                    "-NoProfile",
                    "-STA",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    _PS,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
            )
            if self._proc.stdout:
                hello = self._proc.stdout.readline().strip()
                if hello.startswith("READY "):
                    self._voice_name = hello[6:]
                    self.log(f"озвучка: голос Windows «{self._voice_name}»")
                elif not hello:
                    err = ""
                    if self._proc.stderr:
                        err = self._proc.stderr.read()[:240]
                    self._close_proc()
                    raise RuntimeError(err or "SAPI не запустился")
            return self._proc

    def _close_proc(self) -> None:
        proc = self._proc
        self._proc = None
        if proc:
            try:
                proc.kill()
            except Exception:
                pass


def _clean(text: str) -> str:
    raw = " ".join((text or "").split())
    if len(raw) > 400:
        raw = raw[:400]
    return raw
