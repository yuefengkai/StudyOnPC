# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import threading
from copy import deepcopy
from datetime import date, datetime
from typing import Any

from .paths import STATE_PATH, ensure_runtime_dirs
from .singleton import atomic_write_text

log = logging.getLogger("studyonpc.state")

_lock = threading.RLock()

DEFAULT_STATE: dict[str, Any] = {
    "balance_minutes": 0.0,
    "daily_used_minutes": 0.0,
    "daily_date": "",  # YYYY-MM-DD local
    "wrong_streak": 0,
    "pending_extra": 0,
    "recent_ids": [],
    "quiz_active": False,
    "running_since": "",
    "today_unlock_minutes": 0.0,
    "today_bonus_minutes": 0.0,
    "site_daily_used": {},
}


def _today_str() -> str:
    return date.today().isoformat()


def default_state() -> dict[str, Any]:
    st = deepcopy(DEFAULT_STATE)
    st["daily_date"] = _today_str()
    return st


def load_state() -> dict[str, Any]:
    ensure_runtime_dirs()
    with _lock:
        st = default_state()
        try:
            raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                st.update(raw)
        except FileNotFoundError:
            pass
        except Exception as e:
            log.warning("state load failed: %s", e)
        _rollover_daily(st)
        return st


def save_state(st: dict[str, Any]) -> None:
    ensure_runtime_dirs()
    with _lock:
        _rollover_daily(st)
        payload = {
            "balance_minutes": float(st.get("balance_minutes", 0.0)),
            "daily_used_minutes": float(st.get("daily_used_minutes", 0.0)),
            "daily_date": str(st.get("daily_date") or _today_str()),
            "wrong_streak": int(st.get("wrong_streak", 0)),
            "pending_extra": int(st.get("pending_extra", 0)),
            "recent_ids": list(st.get("recent_ids") or [])[-32:],
            "quiz_active": bool(st.get("quiz_active", False)),
            "running_since": str(st.get("running_since") or ""),
            "today_unlock_minutes": float(st.get("today_unlock_minutes", 0.0)),
            "today_bonus_minutes": float(st.get("today_bonus_minutes", 0.0)),
            "site_daily_used": dict(st.get("site_daily_used") or {}),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        atomic_write_text(
            STATE_PATH,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )
        st.update(payload)


def _rollover_daily(st: dict[str, Any]) -> None:
    today = _today_str()
    if st.get("daily_date") != today:
        prev = str(st.get("daily_date") or "")
        if prev:
            try:
                from . import usage_stats
                usage_stats.archive_day_from_state(prev, st)
            except Exception as e:
                log.warning("usage archive on rollover: %s", e)
        st["daily_date"] = today
        st["daily_used_minutes"] = 0.0
        st["today_unlock_minutes"] = 0.0
        st["today_bonus_minutes"] = 0.0
        st["site_daily_used"] = {}
