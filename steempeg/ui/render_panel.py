"""Render settings panel — rebuilds the settings tabs into the mockup's look.

Re-houses the EXISTING widgets (from main_window_ui.py) into nicer layouts so render
logic keeps working unchanged (same objects, same self.ui.<name>): a page title,
two-per-row "field" cells, sliding toggles, and a Source Info grid of stat blocks.

Custom-value combos (FPS / Bitrate / Audio Bitrate) get an inline edit field that is
overlaid on the combo's body when the last item ("Custom …") is picked. The overlay is an
opaque chip [gear | edit | unit] so it fully covers the "Custom …" text; the unit (FPS /
Mbps / kbps) sits next to the drop-down arrow. The combo stays NON-editable, so
currentText() still returns "Custom …" and every value-reading branch in render_controller
keeps working untouched — we only expose the edit + warning icon on `ui`.
"""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from steempeg.ui.widgets.gradient_slider import GradientSlider
from steempeg.ui.widgets.toggle_switch import ToggleSwitch

_FONT = "font-family: 'Segoe UI', Arial, sans-serif;"
_COMBO_W = 340  # every combo is exactly this wide -> uniform, not stretched to the edge
_FIELD_LABEL_QSS = "color: #8a8a8a; font-size: 11px; font-weight: bold; background: transparent; " + _FONT
_TOGGLE_LABEL_QSS = "color: #cccccc; font-size: 12px; font-weight: bold; background: transparent; " + _FONT
_TITLE_QSS = "color: #ffffff; font-size: 15px; font-weight: bold; background: transparent; " + _FONT
_PATHBOX_QSS = ("QLabel { background-color: #252525; border-radius: 10px; padding: 8px 12px;"
                " color: #b29ae7; font-size: 11px; font-weight: bold; font-family: 'Consolas', monospace; }")
_STAT_CAP_QSS = "color: #8a8a8a; font-size: 10px; font-weight: bold; background: transparent; border: none; " + _FONT
_STAT_VAL_QSS = "color: #ffffff; font-size: 14px; font-weight: bold; background: transparent; border: none; " + _FONT
_STAT_FRAME_QSS = "QFrame { background-color: #303030; border: 1px solid #3a3a3a; border-radius: 12px; }"
# Target-size readout ("Target: … | Safe Bitrate: … / Quality: …") — a readable info card,
# not the tiny grey caption it used to borrow.
_TARGET_READOUT_QSS = ("QLabel { background-color: #303030; border: 1px solid #3a3a3a;"
                       " border-radius: 10px; padding: 9px 13px; color: #e0e0e0;"
                       " font-size: 12px; font-weight: normal; " + _FONT + " }")

# The overlay chip blends into the combo body and leaves the drop-down arrow uncovered.
# (Combo QSS: 2px border, 30px drop-down cell + its 2px left border -> reserve 32px on the right.)
_ARROW_RESERVE = 32
_BORDER = 2
_OVERLAY_QSS = ("QFrame#customOverlay { background-color: #383838;"
                " border-top-left-radius: 10px; border-bottom-left-radius: 10px; }")
_CUSTOM_EDIT_QSS = ("QLineEdit { background: transparent; border: none; color: #ffffff;"
                    " font-size: 12px; font-weight: bold; " + _FONT + " }"
                    " QLineEdit:hover, QLineEdit:focus { border: none; background: transparent; }")
_GEAR_QSS = "color: #b29ae7; background: transparent; font-size: 13px;"
_UNIT_QSS = "color: #8a8a8a; background: transparent; font-size: 11px; font-weight: bold; " + _FONT


class StatValueLabel(QLabel):
    """Shows only the value of a 'Caption: value' string (first line, caption dropped)."""

    def setText(self, text):
        if text:
            text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
            text = text.split("\n", 1)[0]
            if ":" in text:
                text = text.split(":", 1)[1].strip()
        super().setText(text or "")


