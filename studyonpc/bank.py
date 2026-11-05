# -*- coding: utf-8 -*-
"""Question bank load / normalize (grade1 + StudyOnTV-like open formats)."""
from __future__ import annotations

import json
import os
import logging
import random
from pathlib import Path
from typing import Any

from .paths import APP_DIR, RESOURCE_ROOT, ROOT, ensure_runtime_dirs

log = logging.getLogger("studyonpc.bank")


def _as_list(v: Any) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def normalize_question(raw: dict[str, Any], fallback_id: int) -> dict[str, Any] | None:
    """Map internal grade1 or StudyOnTV-like item into internal schema.

    Internal:
      id, type (single|multiple|boolean|text), subject, unit, q,
      choices[], a (str|list), correct_indices[], image?, difficulty?, skip?
    """
    if not isinstance(raw, dict):
        return None
    qtext = raw.get("q") or raw.get("question") or raw.get("title") or ""
    if not str(qtext).strip():
        return None

    qtype = str(raw.get("type") or "single").lower().strip()
    # StudyOnTV aliases
    if qtype in ("judge", "truefalse", "tf", "bool"):
        qtype = "boolean"
    if qtype in ("choice", "select", "singlechoice"):
        qtype = "single"
    if qtype in ("multi", "multichoice", "multiplechoice"):
        qtype = "multiple"
    if qtype in ("subjective", "essay", "open"):
        # MVP: treat as text (manual compare) or skip
        qtype = "text"

    choices = list(raw.get("choices") or raw.get("answers") or raw.get("options") or [])
    choices = [str(c) for c in choices]

    correct_indices = raw.get("correctIndices") or raw.get("correct_indices") or []
    if isinstance(correct_indices, int):
        correct_indices = [correct_indices]
    correct_indices = [int(i) for i in correct_indices if str(i).lstrip("-").isdigit()]

    a = raw.get("a")
    if a is None:
        a = raw.get("answer")
    if a is None and correct_indices and choices:
        a = [choices[i] for i in correct_indices if 0 <= i < len(choices)]
        if qtype == "single" and len(a) == 1:
            a = a[0]
    if a is None and qtype == "boolean":
        # common patterns
        if "correct" in raw:
            a = "正确" if raw["correct"] else "错误"
        elif str(raw.get("k", "")).lower() in ("true", "yes", "1", "对", "正确"):
            a = "正确"

    if qtype == "boolean" and not choices:
        choices = ["正确", "错误"]

    # Skip empty subjective with no answer key for MVP auto-grade
    if qtype == "text" and a is None and not raw.get("k"):
        # allow show-as-text with keyword k
        if not raw.get("keywords"):
            log.info("skip subjective without key: %s", str(qtext)[:40])
            return None

    keywords = raw.get("k") or raw.get("keywords") or []
    keywords = [str(x) for x in _as_list(keywords)]

    qid = raw.get("id", fallback_id)
    try:
        qid = int(qid)
    except Exception:
        qid = fallback_id

    item: dict[str, Any] = {
        "id": qid,
        "type": qtype,
        "subject": str(raw.get("subject") or raw.get("tag") or ""),
        "unit": str(raw.get("unit") or ""),
        "q": str(qtext),
        "choices": choices,
        "a": a if a is not None else "",
        "correct_indices": correct_indices,
        "keywords": keywords,
        "difficulty": raw.get("difficulty", 1),
    }
    if raw.get("image"):
        item["image"] = str(raw["image"]).replace("\\", "/")
    return item


