"""Startablauf: ein Fortschrittsbalken aus Segmenten (ein Segment pro Schritt) und eine schlichte Liste darunter.

Jedes Segment ist grau (offen), animiert (läuft), grün (ok), orange (Hinweis) oder rot (Fehler).
Ein Hinweis oder Fehler hält den Rest nicht auf.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from . import theme
from ..i18n import tr

STATE_COLORS = {"pending": "#2a2f3a", "busy": theme.ACCENT, "ok": theme.OK, "warn": theme.WARN, "error": theme.ERROR}
ICONS = {"pending": "", "busy": "…", "ok": "✓", "warn": "!", "error": "✕"}


class StepBar(QWidget):
    def __init__(self, count: int, parent=None):
        super().__init__(parent)
        self.states = ["pending"] * count
        self.setFixedHeight(10)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(40)

    def set_state(self, index: int, state: str) -> None:
        self.states[index] = state
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(self.states)
        gap = 6
        w = (self.width() - gap * (n - 1)) / n
        pulse = 0.55 + 0.45 * math.sin(time.monotonic() * 5)
        for i, state in enumerate(self.states):
            color = QColor(STATE_COLORS[state])
            if state == "busy":
                color.setAlphaF(pulse)
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(i * (w + gap), 0, w, self.height()), 5, 5)


class StepRow(QWidget):
    """Eine Zeile der Startliste. API wie die alten Statuskarten: set(state, text)."""

    def __init__(self, title: str, index: int, bar: StepBar):
        super().__init__()
        self.index, self.bar = index, bar
        self.state = "pending"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 10, 4, 10)
        lay.setSpacing(14)
        self.icon = QLabel()
        self.icon.setFixedSize(28, 28)
        self.icon.setAlignment(Qt.AlignCenter)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.title = QLabel(title)
        self.title.setObjectName("StepTitle")
        self.text = QLabel(tr("Wartet …"))
        self.text.setObjectName("Muted")
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        col.addWidget(self.title)
        col.addWidget(self.text)
        lay.addWidget(self.icon, 0, Qt.AlignTop)
        lay.addLayout(col, 1)
        self.set("pending", tr("Wartet …"))

    def set(self, state: str, text: str) -> None:
        self.state = state
        color = STATE_COLORS[state]
        if state == "pending":
            self.icon.setStyleSheet(f"border: 2px solid {color}; border-radius: 14px;")
        else:
            c = QColor(color)
            self.icon.setStyleSheet(f"background: rgba({c.red()},{c.green()},{c.blue()},45); color: {color}; "
                                    "border-radius: 14px; font-weight: 800; font-size: 11pt;")
        self.icon.setText(ICONS[state])
        self.text.setText(text)
        self.bar.set_state(self.index, state)


class SetupView(QFrame):
    """Fortschrittsbalken + Schrittliste in einer Karte, mit Zusammenfassung oben."""

    def __init__(self, titles: list):
        super().__init__()
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 14)
        lay.setSpacing(6)
        self.headline = QLabel(tr("Wird eingerichtet …"))
        self.headline.setObjectName("CardHeading")
        lay.addWidget(self.headline)
        lay.addSpacing(6)
        self.bar = StepBar(len(titles))
        lay.addWidget(self.bar)
        lay.addSpacing(8)
        self.rows = []
        for i, title in enumerate(titles):
            if i:
                line = QFrame()
                line.setObjectName("Divider")
                line.setFixedHeight(1)
                lay.addWidget(line)
            row = StepRow(title, i, self.bar)
            self.rows.append(row)
            lay.addWidget(row)

    def refresh_headline(self) -> None:
        states = [r.state for r in self.rows]
        if any(s in ("pending", "busy") for s in states[:-1]):
            self.headline.setText(tr("Wird eingerichtet …"))
        elif "error" in states:
            self.headline.setText(tr("Fertig, aber etwas braucht deine Aufmerksamkeit"))
        elif "warn" in states:
            self.headline.setText(tr("Bereit – mit Hinweisen"))
        else:
            self.headline.setText(tr("Alles bereit"))


class ClosingDialog(QDialog):
    """Zeigt beim Schliessen, was gerade passiert, statt einfach „Keine Rückmeldung“."""

    def __init__(self, steps: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Wird beendet …"))
        self.setModal(True)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(8)
        head = QLabel(tr("Alles wird sauber zurückgegeben …"))
        head.setObjectName("CardHeading")
        lay.addWidget(head)
        lay.addSpacing(6)
        self.bar = StepBar(len(steps))
        lay.addWidget(self.bar)
        lay.addSpacing(6)
        self.rows = [StepRow(text, i, self.bar) for i, text in enumerate(steps)]
        for row in self.rows:
            row.set("pending", "")
            lay.addWidget(row)

    def set_step(self, index: int) -> None:
        for i, row in enumerate(self.rows):
            if i < index:
                row.set("ok", tr("Erledigt"))
            elif i == index:
                row.set("busy", tr("Läuft …"))
