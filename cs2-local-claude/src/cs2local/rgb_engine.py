"""Eingebaute RGB-Engine: der OpenRGB-Kern läuft unsichtbar im Hintergrund und erkennt alle RGB-Geräte.

Der Kern wird in der EXE mitgeliefert (unverändert, GPL-2.0), nur für diese Sitzung gestartet und beim
Beenden wieder geschlossen. Gesteuert wird er über das offene OpenRGB-SDK-Protokoll.
"""
from __future__ import annotations

import atexit
import logging
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

from .config import OPENRGB_DIR

log = logging.getLogger(__name__)

try:
    from openrgb import OpenRGBClient, orgb
    from openrgb.utils import RGBColor

    # openrgb-python verwirft leds_min/leds_max einer Zone. Ohne diese Werte wüssten wir nicht,
    # bei welchen ARGB-Headern man die LED-Anzahl einstellen kann. Deshalb hier mitspeichern.
    if not getattr(orgb.Zone, "_cs2local_patched", False):
        _zone_update = orgb.Zone._update

        def _zone_update_with_limits(self, data):
            _zone_update(self, data)
            self.leds_min = getattr(data, "leds_min", 0)
            self.leds_max = getattr(data, "leds_max", 0)

        orgb.Zone._update = _zone_update_with_limits
        orgb.Zone._cs2local_patched = True
except ImportError:  # pragma: no cover
    OpenRGBClient = None  # type: ignore[assignment]
    RGBColor = None  # type: ignore[assignment]


class RGBEngineError(Exception):
    pass


