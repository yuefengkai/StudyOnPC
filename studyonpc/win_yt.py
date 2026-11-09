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


def _keybd(vk: int, *, extended: bool = False) -> None:
    """Press+release a virtual key via keybd_event."""
    if not IS_WINDOWS or user32 is None:
        return
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    flags = KEYEVENTF_EXTENDEDKEY if extended else 0
    user32.keybd_event(vk, 0, flags, 0)
    user32.keybd_event(vk, 0, flags | KEYEVENTF_KEYUP, 0)


def media_play_pause() -> None:
    """Toggle system media play/pause (Chrome YouTube Media Session responds)."""
    if not IS_WINDOWS or user32 is None:
        return
    try:
        VK_MEDIA_PLAY_PAUSE = 0xB3
        _keybd(VK_MEDIA_PLAY_PAUSE, extended=True)
    except Exception as e:
        log.warning("media play/pause failed: %s", e)


def _force_foreground(hwnd: int) -> bool:
    if not IS_WINDOWS or user32 is None or not hwnd:
        return False
    import ctypes
    from ctypes import wintypes

    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        fg = user32.GetForegroundWindow()
        if int(fg or 0) == int(hwnd):
            return True
        kernel32 = ctypes.windll.kernel32
        pid = wintypes.DWORD()
        tid_target = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        tid_fg = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        tid_cur = kernel32.GetCurrentThreadId()
        if tid_fg:
            user32.AttachThreadInput(tid_cur, tid_fg, True)
        if tid_target:
            user32.AttachThreadInput(tid_cur, tid_target, True)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if tid_fg:
            user32.AttachThreadInput(tid_cur, tid_fg, False)
        if tid_target:
            user32.AttachThreadInput(tid_cur, tid_target, False)
        return int(user32.GetForegroundWindow() or 0) == int(hwnd)
    except Exception as e:
        log.warning("force foreground failed: %s", e)
        try:
            user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
        return False


def _send_space_to_hwnd(hwnd: int) -> bool:
    """Focus window and send Space (YouTube / many players toggle play-pause).

    Returns True only when the target looks focused, so callers can fall back to
    the media key instead of assuming Space hit the player.
    """
    if not IS_WINDOWS or user32 is None or not hwnd:
        return False
    import time

    try:
        focused = _force_foreground(hwnd)
        time.sleep(0.08)
        # Re-check — SetForegroundWindow is flaky but GetForegroundWindow is honest.
        fg = int(user32.GetForegroundWindow() or 0)
        if fg != int(hwnd):
            log.info("space-to-hwnd: focus missed hwnd=%s fg=%s", hwnd, fg)
            return False
        VK_SPACE = 0x20
        _keybd(VK_SPACE)
        return True
    except Exception as e:
        log.warning("space-to-hwnd failed: %s", e)
        return False


# winuser.h APPCOMMAND_* — absolute play/pause (not toggle).
APPCOMMAND_MEDIA_PLAY_PAUSE = 14
APPCOMMAND_MEDIA_PLAY = 46
APPCOMMAND_MEDIA_PAUSE = 47


def _send_appcommand(hwnd: int, cmd: int) -> bool:
    """Deliver WM_APPCOMMAND to a top-level window (works while minimized)."""
    if not IS_WINDOWS or user32 is None or not hwnd:
        return False
    import ctypes
    from ctypes import wintypes

    try:
        WM_APPCOMMAND = 0x0319
        SMTO_ABORTIFHUNG = 0x0002
        lparam = int(cmd) << 16
        result = wintypes.DWORD()
        # Prefer SendMessageTimeout so Chrome/Edge media session sees it before we move on.
        ok = user32.SendMessageTimeoutW(
            int(hwnd),
            WM_APPCOMMAND,
            int(hwnd),
            lparam,
            SMTO_ABORTIFHUNG,
            400,
            ctypes.byref(result),
        )
        if not ok:
            user32.PostMessageW(int(hwnd), WM_APPCOMMAND, int(hwnd), lparam)
        return True
    except Exception as e:
        log.warning("WM_APPCOMMAND cmd=%s failed: %s", cmd, e)
        try:
            user32.PostMessageW(int(hwnd), 0x0319, int(hwnd), int(cmd) << 16)
            return True
        except Exception:
            return False


