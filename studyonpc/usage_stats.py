# -*- coding: utf-8 -*-
"""Daily usage rollups for parent day/week/month stats."""
from __future__ import annotations

import json
import logging
import re
import threading
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .paths import ANSWER_LOG, USAGE_DAILY_PATH, ensure_runtime_dirs

log = logging.getLogger("studyonpc.usage_stats")
_lock = threading.RLock()

_ANSWER_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*"
    r"id=(?P<id>[^|]*)\|\s*(?P<subject>[^|]*)\|\s*(?P<ok>OK|WRONG)\s*\|"
    r"(?:.*?\|\s*)?(?:mode=(?P<mode>\w+))?"
    r"(?:.*?\|\s*)?(?:unit=(?P<unit>[^|]*))?"
    r"(?:.*?\|\s*)?(?:site=(?P<site>[^|]*))?",
    re.IGNORECASE,
)


def _today() -> str:
    return date.today().isoformat()


def _empty_day(day: str) -> dict[str, Any]:
    return {
        "date": day,
        "watch_minutes": 0.0,
        "site_used": {},
        "unlock_minutes": 0.0,
        "bonus_minutes": 0.0,
        "answers_ok": 0,
        "answers_total": 0,
        "sets_normal": 0,
        "sets_challenge": 0,
        "sets_passed_normal": 0,
        "sets_passed_challenge": 0,
        "subject_ok": {},
        "subject_total": {},
        "hour_answers": {},
        "max_correct_streak": 0,
        "current_correct_streak": 0,
        "updated_at": "",
    }


