"""Sprachauswahl beim ersten Start und das Einstellungsfenster (⚙)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout)

from .. import config, system
from ..i18n import LANGUAGES, tr
from .widgets import ToggleSwitch


class LanguageDialog(QDialog):
    """Erster Start: Sprache wählen. Bewusst in allen drei Sprachen beschriftet."""

    def __init__(self, current: str = "en", parent=None):
        super().__init__(parent)
        self.setWindowTitle(config.APP_NAME)
        self.setMinimumWidth(420)
        self.code = current
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(10)
        head = QLabel("🌐  Language · Sprache · Idioma")
        head.setObjectName("CardHeading")
        lay.addWidget(head)
        hint = QLabel("You can change this later in ⚙ Settings.")
        hint.setObjectName("Muted")
        lay.addWidget(hint)
        lay.addSpacing(6)
        self.group = QButtonGroup(self)
        for code, label in LANGUAGES.items():
            btn = QPushButton(label)
            btn.setObjectName("Segment")
            btn.setCheckable(True)
            btn.setMinimumHeight(40)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setChecked(code == current)
            btn.clicked.connect(lambda _=False, c=code: setattr(self, "code", c))
            btn.setProperty("code", code)
            self.group.addButton(btn)
            lay.addWidget(btn)
        lay.addSpacing(8)
        ok = QPushButton("✓  OK")
        ok.setObjectName("Primary")
        ok.setMinimumHeight(36)
        ok.clicked.connect(self.accept)
        lay.addWidget(ok)


def _row(icon: str, title: str, text: str, control) -> QFrame:
    row = QFrame()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 8, 0, 8)
    lay.setSpacing(14)
    ic = QLabel(icon)
    ic.setFixedWidth(26)
    ic.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
    ic.setStyleSheet("font-size: 14pt;")
    col = QVBoxLayout()
    col.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("StepTitle")
    d = QLabel(text)
    d.setObjectName("Muted")
    d.setWordWrap(True)
    col.addWidget(t)
    col.addWidget(d)
    lay.addWidget(ic)
    lay.addLayout(col, 1)
    lay.addWidget(control, 0, Qt.AlignVCenter)
    return row


class SettingsDialog(QDialog):
    """⚙ Einstellungen: Sprache und (freiwilliger) Windows-Autostart."""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("Einstellungen"))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(4)
        head = QLabel(tr("⚙  Einstellungen"))
        head.setObjectName("CardHeading")
        lay.addWidget(head)
        lay.addSpacing(8)

        self.lang = QComboBox()
        for code, label in LANGUAGES.items():
            self.lang.addItem(label, code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(settings.get("language", "en"))))
        lay.addWidget(_row("🌐", tr("Sprache"), tr("Wird nach einem Neustart des Tools aktiv."), self.lang))

        line = QFrame()
        line.setObjectName("Divider")
        line.setFixedHeight(1)
        lay.addWidget(line)

        self.autostart = ToggleSwitch(system.autostart_enabled())
        self.autostart.setEnabled(system.autostart_supported())
        text = tr("Startet das Tool bei der Windows-Anmeldung mit deinen letzten Einstellungen. "
                  "Standardmässig aus. Wenn du die EXE verschiebst, schalte es neu ein.")
        lay.addWidget(_row("⏻", tr("Mit Windows starten"), text, self.autostart))
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        self.status.hide()
        lay.addWidget(self.status)
        self.autostart.toggled.connect(self._autostart_toggled)

        line2 = QFrame()
        line2.setObjectName("Divider")
        line2.setFixedHeight(1)
        lay.addWidget(line2)
        self.restore_dl = ToggleSwitch(bool(settings.get("restore_dynamic_lighting", False)))
        self.restore_dl.toggled.connect(lambda on: settings.__setitem__("restore_dynamic_lighting", on))
        lay.addWidget(_row("◐", tr("Windows-Dynamische Beleuchtung beim Schliessen wieder einschalten"),
                           tr("Das Tool schaltet die Dynamische Beleuchtung von Windows beim Start aus, sonst reagieren "
                              "manche Geräte nicht (z. B. Gigabyte-Mainboards). Standardmässig bleibt sie danach aus."),
                           self.restore_dl))

        lay.addSpacing(12)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        done = QPushButton(tr("✓  Fertig"))
        done.setObjectName("Primary")
        done.clicked.connect(self.accept)
        buttons.addWidget(done)
        lay.addLayout(buttons)

    def language(self) -> str:
        return self.lang.currentData()

    def _autostart_toggled(self, on: bool) -> None:
        ok, err = system.set_autostart(on)
        if not ok:
            self.autostart.blockSignals(True)
            self.autostart.setChecked(not on)
            self.autostart.blockSignals(False)
            self.status.setText(tr("✕ Autostart konnte nicht geändert werden: {v0}", v0=err))
        else:
            self.status.setText(tr("✓ Autostart ist an.") if on else tr("✓ Autostart ist aus."))
        self.status.show()