class RGBEngine:
    def __init__(self, port: int = 6742):
        self.port = port
        self.client = None
        self.proc: subprocess.Popen | None = None
        self.lock = threading.RLock()
        self._zones: dict = {}   # "Gerät::Zone" -> (device, zone)
        self._saved: dict = {}   # Gerät -> (device, alter Modus, [(zone, alte Farben)])
        self._last: dict = {}
        atexit.register(self._kill)

    # ------------------------------------------------------------ Start/Stop
    @staticmethod
    def find_exe() -> Path | None:
        direct = OPENRGB_DIR / "OpenRGB.exe"
        if direct.exists():
            return direct
        if OPENRGB_DIR.is_dir():
            for found in OPENRGB_DIR.rglob("OpenRGB.exe"):
                return found
        return None

    def _port_open(self) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                return True
        except OSError:
            return False

    @property
    def started_by_us(self) -> bool:
        return self.proc is not None

    def start(self, zone_sizes: dict | None = None, progress=lambda msg: None) -> None:
        if OpenRGBClient is None:
            raise RGBEngineError("Die SDK-Bibliothek fehlt in diesem Build.")
        if self._port_open():
            progress("Eine laufende OpenRGB-Instanz wurde gefunden, verbinde …")
        else:
            exe = self.find_exe()
            if not exe:
                raise RGBEngineError("Die eingebaute RGB-Engine fehlt in diesem Build (OpenRGB.exe).")
            progress("Starte die RGB-Engine im Hintergrund …")
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            self.proc = subprocess.Popen(
                [str(exe), "--server", "--server-host", "127.0.0.1", "--server-port", str(self.port),
                 "--localconfig", "--noautoconnect"],
                cwd=str(exe.parent), creationflags=flags,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            )
            log.info("RGB-Engine gestartet (PID %s, %s)", self.proc.pid, exe)

        deadline = time.monotonic() + 60
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if self.proc and self.proc.poll() is not None:
                raise RGBEngineError(f"Die RGB-Engine wurde unerwartet beendet (Code {self.proc.returncode}). "
                                     "Details im Log.")
            try:
                self.client = OpenRGBClient("127.0.0.1", self.port, "CS2 Local Claude")
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(1.0)
        else:
            raise RGBEngineError(f"Keine Verbindung zur RGB-Engine möglich: {last_error}")

        progress("Suche RGB-Geräte (das dauert ein paar Sekunden) …")
        self._wait_for_devices()
        self._index()
        for key, size in (zone_sizes or {}).items():
            try:
                if key in self._zones and self.led_count(key) != size:
                    self.resize(key, size)
            except Exception:  # noqa: BLE001
                log.warning("Zonengrösse für %s nicht setzbar", key)
        log.info("RGB-Engine bereit: %d Zonen", len(self._zones))

    def _wait_for_devices(self, timeout: float = 30.0) -> None:
        """Wartet, bis die Geräteerkennung fertig ist (Anzahl Geräte bleibt stabil)."""
        deadline = time.monotonic() + timeout
        prev, stable = -1, 0
        while time.monotonic() < deadline:
            try:
                self.client.update()
            except Exception:  # noqa: BLE001
                pass
            count = len(self.client.devices)
            if count == prev and count > 0:
                stable += 1
                if stable >= 2:
                    return
            else:
                stable = 0
            prev = count
            time.sleep(1.5)

    def _index(self) -> None:
        self._zones.clear()
        seen: dict = {}
        for dev in self.client.devices:
            seen[dev.name] = seen.get(dev.name, 0) + 1
            name = dev.name if seen[dev.name] == 1 else f"{dev.name} #{seen[dev.name]}"
            for zone in dev.zones:
                self._zones[f"{name}::{zone.name}"] = (dev, zone)

    def refresh(self) -> None:
        with self.lock:
            self.client.update()
            self._index()
            self._last.clear()

    def _kill(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            log.info("RGB-Engine beendet")
        self.proc = None

    def shutdown(self) -> None:
        with self.lock:
            try:
                self.restore()
                if self.client:
                    self.client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self.client = None
        self._kill()

    # ------------------------------------------------------------ Geräte
    def zones(self) -> list:
        out = []
        for key, (dev, zone) in self._zones.items():
            lo = int(getattr(zone, "leds_min", 0) or 0)
            hi = int(getattr(zone, "leds_max", 0) or 0)
            dtype = getattr(getattr(dev, "type", None), "name", "") or "Gerät"
            out.append({
                "key": key,
                "device": key.split("::", 1)[0],
                "zone": zone.name,
                "type": dtype.replace("_", " ").title(),
                "leds": len(zone.leds),
                "resizable": hi > lo,
                "leds_min": lo,
                "leds_max": hi,
            })
        return out

    def led_count(self, key: str) -> int:
        pair = self._zones.get(key)
        return len(pair[1].leds) if pair else 0

    def resize(self, key: str, size: int) -> None:
        with self.lock:
            pair = self._zones.get(key)
            if not pair:
                return
            pair[1].resize(int(size))
            self.refresh()

    # ------------------------------------------------------------ Licht
    def prepare(self, keys) -> None:
        """Merkt sich den bisherigen Zustand und schaltet die Geräte auf Direktsteuerung."""
        with self.lock:
            for key in keys:
                pair = self._zones.get(key)
                if not pair:
                    continue
                dev = pair[0]
                did = getattr(dev, "id", id(dev))
                if did in self._saved:
                    continue
                self._saved[did] = (dev, dev.active_mode, [(z, list(z.colors)) for z in dev.zones])
                try:
                    dev.set_custom_mode()
                except Exception:  # noqa: BLE001
                    try:
                        dev.set_mode("direct")
                    except Exception:  # noqa: BLE001
                        log.warning("%s: kein Direktmodus", dev.name)

    def set_zone(self, key: str, colors: list) -> None:
        frame = tuple(colors)
        if self._last.get(key) == frame:
            return
        with self.lock:
            pair = self._zones.get(key)
            if not pair:
                return
            pair[1].set_colors([RGBColor(*c) for c in colors], fast=True)
        self._last[key] = frame

    def restore(self) -> None:
        """Stellt Modus und Farben wieder her, die vor dem Start aktiv waren."""
        with self.lock:
            for dev, mode, zones in self._saved.values():
                try:
                    dev.set_mode(mode)
                    for zone, cols in zones:
                        if cols:
                            zone.set_colors(cols, fast=True)
                except Exception:  # noqa: BLE001
                    log.warning("Zustand von %s nicht wiederherstellbar", getattr(dev, "name", "?"))
            self._saved.clear()
            self._last.clear()

    def test(self, keys) -> None:
        """Lässt die gewählten Zonen dreimal türkis aufblinken."""
        with self.lock:
            self.prepare(keys)
            for _ in range(3):
                for color in ((0, 255, 200), (0, 0, 0)):
                    for key in keys:
                        n = self.led_count(key)
                        if n:
                            self.set_zone(key, [color] * n)
                    time.sleep(0.35)
            self.restore()
