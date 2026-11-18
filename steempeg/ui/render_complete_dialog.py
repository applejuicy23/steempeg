"""Steempeg-styled dialog after a single clip finishes rendering."""
from __future__ import annotations

import os
from enum import Enum

from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtWidgets import QHBoxLayout, QMenu, QPushButton

from steempeg.render.queue import JobStatus, RenderJob
from steempeg.render.queue_display import format_job_output
from steempeg.ui import ui_theme as ut
from steempeg.ui.widgets.dialog_chrome import SteempegDialog
from steempeg.ui.widgets.play_video_button import PlayVideoSplitButton
from steempeg.ui.render_result_widgets import ExportResultCard, ResultHeader

class RenderCompleteChoice(Enum):
    OK = "ok"
    OPEN_FOLDER = "folder"
    PLAY = "play"
    OPEN_HISTORY = "history"
    OPEN_IN_STEEMPEG = "steempeg"


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
        cache_dir: str | None = None,
        elapsed_seconds: float | None = None,
    ):
        # Legacy cleanup arguments are accepted for older callers; the choice
        # is no longer shown and completion always removes its queue entries.
        super().__init__("Render complete", parent, bar_color=bar_color, bg_color=bg_color)
        from steempeg.ui.ui_density import scaled_dialog_size

        mw, _ = scaled_dialog_size(580, 340, parent=parent)
        rw, rh = scaled_dialog_size(600, 380 if show_clear_queue else 340, parent=parent)
        self.setMinimumWidth(mw)
        self.resize(rw, rh)
        self._choice = RenderCompleteChoice.OK
        self._output_file = output_file or (job.output_file or "").strip()

        self._result_header = ResultHeader("Clip exported successfully", "Your video is ready",
                                           elapsed_seconds=elapsed_seconds)
        self.content_layout.addWidget(self._result_header)
        out_path = self._output_file or format_job_output(job)
        self._result_card = ExportResultCard(job, output_file=out_path, cache_dir=cache_dir,
                                            status=JobStatus.COMPLETED)
        self.content_layout.addWidget(self._result_card)

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
        self._setup_play_menu(play_split)
        actions.addWidget(play_split, 0, Qt.AlignmentFlag.AlignVCenter)

        self.content_layout.addLayout(actions)
        self._footer_buttons = (btn_history, btn_ok, btn_folder)
        self._play_split = play_split
        # Fit the actual font and shared button padding without a spare gap.
        self.ensurePolished()
        self.content_layout.activate()
        buttons = (btn_history, btn_ok, btn_folder, play_split)
        row_width = sum(button.sizeHint().width() for button in buttons) + 3 * actions.spacing()
        content = self.content_layout.contentsMargins()
        body = self.content_layout.parentWidget().parentWidget().layout().contentsMargins()
        fitted_width = row_width + content.left() + content.right() + body.left() + body.right()
        self.setMinimumWidth(fitted_width)
        self.resize(fitted_width, self.minimumSizeHint().height())

    def apply_ui_theme_chrome(self) -> None:
        super().apply_ui_theme_chrome()
        self._result_header.apply_theme()
        self._result_card.apply_theme()
        for button in self._footer_buttons:
            button.setStyleSheet(ut.about_secondary_button_stylesheet())
        self._play_split.apply_ui_theme_chrome()

    def _setup_play_menu(self, play_split: PlayVideoSplitButton) -> None:
        # Rendered videos can register an existing export on demand, including
        # exports outside the default folder and paths with Windows aliases.
        available = os.path.isfile(self._output_file)
        play_split.set_menu_enabled(available)
        if not available:
            play_split.menu_btn.setToolTip("The exported file is unavailable.")

        menu = QMenu(self)
        menu.setStyleSheet(ut.library_menu_stylesheet())
        action_steempeg = menu.addAction("Open in Steempeg")
        action_steempeg.setToolTip(
            "Open the Rendered videos tab and preview this export in Steempeg."
        )
        action_steempeg.triggered.connect(self._open_in_steempeg)

        def _show_menu() -> None:
            if not os.path.isfile(self._output_file):
                play_split.set_menu_enabled(False)
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
        """Compatibility for older callers; completed queue entries always clear."""
        return True
