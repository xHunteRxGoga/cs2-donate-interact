from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from src.config import ROOT

LOG_DIR = ROOT / "logs"
LOG_PATH = LOG_DIR / "debug.log"
_lock = threading.Lock()


def write(text: str) -> str:
    stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{stamp}] {text}"
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with _lock:
            with LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except OSError:
        pass
    return line


def read_tail(max_chars: int = 80000) -> str:
    try:
        data = LOG_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""
    return data[-max_chars:]
