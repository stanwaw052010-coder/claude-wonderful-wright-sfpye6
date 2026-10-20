"""Сценарий (YAML) → таймлайн: дорожки персонажей, реплики, планы камеры, звуки, эффекты.

Правила битов:
  say   — реплика; длительность = голос + пауза. expr/pose/prop применяются к говорящему.
          Жестовые позы (talk, point, …) после реплики возвращаются к базовой позе.
  wait  — пауза.
  act   — мгновенные изменения (move/enter — асинхронные, идут параллельно дальше).
  cam   — явный план; держится до следующего cam или до конца первой реплики, начавшейся
          в течение 1.5 с после него. Остальное время планы выбирает режиссёр.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import yaml

from .characters import HEIGHTS, State
from .util import FPS, ROOT, clamp, ease_io, hash01, lerp, smooth
from .voices import SR, Line, synth_all

GAP = 0.32               # пауза после реплики
TRANSIENT = {"talk", "talk2", "point", "point_up", "shrug", "fist", "cheer", "arms_up", "wave", "camera", "think"}
HOLDING = {"hold", "flashlight", "write", "hips"}
TITLE_DUR = 17.0


@dataclass
class Track:
    who: str
    x0: float
    facing: int
    events: list = field(default_factory=list)   # (t, attr, value)
    moves: list = field(default_factory=list)    # (t0, t1, xa, xb, run)
    jumps: list = field(default_factory=list)
    shakes: list = field(default_factory=list)   # (t0, dur)
    talks: list = field(default_factory=list)    # (t0, Line)
    bike: bool = False
    z: int = 0

    def value(self, attr, t, default=None):
        """Значение атрибута на момент t, время его установки и предыдущее значение."""
        lst = sorted((e for e in self.events if e[1] == attr), key=lambda e: e[0])
        v, vt, prev = default, -1e9, default
        for (et, _, val) in lst:
            if et > t:
                break
            prev, v, vt = v, val, et
        return v, vt, prev

    def x_at(self, t):
        x = self.x0
        walking, run = 0.0, False
        for (t0, t1, xa, xb, r) in self.moves:
            if t >= t1:
                x = xb
            elif t >= t0:
                k = (t - t0) / max(1e-3, t1 - t0)
                x = lerp(xa, xb, ease_io(k) * 0.25 + k * 0.75)
                walking = clamp(min(t - t0, t1 - t) / 0.18)
                run = r
        return x, walking, run


@dataclass
class Shot:
    t0: float
    t1: float
    kind: str                # wide | medium | close | insert | title | endcard
    on: list = field(default_factory=list)
    pan: tuple | None = None
    push: float = 0.03
    item: str = ""
    pan_dur: float = 0.0


@dataclass
class Scene:
    sid: str
    set: str
    light: str
    t0: float
    t1: float
    music: str
    ambience: str
    transition: str
    tracks: dict
    shots: list
    caption: str = ""
    fx: list = field(default_factory=list)
    data: dict = field(default_factory=dict)


@dataclass
class Episode:
    meta: dict
    scenes: list
    lines: list            # (t_abs, Line)
    sfx: list              # (t_abs, name)
    duration: float
    subs: list             # (t0, t1, who, text)


def _lipsync_frames(line: Line):
    """Для реплики: массив (open, wide, round) с шагом 1/FPS + огибающая громкости."""
    n = int(math.ceil(line.dur * FPS)) + 2
    vis = np.zeros((n, 3), np.float32)
    vis[:, 1] = 1.0
    table = {}
    for ch in "aA":
        table[ch] = (0.85, 1.05, 0.1)
    for ch in "eE":
        table[ch] = (0.55, 1.2, 0.0)
    for ch in "iIyY":
        table[ch] = (0.42, 1.25, 0.0)
    for ch in "oO":
        table[ch] = (0.75, 0.8, 0.9)
    for ch in "uU":
        table[ch] = (0.45, 0.65, 1.0)
    for ch in "wW":
        table[ch] = (0.3, 0.65, 0.95)
    for ch in "mbpMBP":
        table[ch] = (0.0, 0.95, 0.0)
    for ch in "fvFV":
        table[ch] = (0.15, 1.05, 0.0)
    for (ch, a, b) in line.chars:
        if not ch.strip() or not ch.isalpha():
            continue
        v = table.get(ch, (0.3, 1.0, 0.15))
        i0, i1 = int(a * FPS), max(int(a * FPS) + 1, int(b * FPS))
        for i in range(i0, min(i1 + 1, n)):
            vis[i] = v
    # сглаживание
    k = np.array([0.25, 0.5, 0.25])
    for j in range(3):
        vis[:, j] = np.convolve(vis[:, j], k, mode="same")
    # громкость
    hop = SR // FPS
    env = np.array([float(np.sqrt(np.mean(line.audio[i * hop:(i + 1) * hop] ** 2))) if i * hop < len(line.audio) else 0.0
                    for i in range(n)])
    env = env / (env.max() or 1.0)
    vis[:, 0] *= (0.35 + 0.85 * np.clip(env * 1.4, 0, 1))
    vis[env < 0.04, 0] = 0
    return vis, env


def load(path: str) -> Episode:
    d = yaml.safe_load(open(path))
    ep = d["id"]
    items = [(b["say"], b["text"]) for sc in d["scenes"] for b in sc["beats"] if "say" in b]
    lines = synth_all(ep, items, d["voices"])
    li = iter(lines)
    for L in lines:
        L.vis, L.env = _lipsync_frames(L)

    scenes, all_lines, sfx, subs = [], [], [], []
    T = 0.0
    for sc in d["scenes"]:
        tracks = {}
        for z, (who, c) in enumerate((sc.get("cast") or {}).items()):
            tr = Track(who, float(c.get("x", 0)), int(c.get("facing", 1)), z=z)
            tr.bike = bool(c.get("bike"))
            tr.events.append((-1, "visible", not c.get("hidden", False)))
            for a in ("expr", "pose", "prop"):
                if a in c:
                    tr.events.append((-1, a, c[a]))
            tr.events.append((-1, "base", c.get("pose", "idle")))
            tr.events.append((-1, "facing", tr.facing))
            tracks[who] = tr
        t = 0.0
        shots_explicit = []   # (t, spec)
        say_times = []        # (t0, t1, who, expr)
        fxs = []
        title_at = None
        line_idx = 0

        def ev(who, at, attr, val):
            tracks[who].events.append((at, attr, val))

        for b in sc["beats"]:
            if "wait" in b:
                t += float(b["wait"])
            elif "cam" in b:
                shots_explicit.append((t, b["cam"]))
            elif "sfx" in b:
                sfx.append((T + t, b["sfx"]))
            elif "fx" in b:
                fxs.append((t, b["fx"]))
            elif "title" in b:
                title_at = t
                t += TITLE_DUR
            elif "say" in b:
                L = next(li)
                who = b["say"]
                if who in tracks:
                    tr = tracks[who]
                    for a in ("expr", "prop"):
                        if a in b:
                            ev(who, t, a, b[a])
                    base, _, _ = tr.value("base", t, "idle")
                    pose = b.get("pose")
                    if pose is None and base == "idle" and who not in ("biscuit", "courier"):
                        pose = ("talk", "talk2", "idle")[line_idx % 3]
                    if pose:
                        ev(who, t, "pose", pose)
                        if pose in TRANSIENT:
                            ev(who, t + L.dur + 0.25, "pose", base if base in HOLDING or base == "idle" else "idle")
                        else:
                            ev(who, t, "base", pose)
                    tr.talks.append((t, L))
                    if b.get("glitch"):
                        ev(who, t, "glitch", True)
                        ev(who, t + L.dur, "glitch", False)
                all_lines.append((T + t, L, b.get("vo", False)))
                subs.append((T + t, T + t + L.dur, who, L.clean))
                say_times.append((t, t + L.dur, who, b.get("expr", "")))
                line_idx += 1
                t += L.dur + GAP
            elif "act" in b:
                whos = b["act"] if isinstance(b["act"], list) else [b["act"]]
                for who in whos:
                    if who not in tracks:
                        tracks[who] = Track(who, 0.0, 1, z=len(tracks))
                        tracks[who].events.append((-1, "visible", False))
                    tr = tracks[who]
                    for a in ("expr", "prop", "look", "extra_spin"):
                        if a in b:
                            ev(who, t, a, b[a])
                    if "pose" in b:
                        ev(who, t, "pose", b["pose"])
                        ev(who, t, "base", b["pose"])
                    if "move" in b:
                        x, _, _ = tr.x_at(t)
                        dur = float(b.get("dur", abs(b["move"] - x) / 300))
                        tr.moves.append((t, t + dur, x, float(b["move"]), bool(b.get("run"))))
                        ev(who, t, "facing", 1 if b["move"] > x else -1)
                    if "enter" in b:
                        e = b["enter"]
                        ev(who, t, "visible", True)
                        tr.x0 = float(e["from"]) if not tr.moves else tr.x0
                        tr.moves.append((t, t + float(e["dur"]), float(e["from"]), float(e["to"]), False))
                        ev(who, t, "facing", 1 if e["to"] > e["from"] else -1)
                        if e.get("bike"):
                            ev(who, t, "bike", True)
                            ev(who, t + float(e["dur"]) + 0.15, "bike", False)
                    if b.get("vanish"):
                        ev(who, t, "visible", False)
                    if b.get("appear"):
                        ev(who, t, "visible", True)
                    if "appear_at" in b:
                        tr.moves.append((t, t + 0.001, float(b["appear_at"]), float(b["appear_at"]), False))
                        ev(who, t, "visible", True)
                    if b.get("jump"):
                        tr.jumps.append(t)
                    if "shake" in b:
                        tr.shakes.append((t, float(b["shake"])))
            elif "end_card" in b:
                pass
        dur = t
        shots = direct(sc, tracks, shots_explicit, say_times, dur, title_at)
        S = Scene(sc["id"], sc["set"], sc.get("light", "night"), T, T + dur, sc.get("music", ""), sc.get("ambience", ""),
                  sc.get("transition", "cut"), tracks, shots, caption=sc.get("caption", ""), fx=fxs)
        S.data["title_at"] = title_at
        scenes.append(S)
        T += dur
    meta = {k: d[k] for k in ("id", "series", "title", "logline") if k in d}
    meta["voices"] = d["voices"]
    return Episode(meta, scenes, all_lines, sfx, T, subs)


# ======================================================================= режиссёр
EMO = {"surprised", "scared", "awe", "excited", "worried", "sly", "proud", "sad", "grin"}


def direct(sc, tracks, explicit, says, dur, title_at):
    """Расставляет планы. Возвращает список Shot, покрывающий [0, dur]."""
    if sc["set"] == "end_card":
        return [Shot(0, dur, "endcard")]
    cuts = []  # (t, Shot-proto)
    # явные планы
    exp_spans = []
    for i, (t, spec) in enumerate(explicit):
        t_end = explicit[i + 1][0] if i + 1 < len(explicit) else dur
        # реплика, начавшаяся в пределах 1.5 с, «поглощается» этим планом
        for (s0, s1, who, _) in says:
            if s0 >= t - 1e-6:
                if s0 - t <= 1.5:
                    t_end = min(t_end, s1 + 0.25)
                else:
                    t_end = min(t_end, s0 - 0.12)
                break
        kind = spec.get("shot", "wide")
        on = spec.get("on", [])
        on = on if isinstance(on, list) else [on]
        exp_spans.append(Shot(t, max(t + 0.5, t_end), kind, on=on, pan=tuple(spec["pan"]) if "pan" in spec else None,
                              push=float(spec.get("push", 0.03)), item=spec.get("item", ""),
                              pan_dur=float(spec.get("dur", 0))))
    if title_at is not None:
        exp_spans.append(Shot(title_at, title_at + TITLE_DUR, "title"))
    exp_spans.sort(key=lambda s: s.t0)

    def covered(t):
        return any(s.t0 - 1e-6 <= t < s.t1 for s in exp_spans)

    auto = []
    last_kind, run = "", 0
    for i, (s0, s1, who, expr) in enumerate(says):
        if covered(s0 + 0.05) or who not in tracks:
            continue
        L = s1 - s0
        prev_who = says[i - 1][2] if i else None
        if L > 5.0:
            kind = "medium"
        elif expr in EMO and L < 4.5:
            kind = "close"
        elif prev_who and prev_who != who and hash01(sc["id"], i) < 0.5:
            kind = "close"
        else:
            kind = "medium"
        if kind == last_kind:
            run += 1
            if run >= 2:
                kind = "medium" if kind == "close" else "close"
                run = 0
        else:
            run = 0
        if i and i % 7 == 0 and L > 2.2:
            kind = "wide"
        last_kind = kind
        partner = prev_who if (prev_who and prev_who != who and prev_who in tracks) else None
        on = [who] + ([partner] if partner and kind == "medium" else [])
        auto.append(Shot(max(0, s0 - 0.12), s1 + 0.2, kind, on=on))
    # склейка: явные важнее авто; пустоты — продлением предыдущего плана
    shots = sorted(exp_spans + auto, key=lambda s: s.t0)
    out = []
    for s in shots:
        if out and s.t0 < out[-1].t1:
            if out[-1].kind in ("insert", "title") or (out[-1] in exp_spans and s not in exp_spans):
                s.t0 = out[-1].t1
                if s.t0 >= s.t1 - 0.3:
                    continue
            else:
                out[-1].t1 = s.t0
        out.append(s)
    if not out or out[0].t0 > 0.01:
        first_end = out[0].t0 if out else dur
        out.insert(0, Shot(0, first_end, "wide"))
    # пустоты между планами — продлеваем предыдущий (кроме вставок — после них общий план)
    filled = []
    for i, s in enumerate(out):
        if filled and s.t0 > filled[-1].t1 + 1e-6:
            if filled[-1].kind in ("insert", "title") or s.t0 - filled[-1].t1 > 3.0:
                filled.append(Shot(filled[-1].t1, s.t0, "wide"))
            else:
                filled[-1].t1 = s.t0
        filled.append(s)
    if filled[-1].t1 < dur:
        if filled[-1].kind in ("insert", "title"):
            filled.append(Shot(filled[-1].t1, dur, "wide"))
        else:
            filled[-1].t1 = dur
    # слишком короткие планы — сливаем с предыдущим
    final = []
    for s in filled:
        if final and s.t1 - s.t0 < 0.7 and s.kind not in ("insert", "title"):
            final[-1].t1 = s.t1
            continue
        final.append(s)
    return final


# ======================================================================= состояние
def char_state(tr: Track, t: float, scene_t: float) -> tuple[State, dict]:
    st = State()
    st.t = scene_t + tr.z * 1.7
    x, walking, run = tr.x_at(t)
    st.x = x
    st.walking = walking
    st.run = run
    st.walk = (x / (22.0 if tr.who != "biscuit" else 14.0))
    vis, vt, _ = tr.value("visible", t, True)
    st.visible = vis
    fade = clamp((t - vt) / 0.35) if vt > -1 else 1.0
    st.alpha = fade if vis else 1.0 - fade
    if not vis and fade >= 1:
        st.visible = False
    else:
        st.visible = True
    f, _, _ = tr.value("facing", t, tr.facing)
    st.facing = f
    e, et, ep = tr.value("expr", t, "neutral")
    st.expr, st.expr_from = e or "neutral", ep or "neutral"
    st.expr_t = smooth((t - et) / 0.22) if et > -1 else 1.0
    p, pt, pp = tr.value("pose", t, "idle")
    st.pose, st.pose_from = p or "idle", pp or "idle"
    st.pose_t = smooth((t - pt) / 0.28) if pt > -1 else 1.0
    pr, _, _ = tr.value("prop", t, None)
    st.prop = pr
    lk, _, _ = tr.value("look", t, None)
    if lk:
        st.look = tuple(lk)
    sp, _, _ = tr.value("extra_spin", t, False)
    st.extra_spin = bool(sp)
    bk, _, _ = tr.value("bike", t, tr.bike)
    extra = {"bike": bool(bk), "glitch": tr.value("glitch", t, False)[0]}
    # моргание
    period = 3.1 + hash01(tr.who) * 1.6
    ph = (scene_t + hash01(tr.who, 1) * 5) % period
    st.blink = 1.0 if ph < 0.07 else (0.5 if ph < 0.12 else 0.0)
    # речь
    for (t0, L) in tr.talks:
        if t0 <= t < t0 + L.dur:
            i = int((t - t0) * FPS)
            v = L.vis[min(i, len(L.vis) - 1)]
            st.talk = (float(v[0]), float(v[1]), float(v[2]))
            st.amp = float(L.env[min(i, len(L.env) - 1)])
            break
    # дыхание
    st.bob = math.sin(st.t * 2.1) * 0.5
    for tj in tr.jumps:
        if tj <= t < tj + 0.5:
            k = (t - tj) / 0.5
            st.jump = math.sin(k * math.pi) * 16
            st.squash = -0.6 * math.sin(k * math.pi) if k < 0.9 else 0.5
    for (ts, d) in tr.shakes:
        if ts <= t < ts + d:
            st.x += math.sin((t - ts) * 60) * 3.0
            st.tilt = math.sin((t - ts) * 45) * 3
    if tr.who == "biscuit" and st.expr in ("happy", "grin", "excited"):
        st.wag = 1
    return st, extra


def height_px(who, S):
    return HEIGHTS[who] * S.scale
