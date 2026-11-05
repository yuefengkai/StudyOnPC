# -*- coding: utf-8 -*-
from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studyonpc.bank import check_answer, shuffle_choices  # noqa: E402


class TestShuffle(unittest.TestCase):
    def test_shuffle_preserves_correct_index_and_value(self):
        choices = ["红", "蓝", "绿", "黄"]
        answer = "蓝"
        correct_indices = [1]
        seen_pos = set()
        for seed in range(40):
            random.seed(seed)
            shuffled, new_idx = shuffle_choices(
                choices, correct_indices=correct_indices, answer=answer
            )
            self.assertEqual(sorted(shuffled), sorted(choices))
            self.assertEqual(len(new_idx), 1)
            self.assertEqual(shuffled[new_idx[0]], answer)
            seen_pos.add(new_idx[0])
            q = {"type": "single", "a": answer, "choices": shuffled}
            self.assertTrue(check_answer(q, answer))
            self.assertFalse(check_answer(q, "红"))
        # with enough seeds, position should vary (not always same slot)
        self.assertGreaterEqual(len(seen_pos), 2)

    def test_shuffle_multiple_indices(self):
        choices = ["1", "2", "3", "4"]
        random.seed(7)
        shuffled, new_idx = shuffle_choices(choices, correct_indices=[1, 2])
        self.assertEqual(sorted(shuffled[i] for i in new_idx), ["2", "3"])
        q = {"type": "multiple", "a": ["2", "3"], "choices": shuffled}
        self.assertTrue(check_answer(q, ["2", "3"]))


if __name__ == "__main__":
    unittest.main()
