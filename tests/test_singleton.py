# -*- coding: utf-8 -*-
"""Single-instance mutex, atomic pid writes, spawn-skip, and cooldown."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from studyonpc import singleton, watchdog
from studyonpc import state as state_mod
from studyonpc import win_yt


@pytest.fixture(autouse=True)
def _reset_singleton():
    singleton.set_mutex_backend(None)
    singleton.set_list_processes_backend(None)
    singleton.release_held_mutexes_for_tests()
    singleton.reset_spawn_gates_for_tests()
    yield
    singleton.set_mutex_backend(None)
    singleton.set_list_processes_backend(None)
    singleton.release_held_mutexes_for_tests()
    singleton.reset_spawn_gates_for_tests()


def test_mutex_names_are_stable():
    assert singleton.MUTEX_MAIN == "Global\\StudyOnPC-main"
    assert singleton.MUTEX_WATCHDOG == "Global\\StudyOnPC-watchdog"
    assert singleton.MUTEX_NAMES["main"] == singleton.MUTEX_MAIN
    assert singleton.MUTEX_NAMES["watchdog"] == singleton.MUTEX_WATCHDOG


def test_mutex_backend_second_instance_exits():
    held: set[str] = set()

    def backend(role: str, name: str) -> bool:
        assert name == singleton.MUTEX_NAMES[role]
        if role in held:
            return False
        held.add(role)
        return True

    singleton.set_mutex_backend(backend)
    assert singleton.acquire_role_mutex("main") is True
    # Same process already holds it.
    assert singleton.acquire_role_mutex("main") is True
    # Simulate another process of the same role.
    singleton._held_mutexes.clear()
    assert singleton.acquire_role_mutex("main") is False
    # Watchdog mutex is independent.
    assert singleton.acquire_role_mutex("watchdog") is True


def test_posix_lock_exclusive(tmp_path, monkeypatch):
    import studyonpc.paths as paths

    monkeypatch.setattr(paths, "LOG_DIR", tmp_path)
    monkeypatch.setattr(paths, "ensure_runtime_dirs", lambda: tmp_path.mkdir(parents=True, exist_ok=True))
    assert singleton.acquire_role_mutex("main") is True
    fd = singleton._held_mutexes["main"]
    assert isinstance(fd, int)
    # Pretend we are a second process still seeing the first lock.
    singleton._held_mutexes.clear()
    assert singleton.acquire_role_mutex("main") is False
    os.close(fd)


def test_read_pid_treats_empty_and_partial_as_invalid(tmp_path):
    path = tmp_path / "main.pid"
    assert watchdog.read_pid(path) is None
    path.write_text("", encoding="utf-8")
    assert watchdog.read_pid(path) is None
    path.write_text("   \n", encoding="utf-8")
    assert watchdog.read_pid(path) is None
    path.write_text("abc", encoding="utf-8")
    assert watchdog.read_pid(path) is None
    path.write_text("12x", encoding="utf-8")
    assert watchdog.read_pid(path) is None
    path.write_text("0", encoding="utf-8")
    assert watchdog.read_pid(path) is None
    path.write_text("  26584\n", encoding="utf-8")
    assert watchdog.read_pid(path) == 26584


def test_write_pid_is_atomic_replace(tmp_path, monkeypatch):
    target = tmp_path / "main.pid"
    target.write_text("11111", encoding="utf-8")
    real_replace = os.replace
    seen: dict[str, str] = {}

    def wrapped(src, dst):
        seen["before"] = Path(dst).read_text(encoding="utf-8")
        seen["tmp"] = Path(src).read_text(encoding="utf-8")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", wrapped)
    watchdog.write_pid(target, pid=22222)
    assert seen["before"] == "11111"
    assert seen["tmp"].strip() == "22222"
    assert target.read_text(encoding="utf-8").strip() == "22222"
    # Destination is never emptied before replace.
    assert seen["before"] != ""


def test_atomic_write_cleans_tmp_on_replace_failure(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    target.write_text("keep-me", encoding="utf-8")

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        singleton.atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "keep-me"
    leftovers = list(tmp_path.glob("state.json*.tmp"))
    assert leftovers == []


def test_cmdline_matches_role():
    watch = r'"D:\anaconda3\pythonw.exe" "E:\Code\Brook\StudyOnPC\studyonpc.py" --role=watchdog'
    main = r'"D:\anaconda3\pythonw.exe" "E:\Code\Brook\StudyOnPC\studyonpc.py" --role=main'
    default = r'"D:\anaconda3\pythonw.exe" "E:\Code\Brook\StudyOnPC\studyonpc.py"'
    frozen = r"E:\Code\Brook\StudyOnPC\StudyOnPC.exe --role=main"
    flag = r'"D:\anaconda3\pythonw.exe" "E:\Code\Brook\StudyOnPC\studyonpc.py" --watchdog'
    other = r"python tests\test_studyonpc.py --role=main"
    assert singleton.cmdline_matches_role(watch, "watchdog")
    assert not singleton.cmdline_matches_role(watch, "main")
    assert singleton.cmdline_matches_role(main, "main")
    assert not singleton.cmdline_matches_role(main, "watchdog")
    assert singleton.cmdline_matches_role(default, "main")
    assert not singleton.cmdline_matches_role(default, "watchdog")
    assert singleton.cmdline_matches_role(frozen, "main")
    assert singleton.cmdline_matches_role(flag, "watchdog")
    assert not singleton.cmdline_matches_role(other, "main")
    assert not singleton.cmdline_matches_role("", "main")
    # --role=main must not match --role=main2
    assert not singleton.cmdline_matches_role(
        r"pythonw studyonpc.py --role=main2", "main"
    )


def test_ensure_peer_skips_spawn_when_live_process_exists(tmp_path, monkeypatch):
    singleton.set_list_processes_backend(
        lambda: [
            (
                9999,
                r'"D:\anaconda3\pythonw.exe" "E:\Code\Brook\StudyOnPC\studyonpc.py" --role=main',
            )
        ]
    )
    spawned: list[str] = []
    monkeypatch.setattr(watchdog, "spawn_role", lambda role: spawned.append(role))
    monkeypatch.setattr(win_yt, "pid_alive", lambda pid: False)
    pid_file = tmp_path / "main.pid"
    pid_file.write_text("", encoding="utf-8")  # empty — previously treated as dead
    watchdog.ensure_peer("main", pid_file)
    assert spawned == []


def test_ensure_peer_spawns_when_peer_is_gone(tmp_path, monkeypatch):
    singleton.set_list_processes_backend(lambda: [])
    spawned: list[str] = []
    monkeypatch.setattr(watchdog, "spawn_role", lambda role: spawned.append(role) or True)
    monkeypatch.setattr(win_yt, "pid_alive", lambda pid: False)
    pid_file = tmp_path / "main.pid"
    watchdog.ensure_peer("main", pid_file)
    assert spawned == ["main"]


def test_ensure_peer_skips_when_pid_file_alive(tmp_path, monkeypatch):
    singleton.set_list_processes_backend(lambda: [])
    spawned: list[str] = []
    monkeypatch.setattr(watchdog, "spawn_role", lambda role: spawned.append(role))
    monkeypatch.setattr(win_yt, "pid_alive", lambda pid: pid == 26584)
    pid_file = tmp_path / "main.pid"
    pid_file.write_text("26584", encoding="utf-8")
    watchdog.ensure_peer("main", pid_file)
    assert spawned == []


def test_spawn_cooldown_after_pagefile_error(caplog):
    import logging

    caplog.set_level(logging.WARNING, logger="studyonpc.singleton")
    err = OSError(8, "Not enough storage is available to process this command")
    err.winerror = 1455
    singleton.note_spawn_failure("main", err, now=1000.0)
    assert singleton.spawn_allowed("main", now=1010.0) is False
    assert singleton.spawn_allowed("main", now=1010.0) is False
    skipped = [r for r in caplog.records if "spawn main skipped" in r.getMessage()]
    assert len(skipped) == 1
    # Still blocked just before the 60s resource cooldown ends.
    assert singleton.spawn_allowed("main", now=1059.9) is False
    assert singleton.spawn_allowed("main", now=1060.1) is True


def test_spawn_cooldown_does_not_retry_thousands_of_times():
    err = OSError(8, "page file")
    err.winerror = 1455
    now = 0.0
    attempts = 0
    # Simulate a watchdog looping every 3s for an hour.
    t = 0.0
    while t < 3600.0:
        if singleton.spawn_allowed("main", now=t):
            attempts += 1
            singleton.note_spawn_failure("main", err, now=t)
        t += 3.0
    # Exponential backoff 60, 120, 240, 300... must be far below thousands.
    assert attempts <= 20
    assert attempts >= 4


def test_min_interval_after_successful_spawn():
    singleton.note_spawn_success("watchdog", now=100.0)
    assert singleton.spawn_allowed("watchdog", now=110.0) is False
    assert singleton.spawn_allowed("watchdog", now=115.1) is True


def test_save_state_uses_atomic_replace(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(state_mod, "ensure_runtime_dirs", lambda: None)
    # Avoid rollover calling usage_stats.
    st = state_mod.default_state()
    real_replace = os.replace
    seen: dict[str, str] = {}

    def wrapped(src, dst):
        if Path(dst).exists():
            seen["before"] = Path(dst).read_text(encoding="utf-8")
        else:
            seen["before"] = None
        seen["tmp"] = Path(src).read_text(encoding="utf-8")
        return real_replace(src, dst)

    (tmp_path / "state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(os, "replace", wrapped)
    state_mod.save_state(st)
    assert seen["before"] == "{}"
    assert "balance_minutes" in seen["tmp"]
    assert (tmp_path / "state.json").read_text(encoding="utf-8").startswith("{")
