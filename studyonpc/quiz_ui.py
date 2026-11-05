# -*- coding: utf-8 -*-
"""Fullscreen quiz-set UI — kid-friendly pastel + 拼音标注.

Persistent shell: option buttons / delay label / feedback stay packed.
Question switches only update text/state/colors (no full content destroy).
"""
from __future__ import annotations

import logging
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, simpledialog
from typing import Any, Callable

from . import bank as bank_mod
from . import pinyin_ui as pyui
from . import rules as rules_mod
from .paths import ANSWER_LOG

log = logging.getLogger("studyonpc.quiz_ui")

# Kid-flashy pastel theme (readable + playful)
BG = "#FFF0F5"          # lavender blush
CARD_BG = "#FFFFFF"
CARD_BORDER = "#FF80AB"
HEADER_FALLBACK = "#FFD54F"
FOOTER_FG = "#6A1B9A"
STICKERS = ("🌟", "🎈", "🦄", "🍭", "🚀", "🌈", "🐱", "🎯")

SUBJECT_THEME = {
    "数学": {"header": "#FF8A65", "accent": "#FF3D00", "btn": "#FFE082", "btn_h": "#FFD54F", "btn_p": "#FFCA28", "emoji": "🔢", "sticker": "🧮"},
    "语文": {"header": "#4FC3F7", "accent": "#0277BD", "btn": "#B2EBF2", "btn_h": "#80DEEA", "btn_p": "#4DD0E1", "emoji": "📖", "sticker": "✏️"},
    "英语": {"header": "#81C784", "accent": "#2E7D32", "btn": "#C5E1A5", "btn_h": "#AED581", "btn_p": "#9CCC65", "emoji": "🔤", "sticker": "🐾"},
}

try:
    from PIL import Image, ImageTk

    HAS_PIL = True
except Exception:
    HAS_PIL = False
    Image = None  # type: ignore
    ImageTk = None  # type: ignore


def log_answer(qid, subject, correct: bool, chosen: str, expected: str) -> None:
    ANSWER_LOG.parent.mkdir(parents=True, exist_ok=True)
    line = (
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
        f"id={qid} | {subject} | {'OK' if correct else 'WRONG'} | "
        f"chose={chosen!r} | expect={expected!r}\n"
    )
    with open(ANSWER_LOG, "a", encoding="utf-8") as f:
        f.write(line)


