# -*- coding: utf-8 -*-
"""Unlock-balance / daily-cap / quiz-set rules (platform-agnostic)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RulesConfig:
    unlock_minutes_per_set: float = 10.0
    questions_per_set: int = 3
    pass_ratio: float = 0.67
    daily_max_watch_minutes: float = 60.0
    wrong_streak_to_extra: int = 3
    extra_questions: int = 1
    answer_delay_seconds: float = 5.0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RulesConfig":
        return cls(
            unlock_minutes_per_set=float(d.get("unlock_minutes_per_set", 10)),
            questions_per_set=max(1, int(d.get("questions_per_set", 3))),
            pass_ratio=float(d.get("pass_ratio", 0.67)),
            daily_max_watch_minutes=float(d.get("daily_max_watch_minutes", 60)),
            wrong_streak_to_extra=max(1, int(d.get("wrong_streak_to_extra", 3))),
            extra_questions=max(0, int(d.get("extra_questions", 1))),
            answer_delay_seconds=max(0.0, float(d.get("answer_delay_seconds", 5))),
        )

    @classmethod
    def from_site(cls, site: dict[str, Any], global_cfg: dict[str, Any] | None = None) -> "RulesConfig":
        """Build rules for the active site, inheriting global streak/delay settings."""
        g = global_cfg or {}
        return cls(
            unlock_minutes_per_set=float(site.get("unlock_minutes_per_set", g.get("unlock_minutes_per_set", 10))),
            questions_per_set=max(1, int(site.get("questions_per_set", g.get("questions_per_set", 3)))),
            pass_ratio=float(site.get("pass_ratio", g.get("pass_ratio", 0.6667))),
            daily_max_watch_minutes=float(site.get("daily_max_minutes", g.get("daily_max_watch_minutes", 60))),
            wrong_streak_to_extra=max(1, int(g.get("wrong_streak_to_extra", 3))),
            extra_questions=max(0, int(g.get("extra_questions", 1))),
            answer_delay_seconds=max(0.0, float(g.get("answer_delay_seconds", 5))),
        )


def _site_used_map(st: dict[str, Any]) -> dict[str, float]:
    raw = st.get("site_daily_used") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = float(v)
        except Exception:
            continue
    return out


def site_daily_used(st: dict[str, Any], site_id: str) -> float:
    return float(_site_used_map(st).get(site_id, 0.0))


def today_bonus_minutes(st: dict[str, Any]) -> float:
    """Parent-granted extra watch allowance for today (raises effective daily cap)."""
    try:
        return max(0.0, float(st.get("today_bonus_minutes", 0.0) or 0.0))
    except Exception:
        return 0.0


def remaining_daily(st: dict[str, Any], cfg: RulesConfig, site_id: str | None = None) -> float:
    if site_id:
        used = site_daily_used(st, site_id)
    else:
        used = float(st.get("daily_used_minutes", 0.0))
    # Manual 今日加时 raises the effective daily cap so watching can continue past daily_max.
    return max(0.0, cfg.daily_max_watch_minutes + today_bonus_minutes(st) - used)


def can_watch(st: dict[str, Any], cfg: RulesConfig, site_id: str | None = None) -> bool:
    bal = float(st.get("balance_minutes", 0.0))
    return bal > 0.0 and remaining_daily(st, cfg, site_id) > 0.0


def needs_quiz(st: dict[str, Any], cfg: RulesConfig, site_id: str | None = None) -> bool:
    """True when shared balance is empty OR this site's daily max is hit."""
    if float(st.get("balance_minutes", 0.0)) <= 0.0:
        return True
    if remaining_daily(st, cfg, site_id) <= 0.0:
        return True
    return False


def consume_watch(
    st: dict[str, Any],
    cfg: RulesConfig,
    dt_minutes: float,
    site_id: str | None = None,
) -> float:
    """Consume from shared balance; track per-site daily used when site_id given."""
    if dt_minutes <= 0:
        return 0.0
    if not can_watch(st, cfg, site_id):
        return 0.0
    bal = float(st.get("balance_minutes", 0.0))
    rem = remaining_daily(st, cfg, site_id)
    take = min(dt_minutes, bal, rem)
    st["balance_minutes"] = bal - take
    st["daily_used_minutes"] = float(st.get("daily_used_minutes", 0.0)) + take
    if site_id:
        used_map = _site_used_map(st)
        used_map[site_id] = float(used_map.get(site_id, 0.0)) + take
        st["site_daily_used"] = used_map
    return take


def set_size(st: dict[str, Any], cfg: RulesConfig) -> int:
    base = cfg.questions_per_set
    extra = int(st.get("pending_extra", 0) or 0)
    return max(1, base + extra)


def required_correct(n_questions: int, cfg: RulesConfig) -> int:
    if n_questions <= 0:
        return 0
    ratio = float(cfg.pass_ratio)
    if ratio <= 0:
        return 0
    if ratio >= 1:
        return n_questions
    for k in range(0, n_questions + 1):
        if (k / n_questions) + 0.005 >= ratio:
            return max(1, k)
    return n_questions


def passed_set(correct: int, n_questions: int, cfg: RulesConfig) -> bool:
    if n_questions <= 0:
        return False
    return correct >= required_correct(n_questions, cfg)


def record_answer(st: dict[str, Any], cfg: RulesConfig, correct: bool) -> None:
    if correct:
        st["wrong_streak"] = 0
        return
    streak = int(st.get("wrong_streak", 0)) + 1
    st["wrong_streak"] = streak
    if streak >= cfg.wrong_streak_to_extra:
        st["pending_extra"] = int(st.get("pending_extra", 0)) + cfg.extra_questions
        st["wrong_streak"] = 0


