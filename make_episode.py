"""PIXEL PINES — сборка эпизода одной командой.

  python make_episode.py episodes/ep101.yaml            # полный 1080p
  python make_episode.py episodes/ep101.yaml --preview  # черновик 960×540
  python make_episode.py episodes/ep101.yaml --audio-only
  python make_episode.py episodes/ep101.yaml --stills 10 95 300   # контрольные кадры
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from studio import extras  # noqa: E402
from studio.episode import load  # noqa: E402
from studio.mix import build  # noqa: E402
from studio.render import Renderer, render_video  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("episode")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--audio-only", action="store_true")
    ap.add_argument("--stills", nargs="*", type=float)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--range", nargs=2, type=float)
    a = ap.parse_args()
    t = time.time()
    ep = load(a.episode)
    eid = ep.meta["id"]
    out = ROOT / "output" / eid
    out.mkdir(parents=True, exist_ok=True)
    adir = ROOT / "audio" / eid
    print(f"{ep.meta['series']} — {ep.meta['title']}: {int(ep.duration // 60)}:{ep.duration % 60:04.1f}, "
          f"{len(ep.lines)} реплик, {sum(len(s.shots) for s in ep.scenes)} планов")
    if a.stills is not None:
        extras.stills(ep, Renderer(ep, 1.0), a.stills, out / "qc")
        return
    mix = build(ep, adir)
    print(f"звук: {mix}")
    extras.subtitles(ep, out / "subtitles_en.srt")
    if a.audio_only:
        return
    scale = 0.5 if a.preview else 1.0
    t0, t1 = (a.range if a.range else (0.0, None))
    silent = render_video(ep, out / f"{eid}.mp4", a.workers, scale, t0, t1)
    name = out / (f"pixel_pines_{eid}{'_preview' if a.preview else ''}.mp4")
    ss = ["-ss", str(t0)] if t0 else []
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(silent), *ss, "-i", str(mix), "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(name)],
                   check=True)
    silent.unlink()
    print(f"видео: {name}")
    if not a.preview and not a.range:
        extras.package(ep, Renderer(ep, 1.0), out, name)
    print(f"готово за {(time.time() - t) / 60:.1f} мин")


if __name__ == "__main__":
    main()
