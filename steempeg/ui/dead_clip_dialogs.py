"""Steempeg-styled dialogs for dead-clip salvage flows (Chupi mascots)."""
from __future__ import annotations

from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from steempeg.ui.widgets.steempeg_check import SteempegCheckBox

from steempeg.infra.paths import get_resource_path
from steempeg.ui import design_tokens as tok


class _YesNoChoice(Enum):
    NO = "no"
    YES = "yes"


_CARD_MASCOT_W = 180


class _CardDialog(QDialog):
    """Frameless card in the Render Failed dialog language.

    Shares ``render_error_dialog_stylesheet`` and the 780×460 footprint: mascot
    left, title + bold hints + description right, pill buttons pinned bottom-right.
    Esc / secondary → no.
    """

    def __init__(
        self,
        mascot_asset: str,
        title: str,
        body: str,
        *,
        hints: list[str] | None = None,
        primary_label: str | None = None,
        secondary_label: str = "OK",
        title_tone: str = "accent",
        rich_body: bool = False,
        object_name: str = "SteempegDeadClipCardDialog",
        window_title: str = "",
        parent=None,
    ):
        super().__init__(parent)
        from steempeg.ui import ui_theme as ut

        self._choice = _YesNoChoice.NO
        self.setObjectName(object_name)
        if window_title:
            self.setWindowTitle(window_title)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(780, 460)

        shell = QWidget(self)
        shell.setObjectName("RenderErrorShell")
        shell.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shell.setStyleSheet(ut.render_error_dialog_stylesheet())
        self._shell = shell

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(shell)

        main_layout = QHBoxLayout(shell)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        pic = QLabel()
        pic.setStyleSheet("background: transparent; border: none;")
        pix = QPixmap(get_resource_path(mascot_asset))
        if not pix.isNull():
            pic.setPixmap(
                pix.scaledToWidth(
                    _CARD_MASCOT_W, Qt.TransformationMode.SmoothTransformation
                )
            )
        else:
            pic.setFixedWidth(_CARD_MASCOT_W)
        pic.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        main_layout.addWidget(pic, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(12)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("ErrorTitle" if title_tone == "error" else "AccentTitle")
        title_lbl.setWordWrap(True)
        col.addWidget(title_lbl)

        if hints:
            hints_lbl = QLabel("\n".join(f"• {h}" for h in hints[:6]))
            hints_lbl.setObjectName("ErrorHint")
            hints_lbl.setWordWrap(True)
            col.addWidget(hints_lbl)

        desc = QLabel(body)
        desc.setObjectName("ErrorDesc")
        desc.setWordWrap(True)
        if rich_body:
            desc.setTextFormat(Qt.TextFormat.RichText)
        col.addWidget(desc)
        col.addStretch(1)

        # Optional row above the buttons (e.g. a checkbox) — subclasses fill it.
        self.extra_layout = QVBoxLayout()
        self.extra_layout.setSpacing(6)
        col.addLayout(self.extra_layout)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)

        btn_secondary = QPushButton(secondary_label)
        btn_secondary.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_secondary.clicked.connect(lambda: self._finish(_YesNoChoice.NO))
        actions.addWidget(btn_secondary)

        if primary_label:
            btn_primary = QPushButton(primary_label)
            btn_primary.setObjectName("AccentBtn")
            btn_primary.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_primary.clicked.connect(lambda: self._finish(_YesNoChoice.YES))
            actions.addWidget(btn_primary)

        col.addLayout(actions)
        main_layout.addLayout(col, 1)

    def apply_ui_theme_chrome(self) -> None:
        """Live-retint if Settings switches theme while this dialog is open."""
        from steempeg.ui import ui_theme as ut

        self._shell.setStyleSheet(ut.render_error_dialog_stylesheet())

    def _finish(self, choice: _YesNoChoice) -> None:
        self._choice = choice
        if choice == _YesNoChoice.YES:
            self.accept()
        else:
            self.reject()

    @property
    def accepted_yes(self) -> bool:
        return self._choice == _YesNoChoice.YES


class DeadClipOfferDialog(_CardDialog):
    """First time a dead clip is opened — offer salvage."""

    def __init__(self, issues: list[str], parent=None, **_theme):
        super().__init__(
            "chupiwarn.png",
            "This clip is marked Dead and won't play normally",
            "Steempeg can try to salvage it from surviving chunks. "
            "If the decoder header is missing, recovery uses a healthy same-game "
            "clip from your library, or a bundled donor for that game when available. "
            "No donor at all = usually unrecoverable.",
            hints=issues,
            primary_label="Try to recover",
            secondary_label="Not now",
            title_tone="error",
            object_name="SteempegDeadClipOfferDialog",
            window_title="Dead Clip",
            parent=parent,
        )


class DeadClipSalvageDialog(_CardDialog):
    """Force play (salvage) — explicit user gamble."""

    def __init__(self, parent=None, **_theme):
        super().__init__(
            "chupicutewarn.png",
            "Try to force-play this dead clip?",
            "Steempeg can rebuild a salvage manifest from surviving chunks. "
            "If this clip's own decoder header (init) is missing or corrupt, "
            "recovery borrows one from a healthy same-game library clip, "
            "or from Steempeg's bundled donor pack for that game when present. "
            "Without any same-game donor, salvage usually cannot work.\n\n"
            "You may see garbled video, only audio, or nothing. "
            "If it plays, the clip stays labelled Dead but can be rendered.",
            primary_label="Try anyway",
            secondary_label="Cancel",
            object_name="SteempegDeadClipSalvageDialog",
            window_title="Force play (salvage)",
            parent=parent,
        )


