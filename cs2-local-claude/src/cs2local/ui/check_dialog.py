"""Geführter Geräte-Check: jedes Gerät und jeder Anschluss blinkt nacheinander, ein Klick bestätigt.

Ein PC kann LEDs nicht sehen. Deshalb blinkt das Tool jedes Ziel an und fragt kurz nach. Reagiert ein Gerät
nicht auf die Direktsteuerung, probiert der Check automatisch die zweite Methode (Static-Modus).
Anschlüsse ohne Angabe werden mit vielen LEDs getestet, damit auch unbekannte Streifen/Lüfter aufleuchten.
"""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from .widgets import DeviceIcon

log = logging.getLogger(__name__)

TEST_LEDS = 60  # so viele LEDs bekommt ein unbekannter Anschluss für den Test


def build_targets(zones: list) -> list:
    """Was nacheinander getestet wird: je Gerät die festen Zonen zusammen, jeder ARGB-Anschluss einzeln."""
    targets = []
    by_device: dict = {}
    for z in zones:
        by_device.setdefault(z["device"], []).append(z)
    for device, dz in by_device.items():
        fixed = [z for z in dz if not z["resizable"] and z["leds"] > 0]
        if fixed:
            targets.append({"device": device, "label": device, "type_id": fixed[0]["type_id"],
                            "keys": [z["key"] for z in fixed], "resizable": None})
        for z in dz:
            if z["resizable"]:
                targets.append({"device": device, "label": f"{device} · Anschluss {z['zone']}",
                                "type_id": z["type_id"], "keys": [z["key"]], "resizable": z})
    return targets


