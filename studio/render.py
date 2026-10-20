"""Покадровая сборка: камера → слои декорации → свет → персонажи → эффекты → пост.

Рендер параллельный: каждый процесс считает свой отрезок кадров и пишет свой
сегмент H.264, затем сегменты склеиваются без перекодирования.
"""
from __future__ import annotations

import math
import multiprocessing as mp
import os
import subprocess
from pathlib import Path

import numpy as np
import skia

from . import fx, inserts, sets
from .characters import HEIGHTS, State, draw_character
from .draw import ellipse, glow, paint
from .episode import Episode, Shot, char_state
from .util import FPS, H, W, clamp, ease_io, font, hash01, lerp, smooth, vnoise

SAMPLING = skia.SamplingOptions(skia.FilterMode.kLinear, skia.MipmapMode.kLinear)


class Renderer:
    def __init__(self, ep: Episode, scale: float = 1.0):
        self.ep = ep
        self.scale = scale
        self.sets = {}
        self.blurred = {}

    # ------------------------------------------------------------ декорации
    def get_set(self, name, light):
        k = (name, light)
        if k not in self.sets:
            self.sets[k] = sets.build(name, light)
        return self.sets[k]

    def blurred_layers(self, S):
        k = id(S)
        if k not in self.blurred:
            out = []
            for d, im in S.layers:
                arr = np.zeros((im.height(), im.width(), 4), np.uint8)
                s = skia.Surface(arr)
                c = s.getCanvas()
                p = skia.Paint(ImageFilter=skia.ImageFilters.Blur(9 * sets.SS, 9 * sets.SS, skia.TileMode.kClamp))
                c.drawImage(im, 0, 0, SAMPLING, p)
                out.append((d, skia.Image.fromarray(arr, colorType=skia.kRGBA_8888_ColorType,
                                                    alphaType=skia.kPremul_AlphaType)))
            self.blurred[k] = out
        return self.blurred[k]

    # ------------------------------------------------------------ поиск
    def scene_at(self, t):
        for sc in self.ep.scenes:
            if sc.t0 <= t < sc.t1:
                return sc
        return self.ep.scenes[-1]

    @staticmethod
    def shot_at(sc, lt) -> Shot:
        for s in sc.shots:
            if s.t0 <= lt < s.t1:
                return s
        return sc.shots[-1]

    # ------------------------------------------------------------ камера
    def camera(self, sc, S, shot: Shot, lt):
        dur = max(0.01, shot.t1 - shot.t0)
        k = clamp((lt - shot.t0) / dur)
        states = {}
        for who, tr in sc.tracks.items():
            st, _ = char_state(tr, lt, lt)
            if st.visible:
                states[who] = st
        on = [w for w in shot.on if w in sc.tracks]
        G = S.ground
        cy = 540.0
        if shot.kind == "wide":
            z = 1.0 + shot.push * ease_io(k)
            if shot.pan:
                pd = shot.pan_dur or dur
                kp = ease_io(clamp((lt - shot.t0) / pd)) if pd else 1
                cx = 960 + (S.width - 1920) * lerp(shot.pan[0], shot.pan[1], kp)
            elif on:
                cx = np.mean([char_state(sc.tracks[w], lt, lt)[0].x for w in on])
            elif states:
                xs = [s.x for s in states.values()]
                cx = (min(xs) + max(xs)) / 2
            else:
                cx = S.width / 2
        else:
            tg = on or list(states)[:2]
            xs, tops, fac = [], [], 1
            for w in tg:
                st, _ = char_state(sc.tracks[w], lt, lt)
                xs.append(st.x)
                tops.append(HEIGHTS[w])
                fac = st.facing if w == tg[0] else fac
            if not xs:
                xs, tops = [S.width / 2], [100]
            lead = tg[0] if tg else "theo"
            if shot.kind == "medium":
                spread = max(xs) - min(xs)
                z = clamp(1920 * 0.62 / (spread + 520), 1.25, 1.7)
                cx = (min(xs) + max(xs)) / 2 + (fac * 40 if len(xs) == 1 else 0)
                hmax = max(tops)
                if hmax > 150:
                    cy = G - 112 * S.scale
                    z = min(z, 1.3)
                elif hmax < 50:
                    cy = G - 30 * S.scale
                    z = 1.9
                else:
                    cy = G - 58 * S.scale
            else:  # close
                if lead == "courier":
                    z, cy, cx = 2.1, G - 160 * S.scale, xs[0] + fac * 30 * S.scale
                elif lead == "biscuit":
                    z, cy, cx = 2.6, G - 30 * S.scale, xs[0] + fac * 30 * S.scale
                else:
                    h = {"june": 1.04, "dot": 0.92}.get(lead, 1.0)
                    z, cy, cx = 2.35, G - 70 * h * S.scale, xs[0] + fac * 26 * S.scale
            z *= 1 + 0.035 * ease_io(k)
        # «ручная» камера
        cx += vnoise(lt * 0.35, 3) * 5
        cy += vnoise(lt * 0.3, 7) * 3
        hw, hh = 960 / z, 540 / z
        cx = clamp(cx, hw, S.width - hw)
        cy = clamp(cy, sets.Y0 + hh + 2, sets.Y1 - hh - 2)
        return cx, cy, z

    # ------------------------------------------------------------ кадр
    def frame(self, t) -> np.ndarray:
        s = self.scale
        arr = np.zeros((int(H * s), int(W * s), 4), np.uint8)
        surf = skia.Surface(arr)
        c = surf.getCanvas()
        c.scale(s, s)
        sc = self.scene_at(t)
        lt = t - sc.t0
        shot = self.shot_at(sc, lt)
        if shot.kind == "insert":
            inserts.draw_insert(c, shot.item, lt - shot.t0)
        elif shot.kind == "title":
            S = self.get_set("lookout", "night")
            inserts.draw_title(c, lt - shot.t0, lambda cc, tau: self.title_world(cc, S, tau))
        elif shot.kind == "endcard":
            S = self.get_set("lookout", "night")
            inserts.draw_endcard(c, lt - shot.t0, lambda cc, tau: self.end_world(cc, S, tau), shot.t1 - shot.t0)
        else:
            S = self.get_set(sc.set, sc.light)
            cam = self.camera(sc, S, shot, lt)
            self.world(c, sc, S, cam, lt)
        self.transition(c, sc, lt)
        return arr

    # ------------------------------------------------------------ мир
    def wpos(self, cam, x, y, depth=1.0):
        cx, cy, z = cam
        ex = 960 + (cx - 960) * depth
        ey = 540 + (cy - 540) * depth
        ze = 1 + (z - 1) * (0.25 + 0.75 * depth)
        return (x - ex) * ze + 960, (y - ey) * ze + 540

    def draw_layers(self, c, layers, cam):
        cx, cy, z = cam
        for d, im in layers:
            ex = 960 + (cx - 960) * d
            ey = 540 + (cy - 540) * d
            ze = 1 + (z - 1) * (0.25 + 0.75 * d)
            x0, x1 = ex - 960 / ze, ex + 960 / ze
            y0, y1 = ey - 540 / ze, ey + 540 / ze
            src = skia.Rect(x0 * sets.SS, (y0 - sets.Y0) * sets.SS, x1 * sets.SS, (y1 - sets.Y0) * sets.SS)
            c.drawImageRect(im, src, skia.Rect(0, 0, W, H), SAMPLING, None)

    def lantern_level(self, sc, lt):
        lvl = 1.0
        for (t0, f) in sc.fx:
            ty = f.get("type")
            if lt < t0:
                continue
            k = lt - t0
            if ty == "lantern_dim":
                lvl = lerp(1.0, 0.45, smooth(k / 1.5))
            elif ty == "drain":
                lvl = lerp(lvl, 0.12, smooth(k / float(f.get("dur", 2))))
            elif ty == "beam":
                lvl = lerp(lvl, 0.7, smooth(k / float(f.get("dur", 3))))
            elif ty == "lantern_bloom":
                lvl = 1.0 + 0.9 * math.exp(-k * 1.2) * smooth(k / 0.4) + 0.15 * smooth(k / 0.4)
        return lvl

    def world(self, c, sc, S, cam, lt, extra_chars=None):
        cx, cy, z = cam
        layers = self.blurred_layers(S) if z > 2.0 else S.layers
        self.draw_layers(c, layers, cam)
        lvl = self.lantern_level(sc, lt) if sc else 1.0
        # живой свет
        for L in S.lamps:
            fl = 1 + L.flicker * (vnoise(lt * 6 + L.x, 2) * 0.7 + vnoise(lt * 17 + L.y, 5) * 0.3)
            a = L.alpha * fl * (lvl if L.key in ("lantern", "tower") else 1.0)
            x, y = self.wpos(cam, L.x, L.y, L.depth)
            glow(c, x, y, L.r * z * (0.8 + 0.2 * min(lvl, 1.6)), L.color, min(a, 1.2))
            if L.key == "lantern":
                self.draw_lantern(c, x, y, z, lvl, lt)
        if sc:
            self.scene_fx_back(c, sc, S, cam, lt)
        # персонажи
        chars = []
        if sc:
            for who, tr in sc.tracks.items():
                st, ex = char_state(tr, lt, lt)
                if st.visible:
                    chars.append((tr.z, who, st, ex))
        if extra_chars:
            chars += extra_chars
        chars.sort(key=lambda q: (0 if q[1] == "courier" else 1, q[0]))
        anchors = {}
        for _, who, st, ex in chars:
            sx, sy = self.wpos(cam, st.x, S.ground)
            u = S.scale * z * st.scale
            # тень на земле
            sw = {"courier": 30, "biscuit": 38}.get(who, 20) * u
            c.drawOval(skia.Rect(sx - sw, sy - 4 * u, sx + sw, sy + 4 * u),
                       paint(S.shadow_color, S.shadow_alpha * st.alpha * (1 - clamp(st.jump / 30))))
            tr_, tg, tb = S.tint
            ar, ag, ab = S.tint_add
            cf = skia.ColorFilters.Matrix([tr_, 0, 0, 0, ar, 0, tg, 0, 0, ag, 0, 0, tb, 0, ab, 0, 0, 0, st.alpha, 0])
            c.saveLayer(None, skia.Paint(ColorFilter=cf))
            c.translate(sx, sy)
            c.scale(u * st.facing, u)
            kw = {}
            if who == "courier":
                kw = {"bike": ex.get("bike", False), "bike_dist": st.x}
            if who == "june" and ex.get("bike"):
                pass
            an = draw_character(c, who, st, S.light, **kw)
            c.restore()
            anchors[who] = {k: (sx + v[0] * u * st.facing, sy + v[1] * u) for k, v in an.items() if v}
            anchors[who]["center"] = (sx, sy - HEIGHTS[who] * 0.5 * u)
            if st.prop == "flashlight" and st.pose == "flashlight":
                hx, hy = anchors[who]["hand"]
                fx.flashlight_cone(c, hx + st.facing * 12 * u, hy, st.facing, u)
            if who == "biscuit" and ex.get("glitch"):
                cx_, cy_ = anchors[who].get("collar", (sx, sy))
                for i in range(10):
                    fx.pixel(c, cx_ + math.sin(lt * 23 + i * 2) * 40 * z, cy_ + math.cos(lt * 17 + i) * 30 * z, 8 * z,
                             fx.CYAN, 0.9 * (0.5 + 0.5 * math.sin(lt * 40 + i)))
        if sc:
            self.scene_fx_front(c, sc, S, cam, lt, anchors)
        # передний план
        if S.front and z < 1.15:
            self.draw_layers(c, S.front, cam)
        fx.ambient(c, S.particles, lt, cam, S.width, z, lambda x, y, d: self.wpos(cam, x, y, d))
        if sc and S.data.get("flicker"):
            self.flicker(c, sc, S, cam, lt)
        for kind, *a in S.overlay:
            if kind == "vignette":
                fx.vignette(c, a[0])
            elif kind == "top":
                fx.top_grad(c, a[0], a[1])
            elif kind == "sun":
                fx.sun_wash(c, a[0], a[1])
        if sc and sc.caption and 0.3 < lt < 3.6:
            al = smooth((lt - 0.3) / 0.5) * (1 - smooth((lt - 3.0) / 0.6))
            from .draw import text
            text(c, sc.caption, W / 2, 150, font("logo", 72), "#ffd23f", align="center", alpha=al, stroke=16,
                 stroke_color="#0d0a24")
        return anchors

    def draw_lantern(self, c, x, y, z, lvl, lt):
        u = 3.0 * z
        c.drawRect(skia.Rect(x - 9 * u, y - 14 * u, x + 9 * u, y + 13 * u), paint("#7a5420"))
        c.drawRect(skia.Rect(x - 7 * u, y - 11 * u, x + 7 * u, y + 10 * u), paint("#fff3c4", clamp(0.3 + 0.6 * lvl)))
        c.drawRect(skia.Rect(x - 11 * u, y - 18 * u, x + 11 * u, y - 14 * u), paint("#5a3a14"))
        c.drawRect(skia.Rect(x - 11 * u, y + 13 * u, x + 11 * u, y + 17 * u), paint("#5a3a14"))
        c.drawCircle(x, y - 22 * u, 4 * u, paint("#5a3a14", stroke=1.5 * u))
        glow(c, x, y, 40 * u * min(lvl, 1.8), "#fff6dc", clamp(0.9 * lvl))
        for i in range(int(14 * min(lvl, 1.5))):
            a = lt * 0.6 + i * 0.45
            r = (18 + (i * 7) % 30) * u
            fx.pixel(c, x + math.cos(a) * r, y + math.sin(a) * r * 0.6 - (lt * 10 + i * 13) % (12 * u), 3 * u,
                     fx.AMBER if i % 3 else fx.CYAN, 0.7 * clamp(lvl))

    def flicker(self, c, sc, S, cam, lt):
        t_on = None
        for (t0, f) in sc.fx:
            if f.get("type") == "flicker_on":
                t_on = t0
        if t_on is None or lt < t_on:
            return
        k = smooth((lt - t_on) / 2.0)
        for i in range(160):
            x = hash01("fl", i) * S.width
            y = 300 + hash01("fly", i) * 560
            d = 0.45 if i % 2 else 1.0
            sx, sy = self.wpos(cam, x, y, d)
            a = k * max(0.0, math.sin(lt * (1.5 + i % 4) + i)) ** 2
            fx.pixel(c, sx, sy, (4 if d < 1 else 6) * cam[2], fx.CYAN if i % 4 else fx.AMBER, a)

    def char_screen(self, sc, S, cam, who, lt, part="center"):
        tr = sc.tracks.get(who)
        if not tr:
            return 960, 540
        st, _ = char_state(tr, lt, lt)
        sx, sy = self.wpos(cam, st.x, S.ground)
        u = S.scale * cam[2]
        if part == "hand":
            return sx + st.facing * 30 * u, sy - 55 * u
        return sx, sy - HEIGHTS[who] * 0.55 * u

    def scene_fx_back(self, c, sc, S, cam, lt):
        for (t0, f) in sc.fx:
            ty = f.get("type")
            tau = lt - t0
            if ty == "tower_shadow" and 0 <= tau < 1.6 and "tower_window" in S.data:
                x, y = self.wpos(cam, *S.data["tower_window"])
                a = smooth(tau / 0.3) * (1 - smooth((tau - 1.1) / 0.4))
                u = cam[2] * 1.2
                c.drawOval(skia.Rect(x - 9 * u, y - 30 * u, x + 9 * u, y - 12 * u), paint("#120a18", a))
                c.drawRect(skia.Rect(x - 13 * u, y - 13 * u, x + 13 * u, y + 35 * u), paint("#120a18", a))
                c.drawRect(skia.Rect(x - 16 * u, y - 34 * u, x + 16 * u, y - 28 * u), paint("#120a18", a))
                c.drawCircle(x + 3 * u, y - 21 * u, 2.5 * u, paint("#ffe9a8", a))
            if ty == "stairs_glitch" and "stairs" in S.data:
                bloom = [t for (t, g) in sc.fx if g.get("type") == "lantern_bloom"]
                end = bloom[0] if bloom else 1e9
                if t0 <= lt < end + 1.0:
                    inten = 1.0 if lt < end else 1 - (lt - end)
                    sx0, sy0 = S.data["stairs"]
                    for i in range(9):
                        if hash01("st", i, int(lt * 8)) < 0.45 * inten:
                            wx, wy = sx0 + i * 46, sy0 - i * 40
                            x, y = self.wpos(cam, wx, wy)
                            u = cam[2]
                            c.drawRect(skia.Rect(x - 4 * u, y - 4 * u, x + 74 * u, y + 20 * u), paint("#140a1c"))
                            for k in range(5):
                                fx.pixel(c, x + (8 + k * 14) * u, y + 6 * u, 9 * u, fx.CYAN, 0.9 * inten)

    def scene_fx_front(self, c, sc, S, cam, lt, anchors):
        z = cam[2]
        for (t0, f) in sc.fx:
            ty = f.get("type")
            tau = lt - t0
            if tau < 0:
                continue
            at = f.get("at") or f.get("from")
            pos = None
            if at:
                pos = anchors.get(at, {}).get("center") or self.char_screen(sc, S, cam, at, t0)
            if ty == "pixels" and pos:
                fx.burst_pixels(c, pos[0], pos[1], tau, int(f.get("count", 40)), z * 1.2, seed=int(t0 * 100))
            elif ty == "confetti" and pos:
                fx.confetti(c, pos[0], pos[1] - 40 * z, tau, int(f.get("count", 80)), z * 1.4, seed=int(t0 * 100))
            elif ty == "flash":
                fx.flash(c, tau)
            elif ty in ("beam", "drain") and at and "lantern" in S.data:
                hand = anchors.get(at, {}).get("hand") or self.char_screen(sc, S, cam, at, lt, "hand")
                lx, ly = self.wpos(cam, *S.data["lantern"])
                d = float(f.get("dur", 3))
                if ty == "beam":
                    fx.beam(c, hand[0], hand[1] - 20 * z, lx, ly, tau, d, scale=z)
                else:
                    fx.beam(c, lx, ly, hand[0], hand[1] - 20 * z, tau, d, col=fx.AMBER, reverse=False, scale=z * 0.7)
            elif ty == "lantern_bloom" and "lantern" in S.data:
                lx, ly = self.wpos(cam, *S.data["lantern"])
                fx.burst_pixels(c, lx, ly, tau, 160, z * 2.2, seed=77, life=3.5, spread=2.5)
                if tau < 1.2:
                    c.drawPaint(paint("#fff3c4", 0.55 * (1 - tau / 1.2) ** 2, blend=skia.BlendMode.kScreen))

    # ------------------------------------------------------------ заставка/финал
    def title_world(self, c, S, tau):
        pan = ease_io(clamp(tau / 17))
        cam = (960 + (S.width - 1920) * (0.15 + 0.5 * pan), 540, 1.0 + 0.04 * pan)
        extra = []
        if tau > 8.6:
            order = [("theo", 1180, 1), ("june", 1340, -1), ("dot", 1020, 1), ("biscuit", 860, 1)]
            for i, (who, x, f) in enumerate(order):
                k = clamp((tau - 8.8 - i * 0.6) / 1.0)
                if k <= 0:
                    continue
                st = State(t=tau + i, x=cam[0] - 960 + 300 + i * 360 + (1 - ease_io(k)) * -500, facing=1,
                           expr=["grin", "happy", "excited", "happy"][i], pose=["wave", "hips", "cheer", "idle"][i],
                           walking=1 - k, alpha=k)
                st.walk = st.x / 22
                if who == "dot":
                    st.prop = "sniffer"
                if who == "biscuit":
                    st.wag = 1
                extra.append((i, who, st, {}))
        anchors = self.world(c, None, S, cam, tau, extra_chars=extra)
        if tau > 9.6:
            names = {"theo": "THEO", "june": "JUNE", "dot": "DOT", "biscuit": "BISCUIT"}
            from .draw import text
            for i, (who, *_r) in enumerate([("theo",), ("june",), ("dot",), ("biscuit",)]):
                k = clamp((tau - 9.8 - i * 0.6) / 0.4)
                if who in anchors and k > 0:
                    x, y = anchors[who]["center"]
                    text(c, names[who], x, S.ground - 30 + 120, font("logo", 52), "#ffffff", align="center", alpha=k,
                         stroke=14, stroke_color="#0d0a24")

    def end_world(self, c, S, tau):
        cam = (S.width * 0.5, 540, 1.0)
        x = 400 + tau * 260
        st = State(t=tau, x=x, facing=1, expr="worried", walking=1)
        st.walk = x / 14
        anchors = self.world(c, None, S, cam, tau, extra_chars=[(0, "biscuit", st, {})])
        # убегающая тень
        sx, sy = self.wpos(cam, x - 260 + math.sin(tau * 3) * 20, S.ground)
        u = S.scale
        c.save()
        c.translate(sx, sy + 4)
        c.scale(u, -u * 0.35)
        c.saveLayer(None, skia.Paint(ColorFilter=skia.ColorFilters.Matrix([0, 0, 0, 0, 0.02, 0, 0, 0, 0, 0.02, 0, 0, 0, 0,
                                                                            0.06, 0, 0, 0, 0.7, 0])))
        sh = State(t=tau + 1, walking=1)
        sh.walk = tau * 20
        draw_character(c, "biscuit", sh, S.light)
        c.restore()
        c.restore()

    # ------------------------------------------------------------ переходы
    def transition(self, c, sc, lt):
        idx = self.ep.scenes.index(sc)
        nxt = self.ep.scenes[idx + 1] if idx + 1 < len(self.ep.scenes) else None
        a = 0.0
        if sc.transition in ("fade", "wipe", "iris") and lt < 0.55:
            a = 1 - smooth(lt / 0.55)
        if idx == 0 and lt < 1.0:
            a = 1 - smooth(lt / 1.0)
        rem = sc.t1 - sc.t0 - lt
        if (nxt is None or nxt.transition in ("fade", "iris", "wipe")) and rem < 0.45:
            a = max(a, 1 - smooth(rem / 0.45))
        if a > 0:
            if sc.transition in ("iris", "wipe") and lt < 0.55:
                r = 1150 * smooth(lt / 0.55)
                p = skia.Path()
                p.setFillType(skia.PathFillType.kEvenOdd)
                p.addRect(skia.Rect(0, 0, W, H))
                p.addCircle(W / 2, H / 2, r)
                c.drawPath(p, paint("#05030f"))
            else:
                c.drawPaint(paint("#05030f", a))


