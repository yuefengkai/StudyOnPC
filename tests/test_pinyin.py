# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studyonpc.pinyin_ui import (  # noqa: E402
    HAS_PYPINYIN,
    annotate_inline,
    annotate_string,
    char_pinyin,
    tokenize,
)


class TestPinyin(unittest.TestCase):
    def test_monkey_nonempty(self):
        s = annotate_string("猴子")
        self.assertTrue(s.strip())
        self.assertIn("猴", s)
        self.assertIn("子", s)
        # must expose some latin pinyin letters
        self.assertTrue(any(c.isascii() and c.isalpha() for c in s))

    def test_inline_monkey(self):
        s = annotate_inline("猴子")
        self.assertIn("猴", s)
        self.assertIn("(", s)
        self.assertTrue(len(s) > 2)

    def test_mixed_keeps_math(self):
        s = annotate_string("3 + 2 = ？")
        self.assertIn("3", s)
        self.assertIn("+", s)

    def test_tokenize(self):
        toks = tokenize("小猴子")
        self.assertEqual(len(toks), 3)
        self.assertTrue(all(py for _, py in toks) or not HAS_PYPINYIN)
        if HAS_PYPINYIN:
            self.assertIsNotNone(char_pinyin("猴"))
            self.assertTrue(char_pinyin("猴"))


if __name__ == "__main__":
    unittest.main()
