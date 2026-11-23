"""Baut das Hauptfenster ohne Bildschirm auf, klickt durch alle Seiten und speichert Bildschirmfotos.

QT_QPA_PLATFORM=offscreen; Bilder landen in tests/screens/ (auf GitHub als Artefakt abrufbar).
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from cs2local import config  # noqa: E402
from cs2local.ui.main_window import MainWindow  # noqa: E402
from cs2local.ui.theme import STYLE  # noqa: E402

SHOTS = Path(__file__).resolve().parent / "screens"
SHOTS.mkdir(exist_ok=True)

app = QApplication(sys.argv)
app.setFont(QFont("Segoe UI", 10))
app.setStyleSheet(STYLE)
settings = config.default_settings()
win = MainWindow(settings, autostart=False)  # ohne Systemprüfung und Dialoge
win.resize(1280, 900)
win.show()


def shot(name: str) -> None:
    for _ in range(5):
        app.processEvents()
    win.grab().save(str(SHOTS / f"{name}.png"))


# Beispielgeräte, wie sie die RGB-Engine liefert (ähnlich dem echten PC)
zones = []
for dev, type_id, type_name, vendor, zz in [
    ("X870M AORUS ELITE WIFI7", 0, "Mainboard", "Gigabyte",
     [("ARGB_V2_1", 0, True), ("ARGB_V2_2", 12, True), ("Chipset Accent", 1, False), ("LED_C", 1, False)]),
    ("G915 X LS TKL", 5, "Tastatur", "Logitech", [("Keyboard", 87, False), ("Extras", 2, False)]),
    ("Corsair Commander Pro", 3, "Kühlung", "Corsair", [("Corsair RGB Header 1", 96, True), ("Corsair RGB Header 2", 0, True)]),
    ("Asus ROG SWIFT PG32UCDM", 20, "Monitor", "ASUS", [("Monitor", 1, False)]),
]:
    for name, leds, resizable in zz:
        zones.append({"key": f"{dev}::{name}", "device": dev, "zone": name, "type": type_name, "type_id": type_id,
                      "vendor": vendor, "leds": leds, "resizable": resizable,
                      "leds_min": 0 if resizable else leds, "leds_max": 300 if resizable else leds})

settings["zone_layout"]["Corsair Commander Pro::Corsair RGB Header 1"] = {
    "name": "Corsair LL120 / LL140", "kind": "fan", "count": 6, "per": 16, "total": 96}
settings["fans_off"]["Corsair Commander Pro::Corsair RGB Header 1"] = [4]
settings["states"]["idle"]["effect"] = "spin"  # damit die Ringe sichtbar drehen
shot("1_uebersicht")
win.go(1)
win.devices_page.populate(zones)
shot("2_geraete_leer")
card = win.devices_page.cards["G915 X LS TKL"]
card.master.click()
app.processEvents()
assert settings["devices"] == ["G915 X LS TKL::Keyboard", "G915 X LS TKL::Extras"], settings["devices"]
win.devices_page._set_all(True)  # noqa: SLF001
app.processEvents()
assert len(settings["devices"]) == 7, settings["devices"]  # Zonen mit 0 LEDs bleiben aus
rings = win.devices_page.cards["Corsair Commander Pro"].rings["Corsair Commander Pro::Corsair RGB Header 1"]
assert len(rings._source(96)) == 96  # noqa: SLF001
shot("2_geraete")
from PySide6.QtWidgets import QScrollArea  # noqa: E402
area = win.devices_page
while not isinstance(area, QScrollArea):
    area = area.parentWidget()
area.ensureWidgetVisible(win.devices_page.cards["Corsair Commander Pro"], 0, 200)
shot("2_geraete_luefter")

from cs2local.ui.pages import ZoneSetupDialog  # noqa: E402
dlg = ZoneSetupDialog("Corsair RGB Header 2", None, 204, win)
dlg.show()
for _ in range(5):
    app.processEvents()
assert dlg.result_layout()["total"] == 16
dlg.grab().save(str(SHOTS / "2_einrichten.png"))
dlg.close()

win.go(2)
page = win.effects_page
for i in range(len(config.CATEGORIES)):
    page.cat_group.button(i).click()
    shot(f"3_effekte_{i}_{config.CATEGORIES[i][0].lower()}")
page.cat_group.button(0).click()
first = page.cards[0]
first.more.setChecked(True)
first.toggle.click()
assert settings["states"][first.sid]["enabled"] is False
first.toggle.click()
page.team_group.button(1).click()
shot("3_effekte_feineinstellungen")

win.go(3)
win._tick()  # noqa: SLF001
shot("4_live")

win.timer.stop()
win.hide()
print("UI ok, Bilder in", SHOTS)