# ============================================================== параллельный рендер
_EP = None


def _worker(args):
    i, f0, f1, out, scale = args
    r = Renderer(_EP, scale)
    w, h = int(W * scale), int(H * scale)
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}", "-r", str(FPS),
           "-i", "-", "-c:v", "libx264", "-preset", "medium" if scale >= 1 else "veryfast", "-crf", "17" if scale >= 1 else "26",
           "-pix_fmt", "yuv420p", "-threads", "1", out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in range(f0, f1):
        p.stdin.write(r.frame(f / FPS).tobytes())
    p.stdin.close()
    p.wait()
    return i


def render_video(ep: Episode, out: Path, workers=4, scale=1.0, t0=0.0, t1=None, progress=print):
    global _EP
    _EP = ep
    t1 = ep.duration if t1 is None else t1
    F0, F1 = int(t0 * FPS), int(t1 * FPS)
    seg = out.parent / "_segments"
    seg.mkdir(parents=True, exist_ok=True)
    n = max(workers * 6, 1)
    step = math.ceil((F1 - F0) / n)
    jobs = [(i, F0 + i * step, min(F1, F0 + (i + 1) * step), str(seg / f"seg_{i:03d}.mp4"), scale)
            for i in range(n) if F0 + i * step < F1]
    ctx = mp.get_context("fork")
    with ctx.Pool(workers) as pool:
        for k, i in enumerate(pool.imap_unordered(_worker, jobs)):
            progress(f"  сегмент {k + 1}/{len(jobs)}")
    lst = seg / "list.txt"
    lst.write_text("".join(f"file '{j[3]}'\n" for j in jobs))
    silent = out.with_suffix(".video.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(silent)],
                   check=True)
    for j in jobs:
        os.remove(j[3])
    return silent
