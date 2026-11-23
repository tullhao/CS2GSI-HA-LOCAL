"""Hauptfenster: Übersicht, Geräte, Effekte und Live-Steuerung."""
from __future__ import annotations

import logging
import secrets
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import config, system
from ..cs2_setup import find_cs2, normalize_cs2_dir, other_gsi_files, write_gsi_config
from ..engine import LightEngine
from ..gsi_server import GSIServer
from ..rgb_engine import RGBEngine, RGBEngineError
from ..states import StateDetector
from . import theme
from .check_dialog import DeviceCheckDialog
from .pages import DevicesPage, EffectsPage, ZoneSetupDialog
from .widgets import LedPreview

log = logging.getLogger(__name__)

ICONS = {"ok": ("✔", theme.OK), "warn": ("!", theme.WARN), "error": ("✖", theme.ERROR), "busy": ("…", theme.MUTED)}
BUSY_MSG = "Bitte zuerst die Lichtsteuerung stoppen."


class Bridge(QObject):
    """Signale aus Hintergrund-Threads sicher in die Oberfläche bringen."""
    rgb_progress = Signal(str)
    rgb_done = Signal(bool, str)
    task_done = Signal(str, str)
    pawnio_done = Signal(bool, bool, str)


class StatusCard(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("Card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(14)
        self.icon = QLabel("…")
        self.icon.setFixedSize(40, 40)
        self.icon.setAlignment(Qt.AlignCenter)
        col = QVBoxLayout()
        col.setSpacing(3)
        t = QLabel(title)
        t.setObjectName("CardHeading")
        self.text = QLabel()
        self.text.setObjectName("Muted")
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        col.addWidget(t)
        col.addWidget(self.text)
        lay.addWidget(self.icon, 0, Qt.AlignTop)
        lay.addLayout(col, 1)
        self.set("busy", "Wird geprüft …")

    def set(self, state: str, text: str) -> None:
        symbol, color = ICONS[state]
        self.icon.setText(symbol)
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        self.icon.setStyleSheet(f"background: rgba({r},{g},{b},40); color:{color}; border-radius:20px; "
                                "font-size:15pt; font-weight:800;")
        self.text.setText(text)


def _title(text: str, sub: str) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 6)
    lay.setSpacing(4)
    t = QLabel(text)
    t.setObjectName("PageTitle")
    s = QLabel(sub)
    s.setObjectName("PageSub")
    s.setWordWrap(True)
    lay.addWidget(t)
    lay.addWidget(s)
    return w


class MainWindow(QMainWindow):
    def __init__(self, settings: dict, autostart: bool = True):
        super().__init__()
        self.settings = settings
        self.setWindowTitle(f"{config.APP_NAME} {config.VERSION}")
        self.resize(1360, 880)
        self.setMinimumSize(1000, 660)

        opts = settings["options"]
        self.bridge = Bridge()
        self.bridge.rgb_progress.connect(lambda msg: self.card_rgb.set("busy", msg))
        self.bridge.rgb_done.connect(self._on_rgb_done)
        self.bridge.task_done.connect(self._on_task_done)
        self.bridge.pawnio_done.connect(self._on_pawnio_done)

        self.rgb = RGBEngine(int(opts["openrgb_port"]))
        self.detector = StateDetector(lambda: self.settings["options"])
        self.engine = LightEngine(self.rgb, self.detector, lambda: self.settings)
        self.gsi: GSIServer | None = None
        self.cs2_path: Path | None = None
        self.rgb_ready = False
        self._pawnio_force = False

        self._build()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(200)
        if autostart:
            QTimer.singleShot(150, self._run_setup)

    # ================================================================ Aufbau
    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(232)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(16, 22, 16, 16)
        sl.setSpacing(6)
        brand = QLabel("CS2 Local")
        brand.setObjectName("Brand")
        sub = QLabel("RGB · BUILT WITH CLAUDE")
        sub.setObjectName("BrandSub")
        sl.addWidget(brand)
        sl.addWidget(sub)
        sl.addSpacing(22)

        self.stack = QStackedWidget()
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        pages = [
            ("①  Übersicht", self._page_overview()),
            ("②  Geräte", self._page_devices()),
            ("③  Effekte", self._page_effects()),
            ("④  Live", self._page_live()),
        ]
        for i, (label, page) in enumerate(pages):
            btn = QPushButton(label)
            btn.setObjectName("Nav")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, idx=i: self.stack.setCurrentIndex(idx))
            self.nav.addButton(btn, i)
            sl.addWidget(btn)
            wrap = QScrollArea()
            wrap.setWidgetResizable(True)
            wrap.setFrameShape(QFrame.NoFrame)
            wrap.setStyleSheet("QScrollArea{background:transparent;border:none;}")
            wrap.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            page.setObjectName("Root")
            wrap.setWidget(page)
            self.stack.addWidget(wrap)
        self.nav.button(0).setChecked(True)
        sl.addStretch(1)
        self.side_status = QLabel("● Bereit")
        self.side_status.setObjectName("Muted")
        sl.addWidget(self.side_status)
        foot = QLabel(f"v{config.VERSION} · portabel · GPL-2.0")
        foot.setObjectName("Footer")
        sl.addWidget(foot)

        outer.addWidget(side)
        outer.addWidget(self.stack, 1)

    def go(self, idx: int) -> None:
        self.nav.button(idx).setChecked(True)
        self.stack.setCurrentIndex(idx)

    @staticmethod
    def _page() -> tuple:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(36, 30, 36, 30)
        lay.setSpacing(16)
        return w, lay

    def _next_button(self, text: str, idx: int) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch(1)
        btn = QPushButton(text)
        btn.setObjectName("Primary")
        btn.clicked.connect(lambda: self.go(idx))
        row.addWidget(btn)
        return row

    # ---------------------------------------------------------------- Seite 1
    def _page_overview(self) -> QWidget:
        w, lay = self._page()
        lay.addWidget(_title("Übersicht", "Das Tool prüft dein System und richtet alles für diese Sitzung ein. "
                                          "Alles Nötige ist eingebaut, es wird nichts heruntergeladen."))
        grid = QGridLayout()
        grid.setSpacing(14)
        self.card_admin = StatusCard("Adminrechte")
        self.card_cs2 = StatusCard("Counter-Strike 2")
        self.card_gsi = StatusCard("Spieldaten (Game State Integration)")
        self.card_driver = StatusCard("Treiber für RGB-Arbeitsspeicher")
        self.card_rgb = StatusCard("RGB-Engine und Geräte")
        self.card_game = StatusCard("Verbindung zum Spiel")
        cards = [self.card_admin, self.card_cs2, self.card_gsi, self.card_driver, self.card_rgb, self.card_game]
        for i, card in enumerate(cards):
            grid.addWidget(card, i // 2, i % 2)
        lay.addLayout(grid)

        row = QHBoxLayout()
        for text, slot in (("CS2-Ordner wählen …", self._choose_cs2), ("Config neu schreiben", self._write_gsi)):
            b = QPushButton(text)
            b.setObjectName("Small")
            b.clicked.connect(slot)
            row.addWidget(b)
        self.btn_driver = QPushButton("Treiber installieren")
        self.btn_driver.setObjectName("Small")
        self.btn_driver.clicked.connect(lambda: self._ask_pawnio(force=True))
        self.btn_driver.hide()
        row.addWidget(self.btn_driver)
        row.addStretch(1)
        nxt = QPushButton("Weiter zu den Geräten  →")
        nxt.setObjectName("Primary")
        nxt.clicked.connect(lambda: self.go(1))
        row.addWidget(nxt)
        lay.addLayout(row)
        lay.addStretch(1)
        return w

    # ---------------------------------------------------------------- Seite 2
    def _page_devices(self) -> QWidget:
        w, lay = self._page()
        lay.addWidget(_title("Geräte", "Alle RGB-Geräte, die dein PC gefunden hat. Schalte ein, was auf CS2 "
                                       "reagieren soll, oder wähle einzelne Zonen."))
        self.devices_page = DevicesPage(self.settings, self._zone_live_frame)
        self.devices_page.setup_requested.connect(self._setup_zone)
        self.devices_page.check_requested.connect(self._run_check)
        self.devices_page.test_requested.connect(self._test_devices)
        self.devices_page.rescan_requested.connect(self._restart_rgb)
        lay.addWidget(self.devices_page)
        lay.addLayout(self._next_button("Weiter zu den Effekten  →", 2))
        return w

    # ---------------------------------------------------------------- Seite 3
    def _page_effects(self) -> QWidget:
        w, lay = self._page()
        lay.addWidget(_title("Effekte", "Wie sollen deine LEDs reagieren? Jede Karte zeigt live, wie es aussieht. "
                                        "„▶ Zeigen“ spielt ihn 3 Sekunden auf deinen Geräten ab."))
        self.effects_page = EffectsPage(self.settings, self._live_team)
        self.effects_page.device_preview.connect(self._preview)
        lay.addWidget(self.effects_page)
        lay.addLayout(self._next_button("Weiter zu Live  →", 3))
        return w

    def _live_team(self):
        return self.detector.team if self.detector.connected() else None

    # ---------------------------------------------------------------- Seite 4
    def _page_live(self) -> QWidget:
        w, lay = self._page()
        lay.addWidget(_title("Live", "Starte CS2 ganz normal. Sobald du auf Start drückst, reagieren deine LEDs "
                                     "auf das Spiel. Stopp stellt die vorherigen Farben wieder her."))
        hero = QFrame()
        hero.setObjectName("Card")
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(24, 22, 24, 22)
        hl.setSpacing(14)
        top = QHBoxLayout()
        self.btn_start = QPushButton("▶  START")
        self.btn_start.setObjectName("StartButton")
        self.btn_start.setProperty("running", False)
        self.btn_start.setMinimumWidth(240)
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self._toggle_run)
        top.addWidget(self.btn_start)
        top.addSpacing(20)
        col = QVBoxLayout()
        self.lbl_top = QLabel("Gestoppt")
        self.lbl_top.setObjectName("LiveState")
        self.lbl_sub = QLabel("Drück auf Start, sobald du bereit bist.")
        self.lbl_sub.setObjectName("Muted")
        self.lbl_sub.setWordWrap(True)
        col.addStretch(1)
        col.addWidget(self.lbl_top)
        col.addWidget(self.lbl_sub)
        col.addStretch(1)
        top.addLayout(col, 1)
        hl.addLayout(top)
        self.live_leds = LedPreview(leds=32, height=46)
        self.live_leds.set_source(self._live_frame)
        hl.addWidget(self.live_leds)
        lay.addWidget(hero)

        info = QFrame()
        info.setObjectName("Card")
        ig = QGridLayout(info)
        ig.setContentsMargins(22, 18, 22, 18)
        ig.setHorizontalSpacing(30)
        ig.setVerticalSpacing(12)
        self.info_labels: dict = {}
        fields = [("map", "Karte"), ("phase", "Phase"), ("team", "Team"), ("health", "Leben"),
                  ("armor", "Rüstung"), ("bomb", "Bombe"), ("c4", "C4-Vorschau"), ("active", "Aktive Situationen")]
        for i, (key, label) in enumerate(fields):
            k = QLabel(label.upper())
            k.setObjectName("CardTitle")
            v = QLabel("–")
            v.setWordWrap(True)
            self.info_labels[key] = v
            ig.addWidget(k, i // 2, (i % 2) * 2)
            ig.addWidget(v, i // 2, (i % 2) * 2 + 1)
        ig.setColumnStretch(1, 1)
        ig.setColumnStretch(3, 1)
        lay.addWidget(info)
        hint = QLabel("Tipp: Wurde die Config neu geschrieben, während CS2 schon lief, starte CS2 einmal neu.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch(1)
        return w

    def _live_frame(self, _elapsed: float, n: int):
        """Was die Geräte gerade zeigen (oder zeigen würden, wenn Live läuft)."""
        now = time.monotonic()
        brightness = max(0.0, min(1.0, float(self.settings["options"]["brightness"]) / 100.0))
        layers = self.engine.layers(now, self.settings)
        frame = self.engine.compose(layers, n, brightness)
        if not self.engine.running:
            frame = [tuple(int(v * 0.35) for v in c) for c in frame]
        return frame

    # ================================================================ Setup-Ablauf
    def _run_setup(self) -> None:
        if system.is_admin():
            self.card_admin.set("ok", "Läuft mit Adminrechten.")
        else:
            self.card_admin.set("warn", "Ohne Adminrechte werden Arbeitsspeicher und manche Mainboards nicht erkannt.")

        saved = self.settings.get("cs2_path")
        path = normalize_cs2_dir(Path(saved)) if saved else None
        self._set_cs2(path or find_cs2())

        if not self.settings.get("gsi_token"):
            self.settings["gsi_token"] = secrets.token_hex(16)
        self.gsi = GSIServer(self.settings["gsi_token"], self.detector.update)
        try:
            port = self.gsi.start(int(self.settings["options"]["gsi_port"]))
            self.settings["options"]["gsi_port"] = port
        except OSError as exc:
            self.card_gsi.set("error", f"Empfang nicht möglich: {exc}")
            self.gsi = None
        self._write_gsi()
        self._driver_step()

    # ---- Schritt: PawnIO
    def _driver_step(self) -> None:
        if system.pawnio_installed():
            self.card_driver.set("ok", "PawnIO ist installiert. Arbeitsspeicher und Mainboard können erkannt werden.")
            self._conflict_step()
            return
        self.btn_driver.show()
        if self.settings.get("pawnio_declined"):
            self.card_driver.set("warn", "PawnIO ist nicht installiert. RGB-Arbeitsspeicher wird übersprungen.")
            self._conflict_step()
            return
        self._ask_pawnio(force=False)

    def _ask_pawnio(self, force: bool) -> None:
        if not system.is_admin():
            QMessageBox.information(self, config.APP_NAME, "Für die Treiber-Installation braucht das Tool "
                                    "Adminrechte. Bitte das Tool neu starten und die Windows-Abfrage bestätigen.")
            if not force:
                self.card_driver.set("warn", "PawnIO ist nicht installiert (keine Adminrechte).")
                self._conflict_step()
            return
        box = QMessageBox(self)
        box.setWindowTitle("Treiber für RGB-Arbeitsspeicher")
        box.setIcon(QMessageBox.Information)
        box.setText("<b>Für RGB-Arbeitsspeicher braucht Windows den Treiber „PawnIO“.</b>")
        box.setInformativeText(
            "Ohne diesen Treiber kann kein Programm die LEDs deines Arbeitsspeichers (und mancher Mainboards) "
            "ansprechen. Das gilt auch für OpenRGB.\n\n"
            "• PawnIO ist Open Source und digital signiert.\n"
            "• Er ist in diesem Tool enthalten, es wird nichts heruntergeladen.\n"
            "• Er wird einmalig als Windows-Treiber installiert und bleibt danach installiert. Entfernen kannst "
            "du ihn jederzeit unter Einstellungen → Apps → PawnIO.\n"
            "• Ohne ihn funktionieren Tastatur, Maus, Lüfter und ARGB-Header trotzdem.\n\n"
            "Jetzt installieren?")
        install = box.addButton("Jetzt installieren", QMessageBox.AcceptRole)
        box.addButton("Ohne Arbeitsspeicher weiter", QMessageBox.RejectRole)
        box.setDefaultButton(install)
        box.exec()
        if box.clickedButton() is not install:
            self.settings["pawnio_declined"] = True
            self.card_driver.set("warn", "PawnIO ist nicht installiert. RGB-Arbeitsspeicher wird übersprungen.")
            if not force:
                self._conflict_step()
            return
        self.settings["pawnio_declined"] = False
        self.card_driver.set("busy", "Installiere PawnIO …")
        self.btn_driver.setEnabled(False)
        self._pawnio_force = force

        def work():
            ok, reboot, msg = system.install_pawnio()
            self.bridge.pawnio_done.emit(ok, reboot, msg)

        threading.Thread(target=work, name="pawnio-setup", daemon=True).start()

    def _on_pawnio_done(self, ok: bool, reboot: bool, msg: str) -> None:
        self.btn_driver.setEnabled(True)
        if ok and not reboot:
            self.btn_driver.hide()
            self.card_driver.set("ok", msg)
        elif ok:
            self.card_driver.set("warn", msg)
        else:
            self.card_driver.set("error", msg)
            QMessageBox.warning(self, config.APP_NAME, f"{msg}\n\nDas Tool läuft ohne RGB-Arbeitsspeicher weiter.")
        if self._pawnio_force:
            self._restart_rgb()
        else:
            self._conflict_step()

    # ---- Schritt: andere RGB-Programme
    def _conflict_step(self) -> None:
        found = system.find_conflicts()
        if found:
            names = "\n".join(f"• {name}" for name in found)
            answer = QMessageBox.question(
                self, "Andere RGB-Programme laufen",
                f"Diese Programme steuern ebenfalls RGB und blockieren oft die Erkennung:\n\n{names}\n\n"
                "Sollen sie für diese Sitzung geschlossen werden? Beim nächsten Windows-Start laufen sie "
                "wieder ganz normal.")
            if answer == QMessageBox.Yes:
                procs = [p for hits in found.values() for p in hits]
                failed = system.close_processes(procs)
                if failed:
                    QMessageBox.warning(self, config.APP_NAME, "Nicht beenden liessen sich: " + ", ".join(failed))
                time.sleep(1.0)
        self._start_rgb()

    # ---- Schritt: RGB-Engine
    def _start_rgb(self) -> None:
        self.rgb_ready = False
        self.card_rgb.set("busy", "Starte …")

        def work():
            try:
                self.rgb.start(self.settings.get("zone_sizes", {}), self.bridge.rgb_progress.emit)
                self.bridge.rgb_done.emit(True, "")
            except RGBEngineError as exc:
                self.bridge.rgb_done.emit(False, str(exc))
            except Exception as exc:  # noqa: BLE001
                log.exception("Start der RGB-Engine fehlgeschlagen")
                self.bridge.rgb_done.emit(False, f"Unerwarteter Fehler: {exc}")

        threading.Thread(target=work, name="rgb-start", daemon=True).start()

    def _restart_rgb(self) -> None:
        if self.engine.busy:
            QMessageBox.information(self, config.APP_NAME, BUSY_MSG)
            return
        self.rgb.shutdown()
        if system.pawnio_installed():
            self.card_driver.set("ok", "PawnIO ist installiert. Arbeitsspeicher und Mainboard können erkannt werden.")
            self.btn_driver.hide()
        self._start_rgb()

    def _on_rgb_done(self, ok: bool, message: str) -> None:
        if not ok:
            self.card_rgb.set("error", message)
            self.devices_page.populate([])
            return
        self.rgb_ready = True
        zones = self.rgb.zones()
        devices = len({z["device"] for z in zones})
        if zones:
            self.card_rgb.set("ok", f"Bereit. {devices} Geräte mit {len(zones)} Zonen erkannt.")
        else:
            self.card_rgb.set("warn", "Bereit, aber keine RGB-Geräte gefunden. Adminrechte? Andere RGB-Software offen?")
        known = {z["key"] for z in zones}
        self.settings["devices"] = [k for k in self.settings["devices"] if k in known]
        self.rgb.methods = dict(self.settings.get("device_methods", {}))
        self.devices_page.populate(zones)
        if zones and not self.settings.get("device_check_done"):
            answer = QMessageBox.question(
                self, "Geräte-Check",
                f"{devices} RGB-Geräte gefunden.\n\nSoll das Tool jetzt prüfen, was wirklich leuchtet? Jedes Gerät "
                "und jeder Anschluss blinkt kurz türkis, du bestätigst mit einem Klick. Was nicht reagiert, wird "
                "ausgeschaltet. Dauert etwa eine Minute.")
            if answer == QMessageBox.Yes:
                self.go(1)
                QTimer.singleShot(200, self._run_check)
            else:
                self.settings["device_check_done"] = True

    # ================================================================ CS2
    def _set_cs2(self, path: Path | None) -> None:
        self.cs2_path = path
        if path:
            self.settings["cs2_path"] = str(path)
            self.card_cs2.set("ok", f"Gefunden und kompatibel.\n{path}")
        else:
            self.card_cs2.set("error", "Nicht gefunden. Bitte den CS2-Ordner manuell wählen.")

    def _choose_cs2(self) -> None:
        start = str(self.cs2_path) if self.cs2_path else "C:/"
        chosen = QFileDialog.getExistingDirectory(self, "Ordner „Counter-Strike Global Offensive“ wählen", start)
        if not chosen:
            return
        path = normalize_cs2_dir(Path(chosen))
        if not path:
            QMessageBox.warning(self, config.APP_NAME, "In diesem Ordner wurde kein CS2 gefunden "
                                "(es fehlt der Unterordner game/csgo).")
            return
        self._set_cs2(path)
        self._write_gsi()

    def _write_gsi(self) -> None:
        if not self.cs2_path:
            self.card_gsi.set("warn", "Wartet auf den CS2-Ordner.")
            return
        if not self.gsi:
            return
        try:
            target, changed = write_gsi_config(self.cs2_path, self.gsi.port, self.settings["gsi_token"])
        except OSError as exc:
            self.card_gsi.set("error", f"Config konnte nicht geschrieben werden: {exc}")
            return
        text = f"Bereit auf Port {self.gsi.port} ({target.name})."
        if changed:
            text += "\nFalls CS2 gerade läuft: einmal neu starten."
        others = other_gsi_files(self.cs2_path)
        if others:
            text += f"\nWeitere Configs bleiben aktiv: {', '.join(others)}"
        self.card_gsi.set("ok", text)

    # ================================================================ Geräte-Aktionen
    def _run_check(self) -> None:
        if not self.rgb_ready:
            QMessageBox.information(self, config.APP_NAME, "Die RGB-Engine ist noch nicht bereit.")
            return
        if self.engine.busy:
            QMessageBox.information(self, config.APP_NAME, BUSY_MSG)
            return
        dialog = DeviceCheckDialog(self.rgb, self.settings, self.rgb.zones(), self)
        accepted = dialog.exec() == QDialog.Accepted
        self.devices_page.populate(self.rgb.zones())
        if accepted:
            config.save_settings(self.settings)
            QMessageBox.information(self, "Geräte-Check fertig", dialog.summary())

    def _setup_zone(self, key: str, zone: str, leds_max: int) -> None:
        if self.engine.busy:
            QMessageBox.information(self, config.APP_NAME, BUSY_MSG)
            return
        dialog = ZoneSetupDialog(zone, self.settings.get("zone_layout", {}).get(key), leds_max, self)
        if dialog.exec() != QDialog.Accepted:
            return
        layout = dialog.result_layout()
        try:
            self.rgb.resize(key, layout["total"])
        except Exception as exc:  # noqa: BLE001
            log.exception("LED-Anzahl setzen fehlgeschlagen")
            QMessageBox.warning(self, config.APP_NAME, f"LED-Anzahl konnte nicht gesetzt werden: {exc}")
            return
        self.settings.setdefault("zone_layout", {})[key] = layout
        self.settings.setdefault("zone_sizes", {})[key] = layout["total"]
        self.settings.setdefault("fans_off", {}).pop(key, None)
        if layout["total"] > 0 and key not in self.settings["devices"]:
            self.settings["devices"].append(key)
        elif layout["total"] == 0 and key in self.settings["devices"]:
            self.settings["devices"].remove(key)
        config.save_settings(self.settings)
        self.devices_page.populate(self.rgb.zones())

    def _zone_live_frame(self, key: str, n: int):
        """Aktuelle Farben einer Zone für die Lüfter-Ringe (gedimmt, solange Live nicht läuft)."""
        now = time.monotonic()
        brightness = max(0.0, min(1.0, float(self.settings["options"]["brightness"]) / 100.0))
        frame = self.engine.zone_frame(self.engine.layers(now, self.settings), key, n, brightness, self.settings)
        if not self.engine.running:
            frame = [tuple(int(v * 0.6) for v in c) for c in frame]
        return frame

    def _run_task(self, name: str, fn) -> None:
        def work():
            try:
                fn()
                self.bridge.task_done.emit(name, "")
            except Exception as exc:  # noqa: BLE001
                log.exception("%s fehlgeschlagen", name)
                self.bridge.task_done.emit(name, str(exc))

        threading.Thread(target=work, name=name, daemon=True).start()

    def _test_devices(self, keys: list) -> None:
        if not self.rgb_ready:
            QMessageBox.information(self, config.APP_NAME, "Die RGB-Engine ist noch nicht bereit.")
            return
        if self.engine.busy:
            QMessageBox.information(self, config.APP_NAME, "Während Live läuft, ist kein Test möglich.")
            return

        def test():
            try:
                self.rgb.test(keys)
            except ConnectionError:
                self.rgb.reconnect()
                self.rgb.test(keys)

        self._run_task("Test", test)

    def _on_task_done(self, name: str, error: str) -> None:
        if error:
            QMessageBox.warning(self, config.APP_NAME, f"{name} fehlgeschlagen: {error}")

    # ================================================================ Effekte
    def _ready_for_light(self) -> bool:
        if not self.rgb_ready:
            QMessageBox.information(self, config.APP_NAME, "Die RGB-Engine ist noch nicht bereit.")
            return False
        if not self.settings["devices"]:
            QMessageBox.information(self, config.APP_NAME, "Bitte zuerst unter „Geräte“ mindestens eine Zone wählen.")
            self.go(1)
            return False
        return True

    def _preview(self, sid: str) -> None:
        if self._ready_for_light():
            self.engine.preview(sid)

    # ================================================================ Live
    def _toggle_run(self) -> None:
        if self.engine.running:
            self.engine.stop()
            return
        if not self._ready_for_light():
            return
        config.save_settings(self.settings)
        self.engine.start()

    def _tick(self) -> None:
        now = time.monotonic()
        connected = self.detector.connected(now)
        if connected:
            where = self.detector.info.get("map") or "Hauptmenü"
            self.card_game.set("ok", f"CS2 sendet Daten · {where}")
        elif self.detector.last_update:
            self.card_game.set("warn", "Seit über 30 Sekunden keine Daten. Läuft CS2 noch?")
        else:
            self.card_game.set("busy", "Warte auf CS2 … starte das Spiel.")

        running = self.engine.running
        if self.btn_start.property("running") != running:
            self.btn_start.setProperty("running", running)
            self.btn_start.setText("■  STOPP" if running else "▶  START")
            self.btn_start.style().unpolish(self.btn_start)
            self.btn_start.style().polish(self.btn_start)
        status = self.engine.status
        if status.get("error"):
            self.lbl_top.setText("Fehler")
            self.lbl_sub.setText(f"{status['error']} – Details im Log ({config.LOG_FILE.name}).")
        elif running:
            self.lbl_top.setText(status.get("top") or "Läuft")
            self.lbl_sub.setText(f"{len(self.settings['devices'])} Zonen reagieren auf CS2.")
        else:
            self.lbl_top.setText("Gestoppt")
            self.lbl_sub.setText("Drück auf Start, sobald du bereit bist. Die LEDs unten zeigen schon, "
                                 "was passieren würde.")
        self.side_status.setText("● Live aktiv" if running else ("● CS2 verbunden" if connected else "● Bereit"))
        self.side_status.setStyleSheet(f"color: {theme.OK if running else theme.MUTED};")

        info = self.detector.info if connected else {}
        phase = info.get("map_phase") if info.get("map_phase") == "warmup" else info.get("round_phase")
        names = {"freezetime": "Kaufphase", "live": "Runde läuft", "over": "Runde vorbei", "warmup": "Aufwärmen"}
        bomb = {"planted": "Gelegt", "defused": "Entschärft", "exploded": "Explodiert"}
        c4 = info.get("c4_preview")
        values = {
            "map": info.get("map") or "–",
            "phase": names.get(phase, phase or "–"),
            "team": info.get("team") or "–",
            "health": "–" if info.get("health") is None else f"{info['health']} HP",
            "armor": "–" if info.get("armor") is None else str(info["armor"]),
            "bomb": bomb.get(info.get("bomb"), "–"),
            "c4": "–" if c4 is None else f"{c4} HP nach Explosion",
            "active": ", ".join(self.detector.active_names(now, self.settings["states"])) if connected else "–",
        }
        for key, value in values.items():
            self.info_labels[key].setText(str(value))

    # ================================================================ Ende
    def closeEvent(self, event) -> None:  # noqa: N802
        self.timer.stop()
        self.engine.stop(wait=True)
        config.save_settings(self.settings)
        if self.gsi:
            self.gsi.stop()
        self.rgb.shutdown()
        super().closeEvent(event)
