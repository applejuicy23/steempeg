"""Split Play video button — same chrome as Refresh ▾, play action + arrow menu."""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from steempeg.ui.icon_assets import arrow_icon, load_icon

# Match RefreshButton (refresh_button.py): 13px bold, pill radius 14, #444 border.
_PLAY_LABEL_FONT = QFont("Segoe UI")
_PLAY_LABEL_FONT.setPixelSize(13)
_PLAY_LABEL_FONT.setBold(True)

_PLAY_SPLIT_STYLE = """
    QPushButton#PlayMain {
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
        font-size: 13px;
        font-weight: bold;
        background-color: #383838;
        color: #ffffff;
        border: 2px solid #444444;
        border-right: none;
        border-top-left-radius: 14px;
        border-bottom-left-radius: 14px;
        border-top-right-radius: 0px;
        border-bottom-right-radius: 0px;
        padding: 0;
        min-height: 24px;
    }
    QPushButton#PlayMain:hover {
        background-color: #404040;
        border: 2px solid #6b5a8e;
        border-right: none;
    }
    QPushButton#PlayMain:pressed {
        background-color: #3a324a;
        border: 2px solid #b29ae7;
        border-right: none;
    }
    QPushButton#PlayMenu {
        background-color: #383838;
        color: #ffffff;
        border: 2px solid #444444;
        border-left: 1px solid #555555;
        border-top-left-radius: 0px;
        border-bottom-left-radius: 0px;
        border-top-right-radius: 14px;
        border-bottom-right-radius: 14px;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
        font-size: 12px;
        font-weight: bold;
        min-width: 28px;
        max-width: 32px;
        padding: 4px 0;
        min-height: 24px;
    }
    QPushButton#PlayMenu:hover {
        background-color: #404040;
        color: #d4c4ff;
        border: 2px solid #6b5a8e;
        border-left: 1px solid #6b5a8e;
    }
    QPushButton#PlayMenu:pressed {
        background-color: #3a324a;
        border: 2px solid #b29ae7;
        border-left: 1px solid #b29ae7;
    }
    QPushButton#PlayMenu:disabled {
        background-color: #333333;
        color: #666666;
        border: 2px solid #444444;
        border-left: 1px solid #555555;
    }
    QLabel#PlayText {
        background: transparent;
        border: none;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
        font-size: 13px;
        font-weight: bold;
        color: #ffffff;
    }
    QLabel#PlayIcon {
        background: transparent;
        border: none;
    }
"""


class _PlayMainButton(QPushButton):
    """Left split segment — icon + label with explicit gap; honest sizeHint for layouts."""

    _BORDER = 4  # 2px border × 2 sides
    _MIN_BODY_H = 24  # RefreshMain min-height

    def sizeHint(self) -> QSize:  # noqa: D102 — Qt override
        lay = self.layout()
        if lay is not None:
            m = lay.contentsMargins()
            inner = lay.sizeHint()
            body_h = max(inner.height() + m.top() + m.bottom(), self._MIN_BODY_H)
            return QSize(
                inner.width() + m.left() + m.right() + self._BORDER,
                body_h + self._BORDER,
            )
        return super().sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: D102 — Qt override
        return self.sizeHint()


class PlayVideoSplitButton(QWidget):
    """Play video (left) with a ▾ menu trigger (right) — Refresh-style split."""

    play_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setStyleSheet(_PLAY_SPLIT_STYLE)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.main_btn = _PlayMainButton()
        self.main_btn.setObjectName("PlayMain")
        self.main_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.main_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.main_btn.clicked.connect(self.play_clicked.emit)

        # RefreshMain uses padding: 4px 12px — mirror via inner margins.
        main_inner = QHBoxLayout(self.main_btn)
        main_inner.setContentsMargins(12, 4, 12, 4)
        main_inner.setSpacing(8)
        main_inner.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        play_icon = QLabel()
        play_icon.setObjectName("PlayIcon")
        play_icon.setPixmap(load_icon("playmini.png", 10).pixmap(QSize(10, 10)))
        play_icon.setFixedSize(10, 10)
        play_icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        play_label = QLabel("Play video")
        play_label.setObjectName("PlayText")
        play_label.setFont(_PLAY_LABEL_FONT)
        play_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        main_inner.addWidget(play_icon)
        main_inner.addWidget(play_label)

        self.menu_btn = QPushButton()
        self.menu_btn.setObjectName("PlayMenu")
        self.menu_btn.setIcon(arrow_icon(10, direction="down"))
        self.menu_btn.setIconSize(QSize(10, 10))
        self.menu_btn.setToolTip("More play options")
        self.menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        layout.addWidget(self.main_btn)
        layout.addWidget(self.menu_btn)

        split_h = max(self.main_btn.sizeHint().height(), self.menu_btn.sizeHint().height())
        self.main_btn.setFixedHeight(split_h)
        self.menu_btn.setFixedHeight(split_h)
        self.setFixedHeight(split_h)

    def sizeHint(self) -> QSize:
        return QSize(
            self.main_btn.sizeHint().width() + self.menu_btn.sizeHint().width(),
            self.height(),
        )

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def set_menu_enabled(self, enabled: bool) -> None:
        self.menu_btn.setEnabled(enabled)
