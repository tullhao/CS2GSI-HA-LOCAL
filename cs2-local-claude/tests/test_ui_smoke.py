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
for row, (state, text) in zip(win.setup_view.rows, [
        ("ok", "Läuft mit Adminrechten."), ("ok", "Gefunden und kompatibel."), ("ok", "Bereit auf Port 3002."),
        ("ok", "Gigabyte Control Center / RGB Fusion, Corsair iCUE pausiert. Startet beim Schliessen wieder."),
        ("warn", "PawnIO ist nicht installiert. RGB-Arbeitsspeicher wird übersprungen."),
        ("busy", "Suche RGB-Geräte …"), ("pending", "Wartet …")]):
    row.set(state, text)
win.setup_view.refresh_headline()
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

# Geräte-Check mit einer simulierten RGB-Engine durchklicken
import threading  # noqa: E402

from cs2local.ui.check_dialog import DeviceCheckDialog  # noqa: E402


class StubRGB:
    methods: dict = {}

    def __init__(self):
        self.sizes = {z["key"]: z["leds"] for z in zones}

    def device_key(self, key):
        return key.split("::")[0]

    def led_count(self, key):
        return self.sizes.get(key, 0)

    def resize(self, key, size):
        self.sizes[key] = size

    def has_static(self, key):
        return key.startswith("X870M")

    def blink(self, keys, stop):
        stop.wait()


check_settings = config.default_settings()
check_settings["devices"] = ["X870M AORUS ELITE WIFI7::LED_C"]
dlg = DeviceCheckDialog(StubRGB(), check_settings, zones, win)
dlg.show()
for _ in range(10):
    app.processEvents()
dlg.grab().save(str(SHOTS / "2_check.png"))
steps = 0
while dlg.isVisible() and steps < 40:
    steps += 1
    t = dlg.target
    z = t["resizable"]
    if z and z["zone"] == "ARGB_V2_1":
        dlg.btn_no.click()  # an ARGB_V2_1 hängt nichts
        if dlg.isVisible() and dlg.second_try:
            dlg.btn_no.click()
        continue
    if t["device"].startswith("X870M") and not z and not dlg.second_try:
        dlg.btn_no.click()  # Board reagiert nicht auf Direktsteuerung …
        assert dlg.second_try, "kein zweiter Versuch"
        dlg.grab().save(str(SHOTS / "2_check_zweiter_versuch.png"))
        continue
    dlg.btn_yes.click()  # … aber auf den Static-Modus; alles andere leuchtet
    app.processEvents()
assert not dlg.isVisible(), "Check nicht beendet"
assert check_settings["device_methods"]["X870M AORUS ELITE WIFI7"] == "static", check_settings["device_methods"]
assert check_settings["device_methods"]["G915 X LS TKL"] == "direct"
assert "X870M AORUS ELITE WIFI7::ARGB_V2_1" not in check_settings["devices"]
assert "X870M AORUS ELITE WIFI7::ARGB_V2_2" in check_settings["devices"]
assert "Corsair Commander Pro::Corsair RGB Header 2" in check_settings["devices"]  # war 0 LEDs, Test mit 60
assert check_settings["zone_sizes"]["Corsair Commander Pro::Corsair RGB Header 2"] == 60
assert check_settings["device_check_done"]
print("Geräte-Check ok:", dlg.summary())

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
