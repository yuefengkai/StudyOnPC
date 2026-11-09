# -*- coding: utf-8 -*-
"""Rules engine unit tests (Linux-safe)."""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studyonpc.rules import (  # noqa: E402
    RulesConfig,
    add_bonus_minutes,
    can_watch,
    challenge_questions,
    consume_watch,
    grant_challenge_reward,
    grant_unlock,
    needs_quiz,
    passed_set,
    record_answer,
    remaining_daily,
    required_correct,
    set_size,
    should_use_challenge,
    status_snapshot,
)
from studyonpc.state import default_state  # noqa: E402


class TestRules(unittest.TestCase):
    def setUp(self):
        self.cfg = RulesConfig(
            unlock_minutes_per_set=10,
            questions_per_set=3,
            pass_ratio=0.6667,
            daily_max_watch_minutes=60,
            wrong_streak_to_extra=3,
            extra_questions=1,
        )

    def test_fresh_install_needs_quiz(self):
        st = default_state()
        self.assertEqual(st["balance_minutes"], 0.0)
        self.assertTrue(needs_quiz(st, self.cfg))
        self.assertFalse(can_watch(st, self.cfg))

    def test_required_correct_two_of_three(self):
        self.assertEqual(required_correct(3, self.cfg), 2)
        self.assertTrue(passed_set(2, 3, self.cfg))
        self.assertFalse(passed_set(1, 3, self.cfg))

    def test_consume_and_cap(self):
        st = default_state()
        st["balance_minutes"] = 15.0
        used = consume_watch(st, self.cfg, 5.0)
        self.assertAlmostEqual(used, 5.0)
        self.assertAlmostEqual(st["balance_minutes"], 10.0)
        self.assertAlmostEqual(st["daily_used_minutes"], 5.0)
        # burn remaining daily
        st["daily_used_minutes"] = 58.0
        st["balance_minutes"] = 20.0
        used = consume_watch(st, self.cfg, 10.0)
        self.assertAlmostEqual(used, 2.0)
        self.assertTrue(needs_quiz(st, self.cfg))

    def test_grant_capped_by_daily_remaining(self):
        st = default_state()
        st["daily_used_minutes"] = 55.0
        grant = grant_unlock(st, self.cfg)
        self.assertAlmostEqual(grant, 5.0)
        self.assertAlmostEqual(st["balance_minutes"], 5.0)
        self.assertEqual(st["pending_extra"], 0)

    def test_wrong_streak_adds_extra(self):
        st = default_state()
        record_answer(st, self.cfg, False)
        record_answer(st, self.cfg, False)
        self.assertEqual(st["pending_extra"], 0)
        record_answer(st, self.cfg, False)
        self.assertEqual(st["pending_extra"], 1)
        self.assertEqual(set_size(st, self.cfg), 4)
        # pass clears
        grant_unlock(st, self.cfg)
        self.assertEqual(st["pending_extra"], 0)

    def test_status_snapshot(self):
        st = default_state()
        st["balance_minutes"] = 8
        snap = status_snapshot(st, self.cfg)
        self.assertEqual(snap["balance_minutes"], 8)
        self.assertTrue(snap["can_watch"])
        self.assertFalse(snap["needs_quiz"])

    def test_bonus_allows_watch_past_daily_max(self):
        """After daily_max is hit, parent 加时 must raise effective cap so watching resumes."""
        st = default_state()
        st["daily_used_minutes"] = 60.0
        st["balance_minutes"] = 0.0
        self.assertFalse(can_watch(st, self.cfg))
        self.assertTrue(needs_quiz(st, self.cfg))
        self.assertAlmostEqual(remaining_daily(st, self.cfg), 0.0)

        added = add_bonus_minutes(st, 10.0)
        self.assertAlmostEqual(added, 10.0)
        self.assertAlmostEqual(st["balance_minutes"], 10.0)
        self.assertAlmostEqual(st["today_bonus_minutes"], 10.0)
        self.assertAlmostEqual(remaining_daily(st, self.cfg), 10.0)
        self.assertTrue(can_watch(st, self.cfg))
        self.assertFalse(needs_quiz(st, self.cfg))

        used = consume_watch(st, self.cfg, 4.0)
        self.assertAlmostEqual(used, 4.0)
        self.assertAlmostEqual(st["balance_minutes"], 6.0)
        self.assertAlmostEqual(st["daily_used_minutes"], 64.0)
        self.assertAlmostEqual(remaining_daily(st, self.cfg), 6.0)

        snap = status_snapshot(st, self.cfg)
        self.assertAlmostEqual(snap["today_bonus_minutes"], 10.0)
        self.assertAlmostEqual(snap["effective_daily_max_minutes"], 70.0)

    def test_challenge_fixed_five_and_bonus_reward(self):
        """大闯关：固定 5 题；pass_ratio≈2/3 → 需对 4 题；奖励走加时 +10。"""
        self.assertEqual(challenge_questions({"challenge_questions": 5}), 5)
        self.assertEqual(required_correct(5, self.cfg), 4)
        self.assertTrue(passed_set(4, 5, self.cfg))
        self.assertFalse(passed_set(3, 5, self.cfg))

        st = default_state()
        st["daily_used_minutes"] = 60.0
        st["balance_minutes"] = 0.0
        self.assertTrue(should_use_challenge(st, self.cfg))
        # Normal grant would be 0 at daily cap
        self.assertAlmostEqual(grant_unlock(st, self.cfg), 0.0)

        added = grant_challenge_reward(st, 10.0)
        self.assertAlmostEqual(added, 10.0)
        self.assertAlmostEqual(st["balance_minutes"], 10.0)
        self.assertAlmostEqual(st["today_bonus_minutes"], 10.0)
        self.assertFalse(should_use_challenge(st, self.cfg))
        self.assertTrue(can_watch(st, self.cfg))


if __name__ == "__main__":
    unittest.main()
