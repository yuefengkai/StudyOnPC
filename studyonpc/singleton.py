# -*- coding: utf-8 -*-
"""Single-instance guards for StudyOnPC.

Windows mutex names (held for the process lifetime; do not rename lightly):
  Global\\StudyOnPC-main      — main / quiz UI role
  Global\\StudyOnPC-watchdog  — watchdog role

A second process of the same role that cannot acquire the mutex exits immediately.
Pid files are written via a temp file + os.replace so a reader never sees a
truncated or empty file (Path.write_text truncates first and caused spawn storms).
"""
from __future__ import annotations

import logging
import os
import re
import sys
import time
from pathlib import Path

log = logging.getLogger("studyonpc.singleton")

MUTEX_MAIN = "Global\\StudyOnPC-main"
MUTEX_WATCHDOG = "Global\\StudyOnPC-watchdog"
MUTEX_NAMES = {
    "main": MUTEX_MAIN,
    "watchdog": MUTEX_WATCHDOG,
}

# WinError 8 / 1450 / 1455: not enough memory, no system resources, pagefile/commit limit.
RESOURCE_WINERRORS = {8, 1450, 1455}
RESOURCE_ERRNOS = {8, 12}  # ENOMEM variants
RESOURCE_COOLDOWN_SEC = 60.0
DEFAULT_FAIL_COOLDOWN_SEC = 30.0
MIN_SPAWN_INTERVAL_SEC = 15.0
MAX_COOLDOWN_SEC = 300.0

ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
WAIT_ABANDONED = 128
WAIT_TIMEOUT = 258

_held_mutexes: dict[str, object] = {}
_mutex_backend = None  # tests: fn(role, name) -> bool
_list_processes_backend = None  # tests: fn() -> list[tuple[int, str]]

_spawn_blocked_until: dict[str, float] = {}
_last_spawn_attempt: dict[str, float] = {}
_spawn_fail_streak: dict[str, int] = {}
_cooldown_logged: dict[str, bool] = {}
_last_error: dict[str, str] = {}

_ROLE_RE = re.compile(r"--role=([A-Za-z0-9_]+)", re.I)
_WATCHDOG_FLAG_RE = re.compile(r"(^|\s)--watchdog(\s|$)", re.I)
_APP_SCRIPT_RE = re.compile(r'(^|[\'"\s\\/])studyonpc\.py([\'"\s]|$)', re.I)
_APP_EXE_RE = re.compile(r'(^|[\'"\s\\/])studyonpc\.exe([\'"\s]|$)', re.I)


def reset_spawn_gates_for_tests() -> None:
    _spawn_blocked_until.clear()
    _last_spawn_attempt.clear()
    _spawn_fail_streak.clear()
    _cooldown_logged.clear()
    _last_error.clear()


def set_mutex_backend(fn) -> None:
    """Tests may inject a backend: fn(role, name) -> bool."""
    global _mutex_backend
    _mutex_backend = fn


def set_list_processes_backend(fn) -> None:
    """Tests may inject a process lister: fn() -> list[(pid, command_line)]."""
    global _list_processes_backend
    _list_processes_backend = fn


def release_held_mutexes_for_tests() -> None:
    """Close test/posix lock fds. Production holds the mutex for process lifetime."""
    for role, handle in list(_held_mutexes.items()):
        try:
            if isinstance(handle, int):
                os.close(handle)
        except Exception:
            pass
        _held_mutexes.pop(role, None)


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write text so readers never observe a truncated destination file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def acquire_role_mutex(role: str) -> bool:
    """Acquire the per-role mutex. True if this process now holds it uniquely.

    The handle is kept in ``_held_mutexes`` for the process lifetime.
    """
    role = (role or "").strip() or "main"
    name = MUTEX_NAMES.get(role)
    if not name:
        log.error("unknown role %r — cannot acquire singleton mutex", role)
        return False
    if role in _held_mutexes:
        return True
    if _mutex_backend is not None:
        ok = bool(_mutex_backend(role, name))
        if ok:
            _held_mutexes[role] = object()
        return ok
    if sys.platform == "win32":
        return _acquire_windows_mutex(role, name)
    return _acquire_posix_lock(role, name)


def _acquire_windows_mutex(role: str, name: str) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        err = kernel32.GetLastError()
        log.warning("CreateMutexW(%s) failed err=%s", name, err)
        return False
    # 0 ms: acquire if free; WAIT_TIMEOUT means another instance already holds it.
    result = kernel32.WaitForSingleObject(handle, 0)
    if result in (WAIT_OBJECT_0, WAIT_ABANDONED):
        _held_mutexes[role] = handle
        log.info("acquired mutex %s", name)
        return True
    kernel32.CloseHandle(handle)
    log.info("mutex %s already held — this %s instance will exit", name, role)
    return False


