# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studyonpc.bank import (  # noqa: E402
    check_answer,
    load_bank_file,
    load_challenge_questions,
    load_questions,
    normalize_question,
    pick_set,
    questions_for_mode,
    resolve_challenge_bank_path,
    resolve_image,
)
from studyonpc.config import load_config  # noqa: E402


class TestBank(unittest.TestCase):
    def test_load_grade1(self):
        cfg = load_config()
        qs = load_questions(cfg)
        self.assertGreaterEqual(len(qs), 50)
        imaged = [q for q in qs if q.get("image")]
        self.assertGreaterEqual(len(imaged), 1)
        p = resolve_image(imaged[0]["image"])
        self.assertIsNotNone(p)
        self.assertTrue(p.exists())

    def test_studyonTV_like_normalize(self):
        raw = {
            "type": "single",
            "q": "1+1=?",
            "answers": ["1", "2", "3"],
            "correctIndices": [1],
            "difficulty": 1,
        }
        item = normalize_question(raw, 99)
        self.assertEqual(item["type"], "single")
        self.assertEqual(item["a"], "2")
        self.assertTrue(check_answer(item, "2"))
        self.assertFalse(check_answer(item, "1"))

        bool_q = normalize_question(
            {"type": "boolean", "q": "太阳从东边升起", "correct": True}, 1
        )
        self.assertEqual(bool_q["choices"], ["正确", "错误"])
        self.assertTrue(check_answer(bool_q, "正确"))

        multi = normalize_question(
            {
                "type": "multiple",
                "q": "偶数",
                "answers": ["1", "2", "4"],
                "correctIndices": [1, 2],
            },
            2,
        )
        self.assertTrue(check_answer(multi, ["2", "4"]))
        self.assertFalse(check_answer(multi, ["2"]))

    def test_skip_subjective_without_key(self):
        self.assertIsNone(
            normalize_question({"type": "subjective", "q": "写一段话"}, 1)
        )

    def test_pick_set(self):
        cfg = load_config()
        qs = load_questions(cfg)
        picked = pick_set(qs, 3, [])
        self.assertEqual(len(picked), 3)

    def test_load_challenge_grade2(self):
        cfg = load_config()
        path = resolve_challenge_bank_path(cfg)
        self.assertTrue(path.exists(), msg=str(path))
        qs = load_challenge_questions(cfg)
        self.assertGreaterEqual(len(qs), 60)
        # 大闯关以二年级数学为主
        math_n = sum(1 for q in qs if q.get("subject") == "数学")
        self.assertGreaterEqual(math_n, 50)
        grades = {q.get("grade") for q in qs if q.get("grade") is not None}
        self.assertIn(2, grades)

    def test_mode_banks_differ(self):
        cfg = load_config()
        normal = questions_for_mode(cfg, False)
        challenge = questions_for_mode(cfg, True)
        self.assertGreaterEqual(len(normal), 50)
        self.assertGreaterEqual(len(challenge), 60)
        n_ids = {q["id"] for q in normal[:20]}
        # 不同文件：抽题池路径不同即可
        self.assertNotEqual(
            resolve_challenge_bank_path(cfg).name,
            "grade1-shenzhen.json",
        )
        picked = pick_set(challenge, 5, [])
        self.assertEqual(len(picked), 5)


if __name__ == "__main__":
    unittest.main()
