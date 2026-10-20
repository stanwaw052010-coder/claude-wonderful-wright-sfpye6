"""Материалы к эпизоду: субтитры, превью, описание, главы, QC."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import skia

from .util import FPS


def _ts(t):
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")


def subtitles(ep, path: Path):
    rows = []
    for i, (a, b, who, text) in enumerate(ep.subs, 1):
        rows.append(f"{i}\n{_ts(a)} --> {_ts(b + 0.15)}\n{text}\n")
    path.write_text("\n".join(rows))


def save(arr, path):
    skia.Image.fromarray(arr).save(str(path))


def stills(ep, r, times, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    for t in times:
        save(r.frame(t), out / f"still_{t:07.2f}.png")
        print(out / f"still_{t:07.2f}.png")


def thumbnail(ep, path: Path):
    """1280×720: герои слева, загадка в светящемся проёме по центру, логотип справа, город внизу."""
    from . import fx, inserts, sets
    from .characters import State, draw_character
    from .draw import Light, glow, lin_grad, paint, rrect, text
    from .util import font
    W_, H_ = 1920, 1080
    arr = np.zeros((H_, W_, 4), np.uint8)
    surf = skia.Surface(arr)
    c = surf.getCanvas()
    S = sets.build("lookout", "night")
    d, im = S.layers[0]
    c.drawImageRect(im, skia.Rect(900 * sets.SS, 60 * sets.SS, 2820 * sets.SS, 1140 * sets.SS), skia.Rect(0, 0, W_, H_),
                    skia.SamplingOptions(skia.FilterMode.kLinear, skia.MipmapMode.kLinear), None)
    d, im = S.layers[1]
    c.drawImageRect(im, skia.Rect(1500 * sets.SS, 500 * sets.SS, 2800 * sets.SS, 900 * sets.SS), skia.Rect(1000, 640, W_, 1080),
                    skia.SamplingOptions(skia.FilterMode.kLinear, skia.MipmapMode.kLinear), None)
    # светящийся проём с Почтальоном
    dx, dy, dw, dh = 760, 60, 360, 640
    glow(c, dx + dw / 2, dy + dh / 2, 520, "#3a8cff", 0.55)
    c.drawPath(rrect(dx, dy, dw, dh, 8), paint(None, shader=lin_grad((0, dy), (0, dy + dh), ["#bfe6ff", "#3a8cff", "#1a3a9a"])))
    c.drawPath(rrect(dx - 14, dy - 14, dw + 28, dh + 14, 8), paint("#0a1030", stroke=22))
    c.save()
    c.translate(dx + dw / 2, dy + dh - 20)
    c.scale(3.0, 3.0)
    sil = Light(rim="#bfe6ff", rim_alpha=0.9, outline="#050818")
    c.saveLayer(None, skia.Paint(ColorFilter=skia.ColorFilters.Matrix([0.25, 0, 0, 0, 0, 0, 0.3, 0, 0, 0, 0, 0, 0.5, 0, 0.02,
                                                                       0, 0, 0, 1, 0])))
    draw_character(c, "courier", State(t=2.0, pose="hold", prop="letter"), sil)
    c.restore()
    c.restore()
    glow(c, dx + dw / 2 + 12, dy + dh - 20 - 168 * 3, 60, "#fff2b0", 0.9)
    # герои
    warm = Light(key=(0.3, 0.9), rim="#7cc8ff", rim_dir=(-0.8, -0.4), rim_alpha=0.75, outline="#1a1430")
    for who, x, y, sc_, st in (
            ("june", 260, 1190, 6.8, State(t=1, expr="awe", facing=1, look=(0.6, -0.5))),
            ("dot", 1180, 1240, 6.4, State(t=2, expr="scared", facing=-1, pose="hold", prop="sniffer", look=(-0.4, -0.6))),
            ("theo", 640, 1300, 8.6, State(t=3, expr="surprised", facing=1, pose="hold", prop="letter", look=(0.7, -0.4))),
            ("biscuit", 120, 1110, 7.0, State(t=4, expr="surprised", facing=1))):
        c.save()
        c.translate(x, y)
        c.scale(sc_ * st.facing, sc_)
        draw_character(c, who, st, warm)
        c.restore()
    glow(c, 760, 840, 260, "#6ff2ff", 0.45)
    fx.vignette(c, 0.45)
    inserts.logo(c, 1500, 330, 0.86, reveal=1.0, t=1.0)
    f = font("logo", 66)
    text(c, "THE LETTER", 1500, 760, f, "#ffffff", align="center", stroke=16, stroke_color="#0d0a24")
    text(c, "FROM TOMORROW", 1500, 840, f, "#6ff2ff", align="center", stroke=16, stroke_color="#0d0a24")
    img = surf.makeImageSnapshot().resize(1280, 720, skia.SamplingOptions(skia.FilterMode.kLinear, skia.MipmapMode.kLinear))
    img.save(str(path))


def chapters(ep):
    names = {"s01": "Cold Open: The Night Courier", "s02": "A Letter Arrives", "s03": "From Me. From Saturday.",
             "s04": "Glitch Sniffer Mark Seven", "s045": "The Legend of Ada Lumen", "s05": "The Lumen Mill",
             "s06": "The Lantern", "s07": "Saturday", "s08": "Next Time"}
    rows = []
    for sc in ep.scenes:
        t = 0 if sc.sid == "s01" else sc.t0
        rows.append(f"{int(t // 60)}:{int(t % 60):02d} {names.get(sc.sid, sc.sid)}")
    return rows


def metadata(ep, path: Path):
    ch = "\n".join(chapters(ep))
    v = ep.meta["voices"]
    txt = f"""# Pixel Pines — S1E1 «{ep.meta['title']}» — материалы для YouTube

