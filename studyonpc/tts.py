# -*- coding: utf-8 -*-
"""Volcengine / ByteDance openspeech TTS (HTTP v1) + local cache/play."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any
from urllib import error, request

from .paths import DATA_DIR, ensure_runtime_dirs

log = logging.getLogger("studyonpc.tts")

DEFAULT_TTS: dict[str, Any] = {
    "enabled": False,
    "provider": "volcengine",
    "appid": "",
    "token": "",
    "cluster": "volcano_tts",
    "voice_type": "BV001_streaming",
    "api_url": "https://openspeech.bytedance.com/api/v1/tts",
    "encoding": "mp3",
    "speed_ratio": 1.0,
}

CACHE_DIR_NAME = "tts_cache"


def normalize_tts(cfg: dict[str, Any]) -> dict[str, Any]:
    raw = cfg.get("tts") if isinstance(cfg.get("tts"), dict) else {}
    out = dict(DEFAULT_TTS)
    out.update({k: raw[k] for k in DEFAULT_TTS if k in raw})
    out["enabled"] = bool(out.get("enabled"))
    out["appid"] = str(out.get("appid") or "").strip()
    out["token"] = str(out.get("token") or "").strip()
    out["cluster"] = str(out.get("cluster") or "volcano_tts").strip()
    out["voice_type"] = str(out.get("voice_type") or "BV001_streaming").strip()
    out["api_url"] = str(out.get("api_url") or DEFAULT_TTS["api_url"]).strip()
    out["encoding"] = str(out.get("encoding") or "mp3").strip().lower()
    try:
        out["speed_ratio"] = float(out.get("speed_ratio") or 1.0)
    except Exception:
        out["speed_ratio"] = 1.0
    cfg["tts"] = out
    return out


def tts_configured(tts: dict[str, Any]) -> bool:
    return bool(tts.get("enabled") and tts.get("appid") and tts.get("token"))


def cache_dir() -> Path:
    ensure_runtime_dirs()
    d = DATA_DIR / CACHE_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(text: str, tts: dict[str, Any]) -> str:
    h = hashlib.sha1(
        f"{tts.get('voice_type')}|{tts.get('encoding')}|{tts.get('speed_ratio')}|{text}".encode("utf-8")
    ).hexdigest()
    ext = "mp3" if tts.get("encoding") == "mp3" else "wav"
    return f"{h}.{ext}"


def synthesize(text: str, tts: dict[str, Any] | None = None) -> Path | None:
    """Call Volcengine TTS; return path to cached audio file or None."""
    tts = normalize_tts({"tts": dict(tts or {})})
    text = (text or "").strip()
    if not text:
        return None
    if not tts_configured(tts):
        log.info("tts skipped: disabled or missing appid/token")
        return None
    # API limit ~1024 bytes; keep short
    if len(text.encode("utf-8")) > 900:
        text = text[:200] + "…"

    path = cache_dir() / _cache_key(text, tts)
    if path.exists() and path.stat().st_size > 32:
        return path

    body = {
        "app": {
            "appid": tts["appid"],
            "token": "access_token",
            "cluster": tts["cluster"],
        },
        "user": {"uid": "studyonpc"},
        "audio": {
            "voice_type": tts["voice_type"],
            "encoding": tts.get("encoding") or "mp3",
            "speed_ratio": float(tts.get("speed_ratio") or 1.0),
            "volume_ratio": 1.0,
            "pitch_ratio": 1.0,
        },
        "request": {
            "reqid": str(uuid.uuid4()),
            "text": text,
            "text_type": "plain",
            "operation": "query",
        },
    }
    data = json.dumps(body).encode("utf-8")
    req = request.Request(
        tts["api_url"],
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer;{tts['token']}",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(e)
        log.warning("tts http error: %s %s", e.code, detail[:300])
        return None
    except Exception as e:
        log.warning("tts request failed: %s", e)
        return None

    b64 = payload.get("data")
    if not b64:
        log.warning("tts no data: %s", str(payload)[:300])
        return None
    try:
        audio = base64.b64decode(b64)
    except Exception as e:
        log.warning("tts b64 decode: %s", e)
        return None
    path.write_bytes(audio)
    return path


def play_file(path: Path) -> None:
    """Best-effort async play on Windows; no-op elsewhere if player missing."""
    if not path or not path.exists():
        return

    def _run() -> None:
        try:
            if os.name == "nt":
                # MediaPlayer supports mp3/wav
                uri = path.resolve().as_uri()
                ps = (
                    "Add-Type -AssemblyName presentationCore; "
                    "$p=New-Object System.Windows.Media.MediaPlayer; "
                    f"$p.Open([Uri]'{uri}'); $p.Volume=1; $p.Play(); "
                    "Start-Sleep -Milliseconds 200; "
                    "while($p.NaturalDuration.HasTimeSpan -eq $false){Start-Sleep -Milliseconds 50}; "
                    "$ms=[int]($p.NaturalDuration.TimeSpan.TotalMilliseconds)+400; "
                    "Start-Sleep -Milliseconds $ms; $p.Stop(); $p.Close()"
                )
                subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                    capture_output=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    timeout=60,
                )
            else:
                for cmd in (("ffplay", "-nodisp", "-autoexit", str(path)), ("mpg123", str(path)), ("afplay", str(path))):
                    try:
                        subprocess.run(list(cmd), capture_output=True, timeout=60)
                        break
                    except Exception:
                        continue
        except Exception as e:
            log.warning("tts play failed: %s", e)

    threading.Thread(target=_run, daemon=True).start()


def speak(text: str, tts: dict[str, Any] | None = None) -> bool:
    path = synthesize(text, tts)
    if not path:
        return False
    play_file(path)
    return True


def public_tts_view(tts: dict[str, Any]) -> dict[str, Any]:
    """Config view for admin UI — mask secrets."""
    t = dict(tts or {})
    token = str(t.get("token") or "")
    appid = str(t.get("appid") or "")
    return {
        "enabled": bool(t.get("enabled")),
        "provider": t.get("provider") or "volcengine",
        "appid": appid,
        "appid_set": bool(appid),
        "token_set": bool(token),
        "token_masked": ("*" * min(8, len(token))) if token else "",
        "cluster": t.get("cluster") or "volcano_tts",
        "voice_type": t.get("voice_type") or "BV001_streaming",
        "api_url": t.get("api_url") or DEFAULT_TTS["api_url"],
        "encoding": t.get("encoding") or "mp3",
        "speed_ratio": t.get("speed_ratio") or 1.0,
    }
