"""Dedicated mini-editor for Custom export presets (v49).

Build / edit a recipe without hijacking the live Video Settings panel.
Soft monitor warning when quality ≫ screen; optional quality fallback for apply.
"""
from __future__ import annotations

import logging
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.core import capabilities
from steempeg.render.encode_speed import ENCODE_SPEED_OPTIONS, normalize_encode_speed
from steempeg.render.export_presets import (
    get_preset_settings,
    load_presets_map,
    save_preset,
)
from steempeg.render.output_formats import (
    AUDIO_FORMATS,
    CONTAINERS,
    DEFAULT_CODEC_TEXT,
    VIDEO_CODEC_ITEMS,
)
from steempeg.render.quality_presets import (
    build_quality_presets,
    format_quality_item,
    original_quality_label,
    parse_quality_height,
)
from steempeg.render.queue import RenderJobSettings
from steempeg.ui import design_tokens as tok
from steempeg.ui import ui_theme as ut
from steempeg.ui.message_dialog import (
    dialog_theme,
    steempeg_information,
    steempeg_question,
    steempeg_warning,
)
from steempeg.ui.ui_density import COMFORT
from steempeg.ui.widgets.combo_chrome import apply_dark_combo_popup
from steempeg.ui.widgets.dialog_chrome import SteempegDialog
from steempeg.ui.widgets.steempeg_check import SteempegCheckBox

_log = logging.getLogger(__name__)

_FALLBACK_ORIGINAL = "Original"
_BITRATE_LEVELS = ("Ultra", "High", "Medium", "Low")
_FPS_CHOICES = (
    ("Original", "Original"),
    ("30 FPS", "30 FPS"),
    ("60 FPS", "60 FPS"),
)

# Match Video / Audio / Export Settings captions (render_panel._FIELD_LABEL_QSS).
_FIELD_LABEL_QSS = (
    "color: #8a8a8a; font-size: 13px; font-weight: bold;"
    f" background: transparent; font-family: {tok.FONT_APP};"
)
_SECTION_QSS = (
    "color: #ffffff; font-size: 15px; font-weight: bold;"
    f" background: transparent; font-family: {tok.FONT_APP};"
)
_NAME_LABEL_QSS = (
    "color: #cccccc; font-size: 12px; font-weight: bold;"
    f" background: transparent; font-family: {tok.FONT_APP};"
)

_BTN_PRIMARY = """
    QPushButton {
        background-color: #4a3d66; color: #f0ecff; border: 2px solid #6b5a8e;
        border-radius: 8px; padding: 8px 16px; font-size: 12px; font-weight: bold;
        font-family: <<FONT>>;
    }
    QPushButton:hover { background-color: #5a4d76; border-color: #b29ae7; }
    QPushButton:pressed { background-color: #3a324a; }
""".replace("<<FONT>>", tok.FONT_APP)

_HINT = f"color: {tok.TEXT_MUTED}; background: transparent; font-size: 11px;"


def _settings_combo_line_h(dense=COMFORT) -> int:
    """Same height math as Video Settings (render_panel.apply_settings_panel_density)."""
    field_font = int(dense.footer_font)
    border = 1 if dense.compact else 2
    pad_v = 7 if dense.scale >= 0.85 else 3
    return max(int(dense.combo_min_h), field_font + pad_v * 2 + border * 2 + 2)


def _field_cell(caption: str, combo: QComboBox) -> QVBoxLayout:
    """Caption above combo — same stack as Video Settings ``_field``."""
    box = QVBoxLayout()
    box.setSpacing(4)
    box.setContentsMargins(0, 0, 0, 0)
    lbl = QLabel(caption)
    lbl.setStyleSheet(_FIELD_LABEL_QSS)
    lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    box.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignLeft)
    box.addWidget(combo)
    return box


def _section_title(text: str) -> QLabel:
    sec = QLabel(text)
    sec.setStyleSheet(_SECTION_QSS)
    return sec


