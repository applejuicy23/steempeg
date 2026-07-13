"""Chrome-style library panel tab with a hover-only close control."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

_TAB_INACTIVE = """
    QFrame#libraryTab {
        background-color: #2d2d2d;
        border: 1px solid #353535;
        border-radius: 16px;
    }
    QLabel#libraryTabText {
        color: #aaaaaa;
        background: transparent;
        border: none;
        font-weight: bold;
        font-size: 14px;
        font-family: 'Segoe UI', Arial, sans-serif;
    }
"""
_TAB_ACTIVE = """
    QFrame#libraryTab {
        background-color: #2d2d2d;
        border: 1px solid #6b5a8e;
        border-radius: 16px;
    }
    QLabel#libraryTabText {
        color: #ffffff;
        background: transparent;
        border: none;
        font-weight: bold;
        font-size: 14px;
        font-family: 'Segoe UI', Arial, sans-serif;
    }
"""
_TAB_HOVER_INACTIVE = """
    QFrame#libraryTab {
        background-color: #2d2d2d;
        border: 1px solid #555555;
        border-radius: 16px;
    }
    QLabel#libraryTabText {
        color: #ffffff;
        background: transparent;
        border: none;
        font-weight: bold;
        font-size: 14px;
        font-family: 'Segoe UI', Arial, sans-serif;
    }
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
        self.setObjectName("libraryTab")
        self.setFixedHeight(40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 0, 6 if closable else 14, 0)
        row.setSpacing(2)

        self._text = QLabel(label)
        self._text.setObjectName("libraryTabText")
        self._text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(self._text)

        self._close = QPushButton("×")
        self._close.setFixedSize(18, 18)
        self._close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close.setToolTip("Close panel")
        self._close.setStyleSheet(_CLOSE_HIDDEN)
        self._close.clicked.connect(self._emit_close)
        if not closable:
            self._close.hide()
            self._close.setEnabled(False)
        row.addWidget(self._close, 0, Qt.AlignmentFlag.AlignVCenter)

        text_w = self._text.fontMetrics().horizontalAdvance(label)
        close_w = 18 if closable else 0
        side_pad = 14 + (6 if closable else 14)
        self.setMinimumWidth(text_w + close_w + side_pad + 8)

        self.set_active(False)

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._apply_style()

    def _emit_close(self) -> None:
        self.close_requested.emit(self.mode)

    def _apply_style(self) -> None:
        if self._active:
            self.setStyleSheet(_TAB_ACTIVE)
        elif self._hovered:
            self.setStyleSheet(_TAB_HOVER_INACTIVE)
        else:
            self.setStyleSheet(_TAB_INACTIVE)

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
