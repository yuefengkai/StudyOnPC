# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studyonpc import win_yt  # noqa: E402


class TestWinYtPauseStubs(unittest.TestCase):
    def test_pause_resume_safe_on_non_windows(self):
        self.assertFalse(win_yt.pause_tracked_playback([1, 2]))
        self.assertFalse(win_yt.resume_tracked_playback([1]))
        win_yt.media_play_pause()

    def test_pause_uses_absolute_appcommand_not_space_toggle(self):
        if not win_yt.IS_WINDOWS:
            self.skipTest("Windows-only path")
        calls = []

        def fake_send(hwnd, cmd):
            calls.append((hwnd, cmd))
            return True

        with mock.patch.object(win_yt, "_send_appcommand", side_effect=fake_send), \
             mock.patch.object(win_yt, "_send_space_to_hwnd") as space, \
             mock.patch.object(win_yt, "media_play_pause") as media:
            ok = win_yt.pause_tracked_playback([11, 11, 22])
            self.assertTrue(ok)
            self.assertEqual(calls, [(11, win_yt.APPCOMMAND_MEDIA_PAUSE), (22, win_yt.APPCOMMAND_MEDIA_PAUSE)])
            space.assert_not_called()
            media.assert_not_called()

    def test_resume_uses_absolute_play(self):
        if not win_yt.IS_WINDOWS:
            # Still verify constants exist after import on Linux
            self.assertEqual(win_yt.APPCOMMAND_MEDIA_PAUSE, 47)
            self.assertEqual(win_yt.APPCOMMAND_MEDIA_PLAY, 46)
            return
        calls = []
        with mock.patch.object(win_yt, "_send_appcommand", side_effect=lambda h, c: calls.append((h, c)) or True), \
             mock.patch.object(win_yt, "media_play_pause") as media:
            ok = win_yt.resume_tracked_playback([7])
            self.assertTrue(ok)
            self.assertEqual(calls, [(7, win_yt.APPCOMMAND_MEDIA_PLAY)])
            media.assert_not_called()


if __name__ == "__main__":
    unittest.main()
