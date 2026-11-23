"""Härtetest der RGB-Engine unter Windows mit OpenRGBs eingebauten Testgeräten (Debug Devices).

Läuft auf dem Build-Server gegen den echten, mitgelieferten OpenRGB-Kern:
  1. Kern unsichtbar starten, verbinden, Testgeräte erkennen und Gerätedaten korrekt lesen
  2. Direktmodus setzen, 10 Sekunden lang mit 30 Bildern/s alle Zonen beschreiben
     und gleichzeitig Gerätedaten abfragen (so wie die Oberfläche es tut)
  3. Farben kommen wirklich an (zurücklesen)
  4. LED-Anzahl einer einstellbaren Zone ändern
  5. Kern mitten im Betrieb abschiessen: Engine startet ihn selbst neu und macht weiter
  6. Wiederherstellen und sauber beenden
"""
import json
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2local import config, rgb_engine  # noqa: E402
from cs2local.config import STATE_ORDER, default_settings  # noqa: E402
from cs2local.engine import LightEngine  # noqa: E402
from cs2local.states import StateDetector  # noqa: E402

BUNDLE = Path(__file__).resolve().parents[1] / "bundle" / "openrgb"
assert (BUNDLE / "OpenRGB.exe").exists(), "bundle/openrgb/OpenRGB.exe fehlt"

# Kopie des Kerns mit Testgeräten, damit die Konfiguration nicht in der EXE landet
work = Path(tempfile.mkdtemp()) / "openrgb"
shutil.copytree(BUNDLE, work)
(work / "OpenRGB.json").write_text(json.dumps({"DebugDevices": {"devices": [
    {"type": "keyboard"}, {"type": "motherboard"}, {"type": "argb"}, {"type": "dram"}, {"type": "gpu"},
]}}), encoding="utf-8")
config.OPENRGB_DIR = work

engine = rgb_engine.RGBEngine(6797)
t0 = time.monotonic()
engine.start(progress=print)
print(f"1) Verbunden nach {time.monotonic() - t0:.1f}s, Protokoll {engine.client.version}")
zones = engine.zones()
for dev in engine.devices:
    print(f"   {dev.name} ({dev.type_name}) Modi={[m.name for m in dev.modes]} "
          f"Zonen={[(z.name, z.leds_count, z.leds_min, z.leds_max) for z in dev.zones]}")
assert len(engine.devices) >= 5, "Testgeräte nicht erkannt"
assert all(d.modes and d.zones for d in engine.devices), "Gerätedaten unvollständig gelesen"
assert all(len(d.colors) == sum(z.leds_count for z in d.zones) for d in engine.devices), "Farbliste passt nicht"
keys = [z["key"] for z in zones if z["leds"] > 0]
print(f"   {len(keys)} Zonen mit LEDs")

# 2) Licht-Motor wie in der App laufen lassen, parallel Gerätedaten abfragen
settings = default_settings()
settings["devices"] = keys
settings["options"]["fps"] = 30
detector = StateDetector(lambda: settings["options"])
light = LightEngine(engine, detector, lambda: settings)
stop_polling = threading.Event()
polls = []


def poll():
    while not stop_polling.is_set():
        try:
            with engine.lock:
                engine.client.device(0)
            polls.append(1)
        except Exception as exc:  # noqa: BLE001
            polls.append(exc)
        time.sleep(0.2)


threading.Thread(target=poll, daemon=True).start()
light.start()
for sid in STATE_ORDER[:10]:  # Vorschauen durchschalten
    light.preview(sid, 1.0)
    time.sleep(1.0)
stop_polling.set()
assert light.running and light.status.get("error") is None, light.status
assert engine.connected, "Verbindung während des Betriebs verloren"
errors = [p for p in polls if p != 1]
assert not errors, f"Abfragen fehlgeschlagen: {errors[:3]}"
print(f"2) 10 s Dauerbetrieb ok, {len(polls)} parallele Abfragen ohne Fehler")

