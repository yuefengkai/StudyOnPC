# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studyonpc.sites import default_site, match_site, migrate_sites  # noqa: E402
from studyonpc.rules import RulesConfig, can_watch, consume_watch, grant_unlock, needs_quiz  # noqa: E402
from studyonpc.state import default_state  # noqa: E402
from studyonpc.config import load_config  # noqa: E402
from studyonpc import tts as tts_mod  # noqa: E402


class TestSites(unittest.TestCase):
    def test_migrate_from_legacy_keywords(self):
        cfg = {
            "youtube_keywords": ["YouTube", "youtu.be"],
            "unlock_minutes_per_set": 8,
            "daily_max_watch_minutes": 40,
            "questions_per_set": 2,
            "pass_ratio": 0.5,
        }
        sites = migrate_sites(cfg)
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0]["id"], "youtube")
        self.assertEqual(sites[0]["keywords"], ["youtube", "youtu.be"])
        self.assertEqual(sites[0]["unlock_minutes_per_set"], 8)
        self.assertEqual(sites[0]["daily_max_minutes"], 40)

    def test_match_site(self):
        cfg = {}
        migrate_sites(cfg)
        cfg["sites"].append(
            {
                "id": "bilibili",
                "name": "B站",
                "enabled": True,
                "keywords": ["bilibili", "哔哩哔哩"],
                "unlock_minutes_per_set": 5,
                "daily_max_minutes": 30,
                "questions_per_set": 3,
                "pass_ratio": 0.6667,
            }
        )
        migrate_sites(cfg)
        self.assertEqual(match_site("Funny cat - YouTube", cfg)["id"], "youtube")
        self.assertEqual(match_site("某视频 - bilibili", cfg)["id"], "bilibili")
        self.assertIsNone(match_site("Notepad", cfg))

    def test_shared_balance_per_site_daily(self):
        st = default_state()
        st["balance_minutes"] = 20
        yt = RulesConfig(unlock_minutes_per_set=10, questions_per_set=3, pass_ratio=0.6667, daily_max_watch_minutes=15)
        bi = RulesConfig(unlock_minutes_per_set=5, questions_per_set=3, pass_ratio=0.6667, daily_max_watch_minutes=10)
        used = consume_watch(st, yt, 12, "youtube")
        self.assertAlmostEqual(used, 12)
        self.assertAlmostEqual(st["balance_minutes"], 8)
        self.assertAlmostEqual(st["site_daily_used"]["youtube"], 12)
        # youtube daily almost full
        used = consume_watch(st, yt, 10, "youtube")
        self.assertAlmostEqual(used, 3)  # 15-12
        self.assertTrue(needs_quiz(st, yt, "youtube"))
        # bilibili still can watch with shared balance
        self.assertTrue(can_watch(st, bi, "bilibili"))
        used = consume_watch(st, bi, 2, "bilibili")
        self.assertAlmostEqual(used, 2)
        self.assertAlmostEqual(st["site_daily_used"]["bilibili"], 2)

    def test_grant_uses_site_remaining(self):
        st = default_state()
        st["site_daily_used"] = {"youtube": 55}
        cfg = RulesConfig(unlock_minutes_per_set=10, daily_max_watch_minutes=60)
        g = grant_unlock(st, cfg, "youtube")
        self.assertAlmostEqual(g, 5)
        self.assertAlmostEqual(st["balance_minutes"], 5)

    def test_tts_public_masks_token(self):
        view = tts_mod.public_tts_view({"enabled": True, "appid": "abc", "token": "secret123"})
        self.assertTrue(view["token_set"])
        self.assertNotIn("secret123", view.get("token_masked", ""))
        self.assertNotEqual(view.get("token", "x"), "secret123")


if __name__ == "__main__":
    unittest.main()
