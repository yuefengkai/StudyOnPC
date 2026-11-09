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
import wave

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
        self._worker = threading.Thread(
            target=self._run, daemon=True, name="quiz-voice-cache"
        )
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


def _silence_wav_path(ms: int = 280) -> Path:
    """Tiny linear-PCM wav used to warm the device and pad the start of speech."""
    path = tts.cache_dir() / f"_silence_{ms}ms.wav"
    if path.exists() and path.stat().st_size > 44:
        return path
    rate = 24000
    frames = max(1, int(rate * ms / 1000))
    tmp = path.with_suffix(".tmp")
    with wave.open(str(tmp), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * frames)
    os.replace(tmp, path)
    return path


class ManagedPlayer:
    """Stoppable playback. Heavy audio work runs off the Tk thread."""

    alias = "studyonpc_quiz_voice"
    pad_alias = "studyonpc_quiz_pad"

    def __init__(self, lead_ms: int = 280):
        self._process = None
        self._thread = None
        self._generation = 0
        self._lock = threading.Lock()
        self._playing = False
        self.lead_ms = max(0, int(lead_ms))
        self._warmed = False

    def _mci(self, command: str):
        import ctypes

        buffer = ctypes.create_unicode_buffer(256)
        rc = ctypes.windll.winmm.mciSendStringW(command, buffer, 255, None)
        return rc, buffer.value

    def _mci_close(self, alias: str) -> None:
        self._mci(f"stop {alias}")
        self._mci(f"close {alias}")

    def warmup(self) -> None:
        """Prime the Windows audio graph once so the first real phrase keeps its onset."""
        if self._warmed or os.name != "nt":
            self._warmed = True
            return
        try:
            silence = _silence_wav_path(120)
            self._mci_close(self.pad_alias)
            rc, _ = self._mci(f'open "{silence.resolve()}" type waveaudio alias {self.pad_alias}')
            if rc:
                rc, _ = self._mci(f'open "{silence.resolve()}" alias {self.pad_alias}')
            if not rc:
                self._mci(f"play {self.pad_alias} wait")
            self._mci_close(self.pad_alias)
            self._warmed = True
        except Exception:
            # Still mark warmed so we do not retry forever on broken audio stacks.
            self._warmed = True

    def play(self, path) -> bool:
        path = Path(path)
        if not path.exists():
            return False
        self.stop()
        with self._lock:
            self._generation += 1
            gen = self._generation
            self._playing = True

        def run() -> None:
            try:
                if os.name == "nt":
                    self._play_windows(path, gen)
                else:
                    self._play_other(path, gen)
            finally:
                with self._lock:
                    if gen == self._generation:
                        self._playing = False

        self._thread = threading.Thread(target=run, daemon=True, name="quiz-voice-play")
        self._thread.start()
        return True

    def _alive(self, gen: int) -> bool:
        with self._lock:
            return gen == self._generation

    def _play_windows(self, path: Path, gen: int) -> None:
        # 1) Device warmup + leading pad so the first phonemes are not clipped.
        if self.lead_ms > 0:
            try:
                if not self._warmed:
                    self.warmup()
                if not self._alive(gen):
                    return
                silence = _silence_wav_path(self.lead_ms)
                self._mci_close(self.pad_alias)
                rc, _ = self._mci(
                    f'open "{silence.resolve()}" type waveaudio alias {self.pad_alias}'
                )
                if rc:
                    rc, _ = self._mci(f'open "{silence.resolve()}" alias {self.pad_alias}')
                if not rc:
                    self._mci(f"play {self.pad_alias} wait")
                self._mci_close(self.pad_alias)
            except Exception:
                pass
        if not self._alive(gen):
            return

        # 2) Open speech, give the decoder a brief settle, then play to completion.
        target = str(path.resolve())
        self._mci_close(self.alias)
        rc, _ = self._mci(f'open "{target}" type mpegvideo alias {self.alias}')
        if rc:
            rc, _ = self._mci(f'open "{target}" alias {self.alias}')
        if rc:
            return
        self._mci(f"setaudio {self.alias} volume to 1000")
        # Seek to start explicitly; short settle avoids cutting the first syllables.
        self._mci(f"seek {self.alias} to start")
        time.sleep(0.08)
        if not self._alive(gen):
            self._mci_close(self.alias)
            return
        rc, _ = self._mci(f"play {self.alias} wait")
        if not self._alive(gen):
            self._mci_close(self.alias)
            return
        self._mci_close(self.alias)

    def _play_other(self, path: Path, gen: int) -> None:
        for program, args in (
            ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
            ("mpg123", ["-q"]),
            ("afplay", []),
        ):
            exe = shutil.which(program)
            if not exe:
                continue
            if not self._alive(gen):
                return
            proc = subprocess.Popen(
                [exe, *args, str(path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._process = proc
            while proc.poll() is None:
                if not self._alive(gen):
                    proc.terminate()
                    break
                time.sleep(0.05)
            self._process = None
            return

    def busy(self) -> bool:
        with self._lock:
            return self._playing

    def stop(self) -> None:
        with self._lock:
            self._generation += 1
            self._playing = False
        if os.name == "nt":
            try:
                self._mci_close(self.alias)
                self._mci_close(self.pad_alias)
            except Exception:
                pass
        proc = self._process
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        self._process = None


class QuizVoice:
    """Pure controller; Tk calls show/hover/poll/stop on its own event thread."""

    def __init__(
        self,
        config,
        questions,
        *,
        preloader=None,
        player=None,
        clock=time.monotonic,
        hover_cooldown=1.2,
    ):
        self.texts = [question_text(q) for q in questions]
        self.preloader = preloader or GroupPreloader(config)
        self.player = player or ManagedPlayer()
        self.clock = clock
        self.hover_cooldown = float(hover_cooldown)
        self.token = 0
        self._request = None
        self.current = None
        self.inside = False
        self.last_hover = float("-inf")
        self.closed = False
        self.status = ""
        self.preloader.prepare(self.texts)
        # Warm audio off the UI thread so the first auto-read keeps its onset.
        threading.Thread(target=self.player.warmup, daemon=True, name="quiz-voice-warm").start()

    def show(self, index):
        self.stop(clear_current=True)
        if self.closed:
            return
        self.current = self.texts[index]
        self.inside = False
        # Promote next, then current; the worker remains strictly bounded to one.
        if index + 1 < len(self.texts):
            self.preloader.request(self.texts[index + 1], priority=True)
        self.request_play(force=True)

    def request_play(self, force: bool = False) -> bool:
        if self.closed or not self.current:
            return False
        if not force and (self._request or self.player.busy()):
            return False
        if force:
            # Invalidate in-flight play results and stop audio, keep current text.
            self.player.stop()
            self.token += 1
            self._request = None
        elif self._request or self.player.busy():
            return False
        self._request = (self.token, self.preloader.request(self.current, priority=True))
        self.status = "语音准备中… 可继续答题"
        return True

    def hover_enter(self) -> bool:
        """Arm a replay when the pointer first enters the question zone."""
        if self.inside:
            return False
        self.inside = True
        now = self.clock()
        if now - self.last_hover < self.hover_cooldown:
            return False
        self.last_hover = now
        # force=True: even if auto-read is still playing/pending, hover means 重播.
        return self.request_play(force=True)

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
                    if path and self.player.play(path):
                        self.status = "正在读题…"
                    else:
                        self.status = "语音暂不可用，可继续答题"
                except Exception:
                    self.status = "语音暂不可用，可继续答题"
        elif self.status == "正在读题…" and not self.player.busy():
            self.status = "移到题目上可重听"
        return self.status

    def stop(self, clear_current: bool = True):
        if self.current:
            self.preloader.discard(self.current)
        self.token += 1
        self._request = None
        if clear_current:
            self.current = None
        self.status = ""
        self.player.stop()

    def close(self):
        self.stop(clear_current=True)
        self.closed = True
        self.preloader.close()
