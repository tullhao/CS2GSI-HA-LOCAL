"""Die Seiten „Geräte“ und „Effekte“: grafische Karten statt Tabellen."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup, QColorDialog, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QPushButton, QSlider,
    QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import config
from ..engine import state_color
from .widgets import ColorSwatch, DeviceIcon, LedPreview, ToggleSwitch, ZoneChip, state_preview_source


# ------------------------------------------------------------------------------------------- Hilfen
class FlowLayout(QLayout):
    """Ordnet Elemente nebeneinander an und bricht in die nächste Zeile um."""

    def __init__(self, parent=None, spacing: int = 8):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):  # noqa: N802
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):  # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):  # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _do_layout(self, rect, test_only):
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() and line > 0:
                x, y, line = rect.x(), y + line + self._spacing, 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line = max(line, hint.height())
        return y + line - rect.y()


def _label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


def _segmented(labels, parent) -> tuple[QHBoxLayout, QButtonGroup]:
    row = QHBoxLayout()
    row.setSpacing(6)
    group = QButtonGroup(parent)
    group.setExclusive(True)
    for i, text in enumerate(labels):
        btn = QPushButton(text)
        btn.setObjectName("Segment")
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        group.addButton(btn, i)
        row.addWidget(btn)
    group.button(0).setChecked(True)
    return row, group


# ------------------------------------------------------------------------------------------- Geräte
class DeviceCard(QFrame):
    selection_changed = Signal(str, bool)
    resize_requested = Signal(str, int)
    test_requested = Signal(list)

    def __init__(self, device: str, zones: list, selected: set):
        super().__init__()
        self.setObjectName("Card")
        self.zones = zones
        self.chips: dict = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(14)
        self.icon = DeviceIcon(zones[0]["type_id"])
        head.addWidget(self.icon)
        col = QVBoxLayout()
        col.setSpacing(2)
        title = _label(device, "CardHeading")
        vendor = zones[0].get("vendor") or ""
        sub = zones[0]["type"] + (f"  ·  {vendor}" if vendor and vendor.lower() not in device.lower() else "")
        col.addWidget(title)
        col.addWidget(_label(sub, "Muted"))
        col.addStretch(1)
        head.addLayout(col, 1)
        self.master = ToggleSwitch()
        self.master.setToolTip("Alle Zonen dieses Geräts verwenden")
        self.master.clicked.connect(self._toggle_all)
        head.addWidget(self.master, 0, Qt.AlignTop)
        lay.addLayout(head)

        chips_box = QWidget()
        flow = FlowLayout(chips_box)
        for z in zones:
            chip = ZoneChip(z["key"], z["zone"], z["leds"])
            chip.setChecked(z["key"] in selected)
            chip.setEnabled(z["leds"] > 0)
            chip.setToolTip("Zone ohne LEDs. Trag unten die Anzahl LEDs ein." if z["leds"] == 0 else "")
            chip.toggled_key.connect(self._chip_toggled)
            flow.addWidget(chip)
            self.chips[z["key"]] = chip
        lay.addWidget(chips_box)

        resizable = [z for z in zones if z["resizable"]]
        if resizable:
            box = QFrame()
            box.setObjectName("Inset")
            grid = QGridLayout(box)
            grid.setContentsMargins(12, 10, 12, 10)
            grid.setHorizontalSpacing(12)
            hint = _label("Anschlüsse für LED-Streifen und Lüfter: Trag ein, wie viele LEDs dranhängen "
                          "(steht auf der Verpackung).", "Muted", wrap=True)
            grid.addWidget(hint, 0, 0, 1, 3)
            for row, z in enumerate(resizable, start=1):
                spin = QSpinBox()
                spin.setRange(z["leds_min"], z["leds_max"] or 300)
                spin.setValue(z["leds"])
                spin.setSuffix(" LEDs")
                spin.setFixedWidth(110)
                spin.editingFinished.connect(lambda k=z["key"], s=spin: self.resize_requested.emit(k, s.value()))
                grid.addWidget(_label(z["zone"]), row, 0)
                grid.addWidget(spin, row, 1)
            grid.setColumnStretch(2, 1)
            lay.addWidget(box)

        foot = QHBoxLayout()
        self.summary = _label("", "Muted")
        foot.addWidget(self.summary, 1)
        test = QPushButton("Testen")
        test.setObjectName("Small")
        test.setToolTip("Lässt die gewählten Zonen dieses Geräts türkis blinken")
        test.clicked.connect(self._test)
        foot.addWidget(test)
        lay.addLayout(foot)
        self._refresh()

    def _chip_toggled(self, key: str, on: bool) -> None:
        self.selection_changed.emit(key, on)
        self._refresh()

    def _toggle_all(self) -> None:
        on = self.master.isChecked()
        for chip in self.chips.values():
            if chip.isEnabled() and chip.isChecked() != on:
                chip.setChecked(on)
        self._refresh()

    def _test(self) -> None:
        keys = [k for k, c in self.chips.items() if c.isChecked()] or \
               [k for k, c in self.chips.items() if c.isEnabled()]
        self.test_requested.emit(keys)

    def set_leds(self, key: str, leds: int) -> None:
        if key in self.chips:
            self.chips[key].set_leds(leds)
            self.chips[key].setEnabled(True)

    def _refresh(self) -> None:
        chosen = [c for c in self.chips.values() if c.isChecked()]
        usable = [c for c in self.chips.values() if c.isEnabled()]
        self.icon.set_active(bool(chosen))
        self.master.setChecked(bool(usable) and len(chosen) == len(usable))
        leds = sum(c.leds for c in chosen)
        self.summary.setText(f"{len(chosen)} von {len(self.chips)} Zonen aktiv · {leds} LEDs" if chosen
                             else "Nicht verwendet")


class DevicesPage(QWidget):
    selection_changed = Signal()
    resize_requested = Signal(str, int)
    test_requested = Signal(list)
    rescan_requested = Signal()

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings
        self.cards: dict = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        bar = QHBoxLayout()
        self.summary = _label("Warte auf die RGB-Engine …", "Muted")
        bar.addWidget(self.summary, 1)
        for text, slot in (("Alle", lambda: self._set_all(True)), ("Keine", lambda: self._set_all(False)),
                           ("Geräte neu suchen", self.rescan_requested.emit)):
            btn = QPushButton(text)
            btn.setObjectName("Small")
            btn.clicked.connect(slot)
            bar.addWidget(btn)
        lay.addLayout(bar)
        self.grid = QGridLayout()
        self.grid.setSpacing(14)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)
        lay.addLayout(self.grid)
        self.empty = _label("Noch keine Geräte. Die RGB-Engine sucht gerade, oder es wurde nichts gefunden "
                            "(Adminrechte? Andere RGB-Software offen?).", "Muted", wrap=True)
        lay.addWidget(self.empty)
        lay.addStretch(1)

    def populate(self, zones: list) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.cards.clear()
        selected = set(self.settings["devices"])
        by_device: dict = {}
        for z in zones:
            by_device.setdefault(z["device"], []).append(z)
        for i, (device, dz) in enumerate(by_device.items()):
            card = DeviceCard(device, dz, selected)
            card.selection_changed.connect(self._on_select)
            card.resize_requested.connect(self.resize_requested.emit)
            card.test_requested.connect(self.test_requested.emit)
            self.grid.addWidget(card, i // 2, i % 2)
            self.cards[device] = card
        self.empty.setVisible(not by_device)
        self._update_summary()

    def update_zone(self, key: str, leds: int) -> None:
        for card in self.cards.values():
            card.set_leds(key, leds)

    def _on_select(self, key: str, on: bool) -> None:
        devices = self.settings["devices"]
        if on and key not in devices:
            devices.append(key)
        elif not on and key in devices:
            devices.remove(key)
        self._update_summary()
        self.selection_changed.emit()

    def _set_all(self, on: bool) -> None:
        for card in self.cards.values():
            card.master.setChecked(on)
            card._toggle_all()

    def _update_summary(self) -> None:
        n = len(self.settings["devices"])
        self.summary.setText(f"{len(self.cards)} Geräte gefunden · {n} Zone{'n' if n != 1 else ''} ausgewählt"
                             if self.cards else "Keine Geräte")


# ------------------------------------------------------------------------------------------- Effekte
SPEED_EFFECTS = {"blink", "pulse", "flicker", "chase"}


class StateCard(QFrame):
    changed = Signal()
    device_preview = Signal(str)

    def __init__(self, sid: str, settings: dict, team_fn):
        super().__init__()
        self.setObjectName("Card")
        self.sid = sid
        self.settings = settings
        self.team_fn = team_fn
        cfg = self.cfg
        cfg["_id"] = sid
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        head = QHBoxLayout()
        self.toggle = ToggleSwitch(bool(cfg["enabled"]))
        self.toggle.clicked.connect(lambda: self._set("enabled", self.toggle.isChecked()))
        head.addWidget(self.toggle)
        head.addSpacing(6)
        head.addWidget(_label(cfg["name"], "CardHeading"))
        tag = _label("kurz" if cfg["kind"] == "event" else "solange aktiv", "Tag")
        tag.setToolTip("Kurzes Ereignis mit fester Dauer" if cfg["kind"] == "event"
                       else "Leuchtet, solange die Situation andauert")
        head.addWidget(tag)
        head.addStretch(1)
        show = QPushButton("Auf Geräten zeigen")
        show.setObjectName("Small")
        show.clicked.connect(lambda: self.device_preview.emit(self.sid))
        head.addWidget(show)
        lay.addLayout(head)

        lay.addWidget(_label(cfg["desc"], "Muted", wrap=True))
        self.preview = LedPreview()
        self.preview.set_source(state_preview_source(cfg, self.current_color))
        lay.addWidget(self.preview)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.swatch = ColorSwatch()
        self.swatch.clicked.connect(self._pick_color)
        row.addWidget(self.swatch)
        self.team = ToggleSwitch(bool(cfg.get("team_color")))
        self.team.clicked.connect(lambda: self._set("team_color", self.team.isChecked()))
        if sid not in ("team_ct", "team_t"):
            row.addWidget(self.team)
            row.addWidget(_label("Teamfarbe", "Muted"))
        row.addSpacing(8)
        self.effect = QComboBox()
        for key, label in config.EFFECTS.items():
            self.effect.addItem(label, key)
        self.effect.setCurrentIndex(max(0, self.effect.findData(cfg["effect"])))
        self.effect.currentIndexChanged.connect(lambda _i: self._set("effect", self.effect.currentData()))
        row.addWidget(self.effect)
        row.addStretch(1)
        self.more = QPushButton("Feineinstellungen  ▾")
        self.more.setObjectName("Link")
        self.more.setCheckable(True)
        self.more.toggled.connect(self._toggle_details)
        row.addWidget(self.more)
        lay.addLayout(row)

        self.details = QFrame()
        self.details.setObjectName("Inset")
        grid = QGridLayout(self.details)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        self.speed = self._slider(grid, 0, "Tempo", 1, 150, int(round(cfg["speed"] * 10)),
                                  lambda v: f"{v / 10:.1f} pro Sekunde", lambda v: self._set("speed", v / 10))
        self.duration = self._slider(grid, 1, "Dauer", 1, 150, int(round((cfg["duration"] or 1) * 10)),
                                     lambda v: f"{v / 10:.1f} Sekunden", lambda v: self._set("duration", v / 10))
        self.intensity = self._slider(grid, 2, "Helligkeit", 0, 100, int(cfg.get("intensity", 100)),
                                      lambda v: f"{v} %", lambda v: self._set("intensity", v))
        grid.addWidget(_label("Vorrang"), 3, 0)
        self.prio = QSpinBox()
        self.prio.setRange(0, 200)
        self.prio.setValue(int(cfg["priority"]))
        self.prio.setFixedWidth(90)
        self.prio.setToolTip("Sind mehrere Situationen gleichzeitig aktiv, gewinnt der höhere Wert.")
        self.prio.valueChanged.connect(lambda v: self._set("priority", v))
        grid.addWidget(self.prio, 3, 1)
        grid.addWidget(_label("Höherer Wert gewinnt, wenn mehreres gleichzeitig passiert.", "Muted"), 3, 2)
        grid.setColumnStretch(1, 1)
        self.details.hide()
        lay.addWidget(self.details)
        self._sync()

    @property
    def cfg(self) -> dict:
        return self.settings["states"][self.sid]

    def _slider(self, grid, row, title, lo, hi, value, fmt, on_change):
        slider = QSlider(Qt.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(value)
        text = _label(fmt(value), "Muted")
        text.setFixedWidth(130)

        def changed(v):
            text.setText(fmt(v))
            on_change(v)

        slider.valueChanged.connect(changed)
        name = _label(title)
        grid.addWidget(name, row, 0)
        grid.addWidget(slider, row, 1)
        grid.addWidget(text, row, 2)
        slider._row_widgets = (name, text)  # noqa: SLF001
        return slider

    def current_color(self):
        return state_color(self.cfg, self.settings["states"], self.team_fn())

    def _set(self, key, value) -> None:
        self.cfg[key] = value
        if key in ("effect", "duration"):
            self.preview.restart()
        self._sync()
        self.changed.emit()

    def _toggle_details(self, on: bool) -> None:
        self.details.setVisible(on)
        self.more.setText("Feineinstellungen  ▴" if on else "Feineinstellungen  ▾")

    def _pick_color(self) -> None:
        if self.cfg.get("team_color"):
            return
        r, g, b = self.cfg["color"]
        chosen = QColorDialog.getColor(QColor(r, g, b), self, f"Farbe für „{self.cfg['name']}“")
        if chosen.isValid():
            self._set("color", [chosen.red(), chosen.green(), chosen.blue()])

    def _sync(self) -> None:
        cfg = self.cfg
        team = bool(cfg.get("team_color"))
        self.swatch.set_color(cfg["color"], team)
        self.swatch.setEnabled(not team)
        self.effect.setEnabled(cfg["enabled"])
        is_event = cfg["kind"] == "event"
        uses_speed = cfg["effect"] in SPEED_EFFECTS
        for slider, visible in ((self.speed, uses_speed), (self.duration, is_event)):
            slider.setVisible(visible)
            for w in slider._row_widgets:  # noqa: SLF001
                w.setVisible(visible)
        self.setProperty("disabled", not cfg["enabled"])
        self.style().unpolish(self)
        self.style().polish(self)

    def reload(self) -> None:
        """Nach „Standardwerte“: alle Bedienelemente auf die neuen Werte setzen."""
        cfg = self.cfg
        cfg["_id"] = self.sid
        for w, value in ((self.toggle, cfg["enabled"]), (self.team, cfg.get("team_color"))):
            w.setChecked(bool(value))
        for w, value in ((self.speed, int(round(cfg["speed"] * 10))),
                         (self.duration, int(round((cfg["duration"] or 1) * 10))),
                         (self.intensity, int(cfg.get("intensity", 100))), (self.prio, int(cfg["priority"]))):
            w.blockSignals(True)
            w.setValue(value)
            w.blockSignals(False)
        self.effect.blockSignals(True)
        self.effect.setCurrentIndex(max(0, self.effect.findData(cfg["effect"])))
        self.effect.blockSignals(False)
        self.preview.set_source(state_preview_source(cfg, self.current_color))
        self._sync()


class EffectsPage(QWidget):
    device_preview = Signal(str)
    changed = Signal()

    def __init__(self, settings: dict, live_team_fn):
        super().__init__()
        self.settings = settings
        self.live_team_fn = live_team_fn
        self.preview_team = "CT"
        self.cards: list = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        top = QHBoxLayout()
        cats, self.cat_group = _segmented([c[0] for c in config.CATEGORIES], self)
        top.addLayout(cats)
        top.addStretch(1)
        top.addWidget(_label("Vorschau als", "Muted"))
        teams, self.team_group = _segmented(["CT", "T"], self)
        self.team_group.idClicked.connect(self._set_team)
        top.addLayout(teams)
        lay.addLayout(top)

        self.stack = QStackedWidget()
        for title, text, ids, options in config.CATEGORIES:
            self.stack.addWidget(self._category_page(title, text, ids, options))
        self.cat_group.idClicked.connect(self.stack.setCurrentIndex)
        lay.addWidget(self.stack)

        general = QFrame()
        general.setObjectName("Card")
        g = QHBoxLayout(general)
        g.setContentsMargins(18, 12, 18, 12)
        g.setSpacing(14)
        g.addWidget(_label("Gesamthelligkeit"))
        self.bright = QSlider(Qt.Horizontal)
        self.bright.setRange(5, 100)
        self.bright.setValue(int(settings["options"]["brightness"]))
        self.bright_text = _label(f"{self.bright.value()} %", "Muted")
        self.bright.valueChanged.connect(self._brightness)
        g.addWidget(self.bright, 1)
        g.addWidget(self.bright_text)
        g.addSpacing(20)
        g.addWidget(_label("Bildrate"))
        fps = QSpinBox()
        fps.setRange(5, 60)
        fps.setSuffix(" pro Sekunde")
        fps.setValue(int(settings["options"]["fps"]))
        fps.setToolTip("Wie oft pro Sekunde die LEDs aktualisiert werden. Arbeitsspeicher mag eher 15–20.")
        fps.valueChanged.connect(lambda v: self._opt("fps", v))
        g.addWidget(fps)
        g.addSpacing(20)
        reset = QPushButton("Alles auf Standard")
        reset.setObjectName("Small")
        reset.clicked.connect(self._reset)
        g.addWidget(reset)
        lay.addWidget(general)

    def _team(self):
        return self.live_team_fn() or self.preview_team

    def _set_team(self, idx: int) -> None:
        self.preview_team = "CT" if idx == 0 else "T"
        for card in self.cards:
            card._sync()  # noqa: SLF001

    def _category_page(self, title, text, ids, options) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(_label(text, "PageSub", wrap=True), 1)
        for key, label, suffix, lo, hi in options:
            head.addWidget(_label(label))
            spin = QSpinBox()
            spin.setRange(lo, hi)
            spin.setSuffix(suffix)
            spin.setValue(int(self.settings["options"][key]))
            spin.valueChanged.connect(lambda v, k=key: self._opt(k, v))
            head.addWidget(spin)
        lay.addLayout(head)
        grid = QGridLayout()
        grid.setSpacing(14)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        for i, sid in enumerate(ids):
            card = StateCard(sid, self.settings, self._team)
            card.device_preview.connect(self.device_preview.emit)
            card.changed.connect(self._card_changed)
            self.cards.append(card)
            grid.addWidget(card, i // 2, i % 2, Qt.AlignTop)
        lay.addLayout(grid)
        lay.addStretch(1)
        return page

    def _card_changed(self) -> None:
        for card in self.cards:  # Teamfarben können andere Karten betreffen
            card._sync()  # noqa: SLF001
        self.changed.emit()

    def _opt(self, key, value) -> None:
        self.settings["options"][key] = value
        self.changed.emit()

    def _brightness(self, value: int) -> None:
        self.bright_text.setText(f"{value} %")
        self._opt("brightness", value)

    def _reset(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        if QMessageBox.question(self, config.APP_NAME, "Alle Effekte auf die Standardwerte zurücksetzen?") \
                != QMessageBox.Yes:
            return
        self.settings["states"].clear()
        self.settings["states"].update(config.default_states())
        for card in self.cards:
            card.reload()
        self.changed.emit()