def grant_unlock(st: dict[str, Any], cfg: RulesConfig, site_id: str | None = None) -> float:
    """Credit shared balance using active site's unlock, capped by that site's remaining daily."""
    rem = remaining_daily(st, cfg, site_id)
    grant = min(float(cfg.unlock_minutes_per_set), rem)
    st["balance_minutes"] = float(st.get("balance_minutes", 0.0)) + grant
    st["today_unlock_minutes"] = float(st.get("today_unlock_minutes", 0.0)) + grant
    st["pending_extra"] = 0
    st["wrong_streak"] = 0
    return grant


def add_bonus_minutes(st: dict[str, Any], minutes: float) -> float:
    """Parent '今日加时' — credit shared balance AND raise today's effective daily cap.

    Quiz unlocks stay capped by remaining daily room. After the kid hits daily_max,
    only this path still lets them keep watching: balance alone was not enough because
    can_watch/consume_watch also require remaining_daily > 0.
    """
    m = max(0.0, float(minutes))
    if m <= 0:
        return 0.0
    st["balance_minutes"] = float(st.get("balance_minutes", 0.0)) + m
    st["today_bonus_minutes"] = today_bonus_minutes(st) + m
    return m


DEFAULT_CHALLENGE_QUESTIONS = 5
DEFAULT_CHALLENGE_REWARD_MINUTES = 10.0


def challenge_questions(cfg_or_dict: RulesConfig | dict | None = None) -> int:
    """大闯关固定题数（默认 5，不受普通组 questions_per_set / pending_extra 影响）。"""
    if isinstance(cfg_or_dict, dict):
        return max(1, int(cfg_or_dict.get("challenge_questions", DEFAULT_CHALLENGE_QUESTIONS)))
    return DEFAULT_CHALLENGE_QUESTIONS


def challenge_reward_minutes(cfg_or_dict: RulesConfig | dict | None = None) -> float:
    """大闯关过关奖励分钟（默认 10），走加时通道抬高今日有效上限。"""
    if isinstance(cfg_or_dict, dict):
        return max(0.0, float(cfg_or_dict.get("challenge_reward_minutes", DEFAULT_CHALLENGE_REWARD_MINUTES)))
    return float(DEFAULT_CHALLENGE_REWARD_MINUTES)


def should_use_challenge(st: dict[str, Any], cfg: RulesConfig, site_id: str | None = None) -> bool:
    """True when today's effective daily room is exhausted — kid must 大闯关 (or parent 加时)."""
    return remaining_daily(st, cfg, site_id) <= 0.0


def grant_challenge_reward(st: dict[str, Any], minutes: float | None = None) -> float:
    """Credit 大闯关 reward via add_bonus_minutes (balance + today_bonus)."""
    reward = DEFAULT_CHALLENGE_REWARD_MINUTES if minutes is None else max(0.0, float(minutes))
    added = add_bonus_minutes(st, reward)
    st["pending_extra"] = 0
    st["wrong_streak"] = 0
    return added


def status_snapshot(
    st: dict[str, Any],
    cfg: RulesConfig,
    *,
    sites: list[dict[str, Any]] | None = None,
    active_site_id: str | None = None,
) -> dict[str, Any]:
    bal = float(st.get("balance_minutes", 0.0))
    used = float(st.get("daily_used_minutes", 0.0))
    bonus = today_bonus_minutes(st)
    rem = remaining_daily(st, cfg, active_site_id)
    site_used = _site_used_map(st)
    site_rows = []
    for s in sites or []:
        sid = str(s.get("id") or "")
        smax = float(s.get("daily_max_minutes", cfg.daily_max_watch_minutes))
        su = float(site_used.get(sid, 0.0))
        site_rows.append(
            {
                "id": sid,
                "name": s.get("name") or sid,
                "enabled": bool(s.get("enabled", True)),
                "daily_used_minutes": round(su, 2),
                "daily_max_minutes": smax,
                "daily_remaining_minutes": round(max(0.0, smax + bonus - su), 2),
                "keywords": list(s.get("keywords") or []),
            }
        )
    return {
        "balance_minutes": round(bal, 2),
        "daily_used_minutes": round(used, 2),
        "daily_remaining_minutes": round(rem, 2),
        "daily_max_watch_minutes": cfg.daily_max_watch_minutes,
        "today_bonus_minutes": round(bonus, 2),
        "effective_daily_max_minutes": round(cfg.daily_max_watch_minutes + bonus, 2),
        "daily_date": st.get("daily_date", ""),
        "pending_extra": int(st.get("pending_extra", 0)),
        "wrong_streak": int(st.get("wrong_streak", 0)),
        "needs_quiz": needs_quiz(st, cfg, active_site_id),
        "can_watch": can_watch(st, cfg, active_site_id),
        "quiz_active": bool(st.get("quiz_active", False)),
        "questions_per_set": set_size(st, cfg),
        "unlock_minutes_per_set": cfg.unlock_minutes_per_set,
        "pass_ratio": cfg.pass_ratio,
        "today_unlock_minutes": round(float(st.get("today_unlock_minutes", 0.0)), 2),
        "challenge_questions": DEFAULT_CHALLENGE_QUESTIONS,
        "challenge_reward_minutes": DEFAULT_CHALLENGE_REWARD_MINUTES,
        "should_challenge": should_use_challenge(st, cfg, active_site_id),
        "running_since": st.get("running_since", ""),
        "active_site_id": active_site_id or "",
        "sites": site_rows,
        "site_daily_used": {k: round(v, 2) for k, v in site_used.items()},
    }
