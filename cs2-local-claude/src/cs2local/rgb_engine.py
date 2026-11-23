"""Eingebaute RGB-Engine: der OpenRGB-Kern läuft unsichtbar im Hintergrund und erkennt alle RGB-Geräte.

Der Kern wird in der EXE mitgeliefert (unverändert, GPL-2.0), nur für diese Sitzung gestartet und beim
Beenden wieder geschlossen. Gesteuert wird er über das offene SDK-Protokoll (eigener Client in sdk_client.py).
Reisst die Verbindung ab, verbindet sich die Engine selbst neu und startet den Kern bei Bedarf neu.
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

from .config import OPENRGB_DIR, app_dir
from .sdk_client import COLOR_MODE_PER_LED, SDKClient, SDKError

log = logging.getLogger(__name__)

ENGINE_LOG = app_dir() / "cs2local_engine.log"


class RGBEngineError(Exception):
    pass


class RGBEngine:
    def __init__(self, port: int = 6742):
        self.port = port
        self.client: SDKClient | None = None
        self.proc: subprocess.Popen | None = None
        self.lock = threading.RLock()
        self.devices: list = []
        self._zones: dict = {}    # "Gerät::Zone" -> (Geräte-Schlüssel, Device, Zone)
        self._saved: dict = {}    # Geräte-Schlüssel -> (Modus, {Zonenindex: Farben})
        self._direct: set = set()  # Geräte im Direktmodus
        self._last: dict = {}
        self._log_handle = None
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

    @property
    def connected(self) -> bool:
        return self.client is not None and self.client.alive

    def _launch(self, progress) -> None:
        exe = self.find_exe()
        if not exe:
            raise RGBEngineError("Die eingebaute RGB-Engine fehlt in diesem Build (OpenRGB.exe).")
        progress("Starte die RGB-Engine im Hintergrund …")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            self._log_handle = open(ENGINE_LOG, "w", encoding="utf-8", errors="replace")  # noqa: SIM115
        except OSError:
            self._log_handle = None
        out = self._log_handle or subprocess.DEVNULL
        self.proc = subprocess.Popen(
            [str(exe), "--server", "--server-host", "127.0.0.1", "--server-port", str(self.port),
             "--localconfig", "--noautoconnect", "--loglevel", "warning", "-v"],
            cwd=str(exe.parent), creationflags=flags, stdout=out, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        log.info("RGB-Engine gestartet (PID %s)", self.proc.pid)

    def _connect(self, deadline: float) -> None:
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if self.proc and self.proc.poll() is not None:
                raise RGBEngineError(f"Die RGB-Engine wurde unerwartet beendet (Code {self.proc.returncode}). "
                                     f"Details: {ENGINE_LOG.name}")
            client = SDKClient("127.0.0.1", self.port)
            try:
                client.connect()
                self.client = client
                return
            except (OSError, SDKError) as exc:
                client.close()
                last_error = exc
                time.sleep(1.0)
        raise RGBEngineError(f"Keine Verbindung zur RGB-Engine möglich: {last_error}")

    def start(self, zone_sizes: dict | None = None, progress=lambda msg: None) -> None:
        with self.lock:
            if self._port_open():
                progress("Eine laufende OpenRGB-Instanz wurde gefunden, verbinde …")
            else:
                self._launch(progress)
            self._connect(time.monotonic() + 60)
            progress("Suche RGB-Geräte (das dauert ein paar Sekunden) …")
            self._wait_for_devices()
            for key, size in (zone_sizes or {}).items():
                try:
                    if key in self._zones and self.led_count(key) != size:
                        self.resize(key, size)
                except Exception:  # noqa: BLE001
                    log.warning("Zonengrösse für %s nicht setzbar", key)
            log.info("RGB-Engine bereit: %d Geräte, %d Zonen", len(self.devices), len(self._zones))
            for dev in self.devices:
                log.info("  %s (%s): %s | Modi: %s", dev.name, dev.type_name,
                         ", ".join(f"{z.name}[{z.leds_count}]" for z in dev.zones),
                         ", ".join(m.name for m in dev.modes))

    def _wait_for_devices(self, timeout: float = 30.0) -> None:
        """Wartet, bis die Geräteerkennung fertig ist (Anzahl Geräte bleibt stabil)."""
        deadline = time.monotonic() + timeout
        prev, stable = -1, 0
        while time.monotonic() < deadline:
            count = self.client.controller_count()
            if count == prev and count > 0:
                stable += 1
                if stable >= 2:
                    break
            else:
                stable = 0
            prev = count
            time.sleep(1.5)
        self._load_devices()

    def _load_devices(self) -> None:
        self.devices = self.client.devices()
        self._zones.clear()
        self._last.clear()
        seen: dict = {}
        for dev in self.devices:
            seen[dev.name] = seen.get(dev.name, 0) + 1
            dkey = dev.name if seen[dev.name] == 1 else f"{dev.name} #{seen[dev.name]}"
            for zone in dev.zones:
                self._zones[f"{dkey}::{zone.name}"] = (dkey, dev, zone)

    def refresh(self) -> None:
        with self.lock:
            self._load_devices()

    def reconnect(self) -> None:
        """Nach einem Verbindungsabriss: Kern bei Bedarf neu starten, neu verbinden, Geräte neu laden."""
        with self.lock:
            if self.client:
                self.client.close()
            self.client = None
            if self.proc and self.proc.poll() is not None:
                log.warning("RGB-Engine war beendet (Code %s), starte neu", self.proc.returncode)
                self.proc = None
                self._launch(lambda m: None)
                self._connect(time.monotonic() + 30)
                self._wait_for_devices(timeout=15)
            else:
                self._connect(time.monotonic() + 15)
                self._load_devices()
            self._direct.clear()
            log.info("RGB-Engine wieder verbunden")

    def _kill(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            log.info("RGB-Engine beendet")
        self.proc = None
        if self._log_handle:
            self._log_handle.close()
            self._log_handle = None

    def shutdown(self) -> None:
        with self.lock:
            try:
                self.restore()
            except Exception:  # noqa: BLE001
                pass
            if self.client:
                self.client.close()
            self.client = None
        self._kill()

    # ------------------------------------------------------------ Geräte
    def zones(self) -> list:
        out = []
        for key, (dkey, dev, zone) in self._zones.items():
            out.append({
                "key": key,
                "device": dkey,
                "zone": zone.name,
                "type": dev.type_name,
                "type_id": dev.type,
                "vendor": dev.vendor,
                "leds": zone.leds_count,
                "resizable": zone.leds_max > zone.leds_min,
                "leds_min": zone.leds_min,
                "leds_max": zone.leds_max,
            })
        return out

    def led_count(self, key: str) -> int:
        entry = self._zones.get(key)
        return entry[2].leds_count if entry else 0

    def resize(self, key: str, size: int) -> None:
        with self.lock:
            entry = self._zones.get(key)
            if not entry:
                return
            self.client.resize_zone(entry[1].index, entry[2].index, int(size))
            time.sleep(0.3)
            self._load_devices()

    # ------------------------------------------------------------ Licht
    def prepare(self, keys) -> None:
        """Merkt sich den bisherigen Zustand und schaltet die Geräte auf Direktsteuerung."""
        with self.lock:
            for key in keys:
                entry = self._zones.get(key)
                if not entry:
                    continue
                dkey, dev, _ = entry
                if dkey not in self._saved:
                    mode = dev.modes[dev.active_mode] if 0 <= dev.active_mode < len(dev.modes) else None
                    colors = {z.index: dev.zone_colors(z) for z in dev.zones}
                    self._saved[dkey] = (dev.index, mode, colors)
                if dkey in self._direct:
                    continue
                direct = dev.mode_by_name("Direct")
                if direct is not None:
                    self.client.update_mode(dev.index, direct)
                else:
                    self.client.set_custom_mode(dev.index)
                self._direct.add(dkey)
                log.info("%s: Direktsteuerung (%s)", dkey, direct.name if direct else "Custom")

    def set_zone(self, key: str, colors: list) -> None:
        frame = tuple(colors)
        if self._last.get(key) == frame:
            return
        entry = self._zones.get(key)
        if not entry:
            return
        with self.lock:
            self.client.update_zone_leds(entry[1].index, entry[2].index, colors)
        self._last[key] = frame

    def restore(self) -> None:
        """Stellt Modus und Farben wieder her, die vor dem Start aktiv waren."""
        with self.lock:
            if self.connected:
                for dkey, (dev_index, mode, colors) in self._saved.items():
                    try:
                        if mode is not None:
                            self.client.update_mode(dev_index, mode)
                            if mode.color_mode == COLOR_MODE_PER_LED:
                                for zone_index, cols in colors.items():
                                    if cols:
                                        self.client.update_zone_raw(dev_index, zone_index, cols)
                    except SDKError:
                        log.warning("Zustand von %s nicht wiederherstellbar", dkey)
            self._saved.clear()
            self._direct.clear()
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
