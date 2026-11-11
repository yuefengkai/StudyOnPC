# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from . import win_yt
from .paths import APP_DIR, MAIN_PID, STOP_FLAG, WATCH_PID, ensure_runtime_dirs, frozen
from .singleton import (
    atomic_write_text,
    note_spawn_attempt,
    note_spawn_failure,
    note_spawn_success,
    peer_role_alive,
    spawn_allowed,
)

log = logging.getLogger("studyonpc.watchdog")


def read_pid(path: Path) -> int | None:
    """Return a pid, or None if the file is missing, empty, partial, or invalid."""
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return None
    text = raw.strip()
    if not text or not text.isdigit():
        return None
    try:
        pid = int(text)
    except ValueError:
        return None
    return pid if pid > 0 else None


def write_pid(path: Path, pid: int | None = None) -> None:
    """Atomically write a pid (temp file + os.replace). Never truncate-in-place."""
    atomic_write_text(path, str(os.getpid() if pid is None else int(pid)))


def stop_requested() -> bool:
    return STOP_FLAG.exists()


def clear_stop_flag() -> None:
    try:
        STOP_FLAG.unlink(missing_ok=True)
    except Exception:
        pass


def spawn_role(role: str) -> bool:
    """Relaunch self as exe when frozen; otherwise pythonw + studyonpc.py."""
    ensure_runtime_dirs()
    cwd = str(APP_DIR)
    if frozen():
        args = [sys.executable, f"--role={role}"]
        log.info("spawned role=%s via frozen exe %s", role, sys.executable)
    else:
        py = win_yt.preferred_python()
        entry = APP_DIR / "studyonpc.py"
        args = [py, str(entry), f"--role={role}"]
        log.info("spawned role=%s via %s", role, py)
    try:
        win_yt.spawn_detached(args, cwd=cwd, raise_on_error=True)
    except Exception as e:
        note_spawn_failure(role, e)
        return False
    note_spawn_success(role)
    return True


def ensure_peer(peer_role: str, peer_pid_file: Path) -> None:
    if stop_requested():
        return
    pid = read_pid(peer_pid_file)
    if pid and win_yt.pid_alive(pid):
        return
    # Pid file empty/partial/stale must not cause a spawn if the peer is alive.
    if peer_role_alive(peer_role):
        log.info("peer role=%s already living (pid file missing or stale) — not spawning", peer_role)
        return
    if not spawn_allowed(peer_role):
        return
    note_spawn_attempt(peer_role)
    spawn_role(peer_role)


def run_watchdog() -> None:
    ensure_runtime_dirs()
    log.info("watchdog started pid=%s frozen=%s", os.getpid(), frozen())
    write_pid(WATCH_PID)
    if STOP_FLAG.exists() and "--force" not in sys.argv and "--ignore-stop" not in sys.argv:
        log.info("watchdog sees stop.flag — exit")
        return
    ensure_peer("main", MAIN_PID)
    while True:
        time.sleep(3)
        if stop_requested():
            log.info("watchdog stop.flag — exit")
            return
        write_pid(WATCH_PID)
        ensure_peer("main", MAIN_PID)
