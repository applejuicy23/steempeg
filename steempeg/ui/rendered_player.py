"""Independent playback windows for multi-open rendered media."""
from __future__ import annotations

import logging
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from steempeg.infra.paths import get_resource_path
from steempeg.services.new_clip_watcher import NewClipInfo
from steempeg.ui.express_player import ExpressPlayerWindow


class RenderedMediaPlayerWindow(ExpressPlayerWindow):
    """Reuse Express transport and cleanup without clip export/delete actions."""

    def __init__(self, app, file_path: str):
        info = NewClipInfo(
            path=os.path.abspath(file_path), app_id="",
            game_name=os.path.basename(file_path),
            icon_path=get_resource_path("unknown_icon.png"),
            thumbnail_path="", duration_sec=None,
        )
        super().__init__(app, info)
        self.setProperty("steempeg_independent_player", True)
        self.setWindowTitle(f"{info.game_name} — Steempeg Player")

    def _build_footer(self) -> QFrame:
        from steempeg.ui.player.controls.audio import VolumeControlWidget
        from steempeg.ui.player.controls.timeline import CustomTimelineWidget

        footer = QFrame()
        footer.setObjectName("ExpressFooter")
        layout = QVBoxLayout(footer)
        layout.setContentsMargins(15, 10, 15, 12)
        self._timeline = CustomTimelineWidget()
        self._timeline.pause_requested.connect(self._on_timeline_press)
        self._timeline.seek_requested.connect(self._on_timeline_seek)
        self._timeline.resume_requested.connect(self._on_timeline_release)
        layout.addWidget(self._timeline)

        controls = QHBoxLayout()
        self._volume = VolumeControlWidget(footer)
        self._volume.slider.valueChanged.connect(self._on_volume_changed)
        controls.addWidget(self._volume)
        controls.addStretch(1)
        self._btn_skip_back = self._make_icon_button("less15.png", 28, "Back 15 s (←)")
        self._btn_skip_back.clicked.connect(lambda: self.skip_by(-15000))
        self._btn_play = self._make_icon_button("icon_play.png", 40, "Play / Pause (Space)", box=48)
        self._btn_play.clicked.connect(self.toggle_play)
        self._btn_skip_forward = self._make_icon_button("more15.png", 28, "Forward 15 s (→)")
        self._btn_skip_forward.clicked.connect(lambda: self.skip_by(15000))
        for button in (self._btn_skip_back, self._btn_play, self._btn_skip_forward):
            controls.addWidget(button)
        controls.addStretch(1)
        self._btn_fullscreen = self._make_icon_button("btn_fullscreen.png", 22, "Fullscreen (F)")
        self._btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        controls.addWidget(self._btn_fullscreen)
        layout.addLayout(controls)
        self._time_label = QLabel("0:00 / 0:00")
        self._time_label.setObjectName("ExpressTime")
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._time_label)
        self._footer = footer
        return footer

    def open_clip(self) -> None:
        """Play the exported file in this window's own MPV handle."""
        if not os.path.isfile(self._info.path):
            self._time_label.setText("File not found")
            return
        try:
            self._player = self._create_player()
            path = self._info.path.replace("\\", "/")
            self._attach_hover_preview(path)
            self._player.play(path)
            self._player.pause = False
            self._poll.start()
        except Exception:
            logging.exception("Rendered player: could not open %s", self._info.path)
            self._release_player()
            self._time_label.setText("Could not play this file")
