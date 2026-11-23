"""Hauptfenster: Übersicht, Geräte, Effekte und Live-Steuerung."""
from __future__ import annotations

import logging
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import config, system, vendor_apps
from ..cs2_setup import find_cs2, normalize_cs2_dir, other_gsi_files, write_gsi_config
from ..engine import LightEngine
from ..gsi_server import GSIServer
from ..rgb_engine import RGBEngine, RGBEngineError
from ..states import StateDetector
from . import theme
from .check_dialog import DeviceCheckDialog
from .pages import DevicesPage, EffectsPage, ZoneSetupDialog
from .setup_view import ClosingDialog, SetupView
from .widgets import LedPreview
from ..i18n import set_language, tr

log = logging.getLogger(__name__)

def busy_msg() -> str:
    return tr("Bitte zuerst die Lichtsteuerung stoppen.")


class Bridge(QObject):
    """Signale aus Hintergrund-Threads sicher in die Oberfläche bringen."""
    rgb_progress = Signal(str)
    rgb_done = Signal(bool, str)
    task_done = Signal(str, str)
    pawnio_done = Signal(bool, bool, str)
    software_done = Signal(object)
    close_step = Signal(int)
    close_done = Signal()


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
        self.bridge.software_done.connect(self._on_software_done)

        self.rgb = RGBEngine(int(opts["openrgb_port"]), settings.get("engine", "stable"))
        self._retry_devices: list = []  # nach Wechsel auf die neueste Engine erneut prüfen
        self._retry_stage = ""
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
        brand = QLabel(tr("CS2 Local"))
        brand.setObjectName("Brand")
        sub = QLabel(tr("RGB · BUILT WITH CLAUDE"))
        sub.setObjectName("BrandSub")
        sl.addWidget(brand)
        sl.addWidget(sub)
        sl.addSpacing(22)

        self.stack = QStackedWidget()
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        pages = [
            (tr("⌂   Übersicht"), self._page_overview()),
            (tr("▦   Geräte"), self._page_devices()),
            (tr("✦   Effekte"), self._page_effects()),
            (tr("▶   Live"), self._page_live()),
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
        gear = QPushButton(tr("⚙   Einstellungen"))
        gear.setObjectName("Nav")
        gear.setCursor(Qt.PointingHandCursor)
        gear.clicked.connect(self._open_settings)
        sl.addWidget(gear)
        sl.addSpacing(8)
        self.side_status = QLabel(tr("● Bereit"))
        self.side_status.setObjectName("Muted")
        sl.addWidget(self.side_status)
        foot = QLabel(tr("v{v0} · portabel · GPL-2.0", v0=config.VERSION))
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
        lay.addWidget(_title(tr("Übersicht"), tr("Das Tool prüft dein System und richtet alles für diese Sitzung ein. Alles Nötige ist eingebaut, es wird nichts heruntergeladen.")))
        self.setup_view = SetupView([tr("Adminrechte"), tr("Counter-Strike 2"), tr("Spieldaten (Game State Integration)"),
                                     tr("Andere RGB-Software"), tr("Treiber für RGB-Arbeitsspeicher"),
                                     tr("RGB-Engine und Geräte"), tr("Verbindung zum Spiel")])
        (self.card_admin, self.card_cs2, self.card_gsi, self.card_software, self.card_driver, self.card_rgb,
         self.card_game) = self.setup_view.rows
        lay.addWidget(self.setup_view)

        row = QHBoxLayout()
        for text, slot in ((tr("⌕  CS2-Ordner wählen"), self._choose_cs2), (tr("↻  Config neu schreiben"), self._write_gsi)):
            b = QPushButton(text)
            b.setObjectName("Small")
            b.clicked.connect(slot)
            row.addWidget(b)
        self.btn_driver = QPushButton(tr("⬇  Treiber installieren"))
        self.btn_driver.setObjectName("Small")
        self.btn_driver.clicked.connect(lambda: self._ask_pawnio(force=True))
        self.btn_driver.hide()
        row.addWidget(self.btn_driver)
        row.addStretch(1)
        nxt = QPushButton(tr("Weiter zu den Geräten  →"))
        nxt.setObjectName("Primary")
        nxt.clicked.connect(lambda: self.go(1))
        row.addWidget(nxt)
        lay.addLayout(row)
        lay.addStretch(1)
        return w

    # ---------------------------------------------------------------- Seite 2
    def _page_devices(self) -> QWidget:
        w, lay = self._page()
        lay.addWidget(_title(tr("Geräte"), tr("Alle RGB-Geräte, die dein PC gefunden hat. Schalte ein, was auf CS2 reagieren soll, oder wähle einzelne Zonen.")))
        self.devices_page = DevicesPage(self.settings, self._zone_live_frame)
        self.devices_page.setup_requested.connect(self._setup_zone)
        self.devices_page.check_requested.connect(self._run_check)
        self.devices_page.empty_requested.connect(self._zone_empty)
        self.devices_page.test_requested.connect(self._test_devices)
        self.devices_page.rescan_requested.connect(self._restart_rgb)
        lay.addWidget(self.devices_page)
        lay.addLayout(self._next_button(tr("Weiter zu den Effekten  →"), 2))
        return w

    # ---------------------------------------------------------------- Seite 3
    def _page_effects(self) -> QWidget:
        w, lay = self._page()
        lay.addWidget(_title(tr("Effekte"), tr("Wie sollen deine LEDs reagieren? Jede Karte zeigt live, wie es aussieht. „▶ Zeigen“ spielt ihn 3 Sekunden auf deinen Geräten ab.")))
        self.effects_page = EffectsPage(self.settings, self._live_team)
        self.effects_page.device_preview.connect(self._preview)
        lay.addWidget(self.effects_page)
        lay.addLayout(self._next_button(tr("Weiter zu Live  →"), 3))
        return w

    def _live_team(self):
        return self.detector.team if self.detector.connected() else None

    # ---------------------------------------------------------------- Seite 4
    def _page_live(self) -> QWidget:
        w, lay = self._page()
        lay.addWidget(_title(tr("Live"), tr("Starte CS2 ganz normal. Sobald du auf Start drückst, reagieren deine LEDs auf das Spiel. Stopp stellt die vorherigen Farben wieder her.")))
        hero = QFrame()
        hero.setObjectName("Card")
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(24, 22, 24, 22)
        hl.setSpacing(14)
        top = QHBoxLayout()
        self.btn_start = QPushButton(tr("▶  START"))
        self.btn_start.setObjectName("StartButton")
        self.btn_start.setProperty("running", False)
        self.btn_start.setMinimumWidth(240)
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self._toggle_run)
        top.addWidget(self.btn_start)
        top.addSpacing(20)
        col = QVBoxLayout()
        self.lbl_top = QLabel(tr("Gestoppt"))
        self.lbl_top.setObjectName("LiveState")
        self.lbl_sub = QLabel(tr("Drück auf Start, sobald du bereit bist."))
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
        fields = [("map", tr("Karte")), ("phase", tr("Phase")), ("team", tr("Team")), ("health", tr("Leben")),
                  ("armor", tr("Rüstung")), ("bomb", tr("Bombe")), ("c4", tr("C4-Vorschau")), ("active", tr("Aktive Situationen"))]
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
        hint = QLabel(tr("Tipp: Wurde die Config neu geschrieben, während CS2 schon lief, starte CS2 einmal neu."))
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
            self.card_admin.set("ok", tr("Läuft mit Adminrechten."))
        else:
            self.card_admin.set("warn", tr("Ohne Adminrechte werden Arbeitsspeicher und manche Mainboards nicht erkannt."))

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
            self.card_gsi.set("error", tr("Empfang nicht möglich: {v0}", v0=exc))
            self.gsi = None
        self._write_gsi()
        self._software_step()

    # ---- Schritt: PawnIO
    def _driver_step(self) -> None:
        if system.pawnio_installed():
            self.card_driver.set("ok", tr("PawnIO ist installiert. Arbeitsspeicher und Mainboard können erkannt werden."))
            self._start_rgb()
            return
        self.btn_driver.show()
        if self.settings.get("pawnio_declined"):
            self.card_driver.set("warn", tr("PawnIO ist nicht installiert. RGB-Arbeitsspeicher wird übersprungen. Unten auf „Treiber installieren“ klicken, wenn du ihn willst."))
            self._start_rgb()
            return
        self._ask_pawnio(force=False)

    def _ask_pawnio(self, force: bool) -> None:
        if not system.is_admin():
            QMessageBox.information(self, config.APP_NAME, tr("Für die Treiber-Installation braucht das Tool Adminrechte. Bitte das Tool neu starten und die Windows-Abfrage bestätigen."))
            if not force:
                self.card_driver.set("warn", tr("PawnIO ist nicht installiert (keine Adminrechte)."))
                self._start_rgb()
            return
        box = QMessageBox(self)
        box.setWindowTitle(tr("Treiber für RGB-Arbeitsspeicher"))
        box.setIcon(QMessageBox.Information)
        box.setText(tr("<b>Für RGB-Arbeitsspeicher braucht Windows den Treiber „PawnIO“.</b>"))
        box.setInformativeText(
            tr("Ohne diesen Treiber kann kein Programm die LEDs deines Arbeitsspeichers (und mancher Mainboards) ansprechen. Das gilt auch für OpenRGB.\n\n• PawnIO ist Open Source und digital signiert.\n• Er ist in diesem Tool enthalten, es wird nichts heruntergeladen.\n• Er wird einmalig als Windows-Treiber installiert und bleibt danach installiert. Entfernen kannst du ihn jederzeit unter Einstellungen → Apps → PawnIO.\n• Ohne ihn funktionieren Tastatur, Maus, Lüfter und ARGB-Header trotzdem.\n\nJetzt installieren?"))
        install = box.addButton(tr("Jetzt installieren"), QMessageBox.AcceptRole)
        box.addButton(tr("Ohne Arbeitsspeicher weiter"), QMessageBox.RejectRole)
        box.setDefaultButton(install)
        box.exec()
        if box.clickedButton() is not install:
            self.settings["pawnio_declined"] = True
            self.card_driver.set("warn", tr("PawnIO ist nicht installiert. RGB-Arbeitsspeicher wird übersprungen."))
            if not force:
                self._start_rgb()
            return
        self.settings["pawnio_declined"] = False
        self.card_driver.set("busy", tr("Installiere PawnIO …"))
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
            self._start_rgb()

    # ---- Schritt: andere RGB-Programme
    def _software_step(self) -> None:
        self.card_software.set("busy", tr("Prüfe, welche RGB-Programme installiert sind und laufen …"))
        threading.Thread(target=lambda: self.bridge.software_done.emit(vendor_apps.scan()),
                         name="software-scan", daemon=True).start()

    def _on_software_done(self, found: dict) -> None:
        active = vendor_apps.running(found)
        idle = [name for name in found if name not in active]
        idle_text = tr(" Installiert, aber nicht aktiv: {v0}.", v0=', '.join(idle)) if idle else ""
        if not active:
            self.card_software.set("ok", tr("Keine störende RGB-Software aktiv.") + idle_text)
            self._driver_step()
            return
        names = "\n".join(f"•  {name}" for name in active)
        box = QMessageBox(self)
        box.setWindowTitle(tr("Andere RGB-Software"))
        box.setIcon(QMessageBox.Information)
        count = len(active)
        box.setText(tr("<b>{v0} Programme steuern deine LEDs gerade selbst und blockieren die Geräte:</b>", v0=count) if count != 1 else tr("<b>1 Programm steuert deine LEDs gerade selbst und blockiert die Geräte:</b>"))
        box.setInformativeText(
            tr("{v0}\n\nDas Tool pausiert sie für diese Sitzung. Beim Schliessen startet es sie automatisch wieder, dann ist deine gewohnte Beleuchtung sofort zurück.", v0=names) + ("\n\n" + idle_text.strip() if idle else ""))
        pause = box.addButton(tr("Pausieren und weiter"), QMessageBox.AcceptRole)
        box.addButton(tr("Laufen lassen"), QMessageBox.RejectRole)
        box.setDefaultButton(pause)
        box.exec()
        if box.clickedButton() is pause:
            self.card_software.set("busy", tr("Pausiere …"))
            failed = vendor_apps.pause(found)
            if failed:
                self.card_software.set("warn", tr("Pausiert, aber nicht alles liess sich stoppen: {v0}", v0='; '.join(failed)))
            else:
                self.card_software.set("ok", tr("{v0} pausiert. Startet beim Schliessen wieder.", v0=', '.join(active)))
            time.sleep(1.5)
        else:
            self.card_software.set("warn", tr("Läuft weiter: {v0}. Diese Geräte reagieren evtl. nicht.", v0=', '.join(active)))
        self._driver_step()

    # ---- Schritt: RGB-Engine
    def _start_rgb(self) -> None:
        self.rgb_ready = False
        self.card_rgb.set("busy", tr("Starte …"))

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
            QMessageBox.information(self, config.APP_NAME, busy_msg())
            return
        self.rgb.shutdown()
        if system.pawnio_installed():
            self.card_driver.set("ok", tr("PawnIO ist installiert. Arbeitsspeicher und Mainboard können erkannt werden."))
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
            self.card_rgb.set("ok", tr("Bereit. {v0} Geräte mit {v1} Zonen erkannt.", v0=devices, v1=len(zones)))
        else:
            self.card_rgb.set("warn", tr("Bereit, aber keine RGB-Geräte gefunden. Adminrechte? Andere RGB-Software offen?"))
        known = {z["key"] for z in zones}
        self.settings["devices"] = [k for k in self.settings["devices"] if k in known]
        engine_name = tr("neueste Entwicklungsversion") if self.rgb.variant == "dev" else tr("stabile Version")
        self.card_rgb.set(self.card_rgb.state, self.card_rgb.text.text() + tr("  ·  Engine: {v0}", v0=engine_name))
        if self._retry_devices:  # nach dem Engine-Wechsel nur die betroffenen Geräte erneut prüfen
            retry, self._retry_devices = self._retry_devices, []
            self.rgb.methods = dict(self.settings.get("device_methods", {}))
            self.devices_page.populate(zones)
            self.go(1)
            QTimer.singleShot(300, lambda: self._run_check(retry))
            return
        self.rgb.methods = dict(self.settings.get("device_methods", {}))
        self.devices_page.populate(zones)
        if zones and not self.settings.get("device_check_done"):
            answer = QMessageBox.question(
                self, tr("Geräte-Check"),
                tr("{v0} RGB-Geräte gefunden.\n\nSoll das Tool jetzt prüfen, was wirklich leuchtet? Jedes Gerät und jeder Anschluss blinkt kurz türkis, du bestätigst mit einem Klick. Was nicht reagiert, wird ausgeschaltet. Dauert etwa eine Minute.", v0=devices))
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
            self.card_cs2.set("ok", tr("Gefunden und kompatibel.\n{v0}", v0=path))
        else:
            self.card_cs2.set("error", tr("Nicht gefunden. Bitte den CS2-Ordner manuell wählen."))

    def _choose_cs2(self) -> None:
        start = str(self.cs2_path) if self.cs2_path else "C:/"
        chosen = QFileDialog.getExistingDirectory(self, tr("Ordner „Counter-Strike Global Offensive“ wählen"), start)
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
            self.card_gsi.set("warn", tr("Wartet auf den CS2-Ordner."))
            return
        if not self.gsi:
            return
        try:
            target, changed = write_gsi_config(self.cs2_path, self.gsi.port, self.settings["gsi_token"])
        except OSError as exc:
            self.card_gsi.set("error", tr("Config konnte nicht geschrieben werden: {v0}", v0=exc))
            return
        text = tr("Bereit auf Port {v0} ({v1}).", v0=self.gsi.port, v1=target.name)
        if changed:
            text += tr("\nFalls CS2 gerade läuft: einmal neu starten.")
        others = other_gsi_files(self.cs2_path)
        if others:
            text += tr("\nWeitere Configs bleiben aktiv: {v0}", v0=', '.join(others))
        self.card_gsi.set("ok", text)

    # ================================================================ Geräte-Aktionen
    def _run_check(self, only_devices=None) -> None:
        if not self.rgb_ready:
            QMessageBox.information(self, config.APP_NAME, tr("Die RGB-Engine ist noch nicht bereit."))
            return
        if self.engine.busy:
            QMessageBox.information(self, config.APP_NAME, busy_msg())
            return
        dialog = DeviceCheckDialog(self.rgb, self.settings, self.rgb.zones(), self, only_devices)
        accepted = dialog.exec() == QDialog.Accepted
        self.devices_page.populate(self.rgb.zones())
        if not accepted:
            return
        config.save_settings(self.settings)
        failed = dialog.failed_devices
        if self._retry_stage == "dev":  # Ergebnis des zweiten Versuchs mit der neuesten Engine
            self._retry_stage = ""
            if failed:
                self._switch_engine("stable")
                QMessageBox.information(
                    self, tr("Geräte-Check"),
                    tr("{v0} reagiert auch mit der neuesten RGB-Engine nicht. Das Gerät wird von OpenRGB (noch) nicht unterstützt. Das Tool nutzt wieder die stabile Version.", v0=', '.join(failed)))
            else:
                QMessageBox.information(self, tr("Geräte-Check"),
                                        tr("Mit der neuesten RGB-Engine funktioniert es. Das Tool verwendet sie ab jetzt."))
            return
        if failed and self.rgb.dev_available() and self.settings.get("engine") != "dev":
            answer = QMessageBox.question(
                self, tr("Geräte-Check"),
                tr("{v0}\n\n{v1} reagiert auf keine Methode. Sehr neue Hardware braucht manchmal die neueste RGB-Engine (OpenRGB-Entwicklungsversion, im Tool enthalten).\n\nDamit erneut versuchen? Es werden nur diese Geräte noch einmal geprüft.", v0=dialog.summary(), v1=', '.join(failed)))
            if answer == QMessageBox.Yes:
                self._retry_devices = list(failed)
                self._retry_stage = "dev"
                self._switch_engine("dev")
                return
        QMessageBox.information(self, tr("Geräte-Check fertig"), dialog.summary())

    def _switch_engine(self, variant: str) -> None:
        self.settings["engine"] = variant
        config.save_settings(self.settings)
        self.rgb.shutdown()
        self.rgb.variant = variant
        log.info("Wechsle RGB-Engine auf %s", variant)
        self._start_rgb()

    def _setup_zone(self, key: str, zone: str, leds_max: int) -> None:
        if self.engine.busy:
            QMessageBox.information(self, config.APP_NAME, busy_msg())
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

    def _zone_empty(self, key: str) -> None:
        """Anschluss als „nichts angeschlossen“ markieren."""
        if self.engine.busy:
            QMessageBox.information(self, config.APP_NAME, busy_msg())
            return
        try:
            self.rgb.resize(key, 0)
        except Exception:  # noqa: BLE001
            log.exception("Zone leeren fehlgeschlagen")
        self.settings.setdefault("zone_layout", {})[key] = {"name": tr("Nichts angeschlossen"), "kind": "none",
                                                            "count": 0, "per": 0, "total": 0}
        self.settings.setdefault("zone_sizes", {})[key] = 0
        if key in self.settings["devices"]:
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
            QMessageBox.information(self, config.APP_NAME, tr("Die RGB-Engine ist noch nicht bereit."))
            return
        if self.engine.busy:
            QMessageBox.information(self, config.APP_NAME, tr("Während Live läuft, ist kein Test möglich."))
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
            QMessageBox.information(self, config.APP_NAME, tr("Die RGB-Engine ist noch nicht bereit."))
            return False
        if not self.settings["devices"]:
            QMessageBox.information(self, config.APP_NAME, tr("Bitte zuerst unter „Geräte“ mindestens eine Zone wählen."))
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
            where = self.detector.info.get("map") or tr("Hauptmenü")
            self.card_game.set("ok", tr("CS2 sendet Daten · {v0}", v0=where))
        elif self.detector.last_update:
            self.card_game.set("warn", tr("Seit über 30 Sekunden keine Daten. Läuft CS2 noch?"))
        else:
            self.card_game.set("busy", tr("Warte auf CS2 … starte das Spiel."))

        self.setup_view.refresh_headline()
        running = self.engine.running
        if self.btn_start.property("running") != running:
            self.btn_start.setProperty("running", running)
            self.btn_start.setText(tr("■  STOPP") if running else tr("▶  START"))
            self.btn_start.style().unpolish(self.btn_start)
            self.btn_start.style().polish(self.btn_start)
        status = self.engine.status
        if status.get("error"):
            self.lbl_top.setText(tr("Fehler"))
            self.lbl_sub.setText(tr("{v0} – Details im Log ({v1}).", v0=status['error'], v1=config.LOG_FILE.name))
        elif running:
            self.lbl_top.setText(tr(status["top"]) if status.get("top") else tr("Läuft"))
            self.lbl_sub.setText(tr("{v0} Zonen reagieren auf CS2.", v0=len(self.settings['devices'])))
        else:
            self.lbl_top.setText(tr("Gestoppt"))
            self.lbl_sub.setText(tr("Drück auf Start, sobald du bereit bist. Die LEDs unten zeigen schon, was passieren würde."))
        self.side_status.setText(tr("● Live aktiv") if running else (tr("● CS2 verbunden") if connected else tr("● Bereit")))
        self.side_status.setStyleSheet(f"color: {theme.OK if running else theme.MUTED};")

        info = self.detector.info if connected else {}
        phase = info.get("map_phase") if info.get("map_phase") == "warmup" else info.get("round_phase")
        names = {"freezetime": tr("Kaufphase"), "live": tr("Runde läuft"), "over": tr("Runde vorbei"), "warmup": tr("Aufwärmen")}
        bomb = {"planted": tr("Gelegt"), "defused": tr("Entschärft"), "exploded": tr("Explodiert")}
        c4 = info.get("c4_preview")
        values = {
            "map": info.get("map") or "–",
            "phase": names.get(phase, phase or "–"),
            "team": info.get("team") or "–",
            "health": "–" if info.get("health") is None else f"{info['health']} HP",
            "armor": "–" if info.get("armor") is None else str(info["armor"]),
            "bomb": bomb.get(info.get("bomb"), "–"),
            "c4": "–" if c4 is None else tr("{v0} HP nach Explosion", v0=c4),
            "active": ", ".join(tr(n) for n in self.detector.active_names(now, self.settings["states"])) if connected else "–",
        }
        for key, value in values.items():
            self.info_labels[key].setText(str(value))

    # ================================================================ Ende
    def closeEvent(self, event) -> None:  # noqa: N802
        if getattr(self, "_shutdown_done", False):
            super().closeEvent(event)
            return
        event.ignore()
        if getattr(self, "_closing", False):
            return
        self._closing = True
        self.timer.stop()
        pending = vendor_apps.load_pending()
        apps = sorted({p.get("vendor", "") for p in pending["processes"]} - {""})
        steps = [tr("Farben zurücksetzen"), tr("RGB-Engine beenden")]
        if pending["services"] or pending["processes"]:
            steps.append(tr("Wieder starten: ") + (", ".join(apps) if apps else tr("pausierte RGB-Software")))
        self._closing_view = ClosingDialog(steps, self)
        self._closing_view.show()
        self.bridge.close_step.connect(self._closing_view.set_step)
        self.bridge.close_done.connect(self._finish_close)

        def work():
            try:
                self.bridge.close_step.emit(0)
                self.engine.stop(wait=True)
                config.save_settings(self.settings)
                if self.gsi:
                    self.gsi.stop()
                self.bridge.close_step.emit(1)
                self.rgb.shutdown()
                if len(steps) > 2 and not getattr(self, "_restart_after_close", False):
                    self.bridge.close_step.emit(2)
                    errors = vendor_apps.resume()
                    if errors:
                        log.warning("Neustart der Hersteller-Software unvollständig: %s", errors)
            except Exception:  # noqa: BLE001
                log.exception("Fehler beim Beenden")
            self.bridge.close_step.emit(len(steps))
            self.bridge.close_done.emit()

        threading.Thread(target=work, name="shutdown", daemon=True).start()

    def _finish_close(self) -> None:
        self._shutdown_done = True
        if getattr(self, "_restart_after_close", False):  # Sprachwechsel: Tool neu starten
            try:
                args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
                subprocess.Popen([sys.executable, *args], env=vendor_apps._clean_launch_env(),  # noqa: SLF001
                                 cwd=str(config.app_dir()), creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
            except OSError:
                log.exception("Neustart fehlgeschlagen")
        QTimer.singleShot(400, self.close)

    def _open_settings(self) -> None:
        from .settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.settings, self)
        dlg.exec()
        code = dlg.language()
        if code == self.settings.get("language"):
            return
        self.settings["language"] = code
        self.settings["language_chosen"] = True
        config.save_settings(self.settings)
        set_language(code)  # Frage gleich in der neuen Sprache
        answer = QMessageBox.question(self, config.APP_NAME,
                                      tr("Die Sprache wird nach einem Neustart des Tools aktiv. Jetzt neu starten?"))
        if answer == QMessageBox.Yes:
            self._restart_after_close = True
            self.close()