class ResolutionLabel(StatValueLabel):
    """Resolution value that also routes any 'Video/Audio Bitrate' lines to sibling blocks."""

    def __init__(self):
        super().__init__()
        self.vbitrate_label = None
        self.abitrate_label = None

    def setText(self, text):
        norm = (text or "").replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
        res_line = ""
        for line in norm.split("\n"):
            s = line.strip()
            if not s:
                continue
            low = s.lower()
            if "video bitrate" in low and self.vbitrate_label is not None:
                StatValueLabel.setText(self.vbitrate_label, s)
            elif "audio bitrate" in low and self.abitrate_label is not None:
                StatValueLabel.setText(self.abitrate_label, s)
            elif not res_line:
                res_line = s
        StatValueLabel.setText(self, res_line)


class _OverlayPositioner(QObject):
    """Keeps an overlay chip glued over a combo's body (minus the drop-down arrow)."""

    def __init__(self, combo, target):
        super().__init__(combo)
        self._combo = combo
        self._target = target
        combo.installEventFilter(self)

    def reposition(self):
        c = self._combo
        w = max(0, c.width() - _ARROW_RESERVE - _BORDER)
        h = max(0, c.height() - 2 * _BORDER)
        self._target.setGeometry(_BORDER, _BORDER, w, h)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Resize, QEvent.Move, QEvent.Show):
            self.reposition()
        return False


def _drop_layout(widget):
    """Detach a widget's current layout so a new one can be set."""
    old = widget.layout()
    if old is not None:
        QWidget().setLayout(old)


def _promote_size_slider(old):
    """Swap the plain Target-Size QSlider for the rainbow GradientSlider, keeping its range,
    value and object name so the render_controller / app wiring is unaffected."""
    new = GradientSlider(Qt.Horizontal)
    new.setObjectName(old.objectName())
    new.setMinimum(old.minimum())
    new.setMaximum(old.maximum())
    new.setValue(old.value())
    new.setVisible(old.isVisible())
    old.deleteLater()
    return new


def _page_title(text):
    title = QLabel(text)
    title.setStyleSheet(_TITLE_QSS)
    return title


def _field(label, combo):
    """A labelled field cell: small caption directly above a fixed-width pill control.

    Both are left-aligned so the caption sits exactly over its combo and every combo
    lines up in uniform columns.
    """
    box = QVBoxLayout()
    box.setSpacing(4)
    box.setContentsMargins(0, 0, 0, 0)
    label.setStyleSheet(_FIELD_LABEL_QSS)
    combo.setFixedWidth(_COMBO_W)
    box.addWidget(label, alignment=Qt.AlignLeft)
    box.addWidget(combo, alignment=Qt.AlignLeft)
    return box


def _custom_field(ui, label, combo, input_attr, warn_attr, unit):
    """Like _field, but when the combo's last item ('Custom …') is selected it reveals an
    opaque chip overlaid on the combo body: [gear | edit | unit], with a warning icon to the
    right. The combo stays non-editable; we stash the edit + warn on `ui` (as input_attr /
    warn_attr) so render_controller can attach validators and read input.text().
    """
    label.setStyleSheet(_FIELD_LABEL_QSS)
    combo.setFixedWidth(_COMBO_W)

    overlay = QFrame(combo)                      # child of the combo -> paints on top of its body
    overlay.setObjectName("customOverlay")
    overlay.setAttribute(Qt.WA_StyledBackground, True)
    overlay.setStyleSheet(_OVERLAY_QSS)
    ol = QHBoxLayout(overlay)
    ol.setContentsMargins(12, 0, 8, 0)
    ol.setSpacing(6)

    gear = QLabel("⚙️")
    gear.setStyleSheet(_GEAR_QSS)
    edit = QLineEdit()
    edit.setStyleSheet(_CUSTOM_EDIT_QSS)
    unit_lbl = QLabel(unit)
    unit_lbl.setStyleSheet(_UNIT_QSS)
    ol.addWidget(gear)
    ol.addWidget(edit, 1)
    ol.addWidget(unit_lbl)

    overlay.hide()
    positioner = _OverlayPositioner(combo, overlay)
    overlay._positioner = positioner             # keep a reference alive

    warn = QLabel()
    warn.setFixedSize(16, 16)
    warn.hide()

    setattr(ui, input_attr, edit)
    setattr(ui, warn_attr, warn)

    def _sync(text):
        if "Custom" in text:
            positioner.reposition()
            overlay.show()
            overlay.raise_()
            edit.setFocus()
        else:
            overlay.hide()
            warn.hide()

    combo.currentTextChanged.connect(_sync)
    _sync(combo.currentText())

    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(combo, 0, Qt.AlignLeft)
    row.addWidget(warn, 0, Qt.AlignVCenter)
    row.addStretch()

    box = QVBoxLayout()
    box.setSpacing(4)
    box.setContentsMargins(0, 0, 0, 0)
    box.addWidget(label, alignment=Qt.AlignLeft)
    box.addLayout(row)
    return box


