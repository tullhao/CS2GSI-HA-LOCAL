"""Startet die eingebaute RGB-Engine (OpenRGB aus bundle/) unter Windows und verbindet sich über das SDK.

Auf dem Build-Server gibt es keine RGB-Geräte, deshalb wird nur geprüft, dass der Kern unsichtbar startet,
antwortet und sauber wieder beendet wird.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2local.rgb_engine import RGBEngine  # noqa: E402

engine = RGBEngine(6798)
exe = engine.find_exe()
print("OpenRGB:", exe)
assert exe is not None, "bundle/openrgb/OpenRGB.exe fehlt"

start = time.monotonic()
engine.start(progress=print)
print(f"Verbunden nach {time.monotonic() - start:.1f}s, Zonen: {len(engine.zones())}")
assert engine.client is not None
assert engine.started_by_us

proc = engine.proc
engine.shutdown()
assert proc.poll() is not None, "RGB-Engine läuft nach dem Beenden noch"
print("RGB-Engine ok")
