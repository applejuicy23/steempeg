"""Compact one-off render settings for Express Player."""
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
)

from steempeg.render.quality_presets import build_quality_presets
from steempeg.render.queue import RenderJob
from steempeg.render.target_size import (
    audio_kbps_for_saved_target,
    clip_duration_and_height,
    plan_for_saved_target,
)
from steempeg.ui import design_tokens as tok, ui_theme as ut
from steempeg.ui.express_render import ExpressExportOptions
from steempeg.ui.message_dialog import dialog_theme
from steempeg.ui.widgets.dialog_chrome import SteempegDialog
from steempeg.ui.widgets.combo_chrome import apply_dark_combo_popup, settings_panel_stylesheet
from steempeg.ui.pro_appearance import accent_color


class ExpressExportDialog(SteempegDialog):
    def __init__(
        self, parent, *, source_height: int, source_fps: float, destination: str,
        target_job: RenderJob | None = None,
    ):
        title = "Target File Size" if target_job is not None else "Express Render Settings"
        super().__init__(title, parent, **dialog_theme(parent))
        self.setMinimumWidth(470)
        self._target_job = target_job
        self._destination_override = ""
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setSpacing(10)

        def add_field(name, field):
            label = QLabel(name)
            label.setStyleSheet(
                f"color: {tok.TEXT_MUTED}; font: bold 13px {tok.FONT_APP}; background: transparent;"
            )
            form.addRow(label, field)

        self._quality = QComboBox(self)
        self._quality.addItem("Source resolution", None)
        for label, height in build_quality_presets(source_height or 1080):
            if height and (not source_height or height < source_height):
                self._quality.addItem(label, height)
        self._fps = QComboBox()
        self._fps.addItem("Source FPS", None)
        for fps in (30, 60):
            if not source_fps or fps < source_fps:
                self._fps.addItem(f"{fps} FPS", fps)
        self._fps.addItem("Custom FPS…", "custom")
        self._custom_fps = QSpinBox()
        self._custom_fps.setRange(1, min(60, max(1, int(source_fps))) if source_fps else 60)
        self._custom_fps.setValue(24)
        spin_style = settings_panel_stylesheet().replace("QLineEdit", "QSpinBox")
        self._custom_fps.setStyleSheet(spin_style)

        self._codec = QComboBox()
        for codec in ("H.264 (AVC)", "H.265 (HEVC)"):
            self._codec.addItem(codec)
        for combo in (self._quality, self._fps, self._codec):
            combo.setStyleSheet(settings_panel_stylesheet())
            apply_dark_combo_popup(combo)
        if target_job is None:
            add_field("Quality Preset", self._quality)
        else:
            self._quality.hide()
            self._target_duration, self._target_height = clip_duration_and_height(target_job)
            maximum = max(1, int(target_job.settings.orig_video_mbps * self._target_duration / 8))
            self._target_slider = QSlider(Qt.Orientation.Horizontal)
            self._target_slider.setRange(1, maximum)
            self._target_slider.setValue(min(25, maximum))
            accent = accent_color("#b29ae7")
            self._target_slider.setStyleSheet(
                "QSlider::groove:horizontal { height: 5px; background: #414141; border-radius: 2px; }"
                f"QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}"
                f"QSlider::handle:horizontal {{ background: {accent}; width: 12px;"
                " margin: -5px 0; border-radius: 4px; }"
            )
            self._target_spin = QSpinBox()
            self._target_spin.setStyleSheet(spin_style)
            self._target_spin.setRange(1, maximum)
            self._target_spin.setValue(self._target_slider.value())
            self._target_spin.setSuffix(" MB")
            target_row = QHBoxLayout()
            target_row.addWidget(self._target_slider, 1)
            target_row.addWidget(self._target_spin)
            add_field("Target File Size", target_row)
            self._target_slider.valueChanged.connect(self._target_spin.setValue)
            self._target_spin.valueChanged.connect(self._target_slider.setValue)
            self._target_spin.valueChanged.connect(self._update_target_estimate)

        add_field("Framerate (FPS)", self._fps)
        add_field("Custom FPS", self._custom_fps)
        form.setRowVisible(self._custom_fps, False)
        self._fps.currentIndexChanged.connect(
            lambda: form.setRowVisible(self._custom_fps, self._fps.currentData() == "custom")
        )
        add_field("Codec", self._codec)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self._folder = QLineEdit(destination)
        self._folder.setReadOnly(True)
        self._folder.setStyleSheet(ut.settings_dialog_line_edit_stylesheet())
        self._folder.setCursorPosition(0)
        self._folder.setToolTip(destination)
        folder_row.addWidget(self._folder, 1)
        browse = QPushButton("Browse…")
        browse.setStyleSheet(ut.settings_dialog_secondary_button_stylesheet())
        browse.clicked.connect(self._browse)
        folder_row.addWidget(browse)
        add_field("Export folder", folder_row)
        self.content_layout.addLayout(form)

        self._hint = QLabel("This export re-encodes the video and uses the current trim range, if set.")
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(f"color: {tok.TEXT_MUTED}; background: transparent;")
        self.content_layout.addWidget(self._hint)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(ut.about_secondary_button_stylesheet())
        cancel.clicked.connect(self.reject)
        export = QPushButton("Export video")
        self._export = export
        export.setStyleSheet(ut.about_accent_button_stylesheet())
        export.clicked.connect(self.accept)
        for button in (browse, cancel, export):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        actions.addWidget(cancel)
        actions.addWidget(export)
        self.content_layout.addLayout(actions)
        if self._target_job is not None:
            self._fps.currentIndexChanged.connect(self._update_target_estimate)
            self._custom_fps.valueChanged.connect(self._update_target_estimate)
            self._update_target_estimate()

    def _selected_fps(self) -> int | None:
        choice = self._fps.currentData()
        return self._custom_fps.value() if choice == "custom" else choice

    def _update_target_estimate(self) -> None:
        fps = self._selected_fps()
        settings = replace(
            self._target_job.settings, custom_target_mb=self._target_spin.value(),
            custom_target_lossless=False, custom_fps=fps,
            fps_text="Custom FPS" if fps is not None else self._target_job.settings.fps_text,
        )
        plan = plan_for_saved_target(settings, self._target_duration, self._target_height)
        self._export.setEnabled(plan is not None)
        if plan is None:
            self._hint.setText("A source duration and bitrate are required to estimate file size.")
            return
        size = (plan.video_kbps + audio_kbps_for_saved_target(settings)) * self._target_duration / 8192
        height = plan.height if plan.height > 0 else self._target_height
        quality = f"{height}p" if height else "Source resolution"
        self._hint.setText(f"Estimated output: ~{size:.1f} MB · {quality} · {plan.video_kbps / 1000:g} Mbps")

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Export folder", self._folder.text())
        if folder:
            self._destination_override = folder
            self._folder.setText(folder)
            self._folder.setCursorPosition(0)
            self._folder.setToolTip(folder)

    def choose(self) -> ExpressExportOptions | None:
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        return ExpressExportOptions(
            self._quality.currentData(), self._selected_fps(), self._codec.currentText(),
            self._destination_override,
            target_mb=self._target_spin.value() if self._target_job is not None else None,
        )