def load_bank_file(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        raws = data
    elif isinstance(data, dict):
        raws = data.get("questions") or data.get("items") or data.get("bank") or []
    else:
        raise ValueError(f"unsupported bank format: {path}")
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(raws, start=1):
        item = normalize_question(raw, fallback_id=i)
        if item:
            out.append(item)
    return out


def resolve_bank_path(cfg: dict[str, Any]) -> Path:
    ensure_runtime_dirs()
    rel = cfg.get("bank_file") or "data/banks/grade1-shenzhen.json"
    p = Path(rel)
    if p.is_absolute():
        return p
    local = APP_DIR / p
    if local.exists():
        return local
    bundled = RESOURCE_ROOT / p
    if bundled.exists():
        return bundled
    return local


def load_questions(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    path = resolve_bank_path(cfg)
    qs = load_bank_file(path)
    if not qs:
        raise RuntimeError(f"题库为空: {path}")
    log.info("loaded %d questions from %s", len(qs), path)
    return qs


def resolve_image(path_str: str) -> Path | None:
    if not path_str:
        return None
    p = Path(path_str)
    if p.is_absolute():
        return p if p.exists() else None
    for base in (APP_DIR, RESOURCE_ROOT):
        candidate = base / path_str
        if candidate.exists():
            return candidate
    return None


def pick_set(
    questions: list[dict[str, Any]],
    n: int,
    recent_ids: list[Any],
) -> list[dict[str, Any]]:
    """Pick n questions avoiding recent ids when possible."""
    if n <= 0:
        return []
    recent = set(recent_ids or [])
    pool = [q for q in questions if q.get("id") not in recent]
    if len(pool) < n:
        pool = list(questions)
    if len(pool) <= n:
        # shuffle copy
        out = list(pool)
        random.shuffle(out)
        # if still short, allow repeats from full bank
        while len(out) < n and questions:
            out.append(random.choice(questions))
        return out[:n]
    return random.sample(pool, n)


def check_answer(q: dict[str, Any], response: Any) -> bool:
    """Grade a response against internal question."""
    qtype = q.get("type", "single")
    if qtype in ("single", "boolean"):
        return str(response).strip() == str(q.get("a", "")).strip()
    if qtype == "multiple":
        expected = q.get("a")
        if isinstance(expected, list):
            exp = sorted(str(x).strip() for x in expected)
        else:
            exp = sorted(str(x).strip() for x in str(expected).split("|") if x.strip())
        if isinstance(response, (list, tuple, set)):
            got = sorted(str(x).strip() for x in response)
        else:
            got = sorted(str(x).strip() for x in str(response).split("|") if x.strip())
        return got == exp
    if qtype == "text":
        text = str(response or "").strip().lower()
        keys = [str(k).strip().lower() for k in (q.get("keywords") or []) if str(k).strip()]
        if keys:
            return all(k in text for k in keys) or text == str(q.get("a", "")).strip().lower()
        return text == str(q.get("a", "")).strip().lower()
    return str(response).strip() == str(q.get("a", "")).strip()


def list_bank_files() -> list[dict[str, str]]:
    from .paths import BANKS_DIR

    BANKS_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for p in sorted(BANKS_DIR.glob("*.json")):
        count = None
        try:
            count = len(load_bank_file(p))
        except Exception:
            count = None
        items.append({"name": p.name, "path": str(p.relative_to(ROOT)).replace("\\", "/"), "count": count})
    return items


def import_bank_json(text: str, filename: str = "imported.json") -> Path:
    from .paths import BANKS_DIR

    BANKS_DIR.mkdir(parents=True, exist_ok=True)
    data = json.loads(text)
    # validate by normalizing
    if isinstance(data, list):
        wrapped = {"name": filename, "questions": data}
    elif isinstance(data, dict):
        wrapped = data
        if "questions" not in wrapped and "items" not in wrapped:
            raise ValueError("JSON 需含 questions 数组，或直接是题目数组")
    else:
        raise ValueError("无效 JSON")
    # dry-run normalize
    tmp = wrapped if "questions" in wrapped else {"questions": wrapped.get("items", [])}
    qs = []
    for i, raw in enumerate(tmp.get("questions") or [], start=1):
        item = normalize_question(raw, i)
        if item:
            qs.append(item)
    if not qs:
        raise ValueError("导入后无可用题目（主观题无答案会被跳过）")
    safe = "".join(c for c in filename if c.isalnum() or c in "-_.") or "imported.json"
    if not safe.endswith(".json"):
        safe += ".json"
    path = BANKS_DIR / safe
    path.write_text(json.dumps(wrapped, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path



def question_summary(q: dict[str, Any]) -> dict[str, Any]:
    text = str(q.get("q") or "")
    return {
        "id": q.get("id"),
        "type": q.get("type") or "single",
        "subject": q.get("subject") or "",
        "unit": q.get("unit") or "",
        "q": text,
        "q_preview": text if len(text) <= 60 else text[:60] + "…",
        "choices_count": len(q.get("choices") or []),
        "has_image": bool(q.get("image")),
        "difficulty": q.get("difficulty", 1),
        "a": q.get("a"),
    }


def _read_bank_document(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return (wrapper_dict, normalized questions). Wrapper always has questions key."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        wrapper: dict[str, Any] = {"name": path.stem, "questions": raw}
        source_list = raw
    elif isinstance(raw, dict):
        wrapper = dict(raw)
        source_list = raw.get("questions") or raw.get("items") or raw.get("bank") or []
        if "questions" not in wrapper:
            wrapper["questions"] = list(source_list)
    else:
        raise ValueError(f"unsupported bank format: {path}")
    qs: list[dict[str, Any]] = []
    for i, item in enumerate(source_list, start=1):
        n = normalize_question(item, fallback_id=i)
        if n:
            qs.append(n)
    return wrapper, qs


def save_bank_document(path: Path, wrapper: dict[str, Any], questions: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = dict(wrapper)
    # Store questions in a stable editable shape
    serializable = []
    for q in questions:
        row = {
            "id": q.get("id"),
            "type": q.get("type") or "single",
            "subject": q.get("subject") or "",
            "unit": q.get("unit") or "",
            "q": q.get("q") or "",
            "a": q.get("a"),
            "choices": list(q.get("choices") or []),
            "difficulty": q.get("difficulty", 1),
        }
        if q.get("image"):
            row["image"] = q["image"]
        if q.get("keywords"):
            row["keywords"] = list(q["keywords"])
        if q.get("correct_indices"):
            row["correct_indices"] = list(q["correct_indices"])
        serializable.append(row)
    out["questions"] = serializable
    out.pop("items", None)
    out.pop("bank", None)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def list_questions(
    cfg: dict[str, Any],
    *,
    subject: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    ensure_runtime_dirs()
    path = resolve_bank_path(cfg)
    _wrapper, qs = _read_bank_document(path)
    subjects = sorted({str(q.get("subject") or "") for q in qs if q.get("subject")})
    filtered = qs
    if subject:
        filtered = [q for q in filtered if str(q.get("subject") or "") == subject]
    if search:
        raw = str(search or "").strip().lower()
        # Support multi-keyword AND search: "拼音 声母"
        keys = [k for k in raw.replace(",", " ").replace("，", " ").split() if k]
        if keys:
            def _blob(q: dict) -> str:
                return " ".join(
                    [
                        str(q.get("q") or ""),
                        str(q.get("unit") or ""),
                        str(q.get("subject") or ""),
                        str(q.get("id") or ""),
                        str(q.get("a") or ""),
                        " ".join(str(c) for c in (q.get("choices") or [])),
                        " ".join(str(k) for k in (q.get("keywords") or [])),
                    ]
                ).lower()

            def _hit(q: dict) -> bool:
                blob = _blob(q)
                return all(k in blob for k in keys)

            filtered = [q for q in filtered if _hit(q)]
    total = len(filtered)
    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 20)))
    start = (page - 1) * page_size
    chunk = filtered[start : start + page_size]
    return {
        "bank_file": (str(path.relative_to(ROOT)).replace(chr(92), "/") if str(path.resolve()).startswith(str(ROOT.resolve())) else str(path)),
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
        "subjects": subjects,
        "items": [question_summary(q) for q in chunk],
    }


def get_question(cfg: dict[str, Any], qid: int | str) -> dict[str, Any] | None:
    path = resolve_bank_path(cfg)
    _wrapper, qs = _read_bank_document(path)
    try:
        target = int(qid)
    except Exception:
        target = qid
    for q in qs:
        if q.get("id") == target or str(q.get("id")) == str(qid):
            return dict(q)
    return None


def _next_id(qs: list[dict[str, Any]]) -> int:
    nums = []
    for q in qs:
        try:
            nums.append(int(q.get("id")))
        except Exception:
            pass
    return (max(nums) + 1) if nums else 1


def upsert_question(cfg: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    path = resolve_bank_path(cfg)
    # Always persist beside exe / APP_DIR (writable)
    from .paths import APP_DIR

    if not path.exists() or str(RESOURCE_ROOT) in str(path.resolve()):
        # copy path under APP_DIR
        rel = cfg.get("bank_file") or "data/banks/grade1-shenzhen.json"
        path = APP_DIR / rel
        path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        wrapper, qs = _read_bank_document(path)
    else:
        wrapper, qs = {"name": path.stem, "questions": []}, []

    normalized = normalize_question(data, fallback_id=_next_id(qs))
    if not normalized:
        raise ValueError("题目无效（需要题干；主观题需答案或关键词）")

    qid = normalized.get("id")
    found = False
    for i, q in enumerate(qs):
        if q.get("id") == qid or str(q.get("id")) == str(qid):
            qs[i] = normalized
            found = True
            break
    if not found:
        if data.get("id") is None:
            normalized["id"] = _next_id(qs)
        qs.append(normalized)

    save_bank_document(path, wrapper, qs)
    return dict(normalized)


def delete_question(cfg: dict[str, Any], qid: int | str) -> bool:
    path = resolve_bank_path(cfg)
    from .paths import APP_DIR

    if not path.exists():
        return False
    # Ensure writable path
    try:
        if not os.access(path, os.W_OK):
            rel = cfg.get("bank_file") or "data/banks/grade1-shenzhen.json"
            path = APP_DIR / rel
    except Exception:
        pass
    wrapper, qs = _read_bank_document(path)
    new_qs = [q for q in qs if not (q.get("id") == qid or str(q.get("id")) == str(qid))]
    if len(new_qs) == len(qs):
        return False
    save_bank_document(path, wrapper, new_qs)
    return True


def export_bank_text(cfg: dict[str, Any]) -> str:
    path = resolve_bank_path(cfg)
    wrapper, qs = _read_bank_document(path)
    save_like = dict(wrapper)
    save_like["questions"] = qs
    return json.dumps(save_like, ensure_ascii=False, indent=2) + "\n"


def replace_bank_from_import(cfg: dict[str, Any], text: str, *, merge: bool = False) -> dict[str, Any]:
    """Import into the *active* bank file (merge or replace)."""
    path = resolve_bank_path(cfg)
    from .paths import APP_DIR

    rel = cfg.get("bank_file") or "data/banks/grade1-shenzhen.json"
    path = APP_DIR / rel
    path.parent.mkdir(parents=True, exist_ok=True)

    data = json.loads(text)
    if isinstance(data, list):
        incoming_raw = data
        wrapper: dict[str, Any] = {"name": path.stem, "questions": []}
    elif isinstance(data, dict):
        wrapper = {k: v for k, v in data.items() if k not in ("questions", "items", "bank")}
        incoming_raw = data.get("questions") or data.get("items") or data.get("bank") or []
        wrapper.setdefault("name", path.stem)
    else:
        raise ValueError("无效 JSON")

    incoming: list[dict[str, Any]] = []
    for i, raw in enumerate(incoming_raw, start=1):
        item = normalize_question(raw, fallback_id=i)
        if item:
            incoming.append(item)
    if not incoming:
        raise ValueError("导入后无可用题目")

    if merge and path.exists():
        old_wrapper, old_qs = _read_bank_document(path)
        wrapper = {**old_wrapper, **wrapper}
        by_id = {q.get("id"): q for q in old_qs}
        for q in incoming:
            by_id[q.get("id")] = q
        # keep stable order: old then new ids
        seen = set()
        merged = []
        for q in old_qs + incoming:
            qid = q.get("id")
            if qid in seen:
                # updated version already in by_id — skip duplicate pass
                continue
            seen.add(qid)
            merged.append(by_id[qid])
        qs = merged
    else:
        qs = incoming

    save_bank_document(path, wrapper, qs)
    return {"path": str(path.relative_to(APP_DIR)).replace("\\", "/"), "count": len(qs)}

def shuffle_choices(
    choices: list[Any],
    *,
    correct_indices: list[int] | None = None,
    answer: Any = None,
) -> tuple[list[Any], list[int]]:
    """Shuffle options; return (shuffled, new_correct_indices).

    Grading by answer *value* still works; indices are remapped so callers that
    rely on correctIndices stay correct after shuffle.
    """
    items = list(choices or [])
    n = len(items)
    if n == 0:
        return [], []
    order = list(range(n))
    random.shuffle(order)
    shuffled = [items[i] for i in order]
    old_to_new = {old: new for new, old in enumerate(order)}

    if correct_indices:
        new_idx = sorted(
            old_to_new[i] for i in correct_indices if isinstance(i, int) and i in old_to_new
        )
    elif answer is not None:
        if isinstance(answer, list):
            targets = {str(x).strip() for x in answer}
        else:
            targets = {str(answer).strip()}
        new_idx = [j for j, c in enumerate(shuffled) if str(c).strip() in targets]
    else:
        new_idx = []
    return shuffled, new_idx

