# -*- coding: utf-8 -*-
"""Multi-site watch targets (shared balance, per-site daily caps)."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

DEFAULT_YOUTUBE_SITE: dict[str, Any] = {
    "id": "youtube",
    "name": "YouTube",
    "enabled": True,
    "keywords": ["youtube", "youtu.be"],
    "unlock_minutes_per_set": 10,
    "daily_max_minutes": 60,
    "questions_per_set": 3,
    "pass_ratio": 0.6667,
}


def _norm_keywords(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    return [str(k).strip().lower() for k in raw if str(k).strip()]


def normalize_site(raw: dict[str, Any], fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    fb = fallback or DEFAULT_YOUTUBE_SITE
    sid = str(raw.get("id") or fb.get("id") or "site").strip() or "site"
    return {
        "id": sid,
        "name": str(raw.get("name") or sid),
        "enabled": bool(raw.get("enabled", True)),
        "keywords": _norm_keywords(raw.get("keywords") or fb.get("keywords") or []),
        "unlock_minutes_per_set": float(raw.get("unlock_minutes_per_set", fb.get("unlock_minutes_per_set", 10))),
        "daily_max_minutes": float(raw.get("daily_max_minutes", fb.get("daily_max_minutes", 60))),
        "questions_per_set": max(1, int(raw.get("questions_per_set", fb.get("questions_per_set", 3)))),
        "pass_ratio": float(raw.get("pass_ratio", fb.get("pass_ratio", 0.6667))),
    }


def migrate_sites(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Ensure cfg['sites'] exists; migrate legacy youtube_keywords + global fields."""
    existing = cfg.get("sites")
    if isinstance(existing, list) and existing:
        sites = [normalize_site(s if isinstance(s, dict) else {}) for s in existing]
    else:
        fb = {
            **DEFAULT_YOUTUBE_SITE,
            "keywords": cfg.get("youtube_keywords") or DEFAULT_YOUTUBE_SITE["keywords"],
            "unlock_minutes_per_set": cfg.get("unlock_minutes_per_set", 10),
            "daily_max_minutes": cfg.get("daily_max_watch_minutes", 60),
            "questions_per_set": cfg.get("questions_per_set", 3),
            "pass_ratio": cfg.get("pass_ratio", 0.6667),
        }
        sites = [normalize_site(fb)]
    cfg["sites"] = sites
    # Keep legacy mirror for older tools / docs
    yt = next((s for s in sites if s["id"] == "youtube"), sites[0])
    cfg["youtube_keywords"] = list(yt.get("keywords") or [])
    return sites


def enabled_sites(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    sites = migrate_sites(cfg)
    return [s for s in sites if s.get("enabled") and s.get("keywords")]


def all_keywords(cfg: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in enabled_sites(cfg):
        for k in s.get("keywords") or []:
            if k not in seen:
                seen.add(k)
                out.append(k)
    return out


def match_site(title: str, cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Return first enabled site whose keyword appears in window title."""
    low = (title or "").lower()
    if not low:
        return None
    for s in enabled_sites(cfg):
        for k in s.get("keywords") or []:
            if k and k in low:
                return s
    return None


def site_by_id(cfg: dict[str, Any], site_id: str | None) -> dict[str, Any] | None:
    if not site_id:
        return None
    for s in migrate_sites(cfg):
        if s.get("id") == site_id:
            return s
    return None


def default_site(cfg: dict[str, Any]) -> dict[str, Any]:
    sites = enabled_sites(cfg) or migrate_sites(cfg)
    return deepcopy(sites[0])
