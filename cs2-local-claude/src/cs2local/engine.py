"""Licht-Motor: setzt Zustände pro Bild zu Farben zusammen und schickt sie an die RGB-Engine."""
from __future__ import annotations

import logging
import threading
import time

from .effects import blend, render, scale

log = logging.getLogger(__name__)

BOMB_TIMER = 40.0  # Sekunden bis zur Explosion in CS2


def state_color(cfg: dict, states: dict, team: str | None) -> tuple:
    """Endfarbe eines Zustands: eigene Farbe oder Teamfarbe, mal Helligkeit des Zustands."""
    if cfg.get("team_color"):
        base = states["team_t" if team == "T" else "team_ct"]["color"]
    else:
        base = cfg["color"]
    return scale(base, max(0, min(100, float(cfg.get("intensity", 100)))) / 100.0)


class LightEngine:
    def __init__(self, rgb, detector, get_settings):
        self.rgb = rgb
        self.detector = detector
        self.get_settings = get_settings
        self.running = False
        self._preview: tuple | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.status = {"top": None, "color": (0, 0, 0), "error": None}

    # ------------------------------------------------------------- Steuerung
    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        self.status["error"] = None
        self.running = True
        self._ensure_thread()

    def stop(self, wait: bool = False) -> None:
        self.running = False
        self._preview = None
        if wait and self._thread:
            self._thread.join(timeout=3.0)

    def preview(self, sid: str, seconds: float = 3.0) -> None:
        now = time.monotonic()
        self._preview = (sid, now, now + seconds)
        self._ensure_thread()

    def _ensure_thread(self) -> None:
        with self._lock:
            if not self.busy:
                self._thread = threading.Thread(target=self._loop, name="light-engine", daemon=True)
                self._thread.start()

    # ------------------------------------------------------------- Berechnung
    def layers(self, now: float, settings: dict, preview=None) -> list:
        states = settings["states"]
        team = self.detector.team
        if preview:
            sid, start, _ = preview
            snap = {sid: (now - start, 1.0)}
        else:
            snap = self.detector.snapshot(now, states)
        out = []
        for sid in sorted(snap, key=lambda s: states.get(s, {}).get("priority", 0)):
            cfg = states.get(sid)
            if not cfg or (not cfg.get("enabled") and not preview):
                continue
            age, alpha = snap[sid]
            t = age
            if sid == "bomb_planted":  # Blinken wird bis zur Explosion 4x schneller
                a = min(age, BOMB_TIMER + 5)
                t = a + 1.5 * a * a / BOMB_TIMER
            out.append((cfg, state_color(cfg, states, team), t, alpha))
        return out

    @staticmethod
    def compose(layers, n: int, brightness: float) -> list:
        frame = [(0, 0, 0)] * n
        start = 0
        for i, layer in enumerate(layers):  # ab der obersten deckenden Ebene rechnen
            if layer[3] >= 1.0:
                start = i
        for cfg, color, t, alpha in layers[start:]:
            cols = render(cfg["effect"], color, cfg.get("speed", 1.0), t, n, cfg.get("duration", 0))
            frame = [blend(b, c, alpha) for b, c in zip(frame, cols)]
        if brightness < 1.0:
            frame = [scale(c, brightness) for c in frame]
        return frame

    def _frame(self, now: float, prepared: set, preview) -> None:
        settings = self.get_settings()
        opts = settings["options"]
        keys = list(settings["devices"])
        new = [k for k in keys if k not in prepared]
        if new:
            self.rgb.prepare(new)
            prepared.update(new)
        layers = self.layers(now, settings, preview)
        brightness = max(0.0, min(1.0, float(opts.get("brightness", 100)) / 100.0))
        for key in keys:
            n = self.rgb.led_count(key)
            if n:
                self.rgb.set_zone(key, self.compose(layers, n, brightness))
        top = layers[-1][0]["name"] if layers else None
        self.status = {"top": top, "color": self.compose(layers, 1, brightness)[0], "error": None}

    def _loop(self) -> None:
        prepared: set = set()
        failures = 0
        try:
            while True:
                now = time.monotonic()
                preview = self._preview if self._preview and now < self._preview[2] else None
                if not self.running and not preview:
                    break
                try:
                    self._frame(now, prepared, preview)
                    failures = 0
                except (ConnectionError, OSError) as exc:  # Verbindung weg: neu verbinden statt aufgeben
                    failures += 1
                    log.warning("Verbindung zur RGB-Engine unterbrochen (%s), Versuch %d", exc, failures)
                    if failures > 5:
                        raise
                    self.status = {"top": "Verbinde neu …", "color": (0, 0, 0), "error": None}
                    time.sleep(min(5.0, 0.5 * failures))
                    self.rgb.reconnect()
                    prepared.clear()
                    continue
                fps = max(5, min(60, int(self.get_settings()["options"].get("fps", 20))))
                time.sleep(max(0.0, 1.0 / fps - (time.monotonic() - now)))
        except Exception as exc:  # noqa: BLE001
            log.exception("Licht-Motor gestoppt")
            self.status = {"top": None, "color": (0, 0, 0), "error": str(exc)}
            self.running = False
        finally:
            if prepared:
                try:
                    self.rgb.restore()
                except Exception:  # noqa: BLE001
                    log.exception("Wiederherstellen fehlgeschlagen")
            self.status["top"] = None