def _toggle_row(toggle, text):
    row = QHBoxLayout()
    row.setSpacing(10)
    row.addWidget(toggle)
    caption = QLabel(text)
    caption.setStyleSheet(_TOGGLE_LABEL_QSS)
    row.addWidget(caption)
    row.addStretch()
    return row


def _stat_block(caption, value_label):
    frame = QFrame()
    frame.setStyleSheet(_STAT_FRAME_QSS)
    box = QVBoxLayout(frame)
    box.setContentsMargins(12, 8, 12, 8)
    box.setSpacing(2)
    cap = QLabel(caption)
    cap.setStyleSheet(_STAT_CAP_QSS)
    value_label.setStyleSheet(_STAT_VAL_QSS)
    box.addWidget(cap)
    box.addWidget(value_label)
    return frame


def restyle_video_page(ui):
    """Video tab: title + a 2-column grid of fields + a sliding 'Disable Audio' toggle."""
    page = ui.tab_video

    was_muted = False
    if hasattr(ui, "check_mute_audio") and ui.check_mute_audio is not None:
        was_muted = ui.check_mute_audio.isChecked()
        ui.check_mute_audio.setParent(None)
        ui.check_mute_audio.deleteLater()

    keep = [
        ui.label_2, ui.combo_quality, ui.label_target_size, ui.size_slider,
        ui.label_5, ui.combo_fps, ui.label_4, ui.combo_bitrate,
        ui.label_14, ui.combo_codec, ui.label_6, ui.combo_encoder,
    ]
    for w in keep:
        w.setParent(None)

    ui.size_slider = _promote_size_slider(ui.size_slider)

    _drop_layout(page)

    root = QVBoxLayout(page)
    root.setContentsMargins(8, 8, 8, 8)
    root.setSpacing(12)
    root.addWidget(_page_title("Video Settings"))

    grid = QGridLayout()
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(12)
    grid.addLayout(_field(ui.label_2, ui.combo_quality), 0, 0)
    grid.addLayout(_custom_field(ui, ui.label_5, ui.combo_fps, "input_custom_fps", "warn_fps", "FPS"), 0, 1)
    ui.label_target_size.setStyleSheet(_TARGET_READOUT_QSS)
    grid.addWidget(ui.label_target_size, 1, 0, 1, 2)
    grid.addWidget(ui.size_slider, 2, 0, 1, 2)
    grid.addLayout(_custom_field(ui, ui.label_4, ui.combo_bitrate, "input_custom_vbitrate", "warn_vbitrate", "Mbps"), 3, 0)
    grid.addLayout(_field(ui.label_14, ui.combo_codec), 3, 1)
    grid.addLayout(_field(ui.label_6, ui.combo_encoder), 4, 0)
    grid.setColumnStretch(2, 1)  # empty 3rd column soaks up slack -> fields stay left, columns line up
    root.addLayout(grid)

    toggle = ToggleSwitch()
    toggle.setObjectName("check_mute_audio")
    toggle.setChecked(was_muted)
    ui.check_mute_audio = toggle
    root.addLayout(_toggle_row(toggle, "Disable Audio (Video Only)"))

    root.addStretch()


