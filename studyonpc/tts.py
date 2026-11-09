# -*- coding: utf-8 -*-
"""Volcengine / ByteDance openspeech TTS (HTTP V3 SSE) + local cache/play.

Aligned with CaptainChen VolcanoTTSProvider:
  POST https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse
  Headers: X-Api-Key, X-Api-Resource-Id, X-Api-Request-Id
  Body: user.uid + req_params.{text,speaker,audio_params}
  Response: SSE lines ``data: {json}``; concatenate base64 ``data`` chunks → mp3.

Legacy V1 fields (appid/token/cluster/voice_type) are ignored if present.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import subprocess
import threading
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib import error, request

from .paths import DATA_DIR, ensure_runtime_dirs

log = logging.getLogger("studyonpc.tts")

DEFAULT_API_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse"
DEFAULT_SPEAKER = "zh_male_tiancaitongsheng_uranus_bigtts"
DEFAULT_RESOURCE_ID = "seed-tts-1.0"

# V1 keys kept only so old config.json does not crash normalize; never sent to API.
_LEGACY_V1_KEYS = ("appid", "token", "cluster", "voice_type")

DEFAULT_TTS: dict[str, Any] = {
    "enabled": False,
    "provider": "volcengine",
    "api_key": "",
    "speaker": DEFAULT_SPEAKER,
    "resource_id": DEFAULT_RESOURCE_ID,
    "api_url": DEFAULT_API_URL,
    "encoding": "mp3",
    "sample_rate": 24000,
    "system_fallback": True,
    "speech_rate": 0,
    "loudness_rate": 0,
}

CACHE_DIR_NAME = "tts_cache"


def normalize_tts(cfg: dict[str, Any]) -> dict[str, Any]:
    raw = cfg.get("tts") if isinstance(cfg.get("tts"), dict) else {}
    out = dict(DEFAULT_TTS)
    # Prefer V3 keys; drop legacy V1 from the normalized view except we leave them
    # out of DEFAULT so they are not re-persisted unless still in raw and we strip.
    for k in DEFAULT_TTS:
        if k in raw:
            out[k] = raw[k]
    out["enabled"] = bool(out.get("enabled"))
    out["api_key"] = str(out.get("api_key") or "").strip()
    out["speaker"] = str(out.get("speaker") or DEFAULT_SPEAKER).strip() or DEFAULT_SPEAKER
    out["resource_id"] = (
        str(out.get("resource_id") or DEFAULT_RESOURCE_ID).strip() or DEFAULT_RESOURCE_ID
    )
    out["api_url"] = str(out.get("api_url") or DEFAULT_API_URL).strip() or DEFAULT_API_URL
    out["encoding"] = str(out.get("encoding") or "mp3").strip().lower() or "mp3"
    try:
        out["sample_rate"] = int(out.get("sample_rate") or 24000)
    except Exception:
        out["sample_rate"] = 24000
    out["system_fallback"] = bool(out.get("system_fallback", True))
    for field in ("speech_rate", "loudness_rate"):
        try:
            out[field] = max(-50, min(100, int(out.get(field) or 0)))
        except (TypeError, ValueError):
            out[field] = 0
    # Do not carry V1 secrets into the live config object (avoid accidental reuse).
    for k in _LEGACY_V1_KEYS:
        out.pop(k, None)
    cfg["tts"] = out
    return out


def tts_configured(tts: dict[str, Any]) -> bool:
    return bool(tts.get("enabled") and tts.get("api_key") and tts.get("speaker"))


def cache_dir() -> Path:
    ensure_runtime_dirs()
    d = DATA_DIR / CACHE_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _speech_text(text: str) -> str:
    text = (text or "").strip()
    return text[:200] + "…" if len(text.encode("utf-8")) > 900 else text


def _cache_key(text: str, tts: dict[str, Any]) -> str:
    # Versioned canonical request identity, never the API key or credentials.
    cfg = normalize_tts({"tts": dict(tts)})
    fields = ("provider", "api_url", "speaker", "resource_id", "encoding",
              "sample_rate", "speech_rate", "loudness_rate")
    identity = {k: cfg[k] for k in fields}
    identity.update(version=2, text=_speech_text(text))
    return hashlib.sha256(json.dumps(identity, sort_keys=True,
                                    ensure_ascii=False).encode("utf-8")).hexdigest() + ".mp3"


# Striped locks bound memory while deduplicating concurrent callers for the same key.
_CACHE_LOCKS = [threading.Lock() for _ in range(32)]


def _atomic_audio_write(path: Path, audio: bytes) -> None:
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tts-", suffix=".tmp",
                                         delete=False) as stream:
            tmp = Path(stream.name)
            stream.write(audio)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def _parse_sse_audio(raw: bytes) -> bytes | None:
    try:
        text = raw.decode("utf-8")
    except Exception:
        return None
    audio = bytearray()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        json_str = line[5:].strip()
        if not json_str:
            continue
        try:
            obj = json.loads(json_str)
        except Exception:
            continue
        if obj.get("code", 0) not in (0, 20000000):
            return None
        b64 = obj.get("data")
        if isinstance(b64, str) and b64:
            try:
                audio.extend(base64.b64decode(b64, validate=True))
            except Exception:
                return None
    return bytes(audio) if audio else None


def _synthesize_locked(text: str, tts: dict[str, Any] | None = None) -> Path | None:
    """Call Volcengine TTS V3 SSE; return path to cached mp3 or None."""
    tts = normalize_tts({"tts": dict(tts or {})})
    text = _speech_text(text)
    if not text:
        return None
    if not tts_configured(tts):
        log.info("tts skipped: disabled or missing api_key/speaker")
        return None
    # Keep payload modest
    if len(text.encode("utf-8")) > 900:
        text = text[:200] + "…"

    path = cache_dir() / _cache_key(text, tts)
    if path.exists() and path.stat().st_size > 32:
        return path

    body = {
        "user": {"uid": "studyonpc"},
        "req_params": {
            "text": text,
            "speaker": tts["speaker"],
            "audio_params": {
                "format": tts.get("encoding") or "mp3",
                "sample_rate": int(tts.get("sample_rate") or 24000),
                "speech_rate": tts["speech_rate"],
                "loudness_rate": tts["loudness_rate"],
            },
        },
    }
    data = json.dumps(body).encode("utf-8")
    req = request.Request(
        tts["api_url"],
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-Api-Key": tts["api_key"],
            "X-Api-Resource-Id": tts["resource_id"],
            "X-Api-Request-Id": str(uuid.uuid4()),
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as resp:
            payload = resp.read()
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

    audio = _parse_sse_audio(payload)
    if not audio:
        preview = payload[:300].decode("utf-8", errors="replace") if payload else ""
        log.warning("tts no audio from SSE: %s", preview)
        return None
    if len(audio) <= 32:
        return None
    _atomic_audio_write(path, audio)
    return path


def synthesize(text: str, tts: dict[str, Any] | None = None) -> Path | None:
    """Thread-safe persistent cache; network and atomic write happen under one key lock."""
    cfg = normalize_tts({"tts": dict(tts or {})})
    key = _cache_key(text, cfg)
    lock = _CACHE_LOCKS[int(key[:8], 16) % len(_CACHE_LOCKS)]
    with lock:
        return _synthesize_locked(text, cfg)


def _play_windows_mci(path: Path) -> bool:
    """Play mp3/wav via winmm MCI (stdlib ctypes). Returns True on success."""
    import ctypes

    winmm = ctypes.windll.winmm
    buf = ctypes.create_unicode_buffer(512)
    alias = "studyonpc_tts"

    def mci(cmd: str) -> int:
        return int(winmm.mciSendStringW(cmd, buf, 511, None))

    path_str = str(path.resolve())
    mci(f"close {alias}")
    rc = mci(f'open "{path_str}" type mpegvideo alias {alias}')
    if rc != 0:
        rc = mci(f'open "{path_str}" alias {alias}')
    if rc != 0:
        winmm.mciGetErrorStringW(rc, buf, 511)
        log.warning("tts mci open failed (%s): %s", rc, buf.value)
        return False
    # volume 0..1000
    mci(f"setaudio {alias} volume to 1000")
    rc = mci(f"play {alias} wait")
    mci(f"close {alias}")
    if rc != 0:
        winmm.mciGetErrorStringW(rc, buf, 511)
        log.warning("tts mci play failed (%s): %s", rc, buf.value)
        return False
    return True


def _play_windows_mediaplayer(path: Path) -> bool:
    """Fallback: WPF MediaPlayer via PowerShell."""
    uri = path.resolve().as_uri().replace("'", "''")
    ps = (
        "Add-Type -AssemblyName presentationCore; "
        "$p=New-Object System.Windows.Media.MediaPlayer; "
        f"$p.Open([Uri]'{uri}'); $p.Volume=1; $p.Play(); "
        "Start-Sleep -Milliseconds 300; "
        "$deadline=(Get-Date).AddSeconds(8); "
        "while(-not $p.NaturalDuration.HasTimeSpan){ "
        "  if((Get-Date) -gt $deadline){ Write-Error 'MediaPlayer duration timeout'; exit 2 }; "
        "  Start-Sleep -Milliseconds 50 "
        "}; "
        "$ms=[int]($p.NaturalDuration.TimeSpan.TotalMilliseconds)+400; "
        "Start-Sleep -Milliseconds $ms; $p.Stop(); $p.Close()"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=60,
    )
    if r.returncode != 0:
        log.warning(
            "tts MediaPlayer failed rc=%s stderr=%s",
            r.returncode,
            (r.stderr or r.stdout or "")[:300],
        )
        return False
    return True


def play_file(path: Path) -> None:
    """Best-effort async play on Windows; no-op elsewhere if player missing."""
    if not path or not path.exists():
        return

    def _run() -> None:
        try:
            if os.name == "nt":
                # Prefer MCI (works without WPF session quirks); then MediaPlayer.
                if _play_windows_mci(path):
                    return
                if _play_windows_mediaplayer(path):
                    return
                log.warning("tts play: all Windows backends failed for %s", path.name)
            else:
                for cmd in (
                    ("ffplay", "-nodisp", "-autoexit", str(path)),
                    ("mpg123", str(path)),
                    ("afplay", str(path)),
                ):
                    try:
                        subprocess.run(list(cmd), capture_output=True, timeout=60)
                        break
                    except Exception:
                        continue
        except Exception as e:
            log.warning("tts play failed: %s", e)

    threading.Thread(target=_run, daemon=True).start()


def _system_speak(text: str) -> bool:
    """Windows SAPI fallback when V3 fails and system_fallback is on."""
    text = (text or "").strip()
    if not text or os.name != "nt":
        return False

    def _run() -> None:
        try:
            # Escape for PowerShell single-quoted string
            safe = text.replace("'", "''")
            ps = (
                "Add-Type -AssemblyName System.Speech; "
                "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "$s.Rate=-1; "
                f"$s.Speak('{safe}')"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=60,
            )
        except Exception as e:
            log.warning("system tts failed: %s", e)

    threading.Thread(target=_run, daemon=True).start()
    return True


def speak(text: str, tts: dict[str, Any] | None = None) -> bool:
    path = synthesize(text, tts)
    if path:
        play_file(path)
        return True
    tts_n = normalize_tts({"tts": dict(tts or {})})
    if tts_n.get("system_fallback") and tts_n.get("enabled"):
        return _system_speak(text)
    return False


def public_tts_view(tts: dict[str, Any]) -> dict[str, Any]:
    """Config view for admin UI — mask secrets."""
    t = normalize_tts({"tts": dict(tts or {})})
    key = str(t.get("api_key") or "")
    masked = ""
    if key:
        masked = ("*" * min(8, max(0, len(key) - 4))) + key[-4:] if len(key) >= 4 else ("*" * len(key))
    return {
        "enabled": bool(t.get("enabled")),
        "provider": t.get("provider") or "volcengine",
        "api_key_set": bool(key),
        "api_key_masked": masked,
        "speaker": t.get("speaker") or DEFAULT_SPEAKER,
        "resource_id": t.get("resource_id") or DEFAULT_RESOURCE_ID,
        "api_url": t.get("api_url") or DEFAULT_API_URL,
        "encoding": t.get("encoding") or "mp3",
        "sample_rate": t.get("sample_rate") or 24000,
        "system_fallback": bool(t.get("system_fallback", True)),
        # migration hint for old admin caches
        "legacy_v1_ignored": True,
    }
