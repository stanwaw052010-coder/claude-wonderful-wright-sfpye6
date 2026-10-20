"""Полноэкранная графика: вставки-детали, логотип, заставка, финальная карточка.

Текст на реквизите рисуется шрифтами (Caveat — почерк Тео), поэтому он всегда
читаемый и точный.
"""
from __future__ import annotations

import math
import random

import skia

from . import fx
from .draw import blur_paint, ellipse, glow, lin_grad, line, paint, poly, rad_grad, rrect, smooth_closed, text
from .util import H, W, clamp, ease_back, ease_out, font, hexc, smooth


def _bg(c, top, bot, blobs=()):
    c.drawRect(skia.Rect(0, 0, W, H), paint(None, shader=lin_grad((0, 0), (0, H), [top, bot])))
    for (x, y, r, col, a) in blobs:
        glow(c, x, y, r, col, a, blend=skia.BlendMode.kScreen)


def _push(c, tau, amt=0.04, dur=6.0):
    z = 1 + amt * smooth(tau / dur)
    c.translate(W / 2, H / 2)
    c.scale(z, z)
    c.translate(-W / 2, -H / 2)


def _paper(c, x, y, w, h, col="#fbf6e6", rot=0.0, shadow=True):
    c.save()
    c.translate(x + w / 2, y + h / 2)
    c.rotate(rot)
    c.translate(-w / 2, -h / 2)
    if shadow:
        c.drawRect(skia.Rect(14, 20, w + 14, h + 20), blur_paint(18, "#000000", 0.45))
    c.drawRect(skia.Rect(0, 0, w, h), paint(None, shader=lin_grad((0, 0), (w, h), [col, "#efe4c8"])))
    return c  # вызывающий делает restore


def postmark(c, x, y, r, lines, col="#3a4a8a", a=0.85):
    c.drawCircle(x, y, r, paint(col, a, stroke=5))
    c.drawCircle(x, y, r * 0.72, paint(col, a, stroke=2.5))
    f = font("round", r * 0.26)
    for i, s in enumerate(lines):
        text(c, s, x, y + (i - (len(lines) - 1) / 2) * r * 0.32 + r * 0.09, f, col, align="center", alpha=a)
    for k in range(4):
        yy = y - r * 0.5 + k * r * 0.33
        line(c, [(x + r * 1.15, yy), (x + r * 1.5, yy - 6), (x + r * 1.85, yy), (x + r * 2.2, yy - 6), (x + r * 2.6, yy)],
             3, col, a * 0.8)


def pixel_pine_icon(c, x, y, s, cols=("#2fd28a", "#6ff2ff")):
    """Фирменный значок: ель из пикселей."""
    rows = [1, 3, 3, 5, 5, 7, 7, 9]
    for r, n in enumerate(rows):
        for k in range(n):
            px = x + (k - n / 2) * s
            py = y + r * s
            col = cols[1] if (r + k) % 5 == 0 else cols[0]
            c.drawRect(skia.Rect(px, py, px + s * 0.92, py + s * 0.92), paint(col))
    c.drawRect(skia.Rect(x - s * 0.5, y + len(rows) * s, x + s * 0.5, y + (len(rows) + 1.4) * s), paint("#8a5a34"))


