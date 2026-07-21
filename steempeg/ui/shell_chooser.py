"""Startup shell chooser — Desktop vs Portable (Steam Deck theatre)."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QFont, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from steempeg.infra import cache
from steempeg.infra.paths import get_resource_path, get_save_directory
from steempeg.ui import design_tokens as tok
from steempeg.ui.message_dialog import dialog_theme
from steempeg.ui.widgets.dialog_chrome import SteempegDialog

UI_SHELL_KEY = "ui_shell"
UI_SHELL_DESKTOP = "desktop"
UI_SHELL_PORTABLE = "portable"

_CARD_W = 200
_CARD_H = 220
_ICON_PX = 96


def _settings_path() -> str:
    return os.path.join(get_save_directory(), "cache", "settings.json")


def load_ui_shell() -> str | None:
    """Return saved shell id, or None if the user has not chosen yet."""
    raw = cache.read_json(_settings_path()).get(UI_SHELL_KEY)
    if raw in (UI_SHELL_DESKTOP, UI_SHELL_PORTABLE):
        return str(raw)
    return None


def save_ui_shell(shell: str) -> None:
    if shell not in (UI_SHELL_DESKTOP, UI_SHELL_PORTABLE):
        return
    path = _settings_path()
    data = cache.read_json(path)
    data[UI_SHELL_KEY] = shell
    cache.write_json(path, data)


class _ShellCard(QPushButton):
    """Rounded square: icon + title + short subtitle."""

    chosen = Signal(str)

    def __init__(
        self,
        *,
        shell_id: str,
        title: str,
        subtitle: str,
        icon_file: str,
        parent=None,
    ):
        super().__init__(parent)
        self._shell_id = shell_id
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setCheckable(False)
        self.setFixedSize(_CARD_W, _CARD_H)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 18, 16, 16)
        lay.setSpacing(10)

        icon = QLabel()
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedHeight(_ICON_PX + 8)
        path = get_resource_path(icon_file)
        if os.path.isfile(path):
            pix = QPixmap(path).scaled(
                _ICON_PX,
                _ICON_PX,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            icon.setPixmap(pix)
        else:
            icon.setText("?")
            icon.setStyleSheet(f"color: {tok.TEXT_MUTED}; font-size: 28px;")
        lay.addWidget(icon)

        title_lbl = QLabel(title)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = QFont()
        title_font.setFamilies(["Segoe UI", "Noto Sans", "Arial"])
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        title_lbl.setStyleSheet(
            f"color: {tok.TEXT_PRIMARY}; background: transparent; border: none;"
        )
        lay.addWidget(title_lbl)

        sub = QLabel(subtitle)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet(
            f"color: {tok.TEXT_MUTED}; font-size: 11px; background: transparent; "
            f"border: none; font-family: {tok.FONT_APP};"
        )
        lay.addWidget(sub)
        lay.addStretch(1)

        self._apply_style(hover=False)
        self.clicked.connect(lambda: self.chosen.emit(self._shell_id))

    def enterEvent(self, event):
        self._apply_style(hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply_style(hover=False)
        super().leaveEvent(event)

    def _apply_style(self, *, hover: bool) -> None:
        border = "#b29ae7" if hover else "#4a4a4a"
        bg = "#2e2a38" if hover else "#2a2a2a"
        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {bg};
                border: 2px solid {border};
                border-radius: 14px;
                text-align: center;
            }}
            QPushButton:focus {{
                border: 2px solid #b29ae7;
            }}
            """
        )


class ShellChooserDialog(SteempegDialog):
    """Pick Desktop (full UI) or Portable (theatre-only Steam Deck shell)."""

    def __init__(self, parent=None, **theme_kwargs):
        if not theme_kwargs.get("bar_color"):
            theme_kwargs = {**dialog_theme(parent), **theme_kwargs}
        super().__init__("Choose your Steempeg", parent, **theme_kwargs)
        self.setMinimumWidth(520)
        self._chosen: str | None = None

        hint = QLabel("How do you want to use Steempeg?")
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {tok.TEXT_PRIMARY}; font-size: 13px; background: transparent; "
            f"font-family: {tok.FONT_APP};"
        )
        self.content_layout.addWidget(hint)

        sub = QLabel(
            "Desktop keeps the full layout. Portable is theatre-only — "
            "built for Steam Deck and small screens."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(
            f"color: {tok.TEXT_MUTED}; font-size: 12px; background: transparent; "
            f"font-family: {tok.FONT_APP};"
        )
        self.content_layout.addWidget(sub)
        self.content_layout.addSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(16)
        row.addStretch(1)

        desktop = _ShellCard(
            shell_id=UI_SHELL_DESKTOP,
            title="Desktop",
            subtitle="Windows & Linux\nClips · Player · Queue",
            icon_file="desktop.png",
        )
        portable = _ShellCard(
            shell_id=UI_SHELL_PORTABLE,
            title="Portable",
            subtitle="Steam Deck\nTheatre mode only",
            icon_file="portable.png",
        )
        desktop.chosen.connect(self._pick)
        portable.chosen.connect(self._pick)
        row.addWidget(desktop)
        row.addWidget(portable)
        row.addStretch(1)
        self.content_layout.addLayout(row)

        foot = QLabel("Pick each time you launch — useful while we tune both shells.")
        foot.setWordWrap(True)
        foot.setStyleSheet(
            f"color: {tok.TEXT_MUTED}; font-size: 11px; background: transparent; "
            f"font-family: {tok.FONT_APP};"
        )
        self.content_layout.addSpacing(6)
        self.content_layout.addWidget(foot)

    def _pick(self, shell_id: str) -> None:
        self._chosen = shell_id
        self.accept()

    @property
    def chosen_shell(self) -> str | None:
        return self._chosen
