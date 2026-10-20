"""Процедурная партитура Pixel Pines: синтез инструментов и музыкальные темы.

Инструменты синтезируются numpy (челеста/колокольчики — FM, пиццикато и маримба —
гармоники с быстрым затуханием, пэды — расстроенные пилы, бас, лёгкие ударные),
затем общий ревербератор. Всё детерминировано.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.signal import fftconvolve

SR = 48000
NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def chord(name, octave=4):
    """'Am' → midi-ноты трезвучия от корня в заданной октаве."""
    root = name[:2] if len(name) > 1 and name[1] in "#b" else name[:1]
    q = name[len(root):]
    r = NOTE[root] + 12 * (octave + 1)
    if q.startswith("m") and not q.startswith("maj"):
        return [r, r + 3, r + 7]
    if q == "sus":
        return [r, r + 5, r + 7]
    return [r, r + 4, r + 7]


# ------------------------------------------------------------------ инструменты
def _t(d):
    return np.arange(int(d * SR)) / SR


def env_adsr(n, a=0.005, d=0.1, s=0.6, r=0.2, dur=None):
    t = np.arange(n) / SR
    dur = dur or n / SR
    e = np.where(t < a, t / max(a, 1e-4), s + (1 - s) * np.exp(-(t - a) / max(d, 1e-4)))
    rel = np.clip((t - dur + r) / max(r, 1e-4), 0, 1)
    return e * (1 - rel)


def bell(f, d=1.6, vel=1.0):
    t = _t(d)
    idx = 2.2 * np.exp(-t * 3)
    y = np.sin(2 * np.pi * f * t + idx * np.sin(2 * np.pi * f * 3.5 * t))
    y += 0.3 * np.sin(2 * np.pi * f * 2.0 * t) * np.exp(-t * 4)
    return y * np.exp(-t * 2.4) * vel * 0.5


def glock(f, d=1.2, vel=1.0):
    t = _t(d)
    y = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * f * 2.76 * t) * np.exp(-t * 6) + \
        0.15 * np.sin(2 * np.pi * f * 5.4 * t) * np.exp(-t * 10)
    return y * np.exp(-t * 3.0) * vel * 0.45


def pluck(f, d=0.6, vel=1.0, bright=1.0):
    t = _t(d)
    y = np.zeros_like(t)
    for k in range(1, 9):
        y += (1 / k ** (1.4 / bright)) * np.sin(2 * np.pi * f * k * t) * np.exp(-t * (5 + k * 3))
    y[:int(0.003 * SR)] += np.random.default_rng(int(f)).normal(0, 0.2, int(0.003 * SR))
    return y * vel * 0.35


def marimba(f, d=0.5, vel=1.0):
    t = _t(d)
    y = np.sin(2 * np.pi * f * t) * np.exp(-t * 7) + 0.25 * np.sin(2 * np.pi * f * 4 * t) * np.exp(-t * 18)
    y += 0.1 * np.sin(2 * np.pi * f * 10 * t) * np.exp(-t * 60)
    return y * vel * 0.5


def pad(freqs, d, vel=1.0, bright=6, attack=0.8, release=1.2, trem=0.0):
    t = _t(d)
    y = np.zeros_like(t)
    for f in freqs:
        for det in (-0.12, 0.0, 0.11):
            ff = f * 2 ** (det / 12)
            ph = np.random.default_rng(int(ff * 10)).uniform(0, 6.28)
            for k in range(1, bright + 1):
                y += (1 / k) * np.sin(2 * np.pi * ff * k * t + ph * k) * (0.55 ** (k - 1)) ** 0.5 / 3
    e = np.clip(t / attack, 0, 1) * np.clip((d - t) / release, 0, 1)
    if trem:
        e = e * (0.7 + 0.3 * np.sin(2 * np.pi * trem * t))
    return y * e * vel * 0.12 / max(1, len(freqs)) ** 0.5


def bass(f, d=0.5, vel=1.0):
    t = _t(d)
    y = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * 2 * f * t) + 0.1 * np.sin(2 * np.pi * 3 * f * t)
    return y * env_adsr(len(t), 0.004, 0.18, 0.5, 0.06) * vel * 0.45


def kick(vel=1.0):
    t = _t(0.35)
    f = 50 + 90 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9) * vel * 0.8


def snare(vel=1.0):
    t = _t(0.22)
    n = np.random.default_rng(3).normal(0, 1, len(t))
    n = np.diff(np.concatenate([[0], n]))
    return (0.5 * n * np.exp(-t * 18) + 0.4 * np.sin(2 * np.pi * 190 * t) * np.exp(-t * 25)) * vel * 0.35


def shaker(vel=1.0):
    t = _t(0.08)
    n = np.random.default_rng(5).normal(0, 1, len(t))
    n = np.diff(np.concatenate([[0], n]))
    return n * np.exp(-t * 60) * vel * 0.12


def timp(f, vel=1.0):
    t = _t(1.4)
    y = np.sin(2 * np.pi * f * t) * np.exp(-t * 2.5) + 0.3 * np.sin(2 * np.pi * f * 1.5 * t) * np.exp(-t * 4)
    return y * vel * 0.5


# ------------------------------------------------------------------ сцена-партитура
class Score:
    def __init__(self, dur):
        self.n = int(dur * SR) + SR * 4
        self.L = np.zeros(self.n, np.float32)
        self.R = np.zeros(self.n, np.float32)

    def add(self, t, y, pan=0.0, gain=1.0):
        i = int(t * SR)
        if i >= self.n or i < 0:
            return
        y = y[: self.n - i] * gain
        l, r = math.cos((pan + 1) * math.pi / 4), math.sin((pan + 1) * math.pi / 4)
        self.L[i:i + len(y)] += (y * l).astype(np.float32)
        self.R[i:i + len(y)] += (y * r).astype(np.float32)


CUES = {
    "theme":   dict(bpm=120, prog=["C", "G", "Am", "F"], style="theme"),
    "mystery": dict(bpm=76, prog=["Am", "F", "Dm", "E"], style="mystery"),
    "curious": dict(bpm=108, prog=["C", "Am", "Dm", "G"], style="curious"),
    "gadget":  dict(bpm=128, prog=["F", "C", "G", "C"], style="gadget"),
    "tension": dict(bpm=84, prog=["Dm", "Bb", "Gm", "A"], style="tension"),
    "wonder":  dict(bpm=70, prog=["D", "Bm", "G", "A"], style="wonder"),
    "finale":  dict(bpm=92, prog=["F", "C", "Dm", "Bb"], style="theme"),
}

# Главная тема: (доля такта, ступень от корня тоники в полутонах, длительность в долях)
THEME = [(0, 16, 1), (1, 19, 1), (2, 21, 0.5), (2.5, 19, 0.5), (3, 16, 1),
         (4, 14, 1), (5, 12, 0.5), (5.5, 14, 0.5), (6, 16, 2),
         (8, 16, 1), (9, 19, 1), (10, 24, 1), (11, 23, 0.5), (11.5, 21, 0.5),
         (12, 19, 1.5), (13.5, 17, 0.5), (14, 16, 1), (15, 14, 1)]


def render_cue(name, dur, seed=0):
    cue = CUES[name]
    bpm, prog, style = cue["bpm"], cue["prog"], cue["style"]
    beat = 60 / bpm
    bar = beat * 4
    S = Score(dur)
    rng = np.random.default_rng(seed)
    nbars = int(dur / bar) + 2
    tonic = chord(prog[0], 4)[0]
    for b in range(nbars):
        t0 = b * bar
        ch = prog[b % len(prog)]
        notes = chord(ch, 4)
        root = chord(ch, 2)[0]
        if style == "mystery":
            S.add(t0, pad([hz(n) for n in notes], bar + 0.8, 0.9, bright=4, attack=1.2), 0, 0.9)
            S.add(t0, bass(hz(root), bar * 0.9, 0.6), 0, 0.8)
            arp = notes + [notes[0] + 12, notes[1] + 12, notes[2] + 12, notes[0] + 24, notes[1] + 12]
            for k in range(8):
                S.add(t0 + k * beat / 2, bell(hz(arp[(k * 3 + b) % len(arp)] + 12), 1.6, 0.35 + 0.15 * (k % 2 == 0)),
                      0.5 * math.sin(k), 0.8)
            if b % 2 == 1:
                S.add(t0, timp(hz(root), 0.4), 0, 0.6)
        elif style == "curious":
            S.add(t0, pad([hz(n) for n in notes], bar, 0.5, bright=3, attack=0.4), 0, 0.5)
            for k in (0, 2):
                S.add(t0 + k * beat, pluck(hz(root + 12), 0.5, 1.0), -0.2, 0.9)
            S.add(t0 + 3.5 * beat, pluck(hz(root + 19), 0.3, 0.7), -0.2, 0.7)
            for k in range(8):
                n = notes[(k + (k // 3)) % 3] + (12 if k in (3, 6) else 0)
                S.add(t0 + k * beat / 2, marimba(hz(n + 12), 0.4, 0.55 if k % 2 else 0.8), 0.3, 0.7)
            for k in range(16):
                S.add(t0 + k * beat / 4, shaker(0.8 if k % 4 == 2 else 0.4), 0.4, 0.6)
            if b % 4 == 3:
                for i, d_ in enumerate((0, 12, 7)):
                    S.add(t0 + (2 + i * 0.5) * beat, glock(hz(notes[0] + 24 + d_), 1.0, 0.6), 0.2, 0.7)
        elif style == "gadget":
            for k in range(4):
                S.add(t0 + k * beat, bass(hz(root + (12 if k % 2 else 0)), beat * 0.45, 0.9), 0, 0.9)
                S.add(t0 + k * beat, kick(0.7 if k % 2 == 0 else 0.4), 0, 0.6)
                if k % 2:
                    S.add(t0 + k * beat, snare(0.8), 0.1, 0.6)
            for k in range(16):
                n = notes[k % 3] + 12 * ((k // 3) % 2)
                S.add(t0 + k * beat / 4, marimba(hz(n + 12), 0.25, 0.5), 0.35 * math.sin(k), 0.55)
            for k in range(8):
                S.add(t0 + k * beat / 2, shaker(0.6), -0.4, 0.6)
            if b % 2 == 1:
                S.add(t0 + 3 * beat, glock(hz(notes[2] + 24), 0.6, 0.6), 0.3, 0.6)
        elif style == "tension":
            S.add(t0, pad([hz(n - 12) for n in notes], bar + 0.4, 0.9, bright=5, attack=0.3, trem=7.5), 0, 0.9)
            for k in range(8):
                S.add(t0 + k * beat / 2, bass(hz(root), beat * 0.35, 0.7 if k % 2 == 0 else 0.45), 0, 0.8)
            S.add(t0, kick(0.6), 0, 0.5)
            S.add(t0 + beat * 0.5, kick(0.35), 0, 0.5)
            if b % 2 == 0:
                for i, d_ in enumerate((7, 8, 7)):
                    S.add(t0 + (2 + i * 0.66) * beat, bell(hz(notes[0] + 12 + d_), 1.4, 0.4), 0.4, 0.6)
        elif style == "wonder":
            S.add(t0, pad([hz(n) for n in notes] + [hz(notes[0] + 12)], bar + 1.0, 1.0, bright=6, attack=1.5), 0, 0.9)
            S.add(t0, bass(hz(root), bar * 0.95, 0.5), 0, 0.7)
            arp = [notes[0], notes[1], notes[2], notes[0] + 12, notes[1] + 12, notes[2] + 12, notes[0] + 24, notes[2] + 12]
            for k in range(16):
                S.add(t0 + k * beat / 4, pluck(hz(arp[k % 8] + 12), 0.9, 0.45, bright=1.5), 0.6 * math.sin(k * 0.7), 0.6)
            if b % 2 == 0:
                S.add(t0 + beat, bell(hz(notes[2] + 24), 2.0, 0.5), -0.3, 0.6)
        elif style == "theme":
            S.add(t0, pad([hz(n) for n in notes], bar, 0.6, bright=4, attack=0.25), 0, 0.6)
            for k in range(4):
                S.add(t0 + k * beat, pluck(hz(root + 12 + (7 if k == 2 else 0)), 0.45, 1.0), -0.15, 0.9)
                S.add(t0 + k * beat, kick(0.6) if k % 2 == 0 else snare(0.6), 0, 0.5)
            for k in range(8):
                S.add(t0 + k * beat / 2, shaker(0.5), 0.4, 0.6)
                S.add(t0 + k * beat / 2, marimba(hz(notes[k % 3] + 12), 0.3, 0.35), -0.3, 0.5)
            # мелодия: каждые 4 такта
            mb = b % 4
            for (pos, deg, dl) in THEME:
                if int(pos // 4) == mb:
                    tt = t0 + (pos - mb * 4) * beat
                    S.add(tt, glock(hz(tonic + deg), max(0.6, dl * beat * 1.6), 0.9), 0.15, 0.9)
                    S.add(tt, bell(hz(tonic + deg - 12), max(0.6, dl * beat * 1.4), 0.25), -0.15, 0.6)
    L, R = S.L[: int(dur * SR)], S.R[: int(dur * SR)]
    return np.stack([L, R])


def reverb(x, secs=2.0, wet=0.25, seed=1):
    n = int(secs * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    out = []
    for ch in range(x.shape[0]):
        ir = rng.normal(0, 1, n) * np.exp(-t * 6.9 / secs)
        ir[: int(0.012 * SR)] = 0
        ir /= np.sqrt(np.sum(ir ** 2))
        out.append(fftconvolve(x[ch], ir)[: x.shape[1]])
    y = np.stack(out)
    return (x * (1 - wet) + y * wet * 1.2).astype(np.float32)