# 3) Farben zurücklesen: Direktmodus aktiv und die gesendete Farbe ist angekommen
light.stop(wait=True)
key = keys[0]
_, dev, zone = engine._zones[key]
engine.prepare([key])
engine.set_zone(key, [(10, 200, 30)] * zone.leds_count)
time.sleep(0.5)
fresh = engine.client.device(dev.index)
direct = fresh.mode_by_name("Direct")
assert direct is None or fresh.active_mode == direct.index, "Direktmodus nicht aktiv"
got = fresh.zone_colors(fresh.zones[zone.index])[0]
assert got == (10 | 200 << 8 | 30 << 16), f"Farbe nicht angekommen: {got:#08x}"
engine.restore()
print("3) Farben kommen an, Direktmodus bestätigt")

# 4) einstellbare Zone (ARGB) in der Länge ändern
resizable = [z for z in engine.zones() if z["resizable"]]
if resizable:
    rz = resizable[0]
    target = min(rz["leds_max"], max(rz["leds_min"], 24 if rz["leds"] != 24 else 12))
    engine.resize(rz["key"], target)
    assert engine.led_count(rz["key"]) == target, (engine.led_count(rz["key"]), target)
    print(f"4) {rz['key']} auf {target} LEDs gesetzt")
else:
    print("4) keine einstellbare Zone unter den Testgeräten")

# 5) Kern abschiessen, Licht-Motor muss sich erholen
light.start()
time.sleep(1.0)
old_pid = engine.proc.pid
engine.proc.kill()
deadline = time.monotonic() + 60
while time.monotonic() < deadline and not (engine.connected and engine.proc and engine.proc.pid != old_pid
                                          and light.status.get("top") not in (None, "Verbinde neu …")):
    time.sleep(0.5)
time.sleep(2.0)
assert light.running and light.status.get("error") is None, light.status
assert engine.connected and engine.proc.pid != old_pid, "Engine nicht neu gestartet"
print(f"5) Nach Absturz selbst neu gestartet (PID {old_pid} -> {engine.proc.pid}) und läuft weiter")

# 6) sauber beenden
light.stop(wait=True)
proc = engine.proc
engine.shutdown()
assert proc.poll() is not None, "RGB-Engine läuft nach dem Beenden noch"
print("6) Sauber beendet")
print("RGB-Engine HÄRTETEST OK")

# 7) Entwicklungsversion (falls eingebaut) mit denselben Testgeräten starten
DEV = Path(__file__).resolve().parents[1] / "bundle" / "openrgb_dev"
if (DEV / "OpenRGB.exe").exists():
    work_dev = Path(tempfile.mkdtemp()) / "openrgb_dev"
    shutil.copytree(DEV, work_dev)
    shutil.copy(work / "OpenRGB.json", work_dev / "OpenRGB.json")
    config.OPENRGB_DEV_DIR = work_dev
    dev = rgb_engine.RGBEngine(6796, variant="dev")
    assert "openrgb_dev" in str(dev.find_exe())
    dev.start(progress=print)
    print(f"7) Entwicklungsversion: Protokoll {dev.client.version}, {len(dev.devices)} Geräte")
    assert len(dev.devices) >= 5 and all(d.zones for d in dev.devices)
    k = [z["key"] for z in dev.zones() if z["leds"] > 0][0]
    dev.prepare([k])
    dev.set_zone(k, [(1, 2, 3)] * dev.led_count(k))
    time.sleep(0.5)
    _, d, zz = dev._zones[k]  # noqa: SLF001
    assert dev.client.device(d.index).zone_colors(zz)[0] == (1 | 2 << 8 | 3 << 16), "Farbe kam nicht an (dev)"
    dev.shutdown()
    print("ENTWICKLUNGSVERSION OK")
else:
    print("7) Entwicklungsversion nicht im Bundle")