def _acquire_posix_lock(role: str, name: str) -> bool:
    import fcntl

    from .paths import LOG_DIR, ensure_runtime_dirs

    ensure_runtime_dirs()
    lock_path = LOG_DIR / f"singleton-{role}.lock"
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    except Exception as e:
        log.warning("singleton lock open failed (%s): %s", name, e)
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        log.info("posix lock %s already held — this %s instance will exit", lock_path, role)
        return False
    except Exception as e:
        os.close(fd)
        log.warning("posix lock failed: %s", e)
        return False
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
    except Exception:
        pass
    _held_mutexes[role] = fd
    log.info("acquired posix lock %s (%s)", lock_path, name)
    return True


def cmdline_matches_role(cmdline: str, role: str) -> bool:
    """True if a process command line is a StudyOnPC instance of ``role``."""
    if not cmdline:
        return False
    if not (_APP_SCRIPT_RE.search(cmdline) or _APP_EXE_RE.search(cmdline)):
        return False
    found = _ROLE_RE.search(cmdline)
    if found:
        return found.group(1).lower() == role.lower()
    if _WATCHDOG_FLAG_RE.search(cmdline):
        return role.lower() == "watchdog"
    return role.lower() == "main"


def list_live_role_pids(role: str) -> list[int]:
    """Living PIDs whose command line is this app + role (may include self)."""
    if _list_processes_backend is not None:
        rows = list(_list_processes_backend())
    elif sys.platform == "win32":
        rows = _list_windows_processes()
    else:
        rows = _list_linux_processes()
    pids: list[int] = []
    for pid, cmd in rows:
        try:
            ipid = int(pid)
        except (TypeError, ValueError):
            continue
        if ipid <= 0:
            continue
        if cmdline_matches_role(str(cmd or ""), role):
            pids.append(ipid)
    return pids


def peer_role_alive(role: str) -> bool:
    """True if another living process (not us) is already running this role."""
    me = os.getpid()
    return any(pid != me for pid in list_live_role_pids(role))


def _list_windows_processes() -> list[tuple[int, str]]:
    import subprocess

    creation = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creation |= subprocess.CREATE_NO_WINDOW
    ps = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -and "
        "($_.CommandLine -like '*studyonpc.py*' -or $_.CommandLine -like '*StudyOnPC.exe*') } | "
        'ForEach-Object { "{0}`t{1}" -f $_.ProcessId, '
        "(($_.CommandLine -replace '[\\t\\r\\n]', ' ')) }"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=creation,
        )
    except Exception as e:
        log.warning("process list failed: %s", e)
        return []
    rows: list[tuple[int, str]] = []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        pid_s, cmd = line.split("\t", 1)
        try:
            rows.append((int(pid_s), cmd))
        except ValueError:
            continue
    return rows


def _list_linux_processes() -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    proc = Path("/proc")
    if not proc.exists():
        return rows
    for p in proc.iterdir():
        if not p.name.isdigit():
            continue
        try:
            raw = (p / "cmdline").read_bytes().replace(b"\x00", b" ")
            cmd = raw.decode("utf-8", "replace")
            rows.append((int(p.name), cmd))
        except Exception:
            continue
    return rows


def spawn_allowed(role: str, now: float | None = None) -> bool:
    """False if this role is in spawn cooldown. Logs at most once per window."""
    now = time.monotonic() if now is None else now
    until = _spawn_blocked_until.get(role, 0.0)
    if now < until:
        if not _cooldown_logged.get(role):
            remain = max(0.0, until - now)
            log.warning(
                "spawn %s skipped (cooldown %.0fs left, last error: %s)",
                role,
                remain,
                _last_error.get(role, ""),
            )
            _cooldown_logged[role] = True
        return False
    last = _last_spawn_attempt.get(role, 0.0)
    if last and (now - last) < MIN_SPAWN_INTERVAL_SEC:
        return False
    return True


def note_spawn_attempt(role: str, now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    _last_spawn_attempt[role] = now
    _cooldown_logged[role] = False


def note_spawn_failure(role: str, exc: BaseException, now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    _last_spawn_attempt[role] = now
    _last_error[role] = f"{type(exc).__name__}: {exc}"
    streak = _spawn_fail_streak.get(role, 0) + 1
    _spawn_fail_streak[role] = streak
    base = RESOURCE_COOLDOWN_SEC if _is_resource_error(exc) else DEFAULT_FAIL_COOLDOWN_SEC
    delay = min(MAX_COOLDOWN_SEC, base * (2 ** (streak - 1)))
    _spawn_blocked_until[role] = now + delay
    _cooldown_logged[role] = False
    log.warning("spawn %s failed, backing off %.0fs: %s", role, delay, exc)


def note_spawn_success(role: str, now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    _last_spawn_attempt[role] = now
    _spawn_fail_streak[role] = 0
    _spawn_blocked_until.pop(role, None)
    _cooldown_logged[role] = False


def _is_resource_error(exc: BaseException) -> bool:
    winerr = getattr(exc, "winerror", None)
    if winerr in RESOURCE_WINERRORS:
        return True
    err = getattr(exc, "errno", None)
    if err in RESOURCE_WINERRORS or err in RESOURCE_ERRNOS:
        return True
    msg = str(exc)
    return (
        "1455" in msg
        or "1450" in msg
        or "Not enough memory" in msg
        or "页面文件" in msg
        or "commitment" in msg.lower()
    )
