# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Writable install dir: beside the exe when frozen, else project root."""
    if frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """Bundled read-only resources (PyInstaller _MEIPASS when frozen)."""
    if frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_DIR = app_dir()
RESOURCE_ROOT = resource_dir()
# Back-compat: most writable paths hang off ROOT (= APP_DIR)
ROOT = APP_DIR

CONFIG_PATH = APP_DIR / "config.json"
DATA_DIR = APP_DIR / "data"
BANKS_DIR = DATA_DIR / "banks"
STATE_PATH = DATA_DIR / "state.json"
LOG_DIR = APP_DIR / "logs"
ANSWER_LOG = LOG_DIR / "answers.log"
APP_LOG = LOG_DIR / "app.log"
MAIN_PID = LOG_DIR / "main.pid"
WATCH_PID = LOG_DIR / "watchdog.pid"
STOP_FLAG = LOG_DIR / "stop.flag"
FORCE_QUIZ_FLAG = LOG_DIR / "force_quiz.flag"
SCRIPTS_DIR = APP_DIR / "scripts"
ASSETS_DIR = APP_DIR / "assets"


def _first_existing(*candidates: Path) -> Path | None:
    for p in candidates:
        if p is not None and p.exists():
            return p
    return None


def mute_ps1() -> Path:
    found = _first_existing(
        APP_DIR / "scripts" / "set_mute.ps1",
        RESOURCE_ROOT / "scripts" / "set_mute.ps1",
    )
    return found or (APP_DIR / "scripts" / "set_mute.ps1")


MUTE_PS1 = mute_ps1()  # refreshed in ensure_runtime_dirs


def resource_file(*parts: str) -> Path:
    """Prefer a file beside the exe; fall back to the bundled copy."""
    local = APP_DIR.joinpath(*parts)
    bundled = RESOURCE_ROOT.joinpath(*parts)
    if local.exists():
        return local
    return bundled


def _copy_tree_if_missing(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.mkdir(parents=True, exist_ok=True)
    if src.is_file():
        if not dst.exists():
            shutil.copy2(src, dst)
        return
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            if not target.exists():
                shutil.copytree(item, target)
        elif not target.exists():
            shutil.copy2(item, target)


def ensure_runtime_dirs() -> None:
    """Create writable dirs and seed defaults from the frozen bundle if needed."""
    global MUTE_PS1
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BANKS_DIR.mkdir(parents=True, exist_ok=True)
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    # Seed config.json beside exe (prefer bundled config.json, else example)
    if not CONFIG_PATH.exists():
        for name in ("config.json", "config.example.json"):
            bundled = RESOURCE_ROOT / name
            if bundled.exists():
                shutil.copy2(bundled, CONFIG_PATH)
                break

    # Seed question banks
    bundled_banks = RESOURCE_ROOT / "data" / "banks"
    if bundled_banks.exists():
        _copy_tree_if_missing(bundled_banks, BANKS_DIR)

    # Seed assets (images)
    bundled_assets = RESOURCE_ROOT / "assets"
    if bundled_assets.exists():
        _copy_tree_if_missing(bundled_assets, ASSETS_DIR)

    # Seed mute script
    bundled_mute = RESOURCE_ROOT / "scripts" / "set_mute.ps1"
    local_mute = SCRIPTS_DIR / "set_mute.ps1"
    if bundled_mute.exists() and not local_mute.exists():
        shutil.copy2(bundled_mute, local_mute)

    MUTE_PS1 = mute_ps1()