## Заголовок (варианты, ≤ 60 символов)
1. The Letter from Tomorrow | Pixel Pines Episode 1
2. A Letter From the Future?! | Pixel Pines (Full Episode)
3. Pixel Pines: The Letter from Tomorrow — Full Episode

## Описание (вставить как есть)
Theo Bramble finds a letter in his own handwriting… postmarked three days from now.
"Don't let them turn off the Lantern."
With his best friend June, inventor Dot and Biscuit — a dog who talks through a translator
collar — Theo has until Saturday to find out what the old Lantern is really keeping safe.

Pixel Pines — Small Town. Big Mysteries.
A new animated adventure series for kids and families. New episodes every other week.

CHAPTERS
{ch}

Made by the Pixel Pines studio team with AI-assisted tools: character voices generated with
ElevenLabs; animation, backgrounds, music and sound design produced in code.
All characters and events are fictional.

## Теги
pixel pines, cartoon for kids, animated series, kids cartoon full episode, mystery cartoon,
family cartoon, adventure cartoon, original animation, cartoon episode 1, kids mystery

## Настройки при загрузке (вручную)
* Audience: **Yes, it's made for kids** (аудитория 7–12, COPPA).
* Altered or synthetic content: **No** — контент стилизованный/анимационный, не реалистичный
  (сверить с текущей формулировкой YouTube Studio).
* Субтитры: загрузить `subtitles_en.srt` (English).
* Превью: `thumbnail.png`.
* Категория: Film & Animation. Язык: English (United States).
* Публикация — вручную; автопубликации нет.

## Важно про лицензию голосов
Ключ ElevenLabs на **бесплатном** тарифе: по условиям ElevenLabs бесплатный план не даёт
коммерческой лицензии и требует указания авторства. Для монетизации канала нужен платный
план (Starter или выше) — после перехода озвучку можно не перегенерировать, если условия
это позволяют; иначе пересоберите эпизод (ответы кэшируются, текст тот же).

## Голоса
""" + "\n".join(f"* {k}: ElevenLabs «{c['name']}» ({c['voice']})" for k, c in v.items()) + """

## Шрифты
Luckiest Guy (Apache 2.0), Fredoka, Caveat, Patrick Hand, Baloo 2 (SIL OFL) — Google Fonts.
"""
    path.write_text(txt)


def qc(video: Path, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    pr = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)],
                                   capture_output=True, text=True).stdout)
    dur = float(pr["format"]["duration"])
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video), "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    import re
    I = re.findall(r"I:\s+(-?[\d.]+) LUFS", r)
    tp = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", r)
    # контактный лист
    n = 16
    tiles = []
    for i in range(n):
        t = dur * (i + 0.5) / n
        f = out / f"frame_{i:02d}.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                        "-vf", "scale=480:270", str(f)], check=True)
        tiles.append(f)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(out / "frame_%02d.png"), "-vf", "tile=4x4", "-frames:v", "1",
                    str(out / "contact_sheet.jpg")], check=True)
    for f in tiles:
        f.unlink()
    v = [s for s in pr["streams"] if s["codec_type"] == "video"][0]
    a = [s for s in pr["streams"] if s["codec_type"] == "audio"][0]
    rep = f"""# QC — {video.name}
* Длительность: {int(dur // 60)}:{dur % 60:04.1f}
* Видео: {v['codec_name']} {v['width']}×{v['height']} {v['r_frame_rate']} fps, {v.get('pix_fmt')}
* Звук: {a['codec_name']} {a['sample_rate']} Hz, {a['channels']} ch
* Громкость: {I[-1] if I else '?'} LUFS (цель −14), true peak {tp[-1] if tp else '?'} dBFS (цель ≤ −1)
* Размер: {int(pr['format']['size']) / 1e6:.0f} МБ
* Контактный лист: qc/contact_sheet.jpg
"""
    (out / "qc_report.md").write_text(rep)
    return rep


def package(ep, r, out, video):
    thumbnail(ep, out / "thumbnail.png")
    metadata(ep, out / "youtube.md")
    print(qc(video, out / "qc"))
