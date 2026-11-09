# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studyonpc import usage_stats  # noqa: E402


class UsageStatsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "usage_daily.json"
        self.answers = Path(self.tmp.name) / "answers.log"
        self.patchers = [
            mock.patch.object(usage_stats, "USAGE_DAILY_PATH", self.path),
            mock.patch.object(usage_stats, "ANSWER_LOG", self.answers),
            mock.patch.object(usage_stats, "ensure_runtime_dirs", lambda: None),
        ]
        for p in self.patchers:
            p.start()

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        self.tmp.cleanup()

    def test_note_answer_and_summarize_day(self):
        when = datetime(2026, 11, 8, 20, 15, 0)
        usage_stats.note_answer(correct=True, subject="数学", when=when)
        usage_stats.note_answer(correct=False, subject="数学", when=when.replace(minute=20))
        usage_stats.note_answer(correct=True, subject="语文", when=when.replace(hour=21))
        usage_stats.note_set(challenge=False, passed=True)
        usage_stats.note_set(challenge=True, passed=False)
        usage_stats.note_bonus(10)
        usage_stats.sync_from_state({
            "daily_date": "2026-11-08",
            "daily_used_minutes": 12.5,
            "today_unlock_minutes": 5,
            "today_bonus_minutes": 10,
            "site_daily_used": {"youtube": 12.5},
        })
        # force date in row — note_set used today(); rewrite key if needed
        data = json.loads(self.path.read_text(encoding="utf-8"))
        # Move whatever today key into 2026-11-08 for deterministic summarize if needed
        if "2026-11-08" not in data and data:
            only = next(iter(data.values()))
            only["date"] = "2026-11-08"
            # merge answer fields already on 2026-11-08 from note_answer
            base = data.get("2026-11-08") or {}
            # answers already on 2026-11-08
        out = usage_stats.summarize("day", "2026-11-08")
        sm = out["summary"]
        self.assertEqual(sm["answers_total"], 3)
        self.assertEqual(sm["answers_ok"], 2)
        self.assertAlmostEqual(sm["success_rate"], 66.7, places=0)
        self.assertEqual(sm["watch_minutes"], 12.5)
        self.assertEqual(sm["bonus_minutes"], 10)
        self.assertTrue(sm["peak_hours"])
        self.assertTrue(sm["subjects"])

    def test_backfill_answers_log(self):
        self.answers.write_text(
            "2026-11-07 19:01:02 | id=1 | 英语 | OK | chose='a' | expect='a'\n"
            "2026-11-07 19:02:02 | id=2 | 英语 | WRONG | chose='b' | expect='a' | mode=challenge | unit=U1 | site=youtube\n",
            encoding="utf-8",
        )
        n = usage_stats.backfill_from_answers()
        self.assertEqual(n, 2)
        out = usage_stats.summarize("day", "2026-11-07")
        self.assertEqual(out["summary"]["answers_total"], 2)
        self.assertEqual(out["summary"]["answers_ok"], 1)
        self.assertEqual(out["summary"]["max_correct_streak"], 1)


if __name__ == "__main__":
    unittest.main()
