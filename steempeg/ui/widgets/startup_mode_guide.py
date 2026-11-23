"""Library startup choices with a relative speed gauge and contextual help."""
from __future__ import annotations

import math
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QStyle, QStyledItemDelegate,
                              QStyleOptionViewItem, QVBoxLayout, QWidget)
from steempeg.ui.pro_appearance import accent_qcolor

from steempeg.ui import design_tokens as tok
from steempeg.ui.widgets.clip_card_style_guide import ClipCardStyleCombo, _ClipCardStylePopupGuide

STARTUP_HELP = (
    "Choose how Steempeg checks and prepares your library when it starts. "
    "The speed gauge is an estimate; actual time depends on your library, disk and cache."
)
MODES = {
    "progressive": ("Progressive", 4,
        "Recommended for everyday use. The first screen loads first, and cards along "
        "the path you scroll finish in the background."),
    "quick": ("Quick", 3,
        "Scans folders and uses cached health or lightweight checks, without ffprobe. "
        "Every card is ready before you start browsing."),
    "full": ("Full", 2,
        "Rechecks every clip, including ffprobe health checks, and prepares all ClipCards. "
        "Steam names and icons refresh in the background. The most thorough scan; "
        "also used for the first folder discovery and manual Refresh."),
    "cache": ("Skip", 2,
        "Use when your library is mostly unchanged. Restores the saved list first, "
        "then recovers missing previews and checks for new clips in the background."),
}

MODE_SUMMARIES = {
    "progressive": "Recommended · Start browsing while cards load.",
    "quick": "Light checks · All cards are ready before browsing.",
    "full": "Deep health check · Use when clips need rechecking.",
    "cache": "Restore the saved list · Previews and new clips follow.",
}


def startup_copy(mode: str) -> tuple[str, str, str]:
    name, _speed, description = MODES.get(mode, MODES["progressive"])
    return name, description, STARTUP_HELP


def paint_speed_gauge(painter: QPainter, rect: QRectF, level: int) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    radius = min(rect.width() / 2 - 2, rect.height() - 5)
    center = rect.center()
    center.setY(rect.bottom() - 3)
    arc = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
    for segment in range(4):
        pen = QPen(accent_qcolor(QColor("#b29ae7" if segment < level else "#55515d")), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(arc, int((177 - segment * 45) * 16), -37 * 16)
    angle = math.pi * (1 - (level - .5) / 4)
    end = center + type(center)(math.cos(angle) * radius * .72, -math.sin(angle) * radius * .72)
    painter.setPen(QPen(QColor("#eeeeee"), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(center, end)
    painter.setBrush(QColor("#eeeeee"))
    painter.drawEllipse(center, 1.5, 1.5)
    painter.restore()


class StartupSpeedGauge(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(30, 22)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._mode = "progressive"

    def set_style(self, mode):
        self._mode = mode
        self.setAccessibleName(f"Estimated startup speed {MODES.get(mode, MODES['progressive'])[1]} of 4")
        self.update()

    def paintEvent(self, event):  # noqa: N802
        paint_speed_gauge(QPainter(self), QRectF(self.rect()), MODES.get(self._mode, MODES["progressive"])[1])


class StartupModeDetails(QWidget):
    """Selected mode row followed by its explanation inside the ? splash."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(6)
        from steempeg.ui.icon_assets import tinted_pixmap
        mark = QLabel()
        mark.setFixedSize(16, 16)
        mark.setPixmap(tinted_pixmap("success.png", "#ffffff", 16))
        self.title = QLabel()
        font = QFont(tok.FONT_FAMILIES[0]); font.setPixelSize(12); font.setBold(True)
        self.title.setFont(font)
        self.title.setStyleSheet("color: #eeeeee;")
        self.gauge = StartupSpeedGauge()
        row.addWidget(mark); row.addWidget(self.title); row.addWidget(self.gauge); row.addStretch(1)
        layout.addLayout(row)
        self.description = QLabel()
        self.description.setWordWrap(True)
        font = QFont(tok.FONT_FAMILIES[0]); font.setPixelSize(11)
        self.description.setFont(font)
        self.description.setStyleSheet("color: #a8a8a8;")
        layout.addWidget(self.description)

    def set_style(self, mode):
        name, description, _ = startup_copy(mode)
        self.title.setText(name); self.description.setText(description); self.gauge.set_style(mode)


class _StartupChoiceDelegate(QStyledItemDelegate):
    def __init__(self, combo):
        super().__init__(combo); self.combo = combo

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        name = opt.text
        opt.text = ""
        widget = option.widget or self.combo.view()
        widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        painter.save(); painter.setFont(opt.font); painter.setPen(QColor("#eeeeee"))
        rect = option.rect
        if index.row() == self.combo.currentIndex():
            from steempeg.ui.icon_assets import tinted_pixmap
            painter.drawPixmap(rect.left() + 10, rect.center().y() - 8,
                               tinted_pixmap("success.png", "#ffffff", 16))
        painter.drawText(rect.adjusted(34, 0, -44, 0), Qt.AlignmentFlag.AlignVCenter, name)
        mode = str(index.data(Qt.ItemDataRole.UserRole) or "")
        paint_speed_gauge(painter, QRectF(rect.right() - 36, rect.center().y() - 11, 30, 22),
                          MODES.get(mode, MODES["progressive"])[1])
        painter.restore()

    def sizeHint(self, option, index):  # noqa: N802
        size = super().sizeHint(option, index)
        return QSize(max(220, size.width() + 80), max(38, size.height()))


class _StartupPopupGuide(_ClipCardStylePopupGuide):
    def __init__(self, parent):
        empty = StartupSpeedGauge()
        empty.hide(); empty.setFixedSize(1, 0)
        super().__init__(parent, empty, startup_copy)
        self._gauge = StartupSpeedGauge(self)
        self.layout().itemAt(0).layout().addWidget(self._gauge)

    def show_style(self, style, combo):
        self._gauge.set_style(style)
        super().show_style(style, combo)

    def _fit(self, title, blurb):
        super()._fit(title, blurb)
        self._title.setFixedWidth(max(1, self._title.width() - self._gauge.width() - 6))


class StartupModeCombo(ClipCardStyleCombo):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(220)
        self.setItemDelegate(_StartupChoiceDelegate(self))
        from PySide6.QtWidgets import QApplication
        QApplication.instance().applicationStateChanged.connect(self._application_state_changed)

    def _application_state_changed(self, state):
        if state != Qt.ApplicationState.ApplicationActive:
            self.hidePopup()

    def showPopup(self):  # noqa: N802
        if self._popup_is_open():
            self.hidePopup()
            return
        super().showPopup()

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        mode = str(self.currentData() or "progressive")
        paint_speed_gauge(painter, QRectF(self.width() - 70, (self.height() - 22) / 2, 30, 22),
                          MODES.get(mode, MODES["progressive"])[1])

    def _ensure_guide(self):
        if self._guide is None:
            self._guide = _StartupPopupGuide(self.window())
        return self._guide

    def eventFilter(self, obj, event):  # noqa: N802
        from PySide6.QtCore import QEvent
        if event.type() in (QEvent.Type.Hide, QEvent.Type.Close) and obj in self._watched_popup:
            if self._guide is not None:
                self._guide.hide()
        return super().eventFilter(obj, event)
