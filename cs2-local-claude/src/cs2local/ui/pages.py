"""Die Seiten „Geräte“ und „Effekte“: grafische Karten statt Tabellen."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QPushButton, QSlider,
    QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import config
from ..engine import state_color
from .widgets import ColorSwatch, DeviceIcon, FanRings, LedPreview, ToggleSwitch, ZoneChip, state_preview_source


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
        return Qt.Orientation(0)

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


class ResponsiveGrid(QWidget):
    """Karten in zwei Spalten, auf schmalen Bildschirmen in einer."""

    def __init__(self, min_column: int = 450):
        super().__init__()
        self.min_column = min_column
        self.widgets: list = []
        self.columns = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(14)

    def set_widgets(self, widgets: list) -> None:
        for w in self.widgets:
            self.grid.removeWidget(w)
            if w not in widgets:
                w.deleteLater()
        self.widgets = list(widgets)
        self.columns = 0
        self._relayout()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        cols = 2 if self.width() >= 2 * self.min_column + 14 else 1
        if cols == self.columns:
            return
        self.columns = cols
        for w in self.widgets:
            self.grid.removeWidget(w)
        for i, w in enumerate(self.widgets):
            self.grid.addWidget(w, i // cols, i % cols)
        for c in range(2):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)


# ------------------------------------------------------------------------------------------- Geräte
class DeviceCard(QFrame):
    selection_changed = Signal(str, bool)
    setup_requested = Signal(str, str, int)
    fans_changed = Signal(str, list)
    test_requested = Signal(list)

    def __init__(self, device: str, zones: list, selected: set, settings: dict, frame_fn=None):
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
        head.addWidget(self.icon, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        title = _label(device, "CardHeading")
        vendor = zones[0].get("vendor") or ""
        sub = zones[0]["type"] + (f"  ·  {vendor}" if vendor and vendor.lower() not in device.lower() else "")
        col.addWidget(title)
        col.addWidget(_label(sub, "Muted"))
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
            chip.setToolTip("Noch nicht eingerichtet. Unten auf „Einrichten“ klicken." if z["leds"] == 0 else "")
            chip.toggled_key.connect(self._chip_toggled)
            flow.addWidget(chip)
            self.chips[z["key"]] = chip
        lay.addWidget(chips_box)

        resizable = [z for z in zones if z["resizable"]]
        self.rings: dict = {}
        for z in resizable:
            layout = settings.get("zone_layout", {}).get(z["key"])
            box = QFrame()
            box.setObjectName("Inset")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(14, 12, 14, 12)
            bl.setSpacing(10)
            row = QHBoxLayout()
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(_label(z["zone"], "CardHeading"))
            if layout:
                text = f"{layout['count']} × {layout['name']}  ·  {z['leds']} LEDs"
            elif z["leds"]:
                text = f"{z['leds']} LEDs, Hardware nicht angegeben"
            else:
                text = "Nicht eingerichtet: Was hängt an diesem Anschluss?"
            col.addWidget(_label(text, "Muted", wrap=True))
            row.addLayout(col, 1)
            setup = QPushButton("Ändern …" if layout else "Einrichten …")
            setup.setObjectName("Small" if layout else "Primary")
            setup.clicked.connect(lambda _=False, k=z["key"], n=z["zone"], hi=z["leds_max"]:
                                  self.setup_requested.emit(k, n, hi))
            row.addWidget(setup, 0, Qt.AlignTop)
            bl.addLayout(row)
            if layout and layout.get("count", 0) > 0:
                rings = FanRings(layout["count"], layout["per"], layout.get("kind", "fan"),
                                 settings.get("fans_off", {}).get(z["key"], []))
                rings.setToolTip("Klick auf einen Lüfter schaltet ihn für CS2 an oder aus")
                rings.changed.connect(lambda off, k=z["key"]: self.fans_changed.emit(k, off))
                if frame_fn:
                    rings.set_source(lambda n, k=z["key"]: frame_fn(k, n))
                bl.addWidget(rings)
                bl.addWidget(_label("Klick auf einen Lüfter, um ihn ein- oder auszuschalten.", "Muted"))
                self.rings[z["key"]] = rings
            lay.addWidget(box)

        lay.addStretch(1)
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
    setup_requested = Signal(str, str, int)
    test_requested = Signal(list)
    rescan_requested = Signal()

    def __init__(self, settings: dict, frame_fn=None):
        super().__init__()
        self.settings = settings
        self.frame_fn = frame_fn
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
        self.grid = ResponsiveGrid(min_column=430)
        lay.addWidget(self.grid)
        self.empty = _label("Noch keine Geräte. Die RGB-Engine sucht gerade, oder es wurde nichts gefunden "
                            "(Adminrechte? Andere RGB-Software offen?).", "Muted", wrap=True)
        lay.addWidget(self.empty)
        lay.addStretch(1)

    def populate(self, zones: list) -> None:
        self.cards.clear()
        selected = set(self.settings["devices"])
        by_device: dict = {}
        for z in zones:
            by_device.setdefault(z["device"], []).append(z)
        for device, dz in by_device.items():
            card = DeviceCard(device, dz, selected, self.settings, self.frame_fn)
            card.selection_changed.connect(self._on_select)
            card.setup_requested.connect(self.setup_requested.emit)
            card.fans_changed.connect(self._on_fans)
            card.test_requested.connect(self.test_requested.emit)
            self.cards[device] = card
        self.grid.set_widgets(list(self.cards.values()))
        self.empty.setVisible(not by_device)
        self._update_summary()

    def _on_fans(self, key: str, off: list) -> None:
        if off:
            self.settings.setdefault("fans_off", {})[key] = off
        else:
            self.settings.setdefault("fans_off", {}).pop(key, None)

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
SPEED_EFFECTS = {"blink", "pulse", "flicker", "chase", "spin"}


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
        show = QPushButton("▶  Zeigen")
        show.setObjectName("Small")
        show.setToolTip("Spielt den Effekt 3 Sekunden auf deinen Geräten ab")
        show.clicked.connect(lambda: self.device_preview.emit(self.sid))
        row.addWidget(show)
        self.more = QPushButton("Mehr  ▾")
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
        self.more.setText("Weniger  ▴" if on else "Mehr  ▾")

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
        grid = ResponsiveGrid(min_column=470)
        cards = []
        for sid in ids:
            card = StateCard(sid, self.settings, self._team)
            card.device_preview.connect(self.device_preview.emit)
            card.changed.connect(self._card_changed)
            cards.append(card)
        self.cards.extend(cards)
        grid.set_widgets(cards)
        lay.addWidget(grid)
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


# ------------------------------------------------------------------------------------------- Einrichten
class ZoneSetupDialog(QDialog):
    """Was hängt an einem ARGB-Anschluss? Modell und Anzahl wählen, LEDs werden ausgerechnet."""

    def __init__(self, zone: str, layout: dict | None, leds_max: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{zone} einrichten")
        self.setMinimumWidth(460)
        self.leds_max = leds_max or 1000
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(14)
        lay.addWidget(_label(f"Was hängt an „{zone}“?", "CardHeading"))
        lay.addWidget(_label("Die Hardware meldet das nicht selbst (auch iCUE fragt danach). Wähl das Modell und "
                             "die Anzahl, die LEDs rechnet das Tool aus. Bei mehreren Lüftern an einem Hub: "
                             "alle zusammen zählen.", "Muted", wrap=True))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        self.model = QComboBox()
        for name, per, kind in config.HARDWARE_PRESETS:
            self.model.addItem(f"{name}  ({per} LEDs)" if name != "Eigene Angabe" else name, (name, per, kind))
        self.count = QSpinBox()
        self.count.setRange(0, 12)
        self.per = QSpinBox()
        self.per.setRange(1, 300)
        self.per.setSuffix(" LEDs pro Stück")
        self.total = _label("", "CardHeading")
        grid.addWidget(_label("Modell"), 0, 0)
        grid.addWidget(self.model, 0, 1)
        grid.addWidget(_label("Anzahl"), 1, 0)
        grid.addWidget(self.count, 1, 1)
        grid.addWidget(_label("LEDs"), 2, 0)
        grid.addWidget(self.per, 2, 1)
        grid.addWidget(_label("Zusammen"), 3, 0)
        grid.addWidget(self.total, 3, 1)
        lay.addLayout(grid)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Übernehmen")
        buttons.button(QDialogButtonBox.Ok).setObjectName("Primary")
        buttons.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.model.currentIndexChanged.connect(self._model_changed)
        self.count.valueChanged.connect(self._update)
        self.per.valueChanged.connect(self._update)
        if layout:
            idx = max(0, self.model.findText(layout.get("name", ""), Qt.MatchStartsWith))
            self.model.setCurrentIndex(idx)
            self.count.setValue(int(layout.get("count", 1)))
            self.per.setValue(int(layout.get("per", 10)))
        else:
            self.count.setValue(1)
            self._model_changed()
        self._update()

    def _model_changed(self, *_):
        name, per, _kind = self.model.currentData()
        self.per.setValue(per)
        self.per.setEnabled(name == "Eigene Angabe" or "allgemein" in name)
        self._update()

    def _update(self, *_):
        total = self.count.value() * self.per.value()
        ok = total <= self.leds_max
        self.total.setText(f"{total} LEDs" + ("" if ok else f"  (max. {self.leds_max})"))
        self.total.setStyleSheet("" if ok else "color: #ff5c5c;")

    def result_layout(self) -> dict:
        name, _per, kind = self.model.currentData()
        count, per = self.count.value(), self.per.value()
        return {"name": name, "kind": kind, "count": count, "per": per,
                "total": min(count * per, self.leds_max)}
