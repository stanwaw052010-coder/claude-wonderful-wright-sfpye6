"""Декорации Pixel Pines. Каждая — набор слоёв с параллаксом + живые источники света.

Мир: высота 1080 px (как кадр), ширина — у каждой декорации своя. Слои рендерятся
один раз с запасом разрешения (SS) и дальше только кадрируются камерой.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import numpy as np
import skia

from .draw import (Light, blob, ellipse, glow, lin_grad, line, paint, poly, rad_grad, rrect, smooth_closed, smooth_open,
                   text)
from .util import font, hexc, mix, shade_of

SS = 1.5           # суперсэмплинг слоёв
Y0, Y1 = -80, 1160  # вертикальный запас мира


@dataclass
class Lamp:
    x: float
    y: float
    r: float
    color: str
    alpha: float = 0.8
    flicker: float = 0.05
    depth: float = 1.0
    key: str = ""


@dataclass
class SetDef:
    name: str
    width: int
    ground: float
    scale: float                      # px мира на единицу персонажа
    light: Light
    tint: tuple = (1.0, 1.0, 1.0)     # множитель цвета персонажей
    tint_add: tuple = (0.0, 0.0, 0.0)
    layers: list = field(default_factory=list)   # [(depth, skia.Image)]
    front: list = field(default_factory=list)    # слои перед персонажами
    lamps: list = field(default_factory=list)
    particles: str = ""
    overlay: list = field(default_factory=list)  # [(kind, args)] — градиенты поверх кадра
    shadow_color: str = "#000000"
    shadow_alpha: float = 0.3
    data: dict = field(default_factory=dict)


def _surface(w):
    arr = np.zeros((int((Y1 - Y0) * SS), int(w * SS), 4), np.uint8)
    s = skia.Surface(arr)
    c = s.getCanvas()
    c.scale(SS, SS)
    c.translate(0, -Y0)
    return arr, s, c


def _img(arr):
    return skia.Image.fromarray(arr, colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kPremul_AlphaType)


class Layers:
    def __init__(self, width):
        self.width = width
        self.out = []

    def layer(self, depth, fn, front=False):
        arr, s, c = _surface(self.width)
        fn(c)
        self.out.append((depth, _img(arr), front))


# ================================================================ кисти пейзажа
def sky(c, W, stops, pos=None):
    c.drawRect(skia.Rect(0, Y0, W, Y1), paint(None, shader=lin_grad((0, Y0), (0, 760), stops, pos)))


def stars(c, W, n, seed=1, ymax=520, alpha=0.9):
    rnd = random.Random(seed)
    for _ in range(n):
        x, y = rnd.uniform(0, W), rnd.uniform(Y0, ymax)
        r = rnd.choice((0.8, 1.0, 1.2, 1.6, 2.2))
        a = alpha * rnd.uniform(0.35, 1.0) * (1 - max(0, y) / (ymax * 1.4))
        c.drawCircle(x, y, r, paint("#e8f0ff", a))
        if r > 1.9:
            glow(c, x, y, r * 6, "#9cc4ff", a * 0.5)


def moon(c, x, y, r):
    glow(c, x, y, r * 7, "#4f86ff", 0.35)
    glow(c, x, y, r * 2.6, "#bcd4ff", 0.5)
    c.drawCircle(x, y, r, paint(None, shader=rad_grad((x - r * 0.3, y - r * 0.3), r * 1.3, ["#ffffff", "#dfe9ff", "#b9cdf5"])))
    rnd = random.Random(7)
    for _ in range(6):
        a, d = rnd.uniform(0, 6.28), rnd.uniform(0, r * 0.6)
        c.drawCircle(x + math.cos(a) * d, y + math.sin(a) * d, rnd.uniform(r * 0.08, r * 0.2), paint("#a9bde6", 0.45))


def cloud(c, x, y, w, color, alpha):
    p = paint(color, alpha)
    p.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, w * 0.06))
    rnd = random.Random(int(x))
    for i in range(6):
        cx = x + (i - 2.5) * w * 0.16 + rnd.uniform(-10, 10)
        c.drawOval(skia.Rect(cx - w * 0.16, y - w * 0.06 - rnd.uniform(0, w * 0.05), cx + w * 0.16, y + w * 0.05), p)


def ridge(c, W, base, height, color, seed, rough=0.5, step=40, top_color=None, snow=False):
    rnd = random.Random(seed)
    pts = [(-50, Y1)]
    x = -50
    y = base - height * rnd.uniform(0.4, 0.9)
    peaks = []
    while x < W + 100:
        x += step * rnd.uniform(0.6, 1.4)
        y += rnd.uniform(-1, 1) * height * rough * 0.35
        y = min(base - height * 0.15, max(base - height, y))
        pts.append((x, y))
        peaks.append((x, y))
    pts.append((W + 100, Y1))
    path = poly(pts)
    sh = lin_grad((0, base - height), (0, base + 80), [top_color or color, color])
    c.drawPath(path, paint(None, shader=sh))
    if snow and False:
        for (px, py) in peaks:
            if py < base - height * 0.75:
                c.drawPath(poly([(px - 26, py + 22), (px, py - 1), (px + 24, py + 20), (px + 8, py + 14), (px - 6, py + 24)]),
                           paint("#c7d6f5", 0.55))
    return peaks


def pine(c, x, base, h, dark, light, rim=None, rim_alpha=0.0, lean=0.0, trunk=None, glow_px=None):
    """Стилизованная ель: ярусы-«юбки», светлая сторона слева."""
    w = h * 0.36
    tiers = max(4, int(h / 38))
    pts_l, pts_r = [], []
    for i in range(tiers + 1):
        k = i / tiers
        yy = base - h * (1 - k) * 0.94 - h * 0.06
        ww = w * (0.08 + 0.92 * k)
        sag = h * 0.035
        pts_l += [(x - ww * 0.62 + lean * (1 - k), yy - sag * 0.4), (x - ww + lean * (1 - k), yy + sag)]
        pts_r += [(x + ww * 0.62 + lean * (1 - k), yy - sag * 0.4), (x + ww + lean * (1 - k), yy + sag)]
    top = (x + lean, base - h)
    if trunk:
        c.drawRect(skia.Rect(x - w * 0.06, base - h * 0.08, x + w * 0.06, base + 4), paint(trunk))
    path = poly([top] + pts_r + [(x, base - h * 0.03)] + pts_l[::-1])
    c.drawPath(path, paint(dark))
    c.save()
    c.clipPath(path, doAntiAlias=True)
    c.drawPath(poly([top] + pts_l + [(x + w * 0.05, base)]), paint(light))
    if rim and rim_alpha > 0:
        c.drawPath(poly([(p[0] + 5, p[1]) for p in ([top] + pts_r)] + [(x + w * 2, base)] + [(x + w * 2, base - h)]),
                   paint(rim, 0, blend=skia.BlendMode.kScreen))
        rp = paint(rim, rim_alpha, stroke=3.0)
        rp.setBlendMode(skia.BlendMode.kScreen)
        c.drawPath(poly([top] + pts_r, close=False), rp)
    c.restore()
    if glow_px:
        rnd = random.Random(int(x * 13 + h))
        for _ in range(glow_px):
            px = x + rnd.uniform(-w, w) * 0.8
            py = base - rnd.uniform(0.08, 0.9) * h
            s = rnd.choice((3, 4, 5))
            col = "#6ff2ff" if rnd.random() < 0.7 else "#ffc966"
            c.drawRect(skia.Rect(px, py, px + s, py + s), paint(col, 0.85))
    return path


def pine_row(c, W, base, hmin, hmax, dark, light, seed, gap=(60, 140), rim=None, rim_alpha=0.0, trunk=None,
             glow_px=None, skip=None):
    rnd = random.Random(seed)
    x = rnd.uniform(-60, 40)
    while x < W + 80:
        if not (skip and skip[0] < x < skip[1]):
            pine(c, x, base + rnd.uniform(-8, 8), rnd.uniform(hmin, hmax), dark, light, rim, rim_alpha,
                 lean=rnd.uniform(-6, 6), trunk=trunk, glow_px=glow_px)
        x += rnd.uniform(*gap)


def fog(c, W, y, h, color, alpha):
    c.drawRect(skia.Rect(0, y - h, W, y + h), paint(None, shader=lin_grad((0, y - h), (0, y + h),
                                                                         [hexc(color, 0), hexc(color, alpha), hexc(color, 0)])))


def window(c, x, y, w, h, lit=True, warm="#ffcf70", frame="#2a1f2e", curtain=None, glow_r=1.0, dark="#1b2546"):
    c.drawRect(skia.Rect(x - 3, y - 3, x + w + 3, y + h + 3), paint(frame))
    if lit:
        c.drawRect(skia.Rect(x, y, x + w, y + h), paint(None, shader=lin_grad((x, y), (x, y + h), [mix(warm, "#fff6d8", 0.4), warm])))
        if curtain:
            c.drawPath(poly([(x, y), (x + w * 0.3, y), (x + w * 0.18, y + h), (x, y + h)]), paint(curtain, 0.85))
            c.drawPath(poly([(x + w, y), (x + w * 0.7, y), (x + w * 0.82, y + h), (x + w, y + h)]), paint(curtain, 0.85))
        glow(c, x + w / 2, y + h / 2, min(w, h) * 1.5 * glow_r, warm, 0.22, blend=skia.BlendMode.kScreen)
    else:
        c.drawRect(skia.Rect(x, y, x + w, y + h), paint(dark))
        c.drawPath(poly([(x, y + h * 0.7), (x + w * 0.5, y), (x + w * 0.7, y), (x, y + h)]), paint("#ffffff", 0.06))
    c.drawRect(skia.Rect(x + w / 2 - 1.5, y, x + w / 2 + 1.5, y + h), paint(frame))
    c.drawRect(skia.Rect(x, y + h / 2 - 1.5, x + w, y + h / 2 + 1.5), paint(frame))


def building(c, x, base, w, h, wall, roof, kind="flat", lit=0.7, seed=0, sign=None, sign_col="#ff6b9a", trim="#e8d9c0",
             warm="#ffcf70", awning=None):
    rnd = random.Random(seed)
    top = base - h
    wall_sh = lin_grad((x, top), (x + w, top), [wall, shade_of(wall, -0.25)])
    c.drawRect(skia.Rect(x, top, x + w, base), paint(None, shader=wall_sh))
    # бревна / сайдинг
    for yy in range(int(top) + 14, int(base), 14):
        c.drawRect(skia.Rect(x, yy, x + w, yy + 1.5), paint(shade_of(wall, -0.18), 0.6))
    if kind == "gable":
        c.drawPath(poly([(x - 14, top + 2), (x + w / 2, top - h * 0.42), (x + w + 14, top + 2)]), paint(roof))
        c.drawPath(poly([(x - 14, top + 2), (x + w / 2, top - h * 0.42), (x + w / 2, top - h * 0.42 + 10), (x - 4, top + 6)]),
                   paint(shade_of(roof, 0.12)))
        window(c, x + w / 2 - 14, top - h * 0.2, 28, 30, lit=rnd.random() < lit, warm=warm)
    elif kind == "false_front":
        c.drawRect(skia.Rect(x - 6, top - 46, x + w + 6, top + 4), paint(shade_of(wall, -0.08)))
        c.drawRect(skia.Rect(x - 10, top - 52, x + w + 10, top - 44), paint(trim))
    else:
        c.drawRect(skia.Rect(x - 8, top - 10, x + w + 8, top + 2), paint(roof))
    c.drawRect(skia.Rect(x - 4, top - 2, x + w + 4, top + 6), paint(trim))
    # окна верхнего этажа
    nwin = max(1, int(w / 70))
    for i in range(nwin):
        wx = x + (i + 0.5) * w / nwin - 18
        window(c, wx, top + 26, 36, 46, lit=rnd.random() < lit, warm=warm, curtain="#b0454f" if rnd.random() < 0.4 else None)
    # витрина
    sw = w * 0.62
    window(c, x + w * 0.08, base - 120, sw, 86, lit=rnd.random() < lit + 0.15, warm=warm)
    c.drawRect(skia.Rect(x + w * 0.76, base - 118, x + w * 0.92, base), paint("#3a2430"))
    c.drawCircle(x + w * 0.79, base - 58, 2.5, paint("#e8c14e"))
    if awning:
        for k in range(int(sw / 24) + 1):
            col = awning if k % 2 == 0 else "#f4ead8"
            ax = x + w * 0.06 + k * 24
            c.drawPath(poly([(ax, base - 150), (ax + 24, base - 150), (ax + 28, base - 126), (ax - 2, base - 126)]), paint(col))
    if sign:
        f = font("round", 26)
        tw = f.measureText(sign)
        sx = x + w / 2 - tw / 2
        c.drawRect(skia.Rect(sx - 12, base - 176, sx + tw + 12, base - 140), paint("#2a1f2e"))
        text(c, sign, x + w / 2, base - 149, f, sign_col, align="center")
        glow(c, x + w / 2, base - 158, tw * 0.9, sign_col, 0.25)


def lamp_post(c, x, base, h=250, color="#2a2f4a"):
    c.drawRect(skia.Rect(x - 4, base - h, x + 4, base), paint(color))
    c.drawRect(skia.Rect(x - 10, base - 12, x + 10, base), paint(color))
    c.drawPath(poly([(x - 14, base - h), (x + 14, base - h), (x + 9, base - h - 30), (x - 9, base - h - 30)]), paint("#ffe7b0"))
    c.drawRect(skia.Rect(x - 16, base - h - 34, x + 16, base - h - 28), paint(color))
    c.drawRect(skia.Rect(x - 16, base - h - 2, x + 16, base - h + 4), paint(color))


def grass_tufts(c, W, base, color, seed, n=120, hmax=18):
    rnd = random.Random(seed)
    for _ in range(n):
        x = rnd.uniform(0, W)
        hh = rnd.uniform(6, hmax)
        line(c, [(x, base + rnd.uniform(0, 30)), (x + rnd.uniform(-4, 4), base - hh)], 2.2, color, 0.8, smooth=False)


# ================================================================ декорации
def build(name: str, light: str) -> SetDef:
    return {"main_street": main_street, "maple_row": maple_row, "garage": garage, "forest": forest,
            "mill_exterior": mill_exterior, "mill_interior": mill_interior, "lookout": lookout,
            "end_card": end_card}[name](light)


NIGHT_L = Light(key=(-0.35, -0.9), rim="#7cc8ff", rim_dir=(0.85, -0.3), rim_alpha=0.65, outline="#1a1430")


def main_street(light="night") -> SetDef:
    W = 3400
    G = 900
    S = SetDef("main_street", W, G, 2.9, NIGHT_L, tint=(0.72, 0.8, 1.0), tint_add=(0.0, 0.01, 0.05),
               particles="fireflies_pixels", shadow_color="#050a1e", shadow_alpha=0.45)
    L = Layers(W)

    def far(c):
        sky(c, W, ["#060b24", "#0d1c4f", "#1d3c86", "#2f5aa8"], [0, 0.35, 0.75, 1])
        stars(c, W, 260, seed=3)
        moon(c, W * 0.72, 150, 58)
        cloud(c, 700, 260, 520, "#25407f", 0.55)
        cloud(c, 2300, 200, 640, "#22397a", 0.5)
        ridge(c, W, 640, 260, "#14245a", 11, top_color="#22397a", snow=True)
    L.layer(0.15, far)

    def mid(c):
        ridge(c, W, 700, 140, "#0f1c48", 12, rough=0.8, step=60, top_color="#1a2c63")
        fog(c, W, 690, 50, "#3a5fae", 0.35)
        pine_row(c, W, 720, 120, 220, "#0b1838", "#13265a", 21, gap=(40, 90), rim="#5d8fe6", rim_alpha=0.35,
                 glow_px=3)
    L.layer(0.4, mid)

    def street(c):
        # дома
        xs = 120
        rnd = random.Random(5)
        names = [None, "PINECONE DINER", None, "LIBRARY", "POST OFFICE", None, "HARDWARE", None]
        cols = ["#5a3d6e", "#8a3b45", "#3d5a7a", "#6b4e3a", "#2f5a5a", "#7a5a3a", "#4a3d6e", "#6e3d4a"]
        clock_x = 1700
        i = 0
        while xs < W - 100:
            w = rnd.choice((230, 260, 300))
            if abs(xs + w / 2 - clock_x) < 200:
                xs = clock_x + 190
                continue
            h = rnd.choice((230, 270, 310))
            building(c, xs, G - 30, w, h, cols[i % len(cols)], "#2a2440", kind=rnd.choice(("flat", "false_front", "gable")),
                     lit=0.75, seed=i, sign=names[i % len(names)], sign_col=["#ff6b9a", "#7cf2ff", "#ffd36b"][i % 3],
                     awning="#c0392b" if i % 3 == 1 else ("#2f8f5b" if i % 3 == 2 else None))
            xs += w + rnd.choice((20, 34, 50))
            i += 1
        # часовая башня
        cx = clock_x
        c.drawRect(skia.Rect(cx - 90, G - 470, cx + 90, G - 30), paint(None, shader=lin_grad((cx - 90, 0), (cx + 90, 0),
                                                                                              ["#6b5a7a", "#3d3050"])))
        c.drawPath(poly([(cx - 110, G - 470), (cx, G - 600), (cx + 110, G - 470)]), paint("#2a2440"))
        c.drawRect(skia.Rect(cx - 100, G - 476, cx + 100, G - 464), paint("#e8d9c0"))
        glow(c, cx, G - 380, 160, "#ffe9b8", 0.35)
        c.drawCircle(cx, G - 380, 62, paint("#fff3d6"))
        c.drawCircle(cx, G - 380, 62, paint("#3d3050", stroke=7))
        for k in range(12):
            a = k / 12 * math.tau
            c.drawCircle(cx + math.sin(a) * 50, G - 380 - math.cos(a) * 50, 3.2, paint("#3d3050"))
        # 11:53 — часы отстают на 7 минут
        line(c, [(cx, G - 380), (cx + math.sin(-0.12) * 34, G - 380 - math.cos(-0.12) * 34)], 6, "#2a1f2e", smooth=False)
        line(c, [(cx, G - 380), (cx + math.sin(math.tau * 53 / 60) * 50, G - 380 - math.cos(math.tau * 53 / 60) * 50)], 4,
             "#2a1f2e", smooth=False)
        c.drawRect(skia.Rect(cx - 36, G - 150, cx + 36, G - 30), paint("#2a1f2e"))
        # тротуар и брусчатка
        c.drawRect(skia.Rect(0, G - 30, W, G + 10), paint("#3a3a5a"))
        c.drawRect(skia.Rect(0, G + 4, W, G + 12), paint("#5a5a7a"))
        c.drawRect(skia.Rect(0, G + 10, W, Y1), paint(None, shader=lin_grad((0, G + 10), (0, Y1), ["#20264a", "#0e1230"])))
        rnd = random.Random(9)
        for row in range(10):
            yy = G + 22 + row * (14 + row * 3)
            for k in range(60):
                xx = k * 62 + (row % 2) * 31 + rnd.uniform(-4, 4)
                c.drawOval(skia.Rect(xx, yy, xx + 50 + row * 4, yy + 8 + row * 2), paint("#2c335e", 0.6))
        for lx in range(260, W, 560):
            lamp_post(c, lx, G + 6)
            # отражения на мокрой мостовой
            glow(c, lx, G + 120, 90, "#ffcf70", 0.18)
            c.drawRect(skia.Rect(lx - 8, G + 20, lx + 8, G + 200), paint(None, shader=lin_grad((0, G + 20), (0, G + 200),
                       [hexc("#ffcf70", 0.35), hexc("#ffcf70", 0)])))
    L.layer(1.0, street)
    S.layers = [(d, im) for d, im, f in L.out if not f]
    S.lamps = [Lamp(lx, G + 6 - 265, 230, "#ffc56b", 0.55, 0.04) for lx in range(260, W, 560)]
    S.lamps.append(Lamp(1700, G - 380, 140, "#ffe9b8", 0.2, 0.0))
    S.overlay = [("vignette", 0.55), ("top", "#0a1440", 0.35)]
    return S


def maple_row(light="night") -> SetDef:
    W = 2800
    G = 930
    night = light == "night"
    if night:
        Lt = NIGHT_L
        S = SetDef("maple_row", W, G, 3.2, Lt, tint=(0.7, 0.78, 1.0), tint_add=(0, 0.01, 0.05), particles="fireflies",
                   shadow_color="#050a1e", shadow_alpha=0.45)
    else:
        Lt = Light(key=(-0.6, -0.8), rim="#fff0c8", rim_dir=(0.8, -0.5), rim_alpha=0.45, outline="#2a1a24")
        S = SetDef("maple_row", W, G, 3.2, Lt, tint=(1.02, 0.98, 0.95), particles="leaves", shadow_color="#3a2a40",
                   shadow_alpha=0.28)
    L = Layers(W)

    def far(c):
        if night:
            sky(c, W, ["#060b24", "#10225a", "#25478f", "#3b64b0"], [0, 0.4, 0.8, 1])
            stars(c, W, 200, seed=5)
            moon(c, W * 0.2, 170, 50)
        else:
            sky(c, W, ["#6fb4ff", "#9fd0ff", "#ffe2b8", "#ffc98f"], [0, 0.45, 0.85, 1])
            glow(c, W * 0.15, 140, 420, "#fff1c8", 0.6)
            cloud(c, 600, 220, 520, "#ffffff", 0.75)
            cloud(c, 1900, 160, 700, "#fff6ea", 0.7)
        ridge(c, W, 640, 230, "#1a2c63" if night else "#7d9fd1", 31, top_color="#2a4380" if night else "#a8c2ea",
              snow=True)
        pine_row(c, W, 700, 90, 170, "#0f1c48" if night else "#3f6f6a", "#1a2c63" if night else "#5b8f7d", 41,
                 gap=(30, 70))
    L.layer(0.25, far)

    def street(c):
        # дом Брамблов
        hx, hw, hh = 600, 760, 330
        wall = "#4f6f9a" if not night else "#2c3f6a"
        c.drawRect(skia.Rect(hx, G - hh - 40, hx + hw, G - 40), paint(None, shader=lin_grad((hx, 0), (hx + hw, 0),
                                                                                             [wall, shade_of(wall, -0.2)])))
        for yy in range(int(G - hh - 40) + 16, int(G - 40), 16):
            c.drawRect(skia.Rect(hx, yy, hx + hw, yy + 2), paint(shade_of(wall, -0.2), 0.6))
        roof = "#5a2f3a" if not night else "#2a1a2e"
        c.drawPath(poly([(hx - 40, G - hh - 30), (hx + hw * 0.5, G - hh - 230), (hx + hw + 40, G - hh - 30)]), paint(roof))
        c.drawPath(poly([(hx - 40, G - hh - 30), (hx + hw * 0.5, G - hh - 230), (hx + hw * 0.5, G - hh - 214),
                         (hx - 18, G - hh - 24)]), paint(shade_of(roof, 0.15)))
        window(c, hx + hw * 0.5 - 30, G - hh - 150, 60, 64, lit=night, warm="#ffd27a", dark="#a8c8f0")
        # крыльцо
        c.drawRect(skia.Rect(hx + 60, G - 200, hx + hw - 60, G - 186), paint("#e8e0d0"))
        for px in range(int(hx + 70), int(hx + hw - 60), 120):
            c.drawRect(skia.Rect(px, G - 186, px + 12, G - 40), paint("#e8e0d0"))
        c.drawRect(skia.Rect(hx + 40, G - 44, hx + hw - 40, G - 30), paint("#8a7a6a"))
        for k in range(3):
            c.drawRect(skia.Rect(hx + 280 - k * 10, G - 30 + k * 10, hx + 420 + k * 10, G - 20 + k * 10), paint("#a89888"))
        # дверь
        c.drawRect(skia.Rect(hx + 300, G - 170, hx + 400, G - 44), paint("#8e2f3a"))
        c.drawRect(skia.Rect(hx + 310, G - 160, hx + 390, G - 110), paint("#ffd27a" if night else "#f0e0b0", 0.9))
        c.drawCircle(hx + 386, G - 100, 5, paint("#e8c14e"))
        # собачья дверца
        c.drawRect(skia.Rect(hx + 315, G - 80, hx + 355, G - 46), paint("#5a1f28"))
        for wx in (hx + 110, hx + 520):
            window(c, wx, G - 160, 120, 90, lit=night, warm="#ffd27a", curtain="#c0392b", dark="#a8c8f0")
        # соседний дом
        building(c, 1650, G - 30, 420, 280, "#6b5a4a" if not night else "#3a2f3a", "#3a2a3a", kind="gable", lit=0.3 if night else 0,
                 seed=3, warm="#ffd27a")
        building(c, 2250, G - 30, 380, 250, "#7a8a5a" if not night else "#2f3a3a", "#3a2a3a", kind="gable", lit=0.4 if night else 0,
                 seed=8, warm="#ffd27a")
        # клёны
        rnd = random.Random(4)
        for mx in (180, 1480, 2620):
            c.drawRect(skia.Rect(mx - 14, G - 260, mx + 14, G - 20), paint("#4a3020" if not night else "#2a1a1a"))
            for k in range(26):
                a = rnd.uniform(0, math.tau)
                d = rnd.uniform(0, 120)
                col = rnd.choice(["#e8743b", "#d9482e", "#f2a33a", "#c0392b"]) if not night else \
                    rnd.choice(["#7a3a4a", "#6a2a3a", "#8a4a3a"])
                c.drawCircle(mx + math.cos(a) * d * 1.2, G - 330 + math.sin(a) * d * 0.7, rnd.uniform(40, 70), paint(col))
        # тротуар, газон, дорога
        c.drawRect(skia.Rect(0, G - 34, W, G + 4), paint("#4f8a4a" if not night else "#1f3a3a"))
        c.drawRect(skia.Rect(0, G, W, G + 40), paint("#c8c0b0" if not night else "#4a4a6a"))
        for k in range(0, W, 90):
            c.drawRect(skia.Rect(k, G, k + 2, G + 40), paint("#9a9080" if not night else "#3a3a5a"))
        c.drawRect(skia.Rect(0, G + 40, W, Y1), paint("#5a5a6a" if not night else "#1e2244"))
        # штакетник
        for k in range(0, W, 26):
            if 820 < k < 1260:
                continue
            c.drawPath(poly([(k, G - 30), (k + 14, G - 30), (k + 14, G - 92), (k + 7, G - 100), (k, G - 92)]),
                       paint("#f0ece4" if not night else "#8a90b0"))
        c.drawRect(skia.Rect(0, G - 80, 820, G - 72), paint("#e0dcd4" if not night else "#7a80a0"))
        c.drawRect(skia.Rect(1260, G - 80, W, G - 72), paint("#e0dcd4" if not night else "#7a80a0"))
        # почтовый ящик
        mx = 1290
        c.drawRect(skia.Rect(mx - 6, G - 150, mx + 6, G - 30), paint("#5a3a2a"))
        mb = rrect(mx - 44, G - 196, 88, 50, 22)
        c.drawPath(mb, paint("#3d6fb0" if not night else "#2a4a80"))
        c.drawPath(mb, paint("#1a1430", stroke=3))
        text(c, "BRAMBLE", mx, G - 164, font("round", 15), "#ffffff", align="center")
        c.drawRect(skia.Rect(mx + 40, G - 220, mx + 46, G - 180), paint("#d0302c"))
        c.drawRect(skia.Rect(mx + 40, G - 220, mx + 64, G - 208), paint("#d0302c"))
        if night:
            for wx in (hx + 170, hx + 580):
                glow(c, wx, G - 115, 120, "#ffb860", 0.18, blend=skia.BlendMode.kScreen)
    L.layer(1.0, street)

    def front(c):
        rnd = random.Random(12)
        for k in range(14):
            x = rnd.uniform(0, W)
            col = rnd.choice(["#e8743b", "#d9482e", "#f2a33a"]) if not night else "#5a3a4a"
            yy = G + 60 + rnd.uniform(0, 80)
            c.drawOval(skia.Rect(x, yy, x + 14, yy + 6), paint(col, 0.9))
    L.layer(1.0, front)
    S.layers = [(d, im) for d, im, f in L.out]
    S.data = {"mailbox": (1290, G - 170), "door": (950, G - 100), "dogdoor": (935, G - 60)}
    if night:
        S.lamps = [Lamp(1770, G - 200, 200, "#ffb860", 0.25, 0.02), Lamp(W * 0.2, 170, 300, "#6f9cff", 0.15, 0)]
        S.overlay = [("vignette", 0.6), ("top", "#0a1440", 0.3)]
    else:
        S.lamps = []
        S.overlay = [("vignette", 0.25), ("sun", "#fff0c0", 0.12)]
    return S


def garage(light="day") -> SetDef:
    W = 2200
    G = 950
    Lt = Light(key=(0.7, -0.7), rim="#9fe8ff", rim_dir=(-0.8, -0.4), rim_alpha=0.4, outline="#24182a")
    S = SetDef("garage", W, G, 3.35, Lt, tint=(1.0, 0.95, 0.9), particles="dust", shadow_color="#2a1a20", shadow_alpha=0.3)
    L = Layers(W)

    def back(c):
        c.drawRect(skia.Rect(0, Y0, W, Y1), paint(None, shader=lin_grad((0, 0), (0, G), ["#3a3050", "#5a4a6a", "#6a5a70"])))
        # доски
        for x in range(0, W, 110):
            c.drawRect(skia.Rect(x, Y0, x + 4, G), paint("#2a2238", 0.6))
        # открытые ворота гаража со светом
        gx = 1500
        c.drawRect(skia.Rect(gx, 150, gx + 640, G), paint(None, shader=lin_grad((0, 150), (0, G), ["#ffe7b0", "#ffd38a", "#f0a860"])))
        c.drawRect(skia.Rect(gx, 120, gx + 640, 200), paint("#8a7a9a"))
        for k in range(4):
            c.drawRect(skia.Rect(gx, 128 + k * 18, gx + 640, 132 + k * 18), paint("#6a5a7a"))
        pine_row(c, W, G - 40, 160, 300, "#4f7f6a", "#6fa08a", 2, gap=(70, 130))
        c.drawRect(skia.Rect(gx - 20, 120, gx, G), paint("#2a2238"))
        # доска с чертежами
        bx, by = 260, 230
        c.drawRect(skia.Rect(bx, by, bx + 520, by + 300), paint("#2a5a8a"))
        c.drawRect(skia.Rect(bx, by, bx + 520, by + 300), paint("#d9c8a8", stroke=10))
        for k in range(5):
            line(c, [(bx + 30, by + 40 + k * 50), (bx + 240, by + 40 + k * 50)], 2, "#bfe0ff", 0.7, smooth=False)
        c.drawCircle(bx + 380, by + 140, 70, paint("#bfe0ff", 0.8, stroke=3))
        line(c, [(bx + 380, by + 70), (bx + 380, by + 210)], 2, "#bfe0ff", 0.6, smooth=False)
        text(c, "MK. 7", bx + 300, by + 270, font("print", 34), "#ffffff", align="left")
        # пробковая доска с листовкой
        cx_, cy_ = 900, 260
        c.drawRect(skia.Rect(cx_, cy_, cx_ + 300, cy_ + 230), paint("#b8864e"))
        c.drawRect(skia.Rect(cx_, cy_, cx_ + 300, cy_ + 230), paint("#6b4226", stroke=8))
        c.drawRect(skia.Rect(cx_ + 40, cy_ + 30, cx_ + 180, cy_ + 200), paint("#fff7e0"))
        text(c, "DEMOLITION", cx_ + 110, cy_ + 70, font("logo", 18), "#c0392b", align="center")
        for k in range(5):
            line(c, [(cx_ + 55, cy_ + 95 + k * 18), (cx_ + 165, cy_ + 95 + k * 18)], 2.4, "#8a8070", 0.8, smooth=False)
        c.drawCircle(cx_ + 110, cy_ + 36, 6, paint("#d0302c"))
        c.drawRect(skia.Rect(cx_ + 200, cy_ + 50, cx_ + 280, cy_ + 130), paint("#ffe066"))
        c.drawRect(skia.Rect(cx_ + 190, cy_ + 140, cx_ + 270, cy_ + 210), paint("#9fe8ff"))
        # табличка
        c.drawRect(skia.Rect(1250, 330, 1440, 400), paint("#f2b233"))
        text(c, "KNOCK", 1345, 362, font("logo", 26), "#2a1f2e", align="center")
        text(c, "(NOT TOO HARD)", 1345, 390, font("print", 20), "#2a1f2e", align="center")
        # полки с банками
        for sy in (600, 470):
            c.drawRect(skia.Rect(1220, sy, 1470, sy + 10), paint("#6b4226"))
            rnd = random.Random(sy)
            for k in range(6):
                jx = 1235 + k * 40
                col = rnd.choice(["#9fe8ff", "#ffd36b", "#a8e06b", "#ff9ab0"])
                c.drawPath(rrect(jx, sy - 44, 30, 44, 6), paint(col, 0.8))
                c.drawRect(skia.Rect(jx + 2, sy - 50, jx + 28, sy - 42), paint("#8a8a9a"))
        # гирлянда
        for k in range(30):
            x = 60 + k * 48
            y = 90 + math.sin(k * 0.5) * 18 + (k % 2) * 6
            c.drawCircle(x, y, 6, paint(["#ffd36b", "#9fe8ff", "#ff9ab0", "#a8e06b"][k % 4]))
            glow(c, x, y, 30, ["#ffd36b", "#9fe8ff", "#ff9ab0", "#a8e06b"][k % 4], 0.4)
        line(c, [(40, 80), (720, 110), (1480, 80)], 2, "#2a2238", 0.8)
        # верстак
        c.drawRect(skia.Rect(140, 640, 1200, 670), paint("#8a5a34"))
        c.drawRect(skia.Rect(160, 670, 190, G), paint("#6b4226"))
        c.drawRect(skia.Rect(1150, 670, 1180, G), paint("#6b4226"))
        # инструменты на верстаке
        c.drawRect(skia.Rect(300, 600, 380, 640), paint("#c0392b"))
        c.drawCircle(500, 615, 26, paint("#9aa3b5"))
        c.drawCircle(500, 615, 12, paint("#5a6070"))
        c.drawRect(skia.Rect(640, 580, 700, 640), paint("#3d6fb0"))
        line(c, [(800, 640), (860, 560)], 6, "#9aa3b5", smooth=False)
        c.drawRect(skia.Rect(900, 610, 1100, 640), paint("#2f8f5b"))
        # пол
        c.drawRect(skia.Rect(0, G - 10, W, Y1), paint(None, shader=lin_grad((0, G), (0, Y1), ["#7a6a7a", "#4a3e52"])))
        c.drawRect(skia.Rect(1500, G - 10, 2140, Y1), paint("#ffd38a", 0.25))
        line(c, [(0, G - 8), (W, G - 8)], 3, "#2a2238", 0.6, smooth=False)
    L.layer(1.0, back)
    S.layers = [(d, im) for d, im, f in L.out]
    S.lamps = [Lamp(1820, 500, 700, "#ffcf8a", 0.35, 0.0), Lamp(700, 100, 500, "#ffd36b", 0.12, 0.05)]
    S.overlay = [("vignette", 0.35), ("sun", "#ffd9a0", 0.12)]
    S.data = {"flyer": (1050, 375)}
    return S


def forest(light="dusk") -> SetDef:
    W = 3600
    G = 930
    Lt = Light(key=(0.75, -0.6), rim="#ff9a5a", rim_dir=(0.85, -0.3), rim_alpha=0.6, outline="#1a1430")
    S = SetDef("forest", W, G, 3.0, Lt, tint=(0.9, 0.82, 0.95), tint_add=(0.03, 0.0, 0.04), particles="fireflies",
               shadow_color="#140a24", shadow_alpha=0.4)
    L = Layers(W)

    def far(c):
        sky(c, W, ["#1a1a5a", "#4a3a8a", "#c0607a", "#ffb070"], [0, 0.4, 0.75, 1])
        stars(c, W, 90, seed=8, ymax=300, alpha=0.6)
        glow(c, W * 0.8, 560, 700, "#ffb070", 0.35)
        ridge(c, W, 650, 230, "#3a2a6a", 51, top_color="#5a3a7a", snow=True)
    L.layer(0.15, far)

    def mid(c):
        fog(c, W, 660, 70, "#c07090", 0.35)
        pine_row(c, W, 760, 260, 420, "#2a1f4a", "#3a2a5a", 61, gap=(50, 100), rim="#ff9a5a", rim_alpha=0.3)
        fog(c, W, 760, 60, "#8a5a9a", 0.4)
    L.layer(0.45, mid)

    def near(c):
        pine_row(c, W, G + 10, 520, 760, "#160f30", "#22183f", 71, gap=(170, 320), rim="#ff9a5a", rim_alpha=0.45,
                 trunk="#140c20")
        c.drawRect(skia.Rect(0, G - 20, W, Y1), paint(None, shader=lin_grad((0, G - 20), (0, Y1), ["#3a2a4a", "#1a1028"])))
        # тропинка
        c.drawPath(poly([(0, G + 10), (W, G - 6), (W, G + 50), (0, G + 70)]), paint("#6a4a5a", 0.8))
        grass_tufts(c, W, G - 12, "#2a3a4a", 3, n=260)
    L.layer(1.0, near)

    def front(c):
        rnd = random.Random(77)
        x = 200
        while x < W:
            pine(c, x, Y1 + 40, rnd.uniform(800, 1100), "#07040f", "#0c0818", lean=rnd.uniform(-10, 10))
            x += rnd.uniform(1500, 2100)
    L.layer(1.35, front, front=True)
    S.layers = [(d, im) for d, im, f in L.out if not f]
    S.front = [(d, im) for d, im, f in L.out if f]
    S.lamps = [Lamp(W * 0.8, 560, 600, "#ffb070", 0.2, 0.0, depth=0.15)]
    S.overlay = [("vignette", 0.6), ("top", "#1a1050", 0.25)]
    S.data = {"flicker": True}
    return S


def mill_exterior(light="dusk") -> SetDef:
    W = 3200
    G = 930
    Lt = Light(key=(0.6, -0.7), rim="#ffb070", rim_dir=(0.8, -0.4), rim_alpha=0.55, outline="#1a1430")
    S = SetDef("mill_exterior", W, G, 2.75, Lt, tint=(0.82, 0.8, 0.98), tint_add=(0.02, 0.0, 0.05), particles="fireflies_pixels",
               shadow_color="#0e0a24", shadow_alpha=0.45)
    L = Layers(W)

    def far(c):
        sky(c, W, ["#0e1446", "#2a2a7a", "#8a4a8a", "#ff9a6a"], [0, 0.4, 0.78, 1])
        stars(c, W, 160, seed=12, ymax=380)
        moon(c, W * 0.18, 140, 40)
        ridge(c, W, 660, 240, "#24205a", 81, top_color="#3a2a6a", snow=True)
        fog(c, W, 680, 60, "#c0709a", 0.3)
    L.layer(0.15, far)

    def mid(c):
        pine_row(c, W, 780, 220, 360, "#14123a", "#1e1a4a", 91, gap=(40, 90), rim="#ff9a6a", rim_alpha=0.25, glow_px=4)
    L.layer(0.45, mid)

    def mill(c):
        mx = 1900
        brick = "#7a3a3a"
        c.drawRect(skia.Rect(mx - 520, G - 420, mx + 520, G - 20), paint(None, shader=lin_grad((mx - 520, 0), (mx + 520, 0),
                                                                                                ["#8a4a44", "#4a2430"])))
        for yy in range(G - 410, G - 20, 22):
            off = 0 if (yy // 22) % 2 else 30
            for xx in range(mx - 520 + off, mx + 520, 60):
                c.drawRect(skia.Rect(xx, yy, xx + 2, yy + 22), paint("#3a1a24", 0.5))
            c.drawRect(skia.Rect(mx - 520, yy, mx + 520, yy + 2), paint("#3a1a24", 0.5))
        c.drawPath(poly([(mx - 560, G - 420), (mx - 400, G - 520), (mx + 400, G - 520), (mx + 560, G - 420)]), paint("#2a1a2e"))
        # высокие окна
        for k in range(7):
            wx = mx - 460 + k * 135
            lit = k in (2, 5)
            c.drawPath(rrect(wx, G - 360, 80, 200, 40), paint("#ffcf70" if lit else "#1a1f40"))
            if lit:
                glow(c, wx + 40, G - 260, 160, "#ffb050", 0.3)
            for g in range(1, 4):
                c.drawRect(skia.Rect(wx, G - 360 + g * 50, wx + 80, G - 357 + g * 50), paint("#2a1a2e"))
            c.drawRect(skia.Rect(wx + 38, G - 360, wx + 42, G - 160), paint("#2a1a2e"))
            if k in (0, 3, 6):
                for b in range(3):
                    c.drawRect(skia.Rect(wx - 6, G - 300 + b * 50, wx + 86, G - 286 + b * 50), paint("#6b4a34"))
        # башня
        tx = mx + 300
        c.drawRect(skia.Rect(tx - 90, G - 820, tx + 90, G - 420), paint(None, shader=lin_grad((tx - 90, 0), (tx + 90, 0),
                                                                                               ["#8a4a44", "#4a2430"])))
        c.drawPath(poly([(tx - 120, G - 820), (tx, G - 960), (tx + 120, G - 820)]), paint("#2a1a2e"))
        c.drawPath(rrect(tx - 40, G - 760, 80, 110, 40), paint("#ffd27a"))
        c.drawRect(skia.Rect(tx - 2, G - 760, tx + 2, G - 650), paint("#4a2a2a"))
        # труба
        c.drawRect(skia.Rect(mx - 380, G - 760, mx - 300, G - 520), paint("#5a2a30"))
        c.drawRect(skia.Rect(mx - 392, G - 770, mx - 288, G - 750), paint("#3a1a24"))
        # дверь и вывеска
        c.drawRect(skia.Rect(mx - 80, G - 200, mx + 80, G - 20), paint("#3a2418"))
        c.drawRect(skia.Rect(mx - 80, G - 200, mx + 80, G - 20), paint("#1a1020", stroke=8))
        c.drawRect(skia.Rect(mx - 300, G - 470, mx + 300, G - 430), paint("#2a1a2e"))
        text(c, "LUMEN LANTERN WORKS · 1887", mx, G - 441, font("round", 30), "#e8c14e", align="center")
        # забор и табличка
        for k in range(0, 1300, 40):
            c.drawRect(skia.Rect(k, G - 120, k + 8, G - 10), paint("#2a2238"))
        line(c, [(0, G - 110), (1300, G - 110)], 3, "#2a2238", smooth=False)
        line(c, [(0, G - 60), (1300, G - 60)], 3, "#2a2238", smooth=False)
        c.drawRect(skia.Rect(980, G - 200, 1200, G - 120), paint("#f2b233"))
        text(c, "DEMOLITION", 1090, G - 165, font("logo", 26), "#c0392b", align="center")
        text(c, "SATURDAY", 1090, G - 134, font("round", 22), "#2a1f2e", align="center")
        c.drawRect(skia.Rect(1085, G - 120, 1095, G - 10), paint("#4a3020"))
        # земля
        c.drawRect(skia.Rect(0, G - 20, W, Y1), paint(None, shader=lin_grad((0, G - 20), (0, Y1), ["#2a2a4a", "#14102a"])))
        grass_tufts(c, W, G - 18, "#3a4a5a", 5, n=300, hmax=26)
    L.layer(1.0, mill)

    def front(c):
        rnd = random.Random(3)
        for x in (140, 2950):
            pine(c, x, Y1 + 30, rnd.uniform(900, 1050), "#06040e", "#0b0818")
    L.layer(1.3, front, front=True)
    S.layers = [(d, im) for d, im, f in L.out if not f]
    S.front = [(d, im) for d, im, f in L.out if f]
    tx = 1900 + 300
    S.lamps = [Lamp(tx, G - 705, 260, "#ffc060", 0.55, 0.08, key="tower"), Lamp(1675, G - 260, 160, "#ffb050", 0.2, 0.05),
               Lamp(2080, G - 260, 160, "#ffb050", 0.2, 0.05)]
    S.overlay = [("vignette", 0.6), ("top", "#0e1446", 0.3)]
    S.data = {"tower_window": (tx, G - 705)}
    return S


def mill_interior(light="night") -> SetDef:
    W = 2400
    G = 950
    Lt = Light(key=(0.75, -0.6), rim="#7cc8ff", rim_dir=(-0.85, -0.3), rim_alpha=0.55, outline="#1a1024")
    S = SetDef("mill_interior", W, G, 3.0, Lt, tint=(0.95, 0.82, 0.78), tint_add=(0.04, 0.01, 0.0), particles="dust_pixels",
               shadow_color="#0a0614", shadow_alpha=0.5)
    L = Layers(W)
    lx, ly = 1500, G - 420

    def back(c):
        c.drawRect(skia.Rect(0, Y0, W, Y1), paint(None, shader=lin_grad((0, 0), (0, G), ["#140e24", "#2a1a30", "#3a2430"])))
        # кирпич
        for yy in range(Y0, G, 26):
            off = 0 if (yy // 26) % 2 else 36
            for xx in range(off, W, 72):
                c.drawRect(skia.Rect(xx, yy, xx + 70, yy + 24), paint("#3a2030", 0.55))
        # арочное окно с луной
        wx = 360
        c.drawPath(rrect(wx, 120, 300, 520, 150), paint(None, shader=lin_grad((0, 120), (0, 640), ["#2a4a9a", "#4a78c8"])))
        c.drawCircle(wx + 200, 260, 40, paint("#e8f0ff"))
        glow(c, wx + 200, 260, 140, "#9cc4ff", 0.4)
        for g in range(1, 5):
            c.drawRect(skia.Rect(wx, 120 + g * 104, wx + 300, 126 + g * 104), paint("#1a1024"))
        c.drawRect(skia.Rect(wx + 147, 120, wx + 153, 640), paint("#1a1024"))
        # лунный луч
        beam = poly([(wx, 140), (wx + 300, 140), (wx + 900, G), (wx + 200, G)])
        c.drawPath(beam, paint(None, shader=lin_grad((wx, 140), (wx + 500, G), [hexc("#7cb0ff", 0.22), hexc("#7cb0ff", 0.0)]),
                               blend=skia.BlendMode.kScreen))
        # шестерни-силуэты
        for gx, gy, gr in ((2050, 300, 140), (2230, 470, 90), (180, 760, 110)):
            c.drawCircle(gx, gy, gr, paint("#1e1424"))
            for k in range(12):
                a = k / 12 * math.tau
                c.drawRect(skia.Rect(gx + math.cos(a) * gr - 14, gy + math.sin(a) * gr - 14, gx + math.cos(a) * gr + 14,
                                     gy + math.sin(a) * gr + 14), paint("#1e1424"))
            c.drawCircle(gx, gy, gr * 0.35, paint("#2a1a30"))
        # лестница-зигзаг к постаменту
        for k in range(9):
            sx = 1000 + k * 46
            sy = G - 20 - k * 40
            c.drawRect(skia.Rect(sx, sy, sx + 70, sy + 14), paint("#6b4a34"))
            c.drawRect(skia.Rect(sx, sy + 14, sx + 70, sy + 18), paint("#3a2418"))
        c.drawRect(skia.Rect(1360, G - 380, 1700, G - 360), paint("#6b4a34"))
        for px in (1370, 1680):
            c.drawRect(skia.Rect(px, G - 360, px + 16, G), paint("#4a3020"))
        # постамент
        c.drawRect(skia.Rect(lx - 70, G - 400, lx + 70, G - 380), paint("#8a6a44"))
        c.drawRect(skia.Rect(lx - 50, G - 418, lx + 50, G - 400), paint("#a8844e"))
        # табличка
        c.drawRect(skia.Rect(lx - 46, G - 375, lx + 46, G - 350), paint("#c9a45a"))
        # пол
        c.drawRect(skia.Rect(0, G - 10, W, Y1), paint(None, shader=lin_grad((0, G), (0, Y1), ["#4a3040", "#1a1020"])))
        for k in range(0, W, 120):
            line(c, [(k, G - 8), (k - 60, Y1)], 2, "#2a1a24", 0.6, smooth=False)
    L.layer(1.0, back)
    S.layers = [(d, im) for d, im, f in L.out]
    S.lamps = [Lamp(lx, ly, 520, "#ffc060", 0.6, 0.06, key="lantern")]
    S.overlay = [("vignette", 0.65)]
    S.data = {"lantern": (lx, ly), "stairs": (1000, G - 20)}
    return S


def lookout(light="sunset") -> SetDef:
    W = 2800
    G = 900
    night = light == "night"
    Lt = Light(key=(0.8, -0.5), rim="#ffb070" if not night else "#7cc8ff", rim_dir=(0.85, -0.3), rim_alpha=0.6,
               outline="#1a1430")
    S = SetDef("lookout", W, G, 3.1, Lt, tint=(1.0, 0.86, 0.85) if not night else (0.72, 0.8, 1.0),
               tint_add=(0.04, 0.0, 0.02), particles="fireflies", shadow_color="#140a24", shadow_alpha=0.35)
    L = Layers(W)

    def far(c):
        if night:
            sky(c, W, ["#050a22", "#0d1c4f", "#1d3c86", "#2f5aa8"], [0, 0.4, 0.8, 1])
            stars(c, W, 300, seed=21)
            moon(c, W * 0.78, 150, 62)
        else:
            sky(c, W, ["#2a2a7a", "#8a4a9a", "#ff7a6a", "#ffc070"], [0, 0.35, 0.72, 1])
            glow(c, W * 0.62, 600, 800, "#ffcf80", 0.5)
            c.drawCircle(W * 0.62, 610, 70, paint("#fff0c0"))
            cloud(c, 800, 300, 700, "#c06a9a", 0.5)
            cloud(c, 2200, 240, 800, "#e08a8a", 0.45)
        ridge(c, W, 600, 200, "#2a2a6a" if not night else "#14245a", 101, top_color="#5a3a8a" if not night else "#22397a",
              snow=True)
    L.layer(0.12, far)

    def town(c):
        ridge(c, W, 680, 90, "#3a2a6a" if not night else "#0f1c48", 111, rough=0.5, step=80)
        # озеро
        c.drawRect(skia.Rect(0, 700, W, 780), paint(None, shader=lin_grad((0, 700), (0, 780), ["#ff9a7a" if not night else "#3a5fae",
                                                                                              "#5a3a8a" if not night else "#14245a"])))
        # городок с огнями
        rnd = random.Random(31)
        for k in range(140):
            x = rnd.uniform(200, W - 200)
            y = rnd.uniform(705, 790)
            w = rnd.uniform(18, 40)
            h = rnd.uniform(14, 26)
            c.drawRect(skia.Rect(x, y - h, x + w, y), paint("#2a2050" if not night else "#141c40"))
            c.drawPath(poly([(x - 3, y - h), (x + w / 2, y - h - 10), (x + w + 3, y - h)]), paint("#1a1440"))
            if rnd.random() < 0.7:
                c.drawRect(skia.Rect(x + 5, y - h + 5, x + 10, y - h + 10), paint("#ffcf70"))
                glow(c, x + 7, y - h + 7, 16, "#ffb050", 0.6)
        # часовая башня вдали
        c.drawRect(skia.Rect(1380, 700, 1404, 760), paint("#2a2050"))
        c.drawCircle(1392, 712, 6, paint("#fff3d6"))
        # фабрика с башней и Фонарём
        c.drawRect(skia.Rect(2000, 690, 2100, 760), paint("#2a1a40"))
        c.drawRect(skia.Rect(2070, 640, 2090, 700), paint("#2a1a40"))
        c.drawCircle(2080, 655, 5, paint("#ffd27a"))
        glow(c, 2080, 655, 60, "#ffc060", 0.7)
        pine_row(c, W, 820, 70, 140, "#1a1440" if not night else "#0b1838", "#2a1f50" if not night else "#13265a", 121,
                 gap=(25, 55))
        # радиовышка
        rx = 360
        line(c, [(rx - 40, 820), (rx, 420), (rx + 40, 820)], 4, "#1a1030", smooth=False)
        for k in range(8):
            yy = 820 - k * 50
            hw = 40 - k * 5
            line(c, [(rx - hw, yy), (rx + hw - 5, yy - 50)], 2, "#1a1030", smooth=False)
        c.drawCircle(rx, 420, 6, paint("#ff4a4a"))
        glow(c, rx, 420, 30, "#ff4a4a", 0.7)
    L.layer(0.35, town)

    def hill(c):
        hp = smooth_closed([(-100, Y1), (-100, G - 40), (500, G - 70), (1200, G - 40), (2000, G - 20), (2900, G + 10), (2900, Y1)])
        c.drawPath(hp, paint(None, shader=lin_grad((0, G - 70), (0, Y1), ["#4a3a6a" if not night else "#1f2a4a",
                                                                        "#1a1030" if not night else "#0a0e20"])))
        grass_tufts(c, W, G - 40, "#6a4a7a" if not night else "#2a3a5a", 13, n=300, hmax=30)
        # скамейка
        c.drawRect(skia.Rect(1500, G - 120, 1700, G - 108), paint("#6b4a34"))
        c.drawRect(skia.Rect(1500, G - 90, 1700, G - 80), paint("#6b4a34"))
        for px in (1515, 1675):
            c.drawRect(skia.Rect(px, G - 120, px + 10, G - 20), paint("#4a3020"))
    L.layer(1.0, hill)

    def front(c):
        pine(c, 2700, Y1 + 30, 1000, "#0c0818", "#140c24")
        pine(c, -60, Y1 + 40, 900, "#0c0818", "#140c24")
    L.layer(1.3, front, front=True)
    S.layers = [(d, im) for d, im, f in L.out if not f]
    S.front = [(d, im) for d, im, f in L.out if f]
    S.lamps = [] if night else [Lamp(W * 0.62, 600, 700, "#ffcf80", 0.25, 0.0, depth=0.12)]
    S.overlay = [("vignette", 0.5)]
    return S


def end_card(light="night") -> SetDef:
    S = lookout("night")
    S.name = "end_card"
    return S
