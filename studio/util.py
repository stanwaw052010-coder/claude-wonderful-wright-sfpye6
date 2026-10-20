"""Общие мелочи: цвета, сглаживание, детерминированный шум."""
from __future__ import annotations

import math
import random
import zlib
from pathlib import Path

import skia

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
W, H, FPS = 1920, 1080, 24


def hexc(h: str, a: float = 1.0) -> int:
    h = h.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return skia.ColorSetARGB(int(round(a * 255)), r, g, b)


def rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def mix(c1: str, c2: str, t: float) -> str:
    a, b = rgb(c1), rgb(c2)
    return "#" + "".join(f"{int(round((x + (y - x) * t) * 255)):02x}" for x, y in zip(a, b))


def shade_of(c: str, k: float) -> str:
    """k<0 темнее (со сдвигом в холодный фиолет), k>0 светлее (в тёплый)."""
    return mix(c, "#2a1840", -k) if k < 0 else mix(c, "#fff4dc", k)


def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def lerp(a, b, t):
    return a + (b - a) * t


def smooth(t):
    t = clamp(t)
    return t * t * (3 - 2 * t)


def ease_io(t):
    t = clamp(t)
    return 0.5 - 0.5 * math.cos(math.pi * t)


def ease_out(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_back(t, s=1.7):
    t = clamp(t) - 1
    return t * t * ((s + 1) * t + s) + 1


def hash01(*args) -> float:
    return random.Random(zlib.crc32(repr(args).encode())).random()


def vnoise(x: float, seed: int = 0) -> float:
    """Гладкий 1D value-noise в [-1, 1]."""
    i = math.floor(x)
    f = x - i
    a = random.Random(i * 7919 + seed * 104729).random()
    b = random.Random((i + 1) * 7919 + seed * 104729).random()
    return (a + (b - a) * smooth(f)) * 2 - 1


_TF: dict[str, skia.Typeface] = {}


def font(name: str, size: float) -> skia.Font:
    files = {"logo": "LuckiestGuy-Regular.ttf", "round": "Fredoka.ttf", "hand": "Caveat.ttf",
             "print": "PatrickHand-Regular.ttf", "baloo": "Baloo2.ttf"}
    if name not in _TF:
        _TF[name] = skia.Typeface.MakeFromFile(str(FONTS / files[name]))
    f = skia.Font(_TF[name], size)
    f.setEdging(skia.Font.Edging.kAntiAlias)
    return f
