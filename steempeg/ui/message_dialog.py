"""Steempeg-styled alert and confirm dialogs — drop-in replacements for QMessageBox."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from steempeg.ui import design_tokens as tok
from steempeg.ui.widgets.dialog_chrome import SteempegDialog

ButtonRole = Literal["primary", "secondary", "danger"]

_BTN_PRIMARY = """
    QPushButton {
        background-color: #4a3d66; color: #f0ecff; border: 2px solid #6b5a8e;
        border-radius: 8px; padding: 8px 16px; font-size: 12px; font-weight: bold;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
    }
    QPushButton:hover { background-color: #5a4d76; border-color: #b29ae7; }
    QPushButton:pressed { background-color: #3a324a; }
"""

_BTN_SECONDARY = """
    QPushButton {
        background-color: #383838; color: #e0e0e0; border: 2px solid #4a4a4a;
        border-radius: 8px; padding: 8px 16px; font-size: 12px; font-weight: bold;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
    }
    QPushButton:hover { background-color: #404040; color: #ffffff; border: 2px solid #6b5a8e; }
    QPushButton:pressed { background-color: #3a324a; border: 2px solid #b29ae7; }
"""

_BTN_DANGER = """
    QPushButton {
        background-color: #3a2222; color: #ff8a8a; border: 2px solid #8b3a3a;
        border-radius: 8px; padding: 8px 16px; font-size: 12px; font-weight: bold;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
    }
    QPushButton:hover { background-color: #522828; color: #ffb3b3; border-color: #c44; }
    QPushButton:pressed { background-color: #2a1818; }
"""

_ROLE_STYLES = {
    "primary": _BTN_PRIMARY,
    "secondary": _BTN_SECONDARY,
    "danger": _BTN_DANGER,
}


@dataclass(frozen=True)
class DialogButton:
    label: str
    role: ButtonRole = "secondary"
    accept: bool = False


def dialog_theme(parent) -> dict[str, str]:
    """Resolve title-bar / background colors from the nearest ancestor with a chrome theme."""
    node = parent
    while node is not None:
        theme_key = getattr(node, "_chrome_theme", None)
        if theme_key is not None:
            colors = tok.chrome_theme_colors(theme_key)
            return {"bar_color": colors["title_bar"], "bg_color": colors["app_bg"]}
        try:
            node = node.parent()
        except RuntimeError:
            break
    colors = tok.chrome_theme_colors(tok.DEFAULT_CHROME_THEME)
    return {"bar_color": colors["title_bar"], "bg_color": colors["app_bg"]}


class SteempegMessageDialog(SteempegDialog):
    """Flexible message box with Steempeg chrome and pill buttons."""

    def __init__(
        self,
        title: str,
        message: str,
        parent=None,
        *,
        detail: str | None = None,
        buttons: tuple[DialogButton, ...] = (DialogButton("OK", "primary", accept=True),),
        rich_text: bool = False,
        min_width: int = 380,
        **theme_kwargs,
    ):
        if not theme_kwargs.get("bar_color"):
            theme_kwargs = {**dialog_theme(parent), **theme_kwargs}
        super().__init__(title, parent, **theme_kwargs)
        from steempeg.ui.ui_density import scaled_dialog_size

        scaled_w, _ = scaled_dialog_size(min_width, 200, parent=parent)
        self.setMinimumWidth(scaled_w)
        self._clicked_index = -1

        body = QLabel(message)
        body.setWordWrap(True)
        if rich_text:
            body.setTextFormat(Qt.TextFormat.RichText)
        body.setStyleSheet(
            f"color: {tok.TEXT_PRIMARY}; font-size: 13px; background: transparent; "
            f"font-family: {tok.FONT_APP};"
        )
        self.content_layout.addWidget(body)

        if detail:
            detail_lbl = QLabel(detail)
            detail_lbl.setWordWrap(True)
            detail_lbl.setStyleSheet(
                f"color: {tok.TEXT_MUTED}; font-size: 12px; background: transparent; "
                f"font-family: {tok.FONT_APP};"
            )
            self.content_layout.addWidget(detail_lbl)

        self.content_layout.addStretch(1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)

        for index, spec in enumerate(buttons):
            btn = QPushButton(spec.label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(_ROLE_STYLES.get(spec.role, _BTN_SECONDARY))
            btn.clicked.connect(lambda _checked=False, i=index, acc=spec.accept: self._on_button(i, acc))
            actions.addWidget(btn)

        self.content_layout.addLayout(actions)

    def _on_button(self, index: int, accept: bool) -> None:
        self._clicked_index = index
        if accept:
            self.accept()
        else:
            self.reject()

    @property
    def clicked_index(self) -> int:
        return self._clicked_index


def _show(
    parent,
    title: str,
    message: str,
    *,
    detail: str | None = None,
    buttons: tuple[DialogButton, ...],
    rich_text: bool = False,
    min_width: int = 380,
) -> int:
    dlg = SteempegMessageDialog(
        title,
        message,
        parent,
        detail=detail,
        buttons=buttons,
        rich_text=rich_text,
        min_width=min_width,
    )
    dlg.exec()
    return dlg.clicked_index


def steempeg_information(parent, title: str, message: str, *, detail: str | None = None) -> None:
    _show(
        parent,
        title,
        message,
        detail=detail,
        buttons=(DialogButton("OK", "primary", accept=True),),
    )


def steempeg_information_dont_ask(
    parent,
    title: str,
    message: str,
    *,
    detail: str | None = None,
    checkbox_label: str = "Don't ask again",
) -> bool:
    """Info dialog with a dismiss checkbox. Returns True if the checkbox was checked on OK."""
    theme = dialog_theme(parent)
    dlg = SteempegMessageDialog(
        title,
        message,
        parent,
        detail=detail,
        buttons=(DialogButton("OK", "primary", accept=True),),
        **theme,
    )
    from steempeg.ui.widgets.steempeg_check import SteempegCheckBox

    chk = SteempegCheckBox(checkbox_label)
    # Insert above the action row (last layout item).
    dlg.content_layout.insertWidget(dlg.content_layout.count() - 1, chk)
    dlg.exec()
    return bool(chk.isChecked())


def steempeg_warning(parent, title: str, message: str, *, detail: str | None = None) -> None:
    _show(
        parent,
        title,
        message,
        detail=detail,
        buttons=(DialogButton("OK", "primary", accept=True),),
    )


def steempeg_critical(parent, title: str, message: str, *, detail: str | None = None) -> None:
    _show(
        parent,
        title,
        message,
        detail=detail,
        buttons=(DialogButton("OK", "danger", accept=True),),
    )


def steempeg_question(parent, title: str, message: str, *, detail: str | None = None) -> bool:
    return _show(
        parent,
        title,
        message,
        detail=detail,
        buttons=(
            DialogButton("No", "secondary"),
            DialogButton("Yes", "primary", accept=True),
        ),
    ) == 1


def steempeg_confirm_delete(
    parent,
    title: str,
    message: str,
    *,
    detail: str | None = None,
    delete_label: str = "🗑️ Delete",
) -> bool:
    return _show(
        parent,
        title,
        message,
        detail=detail,
        buttons=(
            DialogButton("Cancel", "secondary"),
            DialogButton(delete_label, "danger", accept=True),
        ),
    ) == 1


def steempeg_alert_actions(
    parent,
    title: str,
    message: str,
    buttons: tuple[DialogButton, ...],
    *,
    rich_text: bool = False,
    min_width: int = 420,
) -> int:
    """Multi-action alert; returns index of the clicked button (-1 if dismissed via close)."""
    return _show(
        parent,
        title,
        message,
        buttons=buttons,
        rich_text=rich_text,
        min_width=min_width,
    )
