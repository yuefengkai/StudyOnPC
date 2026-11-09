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
from .sites import default_site, enabled_sites, match_site, migrate_sites
from . import tts as tts_mod
from .paths import (
    ANSWER_LOG,
    FORCE_QUIZ_FLAG,
    FORCE_CHALLENGE_FLAG,
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
        migrate_sites(self.cfg)
        tts_mod.normalize_tts(self.cfg)
        self.rules = rules_mod.RulesConfig.from_dict(cfg)
        self.active_site = default_site(cfg)
        self.rules = rules_mod.RulesConfig.from_site(self.active_site, cfg)
        self.poll_ms = int(cfg.get("poll_ms", 2500))
        self.parent_pin = str(cfg.get("parent_pin", "changeme"))
        self.questions = bank_mod.load_questions(cfg)
        try:
            self.challenge_pool = bank_mod.load_challenge_questions(cfg)
        except Exception as e:
            log.warning("challenge bank load failed, using normal bank: %s", e)
            self.challenge_pool = list(self.questions)
        self.state = load_state()
        try:
            from . import wrong_book
            wrong_book.ensure_ready(self.cfg)
        except Exception as e:
            log.warning("wrong_book init: %s", e)
        self.state["running_since"] = datetime.now().isoformat(timespec="seconds")
        self.state["quiz_active"] = False
        save_state(self.state)

        self.in_quiz = False
        self.saved_mute: bool | None = None
        self.minimized: list[int] = []
        self.did_pause_playback = False
        self.last_tick = time.monotonic()
        self._force_pending = False
        self._challenge_pending = False
        self._in_challenge = False
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
            "main started pid=%s questions=%d challenge=%d balance=%.1f",
            os.getpid(),
            len(self.questions),
            len(self.challenge_pool),
            float(self.state.get("balance_minutes", 0)),
        )

        if fire_once:
            log.info("--once: scheduling one quiz set")
            self.root.after(800, self._start_quiz_set)

    def _start_admin(self) -> None:
        port = int(self.cfg.get("admin_port", 8099))
        host = str(self.cfg.get("admin_bind", "0.0.0.0"))

        def get_status():
            snap = rules_mod.status_snapshot(
                self.state,
                self.rules,
                sites=migrate_sites(self.cfg),
                active_site_id=(self.active_site or {}).get("id"),
            )
            snap["running"] = True
            snap["in_quiz"] = self.in_quiz
            snap["tts"] = tts_mod.public_tts_view(self.cfg.get("tts") or {})
            return snap

        def get_config():
            c = dict(self.cfg)
            c["sites"] = migrate_sites(c)
            c["tts"] = tts_mod.public_tts_view(c.get("tts") or {})
            return c

        def do_save(data: dict):
            allowed = {
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
                "challenge_bank_file",
                "challenge_questions",
                "challenge_reward_minutes",
                "admin_port",
                "youtube_keywords",
                "sites",
                "tts",
                "note",
                "task_name",
            }
            for k, v in data.items():
                if k in self.cfg or k in allowed:
                    if k == "tts" and isinstance(v, dict):
                        cur = dict(self.cfg.get("tts") or {})
                        # empty api_key (or legacy token/appid) means keep previous secret
                        for tk, tv in v.items():
                            if tk in ("api_key", "token", "appid") and (
                                tv is None or str(tv).strip() == "" or str(tv).startswith("*")
                            ):
                                continue
                            if tk in ("token", "appid", "cluster", "voice_type"):
                                # strip legacy V1 fields from live config
                                cur.pop(tk, None)
                                continue
                            cur[tk] = tv
                        self.cfg["tts"] = cur
                    else:
                        self.cfg[k] = v
            migrate_sites(self.cfg)
            tts_mod.normalize_tts(self.cfg)
            # Mirror global defaults from first/default site for legacy fields
            ds = default_site(self.cfg)
            self.cfg["unlock_minutes_per_set"] = ds.get("unlock_minutes_per_set", self.cfg.get("unlock_minutes_per_set"))
            self.cfg["questions_per_set"] = ds.get("questions_per_set", self.cfg.get("questions_per_set"))
            self.cfg["pass_ratio"] = ds.get("pass_ratio", self.cfg.get("pass_ratio"))
            self.cfg["daily_max_watch_minutes"] = ds.get("daily_max_minutes", self.cfg.get("daily_max_watch_minutes"))
            save_config(self.cfg)
            self.active_site = ds
            self.rules = rules_mod.RulesConfig.from_site(self.active_site, self.cfg)
            self.parent_pin = str(self.cfg.get("parent_pin", self.parent_pin))
            self.poll_ms = int(self.cfg.get("poll_ms", self.poll_ms))
            try:
                self.questions = bank_mod.load_questions(self.cfg)
                self.challenge_pool = bank_mod.load_challenge_questions(self.cfg)
            except Exception as e:
                log.warning("reload bank: %s", e)

        def add_bonus(minutes: float):
            added = rules_mod.add_bonus_minutes(self.state, minutes)
            save_state(self.state)
            try:
                from . import usage_stats
                if added:
                    usage_stats.note_bonus(float(added))
                usage_stats.sync_from_state(self.state)
            except Exception:
                pass
            return added

        def force_quiz():
            self._force_pending = True
            try:
                FORCE_QUIZ_FLAG.write_text(datetime.now().isoformat(), encoding="utf-8")
            except Exception:
                pass

        def force_challenge():
            self._challenge_pending = True
            self._force_pending = True
            try:
                FORCE_CHALLENGE_FLAG.write_text(datetime.now().isoformat(), encoding="utf-8")
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
                    q_cache: dict[str, str] = {}

                    def _stem_for(qid: str) -> str:
                        key = str(qid or "").strip()
                        if not key:
                            return ""
                        if key in q_cache:
                            return q_cache[key]
                        stem = ""
                        try:
                            item = bank_mod.get_question(self.cfg, key)
                            if item:
                                stem = str(item.get("q") or "")
                        except Exception:
                            stem = ""
                        q_cache[key] = stem
                        return stem

                    for line in raw[-80:]:
                        # 2026-11-05 20:06:01 | id=12 | 语文 | OK | chose='蓝色' | expect='蓝色' | ... | q='题干'
                        parts = [p.strip() for p in line.split("|")]
                        if len(parts) < 5:
                            continue
                        result = parts[3]
                        extra = {}
                        for p in parts[4:]:
                            if "=" in p:
                                k, _, v = p.partition("=")
                                extra[k.strip().lower()] = v.strip().strip("'\"")
                        qid = parts[1].replace("id=", "").strip()
                        stem = extra.get("q") or extra.get("stem") or ""
                        if not stem:
                            stem = _stem_for(qid)
                        lines.append({
                            "time": parts[0],
                            "id": qid,
                            "subject": parts[2],
                            "ok": result == "OK",
                            "chose": extra.get("chose", parts[4].replace("chose=", "").strip("'") if len(parts) > 4 else ""),
                            "expect": extra.get("expect", ""),
                            "q": stem,
                            "mode": extra.get("mode", ""),
                        })
                lines.reverse()
            except Exception as e:
                log.warning("read answers: %s", e)
            return lines

        def reload_questions():
            try:
                self.questions = bank_mod.load_questions(self.cfg)
                self.challenge_pool = bank_mod.load_challenge_questions(self.cfg)
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
            force_challenge=force_challenge,
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
            add_bonus=add_bonus,
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
            if FORCE_CHALLENGE_FLAG.exists():
                try:
                    FORCE_CHALLENGE_FLAG.unlink(missing_ok=True)
                except Exception:
                    pass
                self._challenge_pending = True
                self._force_pending = True
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

                is_hit, _hwnd, title = win_yt.foreground_is_youtube(
                    [k for s in enabled_sites(self.cfg) for k in (s.get("keywords") or [])]
                )
                site = match_site(title, self.cfg) if is_hit else None
                if site is None and is_hit:
                    site = default_site(self.cfg)
                if site is not None:
                    self.active_site = site
                    site_rules = rules_mod.RulesConfig.from_site(site, self.cfg)
                    sid = str(site.get("id") or "")
                    if rules_mod.can_watch(self.state, site_rules, sid):
                        rules_mod.consume_watch(self.state, site_rules, dt_min, sid)

                # Quiz when forced, or when kid is on a tracked site but cannot watch
                should = False
                if self._force_pending:
                    should = True
                    if self.active_site is None:
                        self.active_site = default_site(self.cfg)
                elif site is not None:
                    site_rules = rules_mod.RulesConfig.from_site(site, self.cfg)
                    sid = str(site.get("id") or "")
                    if rules_mod.needs_quiz(self.state, site_rules, sid):
                        should = True
                if should:
                    self._force_pending = False
                    save_state(self.state)
                    self.root.after(0, self._start_quiz_set)
                # persist balance periodically + mirror today usage stats
                if int(now) % 10 == 0:
                    save_state(self.state)
                    try:
                        from . import usage_stats
                        usage_stats.sync_from_state(self.state)
                    except Exception:
                        pass
        except Exception as e:
            log.exception("poll error: %s", e)
        finally:
            try:
                self.root.after(self.poll_ms, self._poll)
            except Exception:
                pass

    def _speak(self, text: str) -> None:
        # Quiz mode mutes the system so YouTube is silent; unmute briefly so TTS is audible.
        try:
            from . import win_yt
            win_yt.set_system_mute(False)
        except Exception as e:
            log.warning("unmute for TTS: %s", e)
        tts_mod.speak(text, self.cfg.get("tts") or {})

    def _challenge_params(self) -> tuple[int, float]:
        n = rules_mod.challenge_questions(self.cfg)
        reward = rules_mod.challenge_reward_minutes(self.cfg)
        return n, reward

    def _quiz_pool(self, challenge: bool) -> list:
        """大闯关抽二年级 challenge_pool；普通答题抽一年级 questions。"""
        if challenge:
            return self.challenge_pool or self.questions
        return self.questions


    def _reinforce_pause(self, hwnds: list[int]) -> None:
        if not self.in_quiz:
            return
        try:
            if win_yt.pause_tracked_playback(list(hwnds or [])):
                self.did_pause_playback = True
                log.info("pause reinforce delayed hwnds=%s", hwnds)
        except Exception as e:
            log.warning("pause reinforce delayed: %s", e)

    def _start_quiz_set(self):
        if self.in_quiz:
            return
        if self.active_site is None:
            self.active_site = default_site(self.cfg)
        self.rules = rules_mod.RulesConfig.from_site(self.active_site, self.cfg)
        site_id = str(self.active_site.get("id") or "")
        # 今日有效额度用尽 → 大闯关；或家长手动点大闯关
        challenge = bool(self._challenge_pending) or rules_mod.should_use_challenge(
            self.state, self.rules, site_id
        )
        self._challenge_pending = False
        self._in_challenge = challenge
        cq, cr = self._challenge_params()
        kws = list(self.active_site.get("keywords") or []) or [k for s in enabled_sites(self.cfg) for k in (s.get("keywords") or [])]
        self.in_quiz = True
        self.state["quiz_active"] = True
        save_state(self.state)
        log.info("quiz set start site=%s challenge=%s", site_id, challenge)
        self.saved_mute = win_yt.get_system_mute()
        # Pause video first (mute alone does not stop playback). Prefer pause over mute
        # so TTS「听一听」can still play while YouTube is stopped.
        yt_wins = win_yt.find_youtube_windows(kws)
        hwnds = [h for h, _t in yt_wins]
        # Absolute MEDIA_PAUSE (not Space toggle). Reinforce after minimize — safe to repeat.
        try:
            self.did_pause_playback = bool(win_yt.pause_tracked_playback(hwnds))
        except Exception as e:
            self.did_pause_playback = False
            log.warning("pause playback: %s", e)
        # If TTS is on, keep system unmuted so TTS is audible after pause.
        # Without TTS, also mute as defense in depth against other audio.
        if tts_mod.tts_configured(self.cfg.get("tts") or {}):
            win_yt.set_system_mute(False)
            log.info("quiz TTS enabled — paused media, system left unmuted")
        else:
            win_yt.set_system_mute(True)
        self.minimized = []
        for hwnd, title in yt_wins:
            win_yt.minimize_hwnd(hwnd)
            self.minimized.append(hwnd)
            log.info("minimized %s", title[:60])
        # Second pause pulse after minimize (APPCOMMAND works while iconic; absolute = no toggle flip).
        try:
            if win_yt.pause_tracked_playback(list(self.minimized) or hwnds):
                self.did_pause_playback = True
        except Exception as e:
            log.warning("pause reinforce: %s", e)

        runner = QuizSetRunner(
            root=self.root,
            questions=self._quiz_pool(challenge),
            state=self.state,
            rules=self.rules,
            parent_pin=self.parent_pin,
            on_finished=self._on_quiz_finished,
            on_parent_quit=self._authorized_stop,
            site_id=site_id,
            speak_fn=self._speak if tts_mod.tts_configured(self.cfg.get("tts") or {}) else None,
            tts_config=self.cfg.get("tts") or {},
            challenge_mode=challenge,
            challenge_questions=cq,
            challenge_reward_minutes=cr,
        )
        runner.start()
        # Quiz window steals focus; one more absolute pause in case Chrome ignored the first.
        try:
            paused_hwnds = list(self.minimized) or hwnds
            self.root.after(250, lambda h=paused_hwnds: self._reinforce_pause(h))
        except Exception:
            pass

    def _on_quiz_finished(self, passed: bool, grant: float):
        save_state(self.state)
        if not passed:
            # immediately another set (keep 大闯关 mode if this was a challenge)
            log.info("set failed — starting another challenge=%s", self._in_challenge)
            site_id = str((self.active_site or {}).get("id") or "")
            cq, cr = self._challenge_params()
            runner = QuizSetRunner(
                root=self.root,
                questions=self._quiz_pool(self._in_challenge),
                state=self.state,
                rules=self.rules,
                parent_pin=self.parent_pin,
                on_finished=self._on_quiz_finished,
                on_parent_quit=self._authorized_stop,
                site_id=site_id,
                speak_fn=self._speak if tts_mod.tts_configured(self.cfg.get("tts") or {}) else None,
                tts_config=self.cfg.get("tts") or {},
                challenge_mode=self._in_challenge,
                challenge_questions=cq,
                challenge_reward_minutes=cr,
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

        restored: list[int] = []
        for hwnd in list(self.minimized):
            try:
                win_yt.restore_hwnd(hwnd)
                restored.append(hwnd)
            except Exception as e:
                log.warning("restore %s: %s", hwnd, e)
        self.minimized = []
        try:
            kws = list((self.active_site or {}).get("keywords") or []) or [
                k for s in enabled_sites(self.cfg) for k in (s.get("keywords") or [])
            ]
            for hwnd, _title in win_yt.find_youtube_windows(kws):
                if hwnd not in restored:
                    win_yt.restore_hwnd(hwnd)
                    restored.append(hwnd)
        except Exception as e:
            log.warning("rescan restore: %s", e)

        # Absolute MEDIA_PLAY if we paused at quiz start (not toggle — avoids pause→play→pause).
        if self.did_pause_playback:
            try:
                win_yt.resume_tracked_playback(restored)
            except Exception as e:
                log.warning("resume playback: %s", e)
            self.did_pause_playback = False

        log.info("quiz passed grant=%.1f balance=%.1f", grant, float(self.state.get("balance_minutes", 0)))

        # If daily remaining is 0 after grant, don't immediately re-quiz unless watching
        # Balance may be 0 if rem was 0 — needs_quiz true; only force when YT foreground next poll.

    def run(self):
        self.root.mainloop()


def main(argv: list[str] | None = None) -> None:
    argv = list(argv if argv is not None else sys.argv[1:])
    # Drop black console for normal runs (python.exe → pythonw). Keep --console for debug.
    if win_yt.reexec_without_console(argv):
        return
    setup_logging()
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
