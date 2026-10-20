"""Риги персонажей Pixel Pines (см. docs/character_bible.md).

Система координат персонажа: начало — между ступнями, ось y вниз, рост Тео = 100
единиц. Перед вызовом холст уже переведён в эти единицы и отражён по facing.
Каждый draw_* возвращает «якоря» (рука, голова) в координатах персонажа.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import skia

from .draw import (Light, blob, diff, ellipse, flat, glow, inter, line, moved, noodle, paint, poly, rrect,
                   shade, smooth_closed, smooth_open, union)
from .util import clamp, hexc, lerp, mix, shade_of

# ------------------------------------------------------------------ выражения
EXPR = {
    #            eye  liftL liftR tilt smile open round pupil
    "neutral":   (1.00, 0.0, 0.0, 0, 0.30, 0.00, 0.0, 1.00),
    "happy":     (0.92, 1.0, 1.0, -2, 1.00, 0.10, 0.0, 1.00),
    "grin":      (0.85, 1.2, 1.2, -2, 1.00, 0.40, 0.0, 1.00),
    "excited":   (1.15, 2.6, 2.6, -2, 1.00, 0.70, 0.1, 1.05),
    "surprised": (1.25, 3.6, 3.6, 2, 0.00, 0.75, 0.85, 0.80),
    "awe":       (1.18, 2.4, 2.4, 4, 0.40, 0.30, 0.7, 1.20),
    "worried":   (1.05, 2.0, 2.0, 20, -0.70, 0.10, 0.0, 0.95),
    "scared":    (1.30, 3.2, 3.2, 16, -0.80, 0.55, 0.3, 0.70),
    "determined": (0.86, -1.2, -1.2, -18, 0.25, 0.00, 0.0, 1.00),
    "skeptical": (0.85, 2.6, -1.2, -4, 0.05, 0.00, 0.0, 1.00),
    "sly":       (0.62, 0.0, 0.0, -7, 0.75, 0.00, 0.0, 1.00),
    "thinking":  (0.80, 1.8, -0.5, 4, 0.00, 0.00, 0.0, 1.00),
    "sad":       (0.80, 0.8, 0.8, 16, -0.60, 0.00, 0.0, 1.00),
    "proud":     (0.70, 1.2, 1.2, -4, 0.85, 0.00, 0.0, 1.00),
}

# ------------------------------------------------------------------ позы рук
# (плечо°, локоть°) для ближней и дальней руки. 0 — рука вниз, 90 — вперёд, 180 — вверх.
POSES = {
    "idle":      ((8, 12), (-6, 10)),
    "talk":      ((32, 58), (6, 14)),
    "talk2":     ((22, 82), (22, 62)),
    "point":     ((96, 2), (6, 12)),
    "point_up":  ((150, 10), (6, 12)),
    "wave":      ((148, 32), (6, 12)),
    "arms_up":   ((158, 12), (150, 14)),
    "cheer":     ((168, -18), (164, 20)),
    "hips":      ((38, -118), (-36, 118)),
    "think":     ((28, 142), (14, 92)),
    "hold":      ((34, 78), (30, 80)),
    "shrug":     ((48, 96), (-44, -90)),
    "flashlight": ((78, 14), (8, 12)),
    "camera":    ((42, 100), (34, 104)),
    "write":     ((40, 66), (36, 80)),
    "hug":       ((40, 122), (36, 122)),
    "reach":     ((110, 8), (70, 20)),
    "fist":      ((50, 120), (6, 12)),
}


@dataclass
class State:
    x: float = 0.0              # мировые координаты (px) — используются сценой
    y: float = 0.0
    facing: int = 1
    scale: float = 1.0
    expr: str = "neutral"
    expr_from: str = "neutral"
    expr_t: float = 1.0         # 0..1 переход между выражениями
    pose: str = "idle"
    pose_from: str = "idle"
    pose_t: float = 1.0
    walk: float = 0.0           # фаза шага, рад
    walking: float = 0.0        # 0..1 — насколько идёт
    run: bool = False
    bob: float = 0.0
    lean: float = 0.0
    tilt: float = 0.0
    look: tuple = (0.0, 0.0)
    blink: float = 0.0          # 0 открыт .. 1 закрыт
    talk: tuple | None = None   # (open, wide, round) с липсинка
    amp: float = 0.0            # громкость реплики 0..1
    t: float = 0.0              # время для вторичной анимации
    prop: str | None = None
    jump: float = 0.0
    squash: float = 0.0
    visible: bool = True
    alpha: float = 1.0
    sit: float = 0.0            # для собаки
    wag: float = 0.0
    extra_spin: bool = False


def _expr(st: State):
    a = EXPR.get(st.expr_from, EXPR["neutral"])
    b = EXPR.get(st.expr, EXPR["neutral"])
    k = st.expr_t
    return tuple(lerp(x, y, k) for x, y in zip(a, b))


def _pose(st: State):
    a = POSES.get(st.pose_from, POSES["idle"])
    b = POSES.get(st.pose, POSES["idle"])
    k = st.pose_t
    return tuple(tuple(lerp(p, q, k) for p, q in zip(pa, pb)) for pa, pb in zip(a, b))


def _limb(base, l1, l2, a1, a2):
    r1 = math.radians(a1)
    e = (base[0] + l1 * math.sin(r1), base[1] + l1 * math.cos(r1))
    r2 = math.radians(a1 + a2)
    h = (e[0] + l2 * math.sin(r2), e[1] + l2 * math.cos(r2))
    return e, h


def _leg_ik(hip, foot, l1, l2, bend=1):
    dx, dy = foot[0] - hip[0], foot[1] - hip[1]
    d = max(1e-3, min(math.hypot(dx, dy), l1 + l2 - 1e-3))
    a = math.atan2(dy, dx)
    cosb = clamp((l1 * l1 + d * d - l2 * l2) / (2 * l1 * d), -1, 1)
    b = math.acos(cosb)
    ang = a - b * bend
    return (hip[0] + l1 * math.cos(ang), hip[1] + l1 * math.sin(ang))


# ================================================================== дети
@dataclass
class KidSpec:
    name: str
    skin: str
    hair: str
    eyes: str
    top: str               # основной цвет верхней одежды
    legs: str
    shoes: str
    sleeve: str
    height: float = 1.0
    head_r: float = 23.5
    blush: str = "#ff7d7d"
    freckles: int = 0
    girl: bool = False
    extra: dict = field(default_factory=dict)


THEO = KidSpec("theo", skin="#f2c6a0", hair="#7a4a2a", eyes="#5a3a22", top="#f2b233", legs="#3e5c9a",
               shoes="#e2483d", sleeve="#f2b233", height=1.0, freckles=5)
JUNE = KidSpec("june", skin="#8a5434", hair="#3b2418", eyes="#3a2216", top="#7d4cdb", legs="#ff8a3d",
               shoes="#6b4226", sleeve="#7d4cdb", height=1.04, girl=True, blush="#ff6f6f")
DOT = KidSpec("dot", skin="#d9a27a", hair="#3a2418", eyes="#4a2c1a", top="#f4f1ea", legs="#8bc34a",
              shoes="#5b4a8a", sleeve="#f4f1ea", height=0.92, head_r=24.5, freckles=11, girl=True)


def _head_path(r):
    pts = [(0, -r * 1.0), (r * 0.78, -r * 0.8), (r * 1.02, -r * 0.1), (r * 0.9, r * 0.5), (r * 0.45, r * 0.9),
           (0, r * 0.98), (-r * 0.45, r * 0.9), (-r * 0.9, r * 0.5), (-r * 1.02, -r * 0.1), (-r * 0.78, -r * 0.8)]
    return smooth_closed(pts)


def _eye(c, cx, cy, rx, ry, sp: KidSpec, ex, st: State, L: Light, far: bool):
    eo, _, _, _, _, _, _, pupil = ex
    open_ = clamp(eo * (1 - st.blink), 0, 1.35)
    ry_e = ry * (0.55 + 0.45 * min(open_, 1.3))
    white = ellipse(cx, cy, rx, ry_e)
    c.drawPath(white, paint("#fdfbf7"))
    c.save()
    c.clipPath(white, doAntiAlias=True)
    lx, ly = st.look
    ir = rx * 0.84
    ix, iy = cx + lx * rx * 0.38, cy + ly * ry * 0.3 + ry * 0.08
    c.drawCircle(ix, iy, ir, paint(sp.eyes))
    c.drawCircle(ix, iy + ir * 0.35, ir * 0.8, paint(shade_of(sp.eyes, 0.25), 0.5))
    c.drawCircle(ix, iy, ir * 0.5 * pupil, paint("#120a10"))
    c.drawCircle(ix - ir * 0.38, iy - ir * 0.42, ir * 0.36, paint("#ffffff"))
    c.drawCircle(ix + ir * 0.35, iy + ir * 0.35, ir * 0.16, paint("#ffffff", 0.9))
    # верхнее веко: тень и моргание
    c.drawPath(ellipse(cx, cy - ry_e * 1.05, rx * 1.3, ry_e * 0.45), paint("#c9c2d8", 0.35))
    if open_ < 1.0:
        lid_y = cy - ry_e + 2 * ry_e * (1 - open_)
        c.drawRect(skia.Rect(cx - rx - 1, cy - ry_e - 2, cx + rx + 1, lid_y), paint(sp.skin))
    c.restore()
    c.drawPath(white, paint(L.outline, stroke=L.line * 0.8))
    # ресницы / линия века — дуга по верхнему краю глаза
    top = skia.Path()
    if open_ >= 1.0:
        top.addArc(skia.Rect(cx - rx, cy - ry_e, cx + rx, cy + ry_e), 195, 150)
    else:
        lid_y = cy - ry_e + 2 * ry_e * (1 - open_)
        top = smooth_open([(cx - rx * 1.02, lid_y + 0.4), (cx, lid_y - 0.4), (cx + rx * 1.02, lid_y + 0.4)])
    c.drawPath(top, paint(L.outline, stroke=L.line * (1.9 if sp.girl else 1.45)))
    if sp.girl and open_ > 0.3:
        side = 1 if far else -1
        ex_ = cx + rx * 0.92 * side
        ey_ = cy - ry_e * 0.45
        line(c, [(ex_, ey_), (ex_ + 1.5 * side, ey_ - 1.3)], L.line * 1.3, L.outline)


def _mouth(c, mx, my, sp: KidSpec, ex, st: State, L: Light, gap_tooth=False):
    _, _, _, _, smile, open_b, round_b, _ = ex
    o, w, r = open_b, 1.0, round_b
    if st.talk is not None:
        to, tw, tr = st.talk
        o = max(o * 0.4, to)
        w, r = tw, max(r * 0.5, tr)
        smile *= 0.6
    hw = 4.2 * w * (1 - 0.42 * r) + 0.9 * max(smile, 0)
    lift = smile * 1.6
    if o < 0.07:
        p = smooth_open([(mx - hw, my - lift), (mx, my + smile * 1.4), (mx + hw, my - lift)])
        c.drawPath(p, paint(L.outline, stroke=L.line * 1.25))
        return
    top_y = my - o * 1.2 - (0.6 if smile > 0.5 else 0)
    bot_y = my + o * 6.4 + max(smile, 0) * 1.2
    p = skia.Path()
    p.moveTo(mx - hw, my - lift)
    p.cubicTo(mx - hw * 0.5, top_y, mx + hw * 0.5, top_y, mx + hw, my - lift)
    p.cubicTo(mx + hw * 0.9, bot_y, mx - hw * 0.9, bot_y, mx - hw, my - lift)
    p.close()
    c.drawPath(p, paint("#5b1a2a"))
    c.save()
    c.clipPath(p, doAntiAlias=True)
    c.drawPath(ellipse(mx + 0.5, bot_y - 0.5, hw * 0.75, o * 3.0 + 0.6), paint("#e8737f"))
    if o > 0.22 and r < 0.7:
        c.drawRect(skia.Rect(mx - hw, top_y - 3, mx + hw, top_y + 1.9), paint("#ffffff"))
        if gap_tooth:
            c.drawRect(skia.Rect(mx + 0.2, top_y - 3, mx + 0.9, top_y + 1.9), paint("#5b1a2a"))
    c.restore()
    c.drawPath(p, paint(L.outline, stroke=L.line * 1.05))


def _brow(c, cx, cy, lift, tilt, side, width, color, L):
    """side=-1 — левая бровь (внутренний край справа). tilt>0 — внутренний край вверх (тревога)."""
    k = tilt * 0.13
    inner = (cx - side * 4.3, cy - lift - k)
    outer = (cx + side * 4.6, cy - lift + k * 0.6)
    mid = (cx + side * 0.3, cy - lift - 1.3 - k * 0.2)
    p = smooth_open([inner, mid, outer])
    c.drawPath(p, paint(color, stroke=width))


def draw_kid(c: skia.Canvas, sp: KidSpec, st: State, L: Light):
    ex = _expr(st)
    (na1, na2), (fa1, fa2) = _pose(st)
    t = st.t
    r = sp.head_r
    s = sp.height
    c.save()
    c.scale(s, s)
    # прыжок / присед
    c.translate(0, -st.jump)
    if st.squash:
        c.scale(1 + st.squash * 0.12, 1 - st.squash * 0.12)

    # --- ноги
    hip_y = -26
    walking = st.walking
    stride = (9 if st.run else 6.5) * walking
    lift = (7 if st.run else 4.5) * walking
    bob = -abs(math.sin(st.walk)) * (2.6 if st.run else 1.6) * walking + st.bob
    legs = []
    for i, side in enumerate((-1, 1)):
        ph = st.walk + (0 if side < 0 else math.pi)
        fx = side * 4.6 + stride * math.sin(ph)
        fy = -max(0.0, math.cos(ph)) * lift
        hip = (side * 4.6, hip_y + bob)
        knee = _leg_ik(hip, (fx, fy), 13.6, 13.6, bend=-1)
        legs.append((hip, knee, (fx, fy)))
    for hip, knee, foot in legs:
        noodle(c, [hip, knee, (foot[0], foot[1] - 2.5)], 7.4, sp.legs, L)
    for hip, knee, foot in legs:
        shoe = smooth_closed([(foot[0] - 4.2, foot[1] - 1), (foot[0] - 3.5, foot[1] - 5.2), (foot[0] + 2.5, foot[1] - 5.4),
                              (foot[0] + 7.5, foot[1] - 2.2), (foot[0] + 7.4, foot[1] + 0.4), (foot[0] - 4, foot[1] + 0.6)])
        shade(c, shoe, sp.shoes, L, depth=1.4)
        c.drawPath(poly([(foot[0] - 4.2, foot[1] - 0.6), (foot[0] + 7.4, foot[1] - 0.6), (foot[0] + 7.4, foot[1] + 0.5),
                         (foot[0] - 4.2, foot[1] + 0.6)]), paint("#f4f0e6"))

    # --- тело с наклоном
    c.save()
    c.translate(0, hip_y + bob)
    c.rotate(st.lean)
    c.translate(0, -(hip_y + bob))
    c.translate(0, bob)
    sh_y = -48.5
    near_sh, far_sh = (9.5, sh_y), (-10.0, sh_y)
    swing = math.sin(st.walk) * (34 if st.run else 22) * walking
    fa1_ = fa1 - swing if st.pose in ("idle", "talk") else fa1
    na1_ = na1 + swing if st.pose in ("idle", "talk") else na1
    if st.pose == "wave":
        na2 = na2 + 22 * math.sin(t * 9)
    if st.pose in ("talk", "talk2") and st.talk is not None:
        na1_ += 8 * math.sin(t * 3.1)
        na2 += 10 * math.sin(t * 2.3 + 1)
    if st.pose == "write":
        na2 += 6 * math.sin(t * 14)

    def arm(base, a1, a2, sleeve):
        e, h = _limb(base, 11.0, 10.5, a1, a2)
        noodle(c, [base, e, h], 6.6, sleeve, L)
        return h

    far_hand = arm(far_sh, fa1_, fa2, sp.sleeve)
    hand_r = 4.1
    flat(c, ellipse(*far_hand, hand_r, hand_r), shade_of(sp.skin, -0.12), L)

    _torso(c, sp, st, L)

    # --- голова
    hx, hy = 0.0, -72.0
    c.save()
    c.translate(hx, hy + 8)
    c.rotate(st.tilt + (math.sin(t * 2.2) * 2.0 if st.talk is not None else 0))
    c.translate(-hx, -(hy + 8))
    _head(c, sp, st, ex, L, hx, hy, r)
    c.restore()

    near_hand = arm(near_sh, na1_, na2, sp.sleeve)
    if st.prop:
        from .props import draw_prop
        draw_prop(c, st.prop, near_hand, st, L)
    flat(c, ellipse(*near_hand, hand_r, hand_r), sp.skin, L)
    c.drawCircle(near_hand[0] - 1.2, near_hand[1] - 1.3, 1.2, paint("#ffffff", 0.25))
    c.restore()
    c.restore()
    return {"hand": (near_hand[0] * s, (near_hand[1] + bob - st.jump) * s), "head": (0, (hy + bob - st.jump) * s),
            "far_hand": (far_hand[0] * s, far_hand[1] * s)}


def _torso(c, sp: KidSpec, st, L):
    n = sp.name
    if n == "theo":
        coat = smooth_closed([(-9, -53), (9, -53), (13.5, -47), (15.5, -32), (17.5, -17.5), (0, -16.2), (-17.5, -17.5),
                              (-15.5, -32), (-13.5, -47)], 0.8)
        shade(c, coat, sp.top, L, shadow="#c98a1e", depth=3.2)
        # капюшон-воротник
        hood = smooth_closed([(-11, -55), (0, -58), (11, -55), (9, -49), (0, -51), (-9, -49)])
        shade(c, hood, "#e3a224", L, shadow="#b67a14", depth=1.6)
        # планка и клёпки
        line(c, [(2.4, -50), (2.8, -34), (3.2, -17)], 0.9, "#b67a14")
        for yy in (-45, -37, -29):
            flat(c, rrect(3.6, yy, 3.2, 1.8, 0.8), "#7a4a2a", L, line_scale=0.5)
        # ремень фотоаппарата и сам Proof Cam
        line(c, [(-8, -51), (-1, -40), (7, -30)], 1.3, "#3a2a2a")
        cam = rrect(4.5, -32, 10.5, 7.5, 1.6)
        shade(c, cam, "#ede3c8", L, depth=1.0)
        flat(c, ellipse(10.5, -28.2, 2.6, 2.6), "#2a2830", L, line_scale=0.6)
        c.drawCircle(9.8, -29, 0.8, paint("#9fd8ff"))
        c.drawRect(skia.Rect(5.6, -31.3, 8.3, -30.0), paint("#e2483d"))
        # карман
        line(c, [(-12, -27), (-6, -26.6)], 0.8, "#b67a14")
    elif n == "june":
        jacket = smooth_closed([(-9, -53), (9, -53), (13.8, -47), (14.8, -36), (13.4, -30), (0, -29.2), (-13.4, -30),
                                (-14.8, -36), (-13.8, -47)], 0.8)
        # туловище в леггинсах до бёдер
        hips = smooth_closed([(-11, -32), (11, -32), (11.5, -25), (0, -23.5), (-11.5, -25)])
        shade(c, hips, sp.legs, L, depth=1.5)
        shade(c, jacket, sp.top, L, shadow="#5a33a8", depth=3.2)
        c.save(); c.clipPath(jacket, doAntiAlias=True)
        c.drawRect(skia.Rect(-16, -33, 16, -28), paint("#5a33a8"))
        for xx in range(-14, 16, 2):
            line(c, [(xx, -32.6), (xx, -29)], 0.35, "#432580", 0.7, smooth=False)
        c.restore()
        line(c, [(1.5, -52), (1.8, -30)], 0.8, "#c8b6ff")
        collar = smooth_closed([(-9, -54.5), (0, -56.5), (9, -54.5), (8, -50.5), (0, -52.5), (-8, -50.5)])
        shade(c, collar, "#5a33a8", L, depth=1.2)
        # нашивка рейнджера
        flat(c, ellipse(-7.5, -43, 2.8, 3.1), "#2f8f5b", L, line_scale=0.6)
        c.drawPath(poly([(-7.5, -45), (-5.9, -41.8), (-9.1, -41.8)]), paint("#e8c14e"))
        # компас
        line(c, [(-5, -53), (0, -46), (5, -53)], 0.6, "#3a2a10")
        flat(c, ellipse(0, -45, 3.0, 3.0), "#e8c14e", L, line_scale=0.7)
        c.drawCircle(0, -45, 1.9, paint("#fff3c4"))
        ang = st.t * 0.5 if not st.extra_spin else st.t * 9
        line(c, [(0, -45), (math.sin(ang) * 1.7, -45 - math.cos(ang) * 1.7)], 0.6, "#d0302c", smooth=False)
    elif n == "dot":
        coat = smooth_closed([(-9, -53), (9, -53), (14.2, -46), (16.5, -28), (19, -10), (0, -9.5), (-19, -10),
                              (-16.5, -28), (-14.2, -46)], 0.8)
        shade(c, coat, sp.top, L, shadow="#cfc7b8", depth=3.0)
        # распахнутый халат: комбинезон
        bib = smooth_closed([(-5.5, -49), (5.5, -49), (6.5, -28), (5.2, -12), (-5.2, -12), (-6.5, -28)])
        shade(c, bib, sp.legs, L, depth=1.6)
        c.drawRect(skia.Rect(-3.5, -46, 3.5, -40), paint("#7aa83c"))
        for bx in (-4.6, 4.6):
            c.drawCircle(bx, -47.3, 1.2, paint("#e8c14e"))
        line(c, [(-6.2, -51), (-4.3, -30), (-5.8, -11)], 1.0, "#cfc7b8")
        line(c, [(6.2, -51), (4.3, -30), (5.8, -11)], 1.0, "#cfc7b8")
        # пояс с инструментами
        belt = rrect(-16, -28.5, 32, 4.2, 1.5)
        flat(c, belt, "#7a5230", L, line_scale=0.7)
        flat(c, rrect(-13, -26, 4.5, 6, 1), "#8c6038", L, line_scale=0.6)
        line(c, [(10.5, -27), (12.5, -19)], 1.6, "#9aa3b5")
        flat(c, rrect(7, -26, 3.8, 5.5, 1), "#c0392b", L, line_scale=0.6)
        # закатанные рукава — в рукаве (см. sleeve)


def _head(c, sp: KidSpec, st, ex, L, hx, hy, r):
    f = 3.4  # сдвиг черт лица к направлению взгляда (вид 3/4)
    n = sp.name
    head = moved(_head_path(r), hx, hy)
    # задние волосы
    if n == "june":
        puff = blob(hx - 5, hy - r - 8, 13.5, 11, 0.07, seed=2)
        shade(c, puff, sp.hair, L, shadow="#1e110a", depth=2.6)
        for k in range(7):
            a = k * 0.9
            line(c, [(hx - 5 + math.cos(a) * 7, hy - r - 8 + math.sin(a) * 7), (hx - 5 + math.cos(a + 0.5) * 9.5, hy - r - 8 + math.sin(a + 0.5) * 9.5)], 0.8, "#6b4430", 0.8)
        back = smooth_closed([(hx - r - 1.5, hy - 2), (hx - r + 1, hy - r * 0.9), (hx, hy - r - 3), (hx + r - 1, hy - r * 0.9),
                              (hx + r + 1.5, hy - 2), (hx + r - 2, hy + 6), (hx - r + 2, hy + 6)])
        flat(c, back, sp.hair, L)
    if n == "dot":
        back = smooth_closed([(hx - r - 2.5, hy + 12), (hx - r - 3, hy - 6), (hx - r + 2, hy - r * 0.95), (hx, hy - r - 4),
                              (hx + r - 2, hy - r * 0.95), (hx + r + 3, hy - 6), (hx + r + 2.5, hy + 12), (hx, hy + 13)])
        shade(c, back, sp.hair, L, shadow="#22140c", depth=2.0)
    # ухо (видимое — с затылочной стороны)
    ear = ellipse(hx - r * 0.93, hy + 1.5, 4.2, 5.6)
    shade(c, ear, sp.skin, L, depth=1.2, rim=False)
    line(c, [(hx - r * 0.93 + 1, hy - 1.5), (hx - r * 0.93 - 1, hy + 1.5), (hx - r * 0.93 + 0.8, hy + 4)], 0.7,
         shade_of(sp.skin, -0.35))
    # лицо
    shade(c, head, sp.skin, L, depth=3.4)
    c.save(); c.clipPath(head, doAntiAlias=True)
    from .draw import rad_grad
    c.drawCircle(hx + L.key[0] * 9, hy + L.key[1] * 9, r * 1.1,
                 paint(None, shader=rad_grad((hx + L.key[0] * 9, hy + L.key[1] * 9), r * 1.1,
                                             [hexc("#fff3e0", 0.28), hexc("#fff3e0", 0.0)])))
    c.restore()
    # румянец
    for bx in (hx + f - 12.0, hx + f + 12.0):
        c.drawPath(ellipse(bx, hy + 9.5, 4.6, 2.8), paint(sp.blush, 0.36))
    # веснушки
    for i in range(sp.freckles):
        side = -1 if i % 2 else 1
        k = i // 2
        fx_ = hx + f + side * (8.5 + (k % 3) * 1.9)
        fy_ = hy + 8.0 + (k // 3) * 1.6 + (k % 2) * 0.7
        c.drawCircle(fx_, fy_, 0.55, paint(shade_of(sp.skin, -0.35), 0.8))
    # тень от волос на лбу
    eo, liftl, liftr, tilt, *_ = ex
    ey = hy + 2.0
    rx, ry = 7.0, 8.6
    _eye(c, hx + f - 8.8, ey, rx * 0.9, ry, sp, ex, st, L, far=False)
    _eye(c, hx + f + 8.6, ey, rx * 0.82, ry * 0.98, sp, ex, st, L, far=True)
    # нос
    nose = ellipse(hx + f + 1.4, hy + 8.6, 2.7, 2.1)
    c.drawPath(nose, paint(shade_of(sp.skin, -0.16)))
    c.drawPath(smooth_open([(hx + f - 0.6, hy + 9.8), (hx + f + 1.6, hy + 10.9), (hx + f + 3.6, hy + 9.6)]),
               paint(shade_of(sp.skin, -0.42), stroke=L.line * 0.75))
    c.drawCircle(hx + f + 0.7, hy + 7.6, 0.9, paint("#ffffff", 0.5))
    c.save()
    c.translate(hx + f + 0.8, hy + 14.6)
    c.scale(1.35, 1.35)
    _mouth(c, 0, 0, sp, ex, st, L, gap_tooth=(n == "dot"))
    c.restore()
    # волосы спереди
    bw = 2.9 if n == "theo" else 2.3
    brow_col = shade_of(sp.hair, -0.5) if sp.name != "june" else "#1a0f0a"
    _hair_front(c, sp, st, L, hx, hy, r, f)
    _brow(c, hx + f - 8.8, ey - 12.0, liftl, tilt, -1, bw, brow_col, L)
    _brow(c, hx + f + 8.6, ey - 12.0, liftr, tilt, 1, bw, brow_col, L)


def _hair_front(c, sp, st, L, hx, hy, r, f):
    n = sp.name
    if n == "theo":
        parts = [ellipse(hx - 1, hy - r * 0.8, r * 1.05, r * 0.5)]
        for i in range(9):
            a = math.radians(196 + i * 18.5)
            parts.append(ellipse(hx + math.cos(a) * r * 1.0, hy + math.sin(a) * r * 0.96 - 2.5, 6.8, 6.2))
        for i, xx in enumerate((-12, -6, 0.5, 7, 12.5)):
            parts.append(ellipse(hx + xx + f * 0.5, hy - r * 0.76 + (i % 2) * 1.8, 5.4, 4.2))
        hair = union(*parts)
        # тень волос на лбу
        c.save(); c.clipPath(moved(_head_path(r), hx, hy), doAntiAlias=True)
        c.drawPath(moved(hair, 0.8, 2.6), paint(shade_of(sp.skin, -0.3), 0.55))
        c.restore()
        shade(c, hair, sp.hair, L, shadow="#4e2c16", depth=2.6)
        for xx, yy in ((-6, -15), (3, -17), (9, -12)):
            line(c, [(hx + xx, hy + yy), (hx + xx + 3, hy + yy - 2.4)], 1.0, "#a8693e", 0.85)
        # вихор-«антенна»
        sway = math.sin(st.t * 3.0) * 2.0
        tuft = smooth_closed([(hx - 2, hy - r - 6), (hx + 0.5 + sway * 0.4, hy - r - 13), (hx + 6 + sway, hy - r - 15.5),
                              (hx + 3.6 + sway * 0.7, hy - r - 11), (hx + 2.5, hy - r - 6)])
        shade(c, tuft, sp.hair, L, shadow="#4e2c16", depth=1.2)
    elif n == "june":
        cap = union(ellipse(hx, hy - r * 0.62, r * 1.06, r * 0.6),
                    ellipse(hx - r * 0.86, hy - 4, 5.2, 8.5), ellipse(hx + r * 0.88, hy - 5, 4.6, 7.6))
        front_edge = smooth_closed([(hx - r * 0.8, hy - r * 0.3), (hx - 4 + f, hy - r * 0.6), (hx + r * 0.85, hy - r * 0.32),
                                    (hx + r, hy - r * 1.3), (hx - r, hy - r * 1.3)])
        cap = union(inter(cap, front_edge), ellipse(hx, hy - r * 0.86, r * 0.95, r * 0.36))
        c.save(); c.clipPath(moved(_head_path(r), hx, hy), doAntiAlias=True)
        c.drawPath(moved(cap, 0.6, 2.2), paint(shade_of(sp.skin, -0.3), 0.5))
        c.restore()
        shade(c, cap, sp.hair, L, shadow="#1e110a", depth=2.2)
        # повязка
        band = smooth_open([(hx - r * 0.98, hy - r * 0.48), (hx - 2, hy - r * 1.0), (hx + r * 0.98, hy - r * 0.5)])
        c.drawPath(band, paint(L.outline, stroke=5.0))
        c.drawPath(band, paint("#2f8f5b", stroke=3.4))
        c.drawPath(moved(band, 0, -0.9), paint("#5ccf8e", stroke=0.9))
        line(c, [(hx - 8, hy - r * 0.86), (hx - 2, hy - r * 0.92)], 0.8, "#ffffff", 0.18)
    elif n == "dot":
        bangs = smooth_closed([(hx - r - 2, hy - 2), (hx - r + 1, hy - r * 0.95), (hx, hy - r - 4), (hx + r - 1, hy - r * 0.95),
                               (hx + r + 2, hy - 2), (hx + r - 1.5, hy - 1), (hx + r - 3, hy - r * 0.55),
                               (hx + 4 + f, hy - r * 0.52), (hx - 6 + f, hy - r * 0.55), (hx - r + 3, hy - r * 0.53),
                               (hx - r + 1.5, hy - 1)], 0.7)
        c.save(); c.clipPath(moved(_head_path(r), hx, hy), doAntiAlias=True)
        c.drawPath(moved(bangs, 0.5, 2.0), paint(shade_of(sp.skin, -0.3), 0.5))
        c.restore()
        shade(c, bangs, sp.hair, L, shadow="#22140c", depth=2.0)
        for xx in (-9, -3, 4, 10):
            line(c, [(hx + xx + f * 0.4, hy - r * 0.85), (hx + xx + f * 0.4 + 0.6, hy - r * 0.5)], 0.6, "#22140c", 0.8)
        # гогглы на лбу
        strap = smooth_open([(hx - r - 1, hy - r * 0.55), (hx, hy - r * 0.95), (hx + r + 1, hy - r * 0.55)])
        c.drawPath(strap, paint(L.outline, stroke=4.2))
        c.drawPath(strap, paint("#4a3226", stroke=2.8))
        glint = 0.5 + 0.5 * math.sin(st.t * 1.3)
        for gx in (hx + f - 7.6, hx + f + 7.2):
            gy = hy - r * 0.86
            flat(c, ellipse(gx, gy, 6.6, 5.6), "#c77b30", L)
            c.drawPath(ellipse(gx, gy, 4.6, 3.8), paint("#7fe3f0"))
            c.drawPath(ellipse(gx + 0.8, gy + 0.9, 3.6, 2.4), paint("#3fb6c9", 0.6))
            c.drawCircle(gx - 1.6, gy - 1.2, 1.3, paint("#ffffff", 0.6 + 0.4 * glint))
            c.drawPath(ellipse(gx, gy, 4.6, 3.8), paint(L.outline, stroke=0.7))
        flat(c, rrect(hx + f - 1.3, hy - r * 0.92, 2.6, 2.4, 0.6), "#c77b30", L, line_scale=0.5)


# ================================================================== собака
DOG = {"cream": "#f3ddb3", "toffee": "#c98b4f", "belly": "#fff1d8", "nose": "#1e1416", "collar": "#22c3b5"}


def draw_dog(c: skia.Canvas, st: State, L: Light):
    t = st.t
    ex = _expr(st)
    eo, liftl, liftr, tilt, smile, open_b, *_ = ex
    walking = st.walking
    sit = st.sit
    c.save()
    c.translate(0, -st.jump)
    bob = -abs(math.sin(st.walk * 2)) * 1.8 * walking + math.sin(t * 2.0) * 0.4
    c.translate(0, bob)
    # хвост
    wag = math.sin(t * (14 if st.wag else 3)) * (24 if st.wag else 6)
    base = (-31 + sit * 6, -18 + sit * 10)
    ta = math.radians(-55 + wag)
    tip = (base[0] - 9 * math.cos(ta) * -1 * -1 - 2, base[1] - 11 * math.cos(math.radians(wag)) - 2)
    noodle(c, [base, (base[0] - 7, base[1] - 6 + sit * 2), (tip[0] - 4 + wag * 0.12, tip[1])], 5.4, DOG["cream"], L)
    # лапы
    legs = [(-23, 1), (-16, -1), (17, 1), (24, -1)]
    feet = []
    for i, (lx, side) in enumerate(legs):
        ph = st.walk * 2 + (0 if i in (0, 3) else math.pi)
        fx = lx + math.sin(ph) * 5 * walking
        fy = -max(0, math.cos(ph)) * 3.5 * walking
        far = i in (1, 3)
        if sit and lx < 0:
            fx, fy = lx + 8, 0
        col = shade_of(DOG["cream"], -0.18) if far else DOG["cream"]
        top_y = -10 + (sit * 6 if lx < 0 else 0)
        feet.append(((lx + (sit * 6 if lx < 0 else 0), top_y), (fx, fy), col, far))
    for top, foot, col, far in feet:
        if far:
            noodle(c, [top, (foot[0], foot[1] - 2)], 6.0, col, L)
            flat(c, ellipse(foot[0] + 1.2, foot[1] - 1.5, 3.8, 2.4), col, L)
    # тело
    c.save()
    c.translate(0, 6)
    c.save()
    c.translate(0, -18)
    c.rotate(-sit * 24)
    c.translate(0, 18)
    body = smooth_closed([(-32, -22), (-24, -31), (0, -31.5), (22, -31), (31, -24), (29, -14), (14, -11), (-14, -11),
                          (-30, -14)])
    shade(c, body, DOG["cream"], L, depth=3.0)
    c.save(); c.clipPath(body, doAntiAlias=True)
    saddle = smooth_closed([(-28, -34), (-18, -25), (2, -23), (14, -27), (12, -36), (-20, -36)])
    c.drawPath(saddle, paint(DOG["toffee"]))
    c.drawPath(ellipse(4, -10, 22, 5), paint(DOG["belly"], 0.9))
    c.restore()
    c.drawPath(body, paint(L.outline, stroke=L.line))
    c.restore()
    c.restore()
    for top, foot, col, far in feet:
        if not far:
            noodle(c, [top, (foot[0], foot[1] - 2)], 6.4, col, L)
            flat(c, ellipse(foot[0] + 1.4, foot[1] - 1.5, 4.2, 2.6), DOG["cream"], L)
    # голова
    c.translate(0, 6)
    hx, hy = 31, -37 + sit * 4
    c.save()
    c.translate(hx, hy)
    c.rotate(st.tilt)
    c.translate(-hx, -hy)
    # висячее ухо (дальнее)
    flop = math.sin(t * 2.5) * 3
    ear2 = smooth_closed([(hx + 1, hy - 10), (hx + 9, hy - 9), (hx + 13 + flop * 0.3, hy - 1), (hx + 9, hy + 2)])
    shade(c, ear2, DOG["toffee"], L, depth=1.4)
    head = smooth_closed([(hx - 12, hy - 2), (hx - 9, hy - 11), (hx, hy - 13), (hx + 9, hy - 9), (hx + 11, hy - 1),
                          (hx + 7, hy + 7), (hx - 4, hy + 8), (hx - 11, hy + 5)])
    shade(c, head, DOG["cream"], L, depth=2.4)
    c.save(); c.clipPath(head, doAntiAlias=True)
    c.drawPath(ellipse(hx + 2.6, hy - 3.2, 7.6, 7.4), paint(DOG["toffee"]))  # пятно на глазу
    c.restore()
    c.drawPath(head, paint(L.outline, stroke=L.line))
    snout = smooth_closed([(hx + 4, hy - 1), (hx + 14, hy - 1.5), (hx + 18.5, hy + 2.5), (hx + 16, hy + 7), (hx + 5, hy + 7.5)])
    shade(c, snout, DOG["belly"], L, depth=1.4)
    flat(c, ellipse(hx + 17.5, hy + 1.2, 2.8, 2.1), DOG["nose"], L, line_scale=0.6)
    c.drawCircle(hx + 16.8, hy + 0.5, 0.8, paint("#ffffff", 0.7))
    # рот
    if smile > 0.5 or open_b > 0.2 or st.wag:
        m = smooth_closed([(hx + 9, hy + 5), (hx + 16, hy + 4.6), (hx + 13.5, hy + 8.5), (hx + 10, hy + 8.2)])
        c.drawPath(m, paint("#5b1a2a"))
        c.drawPath(ellipse(hx + 12.5, hy + 8.6, 2.2, 2.6), paint("#e8737f"))
        c.drawPath(m, paint(L.outline, stroke=L.line * 0.8))
    else:
        line(c, [(hx + 9.5, hy + 5.6), (hx + 12.5, hy + 6.4 + smile), (hx + 16.5, hy + 4.4)], L.line * 0.9, L.outline)
    # глаза: оба спереди на морде (ракурс 3/4), дальний — меньше и сжат
    blink = st.blink
    lx, ly = st.look
    op = clamp(eo * (1 - blink), 0, 1.3)
    for gx, gy, rr, sq, far in ((hx + 10.4, hy - 4.9, 3.7, 0.78, True), (hx + 3.0, hy - 3.4, 5.0, 1.0, False)):
        ry_ = rr * (0.25 + 0.75 * min(op, 1.25))
        rx_ = rr * sq
        ey = ellipse(gx, gy, rx_, ry_)
        c.drawPath(ey, paint("#fdfbf7"))
        c.save(); c.clipPath(ey, doAntiAlias=True)
        ix, iy = gx + rx_ * 0.18 + lx * rx_ * 0.3, gy + ry_ * 0.08 + ly * ry_ * 0.25
        c.drawCircle(ix, iy, rr * 0.74, paint("#3a2414"))
        c.drawCircle(ix, iy + rr * 0.25, rr * 0.6, paint("#5a3a22", 0.6))
        c.drawCircle(ix, iy, rr * 0.42, paint("#120a08"))
        c.drawCircle(ix - rr * 0.28, iy - rr * 0.32, rr * 0.27, paint("#ffffff"))
        c.drawCircle(ix + rr * 0.25, iy + rr * 0.25, rr * 0.11, paint("#ffffff", 0.9))
        c.drawPath(ellipse(gx, gy - ry_ * 1.0, rx_ * 1.3, ry_ * 0.45), paint("#c9c2d8", 0.35))
        c.restore()
        c.drawPath(ey, paint(L.outline, stroke=L.line * 0.85))
        top = skia.Path()
        top.addArc(skia.Rect(gx - rx_, gy - ry_, gx + rx_, gy + ry_), 200, 140)
        c.drawPath(top, paint(L.outline, stroke=L.line * 1.5))
        # брови — главная мимика собаки
        lift = (liftl if not far else liftr) * 0.45
        k = tilt * 0.07
        bw_ = rr * (0.75 if far else 0.85)
        inner = (gx - bw_ if far else gx + bw_, gy - ry_ - 1.2 - lift - k)
        outer = (gx + bw_ if far else gx - bw_, gy - ry_ - 1.0 - lift + k * 0.6)
        line(c, [inner, ((inner[0] + outer[0]) / 2, (inner[1] + outer[1]) / 2 - 0.5), outer], 1.6, "#3a2414")
    # стоячее ухо (ближнее)
    perk = math.sin(t * 1.7) * 1.2
    ear1 = smooth_closed([(hx - 9, hy - 7), (hx - 9 + perk * 0.3, hy - 24 - perk), (hx - 1, hy - 11)])
    shade(c, ear1, DOG["toffee"], L, depth=1.4)
    c.drawPath(smooth_closed([(hx - 7.6, hy - 9), (hx - 8.2 + perk * 0.3, hy - 20 - perk), (hx - 3, hy - 11)]),
               paint("#f0b7a0", 0.85))
    c.restore()
    # ошейник с динамиком
    col = smooth_closed([(hx - 13, hy + 1), (hx - 6, hy + 4.5), (hx - 3, hy + 9), (hx - 6.5, hy + 11), (hx - 14, hy + 6)])
    shade(c, col, DOG["collar"], L, depth=1.0)
    gl = clamp(st.amp * 1.6)
    sx, sy = hx - 6, hy + 9.6
    flat(c, ellipse(sx, sy, 2.9, 2.9), "#16707a", L, line_scale=0.6)
    c.drawCircle(sx, sy, 2.0, paint(mix("#2fa8b8", "#c8ffff", gl)))
    if gl > 0.02:
        glow(c, sx, sy, 7 + 9 * gl, "#6ff2ff", 0.8 * gl)
    c.restore()
    return {"head": (hx, hy - 4 + bob), "hand": (hx + 10, hy + 6), "collar": (sx, sy + 6 + bob)}


# ================================================================== Ночной Почтальон
COURIER = {"coat": "#1e2a4a", "coat_sh": "#121a30", "brass": "#d9b25a", "scarf": "#8e2f3a", "face": "#2b3550",
           "glint": "#ffe9a8", "bag": "#6b4528", "lamp": "#ffb547"}


def draw_courier(c: skia.Canvas, st: State, L: Light, bike: bool = False, bike_dist: float = 0.0):
    t = st.t
    K = COURIER
    (na1, na2), (fa1, fa2) = _pose(st)
    anchors = {}
    c.save()
    seat_drop = 52 if bike else 0
    if bike:
        _bike(c, L, bike_dist, back=True)
    c.translate(0, seat_drop)
    # ноги / сапоги
    if bike:
        crank = (2, -24 - seat_drop)
        ang = bike_dist / 9.0
        for k, ph in enumerate((0, math.pi)):
            pd = (crank[0] + math.cos(ang + ph) * 8, crank[1] + math.sin(ang + ph) * 8)
            hip = (-8, -78)
            knee = _leg_ik(hip, pd, 26, 26, bend=1)
            noodle(c, [hip, knee, pd], 8.5, "#151a2a" if k else "#1b2238", L)
            flat(c, ellipse(pd[0] + 2, pd[1], 5.6, 2.8), "#0f1018", L)
    else:
        for side in (-1, 1):
            fx = side * 6 + math.sin(st.walk + (0 if side < 0 else math.pi)) * 7 * st.walking
            noodle(c, [(side * 6, -24), (fx, -3)], 8.5, "#161b2c", L)
            flat(c, smooth_closed([(fx - 5, -1), (fx - 4, -6), (fx + 4, -6), (fx + 9, -2), (fx + 9, 0.8), (fx - 5, 0.8)]),
                 "#0f1018", L)
    # пальто
    sway = math.sin(t * 1.4) * 1.5
    coat = smooth_closed([(-12, -152), (12, -152), (18, -140), (22, -96), (27 + sway, -40 if not bike else -70),
                          (25 + sway, -16 if not bike else -50), (0, -14 if not bike else -48),
                          (-25 + sway, -16 if not bike else -50), (-27 + sway, -40 if not bike else -70), (-22, -96),
                          (-18, -140)], 0.85)
    # дальняя рука
    fsh = (-12, -144)
    fe, fh = _limb(fsh, 26, 24, fa1, fa2)
    noodle(c, [fsh, fe, fh], 9.5, K["coat_sh"], L)
    flat(c, ellipse(*fh, 4.6, 4.6), "#1a1414", L)
    # сумка (за пальто, ремень спереди)
    bag = rrect(-30, -92, 20, 17, 3)
    shade(c, bag, K["bag"], L, depth=1.6)
    shade(c, coat, K["coat"], L, shadow=K["coat_sh"], depth=4.0)
    line(c, [(1.5, -146), (2, -60 if bike else -20)], 1.0, "#141c34")
    for yy in (-136, -120, -104, -88):
        flat(c, ellipse(5.5, yy, 1.9, 1.9), K["brass"], L, line_scale=0.5)
    line(c, [(14, -150), (-4, -112), (-24, -84)], 2.2, "#4a301c")
    flap = rrect(-31, -93, 22, 7, 2.5)
    shade(c, flap, shade_of(K["bag"], -0.1), L, depth=1.0)
    from .util import font
    from .draw import text
    text(c, "A.L.", -20, -87.4, font("round", 4.0), K["brass"], align="center")
    # шарф и голова
    scarf = smooth_closed([(-11, -156), (11, -156), (12, -148), (0, -146), (-12, -148)])
    shade(c, scarf, K["scarf"], L, depth=1.4)
    tail = smooth_closed([(6, -150), (11, -149), (13 + sway * 1.5, -128), (8 + sway, -127)])
    shade(c, tail, K["scarf"], L, depth=1.0)
    hx, hy = 1, -168
    head = smooth_closed([(hx - 10, hy - 4), (hx - 8, hy - 13), (hx + 9, hy - 13), (hx + 11, hy - 3), (hx + 8, hy + 9),
                          (hx, hy + 12), (hx - 7, hy + 9)])
    shade(c, head, K["face"], L, depth=2.0, rim=True)
    # очки с бликом
    gl = 0.55 + 0.45 * max(0.0, math.sin(t * 1.1)) ** 6
    for gx in (hx + 1, hx + 9):
        c.drawPath(ellipse(gx, hy - 1, 3.6, 3.2), paint("#ffe9a8", 0.35 + 0.5 * gl))
        c.drawPath(ellipse(gx, hy - 1, 3.6, 3.2), paint("#c9a45a", stroke=0.9))
    line(c, [(hx + 4.6, hy - 1.5), (hx + 5.4, hy - 1.5)], 0.8, "#c9a45a")
    glow(c, hx + 5, hy - 1, 9 + 7 * gl, K["glint"], 0.35 * gl)
    # фуражка
    crown = smooth_closed([(hx - 12, hy - 9), (hx - 13, hy - 19), (hx + 1, hy - 23), (hx + 14, hy - 19), (hx + 12, hy - 9)])
    shade(c, crown, "#18213b", L, depth=1.8)
    c.drawRect(skia.Rect(hx - 12, hy - 11.5, hx + 12, hy - 8.5), paint("#2c3a63"))
    flat(c, ellipse(hx + 1, hy - 15, 2.2, 2.2), K["brass"], L, line_scale=0.5)
    brim = smooth_closed([(hx - 4, hy - 10), (hx + 19, hy - 9), (hx + 17, hy - 6), (hx - 3, hy - 7)])
    flat(c, brim, "#0e1424", L)
    # ближняя рука
    nsh = (11, -144)
    if bike:
        na1, na2 = 62, 30
    ne, nh = _limb(nsh, 26, 24, na1, na2)
    noodle(c, [nsh, ne, nh], 9.5, K["coat"], L)
    if st.prop:
        from .props import draw_prop
        draw_prop(c, st.prop, nh, st, L)
    flat(c, ellipse(*nh, 4.8, 4.8), "#1a1414", L)
    anchors["hand"] = (nh[0], nh[1] + seat_drop)
    anchors["head"] = (hx, hy + seat_drop)
    c.restore()
    if bike:
        anchors["lamp"] = _bike(c, L, bike_dist, back=False)
    return anchors


def _bike(c, L, dist, back):
    wheel_r = 22
    rear, front = (-40, -wheel_r), (44, -wheel_r)
    if back:
        for wx, wy in (rear, front):
            c.drawCircle(wx, wy, wheel_r, paint(L.outline, stroke=3.6))
            c.drawCircle(wx, wy, wheel_r, paint("#3a3f52", stroke=2.0))
            ang = dist / wheel_r
            for k in range(8):
                a = ang + k * math.pi / 4
                line(c, [(wx, wy), (wx + math.cos(a) * wheel_r, wy + math.sin(a) * wheel_r)], 0.5, "#8a8fa3", 0.8, smooth=False)
            c.drawCircle(wx, wy, 2.4, paint("#c9a45a"))
        return None
    frame = [(rear[0], rear[1]), (0, -24), (34, -58), (-6, -60), (rear[0], rear[1])]
    c.drawPath(poly(frame, close=False), paint(L.outline, stroke=4.6))
    c.drawPath(poly(frame, close=False), paint("#7a2632", stroke=3.0))
    line(c, [(-6, -60), (0, -24)], 3.0, "#7a2632", smooth=False)
    line(c, [(34, -58), (front[0], front[1])], 3.0, "#7a2632", smooth=False)
    line(c, [(34, -58), (31, -70), (24, -72)], 2.4, "#2a2a30", smooth=False)
    flat(c, rrect(-14, -66, 15, 4.5, 2), "#3a2418", L)
    lamp = (40, -64)
    flat(c, rrect(lamp[0] - 4, lamp[1] - 6, 9, 10, 2), "#c9a45a", L)
    c.drawCircle(lamp[0] + 1, lamp[1] - 1, 3.2, paint("#fff1c4"))
    flick = 0.85 + 0.15 * math.sin(dist * 0.7)
    glow(c, lamp[0] + 1, lamp[1] - 1, 44 * flick, COURIER["lamp"], 0.75)
    glow(c, lamp[0] + 1, lamp[1] - 1, 12, "#fff6dc", 0.9)
    return lamp


def draw_character(c, who: str, st: State, L: Light, **kw):
    if who == "theo":
        return draw_kid(c, THEO, st, L)
    if who == "june":
        return draw_kid(c, JUNE, st, L)
    if who == "dot":
        return draw_kid(c, DOT, st, L)
    if who == "biscuit":
        return draw_dog(c, st, L)
    if who == "courier":
        return draw_courier(c, st, L, **kw)
    raise KeyError(who)


HEIGHTS = {"theo": 100, "june": 104, "dot": 92, "biscuit": 40, "courier": 190}
