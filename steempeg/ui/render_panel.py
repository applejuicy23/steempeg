"""Render settings panel — rebuilds the settings tabs into the mockup's look.

Built incrementally, one page at a time, re-housing the EXISTING widgets (created
in main_window_ui.py) into nicer layouts so render logic keeps working unchanged
(same objects, same self.ui.<name>). Step 1 here is the Video page: two-per-row
"field" cells (small label over a pill combo) plus a sliding toggle.
"""
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from steempeg.ui.widgets.toggle_switch import ToggleSwitch

_FIELD_LABEL_QSS = "color: #8a8a8a; font-size: 11px; font-weight: bold; background: transparent;"
_TOGGLE_LABEL_QSS = "color: #cccccc; font-size: 12px; font-weight: bold; background: transparent;"


def _drop_layout(widget):
    """Detach a widget's current layout so a new one can be set.

    Only call this AFTER every widget you want to keep has been setParent(None)'d:
    any widget still inside the layout gets reparented to the throwaway widget and
    deleted with it.
    """
    old = widget.layout()
    if old is not None:
        QWidget().setLayout(old)


def _field(label, combo):
    """A labelled field cell: small caption above the pill control."""
    box = QVBoxLayout()
    box.setSpacing(4)
    box.setContentsMargins(0, 0, 0, 0)
    label.setStyleSheet(_FIELD_LABEL_QSS)
    box.addWidget(label)
    box.addWidget(combo)
    return box


def restyle_video_page(ui):
    """Rebuild the Video Settings tab: 2-up field rows + a sliding 'Disable Audio' toggle.

    Reassigns ui.check_mute_audio to a ToggleSwitch (a QCheckBox subclass), so the
    existing toggled-connection and handlers keep working as-is.
    """
    page = ui.tab_video

    # Capture state + remove the old checkbox BEFORE dropping the layout
    # (dropping the layout would delete any widget still inside it).
    was_muted = False
    if hasattr(ui, "check_mute_audio") and ui.check_mute_audio is not None:
        was_muted = ui.check_mute_audio.isChecked()
        ui.check_mute_audio.setParent(None)
        ui.check_mute_audio.deleteLater()

    # Detach the widgets we are re-housing (keep them alive).
    keep = [
        ui.label_2, ui.combo_quality, ui.label_target_size, ui.size_slider,
        ui.label_5, ui.combo_fps, ui.label_4, ui.combo_bitrate,
        ui.label_14, ui.combo_codec, ui.label_6, ui.combo_encoder,
    ]
    for w in keep:
        w.setParent(None)

    _drop_layout(page)

    root = QVBoxLayout(page)
    root.setContentsMargins(6, 6, 6, 6)
    root.setSpacing(12)

    # Row 1: Quality | Framerate
    row1 = QHBoxLayout()
    row1.setSpacing(10)
    row1.addLayout(_field(ui.label_2, ui.combo_quality))
    row1.addLayout(_field(ui.label_5, ui.combo_fps))
    root.addLayout(row1)

    # Target-size controls (render logic shows them only in 'target size' mode)
    ui.label_target_size.setStyleSheet(_FIELD_LABEL_QSS)
    root.addWidget(ui.label_target_size)
    root.addWidget(ui.size_slider)

    # Row 2: Bitrate | Codec
    row2 = QHBoxLayout()
    row2.setSpacing(10)
    row2.addLayout(_field(ui.label_4, ui.combo_bitrate))
    row2.addLayout(_field(ui.label_14, ui.combo_codec))
    root.addLayout(row2)

    # Encoder (full width)
    root.addLayout(_field(ui.label_6, ui.combo_encoder))

    # Disable Audio -> sliding toggle + caption (replaces the old checkbox)
    toggle = ToggleSwitch()
    toggle.setObjectName("check_mute_audio")
    toggle.setChecked(was_muted)
    ui.check_mute_audio = toggle  # render logic / signal hookup use this name

    tog_row = QHBoxLayout()
    tog_row.setSpacing(10)
    tog_row.addWidget(toggle)
    caption = QLabel("Disable Audio (Video Only)")
    caption.setStyleSheet(_TOGGLE_LABEL_QSS)
    tog_row.addWidget(caption)
    tog_row.addStretch()
    root.addLayout(tog_row)

    root.addStretch()