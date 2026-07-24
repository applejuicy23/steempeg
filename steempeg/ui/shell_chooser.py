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
from steempeg.ui.widgets.steempeg_check import SteempegCheckBox

UI_SHELL_KEY = "ui_shell"
UI_SHELL_ASK_KEY = "ui_shell_ask_on_startup"
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


def load_ask_ui_shell() -> bool:
    """True = show the chooser on launch (default)."""
    data = cache.read_json(_settings_path())
    if UI_SHELL_ASK_KEY not in data:
        return True
    return bool(data.get(UI_SHELL_ASK_KEY))


def save_ask_ui_shell(ask: bool) -> None:
    path = _settings_path()
    data = cache.read_json(path)
    data[UI_SHELL_ASK_KEY] = bool(ask)
    cache.write_json(path, data)


def is_steamdeck_build() -> bool:
    """True for steamdeck update-channel builds (Deck zip / baked channel)."""
    try:
        from steempeg.services.release_catalog import update_channel

        return update_channel() == "steamdeck"
    except Exception:
        return False


def resolve_startup_ui_shell() -> str | None:
    """Shell to use without showing the chooser, or None to ask.

    Steam Deck builds skip the chooser (Portable by default; Settings can still
    override). Other builds skip only when the user checked Don't ask again.
    """
    saved = load_ui_shell()
    if is_steamdeck_build():
        return saved or UI_SHELL_PORTABLE
    if not load_ask_ui_shell() and saved:
        return saved
    return None


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

        self._chk_remember = SteempegCheckBox("Don't ask again — remember this choice")
        self._chk_remember.setChecked(False)
        self.content_layout.addSpacing(10)
        self.content_layout.addWidget(self._chk_remember)

        foot = QLabel("You can switch Desktop ↔ Portable anytime in Settings.")
        foot.setWordWrap(True)
        foot.setStyleSheet(
            f"color: {tok.TEXT_MUTED}; font-size: 11px; background: transparent; "
            f"font-family: {tok.FONT_APP};"
        )
        self.content_layout.addSpacing(4)
        self.content_layout.addWidget(foot)

    def _pick(self, shell_id: str) -> None:
        self._chosen = shell_id
        save_ui_shell(shell_id)
        # Checked → skip chooser next launch; unchecked → keep asking.
        save_ask_ui_shell(not self._chk_remember.isChecked())
        self.accept()

    @property
    def chosen_shell(self) -> str | None:
        return self._chosen

    @property
    def remember_choice(self) -> bool:
        return bool(self._chk_remember.isChecked())
