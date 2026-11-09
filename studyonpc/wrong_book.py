# -*- coding: utf-8 -*-
"""Wrong-question book: track misses and prefer them on the next unlock set."""
from __future__ import annotations

import json
import logging
import re
import threading
from copy import deepcopy
from datetime import datetime
from typing import Any

from .paths import ANSWER_LOG, WRONG_BOOK_PATH, ensure_runtime_dirs

log = logging.getLogger("studyonpc.wrong_book")
_lock = threading.RLock()

MASTER_STREAK = 2  # consecutive correct answers to mark mastered
STEM_MAX = 120

_ANSWER_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*"
    r"id=(?P<id>[^|]*)\|\s*(?P<subject>[^|]*)\|\s*(?P<ok>OK|WRONG)\s*\|"
    r"(?:.*?chose=(?P<chose>[^|]*))?"
    r"(?:.*?expect=(?P<expect>[^|]*))?"
    r"(?:.*?\|\s*)?(?:mode=(?P<mode>\w+))?"
    r"(?:.*?\|\s*)?(?:unit=(?P<unit>[^|]*))?"
    r"(?:.*?\|\s*)?(?:site=(?P<site>[^|]*))?"
    r"(?:.*?\|\s*)?(?:q=(?P<q>[^|]*))?",
    re.IGNORECASE,
)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _qid_key(qid: Any) -> str | None:
    if qid is None:
        return None
    s = str(qid).strip()
    if not s or s.lower() in ("none", "null"):
        return None
    return s


def _normalize_qid_value(qid: Any) -> Any:
    """Keep int ids as int when possible for bank matching."""
    if qid is None:
        return None
    if isinstance(qid, int):
        return qid
    s = str(qid).strip()
    if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
        try:
            return int(s)
        except Exception:
            return s
    return s


def _stem_summary(stem: str) -> str:
    text = " ".join(str(stem or "").split())
    if len(text) <= STEM_MAX:
        return text
    return text[: STEM_MAX - 1] + "…"


def _answer_text(answer: Any) -> str:
    if isinstance(answer, list):
        return " | ".join(str(x) for x in answer)
    return str(answer if answer is not None else "")


def _empty_entry(qid: Any) -> dict[str, Any]:
    return {
        "question_id": _normalize_qid_value(qid),
        "subject": "",
        "stem": "",
        "correct_answer": "",
        "last_wrong_choice": "",
        "wrong_count": 0,
        "correct_streak": 0,
        "last_wrong_at": "",
        "last_correct_at": "",
        "mastered": False,
        "site_id": "",
        "mode": "",
    }


def _load() -> dict[str, dict[str, Any]]:
    ensure_runtime_dirs()
    if not WRONG_BOOK_PATH.exists():
        return {}
    try:
        raw = json.loads(WRONG_BOOK_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("items"), dict):
            items = raw["items"]
        elif isinstance(raw, dict):
            items = raw
        else:
            return {}
        out: dict[str, dict[str, Any]] = {}
        for k, v in items.items():
            key = _qid_key(k)
            if not key or not isinstance(v, dict):
                continue
            row = _empty_entry(v.get("question_id", key))
            row.update(v)
            row["question_id"] = _normalize_qid_value(row.get("question_id", key))
            row["wrong_count"] = int(row.get("wrong_count") or 0)
            row["correct_streak"] = int(row.get("correct_streak") or 0)
            row["mastered"] = bool(row.get("mastered"))
            out[key] = row
        return out
    except Exception as e:
        log.warning("wrong_book load failed: %s", e)
        return {}


def _save(items: dict[str, dict[str, Any]]) -> None:
    ensure_runtime_dirs()
    payload = {
        "version": 1,
        "updated_at": _now_iso(),
        "items": {k: items[k] for k in sorted(items.keys(), key=lambda x: (len(x), x))},
    }
    tmp = WRONG_BOOK_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(WRONG_BOOK_PATH)


def note_wrong(
    qid: Any,
    *,
    subject: str = "",
    stem: str = "",
    correct_answer: Any = "",
    chosen_answer: Any = "",
    site_id: str = "",
    mode: str = "",
    when: datetime | None = None,
) -> dict[str, Any] | None:
    key = _qid_key(qid)
    if not key:
        return None
    ts = (when or datetime.now()).isoformat(timespec="seconds")
    with _lock:
        items = _load()
        row = items.get(key) or _empty_entry(qid)
        row["question_id"] = _normalize_qid_value(qid)
        if subject:
            row["subject"] = str(subject)
        if stem:
            row["stem"] = _stem_summary(stem)
        if correct_answer is not None and str(correct_answer) != "":
            row["correct_answer"] = _answer_text(correct_answer)
        if chosen_answer is not None and str(chosen_answer) != "":
            row["last_wrong_choice"] = _answer_text(chosen_answer)
        if site_id:
            row["site_id"] = str(site_id)
        if mode:
            row["mode"] = str(mode)
        row["wrong_count"] = int(row.get("wrong_count") or 0) + 1
        row["correct_streak"] = 0
        row["mastered"] = False
        row["last_wrong_at"] = ts
        items[key] = row
        _save(items)
        return deepcopy(row)


