"""Steempeg-styled dialogs for dead-clip salvage flows (Chupi mascots)."""
from __future__ import annotations

from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from steempeg.ui.widgets.steempeg_check import SteempegCheckBox

from steempeg.infra.paths import get_resource_path
from steempeg.ui import design_tokens as tok
from steempeg.ui.widgets.dialog_chrome import SteempegDialog

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

_MASCOT_H = 96


class _YesNoChoice(Enum):
    NO = "no"
    YES = "yes"


def _mascot_label(asset_name: str, height: int = _MASCOT_H) -> QLabel:
    lbl = QLabel()
    lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
    lbl.setStyleSheet("background: transparent; border: none;")
    pix = QPixmap(get_resource_path(asset_name))
    if not pix.isNull():
        lbl.setPixmap(
            pix.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
        )
        lbl.setFixedWidth(lbl.pixmap().width())
    else:
        lbl.setFixedSize(height, height)
    return lbl


class _MascotConfirmDialog(SteempegDialog):
    def __init__(
        self,
        window_title: str,
        mascot_asset: str,
        heading: str,
        body: str,
        *,
        primary_label: str,
        secondary_label: str,
        parent=None,
        bar_color: str | None = None,
        bg_color: str | None = None,
        min_width: int = 500,
        height: int = 300,
    ):
        super().__init__(window_title, parent, bar_color=bar_color, bg_color=bg_color)
        self.setMinimumWidth(min_width)
        self.resize(min_width + 40, height)
        self._choice = _YesNoChoice.NO

        content_row = QHBoxLayout()
        content_row.setSpacing(16)
        content_row.addWidget(_mascot_label(mascot_asset), 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(8)
        title = QLabel(heading)
        title.setWordWrap(True)
        title.setStyleSheet(
            f"color: {tok.TEXT_TITLE}; font-size: 15px; font-weight: 600; background: transparent;"
        )
        text_col.addWidget(title)

        message = QLabel(body)
        message.setWordWrap(True)
        message.setStyleSheet(
            f"color: {tok.TEXT_PRIMARY}; font-size: 12px; background: transparent;"
        )
        text_col.addWidget(message)
        text_col.addStretch(1)
        content_row.addLayout(text_col, 1)
        self.content_layout.addLayout(content_row)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)

        btn_secondary = QPushButton(secondary_label)
        btn_secondary.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_secondary.setStyleSheet(_BTN_SECONDARY)
        btn_secondary.clicked.connect(lambda: self._finish(_YesNoChoice.NO))
        actions.addWidget(btn_secondary)

        btn_primary = QPushButton(primary_label)
        btn_primary.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_primary.setStyleSheet(_BTN_PRIMARY)
        btn_primary.clicked.connect(lambda: self._finish(_YesNoChoice.YES))
        actions.addWidget(btn_primary)

        self.content_layout.addLayout(actions)

    def _finish(self, choice: _YesNoChoice) -> None:
        self._choice = choice
        if choice == _YesNoChoice.YES:
            self.accept()
        else:
            self.reject()

    @property
    def accepted_yes(self) -> bool:
        return self._choice == _YesNoChoice.YES


class DeadClipOfferDialog(_MascotConfirmDialog):
    """First time a dead clip is opened — offer salvage."""

    def __init__(self, issues: list[str], parent=None, **theme):
        issues_text = "\n".join(f"• {issue}" for issue in issues[:6])
        body = (
            f"{issues_text}\n\n"
            "Steempeg can try to salvage it from surviving chunks. "
            "If the decoder header is missing, you need one healthy donor clip "
            "of the same game in your library. No same-game donor = usually unrecoverable."
        )
        super().__init__(
            "Dead Clip",
            "chupiwarn.png",
            "This clip is marked Dead and won't play normally",
            body,
            primary_label="Try to recover",
            secondary_label="Not now",
            parent=parent,
            **theme,
        )


class DeadClipSalvageDialog(_MascotConfirmDialog):
    """Force play (salvage) — explicit user gamble."""

    def __init__(self, parent=None, **theme):
        body = (
            "Steempeg can rebuild a salvage manifest from surviving chunks. "
            "If this clip's own decoder header (init) is missing or corrupt, "
            "recovery needs one healthy donor clip of the same game already in your library. "
            "Without that donor, salvage usually cannot work.\n\n"
            "You may see garbled video, only audio, or nothing. "
            "If it plays, the clip stays labelled Dead but can be rendered."
        )
        super().__init__(
            "Force play (salvage)",
            "chupicutewarn.png",
            "Try to force-play this dead clip?",
            body,
            primary_label="Try anyway",
            secondary_label="Cancel",
            parent=parent,
            min_width=520,
            height=330,
            **theme,
        )