def _post_appcommand_play_pause(hwnd: int) -> bool:
    """Back-compat helper: toggle play/pause via APPCOMMAND."""
    return _send_appcommand(hwnd, APPCOMMAND_MEDIA_PLAY_PAUSE)


def _uniq_hwnds(hwnds: list[int]) -> list[int]:
    uniq: list[int] = []
    for h in hwnds:
        if h and int(h) not in uniq:
            uniq.append(int(h))
    return uniq


def pause_tracked_playback(hwnds: list[int]) -> bool:
    """Pause YouTube/video in tracked windows. Prefer absolute pause over mute/toggle.

    Why not Space / VK_MEDIA_PLAY_PAUSE alone:
      - Both are toggles; focus can look successful while the player ignores Space,
        then we skip the media key and the video keeps playing (especially with TTS unmuted).
      - APPCOMMAND_MEDIA_PAUSE is absolute — safe to send twice (minimize + reinforce).

    Strategy:
      1) APPCOMMAND_MEDIA_PAUSE on every tracked top-level hwnd (no focus steal)
      2) If no hwnds, one global media play/pause key as last resort (toggle)
    Do NOT also send Space after absolute pause — that would resume.
    """
    if not IS_WINDOWS or user32 is None:
        return False
    import time

    uniq = _uniq_hwnds(hwnds)
    if uniq:
        any_ok = False
        for hwnd in uniq:
            if _send_appcommand(hwnd, APPCOMMAND_MEDIA_PAUSE):
                any_ok = True
        time.sleep(0.08)
        log.info("pause_tracked_playback: APPCOMMAND_MEDIA_PAUSE hwnds=%s ok=%s", uniq, any_ok)
        return any_ok

    media_play_pause()
    log.info("pause_tracked_playback: media key fallback (no hwnds)")
    return True


def resume_tracked_playback(hwnds: list[int]) -> bool:
    """Resume after quiz via absolute MEDIA_PLAY (not toggle).

    Using play (not play/pause) avoids: paused → play → accidental second toggle → paused.
    """
    if not IS_WINDOWS or user32 is None:
        return False
    import time

    uniq = _uniq_hwnds(hwnds)
    if uniq:
        any_ok = False
        for hwnd in uniq:
            if _send_appcommand(hwnd, APPCOMMAND_MEDIA_PLAY):
                any_ok = True
        time.sleep(0.05)
        log.info("resume_tracked_playback: APPCOMMAND_MEDIA_PLAY hwnds=%s ok=%s", uniq, any_ok)
        return any_ok

    media_play_pause()
    log.info("resume_tracked_playback: media key fallback (no hwnds)")
    return True


