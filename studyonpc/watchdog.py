# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from . import win_yt
from .paths import APP_DIR, MAIN_PID, STOP_FLAG, WATCH_PID, ensure_runtime_dirs, frozen

log = logging.getLogger("studyonpc.watchdog")


def read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def write_pid(path: Path) -> None:
    path.write_text(str(os.getpid()), encoding="utf-8")


def stop_requested() -> bool:
    return STOP_FLAG.exists()


def clear_stop_flag() -> None:
    try:
        STOP_FLAG.unlink(missing_ok=True)
    except Exception:
        pass


def spawn_role(role: str) -> None:
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
    win_yt.spawn_detached(args, cwd=cwd)


def ensure_peer(peer_role: str, peer_pid_file: Path) -> None:
    if stop_requested():
        return
    pid = read_pid(peer_pid_file)
    if pid and win_yt.pid_alive(pid):
        return
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
