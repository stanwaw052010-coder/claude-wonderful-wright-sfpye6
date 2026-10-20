"""Эффекты: «пиксели» Мерцания, конфетти, вспышка, луч прибора, частицы атмосферы.

Вся магия Pixel Pines — квадратные пиксели бирюзового #6FF2FF и янтарного #FFC966
(см. character_bible.md, правило 3). Всё детерминировано от времени — кадры
можно рендерить в любом порядке и в разных процессах.
"""
from __future__ import annotations

import math
import random

import skia

from .draw import glow, lin_grad, paint, poly
from .util import W as SW, H as SH, clamp, ease_out, hash01, hexc, smooth

CYAN, AMBER = "#6ff2ff", "#ffc966"


def pixel(c, x, y, s, col, a, rot=0.0):
    if a <= 0.01:
        return
    glow(c, x, y, s * 3.2, col, a * 0.45)
    c.save()
    c.translate(x, y)
    c.rotate(rot)
    c.drawRect(skia.Rect(-s / 2, -s / 2, s / 2, s / 2), paint(col, a))
    c.drawRect(skia.Rect(-s / 4, -s / 4, s / 4, s / 4), paint("#ffffff", a * 0.8))
    c.restore()


def burst_pixels(c, x, y, tau, count, scale, seed, life=2.6, spread=1.0):
    if tau < 0 or tau > life + 0.5:
        return
    rnd = random.Random(seed)
    for i in range(count):
        a = rnd.uniform(0, math.tau)
        sp = rnd.uniform(40, 220) * spread
        delay = rnd.uniform(0, 0.5)
        k = tau - delay
        if k < 0:
            continue
        lf = life * rnd.uniform(0.6, 1.0)
        if k > lf:
            continue
        d = sp * ease_out(k / lf) * scale
        px = x + math.cos(a) * d
        py = y + math.sin(a) * d * 0.6 - k * 60 * scale
        al = (1 - k / lf) * (0.6 + 0.4 * math.sin(k * 12 + i))
        s = rnd.choice((6, 8, 10)) * scale * 0.5
        pixel(c, px, py, s, CYAN if rnd.random() < 0.65 else AMBER, al, rot=k * 40 * (1 if i % 2 else -1))


def confetti(c, x, y, tau, count, scale, seed):
    if tau < 0 or tau > 2.6:
        return
    rnd = random.Random(seed)
    cols = ["#ff5a7a", "#ffd23f", "#6ff2ff", "#8bc34a", "#a87bff", "#ff9a3d"]
    for i in range(count):
        a = rnd.uniform(-math.pi * 0.95, -math.pi * 0.05)
        sp = rnd.uniform(300, 800) * scale * 0.4
        vx, vy = math.cos(a) * sp, math.sin(a) * sp
        g = 700 * scale * 0.4
        px = x + vx * tau
        py = y + vy * tau + 0.5 * g * tau * tau
        al = clamp(1.6 - tau * 0.6)
        c.save()
        c.translate(px, py)
        c.rotate(tau * rnd.uniform(200, 700))
        w = rnd.uniform(6, 12) * scale * 0.5
        c.drawRect(skia.Rect(-w / 2, -w / 4 * abs(math.sin(tau * 9 + i)) - 1, w / 2, w / 4), paint(rnd.choice(cols), al))
        c.restore()


def flash(c, tau):
    if 0 <= tau < 0.6:
        c.drawPaint(paint("#ffffff", (1 - tau / 0.6) ** 2 * 0.95))


def beam(c, x0, y0, x1, y1, tau, dur, col=CYAN, reverse=False, scale=1.0):
    if tau < 0 or tau > dur:
        return
    k = smooth(tau / 0.3) * (1 - smooth((tau - dur + 0.3) / 0.3))
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy) or 1
    nx, ny = -dy / L, dx / L
    wob = math.sin(tau * 30) * 3
    w0, w1 = 8 * scale, 26 * scale
    p = poly([(x0 + nx * w0, y0 + ny * w0), (x1 + nx * (w1 + wob), y1 + ny * (w1 + wob)),
              (x1 - nx * (w1 + wob), y1 - ny * (w1 + wob)), (x0 - nx * w0, y0 - ny * w0)])
    c.drawPath(p, paint(None, shader=lin_grad((x0, y0), (x1, y1), [hexc(col, 0.7 * k), hexc(col, 0.25 * k)]),
                        blend=skia.BlendMode.kPlus))
    glow(c, x0, y0, 40 * scale, col, 0.8 * k)
    glow(c, x1, y1, 90 * scale, col, 0.6 * k)
    # пиксели вдоль луча
    for i in range(26):
        f = ((tau * (1.4 if not reverse else -1.4) + i / 26) % 1.0)
        if reverse:
            f = 1 - f
        jx = math.sin(i * 7.1 + tau * 5) * 14 * scale
        pixel(c, x0 + dx * f + nx * jx, y0 + dy * f + ny * jx, 7 * scale, col if i % 3 else AMBER, 0.9 * k, rot=tau * 90 + i)


