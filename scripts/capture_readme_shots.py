# -*- coding: utf-8 -*-
"""Capture clean README screenshots (quiz window + admin pages)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

WANT = [
    ("quiz-math.png", 172),     # shape / ball illustration
    ("quiz-animals.png", 54),   # cat / en_animals
    ("quiz-chinese.png", 25),   # mu / yuwen_mu
]

ADMIN_SHOTS = (
    "admin-login.png",
    "admin-stats.png",
    "admin-wrongbook.png",
)


def _optimize_image(path: Path, max_w: int = 1400, max_h: int = 1800, crop_ultrawide: bool = False) -> None:
    from PIL import Image

    shot = Image.open(path).convert("RGB")
    w, h = shot.size
    # Window-grabbed quiz shots and admin pages should not be side-cropped.
    if crop_ultrawide and w / max(h, 1) > 2.0:
        shot = shot.crop((int(w * 0.12), 0, int(w * 0.88), h))
        w, h = shot.size
    if h > max_h:
        shot = shot.crop((0, 0, w, max_h))
        w, h = shot.size
    if w > max_w:
        ratio = max_w / w
        shot = shot.resize((max_w, int(h * ratio)))
    path.parent.mkdir(parents=True, exist_ok=True)
    shot.save(path, format="PNG", optimize=True)
    print(f"saved {path} bytes={path.stat().st_size} dim={shot.size}", flush=True)


def grab_tk_window(win):
    """Capture a Tk window via PrintWindow (ImageGrab is black on high-DPI)."""
    import ctypes
    from ctypes import wintypes
    from PIL import Image

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hwnd = int(win.winfo_id())
    hwnd = user32.GetAncestor(hwnd, 2) or hwnd
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    if w <= 1 or h <= 1:
        raise RuntimeError(f"invalid window rect {w}x{h}")
    hwnd_dc = user32.GetWindowDC(hwnd)
    src_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    gdi32.SelectObject(src_dc, bmp)
    ok = user32.PrintWindow(hwnd, src_dc, 2)
    if not ok:
        user32.PrintWindow(hwnd, src_dc, 0)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER)]

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(src_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    im = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1).copy()
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(src_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)
    return im


def capture_child(out_dir: str, filename: str, qid: int) -> None:
    """Child entry: show one quiz and save PNG."""
    sys.path.insert(0, str(ROOT))
    import tkinter as tk
    from studyonpc import bank as bank_mod
    from studyonpc import quiz_ui
    from studyonpc import rules as rules_mod

    data = json.loads((ROOT / "data" / "banks" / "grade1-shenzhen.json").read_text(encoding="utf-8"))
    q = next(dict(x) for x in data["questions"] if int(x["id"]) == int(qid))
    print(f"child capture {filename} id={qid} image={q.get('image')} q={q.get('q')}", flush=True)

    root = tk.Tk()
    root.withdraw()
    cfg = rules_mod.RulesConfig.from_dict(
        {
            "questions_per_set": 1,
            "pass_ratio": 1.0,
            "unlock_minutes_per_set": 10,
            "answer_delay_seconds": 0.3,
        }
    )
    state = {
        "balance_minutes": 0,
        "daily_used_minutes": 0,
        "pending_extra": 0,
        "wrong_streak": 0,
        "recent_ids": [],
    }
    bank_mod.pick_set = lambda questions, n, recent, prefer_ids=None, **kwargs: [q]  # type: ignore

    runner = quiz_ui.QuizSetRunner(
        root=root,
        questions=[q],
        state=state,
        rules=cfg,
        parent_pin="changeme",
        on_finished=lambda *_: None,
        on_parent_quit=lambda: None,
    )
    runner.start()

    # Paint + wait for answer gate ("可以答题啦")
    end = time.time() + 3.0
    while time.time() < end:
        root.update()
        time.sleep(0.05)

    if runner._win is None:
        raise RuntimeError("quiz window missing")
    shot = grab_tk_window(runner._win)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / filename
    shot.convert("RGB").save(path, format="PNG")
    _optimize_image(path)

    try:
        if runner._win is not None:
            runner._win.destroy()
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass


def _admin_password() -> str:
    cfg_path = ROOT / "config.json"
    if not cfg_path.exists():
        return ""
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    return str(cfg.get("admin_password") or cfg.get("parent_pin") or "")


def capture_admin(out_dir: str) -> None:
    """Capture login / stats / wrong-book from the running admin server."""
    from playwright.sync_api import sync_playwright

    password = _admin_password()
    if not password:
        print("skip admin screenshots: no local admin password", flush=True)
        return

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chrome")
        page = browser.new_page(viewport={"width": 1440, "height": 780})
        page.goto("http://127.0.0.1:8099/admin", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_selector("#pw", timeout=10000)
        page.wait_for_timeout(300)
        login_path = out / "admin-login.png"
        page.screenshot(path=str(login_path), full_page=False)
        _optimize_image(login_path, max_h=800)
        page.set_viewport_size({"width": 1440, "height": 1100})

        page.fill("#pw", password)
        page.click("#login .btn")
        page.wait_for_selector("#panel", state="visible", timeout=10000)
        page.wait_for_timeout(400)

        page.click("button[data-tab='stats']")
        page.wait_for_selector("#tab-stats", state="visible")
        page.click("#statsRangeMonth")
        page.wait_for_timeout(900)
        stats_path = out / "admin-stats.png"
        page.screenshot(path=str(stats_path), full_page=True)
        _optimize_image(stats_path, max_h=1700)

        page.click("button[data-tab='wrongbook']")
        page.wait_for_selector("#tab-wrongbook", state="visible")
        page.wait_for_timeout(700)
        wb_path = out / "admin-wrongbook.png"
        page.screenshot(path=str(wb_path), full_page=False)
        _optimize_image(wb_path, max_h=1200)

        browser.close()
    print("ADMIN_OK", flush=True)


def main() -> None:
    if len(sys.argv) >= 4 and sys.argv[1] == "--one":
        capture_child(sys.argv[2], sys.argv[3], int(sys.argv[4]))
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "--admin":
        out_dir = sys.argv[2] if len(sys.argv) > 2 else str(ROOT / "docs" / "screenshots")
        capture_admin(out_dir)
        return

    out_dir = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "docs" / "screenshots")
    py = sys.executable
    script = str(Path(__file__).resolve())
    for name, qid in WANT:
        r = subprocess.run(
            [py, script, "--one", out_dir, name, str(qid)],
            cwd=str(ROOT),
            check=False,
        )
        if r.returncode != 0:
            raise SystemExit(f"capture failed for {name}: {r.returncode}")
        time.sleep(0.5)
    r = subprocess.run([py, script, "--admin", out_dir], cwd=str(ROOT), check=False)
    if r.returncode != 0:
        raise SystemExit(f"admin capture failed: {r.returncode}")
    print("ALL_OK")


if __name__ == "__main__":
    main()