def restyle_audio_page(ui):
    """Audio tab: title + Format | Bitrate field row + a sliding 'Extract Audio Only' toggle."""
    page = ui.tab_audio

    was_audio_only = False
    if hasattr(ui, "check_audio_only") and ui.check_audio_only is not None:
        was_audio_only = ui.check_audio_only.isChecked()
        ui.check_audio_only.setParent(None)
        ui.check_audio_only.deleteLater()

    keep = [
        ui.label_audio_format, ui.combo_audio_format,
        ui.label_audio_bitrate, ui.combo_audio_bitrate,
    ]
    for w in keep:
        w.setParent(None)

    _drop_layout(page)

    root = QVBoxLayout(page)
    root.setContentsMargins(8, 8, 8, 8)
    root.setSpacing(12)
    root.addWidget(_page_title("Audio Settings"))

    grid = QGridLayout()
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(12)
    grid.addLayout(_field(ui.label_audio_format, ui.combo_audio_format), 0, 0)
    grid.addLayout(_custom_field(ui, ui.label_audio_bitrate, ui.combo_audio_bitrate, "input_custom_abitrate", "warn_abitrate", "kbps"), 0, 1)
    grid.setColumnStretch(2, 1)  # same column grid as the video page -> combos line up
    root.addLayout(grid)

    toggle = ToggleSwitch()
    toggle.setObjectName("check_audio_only")
    toggle.setChecked(was_audio_only)
    ui.check_audio_only = toggle
    root.addLayout(_toggle_row(toggle, "Disable Video (Extract Audio Only)"))

    root.addStretch()


def restyle_source_page(ui):
    """Source Info tab: title + path box + a 3-column grid of stat blocks.

    Bulletproof: removes EVERY label currently in the source tab (except the path)
    via findChildren, then builds fresh value labels that render_controller writes into.
    """
    page = ui.tab_source
    specs = [
        ("Resolution", "orig_res_label"), ("Video Bitrate", "label_vbitrate"),
        ("Audio Bitrate", "label_abitrate"), ("Duration", "label_duration"),
        ("FPS", "label_fps"), ("Size", "label_size"),
    ]

    old_texts = {}
    for _, name in specs:
        lbl = getattr(ui, name, None)
        old_texts[name] = lbl.text() if lbl is not None else ""

    src = getattr(ui, "source_label", None)

    for lbl in page.findChildren(QLabel):
        if lbl is not src:
            lbl.setParent(None)
            lbl.deleteLater()
    if src is not None:
        src.setParent(None)

    _drop_layout(page)

    for _, name in specs:
        value = ResolutionLabel() if name == "orig_res_label" else StatValueLabel()
        value.setObjectName(name)
        setattr(ui, name, value)
    ui.orig_res_label.vbitrate_label = ui.label_vbitrate
    ui.orig_res_label.abitrate_label = ui.label_abitrate

    for _, name in specs:
        if name != "orig_res_label":
            getattr(ui, name).setText(old_texts[name])
    ui.orig_res_label.setText(old_texts["orig_res_label"])

    root = QVBoxLayout(page)
    root.setContentsMargins(8, 8, 8, 8)
    root.setSpacing(10)
    root.addWidget(_page_title("Source Info"))
    if src is not None:
        src.setStyleSheet(_PATHBOX_QSS)
        root.addWidget(src)

    grid = QGridLayout()
    grid.setSpacing(8)
    for i, (caption, name) in enumerate(specs):
        grid.addWidget(_stat_block(caption, getattr(ui, name)), i // 3, i % 3)
    root.addLayout(grid)
    root.addStretch()