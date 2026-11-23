"""Explicit preset application marks, invalidated by the first settings edit."""
from __future__ import annotations

import weakref

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QPushButton
from steempeg.ui.pro_appearance import accent_qcolor



def _check_icon() -> QIcon:
    pixmap = QPixmap(36, 36)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(accent_qcolor(QColor("#b29ae7")), 4, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.drawPolyline(QPolygonF([QPointF(8, 18), QPointF(15, 25), QPointF(28, 11)]))
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


class PresetApplyButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__("Apply", parent)
        self.setFixedWidth(72)
        self.setIconSize(QSize(18, 18))

    def set_applied(self, applied: bool) -> None:
        changed = self.property("presetApplied") != applied
        self.setProperty("presetApplied", applied)
        self.setText("" if applied else "Apply")
        self.setIcon(_check_icon() if applied else QIcon())
        self.setAccessibleName("Applied" if applied else "Apply preset")
        self.setToolTip("Preset applied" if applied else "Apply this preset to the export panel")
        if changed:
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()


class PresetApplyState:
    """Keep marks through list rebuilds; never infer them from matching values."""

    def __init__(self, app):
        self.app = app
        self.token = None
        self.fingerprint = None
        self.buttons = []
        self.watched = weakref.WeakSet()

    def watch_settings(self):
        names = (
            "combo_quality", "combo_fps", "combo_bitrate", "combo_codec",
            "combo_encoder", "combo_encode_speed", "combo_audio_format",
            "combo_audio_bitrate", "combo_container", "combo_output_preset",
            "combo_rate_control", "combo_pro_quality", "combo_pro_preset",
            "combo_pro_tune", "combo_pro_keyint", "check_audio_only",
            "check_mute_audio", "check_pro_two_pass", "check_pro_ten_bit",
            "size_slider", "input_custom_fps", "input_custom_vbitrate",
            "input_custom_abitrate",
        )
        for owner in (getattr(self.app, "ui", None), self.app):
            for name in names:
                widget = getattr(owner, name, None)
                if widget is None or widget in self.watched:
                    continue
                for signal_name in ("currentIndexChanged", "toggled", "valueChanged", "textChanged"):
                    signal = getattr(widget, signal_name, None)
                    if signal is not None:
                        signal.connect(self._edited)
                        self.watched.add(widget)
                        break

    def register(self, button, token):
        self.buttons.append((weakref.ref(button), token))
        button.set_applied(token == self.token)

    def _sync(self):
        live = []
        for ref, token in self.buttons:
            button = ref()
            if button is not None:
                try:
                    button.set_applied(token == self.token)
                    live.append((ref, token))
                except RuntimeError:  # The old list's C++ widgets were deleted.
                    pass
        self.buttons = live

    def mark(self, token):
        self.watch_settings()
        self.token = token
        self.fingerprint = self._snapshot()
        self._sync()

    def clear(self):
        if self.token is not None:
            self.token = self.fingerprint = None
            self._sync()

    def _edited(self, *_):
        if not any(getattr(self.app, flag, False) for flag in (
            "_bulk_settings_apply", "_applying_export_preset", "_quality_combo_applying_custom",
        )):
            self.clear()

    def _snapshot(self):
        from steempeg.ui.render_job_builder import snapshot_settings_from_ui

        try:
            return self.app._custom_preset_canon_fp(snapshot_settings_from_ui(self.app))
        except (AttributeError, TypeError, ValueError):
            return None

    def revalidate(self):
        if self.token is not None and self.fingerprint is not None:
            if self._snapshot() != self.fingerprint:
                self._edited()


def preset_apply_state(app):
    state = getattr(app, "_preset_row_apply_state", None)
    if state is None:
        state = app._preset_row_apply_state = PresetApplyState(app)
    return state
