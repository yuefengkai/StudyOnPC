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

from studyonpc import wrong_book  # noqa: E402
from studyonpc import bank as bank_mod  # noqa: E402


class WrongBookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "wrong_book.json"
        self.answers = Path(self.tmp.name) / "answers.log"
        self.patchers = [
            mock.patch.object(wrong_book, "WRONG_BOOK_PATH", self.path),
            mock.patch.object(wrong_book, "ANSWER_LOG", self.answers),
            mock.patch.object(wrong_book, "ensure_runtime_dirs", lambda: None),
        ]
        for p in self.patchers:
            p.start()

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        self.tmp.cleanup()

    def test_note_wrong_and_mastery(self):
        wrong_book.note_wrong(21, subject="数学", stem="21+5=?", correct_answer="26")
        open_rows = wrong_book.list_entries("open")
        self.assertEqual(len(open_rows), 1)
        self.assertEqual(open_rows[0]["wrong_count"], 1)
        self.assertFalse(open_rows[0]["mastered"])

        wrong_book.note_correct(21, subject="数学", stem="21+5=?", correct_answer="26")
        row = wrong_book.list_entries("all")[0]
        self.assertEqual(row["correct_streak"], 1)
        self.assertFalse(row["mastered"])
        self.assertEqual(len(wrong_book.list_entries("open")), 1)

        wrong_book.note_correct(21)
        row = wrong_book.list_entries("all")[0]
        self.assertEqual(row["correct_streak"], 2)
        self.assertTrue(row["mastered"])
        self.assertEqual(len(wrong_book.list_entries("open")), 0)
        self.assertEqual(wrong_book.counts()["mastered"], 1)

    def test_wrong_resets_mastery(self):
        wrong_book.note_wrong(7, subject="语文", stem="春天", correct_answer="春")
        wrong_book.note_correct(7)
        wrong_book.note_correct(7)
        self.assertTrue(wrong_book.list_entries("all")[0]["mastered"])
        wrong_book.note_wrong(7, subject="语文", stem="春天", correct_answer="春")
        row = wrong_book.list_entries("open")[0]
        self.assertFalse(row["mastered"])
        self.assertEqual(row["correct_streak"], 0)
        self.assertEqual(row["wrong_count"], 2)

    def test_list_open_and_clear_mastered(self):
        wrong_book.note_wrong(1, subject="英语", stem="apple", correct_answer="A")
        wrong_book.note_wrong(2, subject="英语", stem="book", correct_answer="B")
        wrong_book.note_correct(2)
        wrong_book.note_correct(2)
        self.assertEqual(len(wrong_book.list_entries("open")), 1)
        self.assertEqual(wrong_book.list_entries("open")[0]["question_id"], 1)
        removed = wrong_book.clear_mastered()
        self.assertEqual(removed, 1)
        self.assertEqual(wrong_book.counts()["total"], 1)

    def test_note_correct_without_entry_is_noop(self):
        self.assertIsNone(wrong_book.note_correct(999))
        self.assertEqual(wrong_book.counts()["total"], 0)

    def test_pick_set_prefers_wrong_ids(self):
        qs = [
            {"id": 1, "q": "a", "a": "1", "type": "single", "choices": ["1"]},
            {"id": 2, "q": "b", "a": "2", "type": "single", "choices": ["2"]},
            {"id": 3, "q": "c", "a": "3", "type": "single", "choices": ["3"]},
            {"id": 4, "q": "d", "a": "4", "type": "single", "choices": ["4"]},
            {"id": 5, "q": "e", "a": "5", "type": "single", "choices": ["5"]},
        ]
        # Prefer 3 and 5; set size 3 should include both
        picked = bank_mod.pick_set(qs, 3, recent_ids=[], prefer_ids=[3, 5])
        ids = {q["id"] for q in picked}
        self.assertIn(3, ids)
        self.assertIn(5, ids)
        self.assertEqual(len(picked), 3)
        self.assertEqual(len(ids), 3)  # no dups within set

    def test_backfill_from_answers(self):
        self.answers.write_text(
            "2026-11-07 19:01:02 | id=1 | 英语 | OK | chose='a' | expect='a'\n"
            "2026-11-07 19:02:02 | id=2 | 英语 | WRONG | chose='b' | expect='a' | mode=normal | unit=U1 | site=youtube\n"
            "2026-11-07 19:03:02 | id=2 | 英语 | OK | chose='a' | expect='a'\n"
            "2026-11-07 19:04:02 | id=2 | 英语 | OK | chose='a' | expect='a'\n"
            "2026-11-07 19:05:02 | id= | 英语 | WRONG | chose='x' | expect='y'\n",
            encoding="utf-8",
        )
        n = wrong_book.maybe_backfill_from_answers(force=True)
        self.assertEqual(n, 1)
        rows = wrong_book.list_entries("all")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["question_id"], 2)
        self.assertTrue(rows[0]["mastered"])  # two OK after WRONG
        self.assertEqual(rows[0]["wrong_count"], 1)


if __name__ == "__main__":
    unittest.main()
