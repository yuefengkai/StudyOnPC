# -*- coding: utf-8 -*-
"""Capture clean README screenshots (one illustrated question per subprocess)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

WANT = [
    ("quiz-math.png", 1),       # 3+2 illustration
    ("quiz-animals.png", 54),   # cat / en_animals
    ("quiz-chinese.png", 25),   # 目 / yuwen_mu (simple illustrated)
]


def capture_child(out_dir: str, filename: str, qid: int) -> None:
    """Child entry: show one quiz and save PNG."""
    sys.path.insert(0, str(ROOT))
    import tkinter as tk
    from PIL import ImageGrab
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
    bank_mod.pick_set = lambda questions, n, recent: [q]  # type: ignore

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
    end = time.time() + 2.5
    while time.time() < end:
        root.update()
        time.sleep(0.05)

    shot = ImageGrab.grab()
    w, h = shot.size
    if w / max(h, 1) > 1.8:
        shot = shot.crop((int(w * 0.12), 0, int(w * 0.88), h))
    max_w = 1400
    if shot.width > max_w:
        ratio = max_w / shot.width
        shot = shot.resize((max_w, int(shot.height * ratio)))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / filename
    shot.convert("RGB").save(path, format="PNG", optimize=True)
    print(f"saved {path} bytes={path.stat().st_size} dim={shot.size}", flush=True)

    try:
        if runner._win is not None:
            runner._win.destroy()
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass


def main() -> None:
    if len(sys.argv) >= 4 and sys.argv[1] == "--one":
        capture_child(sys.argv[2], sys.argv[3], int(sys.argv[4]))
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
    print("ALL_OK")


if __name__ == "__main__":
    main()