def flashlight_cone(c, x, y, facing, scale, alpha=1.0):
    L = 900 * scale / 3
    sp = 210 * scale / 3
    p = poly([(x, y - 6 * scale / 3), (x + facing * L, y - sp), (x + facing * L, y + sp * 1.2), (x, y + 6 * scale / 3)])
    c.drawPath(p, paint(None, shader=lin_grad((x, y), (x + facing * L, y), [hexc("#fff2c4", 0.38 * alpha),
                                                                           hexc("#fff2c4", 0.0)]),
                        blend=skia.BlendMode.kPlus))


# ---------------------------------------------------------------- атмосфера
def ambient(c, kind, t, cam, W, scale_z, wpos):
    """Частицы в мировых координатах; wpos(x,y,depth) → экран."""
    if not kind:
        return
    if "fireflies" in kind:
        for i in range(34):
            bx = hash01("ff", i) * W
            by = 380 + hash01("ffy", i) * 520
            x = bx + math.sin(t * 0.4 + i) * 60
            y = by + math.sin(t * 0.7 + i * 2.1) * 30
            sx, sy = wpos(x, y, 0.85)
            a = 0.5 + 0.5 * math.sin(t * 2.3 + i * 1.7)
            glow(c, sx, sy, 16 * scale_z, "#ffe58a", 0.55 * a)
            c.drawCircle(sx, sy, 2.2 * scale_z, paint("#fff6c8", a))
    if "pixels" in kind:
        for i in range(16):
            x = hash01("px", i) * W
            y = 260 + hash01("pxy", i) * 600 - (t * 14 + i * 37) % 300
            sx, sy = wpos(x, y, 0.7)
            a = max(0.0, math.sin(t * 1.3 + i * 2.4)) ** 3
            pixel(c, sx, sy, 5 * scale_z, CYAN if i % 3 else AMBER, 0.7 * a, rot=t * 20 + i)
    if "dust" in kind:
        for i in range(60):
            x = hash01("du", i) * W
            y = (hash01("duy", i) * 900 + t * (6 + i % 5)) % 1000 + 50
            x += math.sin(t * 0.5 + i) * 30
            sx, sy = wpos(x, y, 1.0)
            c.drawCircle(sx, sy, (1.2 + (i % 3) * 0.6) * scale_z, paint("#fff0d0", 0.25 + 0.2 * math.sin(t + i)))
    if kind == "leaves":
        for i in range(14):
            x = (hash01("lf", i) * W + t * 40 + math.sin(t + i) * 80) % W
            y = (hash01("lfy", i) * 1100 + t * (50 + i * 3)) % 1150 - 60
            sx, sy = wpos(x, y, 1.1)
            c.save()
            c.translate(sx, sy)
            c.rotate(t * 90 + i * 40)
            c.scale(scale_z, scale_z * abs(math.sin(t * 2 + i)) + 0.2)
            c.drawOval(skia.Rect(-7, -4, 7, 4), paint(["#e8743b", "#d9482e", "#f2a33a"][i % 3], 0.9))
            c.restore()


def vignette(c, amt):
    sh = skia.GradientShader.MakeRadial((SW / 2, SH / 2), SW * 0.72,
                                        [hexc("#000000", 0), hexc("#000000", 0), hexc("#05030f", amt)], [0, 0.55, 1])
    c.drawRect(skia.Rect(0, 0, SW, SH), paint(None, shader=sh))


def top_grad(c, col, amt):
    c.drawRect(skia.Rect(0, 0, SW, SH * 0.5), paint(None, shader=lin_grad((0, 0), (0, SH * 0.5), [hexc(col, amt),
                                                                                              hexc(col, 0)])))


def sun_wash(c, col, amt):
    sh = skia.GradientShader.MakeRadial((SW * 0.15, 0), SW, [hexc(col, amt), hexc(col, 0)])
    p = paint(None, shader=sh, blend=skia.BlendMode.kScreen)
    c.drawRect(skia.Rect(0, 0, SW, SH), p)
