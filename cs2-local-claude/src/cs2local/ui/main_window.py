"""Hauptfenster: Übersicht, Geräte, Effekte und Live-Steuerung."""
from __future__ import annotations

import logging
import secrets
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox,
    QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import config, system
from ..cs2_setup import find_cs2, normalize_cs2_dir, other_gsi_files, write_gsi_config
from ..engine import LightEngine, state_color
from ..gsi_server import GSIServer
from ..rgb_engine import RGBEngine, RGBEngineError
from ..states import StateDetector
from . import theme

log = logging.getLogger(__name__)

ICONS = {"ok": ("✔", theme.OK), "warn": ("!", theme.WARN), "error": ("✖", theme.ERROR), "busy": ("…", theme.MUTED)}
BUSY_MSG = "Bitte zuerst die Lichtsteuerung stoppen."


class Bridge(QObject):
    """Signale aus Hintergrund-Threads sicher in die Oberfläche bringen."""
    rgb_progress = Signal(str)
    rgb_done = Signal(bool, str)
    test_done = Signal(str)
    pawnio_done = Signal(bool, bool, str)


class StatusCard(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("Card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(14)
        self.icon = QLabel("…")
        self.icon.setFixedSize(34, 34)
        self.icon.setAlignment(Qt.AlignCenter)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(title.upper())
        t.setObjectName("CardTitle")
        self.text = QLabel()
        self.text.setObjectName("CardText")
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        col.addWidget(t)
        col.addWidget(self.text)
        lay.addWidget(self.icon)
        lay.addLayout(col, 1)
        self.set("busy", "Wird geprüft …")

    def set(self, state: str, text: str) -> None:
        symbol, color = ICONS[state]
        self.icon.setText(symbol)
        self.icon.setStyleSheet(
            f"background:{color}22; color:{color}; border-radius:17px; font-size:14pt; font-weight:800;")
        self.text.setText(text)


def _title(text: str, sub: str) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 8)
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
        self.resize(1180, 760)
        self.setMinimumSize(980, 640)

        opts = settings["options"]
        self.bridge = Bridge()
        self.bridge.rgb_progress.connect(lambda msg: self.card_rgb.set("busy", msg))
        self.bridge.rgb_done.connect(self._on_rgb_done)
        self.bridge.test_done.connect(self._on_test_done)
        self.bridge.pawnio_done.connect(self._on_pawnio_done)

        self.rgb = RGBEngine(int(opts["openrgb_port"]))
        self.detector = StateDetector(lambda: self.settings["options"])
        self.engine = LightEngine(self.rgb, self.detector, lambda: self.settings)
        self.gsi: GSIServer | None = None
        self.cs2_path: Path | None = None
        self.rgb_ready = False
        self._populating = False

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
        side.setFixedWidth(230)
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
            btn.clicked.connect(lambda _=False, idx=i: self.stack.setCurrentIndex(idx))
            self.nav.addButton(btn, i)
            sl.addWidget(btn)
            wrap = QScrollArea()
            wrap.setWidgetResizable(True)
            wrap.setFrameShape(QFrame.NoFrame)
            wrap.setStyleSheet("QScrollArea{background:transparent;border:none;}")
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
        lay.setSpacing(14)
        return w, lay

    # ---------------------------------------------------------------- Seite 1
    def _page_overview(self) -> QWidget:
        w, lay = self._page()
        lay.addWidget(_title("Übersicht", "Das Tool prüft dein System und richtet alles für diese Sitzung ein. "
                                          "Alles Nötige ist eingebaut, es wird nichts heruntergeladen."))
        grid = QGridLayout()
        grid.setSpacing(12)
        self.card_admin = StatusCard("Adminrechte")
        self.card_cs2 = StatusCard("Counter-Strike 2")
        self.card_gsi = StatusCard("Game State Integration")
        self.card_driver = StatusCard("Treiber für RGB-Arbeitsspeicher (PawnIO)")
        self.card_rgb = StatusCard("RGB-Engine und Geräte")
        self.card_game = StatusCard("Verbindung zum Spiel")
        cards = [self.card_admin, self.card_cs2, self.card_gsi, self.card_driver, self.card_rgb, self.card_game]
        for i, card in enumerate(cards):
            grid.addWidget(card, i // 2, i % 2)
        lay.addLayout(grid)

        row = QHBoxLayout()
        b1 = QPushButton("CS2-Ordner wählen …")
        b1.clicked.connect(self._choose_cs2)
        b2 = QPushButton("Config neu schreiben")
        b2.clicked.connect(self._write_gsi)
        self.btn_driver = QPushButton("Treiber installieren")
        self.btn_driver.clicked.connect(lambda: self._ask_pawnio(force=True))
        self.btn_driver.hide()
        self.btn_reconnect = QPushButton("Geräte neu suchen")
        self.btn_reconnect.clicked.connect(self._restart_rgb)
        for b in (b1, b2, self.btn_driver, self.btn_reconnect):
            row.addWidget(b)
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
        lay.addWidget(_title("Geräte", "Alle erkannten RGB-Geräte deines PCs. Wähle die Zonen, die auf CS2 "
                                       "reagieren sollen. Bei ARGB-Headern am Mainboard trägst du die Anzahl LEDs "
                                       "deines Streifens oder Lüfters ein."))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Gerät / Zone", "LEDs", "Typ"])
        self.tree.setColumnWidth(0, 440)
        self.tree.setColumnWidth(1, 110)
        self.tree.setMinimumHeight(380)
        self.tree.itemChanged.connect(self._on_tree_changed)
        lay.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.btn_test = QPushButton("Auswahl testen")
        self.btn_test.clicked.connect(self._test_devices)
        b_all = QPushButton("Alle")
        b_all.clicked.connect(lambda: self._check_all(True))
        b_none = QPushButton("Keine")
        b_none.clicked.connect(lambda: self._check_all(False))
        for b in (self.btn_test, b_all, b_none):
            row.addWidget(b)
        self.dev_status = QLabel("Warte auf die RGB-Engine …")
        self.dev_status.setObjectName("Muted")
        row.addWidget(self.dev_status, 1)
        nxt = QPushButton("Weiter zu den Effekten  →")
        nxt.setObjectName("Primary")
        nxt.clicked.connect(lambda: self.go(2))
        row.addWidget(nxt)
        lay.addLayout(row)
        return w

    # ---------------------------------------------------------------- Seite 3
    def _page_effects(self) -> QWidget:
        w, lay = self._page()
        lay.addWidget(_title("Effekte", "Lege fest, wie deine LEDs auf jede Situation reagieren. Bei mehreren "
                                        "gleichzeitig gewinnt die höhere Priorität. „Team“ nimmt die Farbe deines "
                                        "Teams (CT/T). „Vorschau“ zeigt den Effekt 3 Sekunden auf deinen Geräten."))
        opts_box = QFrame()
        opts_box.setObjectName("Card")
        og = QGridLayout(opts_box)
        og.setContentsMargins(16, 14, 16, 14)
        og.setHorizontalSpacing(18)
        opts = self.settings["options"]

        self.sl_bright = QSlider(Qt.Horizontal)
        self.sl_bright.setRange(5, 100)
        self.sl_bright.setValue(int(opts["brightness"]))
        self.lbl_bright = QLabel(f"{opts['brightness']} %")
        self.sl_bright.valueChanged.connect(self._on_brightness)

        def spin(key, lo, hi, suffix, tip=""):
            s = QSpinBox()
            s.setRange(lo, hi)
            s.setSuffix(suffix)
            s.setValue(int(opts[key]))
            s.setToolTip(tip)
            s.valueChanged.connect(lambda v: self._set_opt(key, v))
            return s

        self.sp_low = spin("low_health_threshold", 2, 99, " HP")
        self.sp_crit = spin("critical_health_threshold", 1, 98, " HP")
        self.sp_ammo = spin("low_ammo_percent", 5, 90, " %")
        self.sp_fps = spin("fps", 5, 60, " fps", "Wie oft pro Sekunde die LEDs aktualisiert werden. "
                                                "Arbeitsspeicher mag eher 15–20.")
        og.addWidget(QLabel("Gesamthelligkeit"), 0, 0)
        og.addWidget(self.sl_bright, 0, 1)
        og.addWidget(self.lbl_bright, 0, 2)
        og.addWidget(QLabel("Wenig Leben ab"), 0, 3)
        og.addWidget(self.sp_low, 0, 4)
        og.addWidget(QLabel("Kritisch ab"), 0, 5)
        og.addWidget(self.sp_crit, 0, 6)
        og.addWidget(QLabel("Bildrate"), 1, 0)
        og.addWidget(self.sp_fps, 1, 1)
        og.addWidget(QLabel("Munition knapp ab"), 1, 3)
        og.addWidget(self.sp_ammo, 1, 4)
        reset = QPushButton("Standardwerte")
        reset.clicked.connect(self._reset_effects)
        og.addWidget(reset, 1, 6)
        og.setColumnStretch(1, 1)
        lay.addWidget(opts_box)

        self.rows_holder = QVBoxLayout()
        lay.addLayout(self.rows_holder)
        self._build_effect_rows()

        row = QHBoxLayout()
        row.addStretch(1)
        nxt = QPushButton("Weiter zu Live  →")
        nxt.setObjectName("Primary")
        nxt.clicked.connect(lambda: self.go(3))
        row.addWidget(nxt)
        lay.addLayout(row)
        return w

    def _build_effect_rows(self) -> None:
        while self.rows_holder.count():
            old = self.rows_holder.takeAt(0).widget()
            if old:
                old.deleteLater()
        rows = QWidget()
        rows.setObjectName("Rows")
        g = QGridLayout(rows)
        g.setContentsMargins(16, 12, 16, 12)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(8)
        heads = ["", "Situation", "Farbe", "Team", "Effekt", "Tempo", "Dauer", "Helligkeit", "Priorität", ""]
        for col, head in enumerate(heads):
            h = QLabel(head.upper())
            h.setObjectName("CardTitle")
            g.addWidget(h, 0, col)
        states = self.settings["states"]
        self._color_buttons: dict = {}
        for r, sid in enumerate(config.STATE_ORDER, start=1):
            st = states[sid]
            chk = QCheckBox()
            chk.setChecked(bool(st["enabled"]))
            chk.toggled.connect(lambda v, s=sid: self._set_state(s, "enabled", v))
            name = QLabel(st["name"])
            name.setToolTip(st["desc"])
            color = QPushButton()
            color.setObjectName("ColorButton")
            color.clicked.connect(lambda _=False, s=sid: self._pick_color(s))
            self._color_buttons[sid] = color
            team = QCheckBox()
            team.setChecked(bool(st.get("team_color")))
            team.setToolTip("Statt einer eigenen Farbe die Farbe deines Teams verwenden")
            team.setEnabled(sid not in ("team_ct", "team_t"))
            team.toggled.connect(lambda v, s=sid: (self._set_state(s, "team_color", v), self._paint_colors()))
            effect = QComboBox()
            for key, label in config.EFFECTS.items():
                effect.addItem(label, key)
            effect.setCurrentIndex(max(0, effect.findData(st["effect"])))
            effect.currentIndexChanged.connect(
                lambda _i, s=sid, c=effect: self._set_state(s, "effect", c.currentData()))
            speed = QDoubleSpinBox()
            speed.setRange(0.1, 15.0)
            speed.setSingleStep(0.1)
            speed.setSuffix(" Hz")
            speed.setValue(float(st["speed"]))
            speed.valueChanged.connect(lambda v, s=sid: self._set_state(s, "speed", v))
            dur = QDoubleSpinBox()
            dur.setRange(0.1, 15.0)
            dur.setSingleStep(0.1)
            dur.setSuffix(" s")
            dur.setValue(float(st["duration"] or 1.0))
            dur.valueChanged.connect(lambda v, s=sid: self._set_state(s, "duration", v))
            dur.setEnabled(st["kind"] == "event")
            dur.setToolTip("Nur für kurze Ereignisse (Kill, Treffer, Runde, Bombe entschärft …)")
            inten = QSpinBox()
            inten.setRange(0, 100)
            inten.setSuffix(" %")
            inten.setValue(int(st.get("intensity", 100)))
            inten.valueChanged.connect(lambda v, s=sid: (self._set_state(s, "intensity", v), self._paint_colors()))
            prio = QSpinBox()
            prio.setRange(0, 200)
            prio.setValue(int(st["priority"]))
            prio.valueChanged.connect(lambda v, s=sid: self._set_state(s, "priority", v))
            prev = QPushButton("Vorschau")
            prev.clicked.connect(lambda _=False, s=sid: self._preview(s))
            for col, widget in enumerate([chk, name, color, team, effect, speed, dur, inten, prio, prev]):
                g.addWidget(widget, r, col)
        g.setColumnStretch(1, 1)
        self.rows_holder.addWidget(rows)
        self._paint_colors()

    # ---------------------------------------------------------------- Seite 4
    def _page_live(self) -> QWidget:
        w, lay = self._page()
        lay.addWidget(_title("Live", "Starte CS2 ganz normal. Sobald du auf Start drückst, reagieren deine LEDs "
                                     "auf das Spiel. Stopp stellt die vorherigen Farben wieder her."))
        top = QHBoxLayout()
        top.setSpacing(24)
        self.btn_start = QPushButton("▶  START")
        self.btn_start.setObjectName("StartButton")
        self.btn_start.setProperty("running", False)
        self.btn_start.setMinimumWidth(260)
        self.btn_start.clicked.connect(self._toggle_run)
        top.addWidget(self.btn_start, 0, Qt.AlignTop)

        swatch_box = QFrame()
        swatch_box.setObjectName("Card")
        sb = QVBoxLayout(swatch_box)
        sb.setContentsMargins(18, 16, 18, 16)
        t = QLabel("AKTUELLE FARBE")
        t.setObjectName("CardTitle")
        self.swatch = QFrame()
        self.swatch.setFixedHeight(70)
        self.lbl_top = QLabel("Gestoppt")
        self.lbl_top.setStyleSheet("font-size:13pt;font-weight:600;")
        sb.addWidget(t)
        sb.addWidget(self.swatch)
        sb.addWidget(self.lbl_top)
        top.addWidget(swatch_box, 1)
        lay.addLayout(top)

        info = QFrame()
        info.setObjectName("Card")
        ig = QGridLayout(info)
        ig.setContentsMargins(18, 16, 18, 16)
        ig.setHorizontalSpacing(30)
        ig.setVerticalSpacing(10)
        self.info_labels: dict = {}
        fields = [("map", "Karte"), ("phase", "Phase"), ("team", "Team"), ("health", "Leben"),
                  ("armor", "Rüstung"), ("bomb", "Bombe"), ("c4", "C4-Vorschau"), ("active", "Aktive Zustände")]
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
        lay.addWidget(hint)
        lay.addStretch(1)
        return w

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
            self.card_driver.set("ok", "Installiert. Arbeitsspeicher und Mainboard können erkannt werden.")
            self._conflict_step()
            return
        self.btn_driver.show()
        if self.settings.get("pawnio_declined"):
            self.card_driver.set("warn", "Nicht installiert. RGB-Arbeitsspeicher wird übersprungen.")
            self._conflict_step()
            return
        self._ask_pawnio(force=False)

    def _ask_pawnio(self, force: bool) -> None:
        if not system.is_admin():
            QMessageBox.information(self, config.APP_NAME, "Für die Treiber-Installation braucht das Tool "
                                    "Adminrechte. Bitte das Tool neu starten und die Windows-Abfrage bestätigen.")
            if not force:
                self.card_driver.set("warn", "Nicht installiert (keine Adminrechte).")
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
            self.card_driver.set("warn", "Nicht installiert. RGB-Arbeitsspeicher wird übersprungen.")
            if not force:
                self._conflict_step()
            return
        self.settings["pawnio_declined"] = False
        self.card_driver.set("busy", "Installiere PawnIO …")
        self.btn_driver.setEnabled(False)

        def work():
            ok, reboot, msg = system.install_pawnio()
            self.bridge.pawnio_done.emit(ok, reboot, msg)

        self._pawnio_force = force
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
        if getattr(self, "_pawnio_force", False):
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
        self.btn_reconnect.setEnabled(False)
        self.card_rgb.set("busy", "Starte …")
        self.dev_status.setText("Warte auf die RGB-Engine …")

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
            self.card_driver.set("ok", "Installiert. Arbeitsspeicher und Mainboard können erkannt werden.")
            self.btn_driver.hide()
        self._start_rgb()

    def _on_rgb_done(self, ok: bool, message: str) -> None:
        self.btn_reconnect.setEnabled(True)
        if not ok:
            self.card_rgb.set("error", message)
            self.dev_status.setText("RGB-Engine nicht verbunden.")
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
        self._populate_tree(zones)

    # ================================================================ CS2
    def _set_cs2(self, path: Path | None) -> None:
        self.cs2_path = path
        if path:
            self.settings["cs2_path"] = str(path)
            self.card_cs2.set("ok", f"Gefunden und kompatibel:\n{path}")
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

    # ================================================================ Geräte
    def _populate_tree(self, zones: list) -> None:
        self._populating = True
        self.tree.clear()
        selected = set(self.settings["devices"])
        parents: dict = {}
        for z in zones:
            parent = parents.get(z["device"])
            if parent is None:
                parent = QTreeWidgetItem([z["device"], "", z["type"]])
                parent.setFlags(parent.flags() | Qt.ItemIsAutoTristate | Qt.ItemIsUserCheckable)
                parents[z["device"]] = parent
                self.tree.addTopLevelItem(parent)
            item = QTreeWidgetItem([z["zone"], "" if z["resizable"] else str(z["leds"]), ""])
            item.setData(0, Qt.UserRole, z["key"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if z["key"] in selected else Qt.Unchecked)
            parent.addChild(item)
            if z["resizable"]:
                spin = QSpinBox()
                spin.setRange(z["leds_min"], z["leds_max"] or 300)
                spin.setValue(z["leds"])
                spin.setToolTip("Anzahl LEDs am ARGB-Header (steht auf der Verpackung von Streifen oder Lüfter)")
                spin.editingFinished.connect(lambda k=z["key"], s=spin: self._resize_zone(k, s.value()))
                self.tree.setItemWidget(item, 1, spin)
        self.tree.expandAll()
        self._populating = False
        self._update_dev_status()

    def _selected_keys(self) -> list:
        keys = []
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.checkState(0) == Qt.Checked:
                    keys.append(child.data(0, Qt.UserRole))
        return keys

    def _on_tree_changed(self, _item, column: int) -> None:
        if self._populating or column != 0:
            return
        self.settings["devices"] = self._selected_keys()
        self._update_dev_status()

    def _update_dev_status(self) -> None:
        n = len(self.settings["devices"])
        self.dev_status.setText(f"{n} Zone{'n' if n != 1 else ''} ausgewählt")

    def _check_all(self, on: bool) -> None:
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, Qt.Checked if on else Qt.Unchecked)

    def _resize_zone(self, key: str, size: int) -> None:
        if self.rgb.led_count(key) == size:
            return
        if self.engine.busy:
            QMessageBox.information(self, config.APP_NAME, BUSY_MSG)
            return
        try:
            self.rgb.resize(key, size)
            self.settings.setdefault("zone_sizes", {})[key] = size
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, config.APP_NAME, f"LED-Anzahl konnte nicht gesetzt werden: {exc}")

    def _test_devices(self) -> None:
        if not self._ready_for_light():
            return
        if self.engine.busy:
            QMessageBox.information(self, config.APP_NAME, "Während Live läuft, ist kein Test möglich.")
            return
        keys = list(self.settings["devices"])
        self.btn_test.setEnabled(False)
        self.dev_status.setText("Teste … die gewählten Zonen blinken türkis.")

        def work():
            try:
                self.rgb.test(keys)
                self.bridge.test_done.emit("")
            except Exception as exc:  # noqa: BLE001
                self.bridge.test_done.emit(str(exc))

        threading.Thread(target=work, name="rgb-test", daemon=True).start()

    def _on_test_done(self, error: str) -> None:
        self.btn_test.setEnabled(True)
        if error:
            QMessageBox.warning(self, config.APP_NAME, f"Test fehlgeschlagen: {error}")
        self._update_dev_status()

    # ================================================================ Effekte
    def _set_state(self, sid: str, key: str, value) -> None:
        self.settings["states"][sid][key] = value

    def _set_opt(self, key: str, value) -> None:
        self.settings["options"][key] = value

    def _on_brightness(self, value: int) -> None:
        self._set_opt("brightness", value)
        self.lbl_bright.setText(f"{value} %")

    def _paint_colors(self) -> None:
        states = self.settings["states"]
        team = self.detector.team
        for sid, button in self._color_buttons.items():
            st = states[sid]
            r, g, b = state_color(st, states, team)
            shown = "#{:02x}{:02x}{:02x}".format(*st["color"])
            button.setStyleSheet(f"background: rgb({r},{g},{b});")
            button.setToolTip("Teamfarbe" if st.get("team_color") else f"Farbe {shown}")
            button.setEnabled(not st.get("team_color"))

    def _pick_color(self, sid: str) -> None:
        st = self.settings["states"][sid]
        r, g, b = st["color"]
        chosen = QColorDialog.getColor(QColor(r, g, b), self, f"Farbe für „{st['name']}“")
        if chosen.isValid():
            self._set_state(sid, "color", [chosen.red(), chosen.green(), chosen.blue()])
            self._paint_colors()

    def _reset_effects(self) -> None:
        if QMessageBox.question(self, config.APP_NAME, "Alle Effekte auf die Standardwerte zurücksetzen?") \
                != QMessageBox.Yes:
            return
        self.settings["states"] = config.default_states()
        self._build_effect_rows()

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
            self.lbl_top.setText(f"Fehler: {status['error']}")
        elif self.engine.busy and status.get("top"):
            self.lbl_top.setText(status["top"])
        else:
            self.lbl_top.setText("Gestoppt")
        r, g, b = status.get("color", (0, 0, 0)) if self.engine.busy else (0, 0, 0)
        self.swatch.setStyleSheet(f"background: rgb({r},{g},{b}); border-radius: 12px; border:1px solid {theme.BORDER};")
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
