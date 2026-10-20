"""Озвучка ElevenLabs (eleven_v3, with-timestamps) + обработка голосов персонажей.

Каждая реплика синтезируется отдельно, ответ API (mp3 + тайминги символов)
кэшируется в audio/<ep>/voice_cache — повторная сборка не тратит лимит.
Теги эмоций v3 ([excited], [whispers]) идут в API, но не в субтитры.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np

from .util import ROOT

API = "https://api.elevenlabs.io/v1"
MODEL = "eleven_v3"
SR = 48000
TAG = re.compile(r"\[[^\]]*\]")


@dataclass
class Line:
    key: str
    who: str
    text: str            # с тегами (для API)
    clean: str           # для субтитров
    audio: np.ndarray    # float32 mono SR
    chars: list          # [(char, t0, t1)] по очищенному тексту
    words: list          # [(word, t0, t1)]
    dur: float


def clean_text(t: str) -> str:
    return re.sub(r"\s+", " ", TAG.sub("", t)).strip()


def _post(path, body, timeout=180):
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "xi-api-key": key})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode()), r.headers.get("character-cost")
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:400]
            if e.code in (429, 500, 502, 503) and attempt < 4:
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"ElevenLabs HTTP {e.code}: {msg}") from e
        except urllib.error.URLError:
            if attempt < 4:
                time.sleep(2 ** attempt * 2)
                continue
            raise


def _decode(b: bytes, sr=SR) -> np.ndarray:
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                       input=b, capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.float32).copy()


def _process(audio: np.ndarray, cfg: dict) -> np.ndarray:
    """Сдвиг высоты (rubberband, с сохранением форманты) и эффект ошейника."""
    filt = []
    pitch = float(cfg.get("pitch", 0))
    if abs(pitch) > 0.01:
        filt.append(f"rubberband=pitch={2 ** (pitch / 12):.5f}:formant=preserved")
    if cfg.get("fx") == "collar":
        filt += ["highpass=f=170", "lowpass=f=7200", "equalizer=f=2600:t=q:w=1.2:g=4"]
    if not filt:
        return audio
    r = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "pipe:0",
                        "-af", ",".join(filt), "-f", "f32le", "-"], input=audio.astype(np.float32).tobytes(),
                       capture_output=True, check=True)
    out = np.frombuffer(r.stdout, np.float32).copy()
    n = len(audio)
    return out[:n] if len(out) >= n else np.pad(out, (0, n - len(out)))


def _align(text: str, al: dict):
    """Тайминги символов → очищенный текст без тегов → слова."""
    chars = al["characters"]
    t0s, t1s = al["character_start_times_seconds"], al["character_end_times_seconds"]
    out = []
    depth = 0
    for ch, a, b in zip(chars, t0s, t1s):
        if ch == "[":
            depth += 1
            continue
        if ch == "]":
            depth = max(0, depth - 1)
            continue
        if depth:
            continue
        out.append((ch, a, b))
    # схлопнуть повторные пробелы
    norm = []
    for ch, a, b in out:
        if ch.isspace() and (not norm or norm[-1][0] == " "):
            continue
        norm.append((" " if ch.isspace() else ch, a, b))
    while norm and norm[0][0] == " ":
        norm.pop(0)
    words, cur = [], []
    for ch, a, b in norm + [(" ", 0, 0)]:
        if ch == " ":
            if cur:
                words.append(("".join(c for c, _, _ in cur), cur[0][1], cur[-1][2]))
            cur = []
        else:
            cur.append((ch, a, b))
    return norm, words


def synth_line(ep: str, who: str, text: str, cfg: dict) -> Line:
    cache = ROOT / "audio" / ep / "voice_cache"
    cache.mkdir(parents=True, exist_ok=True)
    stab = float(cfg.get("stability", 0.5))
    stab = min((0.0, 0.5, 1.0), key=lambda v: abs(v - stab))
    body = {"text": text, "model_id": MODEL,
            "voice_settings": {"stability": stab, "similarity_boost": 0.8, "use_speaker_boost": True}}
    h = hashlib.sha1(json.dumps([cfg["voice"], body], sort_keys=True).encode()).hexdigest()[:16]
    f = cache / f"{who}_{h}.json"
    if f.exists():
        res = json.loads(f.read_text())
    else:
        res, cost = _post(f"/text-to-speech/{cfg['voice']}/with-timestamps?output_format=mp3_44100_128", body)
        res["_cost"] = cost
        f.write_text(json.dumps(res))
    audio = _decode(base64.b64decode(res["audio_base64"]))
    al = res.get("alignment") or res.get("normalized_alignment")
    chars, words = _align(text, al)
    # обрезка тишины по краям (сдвигаем тайминги)
    env = np.abs(audio)
    thr = 0.01
    idx = np.where(env > thr)[0]
    if len(idx):
        a = max(0, idx[0] - int(0.04 * SR))
        b = min(len(audio), idx[-1] + int(0.12 * SR))
    else:
        a, b = 0, len(audio)
    audio = audio[a:b]
    off = a / SR
    chars = [(c, max(0.0, s - off), max(0.0, e - off)) for c, s, e in chars]
    words = [(w, max(0.0, s - off), max(0.0, e - off)) for w, s, e in words]
    audio = _process(audio, cfg)
    peak = float(np.max(np.abs(audio))) or 1.0
    rms = float(np.sqrt(np.mean(audio ** 2))) or 1e-4
    audio = audio * min(0.1 / rms, 0.89 / peak)   # выравнивание громкости реплик
    return Line(f.stem, who, text, clean_text(text), audio.astype(np.float32), chars, words, len(audio) / SR)


def synth_all(ep: str, items: list[tuple[str, str]], voices: dict, workers: int = 3) -> list[Line]:
    def job(it):
        who, text = it
        return synth_line(ep, who, text, voices[who])
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(job, items))
