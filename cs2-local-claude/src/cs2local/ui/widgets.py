"""Eigene, gezeichnete Bausteine der Oberfläche: Schalter, Geräte-Symbole, animierte LED-Vorschau."""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from ..effects import render
from . import theme


# ------------------------------------------------------------------------------------------- Schalter
class ToggleSwitch(QAbstractButton):
    """Runder An/Aus-Schalter wie auf dem Handy."""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(44, 24)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(44, 24)

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        track = QColor(theme.ACCENT if on else theme.BORDER)
        if not self.isEnabled():
            track.setAlpha(90)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, 44, 24), 12, 12)
        p.setBrush(QColor("#111" if on else theme.TEXT))
        x = 23 if on else 3
        p.drawEllipse(QRectF(x, 3, 18, 18))


# ------------------------------------------------------------------------------------------- Farbfeld
class ColorSwatch(QAbstractButton):
    """Runder Farbknopf. Zeigt bei Teamfarbe ein geteiltes CT/T-Feld."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(34, 34)
        self._color = QColor(0, 0, 0)
        self._team = False

    def set_color(self, rgb, team: bool = False) -> None:
        self._color = QColor(*rgb)
        self._team = team
        self.setToolTip("Teamfarbe (CT/T)" if team else f"Farbe {self._color.name()} – klicken zum Ändern")
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(2, 2, 30, 30)
        if self._team:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 70, 255))
            p.drawPie(r, 45 * 16, 180 * 16)
            p.setBrush(QColor(0, 210, 60))
            p.drawPie(r, 225 * 16, 180 * 16)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(self._color)
            p.drawEllipse(r)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(theme.TEXT if self.underMouse() and self.isEnabled() else theme.BORDER), 2))
        p.drawEllipse(r)


# ------------------------------------------------------------------------------------------- LED-Vorschau
class LedPreview(QWidget):
    """Animierte Reihe von LEDs, berechnet mit denselben Effekten wie die echten Geräte."""

    def __init__(self, leds: int = 18, height: int = 34, parent=None):
        super().__init__(parent)
        self.leds = leds
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._source = None  # Funktion: (Sekunden seit Start, Anzahl LEDs) -> Farben
        self._start = time.monotonic()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)

    def set_source(self, source) -> None:
        self._source = source
        self.update()

    def restart(self) -> None:
        self._start = time.monotonic()

    def showEvent(self, event):  # noqa: N802
        self._timer.start(33)
        super().showEvent(event)

    def hideEvent(self, event):  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#0b0d11"))
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        colors = []
        if self._source:
            try:
                colors = self._source(time.monotonic() - self._start, self.leds)
            except Exception:  # noqa: BLE001
                colors = []
        n = self.leds
        pad = h * 0.5
        step = (w - 2 * pad) / max(1, n - 1)
        radius = min(h * 0.22, step * 0.38)
        for i in range(n):
            c = colors[i] if i < len(colors) else (0, 0, 0)
            cx, cy = pad + i * step, h / 2
            level = max(c) / 255 if c else 0
            if level > 0.02:  # weicher Schein
                glow = QRadialGradient(QPointF(cx, cy), radius * 3.2)
                col = QColor(*c)
                col.setAlpha(int(150 * level))
                glow.setColorAt(0, col)
                col.setAlpha(0)
                glow.setColorAt(1, col)
                p.setBrush(QBrush(glow))
                p.drawEllipse(QPointF(cx, cy), radius * 3.2, radius * 3.2)
            p.setBrush(QColor(*c) if level > 0.02 else QColor("#1d212a"))
            p.drawEllipse(QPointF(cx, cy), radius, radius)


def state_preview_source(cfg: dict, color_fn):
    """Vorschau-Animation für einen Zustand, so wie er im Spiel aussieht."""
    sid = cfg.get("_id")
    kind = cfg.get("kind")

    def source(elapsed: float, n: int):
        color = color_fn()
        effect, speed, duration = cfg["effect"], cfg.get("speed", 1.0), cfg.get("duration", 0) or 1.0
        if not cfg.get("enabled", True):
            return [(18, 18, 22)] * n
        if kind == "event":  # kurzes Ereignis: abspielen, Pause, wiederholen
            cycle = duration + 0.7
            t = elapsed % cycle
            if t > duration:  # kurze Pause, gedimmt
                return [tuple(int(v * 0.08) for v in color)] * n
            return render(effect, color, speed, t, n, duration)
        if sid == "bomb_planted":  # 40 Sekunden Countdown im Zeitraffer (10 s)
            age = (elapsed % 10.0) * 4.0
            t = age + 1.5 * age * age / 40.0
            return render(effect, color, speed, t, n, duration)
        if sid == "flashed":  # Blendung klingt ab
            level = max(0.0, 1.0 - (elapsed % 3.0) / 2.4)
            return [tuple(int(v * level) for v in c) for c in render(effect, color, speed, elapsed, n)]
        return render(effect, color, speed, elapsed, n, duration)

    return source


# ------------------------------------------------------------------------------------------- Geräte-Symbole
class DeviceIcon(QWidget):
    """Gezeichnetes Symbol je Gerätetyp. Leuchtet in Akzentfarbe, wenn das Gerät verwendet wird."""

    def __init__(self, type_id: int, parent=None):
        super().__init__(parent)
        self.type_id = type_id
        self.active = False
        self.setFixedSize(64, 64)

    def set_active(self, active: bool) -> None:
        self.active = active
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg = QLinearGradient(0, 0, 64, 64)
        bg.setColorAt(0, QColor("#232834"))
        bg.setColorAt(1, QColor("#181b22"))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(QRectF(0, 0, 64, 64), 16, 16)
        line = QColor(theme.ACCENT if self.active else theme.MUTED)
        p.setPen(QPen(line, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        drawer = {0: self._board, 1: self._ram, 2: self._gpu, 3: self._fan, 4: self._strip, 5: self._keyboard,
                  6: self._mouse, 7: self._mat, 8: self._headset, 20: self._monitor, 15: self._case}
        drawer.get(self.type_id, self._generic)(p, line)

    @staticmethod
    def _dots(p, line, points):
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(line)
        for x, y in points:
            p.drawEllipse(QPointF(x, y), 2.2, 2.2)
        p.restore()

    def _keyboard(self, p, line):
        p.drawRoundedRect(QRectF(10, 22, 44, 22), 4, 4)
        self._dots(p, line, [(16 + i * 6.4, 29) for i in range(6)] + [(16 + i * 6.4, 35) for i in range(6)])
        p.drawLine(QPointF(22, 40), QPointF(42, 40))

    def _board(self, p, line):
        p.drawRoundedRect(QRectF(12, 12, 40, 40), 4, 4)
        p.drawRect(QRectF(22, 20, 14, 14))
        p.drawLine(QPointF(16, 42), QPointF(48, 42))
        p.drawLine(QPointF(16, 47), QPointF(40, 47))
        self._dots(p, line, [(44, 20), (44, 27), (44, 34)])

    def _ram(self, p, line):
        p.drawRoundedRect(QRectF(10, 20, 44, 20), 3, 3)
        for i in range(5):
            p.drawRect(QRectF(14 + i * 8, 24, 5, 8))
        for i in range(8):
            p.drawLine(QPointF(13 + i * 5.3, 40), QPointF(13 + i * 5.3, 44))

    def _gpu(self, p, line):
        p.drawRoundedRect(QRectF(8, 18, 48, 26), 4, 4)
        p.drawEllipse(QPointF(22, 31), 8, 8)
        p.drawEllipse(QPointF(42, 31), 8, 8)
        p.drawLine(QPointF(14, 44), QPointF(14, 49))

    def _fan(self, p, line):
        p.drawEllipse(QPointF(32, 32), 20, 20)
        p.drawEllipse(QPointF(32, 32), 4, 4)
        for a in range(0, 360, 90):
            path = QPainterPath()
            path.moveTo(32, 32)
            p.save()
            p.translate(32, 32)
            p.rotate(a)
            p.drawArc(QRectF(-2, -16, 14, 14), 90 * 16, 160 * 16)
            p.restore()

    def _strip(self, p, line):
        path = QPainterPath()
        path.moveTo(10, 40)
        path.cubicTo(22, 16, 42, 48, 54, 24)
        p.drawPath(path)
        self._dots(p, line, [(14, 33), (22, 27), (30, 31), (38, 36), (46, 34), (52, 27)])

    def _mouse(self, p, line):
        p.drawRoundedRect(QRectF(21, 12, 22, 38), 11, 11)
        p.drawLine(QPointF(32, 14), QPointF(32, 24))

    def _mat(self, p, line):
        p.drawRoundedRect(QRectF(10, 18, 44, 28), 5, 5)
        p.drawLine(QPointF(14, 42), QPointF(50, 42))

    def _headset(self, p, line):
        p.drawArc(QRectF(14, 12, 36, 36), 0, 180 * 16)
        p.drawRoundedRect(QRectF(11, 30, 9, 16), 4, 4)
        p.drawRoundedRect(QRectF(44, 30, 9, 16), 4, 4)

    def _monitor(self, p, line):
        p.drawRoundedRect(QRectF(10, 14, 44, 28), 3, 3)
        p.drawLine(QPointF(32, 42), QPointF(32, 49))
        p.drawLine(QPointF(24, 50), QPointF(40, 50))

    def _case(self, p, line):
        p.drawRoundedRect(QRectF(20, 10, 24, 44), 3, 3)
        p.drawEllipse(QPointF(32, 24), 6, 6)
        p.drawEllipse(QPointF(32, 40), 6, 6)

    def _generic(self, p, line):
        p.drawEllipse(QPointF(32, 32), 14, 14)
        self._dots(p, line, [(32, 32)])


# ------------------------------------------------------------------------------------------- Zonen-Chip
class ZoneChip(QAbstractButton):
    """Anklickbare Pille für eine Zone: Name und Anzahl LEDs."""

    toggled_key = Signal(str, bool)

    def __init__(self, key: str, name: str, leds: int, parent=None):
        super().__init__(parent)
        self.key, self.name, self.leds = key, name, leds
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.toggled.connect(lambda on: self.toggled_key.emit(self.key, on))
        self._update_size()

    def set_leds(self, leds: int) -> None:
        self.leds = leds
        self._update_size()
        self.update()

    def _label(self) -> str:
        return f"{self.name}  ·  {self.leds} LED{'s' if self.leds != 1 else ''}"

    def _update_size(self) -> None:
        width = self.fontMetrics().horizontalAdvance(self._label()) + 40
        self.setFixedSize(width, 30)

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        p.setPen(QPen(QColor(theme.ACCENT if on else theme.BORDER), 1.4))
        p.setBrush(QColor("#2a1d10" if on else theme.SURFACE_2))
        p.drawRoundedRect(rect, 15, 15)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.ACCENT if on else theme.MUTED))
        p.drawEllipse(QPointF(15, self.height() / 2), 4, 4)
        p.setPen(QColor(theme.TEXT if on else theme.MUTED))
        p.drawText(QRectF(26, 0, self.width() - 30, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self._label())