def _load_all() -> dict[str, dict[str, Any]]:
    ensure_runtime_dirs()
    if not USAGE_DAILY_PATH.exists():
        return {}
    try:
        raw = json.loads(USAGE_DAILY_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            out: dict[str, dict[str, Any]] = {}
            for k, v in raw.items():
                if isinstance(v, dict):
                    row = _empty_day(str(k))
                    row.update(v)
                    row["date"] = str(k)
                    out[str(k)] = row
            return out
    except Exception as e:
        log.warning("usage_daily load failed: %s", e)
    return {}


def _save_all(data: dict[str, dict[str, Any]]) -> None:
    ensure_runtime_dirs()
    payload = {k: data[k] for k in sorted(data.keys())}
    tmp = USAGE_DAILY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(USAGE_DAILY_PATH)


def get_day(day: str | None = None) -> dict[str, Any]:
    day = day or _today()
    with _lock:
        data = _load_all()
        return deepcopy(data.get(day) or _empty_day(day))


def _upsert(day: str, mutator) -> dict[str, Any]:
    with _lock:
        data = _load_all()
        row = data.get(day) or _empty_day(day)
        mutator(row)
        row["date"] = day
        row["updated_at"] = datetime.now().isoformat(timespec="seconds")
        data[day] = row
        _save_all(data)
        return deepcopy(row)


def sync_from_state(st: dict[str, Any]) -> None:
    """Mirror today's watch/unlock/bonus counters from state into usage_daily."""
    day = str(st.get("daily_date") or _today())
    def mut(row: dict[str, Any]) -> None:
        row["watch_minutes"] = round(float(st.get("daily_used_minutes", 0.0) or 0.0), 2)
        row["unlock_minutes"] = round(float(st.get("today_unlock_minutes", 0.0) or 0.0), 2)
        row["bonus_minutes"] = round(float(st.get("today_bonus_minutes", 0.0) or 0.0), 2)
        site = st.get("site_daily_used") or {}
        if isinstance(site, dict):
            row["site_used"] = {str(k): round(float(v or 0), 2) for k, v in site.items()}
    _upsert(day, mut)


def archive_day_from_state(day: str, st: dict[str, Any]) -> None:
    """Call before daily rollover clears today's counters."""
    if not day:
        return
    sync_from_state({**st, "daily_date": day})


def note_answer(
    *,
    correct: bool,
    subject: str = "",
    mode: str = "normal",
    unit: str = "",
    site_id: str = "",
    when: datetime | None = None,
) -> None:
    when = when or datetime.now()
    day = when.date().isoformat()
    hour = str(when.hour)
    subject = (subject or "未分类").strip() or "未分类"

    def mut(row: dict[str, Any]) -> None:
        row["answers_total"] = int(row.get("answers_total", 0)) + 1
        if correct:
            row["answers_ok"] = int(row.get("answers_ok", 0)) + 1
            streak = int(row.get("current_correct_streak", 0)) + 1
            row["current_correct_streak"] = streak
            row["max_correct_streak"] = max(int(row.get("max_correct_streak", 0)), streak)
        else:
            row["current_correct_streak"] = 0
        sub_t = dict(row.get("subject_total") or {})
        sub_o = dict(row.get("subject_ok") or {})
        sub_t[subject] = int(sub_t.get(subject, 0)) + 1
        if correct:
            sub_o[subject] = int(sub_o.get(subject, 0)) + 1
        row["subject_total"] = sub_t
        row["subject_ok"] = sub_o
        hours = dict(row.get("hour_answers") or {})
        hours[hour] = int(hours.get(hour, 0)) + 1
        row["hour_answers"] = hours
        # keep mode/unit/site lightly for debugging totals
        _ = (mode, unit, site_id)

    _upsert(day, mut)


def note_set(*, challenge: bool, passed: bool, grant: float = 0.0) -> None:
    day = _today()
    _ = grant  # grant minutes come from state sync / note_bonus

    def mut(row: dict[str, Any]) -> None:
        if challenge:
            row["sets_challenge"] = int(row.get("sets_challenge", 0)) + 1
            if passed:
                row["sets_passed_challenge"] = int(row.get("sets_passed_challenge", 0)) + 1
        else:
            row["sets_normal"] = int(row.get("sets_normal", 0)) + 1
            if passed:
                row["sets_passed_normal"] = int(row.get("sets_passed_normal", 0)) + 1

    _upsert(day, mut)


def note_bonus(minutes: float) -> None:
    if minutes <= 0:
        return
    day = _today()

    def mut(row: dict[str, Any]) -> None:
        row["bonus_minutes"] = round(float(row.get("bonus_minutes", 0.0)) + float(minutes), 2)

    _upsert(day, mut)


def _parse_answer_line(line: str) -> dict[str, Any] | None:
    parts = [p.strip() for p in line.split("|")]
    if len(parts) < 4:
        return None
    ts = parts[0]
    try:
        when = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None
    ok_token = parts[3]
    subject = parts[2] if len(parts) > 2 else ""
    extra = {}
    for p in parts[4:]:
        if "=" in p:
            k, _, v = p.partition("=")
            extra[k.strip().lower()] = v.strip().strip("'\"")
    return {
        "when": when,
        "day": when.date().isoformat(),
        "hour": str(when.hour),
        "subject": subject or "未分类",
        "ok": ok_token == "OK",
        "mode": extra.get("mode", ""),
        "unit": extra.get("unit", ""),
        "site": extra.get("site", ""),
    }


def backfill_from_answers(log_path: Path | None = None) -> int:
    """Rebuild answer-derived fields from answers.log without wiping watch/bonus."""
    path = log_path or ANSWER_LOG
    if not path.exists():
        return 0
    by_day: dict[str, list[dict[str, Any]]] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            row = _parse_answer_line(line)
            if not row:
                continue
            by_day.setdefault(row["day"], []).append(row)
    except Exception as e:
        log.warning("backfill answers failed: %s", e)
        return 0

    with _lock:
        data = _load_all()
        for day, rows in by_day.items():
            cur = data.get(day) or _empty_day(day)
            # recompute answer-derived fields
            cur["answers_ok"] = 0
            cur["answers_total"] = 0
            cur["subject_ok"] = {}
            cur["subject_total"] = {}
            cur["hour_answers"] = {}
            cur["max_correct_streak"] = 0
            streak = 0
            for r in sorted(rows, key=lambda x: x["when"]):
                cur["answers_total"] += 1
                sub = r["subject"] or "未分类"
                cur["subject_total"][sub] = int(cur["subject_total"].get(sub, 0)) + 1
                cur["hour_answers"][r["hour"]] = int(cur["hour_answers"].get(r["hour"], 0)) + 1
                if r["ok"]:
                    cur["answers_ok"] += 1
                    cur["subject_ok"][sub] = int(cur["subject_ok"].get(sub, 0)) + 1
                    streak += 1
                    cur["max_correct_streak"] = max(cur["max_correct_streak"], streak)
                else:
                    streak = 0
            cur["current_correct_streak"] = streak
            cur["updated_at"] = datetime.now().isoformat(timespec="seconds")
            data[day] = cur
        _save_all(data)
    return sum(len(v) for v in by_day.values())


def _daterange(start: date, end: date) -> list[str]:
    out = []
    cur = start
    while cur <= end:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def _sum_days(days: list[str], data: dict[str, dict[str, Any]]) -> dict[str, Any]:
    agg = _empty_day(days[0] if len(days) == 1 else f"{days[0]}..{days[-1]}")
    agg["days"] = []
    max_streak = 0
    for d in days:
        row = data.get(d) or _empty_day(d)
        agg["days"].append({
            "date": d,
            "watch_minutes": float(row.get("watch_minutes", 0)),
            "answers_ok": int(row.get("answers_ok", 0)),
            "answers_total": int(row.get("answers_total", 0)),
            "success_rate": (
                round(100.0 * int(row.get("answers_ok", 0)) / int(row.get("answers_total", 0)), 1)
                if int(row.get("answers_total", 0)) else None
            ),
            "sets_normal": int(row.get("sets_normal", 0)),
            "sets_challenge": int(row.get("sets_challenge", 0)),
            "bonus_minutes": float(row.get("bonus_minutes", 0)),
            "unlock_minutes": float(row.get("unlock_minutes", 0)),
            "max_correct_streak": int(row.get("max_correct_streak", 0)),
        })
        agg["watch_minutes"] = float(agg["watch_minutes"]) + float(row.get("watch_minutes", 0))
        agg["unlock_minutes"] = float(agg["unlock_minutes"]) + float(row.get("unlock_minutes", 0))
        agg["bonus_minutes"] = float(agg["bonus_minutes"]) + float(row.get("bonus_minutes", 0))
        agg["answers_ok"] = int(agg["answers_ok"]) + int(row.get("answers_ok", 0))
        agg["answers_total"] = int(agg["answers_total"]) + int(row.get("answers_total", 0))
        agg["sets_normal"] = int(agg["sets_normal"]) + int(row.get("sets_normal", 0))
        agg["sets_challenge"] = int(agg["sets_challenge"]) + int(row.get("sets_challenge", 0))
        agg["sets_passed_normal"] = int(agg["sets_passed_normal"]) + int(row.get("sets_passed_normal", 0))
        agg["sets_passed_challenge"] = int(agg["sets_passed_challenge"]) + int(row.get("sets_passed_challenge", 0))
        max_streak = max(max_streak, int(row.get("max_correct_streak", 0)))
        for k, v in (row.get("subject_total") or {}).items():
            agg["subject_total"][k] = int(agg["subject_total"].get(k, 0)) + int(v)
        for k, v in (row.get("subject_ok") or {}).items():
            agg["subject_ok"][k] = int(agg["subject_ok"].get(k, 0)) + int(v)
        for k, v in (row.get("hour_answers") or {}).items():
            agg["hour_answers"][k] = int(agg["hour_answers"].get(k, 0)) + int(v)
        for k, v in (row.get("site_used") or {}).items():
            agg["site_used"][k] = round(float(agg["site_used"].get(k, 0)) + float(v), 2)
    agg["max_correct_streak"] = max_streak
    total = int(agg["answers_total"])
    agg["success_rate"] = round(100.0 * int(agg["answers_ok"]) / total, 1) if total else None
    # peak hours top 3
    hours_sorted = sorted((agg.get("hour_answers") or {}).items(), key=lambda kv: (-int(kv[1]), int(kv[0])))
    agg["peak_hours"] = [{"hour": int(h), "answers": int(c)} for h, c in hours_sorted[:3]]
    # subject breakdown
    subjects = []
    for name, tot in sorted((agg.get("subject_total") or {}).items(), key=lambda kv: -int(kv[1])):
        ok = int((agg.get("subject_ok") or {}).get(name, 0))
        subjects.append({
            "subject": name,
            "total": int(tot),
            "ok": ok,
            "success_rate": round(100.0 * ok / int(tot), 1) if int(tot) else None,
        })
    agg["subjects"] = subjects
    agg["watch_minutes"] = round(float(agg["watch_minutes"]), 2)
    agg["unlock_minutes"] = round(float(agg["unlock_minutes"]), 2)
    agg["bonus_minutes"] = round(float(agg["bonus_minutes"]), 2)
    return agg


def summarize(range_name: str = "day", anchor: str | None = None) -> dict[str, Any]:
    """range_name: day|week|month. anchor: YYYY-MM-DD (default today)."""
    try:
        data_probe = _load_all()
        if ANSWER_LOG.exists() and (not data_probe or all(int(v.get("answers_total") or 0) == 0 for v in data_probe.values())):
            backfill_from_answers()
    except Exception as e:
        log.warning("auto backfill: %s", e)
    anchor_d = date.fromisoformat(anchor) if anchor else date.today()
    if range_name == "week":
        start = anchor_d - timedelta(days=anchor_d.weekday())  # Monday
        end = start + timedelta(days=6)
    elif range_name == "month":
        start = anchor_d.replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = start.replace(month=start.month + 1, day=1) - timedelta(days=1)
    else:
        start = end = anchor_d
    days = _daterange(start, end)
    with _lock:
        data = _load_all()
        # ensure today mirrored if asking about today
        agg = _sum_days(days, data)
    return {
        "range": range_name,
        "anchor": anchor_d.isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "summary": agg,
    }
