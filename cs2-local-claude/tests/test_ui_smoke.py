"""Baut das Hauptfenster ohne Bildschirm auf und klickt durch alle Seiten (QT_QPA_PLATFORM=offscreen)."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from cs2local import config  # noqa: E402
from cs2local.ui.main_window import MainWindow  # noqa: E402
from cs2local.ui.theme import STYLE  # noqa: E402

app = QApplication(sys.argv)
app.setStyleSheet(STYLE)
settings = config.default_settings()
win = MainWindow(settings, autostart=False)  # ohne Systemprüfung und Dialoge
win.show()

# Seiten wechseln, Effekt-Zeilen neu bauen, Live-Anzeige einmal aktualisieren
for i in range(4):
    win.go(i)
    app.processEvents()
win._build_effect_rows()
win._paint_colors()
win._tick()

# Gerätebaum mit Beispieldaten füllen (wie es die RGB-Engine liefern würde)
zones = [
    {"key": "B650 Board::ARGB Header 1", "device": "B650 Board", "zone": "ARGB Header 1", "type": "Motherboard",
     "leds": 0, "resizable": True, "leds_min": 0, "leds_max": 1024},
    {"key": "B650 Board::Logo", "device": "B650 Board", "zone": "Logo", "type": "Motherboard",
     "leds": 1, "resizable": False, "leds_min": 1, "leds_max": 1},
    {"key": "Logitech G915 TKL::Keyboard", "device": "Logitech G915 TKL", "zone": "Keyboard", "type": "Keyboard",
     "leds": 92, "resizable": False, "leds_min": 92, "leds_max": 92},
]
win._populate_tree(zones)
win._check_all(True)
app.processEvents()
assert len(settings["devices"]) == 3, settings["devices"]
win._check_all(False)
app.processEvents()
assert settings["devices"] == [], settings["devices"]

# Effekt-Einstellungen ändern wie per Klick
win._set_state("kill", "color", [1, 2, 3])
win._on_brightness(50)
assert settings["options"]["brightness"] == 50

win.timer.stop()
win.hide()
print("UI ok")
