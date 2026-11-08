"""Expanded volume and speed controls showing the selected slider limit."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QWidget

from steempeg.ui.player.controls.audio import VolumeControlWidget
from steempeg.ui.player.controls.speed import SpeedControlWidget
from steempeg.ui.widgets.gradient_slider import level_expand_width
from steempeg.ui.widgets.clip_card_style_guide import ClipCardStyleCombo


def player_ceiling_copy(style: str) -> tuple[str, str, str]:
    """The limit label is shared by the choice list and the help card."""
    mode, value = style.split("|", 1)
    label = f"{int(value)}%" if mode == "volume" else f"{int(value) / 10:.1f}x"
    return label, "", ""


class PlayerCeilingDiagram(QWidget):
    """Two controls, with the selected slider expanded and filled to its end."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._volume = VolumeControlWidget(self)
        self._speed = SpeedControlWidget(self)
        self._speed_icon = self._speed.btn_icon.icon()
        self._speed_text = self._speed.btn_icon.text()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(12)
        layout.addWidget(self._volume)
        layout.addWidget(self._speed)
        self.setFixedSize(level_expand_width(40) + 44 + 12 + 16, 54)
        self.set_style("volume|100")

    def set_style(self, style: str) -> None:
        """Uses real, isolated player controls; only the sample slider is expanded."""
        self._mode, raw = style.split("|", 1)
        self._limit = player_ceiling_copy(style)[0]
        volume = self._mode == "volume"
        if volume:
            self._volume.apply_volume_ceiling(int(raw))
            self._volume.slider.setValue(int(raw))
        else:
            self._speed.apply_speed_ceiling(int(raw))
            self._speed.slider.setValue(int(raw))
        # The button identifies playback speed; the value beside the track is its ceiling.
        self._speed.btn_icon.setIcon(self._speed_icon)
        self._speed.btn_icon.setText(self._speed_text)
        for control, expanded in ((self._volume, volume), (self._speed, not volume)):
            control.setFixedWidth(level_expand_width(40) if expanded else 44)
            control.slider.setVisible(expanded)
            control.lbl_percent.setVisible(expanded)
        self.layout().activate()


class PlayerCeilingCombo(ClipCardStyleCombo):
    """Limit choices with the same expanded-control drawing as the ? card."""

    def __init__(self, mode: str, parent: QWidget | None = None):
        super().__init__(parent, diagram_factory=PlayerCeilingDiagram, copy_of=player_ceiling_copy)
        self._mode = mode

    def _guide_style(self, raw: str) -> str:
        return f"{self._mode}|{raw}"
