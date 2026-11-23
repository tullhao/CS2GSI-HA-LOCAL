"""Lichteffekte: berechnen pro Bild die Farben für alle LEDs einer Zone."""
from __future__ import annotations

import bisect
import math
import random

Color = tuple  # (r, g, b)


def _clamp(v: float) -> int:
    return max(0, min(255, int(round(v))))


def scale(color, f: float) -> Color:
    return (_clamp(color[0] * f), _clamp(color[1] * f), _clamp(color[2] * f))


def blend(base: Color, top: Color, alpha: float) -> Color:
    if alpha >= 1.0:
        return top
    if alpha <= 0.0:
        return base
    return tuple(_clamp(b + (t - b) * alpha) for b, t in zip(base, top))


def _noise(x: float) -> float:
    i = int(math.floor(x))
    frac = x - i
    a = random.Random(i).random()
    b = random.Random(i + 1).random()
    return a + (b - a) * frac


C4_TIMER = 40.0  # Sekunden von „gelegt“ bis zur Explosion (Wettkampf/Premier)


def c4_beeps(timer: float = C4_TIMER) -> list:
    """Zeitpunkte der Pieptöne nach dem Legen.

    Wie im Spielcode (planted_c4, C4Think): nach jedem Piep kommt der nächste nach
    max(0.15, 0.1 + 0.9 * Restzeit / Timer) Sekunden – anfangs 1 pro Sekunde, am Ende ~7 pro Sekunde.
    """
    beeps, b = [0.0], 0.0
    while True:
        b += max(0.15, 0.1 + 0.9 * max(0.0, timer - b) / timer)
        if b >= timer:
            return beeps
        beeps.append(b)


_C4_BEEPS = c4_beeps()


def c4_level(t: float) -> float:
    """Helligkeit im Piep-Takt: bei jedem Piep kurz voll, dann schnell abklingen, dazwischen fast dunkel."""
    if t < 0:
        return 0.0
    if t >= C4_TIMER:
        return 1.0
    since = t - _C4_BEEPS[bisect.bisect_right(_C4_BEEPS, t) - 1]
    if since < 0.07:
        return 1.0
    return max(0.06, 1.0 - (since - 0.07) / 0.12)


def render(effect: str, color, speed: float, t: float, n: int, duration: float = 0.0) -> list:
    """Farben für n LEDs. t = Sekunden seit Beginn des Zustands, speed = Wiederholungen pro Sekunde."""
    if n <= 0:
        return []
    speed = max(0.05, float(speed or 1.0))
    if effect in ("chase", "spin"):  # spin: kurzer Schweif, die Engine rechnet ihn pro Lüfter
        pos = (t * speed * n) % n
        width = max(1.5, n / (3.0 if effect == "spin" else 5.0))
        out = []
        for i in range(n):
            d = abs(i - pos)
            d = min(d, n - d)
            out.append(scale(color, max(0.08, 1.0 - d / width)))
        return out
    if effect == "c4":  # t = Sekunden seit dem Legen der Bombe
        f = c4_level(t)
    elif effect == "blink":
        f = 1.0 if (t * speed) % 1.0 < 0.5 else 0.0
    elif effect == "pulse":
        f = 0.05 + 0.95 * (0.5 - 0.5 * math.cos(2 * math.pi * t * speed))
    elif effect == "flicker":
        f = 0.35 + 0.65 * _noise(t * speed)
    elif effect == "flash":  # erst voll halten, dann ausblenden
        length = duration if duration and duration > 0 else 2.5
        hold = length * 0.27
        f = 1.0 if t <= hold else max(0.0, 1.0 - (t - hold) / max(0.01, length - hold))
    elif effect == "fade":
        length = duration if duration and duration > 0 else 1.0 / speed
        f = max(0.0, 1.0 - t / length)
    else:  # solid
        f = 1.0
    return [scale(color, f)] * n


def render_segmented(effect: str, color, speed: float, t: float, n: int, duration: float = 0.0, seg: int = 0) -> list:
    """Wie render(), aber „Drehen“ läuft in jedem Lüfter (Abschnitt von seg LEDs) einzeln im Kreis."""
    if effect == "spin" and 0 < seg < n:
        ring = render(effect, color, speed, t, seg, duration)
        return [ring[i % seg] for i in range(n)]
    return render(effect, color, speed, t, n, duration)
