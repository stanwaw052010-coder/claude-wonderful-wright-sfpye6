"""Кисти студии: контуры, cel-shading, «лапша»-конечности, свечения, текст.

Все персонажи и декорации рисуются этими функциями — так стиль един.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import skia

from .util import hexc, shade_of

AA = True


@dataclass
class Light:
    """Свет сцены для cel-shading. key — направление НА источник (экранные оси)."""
    key: tuple[float, float] = (-0.55, -0.85)
    shadow_amt: float = 0.22         # насколько темнее тень
    rim: str = "#ffe2a8"             # цвет контрового света
    rim_dir: tuple[float, float] = (0.8, -0.4)
    rim_alpha: float = 0.55
    outline: str = "#2a1a24"
    line: float = 1.15               # толщина контура в единицах персонажа


DEFAULT_LIGHT = Light()


def paint(color, alpha=1.0, stroke=0.0, blend=None, shader=None, cap_round=True):
    p = skia.Paint(AntiAlias=AA)
    if isinstance(color, str):
        p.setColor(hexc(color, alpha))
    elif color is not None:
        p.setColor(color)
    if stroke:
        p.setStyle(skia.Paint.kStroke_Style)
        p.setStrokeWidth(stroke)
        if cap_round:
            p.setStrokeCap(skia.Paint.kRound_Cap)
            p.setStrokeJoin(skia.Paint.kRound_Join)
    if blend is not None:
        p.setBlendMode(blend)
    if shader is not None:
        p.setShader(shader)
    return p


# ---------------------------------------------------------------- пути
def smooth_closed(pts, tension=1.0) -> skia.Path:
    """Замкнутый сплайн Catmull-Rom через точки."""
    n = len(pts)
    p = skia.Path()
    p.moveTo(*pts[0])
    for i in range(n):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6 * tension, p1[1] + (p2[1] - p0[1]) / 6 * tension)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6 * tension, p2[1] - (p3[1] - p1[1]) / 6 * tension)
        p.cubicTo(*c1, *c2, *p2)
    p.close()
    return p


def smooth_open(pts, tension=1.0) -> skia.Path:
    p = skia.Path()
    p.moveTo(*pts[0])
    n = len(pts)
    for i in range(n - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < n else pts[i + 1]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6 * tension, p1[1] + (p2[1] - p0[1]) / 6 * tension)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6 * tension, p2[1] - (p3[1] - p1[1]) / 6 * tension)
        p.cubicTo(*c1, *c2, *p2)
    return p


def poly(pts, close=True) -> skia.Path:
    p = skia.Path()
    p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    if close:
        p.close()
    return p


def ellipse(cx, cy, rx, ry) -> skia.Path:
    p = skia.Path()
    p.addOval(skia.Rect(cx - rx, cy - ry, cx + rx, cy + ry))
    return p


def rrect(x, y, w, h, r) -> skia.Path:
    p = skia.Path()
    p.addRRect(skia.RRect.MakeRectXY(skia.Rect(x, y, x + w, y + h), r, r))
    return p


def union(*paths) -> skia.Path:
    out = paths[0]
    for q in paths[1:]:
        out = skia.Op(out, q, skia.PathOp.kUnion_PathOp)
    return out


def diff(a, b) -> skia.Path:
    return skia.Op(a, b, skia.PathOp.kDifference_PathOp)


def inter(a, b) -> skia.Path:
    return skia.Op(a, b, skia.PathOp.kIntersect_PathOp)


def moved(path, dx, dy) -> skia.Path:
    q = skia.Path(path)
    q.offset(dx, dy)
    return q


def blob(cx, cy, r, bumps, amp, seed=0, squash=1.0) -> skia.Path:
    """Кучерявое облако / шапка волос: круг с буграми."""
    pts = []
    n = bumps * 2
    for i in range(n):
        a = i / n * math.tau
        rr = r * (1 + (amp if i % 2 == 0 else -amp * 0.3) * (0.8 + 0.4 * math.sin(seed + i * 1.7)))
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr * squash))
    return smooth_closed(pts)


# ---------------------------------------------------------------- заливки
def shade(c: skia.Canvas, path: skia.Path, color: str, L: Light = DEFAULT_LIGHT,
          shadow: str | None = None, depth: float = 2.6, rim: bool = True, outline=True,
          line_scale=1.0):
    """Заливка + серп тени с дальней от света стороны + контровой свет + контур."""
    c.drawPath(path, paint(color))
    sh = shadow or shade_of(color, -L.shadow_amt - 0.12)
    kx, ky = L.key
    lit = moved(path, kx * depth, ky * depth)
    c.drawPath(diff(path, lit), paint(sh))
    if rim and L.rim_alpha > 0:
        rx, ry = L.rim_dir
        inner = moved(path, -rx * depth * 0.45, -ry * depth * 0.45)
        c.drawPath(diff(path, inner), paint(L.rim, L.rim_alpha, blend=skia.BlendMode.kScreen))
    if outline:
        c.drawPath(path, paint(L.outline, stroke=L.line * line_scale))


def flat(c, path, color, L: Light = DEFAULT_LIGHT, outline=True, alpha=1.0, line_scale=1.0):
    c.drawPath(path, paint(color, alpha))
    if outline:
        c.drawPath(path, paint(L.outline, stroke=L.line * line_scale))


def noodle(c, pts, width, color, L: Light = DEFAULT_LIGHT, shadow: str | None = None):
    """Мягкая конечность: обводка + заливка + тонкая тень по одной стороне."""
    path = smooth_open(pts) if len(pts) > 2 else poly(pts, close=False)
    c.drawPath(path, paint(L.outline, stroke=width + 2 * L.line))
    c.drawPath(path, paint(color, stroke=width))
    sh = shadow or shade_of(color, -L.shadow_amt - 0.1)
    q = moved(path, -L.key[0] * width * 0.22, -L.key[1] * width * 0.22)
    c.save()
    c.clipPath(_stroke_path(path, width), doAntiAlias=True)
    c.drawPath(q, paint(sh, stroke=width * 0.45))
    c.restore()


def _stroke_path(path, width):
    p = paint("#000000", stroke=width)
    out = skia.Path()
    p.getFillPath(path, out)
    return out


def line(c, pts, width, color, alpha=1.0, smooth=True):
    path = smooth_open(pts) if (smooth and len(pts) > 2) else poly(pts, close=False)
    c.drawPath(path, paint(color, alpha, stroke=width))


# ---------------------------------------------------------------- свет
def glow(c, x, y, r, color, alpha=1.0, blend=skia.BlendMode.kPlus, falloff=(0.0, 0.35, 1.0)):
    col = hexc(color)
    r_, g_, b_ = skia.ColorGetR(col) / 255, skia.ColorGetG(col) / 255, skia.ColorGetB(col) / 255
    cols = [skia.Color4f(r_, g_, b_, alpha), skia.Color4f(r_, g_, b_, alpha * 0.28), skia.Color4f(r_, g_, b_, 0)]
    sh = skia.GradientShader.MakeRadial((x, y), max(r, 0.5), [cc.toColor() for cc in cols], list(falloff))
    c.drawCircle(x, y, r, paint(None, blend=blend, shader=sh))


def lin_grad(p0, p1, colors, pos=None):
    return skia.GradientShader.MakeLinear([p0, p1], [hexc(cc) if isinstance(cc, str) else cc for cc in colors], pos)


def rad_grad(center, r, colors, pos=None):
    return skia.GradientShader.MakeRadial(center, r, [hexc(cc) if isinstance(cc, str) else cc for cc in colors], pos)


def blur_paint(sigma, color=None, alpha=1.0):
    p = paint(color, alpha) if color else skia.Paint(AntiAlias=True)
    p.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, sigma))
    return p


# ---------------------------------------------------------------- текст
def text(c, s, x, y, fnt, color="#ffffff", align="left", alpha=1.0, stroke=0.0, stroke_color="#000000",
         shadow: tuple | None = None):
    w = fnt.measureText(s)
    if align == "center":
        x -= w / 2
    elif align == "right":
        x -= w
    if shadow:
        dx, dy, sig, col, a = shadow
        c.drawString(s, x + dx, y + dy, fnt, blur_paint(sig, col, a))
    if stroke:
        p = paint(stroke_color, alpha, stroke=stroke)
        c.drawString(s, x, y, fnt, p)
    c.drawString(s, x, y, fnt, paint(color, alpha))
    return w