def note_correct(
    qid: Any,
    *,
    subject: str = "",
    stem: str = "",
    correct_answer: Any = "",
    site_id: str = "",
    mode: str = "",
    when: datetime | None = None,
) -> dict[str, Any] | None:
    """Record a correct answer. Creates no new entry unless one already exists."""
    key = _qid_key(qid)
    if not key:
        return None
    ts = (when or datetime.now()).isoformat(timespec="seconds")
    with _lock:
        items = _load()
        row = items.get(key)
        if row is None:
            return None
        if subject:
            row["subject"] = str(subject)
        if stem:
            row["stem"] = _stem_summary(stem)
        if correct_answer is not None and str(correct_answer) != "":
            row["correct_answer"] = _answer_text(correct_answer)
        if site_id:
            row["site_id"] = str(site_id)
        if mode:
            row["mode"] = str(mode)
        streak = int(row.get("correct_streak") or 0) + 1
        row["correct_streak"] = streak
        row["last_correct_at"] = ts
        if streak >= MASTER_STREAK:
            row["mastered"] = True
        items[key] = row
        _save(items)
        return deepcopy(row)


def list_entries(filter: str = "open") -> list[dict[str, Any]]:
    """filter: open (unmastered) | all | mastered"""
    filt = (filter or "open").strip().lower()
    with _lock:
        items = _load()
        rows = list(items.values())
    if filt in ("open", "unmastered", "active"):
        rows = [r for r in rows if not r.get("mastered")]
    elif filt in ("mastered", "done"):
        rows = [r for r in rows if r.get("mastered")]
    # else all
    # unmastered first, then more wrongs, then newest last_wrong
    rows.sort(
        key=lambda r: (
            0 if not r.get("mastered") else 1,
            -int(r.get("wrong_count") or 0),
            str(r.get("last_wrong_at") or ""),
        )
    )
    return [deepcopy(r) for r in rows]


def open_question_ids() -> list[Any]:
    """Unmastered question ids (native types) for prefer-picking."""
    with _lock:
        items = _load()
        out = []
        for row in items.values():
            if row.get("mastered"):
                continue
            qid = row.get("question_id")
            if qid is None:
                continue
            out.append(qid)
        return out


def clear_mastered() -> int:
    with _lock:
        items = _load()
        keep = {k: v for k, v in items.items() if not v.get("mastered")}
        removed = len(items) - len(keep)
        if removed:
            _save(keep)
        return removed


def counts() -> dict[str, int]:
    with _lock:
        items = _load()
        open_n = sum(1 for v in items.values() if not v.get("mastered"))
        return {"total": len(items), "open": open_n, "mastered": len(items) - open_n}



def _is_placeholder_stem(stem: str) -> bool:
    s = (stem or "").strip()
    return (not s) or s.startswith("（来自") or s.startswith("(来自")


def enrich_stems_from_bank(cfg: dict[str, Any] | None = None) -> int:
    """Fill missing/placeholder stems from the active question banks. Returns updated rows."""
    try:
        from . import bank as bank_mod
    except Exception as e:
        log.warning("enrich stems: bank import failed: %s", e)
        return 0
    cfg = cfg or {}
    by_id: dict[str, dict[str, Any]] = {}
    try:
        for loader in (bank_mod.load_questions, bank_mod.load_challenge_questions):
            try:
                for q in loader(cfg) or []:
                    qid = q.get("id")
                    key = _qid_key(qid)
                    if key and key not in by_id:
                        by_id[key] = q
            except Exception as e:
                log.warning("enrich stems load: %s", e)
    except Exception as e:
        log.warning("enrich stems banks: %s", e)
        return 0
    updated = 0
    with _lock:
        items = _load()
        for key, row in items.items():
            if not _is_placeholder_stem(row.get("stem") or ""):
                continue
            qid = row.get("question_id")
            qkey = _qid_key(qid)
            item = by_id.get(qkey) if qkey else None
            if not item:
                continue
            stem = str(item.get("q") or "")
            if not stem:
                continue
            row["stem"] = _stem_summary(stem)
            subject = str(item.get("subject") or "")
            if subject and not row.get("subject"):
                row["subject"] = subject
            answer = _answer_text(item.get("a"))
            if answer and (
                not row.get("correct_answer")
                or str(row.get("correct_answer")).strip() in ("", "None")
            ):
                row["correct_answer"] = answer
            items[key] = row
            updated += 1
        if updated:
            _save(items)
            log.info("wrong_book enrich_stems: updated %d", updated)
    return updated


