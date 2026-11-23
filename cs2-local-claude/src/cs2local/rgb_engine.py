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
import sys
import threading
import time
from pathlib import Path

from . import config
from .config import app_dir
from .sdk_client import COLOR_MODE_PER_LED, SDKClient, SDKError
from .i18n import tr

log = logging.getLogger(__name__)

ENGINE_LOG = app_dir() / "cs2local_engine.log"


class RGBEngineError(Exception):
    pass


class RGBEngine:
    def __init__(self, port: int = 6742, variant: str = "stable"):
        self.port = port
        self.variant = variant
        self.client: SDKClient | None = None
        self.proc: subprocess.Popen | None = None
        self.lock = threading.RLock()
        self.devices: list = []
        self._zones: dict = {}    # "Gerät::Zone" -> (Geräte-Schlüssel, Device, Zone)
        self._saved: dict = {}    # Geräte-Schlüssel -> (Modus, {Zonenindex: Farben})
        self._direct: set = set()  # Geräte im Direktmodus
        self.methods: dict = {}    # Geräte-Schlüssel -> "direct" oder "static"
        self._static: dict = {}    # Geräte-Schlüssel -> Static-Modus (zweite Methode)
        self._static_sent: dict = {}
        self._last: dict = {}
        self._log_handle = None
        atexit.register(self._kill)

    # ------------------------------------------------------------ Start/Stop
    @staticmethod
    def dev_available() -> bool:
        return (config.OPENRGB_DEV_DIR / "OpenRGB.exe").exists()

    @staticmethod
    def _stage(base: Path) -> Path:
        """Kopiert die Engine einmalig neben die EXE (Ordner _engine), statt sie aus dem Temp-Ordner zu starten.

        Sonst hält Windows beim Beenden den Temp-Ordner der EXE fest („Failed to remove temporary directory“).
        Pro Engine-Version ein Unterordner; alte Versionen werden entfernt.
        """
        if not getattr(sys, "frozen", False) or not (base / "OpenRGB.exe").exists():
            return base
        import hashlib
        import shutil
        digest = hashlib.sha1((base / "OpenRGB.exe").read_bytes()).hexdigest()[:10]
        root = config.app_dir() / "_engine"
        target = root / f"{base.name}-{digest}"
        try:
            if not (target / "OpenRGB.exe").exists():
                tmp = root / f".tmp-{base.name}-{digest}"
                shutil.rmtree(tmp, ignore_errors=True)
                shutil.copytree(base, tmp)
                tmp.rename(target)
                for old in root.glob(f"{base.name}-*"):
                    if old != target:
                        shutil.rmtree(old, ignore_errors=True)
            return target
        except OSError as exc:
            log.warning("Engine-Ordner neben der EXE nicht möglich (%s), nutze Temp-Ordner", exc)
            return base

    def find_exe(self) -> Path | None:
        base = config.OPENRGB_DEV_DIR if self.variant == "dev" and self.dev_available() else config.OPENRGB_DIR
        base = self._stage(base)
        direct = base / "OpenRGB.exe"
        if direct.exists():
            return direct
        if base.is_dir():
            for found in base.rglob("OpenRGB.exe"):
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
            raise RGBEngineError(tr("Die eingebaute RGB-Engine fehlt in diesem Build (OpenRGB.exe)."))
        progress(tr("Starte die RGB-Engine im Hintergrund …"))
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
        log.info("RGB-Engine gestartet (PID %s, %s)", self.proc.pid,
                 "Entwicklungsversion" if "openrgb_dev" in str(exe) else "OpenRGB 1.1")

    def _connect(self, deadline: float) -> None:
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if self.proc and self.proc.poll() is not None:
                raise RGBEngineError(tr("Die RGB-Engine wurde unerwartet beendet (Code {v0}). Details: {v1}",
                                        v0=self.proc.returncode, v1=ENGINE_LOG.name))
            client = SDKClient("127.0.0.1", self.port)
            try:
                client.connect()
                self.client = client
                return
            except (OSError, SDKError) as exc:
                client.close()
                last_error = exc
                time.sleep(1.0)
        raise RGBEngineError(tr("Keine Verbindung zur RGB-Engine möglich: {v0}", v0=last_error))

    def start(self, zone_sizes: dict | None = None, progress=lambda msg: None) -> None:
        with self.lock:
            if self._port_open():
                progress(tr("Eine laufende OpenRGB-Instanz wurde gefunden, verbinde …"))
            else:
                self._launch(progress)
            self._connect(time.monotonic() + 60)
            progress(tr("Suche RGB-Geräte (das dauert ein paar Sekunden) …"))
            self._wait_for_devices(progress=progress)
            for key, size in (zone_sizes or {}).items():
                try:
                    if key in self._zones and self.led_count(key) != size:
                        self.resize(key, size)
                except Exception:  # noqa: BLE001
                    log.warning("Zonengrösse für %s nicht setzbar", key)
            log.info("RGB-Engine bereit: %d Geräte, %d Zonen", len(self.devices), len(self._zones))
            for dev in self.devices:
                log.info("  %s: Beschreibung=%r Version=%r Seriennr=%r Ort=%r", dev.name, dev.description,
                         dev.version, dev.serial, dev.location)
                log.info("  %s (%s): %s | Modi: %s", dev.name, dev.type_name,
                         ", ".join(f"{z.name}[{z.leds_count}]" for z in dev.zones),
                         ", ".join(m.name for m in dev.modes))

    def _detection_finished(self) -> bool:
        """OpenRGB schreibt „Detection completed“ ins Engine-Log, wenn die Suche ganz fertig ist."""
        if not self._log_handle:
            return False
        try:
            self._log_handle.flush()
            return "Detection completed" in ENGINE_LOG.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False

    def _wait_for_devices(self, timeout: float = 60.0, progress=lambda msg: None) -> None:
        """Wartet, bis die Geräteerkennung fertig ist.

        Mit PawnIO prüft OpenRGB zuerst den Arbeitsspeicher, USB-Geräte (Mainboard, Lüftersteuerung, Tastatur)
        kommen erst nach 10 Sekunden oder mehr. Darum zählt die Meldung „Detection completed“ aus dem Engine-Log;
        ohne Log (fremde OpenRGB-Instanz) muss die Anzahl 12 Sekunden lang gleich bleiben, mit Log notfalls 25.
        """
        start = time.monotonic()
        deadline = start + timeout
        prev, since = -1, start
        while time.monotonic() < deadline:
            count = self.client.controller_count()
            now = time.monotonic()
            if count != prev:
                prev, since = count, now
                if count:
                    progress(tr("Suche RGB-Geräte … {v0} gefunden", v0=count))
            if self._detection_finished():
                time.sleep(0.5)  # letzte Registrierungen abwarten
                break
            if count > 0 and now - since >= (25 if self._log_handle else 12):
                break  # Log bleibt stumm (gepuffert?): lange genug keine neuen Geräte
            time.sleep(0.5)
        else:
            log.warning("Geräteerkennung nach %.0f s nicht abgeschlossen, nehme %d Geräte", timeout, prev)
        log.info("Geräteerkennung fertig nach %.1f s", time.monotonic() - start)
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
                self._wait_for_devices(timeout=40)
            else:
                self._connect(time.monotonic() + 15)
                self._load_devices()
            self._direct.clear()
            log.info("RGB-Engine wieder verbunden")

    def _kill(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                if os.name == "nt":  # ganzen Prozessbaum beenden
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], capture_output=True,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                else:
                    self.proc.kill()
                try:
                    self.proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    pass
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
                if self.methods.get(dkey) == "static" and dev.static_mode() is not None:
                    self._static[dkey] = dev.static_mode()
                    self._direct.add(dkey)
                    log.info("%s: Steuerung über Modus „%s“", dkey, self._static[dkey].name)
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
        dkey = entry[0]
        if dkey in self._static:  # zweite Methode: ganze Geräte-Farbe über den Static-Modus
            if not colors:
                return
            avg = tuple(sum(c[i] for c in colors) // len(colors) for i in range(3))
            now = time.monotonic()
            last_color, last_time = self._static_sent.get(dkey, (None, 0.0))
            if avg == last_color or now - last_time < 0.12:
                return
            with self.lock:
                self.client.update_mode(entry[1].index, self._static[dkey].with_color(avg))
            self._static_sent[dkey] = (avg, now)
            self._last[key] = frame
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
            self._static.clear()
            self._static_sent.clear()
            self._last.clear()

    def device_key(self, key: str) -> str | None:
        entry = self._zones.get(key)
        return entry[0] if entry else None

    def has_static(self, key: str) -> bool:
        entry = self._zones.get(key)
        return bool(entry and entry[1].static_mode() is not None)

    def blink(self, keys, stop: threading.Event, color=(0, 255, 200)) -> None:
        """Lässt Zonen blinken, bis stop gesetzt wird (für den Geräte-Check). Stellt danach wieder her."""
        with self.lock:
            self.prepare(keys)
        on = False
        try:
            while not stop.is_set():
                on = not on
                for key in keys:
                    n = self.led_count(key)
                    if n:
                        with self.lock:
                            self.set_zone(key, [color if on else (0, 0, 0)] * n)
                stop.wait(0.45)
        finally:
            with self.lock:
                self.restore()

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