class DeviceCheckDialog(QDialog):
    def __init__(self, rgb, settings: dict, zones: list, parent=None):
        super().__init__(parent)
        self.rgb = rgb
        self.settings = settings
        self.targets = build_targets(zones)
        self.index = 0
        self.second_try = False
        self.stop: threading.Event | None = None
        self.thread: threading.Thread | None = None
        self.confirmed: set = set()
        self.rejected: set = set()
        self.methods: dict = dict(settings.get("device_methods", {}))
        self.temp_sizes: dict = {}
        self.decided: dict = {}  # Gerät -> Methode, die im Check funktioniert hat

        self.setWindowTitle("Geräte-Check")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 20)
        lay.setSpacing(14)
        self.progress = QProgressBar()
        self.progress.setRange(0, max(1, len(self.targets)))
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        lay.addWidget(self.progress)
        self.step = QLabel()
        self.step.setObjectName("Muted")
        lay.addWidget(self.step)
        head = QHBoxLayout()
        head.setSpacing(16)
        self.icon = DeviceIcon(0)
        head.addWidget(self.icon, 0, Qt.AlignTop)
        self.title = QLabel()
        self.title.setObjectName("PageTitle")
        self.title.setStyleSheet("font-size: 15pt;")
        self.title.setWordWrap(True)
        head.addWidget(self.title, 1)
        lay.addLayout(head)
        self.question = QLabel()
        self.question.setWordWrap(True)
        self.question.setStyleSheet("font-size: 11.5pt;")
        lay.addWidget(self.question)
        self.hint = QLabel()
        self.hint.setObjectName("Muted")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        row = QHBoxLayout()
        self.btn_skip = QPushButton("Überspringen")
        self.btn_skip.setObjectName("Small")
        self.btn_skip.clicked.connect(lambda: self._answer(None))
        row.addWidget(self.btn_skip)
        row.addStretch(1)
        self.btn_no = QPushButton("Nein, nichts")
        self.btn_no.clicked.connect(lambda: self._answer(False))
        self.btn_yes = QPushButton("Ja, es blinkt")
        self.btn_yes.setObjectName("Primary")
        self.btn_yes.clicked.connect(lambda: self._answer(True))
        row.addWidget(self.btn_no)
        row.addWidget(self.btn_yes)
        lay.addLayout(row)
        QTimer.singleShot(100, self._show_target)

    # ------------------------------------------------------------ Ablauf
    @property
    def target(self) -> dict:
        return self.targets[self.index]

    def _show_target(self) -> None:
        if self.index >= len(self.targets):
            self._finish()
            return
        t = self.target
        self.progress.setValue(self.index)
        self.step.setText(f"Schritt {self.index + 1} von {len(self.targets)}")
        self.icon.type_id = t["type_id"]
        self.icon.set_active(True)
        self.title.setText(t["label"])
        dkey = self.rgb.device_key(t["keys"][0])
        if self.second_try:
            self.question.setText("Zweiter Versuch mit einer anderen Methode: Blinkt es jetzt türkis?")
            self.hint.setText("Manche Geräte (z. B. neue Gigabyte-Boards) reagieren nur so. Dann leuchten sie "
                              "einfarbig, aber Effekte und Farben funktionieren.")
        else:
            self.question.setText("Blinkt dieses Gerät jetzt türkis?")
            z = t["resizable"]
            if z and not self.settings.get("zone_layout", {}).get(z["key"]):
                self.hint.setText("Das ist ein Anschluss für Lüfter, LED-Streifen oder z. B. die Grafikkarte. "
                                  "Wenn dort nichts hängt, klick „Nein“.")
            else:
                self.hint.setText("Schau auf das Gerät. Das Blinken läuft, bis du antwortest.")
        if self.second_try:
            self.methods[dkey] = "static"
        else:  # bewährte Methode dieses Geräts weiterverwenden, sonst zuerst Direktsteuerung
            self.methods[dkey] = self.decided.get(dkey, "direct")
        self._start_blink()

    def _start_blink(self) -> None:
        self._stop_blink()
        t = self.target
        z = t["resizable"]
        if z and self.rgb.led_count(z["key"]) == 0:  # unbekannter Anschluss: mit vielen LEDs testen
            size = min(TEST_LEDS, z["leds_max"] or TEST_LEDS)
            try:
                self.rgb.resize(z["key"], size)
                self.temp_sizes[z["key"]] = size
            except Exception:  # noqa: BLE001
                log.exception("Testgrösse nicht setzbar")
        self.rgb.methods = self.methods
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._blink_worker, args=(list(t["keys"]), self.stop),
                                       name="check-blink", daemon=True)
        self.thread.start()

    def _blink_worker(self, keys, stop) -> None:
        try:
            self.rgb.blink(keys, stop)
        except Exception:  # noqa: BLE001
            log.exception("Blinken im Geräte-Check fehlgeschlagen")

    def _stop_blink(self) -> None:
        if self.stop:
            self.stop.set()
        if self.thread:
            self.thread.join(timeout=3.0)
        self.stop = self.thread = None

    def _answer(self, yes) -> None:
        t = self.target
        dkey = self.rgb.device_key(t["keys"][0])
        if yes is False and not self.second_try and self.rgb.has_static(t["keys"][0]) \
                and self.methods.get(dkey) != "static":
            self.second_try = True
            self._show_target()
            return
        self._stop_blink()
        if yes:
            self.confirmed.update(t["keys"])
            self.decided[dkey] = self.methods.get(dkey, "direct")
        elif yes is False:
            self.rejected.update(t["keys"])
            self.methods[dkey] = self.decided.get(dkey, "direct")
            z = t["resizable"]
            if z and z["key"] in self.temp_sizes:  # nichts angeschlossen: wieder auf 0
                try:
                    self.rgb.resize(z["key"], 0)
                except Exception:  # noqa: BLE001
                    pass
                self.temp_sizes.pop(z["key"], None)
        self.second_try = False
        self.index += 1
        self._show_target()

    def _finish(self) -> None:
        self._stop_blink()
        self.rgb.methods = self.methods
        devices = [k for k in self.settings["devices"] if k not in self.rejected]
        for key in self.confirmed:
            if key not in devices:
                devices.append(key)
        self.settings["devices"] = devices
        self.settings["device_methods"] = self.methods
        for key, size in self.temp_sizes.items():
            if key in self.confirmed and not self.settings.get("zone_layout", {}).get(key):
                self.settings.setdefault("zone_sizes", {})[key] = size
                self.settings.setdefault("zone_layout", {})[key] = {
                    "name": "Unbekannt (Test mit 60 LEDs)", "kind": "strip", "count": 1, "per": size, "total": size}
        self.settings["device_check_done"] = True
        log.info("Geräte-Check: %d Zonen bestätigt, %d abgelehnt, Methoden %s",
                 len(self.confirmed), len(self.rejected), self.methods)
        self.accept()

    def reject(self) -> None:  # Fenster geschlossen: Blinken beenden, nichts übernehmen
        self._stop_blink()
        for key in self.temp_sizes:
            try:
                self.rgb.resize(key, 0)
            except Exception:  # noqa: BLE001
                pass
        super().reject()

    def summary(self) -> str:
        return (f"{len(self.confirmed)} Zonen funktionieren und sind eingeschaltet, "
                f"{len(self.rejected)} ohne Reaktion wurden ausgeschaltet.")
