"""Built-in alarm ringtones (generated WAV, no external assets required)."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path


RINGTONES = [
    ("beep", "经典哔哔"),
    ("chime", "清脆钟声"),
    ("urgent", "急促提醒"),
    ("soft", "柔和提示"),
    ("digital", "电子音"),
]


def sounds_dir() -> Path:
    base = Path(__file__).resolve().parent / "assets" / "sounds"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _write_wav(path: Path, samples: list[float], rate: int = 22050) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        for s in samples:
            v = max(-1.0, min(1.0, s))
            w.writeframes(struct.pack("<h", int(v * 30000)))


def _tone(freq: float, dur: float, rate: int = 22050, vol: float = 0.5) -> list[float]:
    n = int(rate * dur)
    out = []
    for i in range(n):
        t = i / rate
        env = min(1.0, i / (rate * 0.02)) * min(1.0, (n - i) / (rate * 0.05))
        out.append(math.sin(2 * math.pi * freq * t) * vol * env)
    return out


def ensure_ringtones() -> dict[str, Path]:
    """Generate default ringtones if missing. Returns id -> path."""
    d = sounds_dir()
    paths: dict[str, Path] = {}
    specs = {
        "beep": lambda: _tone(880, 0.18) + [0.0] * 2000 + _tone(880, 0.18) + [0.0] * 2000 + _tone(880, 0.25),
        "chime": lambda: _tone(523, 0.25, vol=0.45)
        + _tone(659, 0.25, vol=0.4)
        + _tone(784, 0.35, vol=0.35)
        + _tone(1046, 0.5, vol=0.3),
        "urgent": lambda: sum(
            (_tone(1200, 0.1, vol=0.55) + [0.0] * 800 for _ in range(5)),
            [],
        ),
        "soft": lambda: _tone(440, 0.4, vol=0.25) + _tone(554, 0.5, vol=0.2) + _tone(659, 0.6, vol=0.18),
        "digital": lambda: sum(
            (_tone(f, 0.12, vol=0.4) + [0.0] * 600 for f in (600, 800, 1000, 800, 600)),
            [],
        ),
    }
    for rid, gen in specs.items():
        p = d / f"{rid}.wav"
        if not p.exists() or p.stat().st_size < 100:
            _write_wav(p, gen())
        paths[rid] = p
    return paths


def play_ringtone(ringtone_id: str = "beep", *, async_play: bool = True) -> None:
    paths = ensure_ringtones()
    path = paths.get(ringtone_id) or paths.get("beep")
    if path is None or not path.exists():
        return
    try:
        import winsound

        flags = winsound.SND_FILENAME
        if async_play:
            flags |= winsound.SND_ASYNC
        winsound.PlaySound(str(path), flags)
    except Exception as exc:
        print(f"ringtone play failed: {exc}", flush=True)


def stop_ringtone() -> None:
    try:
        import winsound

        winsound.PlaySound(None, winsound.SND_PURGE)
    except Exception:
        pass
