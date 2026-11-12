"""About/Settings-style Play video button with a separate arrow menu."""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from steempeg.ui import design_tokens as tok
from steempeg.ui.icon_assets import arrow_icon, load_icon


def _play_label_font() -> QFont:
    return tok.ui_qfont(pixel_size=12, weight=QFont.Weight.Bold)


def _play_split_style() -> str:
    """Share About/Settings footer chrome, with joined split segments."""
    from steempeg.ui import ui_theme as ut

    base = ut.about_secondary_button_stylesheet()
    main = base.replace("QPushButton", "QPushButton#PlayMain")
    menu = base.replace("QPushButton", "QPushButton#PlayMenu")
    return main + menu + f"""
    QPushButton#PlayMain {{
        border-right: none;
        border-top-right-radius: 0px;
        border-bottom-right-radius: 0px;
        padding: 0;
        min-height: 0px;
    }}
    QPushButton#PlayMain:hover {{ border-right: none; }}
    QPushButton#PlayMenu {{
        border-top-left-radius: 0px;
        border-bottom-left-radius: 0px;
        padding: 0;
        min-width: 32px;
        max-width: 32px;
        min-height: 0px;
    }}
    QLabel#PlayText {{
        background: transparent; border: none; color: white;
        font-family: {tok.FONT_APP}; font-size: 12px; font-weight: bold;
    }}
    QLabel#PlayIcon {{ background: transparent; border: none; }}
    """


class _PlayMainButton(QPushButton):
    """Left split segment — icon + label with explicit gap; honest sizeHint for layouts."""

    _BORDER = 2  # 1px border on each side
    _MIN_BODY_H = 24

    def sizeHint(self) -> QSize:  # noqa: D102 — Qt override
        lay = self.layout()
        if lay is not None:
            inner = lay.sizeHint()
            # Layout sizeHint already includes its content margins.
            body_h = max(inner.height(), self._MIN_BODY_H)
            return QSize(
                inner.width() + self._BORDER,
                body_h + self._BORDER,
            )
        return super().sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: D102 — Qt override
        return self.sizeHint()


class PlayVideoSplitButton(QWidget):
    """About/Settings footer button with separate play and menu actions."""

    play_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setStyleSheet(_play_split_style())

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.main_btn = _PlayMainButton()
        self.main_btn.setObjectName("PlayMain")
        self.main_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.main_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.main_btn.clicked.connect(self.play_clicked.emit)

        # Match the shared footer padding around the icon and label.
        main_inner = QHBoxLayout(self.main_btn)
        main_inner.setContentsMargins(24, 6, 24, 6)
        main_inner.setSpacing(8)
        main_inner.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        play_icon = QLabel()
        play_icon.setObjectName("PlayIcon")
        play_icon.setPixmap(load_icon("playmini.png", 10).pixmap(QSize(10, 10)))
        play_icon.setFixedSize(10, 10)
        play_icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        play_label = QLabel("Play video")
        play_label.setObjectName("PlayText")
        play_label.setFont(_play_label_font())
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

        split_h = 46  # Shared footer: 32px body + 12px padding + 2px border.
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
