from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from src.config import ROOT

REPO = "xHunteRxGoga/cs2-donate-interact"
BRANCH = "main"
API_COMMIT = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
ZIP_URL = f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip"
REVISION_PATH = ROOT / ".app_revision"
UA = {"User-Agent": "cs2-donate-interact-updater", "Accept": "application/vnd.github+json"}
CHECK_EVERY_SEC = 45 * 60

KEEP_ROOT = {
    "config.json",
    "secrets.json",
    ".app_revision",
    "logs",
    ".venv",
    "venv",
    "env",
    ".git",
    ".idea",
    ".vscode",
    ".cursor",
    "canvases",
}
VIDEO_EXT = {".mp4", ".mkv", ".webm", ".avi", ".mov"}


@dataclass
class UpdateResult:
    status: str
    detail: str
    sha: str = ""
    changed: bool = False


def read_sha() -> str:
    try:
        return REVISION_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_sha(sha: str) -> None:
    REVISION_PATH.write_text(sha.strip() + "\n", encoding="utf-8")


def is_git_checkout() -> bool:
    return (ROOT / ".git").is_dir()


def restart_process() -> None:
    os.chdir(ROOT)
    args = [sys.executable, "-m", "src.main"]
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        subprocess.Popen(
            args,
            cwd=str(ROOT),
            close_fds=True,
            creationflags=flags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        raise SystemExit(0)
    os.execv(sys.executable, args)


def bootstrap() -> None:
    """Точка входа: при необходимости обновиться и перезапуститься, потом открыть окно."""
    from src.config import load_config

    cfg = {}
    try:
        cfg = load_config()
    except Exception:
        cfg = {}
    enabled = bool((cfg.get("general") or {}).get("auto_update", True))
    if enabled:
        try:
            result = check_and_apply(apply=True, on_status=lambda text: print(text, flush=True))
            print(result.detail, flush=True)
            if result.changed:
                print("перезапуск с новой версией…", flush=True)
                restart_process()
        except Exception as exc:
            print(f"автообновление пропущено: {exc}", flush=True)
    from src.app import run

    run()


def check_and_apply(apply: bool = True, on_status=None) -> UpdateResult:
    def note(text: str) -> None:
        if on_status:
            on_status(text)

    if os.environ.get("CS2DI_SKIP_UPDATE") == "1":
        return UpdateResult("skipped", "автообновление выключено переменной CS2DI_SKIP_UPDATE")

    note("спрашиваю GitHub, есть ли новая версия…")
    try:
        remote = _remote_sha()
    except Exception as exc:
        return UpdateResult("error", f"GitHub недоступен: {exc}")

    local = read_sha()
    if local and local == remote:
        return UpdateResult("current", f"уже последняя версия {remote[:7]}", remote)

    if not apply:
        return UpdateResult("pending", f"на GitHub есть {remote[:7]}", remote)

    if is_git_checkout():
        return _apply_git(remote, note)
    return _apply_zip(remote, note)


def _remote_sha() -> str:
    with httpx.Client(timeout=12.0, follow_redirects=True, headers=UA) as client:
        resp = client.get(API_COMMIT)
        resp.raise_for_status()
        sha = str(resp.json().get("sha") or "")
        if len(sha) < 7:
            raise RuntimeError("GitHub не отдал commit sha")
        return sha


def _apply_git(remote: str, note) -> UpdateResult:
    if _git_out("status", "--porcelain").strip():
        return UpdateResult(
            "skipped",
            "это git-клон с локальными правками — не трогаю, чтобы не затереть работу",
            remote,
        )
    note("git fetch origin…")
    fetch = _git("fetch", "origin", BRANCH)
    if fetch.returncode != 0:
        return UpdateResult("error", f"git fetch: {_tail(fetch.stderr)}", remote)
    old = _git_out("rev-parse", "HEAD").strip()
    merge = _git("merge", "--ff-only", f"origin/{BRANCH}")
    if merge.returncode != 0:
        return UpdateResult("skipped", f"git merge --ff-only не прошёл: {_tail(merge.stderr)}", remote)
    new = _git_out("rev-parse", "HEAD").strip() or remote
    write_sha(new)
    if new != old:
        _wipe_pycache()
        _pip_install(note)
        return UpdateResult("updated", f"подтянул GitHub {new[:7]}", new, changed=True)
    return UpdateResult("current", f"уже последняя версия {new[:7]}", new)


def _apply_zip(remote: str, note) -> UpdateResult:
    note("скачиваю ZIP с GitHub…")
    with tempfile.TemporaryDirectory(prefix="cs2di-upd-") as tmp:
        tmp_path = Path(tmp)
        archive = tmp_path / "src.zip"
        with httpx.Client(timeout=60.0, follow_redirects=True, headers=UA) as client:
            with client.stream("GET", ZIP_URL) as resp:
                resp.raise_for_status()
                with archive.open("wb") as handle:
                    for chunk in resp.iter_bytes():
                        handle.write(chunk)
        extract_to = tmp_path / "unpacked"
        extract_to.mkdir()
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(extract_to)
        inner = _zip_root(extract_to)
        copied = _copy_tree(inner, ROOT)
        if copied <= 0:
            return UpdateResult("error", "ZIP с GitHub пустой или нечего копировать", remote)
    write_sha(remote)
    _wipe_pycache()
    _pip_install(note)
    return UpdateResult("updated", f"поставил GitHub {remote[:7]} ({copied} файлов)", remote, changed=True)


def _zip_root(extracted: Path) -> Path:
    children = [p for p in extracted.iterdir() if p.is_dir()]
    if len(children) == 1:
        return children[0]
    return extracted


def _skip(rel: Path, dest_root: Path) -> bool:
    parts = rel.parts
    if not parts:
        return True
    if parts[0] in KEEP_ROOT:
        return True
    if any(part in {"__pycache__", ".git"} for part in parts):
        return True
    if rel.suffix in {".pyc", ".pyo"}:
        return True
    if rel.suffix.lower() in VIDEO_EXT and (dest_root / rel).exists():
        return True
    return False


def _copy_tree(src_root: Path, dest_root: Path) -> int:
    copied = 0
    for path in src_root.rglob("*"):
        rel = path.relative_to(src_root)
        if _skip(rel, dest_root):
            continue
        dest = dest_root / rel
        if path.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        copied += 1
    return copied


def _wipe_pycache() -> None:
    src = ROOT / "src"
    if not src.is_dir():
        return
    for path in src.rglob("__pycache__"):
        shutil.rmtree(path, ignore_errors=True)


def _pip_install(note) -> None:
    req = ROOT / "requirements.txt"
    if not req.exists():
        return
    note("проверяю зависимости…")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req), "-q"],
            cwd=str(ROOT),
            timeout=120,
            check=False,
            capture_output=True,
        )
    except Exception:
        pass


def _git(*args: str, timeout: int = 45) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _git_out(*args: str) -> str:
    proc = _git(*args)
    return proc.stdout if proc.returncode == 0 else ""


def _tail(text: str, n: int = 180) -> str:
    return (text or "").strip().replace("\n", " ")[:n]
