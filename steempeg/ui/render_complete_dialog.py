"""Steempeg-styled dialog after a single clip finishes rendering."""
from __future__ import annotations

import os
from enum import Enum

from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout

from steempeg.infra.paths import get_resource_path, is_in_default_rendered_videos
from steempeg.render.queue import RenderJob
from steempeg.render.queue_display import format_job_output, format_job_preset, format_job_trim
from steempeg.ui import design_tokens as tok
from steempeg.ui import ui_theme as ut
from steempeg.ui.queue_card_shared import _FONT, set_game_icon_label
from steempeg.ui.widgets import ElidedLabel, SteempegCheckBox
from steempeg.ui.widgets.dialog_chrome import SteempegDialog
from steempeg.ui.widgets.play_video_button import PlayVideoSplitButton

_MASCOT_H = 110


class RenderCompleteChoice(Enum):
    OK = "ok"
    OPEN_FOLDER = "folder"
    PLAY = "play"
    OPEN_HISTORY = "history"
    OPEN_IN_STEEMPEG = "steempeg"


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
    open_in_rendered_requested = Signal(str)

    def __init__(
        self,
        job: RenderJob,
        output_file: str,
        parent=None,
        *,
        bar_color: str | None = None,
        bg_color: str | None = None,
        show_clear_queue: bool = False,
        always_clear_queue: bool = True,
    ):
        super().__init__("Render complete", parent, bar_color=bar_color, bg_color=bg_color)
        from steempeg.ui.ui_density import scaled_dialog_size

        mw, _ = scaled_dialog_size(580, 340, parent=parent)
        rw, rh = scaled_dialog_size(600, 380 if show_clear_queue else 340, parent=parent)
        self.setMinimumWidth(mw)
        self.resize(rw, rh)
        self._choice = RenderCompleteChoice.OK
        self._output_file = output_file or ""
        self._show_clear_queue = bool(show_clear_queue)

        body_row = QHBoxLayout()
        body_row.setSpacing(18)
        body_row.addWidget(_success_mascot(), 0, Qt.AlignmentFlag.AlignVCenter)

        header_text = QVBoxLayout()
        header_text.setSpacing(6)
        header_text.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        heading = QLabel("Clip exported successfully")
        heading.setStyleSheet(
            f"color: {tok.TEXT_TITLE}; font-family: {tok.FONT_SEMIBOLD}; "
            "font-size: 16px; font-weight: 700; background: transparent;"
        )
        header_text.addWidget(heading)
        summary = QLabel("Your video is ready")
        summary.setStyleSheet(
            f"color: #b29ae7; font-size: 13px; background: transparent; {_FONT}"
        )
        header_text.addWidget(summary)
        body_row.addLayout(header_text, 1)
        self.content_layout.addLayout(body_row)

        result_card = QFrame()
        result_card.setObjectName("renderResultCard")
        result_card.setStyleSheet(ut.render_result_card_stylesheet("renderResultCard"))
        details = QVBoxLayout(result_card)
        details.setContentsMargins(14, 12, 14, 12)
        details.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        game_icon = QLabel()
        set_game_icon_label(game_icon, job, size=28)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        game_name = job.game_name.strip() or os.path.basename(job.clip_path or "Clip")
        name_lbl = QLabel(game_name)
        name_lbl.setStyleSheet(
            f"color: {tok.TEXT_TITLE}; font-size: 14px; font-weight: 600; background: transparent; {_FONT}"
        )
        preset_lbl = QLabel(format_job_preset(job.settings))
        preset_lbl.setStyleSheet(f"color: {tok.TEXT_MUTED}; font-size: 11px; background: transparent; {_FONT}")
        title_col.addWidget(name_lbl)
        title_col.addWidget(preset_lbl)
        title_row.addWidget(game_icon, 0, Qt.AlignmentFlag.AlignTop)
        title_row.addLayout(title_col, 1)
        details.addLayout(title_row)
        source_date = " ".join(part for part in (job.clip_date, job.clip_time) if part)
        if source_date:
            date_lbl = QLabel(source_date)
            date_lbl.setStyleSheet(
                f"color: {tok.TEXT_MUTED}; font-size: 11px; background: transparent; {_FONT}"
            )
            details.addWidget(date_lbl)

        trim_text = format_job_trim(job.settings)
        if trim_text != "Full clip":
            trim_lbl = QLabel(trim_text)
            trim_lbl.setStyleSheet(f"color: #b29ae7; font-size: 11px; background: transparent; {_FONT}")
            details.addWidget(trim_lbl)

        out_path = output_file or format_job_output(job)
        path_lbl = ElidedLabel(f"📁 {out_path}")
        path_lbl.setToolTip(out_path)
        path_lbl.setStyleSheet(f"color: {tok.TEXT_MUTED}; font-size: 11px; background: transparent; {_FONT}")
        details.addWidget(path_lbl)

        self.content_layout.addWidget(result_card)

        self._chk_clear_queue = None
        if self._show_clear_queue:
            self._chk_clear_queue = SteempegCheckBox(
                "Remove from render queue"
            )
            self._chk_clear_queue.setChecked(bool(always_clear_queue))
            self.content_layout.addWidget(self._chk_clear_queue)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        btn_history = QPushButton("📜  Open Render History")
        btn_history.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_history.setStyleSheet(ut.about_secondary_button_stylesheet())
        btn_history.clicked.connect(lambda: self._pick(RenderCompleteChoice.OPEN_HISTORY))
        actions.addWidget(btn_history)

        btn_ok = QPushButton("OK")
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.setStyleSheet(ut.about_secondary_button_stylesheet())
        btn_ok.clicked.connect(lambda: self._pick(RenderCompleteChoice.OK))
        actions.addWidget(btn_ok)

        btn_folder = QPushButton("📂  Open folder")
        btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_folder.setStyleSheet(ut.about_secondary_button_stylesheet())
        btn_folder.clicked.connect(lambda: self._pick(RenderCompleteChoice.OPEN_FOLDER))
        actions.addWidget(btn_folder)

        play_split = PlayVideoSplitButton()
        play_split.play_clicked.connect(lambda: self._pick(RenderCompleteChoice.PLAY))
        self._setup_play_menu(play_split, out_path)
        actions.addWidget(play_split, 0, Qt.AlignmentFlag.AlignVCenter)

        self.content_layout.addLayout(actions)

    def _setup_play_menu(self, play_split: PlayVideoSplitButton, output_file: str) -> None:
        in_library = is_in_default_rendered_videos(output_file)
        play_split.set_menu_enabled(in_library)
        if in_library:
            play_split.menu_btn.setToolTip("More play options")
        else:
            play_split.menu_btn.setToolTip(
                "Open in Steempeg is only available when the file is in the rendered_videos folder."
            )

        menu = QMenu(self)
        menu.setStyleSheet(ut.library_menu_stylesheet())
        action_steempeg = menu.addAction("Open in Steempeg")
        action_steempeg.setEnabled(in_library)
        if in_library:
            action_steempeg.setToolTip(
                "Open the Rendered videos tab and preview this export in Steempeg."
            )
        else:
            action_steempeg.setToolTip(
                "Only available when the file was saved to the rendered_videos folder."
            )
        action_steempeg.triggered.connect(self._open_in_steempeg)

        def _show_menu() -> None:
            if not in_library:
                return
            menu.exec(
                play_split.menu_btn.mapToGlobal(
                    QPoint(0, play_split.menu_btn.height())
                )
            )

        play_split.menu_btn.clicked.connect(_show_menu)

    def _open_in_steempeg(self) -> None:
        if self._output_file:
            self.open_in_rendered_requested.emit(self._output_file)
        self._pick(RenderCompleteChoice.OPEN_IN_STEEMPEG)

    def _pick(self, choice: RenderCompleteChoice) -> None:
        self._choice = choice
        self.accept()

    def choice(self) -> RenderCompleteChoice:
        return self._choice

    def clear_queue(self) -> bool:
        if self._chk_clear_queue is None:
            return False
        return self._chk_clear_queue.isChecked()