def _apply_settings_combo_chrome(*combos: QComboBox) -> None:
    """Same face as Video Settings; floor height so a tight dialog cannot squash."""
    dense = COMFORT
    field_font = int(dense.footer_font)
    line_h = _settings_combo_line_h(dense)
    # Vertical padding comes from fixed height centering — QSS padding-top/bottom
    # + a short layout slot is what flattened the Video grid rows.
    field_bg, field_border, drop_bg = ut.render_settings_active_combo_colors()
    from steempeg.ui.widgets.combo_chrome import combo_popup_item_rules

    combo_qss = f"""
    QComboBox {{
        background-color: {field_bg}; color: #ffffff;
        border: 2px solid {field_border}; border-radius: 12px;
        padding: 0px 10px; font-size: {field_font}px; font-weight: bold;
        font-family: {tok.FONT_APP};
        min-height: {line_h}px; max-height: {line_h}px;
    }}
    QComboBox:hover {{ border: 2px solid #6b5a8e; }}
    QComboBox:disabled {{
        background-color: #262626; color: #5a5a5a; border: 2px solid #333333;
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding; subcontrol-position: top right;
        width: 30px; background-color: {drop_bg};
        border-left: 2px solid {field_border};
        border-top-right-radius: 10px; border-bottom-right-radius: 10px;
    }}
    QComboBox::drop-down:disabled {{ background-color: #1f1f1f; }}
    QComboBox::down-arrow {{
        width: 0; height: 0;
        border-left: 5px solid transparent; border-right: 5px solid transparent;
        border-top: 6px solid #cccccc;
    }}
    """ + combo_popup_item_rules(dense)
    for combo in combos:
        if combo is None:
            continue
        combo.setFixedHeight(line_h)
        combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        combo.setStyleSheet(combo_qss)
        apply_dark_combo_popup(combo, dense=dense)
        fnt = tok.pin_ui_font(combo.font())
        fnt.setBold(True)
        fnt.setPixelSize(field_font)
        combo.setFont(fnt)


def _screen_height_px() -> int:
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return 0
    try:
        return int(screen.availableGeometry().height())
    except Exception:
        return 0


def _set_combo_data(combo: QComboBox, data: object) -> None:
    idx = combo.findData(data)
    if idx >= 0:
        combo.setCurrentIndex(idx)


def _set_combo_text(combo: QComboBox, text: str) -> None:
    if not text:
        return
    idx = combo.findText(text)
    if idx >= 0:
        combo.setCurrentIndex(idx)


