"""One quiz group's bounded preloader and main-thread playback controller.

Workers only prepare files. They never call Tk or play audio. Results are polled
on the UI thread, so a stale future can populate cache but cannot start old audio.
"""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

from . import tts


def question_text(question: dict) -> str:
    """Read only the prompt: never answers, explanations or shuffled choices."""
    return str(question.get("q") or "").strip()


class GroupPreloader:
    """One daemon worker, shared futures per key, promotable current/next queue."""

    def __init__(self, config: dict, synthesize=None):
        self.config = dict(config)
        self.synthesize = synthesize or tts.synthesize
        self._condition = threading.Condition()
        self._pending = OrderedDict()
        self._futures = {}
        self.closed = False
        self._worker = threading.Thread(target=self._run, daemon=True,
                                        name="quiz-voice-cache")
        self._worker.start()

    def request(self, text: str, priority=False) -> Future:
        key = tts._cache_key(text, self.config)
        with self._condition:
            if self.closed:
                f = Future()
                f.cancel()
                return f
            f = self._futures.get(key)
            # Explicit replay may retry a failed synthesis, not an endless auto-loop.
            if f is not None and f.done() and not f.cancelled():
                if f.exception() is not None or f.result() is None:
                    f = None
            if f is None:
                f = Future()
                self._futures[key] = f
                self._pending[key] = (text, f)
            if priority and key in self._pending:
                self._pending.move_to_end(key, last=False)
            self._condition.notify()
            return f

    def prepare(self, texts):
        # The caller supplies only the selected group, never the entire bank.
        for text in texts:
            if text:
                self.request(text)

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self.closed or self._pending)
                if self.closed:
                    return
                _, (text, future) = self._pending.popitem(last=False)
                if not future.set_running_or_notify_cancel():
                    continue
            try:
                future.set_result(self.synthesize(text, self.config))
            except Exception as exc:
                future.set_exception(exc)

    def discard(self, text):
        """Cancel an obsolete prompt only if its request has not left the queue."""
        key = tts._cache_key(text, self.config)
        with self._condition:
            item = self._pending.pop(key, None)
            if item is not None:
                item[1].cancel()
                self._futures.pop(key, None)

    def close(self):
        with self._condition:
            self.closed = True
            for _, future in self._pending.values():
                future.cancel()
            self._pending.clear()
            self._condition.notify_all()


class ManagedPlayer:
    """Nonblocking, stoppable playback; all methods used on the Tk thread."""

    alias = "studyonpc_quiz_voice"

    def __init__(self):
        self._process = None

    def _mci(self, command):
        import ctypes
        buffer = ctypes.create_unicode_buffer(128)
        rc = ctypes.windll.winmm.mciSendStringW(command, buffer, 127, None)
        return rc, buffer.value

    def play(self, path):
        self.stop()
        if os.name == "nt":
            # No 'wait': playback runs in Windows, not on the Tk event loop.
            rc, _ = self._mci(f'open "{Path(path).resolve()}" type mpegvideo alias {self.alias}')
            if rc:
                rc, _ = self._mci(f'open "{Path(path).resolve()}" alias {self.alias}')
            if rc:
                return False
            self._mci(f"setaudio {self.alias} volume to 1000")
            rc, _ = self._mci(f"play {self.alias}")
            if rc:
                self.stop()
            return rc == 0
        for program, args in (("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
                              ("mpg123", ["-q"]), ("afplay", [])):
            exe = shutil.which(program)
            if exe:
                self._process = subprocess.Popen([exe, *args, str(path)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL)
                return True
        return False

    def busy(self):
        if os.name == "nt":
            rc, mode = self._mci(f"status {self.alias} mode")
            return rc == 0 and mode == "playing"
        return self._process is not None and self._process.poll() is None

    def stop(self):
        if os.name == "nt":
            self._mci(f"stop {self.alias}")
            self._mci(f"close {self.alias}")
        elif self._process is not None:
            if self._process.poll() is None:
                self._process.terminate()
            self._process = None


class QuizVoice:
    """Pure controller; Tk calls show/hover/poll/stop on its own event thread."""

    def __init__(self, config, questions, *, preloader=None, player=None, clock=time.monotonic):
        self.texts = [question_text(q) for q in questions]
        self.preloader = preloader or GroupPreloader(config)
        self.player = player or ManagedPlayer()
        self.clock = clock
        self.token = 0
        self._request = None
        self.current = None
        self.inside = False
        self.last_hover = float("-inf")
        self.closed = False
        self.status = ""
        self.preloader.prepare(self.texts)

    def show(self, index):
        self.stop()
        if self.closed:
            return
        self.current = self.texts[index]
        self.inside = False
        # Promote next, then current; the worker remains strictly bounded to one.
        if index + 1 < len(self.texts):
            self.preloader.request(self.texts[index + 1], priority=True)
        self.request_play()

    def request_play(self):
        if self.closed or not self.current or self._request or self.player.busy():
            return False
        self._request = (self.token, self.preloader.request(self.current, priority=True))
        self.status = "语音准备中… 可继续答题"
        return True

    def hover_enter(self):
        if self.inside:
            return False
        self.inside = True
        now = self.clock()
        if now - self.last_hover < 1.2:
            return False
        self.last_hover = now
        return self.request_play()

    def hover_leave(self):
        self.inside = False

    def poll(self):
        if self.closed:
            return self.status
        if self._request:
            token, future = self._request
            if future.done():
                self._request = None
                if token != self.token:
                    return self.status
                try:
                    path = None if future.cancelled() else future.result()
                    self.status = "正在读题…" if path and self.player.play(path) else "语音暂不可用，可继续答题"
                except Exception:
                    self.status = "语音暂不可用，可继续答题"
        elif self.status == "正在读题…" and not self.player.busy():
            self.status = "移到题目上可重听"
        return self.status

    def stop(self):
        if self.current:
            self.preloader.discard(self.current)
        self.token += 1
        self._request = None
        self.current = None
        self.status = ""
        self.player.stop()

    def close(self):
        self.stop()
        self.closed = True
        self.preloader.close()