def logo(c, cx, cy, sc=1.0, reveal=1.0, tag=True, t=0.0):
    """PIXEL PINES: белое «Pixel», жёлтое «PINES», пиксельная ель, слоган."""
    c.save()
    c.translate(cx, cy)
    c.scale(sc, sc)
    f1 = font("logo", 150)
    f2 = font("logo", 190)
    word1, word2 = "Pixel", "PINES"
    w1 = f1.measureText(word1)
    w2 = f2.measureText(word2)
    # «Pixel» — буквы падают по очереди
    x = -w1 / 2 - 40
    for i, ch in enumerate(word1):
        k = clamp(reveal * 7 - i * 0.6)
        if k <= 0:
            x += f1.measureText(ch)
            continue
        dy = (1 - ease_back(k)) * -160
        cw = f1.measureText(ch)
        rot = (i % 2 * 2 - 1) * 3
        c.save()
        c.translate(x + cw / 2, -60 + dy)
        c.rotate(rot)
        text(c, ch, 0, 0, f1, "#1a1440", align="center", stroke=26, stroke_color="#0d0a24",
             shadow=(8, 12, 6, "#000000", 0.5))
        text(c, ch, 0, 0, f1, "#ffffff", align="center", stroke=10, stroke_color="#0d0a24")
        c.restore()
        x += cw
    # «PINES»
    k2 = clamp(reveal * 3 - 1.6)
    if k2 > 0:
        s2 = ease_back(k2, 2.2)
        c.save()
        c.translate(0, 130)
        c.scale(s2, s2)
        sh = lin_grad((0, -150), (0, 10), ["#ffe45c", "#ffb81c"])
        text(c, word2, 0, 0, f2, "#0d0a24", align="center", stroke=30, stroke_color="#0d0a24",
             shadow=(8, 14, 6, "#000000", 0.5))
        w = f2.measureText(word2)
        p = paint(None, shader=sh)
        c.drawString(word2, -w / 2, 0, f2, p)
        c.drawString(word2, -w / 2, 0, f2, paint("#0d0a24", stroke=5))
        c.restore()
    # пиксельная ель над «l»
    k3 = clamp(reveal * 3 - 1.2)
    if k3 > 0:
        c.save()
        c.translate(w1 / 2 - 52, -250 + (1 - ease_out(k3)) * -60)
        pixel_pine_icon(c, 0, 0, 13 * k3)
        c.restore()
        for i in range(6):
            fx.pixel(c, w1 / 2 - 50 + math.sin(t * 1.3 + i) * 90, -220 + math.cos(t * 0.9 + i * 2) * 60, 9,
                     fx.CYAN if i % 2 else fx.AMBER, 0.7 * k3 * (0.5 + 0.5 * math.sin(t * 3 + i)))
    if tag:
        k4 = clamp(reveal * 3 - 2.2)
        if k4 > 0:
            f3 = font("round", 52)
            s = "SMALL TOWN. BIG MYSTERIES."
            tw = f3.measureText(s)
            c.save()
            c.translate(0, 240)
            c.rotate(-3)
            c.clipRect(skia.Rect(-tw / 2 - 20, -80, -tw / 2 - 20 + (tw + 40) * ease_out(k4), 60))
            text(c, s, 0, 0, f3, "#0d0a24", align="center", stroke=16, stroke_color="#0d0a24")
            text(c, s, 0, 0, f3, "#bff6ff", align="center")
            line(c, [(-tw / 2, 26), (0, 18), (tw / 2 + 30, 10)], 7, "#6ff2ff")
            c.restore()
    c.restore()