class QuizSetRunner:
    """Runs one quiz set in a persistent fullscreen window."""

    def __init__(
        self,
        root: tk.Tk,
        questions: list[dict[str, Any]],
        state: dict[str, Any],
        rules: rules_mod.RulesConfig,
        parent_pin: str,
        on_finished: Callable[[bool, float], None],
        on_parent_quit: Callable[[], None],
        site_id: str | None = None,
        speak_fn: Callable[[str], None] | None = None,
    ):
        self.root = root
        self.questions = questions
        self.state = state
        self.rules = rules
        self.parent_pin = parent_pin
        self.on_finished = on_finished
        self.on_parent_quit = on_parent_quit
        self.site_id = site_id
        self.speak_fn = speak_fn
        self.set_qs: list[dict[str, Any]] = []
        self.idx = 0
        self.correct_count = 0
        self._win: tk.Toplevel | None = None
        self._content: tk.Frame | None = None
        self._photo_ref: list = []
        self._answered = False
        self._built = False
        self._gate_token = 0
        self._active_q: dict[str, Any] | None = None
        self._mode = "single"  # single | multiple | text | result

        # Persistent widgets (filled by _build_shell)
        self._header: tk.Frame | None = None
        self._title_lbl: tk.Label | None = None
        self._progress_lbl: tk.Label | None = None
        self._dots_frame: tk.Frame | None = None
        self._dot_lbls: list[tk.Label] = []
        self._sub_host: tk.Frame | None = None
        self._unit_host: tk.Frame | None = None
        self._body: tk.Frame | None = None
        self._q_host: tk.Frame | None = None
        self._img_host: tk.Frame | None = None
        self._img_lbl: tk.Label | None = None
        self._fb_lbl: tk.Label | None = None
        self._delay_lbl: tk.Label | None = None
        self._speak_btn: tk.Button | None = None
        self._sticker_lbl: tk.Label | None = None
        self._btn_frame: tk.Frame | None = None
        self._choice_btns: list = []
        self._multi_frame: tk.Frame | None = None
        self._multi_rows: list = []
        self._multi_vars: list[tk.BooleanVar] = []
        self._multi_checks: list[tk.Checkbutton] = []
        self._multi_text_hosts: list[tk.Frame] = []
        self._submit_btn: tk.Button | None = None
        self._entry: tk.Entry | None = None
        self._result_frame: tk.Frame | None = None
        self._quiz_frame: tk.Frame | None = None

    def start(self) -> None:
        n = rules_mod.set_size(self.state, self.rules)
        recent = list(self.state.get("recent_ids") or [])
        self.set_qs = bank_mod.pick_set(self.questions, n, recent)
        for q in self.set_qs:
            qid = q.get("id")
            if qid is not None:
                recent.append(qid)
        self.state["recent_ids"] = recent[-32:]
        self.idx = 0
        self.correct_count = 0
        log.info("quiz set start n=%d pending_extra=%s", n, self.state.get("pending_extra"))
        self._show_current()


    def _on_speak(self) -> None:
        if not self.speak_fn:
            try:
                messagebox.showinfo("听一听", "语音朗读未开启。请在管理页打开 TTS，并填写火山引擎 appid/token。", parent=self._win or self.root)
            except Exception:
                pass
            return
        q = self._active_q or (self.set_qs[self.idx] if self.set_qs and self.idx < len(self.set_qs) else None)
        if not q:
            return
        parts = [str(q.get("q") or "")]
        choices = q.get("choices") or []
        if choices:
            parts.append("选项：" + "，".join(str(c) for c in choices[:4]))
        text = "。".join(p for p in parts if p)
        try:
            self.speak_fn(text)
        except Exception as e:
            log.warning("speak failed: %s", e)

    def _harden(self, win: tk.Toplevel) -> None:
        win.protocol("WM_DELETE_WINDOW", lambda: None)
        win.bind("<Alt-F4>", lambda e: "break")
        win.bind("<Escape>", lambda e: "break")
        win.bind("<Control-Shift-Q>", self._hotkey_quit)
        try:
            win.overrideredirect(True)
        except Exception:
            pass
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass
        try:
            win.update_idletasks()
            sw = win.winfo_screenwidth()
            sh = win.winfo_screenheight()
            win.geometry(f"{sw}x{sh}+0+0")
        except Exception:
            try:
                win.attributes("-fullscreen", True)
            except Exception:
                pass
        try:
            import ctypes
            from ctypes import wintypes

            win.update_idletasks()
            hwnd = wintypes.HWND(int(win.winfo_id()))
            user32 = ctypes.windll.user32
            HWND_TOPMOST = -1
            SWP_SHOWWINDOW = 0x0040
            sw = int(user32.GetSystemMetrics(0))
            sh = int(user32.GetSystemMetrics(1))
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, sw, sh, SWP_SHOWWINDOW)
        except Exception:
            pass

    def _hotkey_quit(self, _event=None):
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
        self.on_parent_quit()

    def _close_win(self) -> None:
        self._gate_token += 1
        if self._win is not None:
            try:
                self._win.grab_release()
            except Exception:
                pass
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None
            self._content = None
            self._built = False

    def _theme(self, subject: str) -> dict:
        return SUBJECT_THEME.get(
            subject,
            {
                "header": HEADER_FALLBACK,
                "accent": "#FF4081",
                "btn": "#F8BBD0",
                "btn_h": "#F48FB1",
                "btn_p": "#F06292",
                "emoji": "⭐",
                "sticker": "🌈",
            },
        )

    def _paint_bg(self, widget, color: str) -> None:
        try:
            widget.configure(bg=color)
        except Exception:
            return
        for ch in widget.winfo_children():
            # Don't recurse into choice buttons / entry — they manage own colors
            if ch in self._choice_btns:
                continue
            if ch is self._entry or ch is self._submit_btn:
                continue
            if ch is self._btn_frame or ch is self._multi_frame:
                continue
            try:
                cls = ch.winfo_class()
            except Exception:
                continue
            if cls in ("Frame", "Label"):
                self._paint_bg(ch, color)

    def _ensure_shell(self) -> tk.Toplevel:
        if self._win is not None:
            try:
                if self._win.winfo_exists():
                    self._harden(self._win)
                    if not self._built:
                        self._build_shell()
                    return self._win
            except Exception:
                self._win = None
                self._built = False
        win = tk.Toplevel(self.root)
        self._win = win
        win.title("先学再看")
        win.configure(bg=BG)
        self._harden(win)
        try:
            win.grab_set()
        except Exception:
            pass
        host = tk.Frame(win, bg=BG)
        host.pack(fill="both", expand=True)
        self._content = host
        self._build_shell()
        win.focus_force()
        win.lift()
        return win

    def _build_shell(self) -> None:
        """Build persistent quiz chrome once — never pack_forget the option grid."""
        host = self._content
        assert host is not None
        for w in list(host.winfo_children()):
            try:
                w.destroy()
            except Exception:
                pass

        # ---- quiz mode container ----
        quiz = tk.Frame(host, bg=BG)
        quiz.pack(fill="both", expand=True)
        self._quiz_frame = quiz

        header = tk.Frame(quiz, bg=HEADER_FALLBACK)
        header.pack(fill="x")
        self._header = header

        top_row = tk.Frame(header, bg=HEADER_FALLBACK)
        top_row.pack(fill="x", padx=24, pady=(16, 4))
        self._title_lbl = tk.Label(
            top_row,
            text="🌈 先学再看 ✨",
            bg=HEADER_FALLBACK,
            fg="#4A148C",
            font=pyui.preferred_font(20, "bold"),
        )
        self._title_lbl.pack(side="left")
        self._sticker_lbl = tk.Label(
            top_row,
            text=" " + " ".join(STICKERS[:4]),
            bg=HEADER_FALLBACK,
            fg="#6A1B9A",
            font=pyui.preferred_font(14),
        )
        self._sticker_lbl.pack(side="left", padx=(12, 0))
        self._progress_lbl = tk.Label(
            top_row,
            text="第 1 / 1 题",
            bg=HEADER_FALLBACK,
            fg="#4E342E",
            font=pyui.preferred_font(18, "bold"),
        )
        self._progress_lbl.pack(side="right")

        self._dots_frame = tk.Frame(header, bg=HEADER_FALLBACK)
        self._dots_frame.pack(pady=(0, 6))
        self._dot_lbls = []

        self._sub_host = tk.Frame(header, bg=HEADER_FALLBACK)
        self._sub_host.pack(pady=(0, 4))
        self._unit_host = tk.Frame(header, bg=HEADER_FALLBACK)
        self._unit_host.pack(pady=(0, 10))

        foot = tk.Frame(quiz, bg=BG)
        foot.pack(side="bottom", fill="x", pady=8)
        pyui.render_annotated(
            foot,
            "答完一组才可以继续看　家长按 Ctrl+Shift+Q",
            bg=BG,
            fg=FOOTER_FG,
            py_fg="#A1887F",
            han_size=12,
            py_size=8,
            max_cols=28,
        ).pack()

        body_wrap = tk.Frame(quiz, bg=BG)
        body_wrap.pack(expand=True, fill="both", padx=36, pady=18)
        shadow = tk.Frame(body_wrap, bg="#E8E0D5")
        shadow.pack(expand=True, fill="both")
        border = tk.Frame(shadow, bg=CARD_BORDER, padx=6, pady=6)
        border.pack(fill="both", expand=True, padx=4, pady=4)
        body = tk.Frame(border, bg=CARD_BG)
        body.pack(fill="both", expand=True)
        self._body = body

        self._q_host = tk.Frame(body, bg=CARD_BG)
        self._q_host.pack(pady=(22, 10), padx=20)

        self._img_host = tk.Frame(body, bg="#FFF8E1", padx=8, pady=8)
        # packed only when an image is present
        self._img_lbl = tk.Label(self._img_host, bg="#FFF8E1")
        self._img_lbl.pack()

        self._fb_lbl = tk.Label(
            body,
            text="",
            bg=CARD_BG,
            fg="#546E7A",
            font=pyui.preferred_font(16, "bold"),
            wraplength=720,
            justify="center",
        )
        self._fb_lbl.pack(pady=8)

        # Plain Label — countdown only updates text (no destroy/rebuild)
        self._delay_lbl = tk.Label(
            body,
            text="",
            bg=CARD_BG,
            fg="#EF6C00",
            font=pyui.preferred_font(18, "bold"),
        )
        self._delay_lbl.pack(pady=(4, 0))

        speak_row = tk.Frame(body, bg=CARD_BG)
        speak_row.pack(pady=(2, 4))
        self._speak_btn = tk.Button(
            speak_row,
            text="🔊 听一听题目",
            font=pyui.preferred_font(14, "bold"),
            bg="#FFF59D",
            fg="#E65100",
            activebackground="#FFEE58",
            activeforeground="#BF360C",
            relief="raised",
            bd=3,
            padx=14,
            pady=6,
            cursor="hand2",
            command=self._on_speak,
        )
        self._speak_btn.pack()

        # Fixed 2x2 option grid — widgets stay forever
        self._btn_frame = tk.Frame(body, bg=CARD_BG)
        self._btn_frame.pack(pady=16, anchor="center")
        self._choice_btns = []
        for i in range(4):
            b = pyui.make_choice_button(
                self._btn_frame,
                "…",
                command=lambda: None,
                bg="#FFF3E0",
                bg_hover="#FFE0B2",
                bg_press="#FFCC80",
                fg="#1A237E",
                accent="#FFA726",
                width=340,
                height=112,
                enabled=False,
            )
            # sticky="" — do not stretch cards; uniform columns keep positions fixed
            b.grid(row=i // 2, column=i % 2, padx=14, pady=12, sticky="")
            self._choice_btns.append(b)
        # Equal column/row sizes so hover never redistributes width
        # Equal fixed columns — no weight so hover cannot redistribute width
        self._btn_frame.grid_columnconfigure(0, weight=0, minsize=340, uniform="optcol")
        self._btn_frame.grid_columnconfigure(1, weight=0, minsize=340, uniform="optcol")
        self._btn_frame.grid_rowconfigure(0, weight=0, minsize=112, uniform="optrow")
        self._btn_frame.grid_rowconfigure(1, weight=0, minsize=112, uniform="optrow")

        # Multiple-choice panel (hidden unless needed)
        self._multi_frame = tk.Frame(body, bg=CARD_BG)
        self._multi_rows = []
        self._multi_vars = []
        self._multi_checks = []
        self._multi_text_hosts = []
        for _ in range(4):
            v = tk.BooleanVar(value=False)
            self._multi_vars.append(v)
            row = tk.Frame(self._multi_frame, bg="#FFF3E0", padx=10, pady=8)
            row.pack(fill="x", pady=6, padx=20)
            cb = tk.Checkbutton(
                row,
                variable=v,
                bg="#FFF3E0",
                activebackground="#FFE0B2",
                highlightthickness=0,
                state="disabled",
            )
            cb.pack(side="left", padx=(4, 10))
            text_host = tk.Frame(row, bg="#FFF3E0")
            text_host.pack(side="left")
            self._multi_rows.append(row)
            self._multi_checks.append(cb)
            self._multi_text_hosts.append(text_host)

        self._entry = tk.Entry(
            body,
            font=pyui.preferred_font(24),
            width=22,
            justify="center",
            bg="#FFFDE7",
            fg="#1A237E",
            relief="solid",
            bd=2,
            state="disabled",
        )

        self._submit_btn = tk.Button(
            body,
            text="✅ 提交",
            font=pyui.preferred_font(18, "bold"),
            bg="#B0BEC5",
            fg="#FFFFFF",
            relief="flat",
            padx=28,
            pady=10,
            cursor="arrow",
            state="disabled",
        )

        # Result overlay (shown instead of quiz chrome at end)
        self._result_frame = tk.Frame(host, bg=BG)

        self._built = True

    def _set_header_theme(self, theme: dict, subject: str) -> None:
        assert self._header is not None
        h = theme["header"]
        self._header.configure(bg=h)
        for child in self._header.winfo_children():
            try:
                child.configure(bg=h)
            except Exception:
                pass
            for g in child.winfo_children():
                try:
                    g.configure(bg=h)
                except Exception:
                    pass
        emoji = theme.get("emoji") or "⭐"
        sticker = theme.get("sticker") or "🌈"
        self._title_lbl.configure(text=f"{emoji} 先学再看 ✨", bg=h, fg="#4A148C")
        if self._sticker_lbl is not None:
            try:
                self._sticker_lbl.configure(
                    text=f" {sticker} " + " ".join(STICKERS[:3]),
                    bg=h,
                )
            except Exception:
                pass
        self._progress_lbl.configure(bg=h)
        self._dots_frame.configure(bg=h)
        self._sub_host.configure(bg=h)
        self._unit_host.configure(bg=h)

    def _refresh_dots(self, theme: dict) -> None:
        n = len(self.set_qs)
        # Grow/shrink labels only when set size changes (once per set usually)
        while len(self._dot_lbls) < n:
            lbl = tk.Label(
                self._dots_frame,
                text="●",
                bg=self._dots_frame.cget("bg"),
                fg="#FFFFFF",
                font=pyui.preferred_font(14),
            )
            lbl.pack(side="left", padx=4)
            self._dot_lbls.append(lbl)
        while len(self._dot_lbls) > n:
            lbl = self._dot_lbls.pop()
            try:
                lbl.destroy()
            except Exception:
                pass
        for i, lbl in enumerate(self._dot_lbls):
            if i < self.correct_count and i < self.idx:
                c = "#43A047"
            elif i < self.idx:
                c = "#E53935"
            elif i == self.idx:
                c = theme["accent"]
            else:
                c = "#FFFFFF"
            try:
                lbl.configure(fg=c, bg=self._dots_frame.cget("bg"))
            except Exception:
                pass

    def _set_annotated_host(self, host: tk.Frame, text: str, *, bg: str, fg: str, py_fg: str, han_size: int, py_size: int, max_cols: int) -> None:
        for w in list(host.winfo_children()):
            try:
                w.destroy()
            except Exception:
                pass
        if not text:
            return
        pyui.render_annotated(
            host,
            text,
            bg=bg,
            fg=fg,
            py_fg=py_fg,
            han_size=han_size,
            py_size=py_size,
            max_cols=max_cols,
        ).pack()

    def _set_feedback(self, text: str, color: str) -> None:
        if self._fb_lbl is None:
            return
        try:
            self._fb_lbl.configure(text=text, fg=color)
        except Exception:
            pass

    def _set_delay_text(self, text: str, color: str = "#EF6C00") -> None:
        if self._delay_lbl is None:
            return
        try:
            self._delay_lbl.configure(text=text, fg=color)
        except Exception:
            pass

    def _show_mode(self, mode: str) -> None:
        """Show single / multiple / text controls without destroying them.

        Same-mode switches are a no-op so the option grid never unpacks/repacks
        (that was a major source of flicker between questions).
        """
        prev = getattr(self, "_mode", None)
        if prev == mode:
            return
        self._mode = mode
        # Unpack only what is leaving; never destroy widgets.
        if prev == "single":
            try:
                self._btn_frame.pack_forget()
            except Exception:
                pass
        elif prev == "multiple":
            try:
                self._multi_frame.pack_forget()
            except Exception:
                pass
            try:
                self._submit_btn.pack_forget()
            except Exception:
                pass
        elif prev == "text":
            try:
                self._entry.pack_forget()
            except Exception:
                pass
            try:
                self._submit_btn.pack_forget()
            except Exception:
                pass

        if mode == "single":
            self._btn_frame.pack(pady=16, anchor="center")
        elif mode == "multiple":
            self._multi_frame.pack(pady=12)
            self._submit_btn.configure(text="✅ 提交多选")
            self._submit_btn.pack(pady=14)
        elif mode == "text":
            self._entry.pack(pady=16)
            self._submit_btn.configure(text="✅ 提交")
            self._submit_btn.pack(pady=8)

    def _answer_delay(self) -> float:
        return float(getattr(self.rules, "answer_delay_seconds", 5) or 0)

    def _start_answer_gate(self, enable_cb) -> None:
        """Countdown via Label.configure only — never rebuild option widgets."""
        self._gate_token += 1
        token = self._gate_token
        delay = int(round(self._answer_delay()))
        win = self._win
        if win is None:
            enable_cb()
            return

        if delay <= 0:
            self._set_delay_text("可以答题啦", "#2E7D32")
            enable_cb()
            return

        remaining = {"n": delay}

        def tick():
            if token != self._gate_token:
                return
            n = remaining["n"]
            if n <= 0:
                self._set_delay_text("可以答题啦", "#2E7D32")
                enable_cb()
                return
            self._set_delay_text(f"请先看题 {n}", "#EF6C00")
            remaining["n"] = n - 1
            win.after(1000, tick)

        tick()

    def _show_current(self) -> None:
        self._answered = False
        if self.idx >= len(self.set_qs):
            self._finish_set()
            return

        q = self.set_qs[self.idx]
        win = self._ensure_shell()

        # Ensure quiz chrome visible (not result overlay)
        if self._result_frame is not None:
            try:
                self._result_frame.pack_forget()
            except Exception:
                pass
        if self._quiz_frame is not None:
            try:
                self._quiz_frame.pack(fill="both", expand=True)
            except Exception:
                pass

        subject = q.get("subject", "")
        theme = self._theme(subject)
        unit = q.get("unit", "")
        n = len(self.set_qs)
        need = rules_mod.required_correct(n, self.rules)

        self._set_header_theme(theme, subject)
        self._progress_lbl.configure(text=f"第 {self.idx + 1} / {n} 题")
        self._refresh_dots(theme)

        hbg = theme["header"]
        self._set_annotated_host(
            self._sub_host,
            f"{subject}　需要答对 {need} 题才能看哦",
            bg=hbg,
            fg="#4E342E",
            py_fg="#6D4C41",
            han_size=14,
            py_size=9,
            max_cols=22,
        )
        self._set_annotated_host(
            self._unit_host,
            str(unit) if unit else "",
            bg=hbg,
            fg="#5D4037",
            py_fg="#8D6E63",
            han_size=12,
            py_size=8,
            max_cols=24,
        )

        # Question text — only this small host is rebuilt for new 拼音 layout
        self._set_annotated_host(
            self._q_host,
            str(q.get("q", "")),
            bg=CARD_BG,
            fg="#1A237E",
            py_fg="#5C6BC0",
            han_size=32,
            py_size=12,
            max_cols=16,
        )

        # Image: update PhotoImage on stable Label
        self._photo_ref = []
        img_rel = q.get("image")
        show_img = False
        if img_rel and HAS_PIL:
            img_path = bank_mod.resolve_image(img_rel)
            if img_path is not None:
                try:
                    im = Image.open(img_path)
                    im.thumbnail((480, 280), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(im)
                    self._photo_ref.append(photo)
                    self._img_lbl.configure(image=photo)
                    show_img = True
                except Exception as e:
                    log.warning("image load failed: %s", e)
        if show_img:
            try:
                self._img_host.pack(pady=6)
            except Exception:
                pass
        else:
            try:
                self._img_lbl.configure(image="")
                self._img_host.pack_forget()
            except Exception:
                pass

        self._set_feedback(f"加油！本组已经对了 {self.correct_count} 题", "#546E7A")
        self._set_delay_text("")

        qtype = q.get("type", "single")
        if qtype == "text":
            self._prep_text(q, theme)
        elif qtype == "multiple":
            self._prep_multiple(q, theme)
        else:
            self._prep_single(q, theme)

        try:
            win.focus_force()
            win.lift()
        except Exception:
            pass

    def _prep_single(self, q, theme) -> None:
        raw_choices = list(q.get("choices") or [])
        shuffled, new_idx = bank_mod.shuffle_choices(
            raw_choices,
            correct_indices=list(q.get("correct_indices") or []),
            answer=q.get("a"),
        )
        q = dict(q)
        if new_idx and q.get("a") is None:
            q["correct_indices"] = new_idx
            if len(new_idx) == 1:
                q["a"] = shuffled[new_idx[0]]
        elif new_idx:
            # Keep answer value; indices remapped for bookkeeping
            q["correct_indices"] = new_idx
        self._active_q = q

        self._show_mode("single")

        # Update existing 4 buttons in place — never destroy / re-grid
        for i, b in enumerate(self._choice_btns):
            if i < len(shuffled):
                choice = str(shuffled[i])
                try:
                    b.grid()  # restore if previously grid_remove'd
                except Exception:
                    pass
                b.set_colors(
                    bg=theme["btn"],
                    bg_hover=theme["btn_h"],
                    bg_press=theme["btn_p"],
                    accent=theme["accent"],
                    fg="#1A237E",
                )
                b.set_command(lambda ch=choice, qq=q: self._handle_answer(qq, ch, self._win))
                b.set_text(choice)
                b.set_enabled(False)
            else:
                try:
                    b.grid_remove()
                except Exception:
                    pass

        self._start_answer_gate(lambda: self._enable_single())

    def _enable_single(self) -> None:
        for b in self._choice_btns:
            try:
                # only enable buttons currently mapped (have text and are gridded)
                info = b.grid_info()
                if info:
                    b.set_enabled(True)
            except Exception:
                pass

    def _prep_multiple(self, q, theme) -> None:
        raw_choices = list(q.get("choices") or [])
        shuffled, new_idx = bank_mod.shuffle_choices(
            raw_choices,
            correct_indices=list(q.get("correct_indices") or []),
            answer=q.get("a"),
        )
        q = dict(q)
        if new_idx:
            q["correct_indices"] = new_idx
            q["a"] = [shuffled[i] for i in new_idx]
        self._active_q = q
        self._multi_choice_vals = [str(c) for c in shuffled]
        self._show_mode("multiple")

        for i in range(4):
            row = self._multi_rows[i]
            cb = self._multi_checks[i]
            host = self._multi_text_hosts[i]
            var = self._multi_vars[i]
            var.set(False)
            if i < len(shuffled):
                try:
                    row.pack(fill="x", pady=6, padx=20)
                except Exception:
                    pass
                row.configure(bg=theme["btn"])
                cb.configure(bg=theme["btn"], activebackground=theme["btn_h"], state="disabled")
                host.configure(bg=theme["btn"])
                self._set_annotated_host(
                    host,
                    str(shuffled[i]),
                    bg=theme["btn"],
                    fg="#1A237E",
                    py_fg="#5C6BC0",
                    han_size=22,
                    py_size=10,
                    max_cols=14,
                )
            else:
                try:
                    row.pack_forget()
                except Exception:
                    pass

        self._submit_btn.configure(
            state="disabled",
            bg="#B0BEC5",
            cursor="arrow",
            command=lambda: None,
        )

        def enable():
            for i, c in enumerate(shuffled):
                try:
                    self._multi_checks[i].configure(state="normal")
                except Exception:
                    pass
            try:
                self._submit_btn.configure(
                    state="normal",
                    bg=theme["accent"],
                    cursor="hand2",
                    command=lambda: self._submit_multiple(q),
                )
            except Exception:
                pass

        self._start_answer_gate(enable)

    def _submit_multiple(self, q) -> None:
        choices = list(getattr(self, "_multi_choice_vals", []) or [])
        picked = [
            choices[i]
            for i, var in enumerate(self._multi_vars)
            if i < len(choices) and var.get()
        ]
        self._handle_answer(q, picked, self._win)

    def _prep_text(self, q, theme) -> None:
        self._active_q = q
        self._show_mode("text")
        try:
            self._entry.configure(state="normal")
            self._entry.delete(0, "end")
            self._entry.configure(state="disabled")
            self._entry.unbind("<Return>")
        except Exception:
            pass
        self._submit_btn.configure(
            state="disabled",
            bg="#B0BEC5",
            cursor="arrow",
            command=lambda: None,
        )

        def submit(_event=None):
            self._handle_answer(q, self._entry.get(), self._win)

        def enable():
            try:
                self._entry.configure(state="normal")
                self._entry.focus_set()
                self._entry.bind("<Return>", submit)
                self._submit_btn.configure(
                    state="normal",
                    bg=theme["accent"],
                    cursor="hand2",
                    command=submit,
                )
            except Exception:
                pass

        self._start_answer_gate(enable)

    def _handle_answer(self, q, response, win) -> None:
        if self._answered:
            return
        self._answered = True
        # Freeze controls in place (no destroy)
        self._gate_token += 1
        for b in self._choice_btns:
            try:
                b.set_enabled(False)
            except Exception:
                pass
        try:
            self._submit_btn.configure(state="disabled")
            self._entry.configure(state="disabled")
            for cb in self._multi_checks:
                cb.configure(state="disabled")
        except Exception:
            pass

        ok = bank_mod.check_answer(q, response)
        expected = q.get("a")
        log_answer(q.get("id"), q.get("subject", ""), ok, str(response), str(expected))
        rules_mod.record_answer(self.state, self.rules, ok)
        if ok:
            self.correct_count += 1
            self._set_feedback(
                f"太棒了！答对了　本组已对 {self.correct_count} 题",
                "#2E7D32",
            )
        else:
            self._set_feedback("再想想哦　下一题加油", "#C62828")
        self.idx += 1
        if win is not None:
            win.after(750, self._show_current)

    def _finish_set(self) -> None:
        n = len(self.set_qs)
        passed = rules_mod.passed_set(self.correct_count, n, self.rules)
        grant = 0.0
        if passed:
            grant = rules_mod.grant_unlock(self.state, self.rules, self.site_id)
        log.info(
            "quiz set done correct=%d/%d passed=%s grant=%.1f",
            self.correct_count,
            n,
            passed,
            grant,
        )
        win = self._ensure_shell()

        # Hide quiz chrome, show result on same window (no flash to desktop)
        try:
            self._quiz_frame.pack_forget()
        except Exception:
            pass
        rf = self._result_frame
        for w in list(rf.winfo_children()):
            try:
                w.destroy()
            except Exception:
                pass
        rf.pack(fill="both", expand=True)

        card_shadow = tk.Frame(rf, bg="#E8E0D5")
        card_shadow.place(relx=0.5, rely=0.45, anchor="center")
        border = tk.Frame(card_shadow, bg=CARD_BORDER, padx=5, pady=5)
        border.pack(padx=6, pady=6)
        card = tk.Frame(border, bg=CARD_BG, padx=40, pady=36)
        card.pack()

        if passed:
            title = f"太棒了！对了 {self.correct_count}/{n} 题"
            sub = f"解锁观看 {grant:.0f} 分钟　去看吧"
            color = "#2E7D32"
            btn_text = "🎉 去看吧！"
            emoji = "🌟"
        else:
            need = rules_mod.required_correct(n, self.rules)
            title = f"本组 {self.correct_count}/{n} 题"
            sub = f"还需要答对 {need} 题　再来一组"
            color = "#C62828"
            btn_text = "💪 再答一组"
            emoji = "💪"

        tk.Label(card, text=emoji, bg=CARD_BG, font=pyui.preferred_font(48)).pack(pady=(0, 8))
        pyui.render_annotated(
            card, title, bg=CARD_BG, fg=color, py_fg=color, han_size=28, py_size=12, max_cols=18
        ).pack(pady=6)
        pyui.render_annotated(
            card, sub, bg=CARD_BG, fg="#5D4037", py_fg="#8D6E63", han_size=18, py_size=10, max_cols=20
        ).pack(pady=8)

        def cont():
            self._close_win()
            self.on_finished(passed, grant)

        tk.Button(
            card,
            text=btn_text,
            font=pyui.preferred_font(22, "bold"),
            bg="#FFE082",
            fg="#3E2723",
            activebackground="#FFD54F",
            relief="flat",
            padx=28,
            pady=14,
            cursor="hand2",
            command=cont,
        ).pack(pady=18)

        if not passed:
            win.after(1800, cont)
