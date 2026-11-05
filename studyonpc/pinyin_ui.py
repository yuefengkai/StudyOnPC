# -*- coding: utf-8 -*-
"""Ruby-style 拼音标注 for kid-friendly tkinter UI.

Core annotate/tokenize helpers work without tkinter (Linux CI).
Widget builders import tkinter lazily.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tkinter as tk

# Han character range (CJK Unified + common ext)
_HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

try:
    from pypinyin import Style, pinyin as _pinyin

    HAS_PYPINYIN = True
except Exception:  # pragma: no cover
    HAS_PYPINYIN = False
    _pinyin = None  # type: ignore
    Style = None  # type: ignore


def is_han(ch: str) -> bool:
    return bool(ch) and bool(_HAN_RE.fullmatch(ch))


def char_pinyin(ch: str) -> str | None:
    """Return tone-marked pinyin for one Han character, else None."""
    if not is_han(ch):
        return None
    if not HAS_PYPINYIN:
        return "?"
    try:
        rows = _pinyin(ch, style=Style.TONE, heteronym=False)
        if rows and rows[0]:
            return str(rows[0][0])
    except Exception:
        return "?"
    return None


def tokenize(text: str) -> list[tuple[str, str | None]]:
    """Split into (glyph, pinyin|None). Consecutive non-Han stay grouped."""
    out: list[tuple[str, str | None]] = []
    buf: list[str] = []
    for ch in str(text or ""):
        if is_han(ch):
            if buf:
                out.append(("".join(buf), None))
                buf = []
            out.append((ch, char_pinyin(ch)))
        else:
            buf.append(ch)
    if buf:
        out.append(("".join(buf), None))
    return out


def annotate_string(text: str) -> str:
    """Plain-text annotation for tests / logs.

    Example for 「猴子」::

        hóu zi
        猴 子
    """
    text = str(text or "")
    if not text:
        return ""
    toks = tokenize(text)
    if not any(py for _, py in toks):
        return text
    top: list[str] = []
    bot: list[str] = []
    for glyph, py in toks:
        if py is None:
            top.append(glyph)
            bot.append(glyph)
        else:
            top.append(py)
            bot.append(glyph)
    return " ".join(top) + "\n" + " ".join(bot)


def annotate_inline(text: str) -> str:
    """Inline form: 猴(hóu)子(zi)."""
    text = str(text or "")
    parts: list[str] = []
    for glyph, py in tokenize(text):
        if py:
            parts.append(f"{glyph}({py})")
        else:
            parts.append(glyph)
    return "".join(parts)


def preferred_font(size: int, weight: str = "normal") -> tuple:
    for family in (
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "PingFang SC",
        "Noto Sans CJK SC",
        "Sans",
    ):
        if weight != "normal":
            return (family, size, weight)
        return (family, size)
    return ("Sans", size)


def _tk():
    import tkinter as tk

    return tk


def render_annotated(
    parent,
    text: str,
    *,
    bg: str = "#FFFFFF",
    fg: str = "#1A237E",
    py_fg: str = "#5C6BC0",
    han_size: int = 28,
    py_size: int = 11,
    max_cols: int = 14,
    justify: str = "center",
    pad_x: int = 2,
    pad_y: int = 1,
):
    """Build a Frame with ruby-style 拼音 above each Chinese character."""
    tk = _tk()
    outer = tk.Frame(parent, bg=bg)
    toks = tokenize(text)
    if not toks:
        tk.Label(outer, text="", bg=bg).pack()
        return outer

    rows: list[list[tuple[str, str | None]]] = []
    cur: list[tuple[str, str | None]] = []
    cols = 0
    for glyph, py in toks:
        w = 1 if py is not None else max(1, (len(glyph) + 1) // 2)
        if cur and cols + w > max_cols:
            rows.append(cur)
            cur = []
            cols = 0
        cur.append((glyph, py))
        cols += w
    if cur:
        rows.append(cur)

    han_font = preferred_font(han_size, "bold")
    py_font = preferred_font(py_size, "normal")

    for row in rows:
        row_f = tk.Frame(outer, bg=bg)
        if justify == "center":
            row_f.pack(anchor="center", pady=pad_y)
        else:
            row_f.pack(anchor="w", pady=pad_y)
        for glyph, py in row:
            cell = tk.Frame(row_f, bg=bg)
            cell.pack(side="left", padx=pad_x)
            tk.Label(
                cell,
                text=py or " ",
                bg=bg,
                fg=py_fg if py else bg,
                font=py_font,
            ).pack()
            tk.Label(
                cell,
                text=glyph,
                bg=bg,
                fg=fg,
                font=han_font,
            ).pack()
    return outer


def soft_card(
    parent,
    *,
    bg: str = "#FFFFFF",
    border: str = "#FFE0B2",
    padx: int = 18,
    pady: int = 14,
):
    """Nested frames to fake a soft card. Returns (shadow_outer, inner_content)."""
    tk = _tk()
    shadow = tk.Frame(parent, bg="#E0E0D5")
    card = tk.Frame(shadow, bg=border, padx=3, pady=3)
    card.pack(padx=3, pady=3)
    inner = tk.Frame(card, bg=bg, padx=padx, pady=pady)
    inner.pack(fill="both", expand=True)
    return shadow, inner


def make_choice_button(
    parent,
    text: str,
    *,
    command,
    bg: str = "#E3F2FD",
    bg_hover: str = "#BBDEFB",
    bg_press: str = "#90CAF9",
    bg_disabled: str = "#ECEFF1",
    fg: str = "#0D47A1",
    fg_disabled: str = "#90A4AE",
    py_fg: str = "#5C6BC0",
    width: int = 300,
    height: int = 100,
    accent: str = "#42A5F5",
    accent_disabled: str = "#B0BEC5",
    enabled: bool = True,
):
    """Fixed-size choice card. Hover/press only recolor bg — never resize or rebuild."""
    tk = _tk()
    colors = {
        "bg": bg,
        "bg_hover": bg_hover,
        "bg_press": bg_press,
        "bg_disabled": bg_disabled,
        "fg": fg,
        "fg_disabled": fg_disabled,
        "py_fg": py_fg,
        "accent": accent,
        "accent_disabled": accent_disabled,
    }
    state = {
        "enabled": bool(enabled),
        "command": command,
        "text": str(text or ""),
        "pressed": False,
        "hover": False,
    }

    # Fixed outer geometry — grid columns cannot shrink/grow this widget
    wrap = tk.Frame(
        parent,
        bg=colors["accent"] if state["enabled"] else colors["accent_disabled"],
        width=width,
        height=height,
        highlightthickness=0,
        bd=0,
        relief="flat",
        cursor="hand2" if state["enabled"] else "arrow",
    )
    wrap.pack_propagate(False)

    # Border via padx/pady (stable; no place() negative width)
    inner = tk.Frame(
        wrap,
        bg=colors["bg"] if state["enabled"] else colors["bg_disabled"],
        highlightthickness=0,
        bd=0,
        relief="flat",
    )
    inner.pack(fill="both", expand=True, padx=3, pady=3)

    # Fill click-catcher so empty padding still receives events
    fill = tk.Frame(inner, bg=inner.cget("bg"), highlightthickness=0, bd=0, relief="flat")
    fill.pack(fill="both", expand=True)

    content_host = tk.Frame(fill, bg=fill.cget("bg"), highlightthickness=0, bd=0, relief="flat")
    content_host.place(relx=0.5, rely=0.5, anchor="center")

    bg_targets: list = []

    def _collect_bg():
        bg_targets.clear()
        bg_targets.extend([wrap, inner, fill, content_host])

        def walk(w):
            for ch in w.winfo_children():
                bg_targets.append(ch)
                walk(ch)

        walk(content_host)

    def _paint_bgs(fill_color: str, border_color: str):
        """Hover path: ONLY bg. Never font, padx, pady, relief, width, height."""
        try:
            wrap.configure(bg=border_color)
        except Exception:
            pass
        for w in bg_targets:
            if w is wrap:
                continue
            try:
                w.configure(bg=fill_color)
            except Exception:
                pass

    def _face_colors():
        if not state["enabled"]:
            return colors["bg_disabled"], colors["accent_disabled"]
        if state["pressed"]:
            return colors["bg_press"], colors["accent"]
        if state["hover"]:
            return colors["bg_hover"], colors["accent"]
        return colors["bg"], colors["accent"]

    def _refresh_face():
        fill_color, border_color = _face_colors()
        _paint_bgs(fill_color, border_color)
        try:
            wrap.configure(cursor="hand2" if state["enabled"] else "arrow")
        except Exception:
            pass

    def _apply_text_colors():
        fg0 = colors["fg"] if state["enabled"] else colors["fg_disabled"]
        py0 = colors["py_fg"] if state["enabled"] else colors["fg_disabled"]
        fill_color, _ = _face_colors()

        def walk(w):
            try:
                if w.winfo_class() == "Label":
                    cur = str(w.cget("text") or "")
                    if not cur.strip():
                        w.configure(fg=fill_color)
                    else:
                        f = str(w.cget("font") or "")
                        if any(s in f for s in (" 9", " 10", " 11", ",9", ",10", ",11")):
                            w.configure(fg=py0)
                        else:
                            w.configure(fg=fg0)
            except Exception:
                pass
            for ch in w.winfo_children():
                walk(ch)

        walk(content_host)

    def _build_content():
        for w in list(content_host.winfo_children()):
            try:
                w.destroy()
            except Exception:
                pass
        bg0 = colors["bg"] if state["enabled"] else colors["bg_disabled"]
        fg0 = colors["fg"] if state["enabled"] else colors["fg_disabled"]
        py0 = colors["py_fg"] if state["enabled"] else colors["fg_disabled"]
        content_host.configure(bg=bg0)
        txt = state["text"]
        if not any(is_han(ch) for ch in str(txt or "")):
            tk.Label(
                content_host,
                text=str(txt or ""),
                bg=bg0,
                fg=fg0,
                font=preferred_font(26, "bold"),
                justify="center",
                highlightthickness=0,
                bd=0,
                relief="flat",
            ).pack()
        else:
            render_annotated(
                content_host,
                txt,
                bg=bg0,
                fg=fg0,
                py_fg=py0,
                han_size=26,
                py_size=11,
                max_cols=10,
            ).pack()
        _collect_bg()
        _bind_tree(content_host)
        state["hover"] = False
        state["pressed"] = False
        _refresh_face()
        _apply_text_colors()

    def _pointer_inside() -> bool:
        try:
            x, y = wrap.winfo_pointerxy()
            w = wrap.winfo_containing(x, y)
        except Exception:
            return False
        while w is not None:
            if w == wrap:
                return True
            try:
                parent = w.winfo_parent()
                if not parent:
                    break
                w = w.nametowidget(parent)
            except Exception:
                break
        return False

    def on_enter(_e=None):
        if not state["enabled"]:
            return
        state["hover"] = True
        _refresh_face()

    def on_leave(_e=None):
        if not state["enabled"]:
            return

        def _check():
            if not state["enabled"]:
                return
            inside = _pointer_inside()
            state["hover"] = inside
            if not inside:
                state["pressed"] = False
            _refresh_face()

        try:
            wrap.after_idle(_check)
        except Exception:
            state["hover"] = False
            state["pressed"] = False
            _refresh_face()

    def on_press(_e=None):
        if not state["enabled"]:
            return
        state["pressed"] = True
        _refresh_face()

    def on_release(_e=None):
        if not state["enabled"]:
            return
        was_pressed = state["pressed"]
        state["pressed"] = False
        state["hover"] = _pointer_inside()
        _refresh_face()
        if was_pressed and state["hover"]:
            cmd = state.get("command")
            if cmd:
                cmd()

    def _bind_tree(widget):
        widget.bind("<Enter>", on_enter, add="+")
        widget.bind("<Leave>", on_leave, add="+")
        widget.bind("<ButtonPress-1>", on_press, add="+")
        widget.bind("<ButtonRelease-1>", on_release, add="+")
        for ch in widget.winfo_children():
            _bind_tree(ch)

    def set_enabled(v: bool):
        state["enabled"] = bool(v)
        state["pressed"] = False
        if not v:
            state["hover"] = False
        _refresh_face()
        _apply_text_colors()

    def set_text(new_text: str):
        state["text"] = str(new_text or "")
        _build_content()

    def set_command(cmd):
        state["command"] = cmd

    def set_colors(
        *,
        bg=None,
        bg_hover=None,
        bg_press=None,
        fg=None,
        py_fg=None,
        accent=None,
    ):
        if bg is not None:
            colors["bg"] = bg
        if bg_hover is not None:
            colors["bg_hover"] = bg_hover
        if bg_press is not None:
            colors["bg_press"] = bg_press
        if fg is not None:
            colors["fg"] = fg
        if py_fg is not None:
            colors["py_fg"] = py_fg
        if accent is not None:
            colors["accent"] = accent
        _refresh_face()
        _apply_text_colors()

    _build_content()
    _bind_tree(wrap)

    wrap.set_enabled = set_enabled  # type: ignore[attr-defined]
    wrap.set_text = set_text  # type: ignore[attr-defined]
    wrap.set_command = set_command  # type: ignore[attr-defined]
    wrap.set_colors = set_colors  # type: ignore[attr-defined]
    wrap._choice_state = state  # type: ignore[attr-defined]
    return wrap
