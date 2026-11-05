# -*- coding: utf-8 -*-
"""Foreground YouTube detect / minimize / mute — Windows real, Linux stubs."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Callable

from .paths import mute_ps1

log = logging.getLogger("studyonpc.win_yt")

IS_WINDOWS = os.name == "nt"
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0

user32 = None
if IS_WINDOWS:
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]

SW_MINIMIZE = 6
SW_RESTORE = 9
GW_OWNER = 4


def _get_window_text(hwnd: int) -> str:
    if not IS_WINDOWS or user32 is None:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    import ctypes

    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value or ""


def _is_visible_top_level(hwnd: int) -> bool:
    if not IS_WINDOWS or user32 is None:
        return False
    if not user32.IsWindowVisible(hwnd):
        return False
    if user32.GetWindow(hwnd, GW_OWNER):
        return False
    return True


def find_youtube_windows(keywords: list[str]) -> list[tuple[int, str]]:
    if not IS_WINDOWS or user32 is None:
        return []
    import ctypes

    results: list[tuple[int, str]] = []
    kws = [k.lower() for k in keywords]

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_proc(hwnd, _lparam):
        if not _is_visible_top_level(hwnd):
            return True
        title = _get_window_text(hwnd)
        low = title.lower()
        if any(k in low for k in kws):
            results.append((int(hwnd), title))
        return True

    user32.EnumWindows(enum_proc, 0)
    return results


def foreground_is_youtube(keywords: list[str]) -> tuple[bool, int | None, str]:
    if not IS_WINDOWS or user32 is None:
        return False, None, ""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False, None, ""
    title = _get_window_text(hwnd)
    low = title.lower()
    kws = [k.lower() for k in keywords]
    if any(k in low for k in kws):
        return True, int(hwnd), title
    for h, t in find_youtube_windows(keywords):
        if h == int(hwnd):
            return True, h, t
    return False, None, title


def minimize_hwnd(hwnd: int) -> None:
    if not IS_WINDOWS or user32 is None:
        return
    try:
        user32.ShowWindow(hwnd, SW_MINIMIZE)
    except Exception as e:
        log.warning("minimize failed: %s", e)


def restore_hwnd(hwnd: int) -> None:
    if not IS_WINDOWS or user32 is None:
        return
    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
    except Exception as e:
        log.warning("restore failed: %s", e)


def _run_mute_ps(action: str) -> str:
    if not IS_WINDOWS:
        return ""
    script = mute_ps1()
    if not script.exists():
        log.warning("set_mute.ps1 missing: %s", script)
        return ""
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Action",
                action,
            ],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=_CREATE_NO_WINDOW,
        )
        if r.returncode != 0:
            log.warning("mute ps stderr: %s", (r.stderr or "")[:300])
        return (r.stdout or "").strip()
    except Exception as e:
        log.warning("mute ps failed (%s): %s", action, e)
        return ""


def set_system_mute(mute: bool) -> None:
    if not IS_WINDOWS:
        return
    out = _run_mute_ps("on" if mute else "off")
    if out:
        return
    log.warning("Core Audio mute failed; VK_VOLUME_MUTE fallback")
    if user32 is None:
        return
    try:
        VK_VOLUME_MUTE = 0xAD
        KEYEVENTF_EXTENDEDKEY = 0x0001
        KEYEVENTF_KEYUP = 0x0002
        user32.keybd_event(VK_VOLUME_MUTE, 0, KEYEVENTF_EXTENDEDKEY, 0)
        user32.keybd_event(VK_VOLUME_MUTE, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
    except Exception as e:
        log.warning("key mute fallback failed: %s", e)


def get_system_mute() -> bool | None:
    if not IS_WINDOWS:
        return None
    out = _run_mute_ps("get").lower()
    if "true" in out:
        return True
    if "false" in out:
        return False
    return None


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if not IS_WINDOWS:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if h:
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    return False


def kill_pid(pid: int) -> None:
    if pid <= 0:
        return
    if IS_WINDOWS:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True,
                creationflags=_CREATE_NO_WINDOW,
            )
        except Exception:
            pass
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass


def preferred_python() -> str:
    py = sys.executable
    if IS_WINDOWS and py.lower().endswith("python.exe"):
        from pathlib import Path

        candidate = Path(py).with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return py


def spawn_detached(args: list[str], cwd: str) -> None:
    creation = 0
    if IS_WINDOWS:
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creation |= subprocess.CREATE_NO_WINDOW
        if hasattr(subprocess, "DETACHED_PROCESS"):
            creation |= subprocess.DETACHED_PROCESS
    try:
        subprocess.Popen(
            args,
            cwd=cwd,
            creationflags=creation,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        log.warning("spawn failed: %s", e)