def _powershell_exe() -> str | None:
    """Resolve powershell.exe even when PATH is stripped (common under pythonw/shims)."""
    if not IS_WINDOWS:
        return None
    import shutil
    from pathlib import Path

    found = shutil.which("powershell") or shutil.which("powershell.exe")
    if found:
        return found
    candidates = [
        Path(os.environ.get("SystemRoot", r"C:\\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe",
        Path(r"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def _endpoint_mute_com(mute: bool | None) -> bool | None:
    """Direct IAudioEndpointVolume GetMute/SetMute via ctypes (no PowerShell).

    mute is True/False to set, or None to only query. Returns current mute, or None on failure.
    """
    if not IS_WINDOWS:
        return None
    import ctypes
    from ctypes import POINTER, byref, c_int, c_void_p, cast

    class HRESULT(ctypes.c_long):
        pass

    CLSCTX_ALL = 23
    CLSID_MMDeviceEnumerator = ctypes.c_char_p  # placeholder; use GUID struct below

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    def guid(s: str) -> GUID:
        # s like 5CDF2C82-841E-4546-9722-0CF74078229A
        parts = s.split("-")
        d4 = bytes.fromhex(parts[3] + parts[4])
        g = GUID(int(parts[0], 16), int(parts[1], 16), int(parts[2], 16), (ctypes.c_ubyte * 8)(*d4))
        return g

    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)

    class IUnknown(ctypes.Structure):
        pass

    # Manual vtable calls for IMMDeviceEnumerator / IMMDevice / IAudioEndpointVolume
    IID_IAudioEndpointVolume = guid("5CDF2C82-841E-4546-9722-0CF74078229A")
    IID_IMMDeviceEnumerator = guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
    CLSID_MMDeviceEnumerator = guid("BCDE0395-E52F-467C-8E3D-C4579291692E")

    enumerator = c_void_p()
    hr = ole32.CoCreateInstance(
        byref(CLSID_MMDeviceEnumerator),
        None,
        CLSCTX_ALL,
        byref(IID_IMMDeviceEnumerator),
        byref(enumerator),
    )
    if hr:
        log.warning("CoCreateInstance MMDeviceEnumerator hr=%s", hr)
        return None

    # IMMDeviceEnumerator vtable: QueryInterface, AddRef, Release, EnumAudioEndpoints, GetDefaultAudioEndpoint
    class IMMDeviceEnumeratorVtbl(ctypes.Structure):
        _fields_ = [
            ("QueryInterface", ctypes.c_void_p),
            ("AddRef", ctypes.c_void_p),
            ("Release", ctypes.c_void_p),
            ("EnumAudioEndpoints", ctypes.c_void_p),
            ("GetDefaultAudioEndpoint", ctypes.c_void_p),
        ]

    class IMMDeviceEnumerator(ctypes.Structure):
        _fields_ = [("lpVtbl", POINTER(IMMDeviceEnumeratorVtbl))]

    enum_obj = cast(enumerator, POINTER(IMMDeviceEnumerator))
    GetDefaultAudioEndpoint = ctypes.WINFUNCTYPE(
        HRESULT, c_void_p, c_int, c_int, POINTER(c_void_p)
    )(enum_obj.contents.lpVtbl.contents.GetDefaultAudioEndpoint)

    device = c_void_p()
    # eRender=0, eMultimedia=1
    hr = GetDefaultAudioEndpoint(enum_obj, 0, 1, byref(device))
    if hr:
        log.warning("GetDefaultAudioEndpoint hr=%s", hr)
        return None

    class IMMDeviceVtbl(ctypes.Structure):
        _fields_ = [
            ("QueryInterface", ctypes.c_void_p),
            ("AddRef", ctypes.c_void_p),
            ("Release", ctypes.c_void_p),
            ("Activate", ctypes.c_void_p),
        ]

    class IMMDevice(ctypes.Structure):
        _fields_ = [("lpVtbl", POINTER(IMMDeviceVtbl))]

    dev_obj = cast(device, POINTER(IMMDevice))
    Activate = ctypes.WINFUNCTYPE(
        HRESULT, c_void_p, POINTER(GUID), c_int, c_void_p, POINTER(c_void_p)
    )(dev_obj.contents.lpVtbl.contents.Activate)

    endpoint = c_void_p()
    hr = Activate(dev_obj, byref(IID_IAudioEndpointVolume), 1, None, byref(endpoint))
    if hr:
        log.warning("Activate IAudioEndpointVolume hr=%s", hr)
        return None

    # IAudioEndpointVolume: QI,AddRef,Release, Register...,Unregister...,GetChannelCount,
    # SetMasterVolumeLevel, SetMasterVolumeLevelScalar, GetMasterVolumeLevel, GetMasterVolumeLevelScalar,
    # SetChannelVolumeLevel, SetChannelVolumeLevelScalar, GetChannelVolumeLevel, GetChannelVolumeLevelScalar,
    # SetMute, GetMute  (indices 0..14 then SetMute=15 GetMute=16)
    class IAudioEndpointVolumeVtbl(ctypes.Structure):
        _fields_ = [
            ("QueryInterface", ctypes.c_void_p),
            ("AddRef", ctypes.c_void_p),
            ("Release", ctypes.c_void_p),
            ("RegisterControlChangeNotify", ctypes.c_void_p),
            ("UnregisterControlChangeNotify", ctypes.c_void_p),
            ("GetChannelCount", ctypes.c_void_p),
            ("SetMasterVolumeLevel", ctypes.c_void_p),
            ("SetMasterVolumeLevelScalar", ctypes.c_void_p),
            ("GetMasterVolumeLevel", ctypes.c_void_p),
            ("GetMasterVolumeLevelScalar", ctypes.c_void_p),
            ("SetChannelVolumeLevel", ctypes.c_void_p),
            ("SetChannelVolumeLevelScalar", ctypes.c_void_p),
            ("GetChannelVolumeLevel", ctypes.c_void_p),
            ("GetChannelVolumeLevelScalar", ctypes.c_void_p),
            ("SetMute", ctypes.c_void_p),
            ("GetMute", ctypes.c_void_p),
        ]

    class IAudioEndpointVolume(ctypes.Structure):
        _fields_ = [("lpVtbl", POINTER(IAudioEndpointVolumeVtbl))]

    vol = cast(endpoint, POINTER(IAudioEndpointVolume))
    SetMute = ctypes.WINFUNCTYPE(
        HRESULT, c_void_p, ctypes.c_int, POINTER(GUID)
    )(vol.contents.lpVtbl.contents.SetMute)
    GetMute = ctypes.WINFUNCTYPE(
        HRESULT, c_void_p, POINTER(ctypes.c_int)
    )(vol.contents.lpVtbl.contents.GetMute)

    if mute is not None:
        hr = SetMute(vol, 1 if mute else 0, None)
        if hr:
            log.warning("SetMute hr=%s", hr)
            return None
    muted = ctypes.c_int()
    hr = GetMute(vol, byref(muted))
    if hr:
        log.warning("GetMute hr=%s", hr)
        return None
    return bool(muted.value)


def _run_mute_ps(action: str) -> str:
    if not IS_WINDOWS:
        return ""
    script = mute_ps1()
    if not script.exists():
        log.warning("set_mute.ps1 missing: %s", script)
        return ""
    exe = _powershell_exe()
    if not exe:
        log.warning("powershell.exe not found for mute action=%s", action)
        return ""
    try:
        r = subprocess.run(
            [
                exe,
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
    # Prefer in-process Core Audio — works even when PATH has no powershell.
    try:
        cur = _endpoint_mute_com(bool(mute))
        if cur is not None:
            return
    except Exception as e:
        log.warning("endpoint mute com set failed: %s", e)
    out = _run_mute_ps("on" if mute else "off")
    if out:
        return
    # Do NOT fall back to VK_VOLUME_MUTE: it toggles and can silence TTS by accident
    # when get/set via Core Audio / PowerShell both fail.
    log.warning("system mute set(%s) failed (no toggle fallback)", mute)


def get_system_mute() -> bool | None:
    if not IS_WINDOWS:
        return None
    try:
        cur = _endpoint_mute_com(None)
        if cur is not None:
            return cur
    except Exception as e:
        log.warning("endpoint mute com get failed: %s", e)
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


def should_hide_console(argv: list[str] | None = None) -> bool:
    """True when we should avoid a black console (normal kid run)."""
    if not IS_WINDOWS:
        return False
    if getattr(sys, "frozen", False):
        return False  # StudyOnPC.spec already sets console=False
    args = list(argv if argv is not None else sys.argv[1:])
    if "--console" in args:
        return False
    return sys.executable.lower().endswith("python.exe")


def reexec_without_console(argv: list[str] | None = None) -> bool:
    """If started via python.exe without --console, respawn with pythonw and exit.

    Returns True if a hidden child was spawned (caller must return immediately).
    """
    if not should_hide_console(argv):
        return False
    from pathlib import Path

    pyw = Path(sys.executable).with_name("pythonw.exe")
    if not pyw.exists():
        log.warning("pythonw.exe missing next to %s — console may stay visible", sys.executable)
        return False
    args_in = list(argv if argv is not None else sys.argv[1:])
    # Prefer launching the repo entry script so relative imports match double-click.
    entry = Path(sys.argv[0]).resolve() if sys.argv else None
    if entry and entry.suffix.lower() == ".py":
        cmd = [str(pyw), str(entry), *args_in]
        cwd = str(entry.parent)
    else:
        cmd = [str(pyw), "-m", "studyonpc.app", *args_in]
        cwd = os.getcwd()
    log.info("re-exec without console: %s", cmd)
    spawn_detached(cmd, cwd=cwd)
    return True


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
