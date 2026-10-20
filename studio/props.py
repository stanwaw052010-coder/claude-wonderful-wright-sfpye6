"""Реквизит в руке персонажа (координаты персонажа, рука = hand)."""
from __future__ import annotations

import math

from .draw import ellipse, flat, glow, line, paint, poly, rrect, shade
from .util import shade_of


def draw_prop(c, name, hand, st, L):
    hx, hy = hand
    t = st.t
    if name in ("letter", "letter_open"):
        c.save()
        c.translate(hx + 3, hy - 4)
        c.rotate(-8 + math.sin(t * 1.5) * 2)
        glow(c, 0, 0, 26, "#6ff2ff", 0.35 + 0.15 * math.sin(t * 4))
        if name == "letter":
            env = rrect(-9, -6, 18, 12, 1.0)
            shade(c, env, "#f3ead2", L, depth=1.2)
            line(c, [(-9, -6), (0, 1), (9, -6)], 0.7, "#b9a77c", smooth=False)
            c.drawRect(__import__("skia").Rect(4.5, -4.8, 7.8, -1.6), paint("#d0302c"))
        else:
            sheet = rrect(-8, -11, 16, 20, 0.8)
            shade(c, sheet, "#fbf6e6", L, depth=1.0)
            for k in range(6):
                line(c, [(-5.5, -7 + k * 2.6), (5.5 - (k % 2) * 2, -7 + k * 2.6)], 0.45, "#3a4a8a", 0.8, smooth=False)
        c.restore()
    elif name == "camera":
        cam = rrect(hx - 7, hy - 9, 14, 10, 2)
        shade(c, cam, "#ede3c8", L, depth=1.2)
        flat(c, ellipse(hx + 1, hy - 4, 3.6, 3.6), "#2a2830", L, line_scale=0.6)
        c.drawCircle(hx, hy - 5, 1.1, paint("#9fd8ff"))
    elif name == "flashlight":
        body = rrect(hx - 3, hy - 3.2, 13, 6.4, 1.6)
        shade(c, body, "#3a3f52", L, depth=1.0)
        flat(c, rrect(hx + 9, hy - 4.4, 4, 8.8, 1.2), "#c9a45a", L, line_scale=0.6)
        glow(c, hx + 13, hy, 14, "#fff1c4", 0.9)
    elif name == "sniffer":
        flick = 0.5 + 0.5 * math.sin(t * 11)
        box = rrect(hx - 7, hy - 8, 15, 11, 2.2)
        shade(c, box, "#8bc34a", L, depth=1.4)
        c.drawRect(__import__("skia").Rect(hx - 4.5, hy - 6, hx + 2.5, hy - 1.5), paint("#103030"))
        line(c, [(hx - 3.5, hy - 3), (hx - 1, hy - 4.5 - flick), (hx + 1.5, hy - 2.5)], 0.6, "#6ff2ff", smooth=False)
        for k, col in enumerate(("#e2483d", "#f2b233", "#6ff2ff")):
            c.drawCircle(hx + 4.8, hy - 6 + k * 2.2, 0.9, paint(col, 0.5 + 0.5 * ((k + int(t * 6)) % 3 == 0)))
        line(c, [(hx + 2, hy - 8), (hx + 6, hy - 17)], 0.9, "#9aa3b5", smooth=False)
        dish = poly([(hx + 1.5, hy - 19.5), (hx + 10.5, hy - 14.5), (hx + 6, hy - 17)])
        flat(c, ellipse(hx + 6, hy - 17, 5.0, 2.2), "#c9d1e0", L, line_scale=0.6)
        c.drawCircle(hx + 6, hy - 17, 1.0, paint("#e2483d"))
    elif name == "pen":
        line(c, [(hx - 1, hy + 1), (hx + 6, hy - 7)], 1.4, "#1f2a5a", smooth=False)
    elif name == "sandwich":
        flat(c, rrect(hx - 7, hy - 7, 14, 3.5, 1.5), "#e8c27a", L, line_scale=0.6)
        flat(c, rrect(hx - 7.5, hy - 4, 15, 2.5, 1), "#7fcf4a", L, line_scale=0.6)
        flat(c, rrect(hx - 7, hy - 2, 14, 3.5, 1.5), "#e8c27a", L, line_scale=0.6)
