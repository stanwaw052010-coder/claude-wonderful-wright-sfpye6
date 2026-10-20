"""Сведение: диалоги + музыка (с «приседанием» под речь) + атмосферы + эффекты → −14 LUFS."""
from __future__ import annotations

import json
import zlib
import re
import subprocess
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve

from . import music, sfx
from .episode import TITLE_DUR, Episode
from .voices import SR

ROOM = {"garage": (0.45, 0.10), "mill_interior": (1.7, 0.20), "main_street": (0.8, 0.06), "maple_row": (0.5, 0.05),
        "forest": (0.9, 0.07), "mill_exterior": (0.9, 0.07), "lookout": (0.6, 0.05), "end_card": (0.4, 0.03)}
SFX_GAIN = {"magic_swell": 0.75, "pop": 0.6, "boing": 0.45, "glitch": 0.5, "clock_chime": 0.5, "bike_bell": 0.5,
            "camera_flash": 0.55, "shimmer": 0.45, "whoosh": 0.5, "writing": 0.45, "laugh_soft": 0.4}


def db(x):
    return 10 ** (x / 20)


def _room(x, secs, wet, seed):
    n = int(secs * SR)
    t = np.arange(n) / SR
    ir = np.random.default_rng(seed).normal(0, 1, n) * np.exp(-t * 6.9 / secs)
    ir[: int(0.008 * SR)] = 0
    ir /= np.sqrt(np.sum(ir ** 2))
    return x * (1 - wet) + fftconvolve(x, ir)[: len(x)] * wet


def _loop(a, n, xf=SR):
    if len(a) >= n:
        return a[:n]
    out = np.zeros(n, np.float32)
    pos = 0
    fade = np.linspace(0, 1, xf, dtype=np.float32)
    while pos < n:
        seg = a.copy()
        if pos > 0:
            seg[:xf] *= fade
        seg[-xf:] *= fade[::-1]
        m = min(len(seg), n - pos)
        out[pos:pos + m] += seg[:m]
        pos += len(seg) - xf
    return out


def build(ep: Episode, out_dir: Path, log=print):
    N = int((ep.duration + 1.0) * SR)
    dia = np.zeros(N, np.float32)
    # --- диалоги
    for (t, L, vo) in ep.lines:
        sc = next(s for s in ep.scenes if s.t0 <= t < s.t1 + 1e-6)
        secs, wet = ROOM.get(sc.set, (0.5, 0.05))
        y = _room(L.audio, secs, wet, seed=zlib.crc32(sc.set.encode()) & 0xFFFF)
        i = int(t * SR)
        dia[i:i + len(y)] += y[: N - i]
    # огибающая речи для «приседания» музыки
    env = np.abs(dia)
    hop = 480
    e = env[: len(env) // hop * hop].reshape(-1, hop).max(axis=1)
    k = np.ones(40) / 40
    e = np.convolve(e, k, mode="same")
    e = np.clip(e / 0.05, 0, 1)
    duck = np.repeat(e, hop)
    duck = np.pad(duck, (0, N - len(duck)))
    # --- музыка
    regions = []
    for sc in ep.scenes:
        ta = sc.data.get("title_at")
        if sc.music:
            if ta is not None:
                if ta > 0.5:
                    regions.append((sc.t0, sc.t0 + ta, sc.music))
                regions.append((sc.t0 + ta, sc.t0 + ta + TITLE_DUR, "theme"))
                if sc.t0 + ta + TITLE_DUR < sc.t1 - 0.5:
                    regions.append((sc.t0 + ta + TITLE_DUR, sc.t1, sc.music))
            else:
                regions.append((sc.t0, sc.t1, sc.music))
    # сливаем соседние одинаковые
    merged = []
    for r in regions:
        if merged and merged[-1][2] == r[2] and abs(merged[-1][1] - r[0]) < 0.01:
            merged[-1] = (merged[-1][0], r[1], r[2])
        else:
            merged.append(r)
    mus = np.zeros((2, N), np.float32)
    for i, (a, b, cue) in enumerate(merged):
        d = b - a + 1.2
        y = music.render_cue(cue, d, seed=i)
        y = music.reverb(y, 2.2 if cue in ("mystery", "wonder", "tension") else 1.4, 0.3)
        n = y.shape[1]
        fi, fo = int(0.8 * SR), int(1.2 * SR)
        y[:, :fi] *= np.linspace(0, 1, fi)
        y[:, -fo:] *= np.linspace(1, 0, fo)
        p = int(a * SR)
        m = min(n, N - p)
        mus[:, p:p + m] += y[:, :m]
    peak = np.percentile(np.abs(mus), 99.9) or 1
    mus = mus / peak * db(-9)
    mus *= (1 - duck * (1 - db(-11)))[None, :]
    # --- атмосферы
    names_amb = sorted({s.ambience for s in ep.scenes if s.ambience})
    names_sfx = sorted({n for _, n in ep.sfx})
    lib, warn = sfx.load_all(names_sfx, names_amb)
    for w in warn:
        log(f"  ! эффект недоступен: {w}")
    amb = np.zeros((2, N), np.float32)
    for sc in ep.scenes:
        if not sc.ambience or sc.ambience not in lib:
            continue
        n = int((sc.t1 - sc.t0) * SR)
        a = _loop(lib[sc.ambience], n)
        f = int(0.6 * SR)
        a[:f] *= np.linspace(0, 1, f)
        a[-f:] *= np.linspace(1, 0, f)
        p = int(sc.t0 * SR)
        a = a * db(-21)
        amb[0, p:p + n] += a[: N - p]
        amb[1, p:p + n] += np.roll(a, 900)[: N - p]
    # --- эффекты
    fxb = np.zeros((2, N), np.float32)
    for (t, name) in ep.sfx:
        if name not in lib:
            continue
        y = lib[name] * SFX_GAIN.get(name, 0.55) * db(-4)
        p = int(t * SR)
        m = min(len(y), N - p)
        fxb[0, p:p + m] += y[:m]
        fxb[1, p:p + m] += y[:m]
    mix = mus + amb + fxb + np.stack([dia, dia]) * db(-1)
    raw = out_dir / "mix_raw.wav"
    _write_wav(raw, mix)
    final = out_dir / "mix.wav"
    _loudnorm(raw, final)
    raw.unlink()
    voice = out_dir / "mix_voice_only.wav"
    _write_wav(voice, np.stack([dia, dia]) * 0.9)
    return final


def _write_wav(path, x):
    x = np.clip(x, -1, 1)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "pipe:0",
                    "-c:a", "pcm_s16le", str(path)], input=x.T.astype(np.float32).tobytes(), check=True)


def _loudnorm(src, dst, I=-14.0, TP=-1.0, LRA=11):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-af", f"loudnorm=I={I}:TP={TP}:LRA={LRA}:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True)
    m = json.loads(re.findall(r"\{[^{}]*\}", r.stderr)[-1])
    af = (f"loudnorm=I={I}:TP={TP}:LRA={LRA}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", af, "-ar", str(SR), "-c:a", "pcm_s16le", str(dst)],
                   check=True)