# ====================================================================== вставки
def draw_insert(c, item, tau, set_def=None):
    _push_amt = 0.05
    c.save()
    _push(c, tau, _push_amt)
    if item == "mailbox_open":
        _bg(c, "#0a1236", "#1d3170", [(1500, 200, 500, "#5a8aff", 0.3)])
        for i in range(60):
            c.drawCircle(random.Random(i).uniform(0, W), random.Random(i + 99).uniform(0, 500), 2, paint("#e8f0ff", 0.4))
        # ящик крупно
        mb = rrect(380, 330, 1060, 520, 250)
        c.drawPath(mb, paint(None, shader=lin_grad((0, 330), (0, 850), ["#3d6fb0", "#1f3d70"])))
        c.drawPath(mb, paint("#0d0a24", stroke=12))
        c.drawPath(rrect(420, 380, 980, 430, 210), paint("#0a1430"))
        text(c, "BRAMBLE", 910, 820, font("round", 60), "#ffffff", align="center", alpha=0.9)
        # перчатка и конверт въезжают
        k = ease_out(clamp(tau / 1.1))
        ex = 1700 - 900 * k
        c.save()
        c.translate(ex, 590)
        c.rotate(-4)
        glow(c, 0, 0, 260, "#6ff2ff", 0.5)
        c.drawPath(rrect(-170, -105, 340, 210, 10), paint("#f3ead2"))
        c.drawPath(rrect(-170, -105, 340, 210, 10), paint("#0d0a24", stroke=6))
        line(c, [(-170, -105), (0, 20), (170, -105)], 5, "#b9a77c", smooth=False)
        c.drawPath(rrect(150, -60, 260, 140, 60), paint("#121828"))
        c.restore()
        # флажок поднимается
        fk = ease_back(clamp((tau - 1.0) / 0.4))
        c.save()
        c.translate(1420, 420)
        c.rotate(-90 * fk)
        c.drawRect(skia.Rect(-10, -10, 10, 200), paint("#d0302c"))
        c.drawRect(skia.Rect(-10, 170, 90, 210), paint("#d0302c"))
        c.restore()
    elif item in ("envelope", "envelope_june"):
        june = item == "envelope_june"
        if june:
            _bg(c, "#3a1a3a", "#ff9a6a", [(1400, 300, 600, "#ffcf80", 0.5)])
        else:
            _bg(c, "#9fd0ff", "#ffe2b8", [(300, 200, 600, "#ffffff", 0.5), (1700, 900, 500, "#f2b233", 0.5)])
        c.save()
        c.translate(W / 2, H / 2 + 10)
        c.rotate(-3 + math.sin(tau * 1.2) * 1)
        glow(c, 0, 0, 760, "#6ff2ff", 0.32 + 0.1 * math.sin(tau * 3))
        col = "#f3ead2" if not june else "#e8d3a8"
        c.drawRect(skia.Rect(-600, -330, 620, 350), blur_paint(24, "#000000", 0.4))
        c.drawPath(rrect(-620, -350, 1240, 700, 16), paint(None, shader=lin_grad((0, -350), (0, 350), [col, "#e2d4b0"])))
        c.drawPath(rrect(-620, -350, 1240, 700, 16), paint("#6a5a3a", stroke=5))
        # марка
        c.drawPath(rrect(380, -300, 190, 230, 6), paint("#ffffff"))
        c.drawPath(rrect(395, -285, 160, 200, 4), paint("#1f3a6e" if not june else "#6a3a2a"))
        pixel_pine_icon(c, 475, -265, 15)
        # штемпель
        postmark(c, 270, -170, 120, ["PIXEL PINES", "SAT · OCT 24" if not june else "OCT 24 · 1887", "AM"],
                 col="#2a3a8a" if not june else "#7a2a2a")
        fh = font("hand", 110)
        if june:
            text(c, "June Okafor", -420, 40, fh, "#3a2a1a")
            text(c, "Maple Row, Pixel Pines", -420, 160, font("hand", 80), "#3a2a1a")
        else:
            text(c, "Theo Bramble", -440, 40, fh, "#1f2a6a")
            text(c, "12 Maple Row, Pixel Pines", -440, 160, font("hand", 80), "#1f2a6a")
        c.restore()
        for i in range(10):
            fx.pixel(c, 200 + i * 170 + math.sin(tau + i) * 30, 980 - ((tau * 60 + i * 90) % 900), 12, fx.CYAN if i % 2 else fx.AMBER,
                     0.6 * max(0, math.sin(tau * 2 + i)))
    elif item == "letter":
        _bg(c, "#ffe2b8", "#f2b233", [(1600, 200, 600, "#ffffff", 0.4)])
        c.save()
        c.translate(W / 2, H / 2)
        c.rotate(2)
        c.drawRect(skia.Rect(-520, -470, 560, 520), blur_paint(24, "#000000", 0.35))
        c.drawPath(rrect(-540, -500, 1080, 1000, 6), paint(None, shader=lin_grad((0, -500), (0, 500), ["#fffdf2", "#f1e8cf"])))
        for k in range(14):
            yy = -380 + k * 64
            line(c, [(-480, yy + 18), (480, yy + 18)], 2, "#a8c4e8", 0.6, smooth=False)
        line(c, [(-400, -500), (-400, 500)], 3, "#e8a0a0", 0.7, smooth=False)
        rows = [("Theo —", 0), ("Don't let them turn off", 1), ("the Lantern.", 2), ("Bring June. Bring Dot.", 3),
                ("Bring the dog.", 4), ("— Theo", 5.6), ("P.S. Don't eat the green sandwich.", 7.2)]
        fh = font("hand", 82)
        total = 3.6
        for s, r in rows:
            k = clamp((tau - r * 0.45) / 0.5)
            if k <= 0:
                continue
            x0 = -370
            yy = -330 + r * 64 * 1.15
            w = fh.measureText(s)
            c.save()
            c.clipRect(skia.Rect(x0 - 10, yy - 90, x0 + (w + 20) * k, yy + 30))
            text(c, s, x0 + (200 if s == "— Theo" else 0), yy, fh if not s.startswith("P.S.") else font("hand", 60), "#1f2a6a")
            c.restore()
        c.restore()
    elif item in ("photo_letter", "photo_threads"):
        _bg(c, "#2a1a3a", "#0a0a20" if item == "photo_threads" else "#5a4a3a", [(960, 540, 700, "#ffffff", 0.15)])
        dev = clamp(tau / 1.8)
        c.save()
        c.translate(W / 2, H / 2 + (1 - ease_out(clamp(tau / 0.6))) * 300)
        c.rotate(-4)
        c.drawRect(skia.Rect(-400, -440, 440, 500), blur_paint(24, "#000000", 0.5))
        c.drawPath(rrect(-420, -460, 840, 960, 10), paint("#fbf8f0"))
        img = skia.Rect(-370, -410, 370, 330)
        c.save()
        c.clipRect(img)
        if item == "photo_letter":
            c.drawRect(img, paint(None, shader=lin_grad((0, -410), (0, 330), ["#d8e8ff", "#f8d8a0"])))
            # силуэт холма с фабрикой
            c.drawPath(poly([(-370, 120), (-100, 40), (150, 70), (370, 0), (370, 330), (-370, 330)]), paint("#4a5a7a"))
            c.drawRect(skia.Rect(200, -90, 236, 40), paint("#3a2a3a"))
            c.drawPath(poly([(190, -90), (218, -130), (246, -90)]), paint("#3a2a3a"))
            c.drawCircle(218, -60, 9, paint("#ffd27a"))
            glow(c, 218, -60, 60, "#ffc060", 0.7)
            # письмо в руке
            c.save()
            c.translate(-120, 170)
            c.rotate(-8)
            c.drawPath(rrect(-170, -120, 340, 230, 6), paint("#fbf6e6"))
            for k in range(5):
                line(c, [(-130, -80 + k * 38), (120, -80 + k * 38)], 6, "#4a5a9a", 0.7, smooth=False)
            c.restore()
            # светящаяся стрелка к фабрике
            ak = clamp((tau - 1.2) / 1.0)
            pts = [(-60, 90), (40, 0), (130, -40), (200, -60)]
            n = int(len(pts) * ak) + 1
            if ak > 0:
                line(c, pts[:max(2, n)], 14, "#6ff2ff", 0.9 * ak)
                glow(c, 200, -60, 90, "#6ff2ff", 0.6 * ak)
                for i in range(8):
                    fx.pixel(c, -60 + i * 34, 90 - i * 20, 10, fx.CYAN, 0.8 * ak)
        else:
            c.drawRect(img, paint(None, shader=lin_grad((0, -410), (0, 330), ["#1a1430", "#3a2440"])))
            lx, ly = 0, -180
            rnd = random.Random(4)
            houses = [(rnd.uniform(-340, 340), rnd.uniform(130, 290)) for _ in range(16)]
            ak = clamp((tau - 1.0) / 1.6)
            for (hx, hy) in houses:
                c.drawRect(skia.Rect(hx - 18, hy - 22, hx + 18, hy + 10), paint("#2a2050"))
                c.drawPath(poly([(hx - 24, hy - 22), (hx, hy - 42), (hx + 24, hy - 22)]), paint("#1a1440"))
                c.drawRect(skia.Rect(hx - 6, hy - 14, hx + 6, hy - 4), paint("#ffcf70"))
                if ak > 0:
                    mx, my = (lx + hx) / 2, (ly + hy) / 2 - 60
                    p = skia.Path()
                    p.moveTo(lx, ly)
                    p.quadTo(mx, my, lx + (hx - lx) * ak, ly + (hy - ly) * ak)
                    c.drawPath(p, paint("#ffd27a", 0.85, stroke=3.5))
            c.drawRect(skia.Rect(lx - 26, ly - 30, lx + 26, ly + 40), paint("#c9a45a"))
            c.drawCircle(lx, ly + 6, 18, paint("#fff3c4"))
            glow(c, lx, ly + 6, 160, "#ffc060", 0.9)
        # проявка
        c.drawRect(img, paint("#1a1420", 1 - dev))
        c.restore()
        c.restore()
    elif item == "flyer":
        _bg(c, "#b8864e", "#8a5a34")
        c.save()
        c.translate(W / 2, H / 2)
        c.rotate(-2)
        c.drawRect(skia.Rect(-430, -470, 470, 520), blur_paint(20, "#000000", 0.4))
        c.drawPath(rrect(-450, -490, 900, 980, 4), paint("#fff7e0"))
        c.drawCircle(0, -450, 22, paint("#d0302c"))
        text(c, "TOWN OF PIXEL PINES", 0, -360, font("round", 50), "#2a1f2e", align="center")
        text(c, "LUMEN MILL", 0, -230, font("logo", 120), "#2a1f2e", align="center")
        text(c, "DEMOLITION", 0, -100, font("logo", 120), "#c0392b", align="center")
        c.drawRect(skia.Rect(-380, -50, 380, 60), paint("#ffd23f"))
        text(c, "SATURDAY · OCTOBER 24", 0, 24, font("round", 64), "#2a1f2e", align="center")
        text(c, "Make way for the new", 0, 170, font("print", 66), "#2a1f2e", align="center")
        text(c, "Main Street Parking Lot!", 0, 250, font("print", 66), "#2a1f2e", align="center")
        text(c, "— Mayor Pruitt", 120, 380, font("print", 54), "#5a4a4a", align="center")
        c.restore()
    elif item == "plaque":
        _bg(c, "#1a0e18", "#3a2420", [(960, 300, 700, "#ffb050", 0.35 + 0.08 * math.sin(tau * 7))])
        c.save()
        c.translate(W / 2, H / 2 + 20)
        c.drawPath(rrect(-700, -320, 1400, 640, 30), paint(None, shader=lin_grad((0, -320), (0, 320), ["#e6c06a", "#9a7430"])))
        c.drawPath(rrect(-700, -320, 1400, 640, 30), paint("#5a3a14", stroke=12))
        c.drawPath(rrect(-660, -280, 1320, 560, 20), paint("#5a3a14", 0.6, stroke=4))
        for sx in (-640, 640):
            for sy in (-260, 260):
                c.drawCircle(sx, sy, 14, paint("#7a5420"))
        fe = font("round", 54)
        text(c, "LUMEN LANTERN No. 1 · 1887", 0, -180, fe, "#4a2a0a", align="center")
        rows = ["Keep one light burning,", "and the Pines will remember", "the way home."]
        for i, s in enumerate(rows):
            k = clamp((tau - 0.4 - i * 1.1) / 0.8)
            text(c, s, 0, -60 + i * 90, font("print", 74), "#3a1e06", align="center", alpha=k)
        text(c, "— A.L.", 420, 250, font("print", 64), "#3a1e06", align="center", alpha=clamp((tau - 3.6) / 0.6))
        glow(c, -200, -200, 400, "#fff3c4", 0.2, blend=skia.BlendMode.kScreen)
        c.restore()
    c.restore()


