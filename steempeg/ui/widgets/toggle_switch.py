"""A sliding on/off toggle switch.

Subclasses QCheckBox so the rest of the app keeps using isChecked(), setChecked()
and the toggled signal unchanged - only the look is custom (an animated pill +
thumb, matching the settings-panel mockup). The descriptive text lives in a
separate QLabel next to it, so this widget is just the switch.
"""
from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QCheckBox


class ToggleSwitch(QCheckBox):
    def __init__(self, parent=None, track_on="#b29ae7", track_off="#444444", thumb="#ffffff"):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self._w, self._h, self._margin = 40, 22, 3
        self._track_on = QColor(track_on)
        self._track_off = QColor(track_off)
        self._thumb = QColor(thumb)
        self._offset = float(self._margin)
        self.setFixedSize(self._w, self._h)

        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self.toggled.connect(self._animate)

    def _on_pos(self):
        return float(self._w - self._h + self._margin)

    def _off_pos(self):
        return float(self._margin)

    def _animate(self, checked):
        self._anim.stop()
        end = self._on_pos() if checked else self._off_pos()
        if abs(self._offset - end) < 0.5:
            self._offset = end
            self.update()
            return
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(end)
        self._anim.start()

    def get_offset(self):
        return self._offset

    def set_offset(self, value):
        self._offset = value
        self.update()

    offset = Property(float, get_offset, set_offset)

    def hitButton(self, pos):
        # Make the whole widget clickable, not just the (hidden) checkbox box.
        return self.contentsRect().contains(pos)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)

        # Keep the thumb in sync even when state changes without the toggled signal
        # (e.g. setChecked under blockSignals), as long as no animation is running.
        if self._anim.state() != QPropertyAnimation.Running:
            self._offset = self._on_pos() if self.isChecked() else self._off_pos()

        radius = self._h / 2.0
        p.setBrush(self._track_on if self.isChecked() else self._track_off)
        p.drawRoundedRect(QRectF(0, 0, self._w, self._h), radius, radius)

        diameter = self._h - 2 * self._margin
        p.setBrush(self._thumb)
        p.drawEllipse(QRectF(self._offset, self._margin, diameter, diameter))
        p.end()
