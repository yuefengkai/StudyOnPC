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
    can_watch,
    consume_watch,
    grant_unlock,
    needs_quiz,
    passed_set,
    record_answer,
    remaining_daily,
    required_correct,
    set_size,
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


if __name__ == "__main__":
    unittest.main()