# ====================================================================== заставка
def draw_title(c, tau, render_world):
    """17 с: логотип собирается над ночным городом, затем герои на холме."""
    render_world(c, tau)
    if tau < 9.0:
        k = clamp(tau / 4.0)
        a = 1 - smooth((tau - 8.2) / 0.8)
        c.saveLayerAlpha(None, int(255 * a))
        logo(c, W / 2, H / 2 - 40, 1.25, reveal=k, t=tau)
        c.restore()
    else:
        k = clamp((tau - 14.6) / 1.4)
        logo(c, W * 0.5, 230, 0.62 * (0.85 + 0.15 * smooth((tau - 9) / 1)), reveal=1.0, t=tau)
    fade = clamp(tau / 0.6) * (1 - smooth((tau - 16.3) / 0.7))
    if fade < 1:
        c.drawPaint(paint("#000000", 1 - fade))


def draw_endcard(c, tau, render_world, dur):
    render_world(c, tau)
    c.drawPaint(paint("#05081e", 0.35))
    logo(c, W / 2, 230, 0.55, reveal=1.0, tag=False, t=tau)
    f = font("round", 46)
    text(c, "NEXT TIME", W / 2, 520, f, "#bff6ff", align="center", stroke=12, stroke_color="#0d0a24")
    text(c, "The Shadow That Ran Late", W / 2, 620, font("logo", 86), "#ffd23f", align="center", stroke=18,
         stroke_color="#0d0a24")
    k = clamp((dur - tau - 0.2) / 0.8)
    text(c, "SMALL TOWN. BIG MYSTERIES.", W / 2, 990, font("round", 40), "#ffffff", align="center", alpha=0.85)
    if k < 1:
        c.drawPaint(paint("#000000", 1 - k))
