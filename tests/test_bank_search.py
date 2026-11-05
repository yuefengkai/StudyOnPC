# -*- coding: utf-8 -*-
from __future__ import annotations
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studyonpc.bank import list_questions  # noqa: E402
from studyonpc.config import load_config  # noqa: E402


class TestBankSearch(unittest.TestCase):
    def test_search_question_text(self):
        cfg = load_config()
        all_n = list_questions(cfg, page_size=1)["total"]
        self.assertGreaterEqual(all_n, 50)
        r = list_questions(cfg, search="声母", page_size=50)
        self.assertGreaterEqual(r["total"], 1)
        self.assertTrue(any("声母" in (it.get("q_preview") or it.get("q") or "") or "声母" in (it.get("unit") or "") for it in r["items"]))

    def test_search_choices(self):
        cfg = load_config()
        r = list_questions(cfg, search="dad", page_size=20)
        self.assertGreaterEqual(r["total"], 1)

    def test_search_unit_and_subject(self):
        cfg = load_config()
        r = list_questions(cfg, subject="数学", search="加法", page_size=50)
        self.assertGreaterEqual(r["total"], 1)
        for it in r["items"]:
            self.assertEqual(it.get("subject"), "数学")

    def test_multi_keyword_and(self):
        cfg = load_config()
        r = list_questions(cfg, search="拼音 声母", page_size=50)
        self.assertGreaterEqual(r["total"], 1)


if __name__ == "__main__":
    unittest.main()