class DeadClipSalvageFailedDialog(_CardDialog):
    """Salvage manifest could not be built."""

    def __init__(self, parent=None, **_theme):
        super().__init__(
            "chupiwarn.png",
            "Could not recover this clip",
            "Either there are no usable video chunks, or the decoder header is gone "
            "and no same-game donor was found (library or bundled pack).\n\n"
            "Add at least one working clip of this game — or wait for a bundled donor "
            "for this title — then try Force play (salvage) again.",
            secondary_label="OK",
            title_tone="error",
            object_name="SteempegDeadClipSalvageFailedDialog",
            window_title="Nothing to salvage",
            parent=parent,
        )


class DeadClipSalvageVerifyDialog(_CardDialog):
    """After salvage playback starts — confirm recovery and optional auto-play."""

    def __init__(self, parent=None, **_theme):
        super().__init__(
            "chupisuccess.png",
            "Did the salvaged clip play correctly?",
            "If playback looks or sounds right, Steempeg will run an internal check. "
            "Only when real decoded playback is detected will this clip be marked "
            "<b>Cured</b> and allowed into the render queue.<br><br>"
            "Saying yes without actual playback will not grant Cured status.",
            primary_label="Yes, it works",
            secondary_label="Not yet",
            rich_body=True,
            object_name="SteempegDeadClipSalvageVerifyDialog",
            window_title="Salvage playback",
            parent=parent,
        )
        self._chk_auto_play = SteempegCheckBox(
            "Always play this clip via salvage without asking",
        )
        self.extra_layout.addWidget(self._chk_auto_play)

    def always_play_salvage(self) -> bool:
        return self._chk_auto_play.isChecked()


def show_clip_cured_dialog(parent) -> None:
    """«Clip Cured» ack — bold Cured-icon lead line, then the plain explanation."""
    from steempeg.core.dash.health import HEALTH_COLORS, ClipHealth
    from steempeg.ui.icon_assets import health_icon
    from steempeg.ui.message_dialog import SteempegMessageDialog

    dlg = SteempegMessageDialog(
        "Clip Cured",
        "This clip is now marked Cured and can be added to the render queue.",
        parent,
    )

    lead = QHBoxLayout()
    lead.setSpacing(6)
    icon_lbl = QLabel()
    icon_lbl.setStyleSheet("background: transparent; border: none;")
    icon_lbl.setPixmap(health_icon(ClipHealth.CURED, 16).pixmap(16, 16))
    icon_lbl.setFixedSize(16, 16)
    lead.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
    lead_text = QLabel("Salvage playback was verified.")
    lead_text.setStyleSheet(
        f"color: {HEALTH_COLORS[ClipHealth.CURED]}; font-size: 13px; font-weight: bold; "
        f"background: transparent; font-family: {tok.FONT_APP};"
    )
    lead.addWidget(lead_text, 0, Qt.AlignmentFlag.AlignVCenter)
    lead.addStretch(1)
    dlg.content_layout.insertLayout(0, lead)
    dlg.exec()


def run_salvage_demo(
    parent, host=None, *, salvage_fails: bool = False, verify_fails: bool = False
) -> str:
    """Walk the real Dead Clip → salvage → verify → Cured dialogs with no clip I/O.

    Returns a short outcome tag for the caller's log.
    """
    from steempeg.ui.message_dialog import steempeg_warning

    theme = dialog_theme(host) if host is not None else {}
    offer = DeadClipOfferDialog(
        [
            "Missing or corrupt video init segment (init-stream0.m4s)",
            "Demo issue — no real clip is touched",
        ],
        parent=parent,
        **theme,
    )
    if not (offer.exec() and offer.accepted_yes):
        return "offer declined"

    confirm = DeadClipSalvageDialog(parent=parent, **theme)
    if not (confirm.exec() and confirm.accepted_yes):
        return "salvage cancelled"

    if salvage_fails:
        DeadClipSalvageFailedDialog(parent=parent, **theme).exec()
        return "salvage failed"

    verify = DeadClipSalvageVerifyDialog(parent=parent, **theme)
    if not (verify.exec() and verify.accepted_yes):
        return "verify skipped"

    if verify_fails:
        steempeg_warning(
            parent,
            "Could not verify playback",
            "Playback was not confirmed by the internal check, so this clip "
            "was not marked Cured.\n\n"
            "No decoded playback was detected.",
        )
        return "verify failed"

    show_clip_cured_dialog(parent)
    return "cured"


def dialog_theme(parent) -> dict:
    from steempeg.ui import design_tokens as tok

    theme = tok.chrome_theme_colors(getattr(parent, "_chrome_theme", tok.DEFAULT_CHROME_THEME))
    return {"bar_color": theme["title_bar"], "bg_color": theme["app_bg"]}
