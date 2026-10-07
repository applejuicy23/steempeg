"""Steempeg PRO encoding controls on the Video settings page.

Widgets are built in ``render_panel._build_pro_encoding_section``; this module
keeps them in sync with the encoder / quality pickers and maps them to and from
``RenderJobSettings``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt

from steempeg.core import capabilities
from steempeg.render import pro_encoding as pro
from steempeg.render.output_formats import resolve_video_encoder

if TYPE_CHECKING:
    from steempeg.render.queue import RenderJobSettings

MODE_ORIGINAL = "original"
MODE_TARGET = "target"
MODE_HEIGHT = "height"
MODE_AUDIO = "audio"

_UNSUPPORTED_TIP = "Not available for AMF / QuickSync encoders yet — pick NVENC or CPU."


@dataclass(frozen=True)
class ProUiState:
    enabled: bool
    encoder: str
    mode: str
    rate_control: str
    quality: int
    two_pass: bool
    ten_bit: bool

    @property
    def constant_quality_active(self) -> bool:
        return (
            self.enabled
            and self.mode == MODE_HEIGHT
            and self.rate_control == pro.RATE_QUALITY
            and pro.supports_constant_quality(self.encoder)
        )

    @property
    def two_pass_active(self) -> bool:
        return (
            self.enabled
            and self.mode == MODE_TARGET
            and self.two_pass
            and pro.supports_two_pass(self.encoder)
        )

    @property
    def ten_bit_active(self) -> bool:
        return (
            self.enabled
            and self.mode in (MODE_TARGET, MODE_HEIGHT)
            and self.ten_bit
            and pro.supports_ten_bit(self.encoder)
        )


def pro_enabled(app) -> bool:
    cached = getattr(app, "_steempeg_pro_enabled", None)
    if cached is None:
        from steempeg.ui.settings_prefs import resolve_steempeg_pro

        cached = app._steempeg_pro_enabled = bool(resolve_steempeg_pro())
    return bool(cached)


def _ui_encoder(ui) -> str:
    codec_raw = ui.combo_codec.currentText() if hasattr(ui, "combo_codec") else ""
    data = ui.combo_encoder.currentData(Qt.UserRole) if hasattr(ui, "combo_encoder") else None
    return str(
        resolve_video_encoder(
            codec_raw,
            str(data) if data else "libx264",
            capabilities.av1_encoder_available(),
        )
    )


def _ui_mode(ui) -> str:
    if hasattr(ui, "check_audio_only") and ui.check_audio_only.isChecked():
        return MODE_AUDIO
    text = ui.combo_quality.currentText() if hasattr(ui, "combo_quality") else ""
    if "Target File Size" in text:
        return MODE_TARGET
    if "Original" in text:
        return MODE_ORIGINAL
    if re.match(r"^\d+p", text or ""):
        return MODE_HEIGHT
    return MODE_ORIGINAL


def read_pro_state(app) -> ProUiState:
    ui = app.ui
    encoder = _ui_encoder(ui)
    rate = pro.RATE_BITRATE
    quality = -1
    two_pass = ten_bit = False
    if hasattr(ui, "combo_rate_control"):
        rate = pro.normalize_rate_control(ui.combo_rate_control.currentData(Qt.UserRole))
        data = ui.combo_pro_quality.currentData(Qt.UserRole)
        quality = int(data) if data is not None else -1
        two_pass = ui.check_pro_two_pass.isChecked()
        ten_bit = ui.check_pro_ten_bit.isChecked()
    return ProUiState(
        enabled=pro_enabled(app) and hasattr(ui, "pro_encoding_box"),
        encoder=encoder,
        mode=_ui_mode(ui),
        rate_control=rate,
        quality=quality,
        two_pass=two_pass,
        ten_bit=ten_bit,
    )


def _fill_quality_combo(ui, encoder: str, wanted: int) -> None:
    combo = ui.combo_pro_quality
    choices = pro.quality_choices(encoder)
    combo.blockSignals(True)
    combo.clear()
    for value, label in choices:
        combo.addItem(label, value)
    if choices:
        target = pro.clamp_quality(encoder, wanted)
        idx = combo.findData(target, Qt.UserRole)
        if idx < 0:
            # Keep an off-grid value (e.g. restored from a job) selectable.
            scale = pro.quality_scale(encoder)
            combo.addItem(f"{scale.flag} {target}", target)
            idx = combo.count() - 1
        combo.setCurrentIndex(idx)
    combo.blockSignals(False)


def _set_enabled_with_tip(widgets, enabled: bool, tip: str) -> None:
    for w in widgets:
        w.setEnabled(enabled)
        w.setToolTip(tip)


def refresh_pro_controls(app) -> None:
    """Visibility, per-encoder ranges and enable state of the PRO controls."""
    ui = app.ui
    box = getattr(ui, "pro_encoding_box", None)
    if box is None:
        return
    enabled = pro_enabled(app)
    box.setVisible(enabled)

    combo_rate = ui.combo_rate_control
    if combo_rate.count() == 0:
        combo_rate.blockSignals(True)
        for key, label in pro.RATE_CONTROL_OPTIONS:
            combo_rate.addItem(label, key)
        combo_rate.blockSignals(False)

    state = read_pro_state(app)
    encoder = state.encoder
    previous = getattr(app, "_pro_quality_by_family", None)
    if previous is None:
        previous = app._pro_quality_by_family = {}
    family = pro.pro_family(encoder)
    remembered = previous.get(family, state.quality if state.quality >= 0 else -1)
    if ui.combo_pro_quality.property("pro_family") != family:
        _fill_quality_combo(ui, encoder, remembered)
        ui.combo_pro_quality.setProperty("pro_family", family)

    video_encode = state.mode in (MODE_TARGET, MODE_HEIGHT)
    cq_supported = pro.supports_constant_quality(encoder)
    if not cq_supported:
        rate_tip = _UNSUPPORTED_TIP
    elif state.mode == MODE_TARGET:
        rate_tip = "Target File Size picks the bitrate itself — constant quality needs a resolution preset."
    elif not video_encode:
        rate_tip = "Only for re-encoding presets (1440p / 1080p / …)."
    else:
        rate_tip = (
            "Bitrate: fixed Mbps from the Bitrate field.\n"
            "Constant quality: the encoder spends what each scene needs — "
            "same look everywhere, file size varies."
        )
    rate_ok = cq_supported and state.mode == MODE_HEIGHT
    _set_enabled_with_tip((combo_rate, ui.label_rate_control), rate_ok, rate_tip)

    quality_ok = rate_ok and state.rate_control == pro.RATE_QUALITY
    scale = pro.quality_scale(encoder)
    quality_tip = (
        f"{scale.flag} {scale.low}–{scale.high}: lower = better quality, bigger file."
        if scale is not None
        else _UNSUPPORTED_TIP
    )
    _set_enabled_with_tip((ui.combo_pro_quality, ui.label_pro_quality), quality_ok, quality_tip)
    if scale is not None:
        ui.label_pro_quality.setText(f"Constant Quality ({scale.flag})")

    if not pro.supports_two_pass(encoder):
        two_tip = _UNSUPPORTED_TIP
    elif state.mode != MODE_TARGET:
        two_tip = "Only for Target File Size — the first pass measures the clip so the size lands on target."
    elif not pro.two_pass_runs_twice(encoder):
        two_tip = "NVENC runs its analysis pass inside one encode (multipass)."
    else:
        two_tip = "Encodes twice: pass 1 analyses the clip, pass 2 hits the size more precisely. ~2× slower."
    two_ok = pro.supports_two_pass(encoder) and state.mode == MODE_TARGET
    _set_enabled_with_tip((ui.check_pro_two_pass, ui.label_pro_two_pass), two_ok, two_tip)

    if not pro.supports_ten_bit(encoder):
        ten_tip = "This encoder has no 10-bit mode here — pick H.265, AV1 or VP9 (or H.264 CPU)."
    elif not video_encode:
        ten_tip = "Only for re-encoding presets."
    else:
        ten_tip = "Smoother gradients, less banding in skies and fog.\n" + pro.ten_bit_note(encoder)
    ten_ok = pro.supports_ten_bit(encoder) and video_encode
    _set_enabled_with_tip((ui.check_pro_ten_bit, ui.label_pro_ten_bit), ten_ok, ten_tip)

    sync_bitrate_lock(app, state)


def sync_bitrate_lock(app, state: ProUiState | None = None) -> None:
    """Grey out the Bitrate field while constant quality drives the encode."""
    ui = app.ui
    combo = getattr(ui, "combo_bitrate", None)
    if combo is None:
        return
    state = state or read_pro_state(app)
    locked = state.constant_quality_active
    if state.mode == MODE_HEIGHT:
        combo.setEnabled(not locked)
    combo.setToolTip("Constant quality is on — bitrate varies per scene." if locked else "")
    label = getattr(ui, "label_4", None)
    if label is not None:
        label.setEnabled(not locked)


def remember_quality_choice(app) -> None:
    ui = app.ui
    data = ui.combo_pro_quality.currentData(Qt.UserRole)
    if data is None:
        return
    family = ui.combo_pro_quality.property("pro_family")
    if family:
        if getattr(app, "_pro_quality_by_family", None) is None:
            app._pro_quality_by_family = {}
        app._pro_quality_by_family[str(family)] = int(data)


def snapshot_pro_fields(app) -> dict:
    """``RenderJobSettings`` PRO fields; defaults when PRO is off."""
    state = read_pro_state(app)
    if not state.enabled:
        return {}
    return {
        "pro_rate_control": state.rate_control,
        "pro_quality": state.quality,
        "pro_two_pass": state.two_pass,
        "pro_ten_bit": state.ten_bit,
    }


def apply_pro_fields_to_ui(app, settings: RenderJobSettings) -> None:
    ui = app.ui
    if not hasattr(ui, "combo_rate_control"):
        return
    widgets = (ui.combo_rate_control, ui.combo_pro_quality, ui.check_pro_two_pass, ui.check_pro_ten_bit)
    for w in widgets:
        w.blockSignals(True)
    try:
        if ui.combo_rate_control.count() == 0:
            for key, label in pro.RATE_CONTROL_OPTIONS:
                ui.combo_rate_control.addItem(label, key)
        idx = ui.combo_rate_control.findData(
            pro.normalize_rate_control(settings.pro_rate_control), Qt.UserRole
        )
        if idx >= 0:
            ui.combo_rate_control.setCurrentIndex(idx)
        encoder = _ui_encoder(ui)
        _fill_quality_combo(ui, encoder, int(settings.pro_quality))
        ui.combo_pro_quality.setProperty("pro_family", pro.pro_family(encoder))
        ui.check_pro_two_pass.setChecked(bool(settings.pro_two_pass))
        ui.check_pro_ten_bit.setChecked(bool(settings.pro_ten_bit))
    finally:
        for w in widgets:
            w.blockSignals(False)
    remember_quality_choice(app)
    refresh_pro_controls(app)


def pro_summary_tags(app) -> list[str]:
    """Short labels for the detailed summary (``CRF 20``, ``2-pass``, ``10-bit``)."""
    state = read_pro_state(app)
    tags: list[str] = []
    if state.constant_quality_active:
        scale = pro.quality_scale(state.encoder)
        tags.append(f"{scale.flag} {pro.clamp_quality(state.encoder, state.quality)}")
    if state.two_pass_active:
        tags.append("2-pass" if pro.two_pass_runs_twice(state.encoder) else "multipass")
    if state.ten_bit_active:
        tags.append("10-bit")
    return tags
