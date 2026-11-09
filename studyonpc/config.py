# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
from copy import deepcopy
from typing import Any

from .paths import CONFIG_PATH, ROOT, ensure_runtime_dirs
from .sites import migrate_sites
from .tts import DEFAULT_TTS, normalize_tts

log = logging.getLogger("studyonpc.config")
LOCAL_CONFIG_PATH = ROOT / "config.local.json"

DEFAULTS: dict[str, Any] = {
    "parent_pin": "changeme",
    "admin_password": "changeme",
    "unlock_minutes_per_set": 5,
    "questions_per_set": 3,
    "pass_ratio": 0.6667,
    "daily_max_watch_minutes": 60,
    "challenge_questions": 5,
    "challenge_reward_minutes": 10,
    "wrong_streak_to_extra": 3,
    "extra_questions": 1,
    "poll_ms": 2500,
    "admin_port": 8099,
    "admin_bind": "0.0.0.0",
    "youtube_keywords": ["youtube", "youtu.be"],
    "sites": [],
    "tts": dict(DEFAULT_TTS),
    "bank_file": "data/banks/grade1-shenzhen.json",
    "challenge_bank_file": "data/banks/grade2-challenge.json",
    "task_name": "StudyOnPC",
    "answer_delay_seconds": 5,
}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> None:
    """Merge overlay into base in-place; nested dicts merge, other values replace."""
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def load_config() -> dict[str, Any]:
    ensure_runtime_dirs()
    cfg = deepcopy(DEFAULTS)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            cfg.update(data)
    except FileNotFoundError:
        log.warning("config missing, using defaults")
    except Exception as e:
        log.warning("config load failed: %s", e)
    # Optional local secrets overlay (gitignored). Survives sync that rewrites config.json
    # without api_key / pins. Prefer config.local.json for TTS api_key.
    try:
        if LOCAL_CONFIG_PATH.is_file():
            local = json.loads(LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(local, dict):
                _deep_merge(cfg, local)
                log.info("merged config.local.json")
    except Exception as e:
        log.warning("config.local.json load failed: %s", e)
    migrate_sites(cfg)
    normalize_tts(cfg)
    cfg["parent_pin"] = str(cfg.get("parent_pin", "changeme"))
    cfg["admin_password"] = str(cfg.get("admin_password") or cfg["parent_pin"])
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    ensure_runtime_dirs()
    migrate_sites(cfg)
    normalize_tts(cfg)
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
