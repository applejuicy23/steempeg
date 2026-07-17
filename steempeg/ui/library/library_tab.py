"""Chrome-style library panel tab with a hover-only close control."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from steempeg.ui.ui_density import COMFORT, UiDensity


def _tab_qss(font_px: int, radius: int, *, active: bool, hover: bool) -> str:
    if active:
        border, color = "#6b5a8e", "#ffffff"
    elif hover:
        border, color = "#555555", "#ffffff"
    else:
        border, color = "#353535", "#aaaaaa"
    return f"""
    QFrame#libraryTab {{
        background-color: #2d2d2d;
        border: 1px solid {border};
        border-radius: {radius}px;
    }}
    QLabel#libraryTabText {{
        color: {color};
        background: transparent;
        border: none;
        font-weight: bold;
        font-size: {font_px}px;
        font-family: 'Segoe UI', Arial, sans-serif;
    }}
"""


_CLOSE_HIDDEN = """
    QPushButton {
        background: transparent;
        border: none;
        color: transparent;
        font-size: 15px;
        font-weight: bold;
        padding: 0;
        margin: 0;
    }
"""
_CLOSE_VISIBLE = """
    QPushButton {
        background: transparent;
        border: none;
        color: #888888;
        font-size: 15px;
        font-weight: bold;
        padding: 0;
        margin: 0;
    }
    QPushButton:hover { color: #ffffff; background: rgba(255, 255, 255, 20); border-radius: 8px; }
"""


class LibraryTabWidget(QFrame):
    """Single library panel tab; close button is invisible until the tab is hovered."""

    activated = Signal(str)
    close_requested = Signal(str)

    def __init__(self, label: str, mode: str, parent=None, *, closable: bool = True):
        super().__init__(parent)
        self.mode = mode
        self._closable = closable
        self._active = False
        self._hovered = False
        self._label = label
        self._density = COMFORT
        self.setObjectName("libraryTab")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._row = QHBoxLayout(self)
        self._row.setSpacing(2)

        self._text = QLabel(label)
        self._text.setObjectName("libraryTabText")
        self._text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._row.addWidget(self._text)

        self._close = QPushButton("×")
        self._close.setFixedSize(18, 18)
        self._close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close.setToolTip("Close panel")
        self._close.setStyleSheet(_CLOSE_HIDDEN)
        self._close.clicked.connect(self._emit_close)
        if not closable:
            self._close.hide()
            self._close.setEnabled(False)
        self._row.addWidget(self._close, 0, Qt.AlignmentFlag.AlignVCenter)

        self.apply_density(COMFORT)
        self.set_active(False)

    def set_label(self, label: str) -> None:
        self._label = label
        self._text.setText(label)
        self._recompute_min_width()

    def apply_density(self, dense: UiDensity) -> None:
        self._density = dense
        self.setFixedHeight(dense.tab_height)
        pad_r = dense.tab_pad_r if self._closable else dense.tab_pad_l
        self._row.setContentsMargins(dense.tab_pad_l, 0, pad_r, 0)
        close_sz = 16 if dense.compact else 18
        self._close.setFixedSize(close_sz, close_sz)
        self._apply_style()
        self._recompute_min_width()

    def _recompute_min_width(self) -> None:
        d = self._density
        text_w = self._text.fontMetrics().horizontalAdvance(self._label)
        close_w = self._close.width() if self._closable else 0
        pad_r = d.tab_pad_r if self._closable else d.tab_pad_l
        self.setMinimumWidth(text_w + close_w + d.tab_pad_l + pad_r + 6)

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._apply_style()

    def _emit_close(self) -> None:
        self.close_requested.emit(self.mode)

    def _apply_style(self) -> None:
        d = self._density
        self.setStyleSheet(
            _tab_qss(
                d.tab_font,
                d.tab_radius,
                active=self._active,
                hover=self._hovered and not self._active,
            )
        )

    def enterEvent(self, event):
        self._hovered = True
        if self._closable:
            self._close.setStyleSheet(_CLOSE_VISIBLE)
        self._apply_style()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        if self._closable:
            self._close.setStyleSheet(_CLOSE_HIDDEN)
        self._apply_style()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.mode)
            event.accept()
            return
        super().mousePressEvent(event)
