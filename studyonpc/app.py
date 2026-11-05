# -*- coding: utf-8 -*-
"""StudyOnPC main application loop."""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime

import tkinter as tk
from tkinter import messagebox, simpledialog

from . import bank as bank_mod
from . import rules as rules_mod
from . import win_yt
from .admin_server import AdminContext, start_admin_server
from .config import load_config, save_config
from .paths import (
    ANSWER_LOG,
    FORCE_QUIZ_FLAG,
    MAIN_PID,
    ROOT,
    STOP_FLAG,
    WATCH_PID,
    ensure_runtime_dirs,
)
from .quiz_ui import QuizSetRunner
from .state import load_state, save_state
from .watchdog import (
    clear_stop_flag,
    ensure_peer,
    read_pid,
    run_watchdog,
    spawn_role,
    stop_requested,
    write_pid,
)

log = logging.getLogger("studyonpc.app")


def setup_logging() -> None:
    ensure_runtime_dirs()
    from .paths import APP_LOG

    root = logging.getLogger("studyonpc")
    root.setLevel(logging.INFO)
    if not root.handlers:
        fh = logging.FileHandler(APP_LOG, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root.addHandler(fh)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        root.addHandler(sh)


class StudyApp:
    def __init__(self, cfg: dict, fire_once: bool = False):
        self.cfg = cfg
        self.rules = rules_mod.RulesConfig.from_dict(cfg)
        self.keywords = list(cfg.get("youtube_keywords") or ["youtube", "youtu.be"])
        self.poll_ms = int(cfg.get("poll_ms", 2500))
        self.parent_pin = str(cfg.get("parent_pin", "changeme"))
        self.questions = bank_mod.load_questions(cfg)
        self.state = load_state()
        self.state["running_since"] = datetime.now().isoformat(timespec="seconds")
        self.state["quiz_active"] = False
        save_state(self.state)

        self.in_quiz = False
        self.saved_mute: bool | None = None
        self.minimized: list[int] = []
        self.last_tick = time.monotonic()
        self._force_pending = False
        self._admin = None
        self._httpd = None

        if STOP_FLAG.exists() and "--force" not in sys.argv and "--ignore-stop" not in sys.argv:
            log.info("stop.flag present — main exiting")
            sys.exit(0)

        self.root = tk.Tk()
        self.root.title("StudyOnPC 先学再看")
        self.root.withdraw()
        self.root.bind_all("<Control-Shift-Q>", self._parent_quit_hotkey)

        self._start_admin()
        write_pid(MAIN_PID)
        ensure_peer("watchdog", WATCH_PID)

        self.root.after(self.poll_ms, self._poll)
        self.root.after(3000, self._peer_check)

        print(
            "StudyOnPC 已启动。余额为 0 时需先答题解锁。"
            "家长退出：Ctrl+Shift+Q。管理页端口："
            f"{cfg.get('admin_port', 8099)}"
        )
        log.info(
            "main started pid=%s questions=%d balance=%.1f",
            os.getpid(),
            len(self.questions),
            float(self.state.get("balance_minutes", 0)),
        )

        if fire_once:
            log.info("--once: scheduling one quiz set")
            self.root.after(800, self._start_quiz_set)

    def _start_admin(self) -> None:
        port = int(self.cfg.get("admin_port", 8099))
        host = str(self.cfg.get("admin_bind", "0.0.0.0"))

        def get_status():
            snap = rules_mod.status_snapshot(self.state, self.rules)
            snap["running"] = True
            snap["in_quiz"] = self.in_quiz
            return snap

        def get_config():
            return dict(self.cfg)

        def do_save(data: dict):
            for k, v in data.items():
                if k in self.cfg or k in (
                    "unlock_minutes_per_set",
                    "questions_per_set",
                    "pass_ratio",
                    "daily_max_watch_minutes",
                    "wrong_streak_to_extra",
                    "extra_questions",
                    "poll_ms",
                    "answer_delay_seconds",
                    "parent_pin",
                    "admin_password",
                    "bank_file",
                    "admin_port",
                ):
                    self.cfg[k] = v
            save_config(self.cfg)
            self.rules = rules_mod.RulesConfig.from_dict(self.cfg)
            self.parent_pin = str(self.cfg.get("parent_pin", self.parent_pin))
            self.poll_ms = int(self.cfg.get("poll_ms", self.poll_ms))
            # reload bank if path changed
            try:
                self.questions = bank_mod.load_questions(self.cfg)
            except Exception as e:
                log.warning("reload bank: %s", e)

        def force_quiz():
            self._force_pending = True
            try:
                FORCE_QUIZ_FLAG.write_text(datetime.now().isoformat(), encoding="utf-8")
            except Exception:
                pass

        def request_quit(pin: str):
            if pin.strip() != self.parent_pin:
                return False, "PIN 不对"
            self.root.after(0, self._authorized_stop)
            return True, "ok"

        def list_banks():
            return bank_mod.list_bank_files()

        def import_bank(text: str, filename: str):
            path = bank_mod.import_bank_json(text, filename)
            return str(path.relative_to(ROOT)).replace("\\", "/")

        def get_answers():
            lines = []
            try:
                if ANSWER_LOG.exists():
                    raw = ANSWER_LOG.read_text(encoding="utf-8").splitlines()
                    for line in raw[-80:]:
                        # 2026-11-05 20:06:01 | id=12 | 语文 | OK | chose='蓝色' | expect='蓝色'
                        parts = [p.strip() for p in line.split("|")]
                        if len(parts) < 5:
                            continue
                        result = parts[3]
                        lines.append({
                            "time": parts[0],
                            "id": parts[1].replace("id=", ""),
                            "subject": parts[2],
                            "ok": result == "OK",
                            "chose": parts[4].replace("chose=", "").strip("'"),
                            "expect": parts[5].replace("expect=", "").strip("'") if len(parts) > 5 else "",
                        })
                lines.reverse()
            except Exception as e:
                log.warning("read answers: %s", e)
            return lines

        def reload_questions():
            try:
                self.questions = bank_mod.load_questions(self.cfg)
            except Exception as e:
                log.warning("reload questions: %s", e)

        def list_questions(**kwargs):
            return bank_mod.list_questions(self.cfg, **kwargs)

        def get_question(qid):
            return bank_mod.get_question(self.cfg, qid)

        def upsert_question(data):
            item = bank_mod.upsert_question(self.cfg, data)
            reload_questions()
            return item

        def delete_question(qid):
            ok = bank_mod.delete_question(self.cfg, qid)
            if ok:
                reload_questions()
            return ok

        def export_bank():
            return bank_mod.export_bank_text(self.cfg)

        def import_active(text, merge=False):
            result = bank_mod.replace_bank_from_import(self.cfg, text, merge=merge)
            reload_questions()
            return result

        ctx = AdminContext(
            get_status=get_status,
            get_config=get_config,
            save_config=do_save,
            force_quiz=force_quiz,
            request_quit=request_quit,
            list_banks=list_banks,
            import_bank=import_bank,
            get_answers=get_answers,
            list_questions=list_questions,
            get_question=get_question,
            upsert_question=upsert_question,
            delete_question=delete_question,
            export_bank=export_bank,
            import_active=import_active,
            password=str(self.cfg.get("admin_password") or self.parent_pin),
        )
        self._admin = ctx
        try:
            self._httpd = start_admin_server(ctx, host=host, port=port)
        except OSError as e:
            log.warning("admin server failed to bind %s:%s: %s", host, port, e)

    def _peer_check(self):
        try:
            if stop_requested():
                self._clean_exit()
                return
            ensure_peer("watchdog", WATCH_PID)
            write_pid(MAIN_PID)
        except Exception as e:
            log.warning("peer check: %s", e)
        self.root.after(3000, self._peer_check)

    def _parent_quit_hotkey(self, _event=None):
        pin = simpledialog.askstring(
            "家长验证",
            "输入家长 PIN 才能退出守护：",
            show="*",
            parent=self.root,
        )
        if pin is None:
            return
        if pin.strip() != self.parent_pin:
            messagebox.showerror("错误", "PIN 不对。小朋友请继续答题～", parent=self.root)
            return
        self._authorized_stop()

    def _authorized_stop(self):
        STOP_FLAG.write_text(datetime.now().isoformat(), encoding="utf-8")
        log.info("parent quit OK")
        wpid = read_pid(WATCH_PID)
        if wpid and wpid != os.getpid() and win_yt.pid_alive(wpid):
            win_yt.kill_pid(wpid)
        self._clean_exit()

    def _clean_exit(self):
        try:
            if self.in_quiz and (self.saved_mute is False or self.saved_mute is None):
                win_yt.set_system_mute(False)
        except Exception:
            pass
        try:
            self.state["quiz_active"] = False
            save_state(self.state)
        except Exception:
            pass
        try:
            if self._httpd is not None:
                self._httpd.shutdown()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        sys.exit(0)

    def _poll(self):
        try:
            if stop_requested():
                self._clean_exit()
                return
            now = time.monotonic()
            # force quiz flag / admin
            if FORCE_QUIZ_FLAG.exists():
                try:
                    FORCE_QUIZ_FLAG.unlink(missing_ok=True)
                except Exception:
                    pass
                self._force_pending = True

            if self.in_quiz:
                self.last_tick = now
            else:
                dt = max(0.0, now - self.last_tick)
                self.last_tick = now
                dt = min(dt, self.poll_ms / 1000.0 * 3)
                dt_min = dt / 60.0

                is_yt, _hwnd, _title = win_yt.foreground_is_youtube(self.keywords)
                if is_yt and rules_mod.can_watch(self.state, self.rules):
                    used = rules_mod.consume_watch(self.state, self.rules, dt_min)
                    if used > 0:
                        # persist occasionally (every ~15s of wall via tick count not needed — each poll ok but light)
                        pass

                # Quiz when forced, or when kid is on YouTube but cannot watch
                # (balance 0 or daily cap). Do not popup at idle/boot.
                should = False
                if self._force_pending:
                    should = True
                elif is_yt and rules_mod.needs_quiz(self.state, self.rules):
                    should = True
                if should:
                    self._force_pending = False
                    save_state(self.state)
                    self.root.after(0, self._start_quiz_set)
                # persist balance periodically
                if int(now) % 10 == 0:
                    save_state(self.state)
        except Exception as e:
            log.exception("poll error: %s", e)
        finally:
            try:
                self.root.after(self.poll_ms, self._poll)
            except Exception:
                pass

    def _start_quiz_set(self):
        if self.in_quiz:
            return
        self.in_quiz = True
        self.state["quiz_active"] = True
        save_state(self.state)
        log.info("quiz set start")
        self.saved_mute = win_yt.get_system_mute()
        win_yt.set_system_mute(True)
        self.minimized = []
        for hwnd, title in win_yt.find_youtube_windows(self.keywords):
            win_yt.minimize_hwnd(hwnd)
            self.minimized.append(hwnd)
            log.info("minimized %s", title[:60])

        runner = QuizSetRunner(
            root=self.root,
            questions=self.questions,
            state=self.state,
            rules=self.rules,
            parent_pin=self.parent_pin,
            on_finished=self._on_quiz_finished,
            on_parent_quit=self._authorized_stop,
        )
        runner.start()

    def _on_quiz_finished(self, passed: bool, grant: float):
        save_state(self.state)
        if not passed:
            # immediately another set
            log.info("set failed — starting another")
            runner = QuizSetRunner(
                root=self.root,
                questions=self.questions,
                state=self.state,
                rules=self.rules,
                parent_pin=self.parent_pin,
                on_finished=self._on_quiz_finished,
                on_parent_quit=self._authorized_stop,
            )
            runner.start()
            return

        # passed — restore media and leave quiz mode
        self.in_quiz = False
        self.state["quiz_active"] = False
        self.last_tick = time.monotonic()
        save_state(self.state)

        try:
            if self.saved_mute is True:
                win_yt.set_system_mute(True)
            else:
                win_yt.set_system_mute(False)
        except Exception as e:
            log.warning("unmute: %s", e)
            try:
                win_yt.set_system_mute(False)
            except Exception:
                pass

        restored = set()
        for hwnd in list(self.minimized):
            try:
                win_yt.restore_hwnd(hwnd)
                restored.add(hwnd)
            except Exception as e:
                log.warning("restore %s: %s", hwnd, e)
        self.minimized = []
        try:
            for hwnd, _title in win_yt.find_youtube_windows(self.keywords):
                if hwnd not in restored:
                    win_yt.restore_hwnd(hwnd)
        except Exception as e:
            log.warning("rescan restore: %s", e)

        log.info("quiz passed grant=%.1f balance=%.1f", grant, float(self.state.get("balance_minutes", 0)))

        # If daily remaining is 0 after grant, don't immediately re-quiz unless watching
        # Balance may be 0 if rem was 0 — needs_quiz true; only force when YT foreground next poll.

    def run(self):
        self.root.mainloop()


def main(argv: list[str] | None = None) -> None:
    setup_logging()
    argv = list(argv if argv is not None else sys.argv[1:])
    role = "main"
    for a in argv:
        if a.startswith("--role="):
            role = a.split("=", 1)[1].strip()
    if "--watchdog" in argv:
        role = "watchdog"

    if role == "watchdog":
        run_watchdog()
        return

    if "--force" in argv or "--ignore-stop" in argv:
        clear_stop_flag()

    cfg = load_config()
    fire_once = "--once" in argv
    app = StudyApp(cfg, fire_once=fire_once)
    app.run()


if __name__ == "__main__":
    main()
