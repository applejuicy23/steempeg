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
from steempeg.ui.widgets.dialog_chrome import SteempegDialog

_BTN_PRIMARY = """
    QPushButton {
        background-color: #4a3d66; color: #f0ecff; border: 2px solid #6b5a8e;
        border-radius: 8px; padding: 8px 16px; font-size: 12px; font-weight: bold;
        font-family: <<FONT>>;
    }
    QPushButton:hover { background-color: #5a4d76; border-color: #b29ae7; }
    QPushButton:pressed { background-color: #3a324a; }
""".replace("<<FONT>>", tok.FONT_APP)

_BTN_SECONDARY = """
    QPushButton {
        background-color: #383838; color: #e0e0e0; border: 2px solid #4a4a4a;
        border-radius: 8px; padding: 8px 16px; font-size: 12px; font-weight: bold;
        font-family: <<FONT>>;
    }
    QPushButton:hover { background-color: #404040; color: #ffffff; border: 2px solid #6b5a8e; }
    QPushButton:pressed { background-color: #3a324a; border: 2px solid #b29ae7; }
""".replace("<<FONT>>", tok.FONT_APP)

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


_OFFER_MASCOT_W = 180


class DeadClipOfferDialog(QDialog):
    """First time a dead clip is opened — offer salvage.

    Frameless card in the Render Failed dialog language (shared
    ``render_error_dialog_stylesheet``): big mascot left, red title, bold issues,
    pill buttons. Esc / Not now → no.
    """

    def __init__(self, issues: list[str], parent=None, **_theme):
        super().__init__(parent)
        from steempeg.ui import ui_theme as ut

        self._choice = _YesNoChoice.NO
        self.setObjectName("SteempegDeadClipOfferDialog")
        self.setWindowTitle("Dead Clip")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Same card footprint as Render Failed (render_controller).
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
        pix = QPixmap(get_resource_path("chupiwarn.png"))
        if not pix.isNull():
            pic.setPixmap(
                pix.scaledToWidth(
                    _OFFER_MASCOT_W, Qt.TransformationMode.SmoothTransformation
                )
            )
        else:
            pic.setFixedWidth(_OFFER_MASCOT_W)
        pic.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        main_layout.addWidget(pic, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(12)

        title = QLabel("This clip is marked Dead and won't play normally")
        title.setObjectName("ErrorTitle")
        title.setWordWrap(True)
        col.addWidget(title)

        issues_lbl = QLabel("\n".join(f"• {issue}" for issue in issues[:6]))
        issues_lbl.setObjectName("ErrorHint")
        issues_lbl.setWordWrap(True)
        col.addWidget(issues_lbl)

        desc = QLabel(
            "Steempeg can try to salvage it from surviving chunks. "
            "If the decoder header is missing, recovery uses a healthy same-game "
            "clip from your library, or a bundled donor for that game when available. "
            "No donor at all = usually unrecoverable."
        )
        desc.setObjectName("ErrorDesc")
        desc.setWordWrap(True)
        col.addWidget(desc)
        col.addStretch(1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)

        btn_not_now = QPushButton("Not now")
        btn_not_now.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_not_now.clicked.connect(lambda: self._finish(_YesNoChoice.NO))
        actions.addWidget(btn_not_now)

        btn_recover = QPushButton("Try to recover")
        btn_recover.setObjectName("AccentBtn")
        btn_recover.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_recover.clicked.connect(lambda: self._finish(_YesNoChoice.YES))
        actions.addWidget(btn_recover)

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


class DeadClipSalvageDialog(_MascotConfirmDialog):
    """Force play (salvage) — explicit user gamble."""

    def __init__(self, parent=None, **theme):
        body = (
            "Steempeg can rebuild a salvage manifest from surviving chunks. "
            "If this clip's own decoder header (init) is missing or corrupt, "
            "recovery borrows one from a healthy same-game library clip, "
            "or from Steempeg's bundled donor pack for that game when present. "
            "Without any same-game donor, salvage usually cannot work.\n\n"
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
            "and no same-game donor was found (library or bundled pack).\n\n"
            "Add at least one working clip of this game — or wait for a bundled donor "
            "for this title — then try Force play (salvage) again."
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