class DeadClipSalvageFailedDialog(SteempegDialog):
    """Salvage manifest could not be built."""

    def __init__(self, parent=None, **theme):
        super().__init__("Nothing to salvage", parent, **theme)
        self.setMinimumWidth(480)
        self.resize(520, 280)

        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(_mascot_label("chupiwarn.png"), 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(8)
        title = QLabel("Could not recover this clip")
        title.setStyleSheet(
            f"color: {tok.TEXT_TITLE}; font-size: 15px; font-weight: 600; background: transparent;"
        )
        col.addWidget(title)
        body = QLabel(
            "Either there are no usable video chunks, or the decoder header is gone "
            "and no healthy donor clip of the same game is in your library.\n\n"
            "Add at least one working clip of this game, then try Force play (salvage) again. "
            "Without a same-game donor, this dead clip cannot be revived."
        )
        body.setWordWrap(True)
        body.setStyleSheet(
            f"color: {tok.TEXT_PRIMARY}; font-size: 12px; background: transparent;"
        )
        col.addWidget(body)
        row.addLayout(col, 1)
        self.content_layout.addLayout(row)

        actions = QHBoxLayout()
        actions.addStretch(1)
        btn_ok = QPushButton("OK")
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.setStyleSheet(_BTN_SECONDARY)
        btn_ok.setFixedWidth(100)
        btn_ok.clicked.connect(self.accept)
        actions.addWidget(btn_ok)
        self.content_layout.addLayout(actions)


class DeadClipSalvageVerifyDialog(SteempegDialog):
    """After salvage playback starts — confirm recovery and optional auto-play."""

    def __init__(self, parent=None, **theme):
        super().__init__("Salvage playback", parent, **theme)
        self.setMinimumWidth(500)
        self.resize(540, 320)
        self._accepted_yes = False

        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(_mascot_label("chupisuccess.png"), 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(8)
        title = QLabel("Did the salvaged clip play correctly?")
        title.setWordWrap(True)
        title.setStyleSheet(
            f"color: {tok.TEXT_TITLE}; font-size: 15px; font-weight: 600; background: transparent;"
        )
        col.addWidget(title)
        body = QLabel(
            "If playback looks or sounds right, Steempeg will run an internal check. "
            "Only when real decoded playback is detected will this clip be marked "
            "<b>Cured</b> and allowed into the render queue.\n\n"
            "Saying yes without actual playback will not grant Cured status."
        )
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setStyleSheet(
            f"color: {tok.TEXT_PRIMARY}; font-size: 12px; background: transparent;"
        )
        col.addWidget(body)
        row.addLayout(col, 1)
        self.content_layout.addLayout(row)

        self._chk_auto_play = SteempegCheckBox(
            "Always play this clip via salvage without asking",
        )
        self.content_layout.addWidget(self._chk_auto_play)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)

        btn_no = QPushButton("Not yet")
        btn_no.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_no.setStyleSheet(_BTN_SECONDARY)
        btn_no.clicked.connect(self.reject)
        actions.addWidget(btn_no)

        btn_yes = QPushButton("Yes, it works")
        btn_yes.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_yes.setStyleSheet(_BTN_PRIMARY)
        btn_yes.clicked.connect(self._accept_yes)
        actions.addWidget(btn_yes)

        self.content_layout.addLayout(actions)

    def _accept_yes(self) -> None:
        self._accepted_yes = True
        self.accept()

    @property
    def accepted_yes(self) -> bool:
        return self._accepted_yes

    def always_play_salvage(self) -> bool:
        return self._chk_auto_play.isChecked()


def dialog_theme(parent) -> dict:
    from steempeg.ui import design_tokens as tok

    theme = tok.chrome_theme_colors(getattr(parent, "_chrome_theme", tok.DEFAULT_CHROME_THEME))
    return {"bar_color": theme["title_bar"], "bg_color": theme["app_bg"]}
