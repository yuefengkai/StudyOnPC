# -*- coding: utf-8 -*-
"""Unlock-balance / daily-cap / quiz-set rules (platform-agnostic)."""
from __future__ import annotations

import math
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


def remaining_daily(st: dict[str, Any], cfg: RulesConfig) -> float:
    used = float(st.get("daily_used_minutes", 0.0))
    return max(0.0, cfg.daily_max_watch_minutes - used)


def can_watch(st: dict[str, Any], cfg: RulesConfig) -> bool:
    bal = float(st.get("balance_minutes", 0.0))
    return bal > 0.0 and remaining_daily(st, cfg) > 0.0


def needs_quiz(st: dict[str, Any], cfg: RulesConfig) -> bool:
    """True when kid cannot consume more watch time."""
    if float(st.get("balance_minutes", 0.0)) <= 0.0:
        return True
    if remaining_daily(st, cfg) <= 0.0:
        return True
    return False


def consume_watch(st: dict[str, Any], cfg: RulesConfig, dt_minutes: float) -> float:
    """Consume up to dt_minutes from balance (and daily). Returns minutes actually consumed."""
    if dt_minutes <= 0:
        return 0.0
    if not can_watch(st, cfg):
        return 0.0
    bal = float(st.get("balance_minutes", 0.0))
    rem = remaining_daily(st, cfg)
    take = min(dt_minutes, bal, rem)
    st["balance_minutes"] = bal - take
    st["daily_used_minutes"] = float(st.get("daily_used_minutes", 0.0)) + take
    return take


def set_size(st: dict[str, Any], cfg: RulesConfig) -> int:
    base = cfg.questions_per_set
    extra = int(st.get("pending_extra", 0) or 0)
    return max(1, base + extra)


def required_correct(n_questions: int, cfg: RulesConfig) -> int:
    """Minimum correct answers to pass a set of n questions.

    Finds the smallest k such that k/n >= pass_ratio (float-tolerant).
    Default pass_ratio≈2/3 → 2 of 3. Note: literal 0.67 is slightly above 2/3,
    so config default uses 0.6667.
    """
    if n_questions <= 0:
        return 0
    ratio = float(cfg.pass_ratio)
    if ratio <= 0:
        return 0
    if ratio >= 1:
        return n_questions
    # 0.005 slack so config 0.67 / 0.6667 both mean "2 of 3"
    for k in range(0, n_questions + 1):
        if (k / n_questions) + 0.005 >= ratio:
            return max(1, k)
    return n_questions


def passed_set(correct: int, n_questions: int, cfg: RulesConfig) -> bool:
    if n_questions <= 0:
        return False
    return correct >= required_correct(n_questions, cfg)


def record_answer(st: dict[str, Any], cfg: RulesConfig, correct: bool) -> None:
    """Update wrong streak / pending make-up after one question."""
    if correct:
        st["wrong_streak"] = 0
        return
    streak = int(st.get("wrong_streak", 0)) + 1
    st["wrong_streak"] = streak
    if streak >= cfg.wrong_streak_to_extra:
        st["pending_extra"] = int(st.get("pending_extra", 0)) + cfg.extra_questions
        st["wrong_streak"] = 0


def grant_unlock(st: dict[str, Any], cfg: RulesConfig) -> float:
    """On passed set: clear make-up, add unlock minutes capped by remaining daily room
    (balance may exceed remaining so kid can sit with leftover after daily resets tomorrow —
    but we cap the *grant* by remaining daily so they cannot bank past today's cap via quizzes).

    Spec: "add unlock_minutes (capped by remaining daily max)".
    Interpret remaining as: how many more watch minutes are allowed today.
    Grant min(unlock, remaining_daily) so quiz cannot push usable-today beyond the cap.
    Balance itself stores granted minutes; consume still respects daily cap.
    """
    rem = remaining_daily(st, cfg)
    grant = min(float(cfg.unlock_minutes_per_set), rem)
    # If rem is 0 (daily cap hit), grant 0 — kid already can't watch; still clear make-up
    # so they don't accumulate infinite extras overnight. Balance stays as-is.
    st["balance_minutes"] = float(st.get("balance_minutes", 0.0)) + grant
    st["today_unlock_minutes"] = float(st.get("today_unlock_minutes", 0.0)) + grant
    st["pending_extra"] = 0
    st["wrong_streak"] = 0
    return grant


def status_snapshot(st: dict[str, Any], cfg: RulesConfig) -> dict[str, Any]:
    bal = float(st.get("balance_minutes", 0.0))
    used = float(st.get("daily_used_minutes", 0.0))
    rem = remaining_daily(st, cfg)
    return {
        "balance_minutes": round(bal, 2),
        "daily_used_minutes": round(used, 2),
        "daily_remaining_minutes": round(rem, 2),
        "daily_max_watch_minutes": cfg.daily_max_watch_minutes,
        "daily_date": st.get("daily_date", ""),
        "pending_extra": int(st.get("pending_extra", 0)),
        "wrong_streak": int(st.get("wrong_streak", 0)),
        "needs_quiz": needs_quiz(st, cfg),
        "can_watch": can_watch(st, cfg),
        "quiz_active": bool(st.get("quiz_active", False)),
        "questions_per_set": set_size(st, cfg),
        "unlock_minutes_per_set": cfg.unlock_minutes_per_set,
        "pass_ratio": cfg.pass_ratio,
        "today_unlock_minutes": round(float(st.get("today_unlock_minutes", 0.0)), 2),
        "running_since": st.get("running_since", ""),
    }
