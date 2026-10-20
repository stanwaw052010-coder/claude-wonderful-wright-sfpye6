"""Звуковые эффекты и атмосферы: ElevenLabs Sound Effects (кэш в audio/sfx_cache).

Если API недоступен — эффект заменяется тишиной, а сборка продолжается
(в отчёт пишется предупреждение).
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .util import ROOT
from .voices import SR, _decode

SFX = {
    "bike_bell": ("old brass bicycle bell, two bright rings", 1.6),
    "clock_chime": ("distant town clock tower bell chiming once at night, deep and gentle", 3.5),
    "shimmer": ("magical sparkle shimmer, soft twinkling chimes, cartoon magic", 1.8),
    "mailbox": ("metal mailbox door opening and closing with a soft clank", 1.2),
    "whoosh": ("soft magical whoosh disappearing with sparkles", 1.4),
    "dog_door": ("small pet door flap swinging", 0.9),
    "door": ("wooden front door opening, house, morning", 1.4),
    "paper": ("paper envelope opening and letter unfolding", 1.2),
    "camera_flash": ("vintage instant camera shutter click and flash whine, photo ejecting", 1.6),
    "bike_brakes": ("bicycle brakes squeak to a stop on pavement", 1.2),
    "gadget_whir": ("cartoon gadget powering up, whirring, rising beeps and boops", 2.0),
    "pop": ("cartoon pop with confetti burst, comedic", 1.0),
    "pop_small": ("small comedic cartoon pop", 0.6),
    "beeps": ("fast excited electronic beeping of a handheld scanner, cartoon", 1.6),
    "door_creak": ("old heavy wooden door creaking open slowly", 2.2),
    "power_down": ("magical light fading, power down hum descending", 2.0),
    "glitch": ("digital glitch stutter sound, cartoon, brief", 1.2),
    "gadget_charge": ("cartoon gadget charging up to a high whine then a bright zap", 2.4),
    "magic_swell": ("big warm magical swell, chimes and whoosh, light bursting, wonder", 4.0),
    "writing": ("pencil writing quickly on paper", 2.6),
    "boing": ("cartoon surprise jump boing", 0.8),
    "laugh_soft": ("soft cozy chuckle of a happy dog huffing", 1.0),
    "click": ("small plastic switch click", 0.5),
    "footsteps_grass": ("kids footsteps walking on grass and leaves", 3.0),
}

AMB = {
    "night_town": ("quiet small town at night, distant crickets, soft wind, faraway dog bark, calm", 12.0),
    "night_street": ("suburban street at night, crickets, gentle breeze in trees", 12.0),
    "morning_birds": ("autumn morning in a small town, birds chirping, light breeze, distant car", 12.0),
    "garage_hum": ("cozy garage workshop, soft electrical hum, distant birds outside", 12.0),
    "forest_evening": ("pine forest at dusk, gentle wind in pine trees, crickets starting, an owl far away", 12.0),
    "crickets": ("field of crickets at dusk near an old factory, light wind", 12.0),
    "mill_room": ("inside a large old empty brick building at night, quiet airy room tone, faint creaks", 12.0),
    "evening_wind": ("hilltop at sunset, gentle wind through grass, distant birds", 12.0),
}


def _gen(prompt, dur):
    cache = ROOT / "audio" / "sfx_cache"
    cache.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1(json.dumps([prompt, dur]).encode()).hexdigest()[:16]
    f = cache / f"{h}.mp3"
    if not f.exists():
        body = {"text": prompt, "duration_seconds": dur, "prompt_influence": 0.5}
        req = urllib.request.Request("https://api.elevenlabs.io/v1/sound-generation", data=json.dumps(body).encode(),
                                     method="POST", headers={"Content-Type": "application/json",
                                                             "xi-api-key": os.environ.get("ELEVENLABS_API_KEY", "")})
        with urllib.request.urlopen(req, timeout=180) as r:
            f.write_bytes(r.read())
    return _decode(f.read_bytes())


def load_all(names_sfx, names_amb, workers=3):
    out, warn = {}, []

    def job(item):
        kind, name = item
        prompt, dur = (SFX if kind == "sfx" else AMB)[name]
        try:
            a = _gen(prompt, dur)
        except Exception as e:  # noqa: BLE001 — сборка не должна падать из-за эффекта
            warn.append(f"{name}: {e}")
            a = np.zeros(int(SR * 0.2), np.float32)
        peak = float(np.max(np.abs(a))) or 1.0
        return name, (a / peak * 0.9).astype(np.float32)

    items = [("sfx", n) for n in names_sfx if n in SFX] + [("amb", n) for n in names_amb if n in AMB]
    with ThreadPoolExecutor(workers) as ex:
        for name, a in ex.map(job, items):
            out[name] = a
    return out, warn
