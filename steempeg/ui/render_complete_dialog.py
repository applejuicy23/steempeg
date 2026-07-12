"""Steempeg-styled dialog after a single clip finishes rendering."""
from __future__ import annotations

import os
from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from steempeg.infra.paths import get_resource_path
from steempeg.render.queue import RenderJob
from steempeg.render.queue_display import format_job_output, format_job_preset, format_job_trim
from steempeg.ui import design_tokens as tok
from steempeg.ui.queue_card_shared import _FONT, set_game_icon_label
from steempeg.ui.widgets import ElidedLabel
from steempeg.ui.widgets.dialog_chrome import SteempegDialog

_BTN_PRIMARY = """
    QPushButton {
        background-color: #4a3d66; color: #f0ecff; border: 2px solid #6b5a8e;
        border-radius: 8px; padding: 8px 16px; font-size: 12px; font-weight: bold;
        font-family: 'Segoe UI', Arial, sans-serif;
    }
    QPushButton:hover { background-color: #5a4d76; border-color: #b29ae7; }
    QPushButton:pressed { background-color: #3a324a; }
"""

_BTN_SECONDARY = """
    QPushButton {
        background-color: #383838; color: #e0e0e0; border: 2px solid #4a4a4a;
        border-radius: 8px; padding: 8px 16px; font-size: 12px; font-weight: bold;
        font-family: 'Segoe UI', Arial, sans-serif;
    }
    QPushButton:hover { background-color: #404040; color: #ffffff; border: 2px solid #6b5a8e; }
    QPushButton:pressed { background-color: #3a324a; border: 2px solid #b29ae7; }
"""

_MASCOT_H = 140


class RenderCompleteChoice(Enum):
    OK = "ok"
    OPEN_FOLDER = "folder"
    PLAY = "play"
    OPEN_HISTORY = "history"


def _success_mascot() -> QLabel:
    lbl = QLabel()
    lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)
    lbl.setStyleSheet("background: transparent; border: none;")
    pix = QPixmap(get_resource_path("chupisuccess.png"))
    if not pix.isNull():
        lbl.setPixmap(pix.scaledToHeight(_MASCOT_H, Qt.TransformationMode.SmoothTransformation))
        lbl.setFixedWidth(lbl.pixmap().width())
        lbl.setFixedHeight(_MASCOT_H)
    return lbl


class RenderCompleteDialog(SteempegDialog):
    def __init__(
        self,
        job: RenderJob,
        output_file: str,
        parent=None,
        *,
        bar_color: str | None = None,
        bg_color: str | None = None,
    ):
        super().__init__("Render complete", parent, bar_color=bar_color, bg_color=bg_color)
        self.setMinimumWidth(520)
        self.resize(560, 340)
        self._choice = RenderCompleteChoice.OK
        self._output_file = output_file or ""

        body_row = QHBoxLayout()
        body_row.setSpacing(18)
        body_row.addWidget(_success_mascot(), 0, Qt.AlignmentFlag.AlignVCenter)

        details = QVBoxLayout()
        details.setSpacing(8)

        heading = QLabel("Clip exported successfully")
        heading.setStyleSheet(
            f"color: {tok.TEXT_TITLE}; font-size: 15px; font-weight: 600; background: transparent;"
        )
        details.addWidget(heading)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        game_icon = QLabel()
        set_game_icon_label(game_icon, job, size=28)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        game_name = job.game_name.strip() or os.path.basename(job.clip_path or "Clip")
        name_lbl = QLabel(game_name)
        name_lbl.setStyleSheet(
            f"color: #f0f0f0; font-size: 14px; font-weight: 600; background: transparent; {_FONT}"
        )
        preset_lbl = QLabel(format_job_preset(job.settings))
        preset_lbl.setStyleSheet(f"color: #999999; font-size: 11px; background: transparent; {_FONT}")
        title_col.addWidget(name_lbl)
        title_col.addWidget(preset_lbl)
        title_row.addWidget(game_icon, 0, Qt.AlignmentFlag.AlignTop)
        title_row.addLayout(title_col, 1)
        details.addLayout(title_row)

        trim_text = format_job_trim(job.settings)
        if trim_text != "Full clip":
            trim_lbl = QLabel(f"✂️ {trim_text}")
            trim_lbl.setStyleSheet(f"color: #b29ae7; font-size: 11px; background: transparent; {_FONT}")
            details.addWidget(trim_lbl)

        out_path = output_file or format_job_output(job)
        path_lbl = ElidedLabel(f"📁 {out_path}")
        path_lbl.setToolTip(out_path)
        path_lbl.setStyleSheet(f"color: #aaaaaa; font-size: 11px; background: transparent; {_FONT}")
        details.addWidget(path_lbl)

        body_row.addLayout(details, 1)
        self.content_layout.addLayout(body_row)
        self.content_layout.addStretch(1)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        btn_history = QPushButton("📜  Open Render History")
        btn_history.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_history.setStyleSheet(_BTN_SECONDARY)
        btn_history.clicked.connect(lambda: self._pick(RenderCompleteChoice.OPEN_HISTORY))
        actions.addWidget(btn_history)

        actions.addStretch(1)

        btn_ok = QPushButton("OK")
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.setStyleSheet(_BTN_SECONDARY)
        btn_ok.clicked.connect(lambda: self._pick(RenderCompleteChoice.OK))
        actions.addWidget(btn_ok)

        btn_folder = QPushButton("📂  Open folder")
        btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_folder.setStyleSheet(_BTN_SECONDARY)
        btn_folder.clicked.connect(lambda: self._pick(RenderCompleteChoice.OPEN_FOLDER))
        actions.addWidget(btn_folder)

        btn_play = QPushButton("▶  Play video")
        btn_play.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_play.setStyleSheet(_BTN_PRIMARY)
        btn_play.clicked.connect(lambda: self._pick(RenderCompleteChoice.PLAY))
        actions.addWidget(btn_play)

        self.content_layout.addLayout(actions)

    def _pick(self, choice: RenderCompleteChoice) -> None:
        self._choice = choice
        self.accept()

    def choice(self) -> RenderCompleteChoice:
        return self._choice