class PresetMiniEditor(SteempegDialog):
    """Create or edit a Custom export preset as its own surface."""

    def __init__(
        self,
        app,
        *,
        edit_name: str | None = None,
        seed: RenderJobSettings | None = None,
        parent=None,
    ):
        theme = dialog_theme(parent or getattr(app, "ui", None))
        title = "Edit preset" if edit_name else "Create preset"
        super().__init__(title, parent or getattr(app, "ui", None), **theme)
        self._app = app
        self._edit_name = " ".join((edit_name or "").strip().split()) or None
        # No set_comfort_size / setFixedSize — that crushed combo bodies to slits.
        self.setMinimumSize(580, 620)
        self.resize(640, 720)

        root = self.content_layout
        root.setSpacing(10)

        # Scroll so the tall Video grid never compresses combo row heights.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        form = QVBoxLayout(body)
        form.setContentsMargins(0, 0, 4, 0)
        form.setSpacing(12)

        name_col = QVBoxLayout()
        name_col.setSpacing(4)
        name_col.setContentsMargins(0, 0, 0, 0)
        name_lbl = QLabel("Name")
        name_lbl.setStyleSheet(_NAME_LABEL_QSS)
        self._name = QLineEdit()
        self._name.setPlaceholderText("e.g. Discord 720p")
        self._name.setFixedHeight(_settings_combo_line_h())
        self._name.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._name.setStyleSheet(ut.presets_line_edit_stylesheet())
        if self._edit_name:
            self._name.setText(self._edit_name)
        name_col.addWidget(name_lbl, alignment=Qt.AlignmentFlag.AlignLeft)
        name_col.addWidget(self._name)
        form.addLayout(name_col)

        # --- Video (2-col grid like Video Settings) ---
        form.addWidget(_section_title("Video"))

        self._quality = QComboBox()
        self._quality.addItem(original_quality_label(None), "original")
        for label, height in build_quality_presets(4320):
            self._quality.addItem(label, height)

        self._fallback = QComboBox()
        self._fallback.addItem("Original (always last resort)", _FALLBACK_ORIGINAL)
        for label, _height in build_quality_presets(4320):
            self._fallback.addItem(f"Then {label}", label)
        self._fallback.setToolTip(
            "If this quality cannot apply to the clip (taller than source), "
            "try this instead. Original is always the final fallback."
        )

        self._bitrate = QComboBox()
        for level in _BITRATE_LEVELS:
            self._bitrate.addItem(level, level)

        self._fps = QComboBox()
        for label, data in _FPS_CHOICES:
            self._fps.addItem(label, data)

        self._codec = QComboBox()
        optional = set(capabilities.detect_optional_video_codecs())
        for item in VIDEO_CODEC_ITEMS:
            if item == "AV1" and "AV1" not in optional:
                continue
            if item == "VP9" and "VP9" not in optional:
                continue
            self._codec.addItem(item)

        self._encoder = QComboBox()
        encoders = capabilities.detect_supported_encoders()
        for display, codec in encoders:
            self._encoder.addItem(display, codec)
        if self._encoder.count() == 0:
            self._encoder.addItem("CPU (Software)", "libx264")

        self._speed = QComboBox()
        for opt in ENCODE_SPEED_OPTIONS:
            self._speed.addItem(opt.label, opt.id)

        video = QGridLayout()
        video.setContentsMargins(0, 0, 0, 0)
        video.setHorizontalSpacing(16)
        video.setVerticalSpacing(12)
        video.addLayout(_field_cell("Quality", self._quality), 0, 0)
        video.addLayout(_field_cell("If unavailable", self._fallback), 0, 1)
        video.addLayout(_field_cell("Bitrate tier", self._bitrate), 1, 0)
        video.addLayout(_field_cell("FPS", self._fps), 1, 1)
        video.addLayout(_field_cell("Codec", self._codec), 2, 0)
        video.addLayout(_field_cell("Encoder", self._encoder), 2, 1)
        video.addLayout(_field_cell("Encode speed", self._speed), 3, 0)
        video.setColumnStretch(0, 1)
        video.setColumnStretch(1, 1)
        form.addLayout(video)

        # --- Audio ---
        form.addWidget(_section_title("Audio"))

        self._mute = SteempegCheckBox("Disable audio (video only)")
        form.addWidget(self._mute)

        self._audio_fmt = QComboBox()
        for fmt in AUDIO_FORMATS:
            self._audio_fmt.addItem(fmt)

        self._audio_br = QComboBox()
        for kbps in (96, 128, 160, 192, 256, 320):
            self._audio_br.addItem(f"{kbps} kbps", kbps)

        audio = QGridLayout()
        audio.setContentsMargins(0, 0, 0, 0)
        audio.setHorizontalSpacing(16)
        audio.setVerticalSpacing(12)
        audio.addLayout(_field_cell("Audio format", self._audio_fmt), 0, 0)
        audio.addLayout(_field_cell("Audio bitrate", self._audio_br), 0, 1)
        audio.setColumnStretch(0, 1)
        audio.setColumnStretch(1, 1)
        form.addLayout(audio)

        # --- Export ---
        form.addWidget(_section_title("Export"))

        self._container = QComboBox()
        for c in CONTAINERS:
            self._container.addItem(c)

        export = QGridLayout()
        export.setContentsMargins(0, 0, 0, 0)
        export.setHorizontalSpacing(16)
        export.addLayout(_field_cell("Container", self._container), 0, 0)
        export.setColumnStretch(0, 1)
        export.setColumnStretch(1, 1)
        form.addLayout(export)
        form.addStretch(1)

        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        _apply_settings_combo_chrome(
            self._quality,
            self._fallback,
            self._bitrate,
            self._fps,
            self._codec,
            self._encoder,
            self._speed,
            self._audio_fmt,
            self._audio_br,
            self._container,
        )

        hint = QLabel(
            "Applies at render time: FPS cannot exceed the clip · "
            "missing GPU encoder falls back to CPU · "
            "quality taller than the source uses “If unavailable”, then Original."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(_HINT)
        root.addWidget(hint)

        actions = QHBoxLayout()
        actions.addStretch(1)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet(ut.settings_dialog_secondary_button_stylesheet())
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("Save")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setStyleSheet(_BTN_PRIMARY)
        btn_save.clicked.connect(self._on_save)
        actions.addWidget(btn_cancel)
        actions.addWidget(btn_save)
        root.addLayout(actions)

        self._quality.currentIndexChanged.connect(self._sync_original_locks)
        self._mute.toggled.connect(self._sync_audio_enabled)
        self._audio_fmt.currentIndexChanged.connect(self._sync_audio_enabled)

        if seed is not None:
            self._load_settings(seed)
        elif self._edit_name:
            loaded = get_preset_settings(self._edit_name, app.load_user_settings)
            if loaded is not None:
                self._load_settings(loaded)
        else:
            # Sensible new-preset defaults.
            _set_combo_data(self._quality, 1080)
            _set_combo_data(self._fallback, _FALLBACK_ORIGINAL)
            _set_combo_data(self._bitrate, "High")
            _set_combo_data(self._fps, "Original")
            enc_pairs = [
                (self._encoder.itemText(i), str(self._encoder.itemData(i) or ""))
                for i in range(self._encoder.count())
            ]
            idx = capabilities.preferred_encoder_index(enc_pairs)
            if 0 <= idx < self._encoder.count():
                self._encoder.setCurrentIndex(idx)
            _set_combo_data(self._speed, "balanced")
            _set_combo_text(self._audio_fmt, "AAC")
            _set_combo_data(self._audio_br, 192)
            _set_combo_text(self._container, "MP4")
            _set_combo_text(self._codec, DEFAULT_CODEC_TEXT)

        self._sync_original_locks()
        self._sync_audio_enabled()

    def _sync_original_locks(self) -> None:
        is_orig = self._quality.currentData() == "original"
        self._bitrate.setEnabled(not is_orig)
        self._codec.setEnabled(not is_orig)
        self._encoder.setEnabled(not is_orig)
        self._speed.setEnabled(not is_orig)
        self._fallback.setEnabled(not is_orig)
        self._fps.setEnabled(not is_orig)
        if is_orig:
            _set_combo_data(self._fps, "Original")

    def _sync_audio_enabled(self) -> None:
        on = not self._mute.isChecked()
        self._audio_fmt.setEnabled(on)
        self._audio_br.setEnabled(on and self._audio_fmt.currentText() not in ("FLAC", "WAV", "Copy"))

    def _load_settings(self, settings: RenderJobSettings) -> None:
        q = settings.quality_text or ""
        if "Original" in q and "Target" not in q:
            _set_combo_data(self._quality, "original")
        else:
            h = parse_quality_height(q)
            if h > 0:
                _set_combo_data(self._quality, h)
            else:
                _set_combo_text(self._quality, q)

        fb = (getattr(settings, "quality_fallback", None) or _FALLBACK_ORIGINAL).strip()
        if fb.lower().startswith("original") or not fb:
            _set_combo_data(self._fallback, _FALLBACK_ORIGINAL)
        else:
            idx = self._fallback.findData(fb)
            if idx < 0:
                # Try match by height label prefix.
                fh = parse_quality_height(fb)
                if fh > 0:
                    want = format_quality_item(fh)
                    idx = self._fallback.findData(want)
            if idx >= 0:
                self._fallback.setCurrentIndex(idx)

        br = settings.bitrate_text or ""
        level = br.split(" - ")[0].strip() if " - " in br else ""
        if level in _BITRATE_LEVELS:
            _set_combo_data(self._bitrate, level)
        else:
            _set_combo_data(self._bitrate, "High")

        fps = settings.fps_text or ""
        if "Original" in fps:
            _set_combo_data(self._fps, "Original")
        elif "30" in fps:
            _set_combo_data(self._fps, "30 FPS")
        elif "60" in fps:
            _set_combo_data(self._fps, "60 FPS")
        else:
            _set_combo_data(self._fps, "Original")

        if settings.codec_text:
            _set_combo_text(self._codec, settings.codec_text)
        if settings.encoder_codec:
            _set_combo_data(self._encoder, settings.encoder_codec)
        elif settings.encoder_display:
            _set_combo_text(self._encoder, settings.encoder_display)
        _set_combo_data(self._speed, normalize_encode_speed(settings.encode_speed))

        self._mute.setChecked(bool(settings.mute_audio or settings.audio_only))
        if settings.audio_format:
            _set_combo_text(self._audio_fmt, settings.audio_format)
        m = re.search(r"(\d+)", settings.audio_bitrate_text or "")
        if m:
            _set_combo_data(self._audio_br, int(m.group(1)))
        if settings.container_format:
            _set_combo_text(self._container, settings.container_format)

        self._sync_original_locks()
        self._sync_audio_enabled()

    def _build_settings(self) -> RenderJobSettings | None:
        qdata = self._quality.currentData()
        if qdata == "original":
            quality_text = original_quality_label(None)
            bitrate_text = "Unknown Mbps (Original)"
            codec_text = "H.264 (AVC)"  # stream copy — UI placeholder only
            encoder_codec = "libx264"
            encoder_display = "CPU (Software)"
            encode_speed = "balanced"
            fallback = _FALLBACK_ORIGINAL
            fps_text = "60 FPS (Original)"
        else:
            height = int(qdata or 1080)
            quality_text = self._quality.currentText()
            level = str(self._bitrate.currentData() or "High")
            from steempeg.render.quality_presets import bitrate_mbps_for

            presets = getattr(self._app, "steam_bitrate_presets", None) or {}
            mbps = bitrate_mbps_for(presets, level, height)
            if mbps is None:
                bitrate_text = f"{level} - 0 Mbps"
            else:
                bitrate_text = f"{level} - {mbps:g} Mbps"
            codec_text = self._codec.currentText() or DEFAULT_CODEC_TEXT
            encoder_codec = str(self._encoder.currentData() or "libx264")
            encoder_display = self._encoder.currentText() or ""
            encode_speed = normalize_encode_speed(
                str(self._speed.currentData() or "balanced")
            )
            fb_data = self._fallback.currentData()
            fallback = (
                _FALLBACK_ORIGINAL
                if fb_data == _FALLBACK_ORIGINAL
                else str(fb_data or _FALLBACK_ORIGINAL)
            )

        if qdata != "original":
            fps_data = str(self._fps.currentData() or "Original")
            if fps_data == "Original":
                fps_text = "60 FPS (Original)"
            else:
                fps_text = fps_data

        mute = self._mute.isChecked()
        audio_fmt = self._audio_fmt.currentText() or "AAC"
        kbps = int(self._audio_br.currentData() or 192)
        audio_br = f"{kbps} kbps"

        return RenderJobSettings(
            quality_text=quality_text,
            fps_text=fps_text,
            bitrate_text=bitrate_text,
            codec_text=codec_text,
            encoder_codec=encoder_codec,
            encoder_display=encoder_display,
            audio_only=False,
            mute_audio=mute,
            audio_format=audio_fmt,
            audio_bitrate_text=audio_br,
            container_format=self._container.currentText() or "MP4",
            output_preset="Custom",
            encode_speed=encode_speed,
            quality_fallback=fallback,
        )

    def _maybe_warn_monitor(self, settings: RenderJobSettings) -> bool:
        """Ask when chosen quality is much taller than the monitor. False = cancel."""
        h = parse_quality_height(settings.quality_text)
        screen_h = _screen_height_px()
        if h <= 0 or screen_h <= 0:
            return True
        if h <= screen_h * 1.15:
            return True
        return steempeg_question(
            self,
            "Quality taller than your screen?",
            f"You picked {h}p, but this monitor is about {screen_h}p tall.\n\n"
            f"Encoding taller than the display is fine for upload / archive — "
            f"just checking it was on purpose.\n\n"
            f"Keep {h}p?",
        )

    def _on_save(self) -> None:
        name = " ".join((self._name.text() or "").strip().split())
        if not name:
            steempeg_warning(self, "Save preset", "Enter a name for the preset first.")
            return
        settings = self._build_settings()
        if settings is None:
            return
        if not self._maybe_warn_monitor(settings):
            return

        existing = load_presets_map(self._app.load_user_settings)
        target = self._edit_name or name
        if self._edit_name and name != self._edit_name and name in existing:
            steempeg_warning(
                self,
                "Save preset",
                f"A preset named “{name}” already exists.",
            )
            return
        if not self._edit_name and name in existing:
            if not steempeg_question(
                self,
                "Overwrite preset?",
                f"“{name}” already exists. Overwrite it?",
            ):
                return

        try:
            if self._edit_name and name != self._edit_name:
                from steempeg.render.export_presets import rename_preset

                # Save under old key first, then rename — or save new + delete old.
                key = save_preset(
                    self._edit_name,
                    settings,
                    load_settings=self._app.load_user_settings,
                    save_settings=self._app.save_user_settings,
                )
                key = rename_preset(
                    key,
                    name,
                    load_settings=self._app.load_user_settings,
                    save_settings=self._app.save_user_settings,
                )
            else:
                key = save_preset(
                    name,
                    settings,
                    load_settings=self._app.load_user_settings,
                    save_settings=self._app.save_user_settings,
                )
        except Exception as exc:
            _log.exception("Preset mini-editor save failed")
            steempeg_warning(self, "Save preset", str(exc))
            return

        self._saved_name = key
        steempeg_information(self, "Preset saved", f"Saved “{key}”.")
        self.accept()


def open_preset_mini_editor(
    app,
    *,
    edit_name: str | None = None,
    seed: RenderJobSettings | None = None,
) -> str | None:
    """Open the editor; return saved preset name or None if cancelled."""
    dlg = PresetMiniEditor(
        app,
        edit_name=edit_name,
        seed=seed,
        parent=getattr(app, "ui", None),
    )
    if dlg.exec() != dlg.DialogCode.Accepted:
        return None
    return getattr(dlg, "_saved_name", None)