def maybe_backfill_from_answers(force: bool = False) -> int:
    """If wrong_book.json missing (or force), rebuild lightly from answers.log.

    Processes chronologically: WRONG creates/bumps entries; OK advances streak
    only for ids already in the book. Lines without a usable id are skipped.
    Returns number of WRONG lines applied.
    """
    ensure_runtime_dirs()
    with _lock:
        if WRONG_BOOK_PATH.exists() and not force:
            return 0
        if not ANSWER_LOG.exists():
            if not WRONG_BOOK_PATH.exists():
                _save({})
            return 0
        try:
            lines = ANSWER_LOG.read_text(encoding="utf-8").splitlines()
        except Exception as e:
            log.warning("wrong_book backfill read failed: %s", e)
            return 0

        items: dict[str, dict[str, Any]] = {}
        wrong_applied = 0
        for line in lines:
            m = _ANSWER_RE.match(line.strip())
            if not m:
                # fallback split parser
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 4:
                    continue
                ts = parts[0]
                id_part = parts[1]
                subject = parts[2]
                ok_flag = parts[3]
                if not id_part.startswith("id="):
                    continue
                qid_raw = id_part[3:].strip()
                key = _qid_key(qid_raw)
                if not key:
                    continue
                expect = ""
                mode = ""
                site = ""
                stem_from_log = ""
                chose_from_log = ""
                for p in parts[4:]:
                    if p.startswith("expect="):
                        expect = p[7:].strip().strip("'\"")
                    elif p.startswith("mode="):
                        mode = p[5:].strip()
                    elif p.startswith("site="):
                        site = p[5:].strip()
                    elif p.startswith("q="):
                        stem_from_log = p[2:].strip().strip("'\"")
                    elif p.startswith("chose="):
                        chose_from_log = p[6:].strip().strip("'\"")
                is_ok = ok_flag == "OK"
            else:
                qid_raw = (m.group("id") or "").strip()
                key = _qid_key(qid_raw)
                if not key:
                    continue
                ts = m.group("ts")
                subject = (m.group("subject") or "").strip()
                is_ok = (m.group("ok") or "").upper() == "OK"
                expect = (m.group("expect") or "").strip().strip("'\"")
                mode = (m.group("mode") or "").strip()
                site = (m.group("site") or "").strip()
                stem_from_log = (m.groupdict().get("q") or "").strip().strip("'\"")
                chose_from_log = (m.groupdict().get("chose") or "").strip().strip("'\"")

            if is_ok:
                row = items.get(key)
                if not row:
                    continue
                row["correct_streak"] = int(row.get("correct_streak") or 0) + 1
                row["last_correct_at"] = ts.replace(" ", "T") if "T" not in ts else ts
                if row["correct_streak"] >= MASTER_STREAK:
                    row["mastered"] = True
                continue

            # WRONG
            row = items.get(key) or _empty_entry(qid_raw)
            row["question_id"] = _normalize_qid_value(qid_raw)
            if subject:
                row["subject"] = subject
            if expect:
                row["correct_answer"] = expect
            if mode:
                row["mode"] = mode
            if site:
                row["site_id"] = site
            if stem_from_log:
                row["stem"] = _stem_summary(stem_from_log)
            elif _is_placeholder_stem(row.get("stem") or ""):
                row["stem"] = "（来自答题记录）"
            if chose_from_log:
                row["last_wrong_choice"] = _answer_text(chose_from_log)
            row["wrong_count"] = int(row.get("wrong_count") or 0) + 1
            row["correct_streak"] = 0
            row["mastered"] = False
            row["last_wrong_at"] = ts.replace(" ", "T") if "T" not in ts else ts
            items[key] = row
            wrong_applied += 1

        _save(items)
        log.info("wrong_book backfill: %d WRONG lines -> %d entries", wrong_applied, len(items))
        return wrong_applied



def backfill_wrong_choices_from_answers() -> int:
    """Fill last_wrong_choice from the latest WRONG line per question id in answers.log."""
    if not ANSWER_LOG.exists():
        return 0
    latest: dict[str, str] = {}
    try:
        for line in ANSWER_LOG.read_text(encoding="utf-8").splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 5:
                continue
            if parts[3] != "WRONG":
                continue
            if not parts[1].startswith("id="):
                continue
            key = _qid_key(parts[1][3:].strip())
            if not key:
                continue
            chose = ""
            for p in parts[4:]:
                if p.startswith("chose="):
                    chose = p[6:].strip().strip("'\"")
                    break
            if chose:
                latest[key] = chose
    except Exception as e:
        log.warning("backfill wrong choices: %s", e)
        return 0
    updated = 0
    with _lock:
        items = _load()
        for key, row in items.items():
            if str(row.get("last_wrong_choice") or "").strip():
                continue
            chose = latest.get(key)
            if not chose:
                continue
            row["last_wrong_choice"] = _answer_text(chose)
            items[key] = row
            updated += 1
        if updated:
            _save(items)
            log.info("wrong_book backfill choices: %d", updated)
    return updated


def ensure_ready(cfg: dict[str, Any] | None = None) -> None:
    """Startup hook: backfill once if absent, then fill stems from banks when possible."""
    try:
        maybe_backfill_from_answers(force=False)
    except Exception as e:
        log.warning("wrong_book ensure_ready: %s", e)
    try:
        enrich_stems_from_bank(cfg)
    except Exception as e:
        log.warning("wrong_book enrich on ready: %s", e)
    try:
        backfill_wrong_choices_from_answers()
    except Exception as e:
        log.warning("wrong_book choice backfill on ready: %s", e)
