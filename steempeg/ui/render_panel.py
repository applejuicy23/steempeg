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
from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QGuiApplication, QIcon

from steempeg.ui.icon_assets import warning_icon
from steempeg.ui.layout_defaults import (
    SETTINGS_CONTENT_WIDTH,
    SETTINGS_PAGE_MARGIN_BOTTOM,
    SETTINGS_PAGE_MARGIN_LEFT,
    SETTINGS_PAGE_MARGIN_RIGHT,
    SETTINGS_PAGE_MARGIN_TOP,
)
from steempeg.ui.widgets.elided_label import ElidedLabel

from steempeg.ui.widgets.gradient_slider import GradientSlider
from steempeg.ui.widgets.toggle_switch import ToggleSwitch

_FONT = "font-family: 'Segoe UI', Arial, sans-serif;"
# Match Video Settings combo text (see combo_chrome.SETTINGS_COMBO_FIELD_RULES + app.py).
_FONT_COMBO = _FONT + " font-size: 13px; font-weight: bold;"
_COMBO_W = 340  # every combo is exactly this wide -> uniform, not stretched to the edge
# Two export-tab combos side-by-side must fit inside SETTINGS_CONTENT_WIDTH.
_EXPORT_COMBO_W = (SETTINGS_CONTENT_WIDTH - 16) // 2
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
                       " border-radius: 10px; padding: 9px 13px; color: #cfcfcf;"
                       " font-size: 11px; font-weight: normal; line-height: 1.35; " + _FONT + " }")

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


class SourcePathsBox(QWidget):
    """Source directories rendered as individual field-styled rows, each with its own
    copy button on the right. render_controller calls set_sources([...]) with full
    directory paths; legacy setText() resets/placeholders are still handled."""

    _CAP_QSS = "color: #8a8a8a; font-size: 11px; font-weight: bold; background: transparent; " + _FONT
    _ROW_QSS = "QFrame#srcRow { background-color: #252525; border-radius: 10px; }"
    _PATH_QSS = ("color: #b29ae7; font-size: 11px; font-weight: bold;"
                 " font-family: 'Consolas', monospace; background: transparent; border: none;")
    _MSG_QSS = ("color: #8a8a8a; font-size: 11px; font-weight: bold;"
                " background: transparent; border: none; " + _FONT)
    _COPY_QSS = ("QPushButton { background: transparent; border: none; border-radius: 6px; }"
                 " QPushButton:hover { background: rgba(255, 255, 255, 28); }"
                 " QPushButton:pressed { background: rgba(255, 255, 255, 45); }")
    _RESET_TEXTS = {"", "source:", "source: -", "source:-"}

    def __init__(self):
        super().__init__()
        self._copy_icon = None
        try:
            import os as _os
            from steempeg.infra.paths import get_resource_path

            icon_path = get_resource_path("copyfile.png")
            if _os.path.exists(icon_path):
                self._copy_icon = QIcon(icon_path)
        except Exception:
            self._copy_icon = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self._caption = QLabel("Source:")
        self._caption.setStyleSheet(self._CAP_QSS)
        root.addWidget(self._caption)

        self._rows_host = QWidget()
        self._rows_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(6)
        root.addWidget(self._rows_host)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def minimumSizeHint(self):
        sh = super().minimumSizeHint()
        min_w = self.minimumWidth()
        if min_w > 0:
            return QSize(min_w, sh.height())
        return sh

    def _clear_rows(self):
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def set_sources(self, paths):
        self._clear_rows()
        paths = [p for p in (paths or []) if p]
        if not paths:
            return
        from steempeg.infra.paths import display_path

        multi = len(paths) > 1
        for i, full in enumerate(paths):
            shown = display_path(full)
            display = f"{i + 1}.  {shown}" if multi else shown
            self._rows_layout.addWidget(self._make_path_row(display, shown))
        QTimer.singleShot(0, self._refresh_path_labels)

    def _refresh_path_labels(self) -> None:
        return

    def setText(self, text):
        """Legacy reset/placeholder entry point (lifecycle/player/controller)."""
        self._clear_rows()
        msg = (text or "").strip()
        if msg.lower() in self._RESET_TEXTS:
            return
        shown = msg
        if msg.lower().startswith("source:"):
            shown = msg.split(":", 1)[1].strip() or msg
        self._rows_layout.addWidget(self._make_message_row(shown))

    def _make_message_row(self, text):
        row = QFrame()
        row.setObjectName("srcRow")
        row.setStyleSheet(self._ROW_QSS)
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 8, 12, 8)
        lbl = QLabel(text)
        lbl.setStyleSheet(self._MSG_QSS)
        h.addWidget(lbl, 1)
        return row

    def _make_path_row(self, display_text, full_path):
        row = QFrame()
        row.setObjectName("srcRow")
        row.setStyleSheet(self._ROW_QSS)
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 6, 6, 6)
        h.setSpacing(8)

        path_field = QLineEdit(full_path)
        path_field.setReadOnly(True)
        path_field.setFrame(False)
        path_field.setCursorPosition(0)
        path_field.setStyleSheet(self._PATH_QSS)
        path_field.setMinimumWidth(0)
        path_field.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        h.addWidget(path_field, 1)

        btn = QPushButton()
        btn.setFixedSize(24, 24)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip("Copy this path")
        btn.setStyleSheet(self._COPY_QSS)
        if self._copy_icon is not None:
            btn.setIcon(self._copy_icon)
            btn.setIconSize(QSize(16, 16))
        else:
            btn.setText("📋")
        btn.clicked.connect(lambda _=False, p=full_path: QGuiApplication.clipboard().setText(p))
        h.addWidget(btn, 0, Qt.AlignVCenter)
        return row


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


class SummaryLabel(QWidget):
    """Renders render_controller's "Key: Value\\n…" render summary as a compact 2-column
    key/value grid (sized to its content, not stretched). Exposes setText() so the controller
    keeps writing to it exactly like the old QLabel did."""

    _KEY_QSS = "color: #8a8a8a; background: transparent; font-size: 12px; " + _FONT
    _VAL_QSS = "color: #ffffff; background: transparent; " + _FONT_COMBO

    def __init__(self):
        super().__init__()
        self._pairs = []
        self._plain = None
        self._cols = 2
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setVerticalSpacing(7)
        self._grid.setHorizontalSpacing(10)

    def setText(self, text):
        norm = (text or "").replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
        pairs = []
        for line in norm.split("\n"):
            s = line.strip()
            if not s:
                continue
            if ":" in s:
                k, v = s.split(":", 1)
                pairs.append((k.strip(), v.strip()))
            else:
                pairs.append(("", s))
        # plain status line (e.g. "Waiting for clip selection…") -> show as-is
        self._plain = norm.strip() if (len(pairs) <= 1 and (not pairs or pairs[0][0] == "")) else None
        self._pairs = pairs
        self._rebuild()

    def patch_field(self, key: str, value: str) -> bool:
        """Update one key/value pair without rebuilding unrelated rows."""
        key = (key or "").strip()
        if not key or self._plain is not None:
            return False
        for idx, (k, v) in enumerate(self._pairs):
            if k == key:
                if v == value:
                    return True
                self._pairs[idx] = (k, value)
                cols = self._cols
                r, c = idx // cols, idx % cols
                base = c * 3 + 1
                item = self._grid.itemAtPosition(r, base)
                if item and item.widget():
                    item.widget().setText(value)
                return True
        return False

    def _clear(self):
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _label(self, text, qss):
        lbl = QLabel(text)
        lbl.setStyleSheet(qss)
        lbl.setTextFormat(Qt.PlainText)
        return lbl

    def _rebuild(self):
        self._clear()
        for col in (1, 2, 4):
            self._grid.setColumnStretch(col, 0)
            self._grid.setColumnMinimumWidth(col, 0)

        if self._plain is not None:
            self._grid.addWidget(self._label(self._plain, self._VAL_QSS), 0, 0)
            return

        cols = self._cols
        for idx, (k, v) in enumerate(self._pairs):
            r, c = idx // cols, idx % cols
            base = c * 3  # left pair -> cols 0/1, right pair -> cols 3/4, col 2 is the gutter
            self._grid.addWidget(self._label(k, self._KEY_QSS), r, base, Qt.AlignLeft | Qt.AlignVCenter)
            self._grid.addWidget(self._label(v, self._VAL_QSS), r, base + 1, Qt.AlignLeft | Qt.AlignVCenter)

        # No column stretch -> columns hug their content so the whole grid stays compact.
        if cols == 2:
            self._grid.setColumnMinimumWidth(2, 24)  # gutter between the two pairs


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


def _settings_page_margins():
    return (
        SETTINGS_PAGE_MARGIN_LEFT,
        SETTINGS_PAGE_MARGIN_TOP,
        SETTINGS_PAGE_MARGIN_RIGHT,
        SETTINGS_PAGE_MARGIN_BOTTOM,
    )


def _page_title(text):
    title = QLabel(text)
    title.setObjectName("settingsPageTitle")
    title.setStyleSheet(_TITLE_QSS)
    return title


def _content_width_wrap(inner: QWidget) -> QWidget:
    """Clamp a block to the settings-tab content column (Source Info right edge)."""
    wrap = QWidget()
    wrap.setObjectName("settingsContentWrap")
    wrap.setMaximumWidth(SETTINGS_CONTENT_WIDTH)
    wrap.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
    lay = QVBoxLayout(wrap)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addWidget(inner)
    return wrap


def _field_export(label, combo):
    """Export tab field — narrower combo so two fit in SETTINGS_CONTENT_WIDTH."""
    box = QVBoxLayout()
    box.setSpacing(4)
    box.setContentsMargins(0, 0, 0, 0)
    label.setStyleSheet(_FIELD_LABEL_QSS)
    combo.setFixedWidth(_EXPORT_COMBO_W)
    box.addWidget(label, alignment=Qt.AlignLeft)
    box.addWidget(combo, alignment=Qt.AlignLeft)
    return box


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


def _quality_field(ui, label, combo):
    """Quality field with a contextual warning for the Original copy preset.

    Row layout matches _custom_field (combo + 8px + 16px icon slot) so the help
    icon lines up with custom-value warn icons and the combo stays full width.
    """
    box = QVBoxLayout()
    box.setSpacing(4)
    box.setContentsMargins(0, 0, 0, 0)

    label.setStyleSheet(_FIELD_LABEL_QSS)
    combo.setFixedWidth(_COMBO_W)

    help_slot = QWidget()
    help_slot.setFixedSize(16, 16)
    help_slot_layout = QHBoxLayout(help_slot)
    help_slot_layout.setContentsMargins(0, 0, 0, 0)
    help_slot_layout.setSpacing(0)

    help_btn = QPushButton(help_slot)
    help_btn.setIcon(warning_icon(16))
    help_btn.setIconSize(QSize(16, 16))
    help_btn.setFlat(True)
    help_btn.setCursor(Qt.PointingHandCursor)
    help_btn.setStyleSheet(
        "QPushButton { background: transparent; border: none; padding: 0; " + _FONT + " }"
        " QPushButton:hover { background-color: rgba(240, 192, 0, 0.12); border-radius: 3px; }"
    )
    help_btn.setToolTip(
        "<b>Original preset warning</b><br>"
        "Original uses fast stream copy / block merge without re-encoding.<br><br>"
        "If Steam DASH chunks are slightly broken, the output duration can be wrong "
        "(for example, a 3-second clip may become much longer).<br><br>"
        "If that happens, use a normal re-encode preset such as 1440p/1080p. "
        "Re-encoding usually fixes those timeline glitches."
    )
    help_btn.hide()
    help_slot_layout.addWidget(help_btn)

    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)

    def _sync_help(text):
        dismissed = bool(help_btn.property("warning_dismissed"))
        help_btn.setVisible("Original" in (text or "") and not dismissed)

    help_btn._sync_help = _sync_help
    combo.currentTextChanged.connect(_sync_help)
    _sync_help(combo.currentText())
    ui.btn_quality_original_help = help_btn

    row.addWidget(combo, 0, Qt.AlignLeft)
    row.addWidget(help_slot, 0, Qt.AlignVCenter)
    row.addStretch()

    box.addWidget(label, alignment=Qt.AlignLeft)
    box.addLayout(row)
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

    warn_slot = QWidget()
    warn_slot.setFixedSize(16, 16)
    warn_slot_layout = QHBoxLayout(warn_slot)
    warn_slot_layout.setContentsMargins(0, 0, 0, 0)
    warn_slot_layout.setSpacing(0)

    warn = QLabel(warn_slot)
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
            edit.textChanged.emit(edit.text())
        else:
            overlay.hide()
            warn.hide()

    combo.currentTextChanged.connect(_sync)
    _sync(combo.currentText())

    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(combo, 0, Qt.AlignLeft)
    row.addWidget(warn_slot, 0, Qt.AlignVCenter)
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
    value_label.setWordWrap(True)  # long values (e.g. multiple resolutions) wrap instead of widening
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

    if not hasattr(ui, "combo_encode_speed") or ui.combo_encode_speed is None:
        ui.label_encode_speed = QLabel("Encode Speed")
        ui.label_encode_speed.setObjectName("label_encode_speed")
        ui.combo_encode_speed = QComboBox()
        ui.combo_encode_speed.setObjectName("combo_encode_speed")
    else:
        ui.label_encode_speed.setParent(None)
        ui.combo_encode_speed.setParent(None)

    keep = [
        ui.label_2, ui.combo_quality, ui.label_target_size, ui.size_slider,
        ui.label_5, ui.combo_fps, ui.label_4, ui.combo_bitrate,
        ui.label_14, ui.combo_codec, ui.label_6, ui.combo_encoder,
        ui.label_encode_speed, ui.combo_encode_speed,
    ]
    for w in keep:
        w.setParent(None)

    ui.size_slider = _promote_size_slider(ui.size_slider)

    _drop_layout(page)

    root = QVBoxLayout(page)
    root.setContentsMargins(*_settings_page_margins())
    root.setSpacing(12)
    root.addWidget(_page_title("Video Settings"))

    grid = QGridLayout()
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(12)
    grid.addLayout(_quality_field(ui, ui.label_2, ui.combo_quality), 0, 0)
    grid.addLayout(_custom_field(ui, ui.label_5, ui.combo_fps, "input_custom_fps", "warn_fps", "FPS"), 0, 1)
    ui.label_target_size.setStyleSheet(_TARGET_READOUT_QSS)
    grid.addWidget(ui.label_target_size, 1, 0, 1, 2)
    grid.addWidget(ui.size_slider, 2, 0, 1, 2)
    grid.addLayout(_custom_field(ui, ui.label_4, ui.combo_bitrate, "input_custom_vbitrate", "warn_vbitrate", "Mbps"), 3, 0)
    grid.addLayout(_field(ui.label_14, ui.combo_codec), 3, 1)
    grid.addLayout(_field(ui.label_6, ui.combo_encoder), 4, 0)
    grid.addLayout(_field(ui.label_encode_speed, ui.combo_encode_speed), 4, 1)
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
    root.setContentsMargins(*_settings_page_margins())
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

    old_src = getattr(ui, "source_label", None)

    for lbl in page.findChildren(QLabel):
        lbl.setParent(None)
        lbl.deleteLater()
    if old_src is not None:
        old_src.setParent(None)
        old_src.deleteLater()

    _drop_layout(page)

    # New: each source directory becomes its own field-styled row with a copy button.
    ui.source_label = SourcePathsBox()

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
    root.setContentsMargins(*_settings_page_margins())
    root.setSpacing(10)
    root.addWidget(_page_title("Source Info"))

    # Match the stat-block grid width below (3 * 210 + 2 * 8 spacing) so the source
    # rows line up with the cards instead of sprawling to the panel edge.
    stat_grid_w = SETTINGS_CONTENT_WIDTH
    ui.source_label.setMinimumWidth(stat_grid_w)
    ui.source_label.setMaximumWidth(stat_grid_w)
    root.addWidget(ui.source_label, alignment=Qt.AlignLeft)

    grid = QGridLayout()
    grid.setSpacing(8)
    for i, (caption, name) in enumerate(specs):
        block = _stat_block(caption, getattr(ui, name))
        block.setObjectName("settingsStatBlock")
        block.setFixedWidth(210)  # uniform; density resize via apply_settings_panel_density
        grid.addWidget(block, i // 3, i % 3)
    grid.setColumnStretch(3, 1)  # extra panel width pools on the right, blocks stay put
    root.addLayout(grid)
    root.addStretch()


def restyle_export_page(ui):
    """Export tab: title + a 'Final Render Details' key/value card, then an Output Filename row
    with a 'Save as…' button, then the destination path below.

    label_detailed_summary is swapped for a SummaryLabel grid; render_controller keeps calling
    .setText() with its "Key: Value\\n…" block, so its logic is untouched.
    """
    page = ui.tab_export

    old_summary = getattr(ui, "label_detailed_summary", None)
    old_text = old_summary.text() if old_summary is not None else ""

    fname_cap = getattr(ui, "label_10", None)
    fname_input = getattr(ui, "input_filename", None)
    dest_btn = getattr(ui, "destination_button", None)
    loc_label = getattr(ui, "label_location", None)

    for w in (fname_cap, fname_input, dest_btn, loc_label):
        if w is not None:
            w.setParent(None)

    grp = getattr(ui, "group_summary", None)
    if old_summary is not None:
        old_summary.setParent(None)
        old_summary.deleteLater()
    if grp is not None:
        grp.setParent(None)
        grp.deleteLater()

    _drop_layout(page)

    summary = SummaryLabel()
    summary.setObjectName("label_detailed_summary")
    ui.label_detailed_summary = summary

    root = QVBoxLayout(page)
    root.setContentsMargins(*_settings_page_margins())
    root.setSpacing(12)
    root.addWidget(_page_title("Export Settings"))

    card = QFrame()
    card.setObjectName("summaryCard")
    card.setStyleSheet("QFrame#summaryCard { background-color: #303030; border: 1px solid #3a3a3a;"
                       " border-radius: 14px; }")
    card_box = QVBoxLayout(card)
    card_box.setContentsMargins(16, 12, 16, 14)
    card_box.setSpacing(10)
    cap = QLabel("Final Render Details")
    cap.setStyleSheet(
        "color: #b29ae7; background: transparent; font-size: 11px; font-weight: bold; " + _FONT
    )
    card_box.addWidget(cap)
    card_box.addWidget(summary)
    card.setFixedWidth(SETTINGS_CONTENT_WIDTH)
    card.setProperty("settingsContentFixed", True)
    card_row = QHBoxLayout()
    card_row.setContentsMargins(0, 0, 0, 0)
    card_row.addWidget(card)
    card_row.addStretch()
    root.addLayout(card_row)

    summary.setText(old_text)

    # Output format: preset + container (codecs live on Video / Audio tabs)
    preset_combo = getattr(ui, "combo_output_preset", None)
    container_combo = getattr(ui, "combo_container", None)
    if preset_combo is None:
        preset_combo = QComboBox()
        preset_combo.setObjectName("combo_output_preset")
        ui.combo_output_preset = preset_combo
    if container_combo is None:
        container_combo = QComboBox()
        container_combo.setObjectName("combo_container")
        ui.combo_container = container_combo

    fmt_host = QWidget()
    fmt_grid = QGridLayout(fmt_host)
    fmt_grid.setContentsMargins(0, 0, 0, 0)
    fmt_grid.setHorizontalSpacing(16)
    fmt_grid.setVerticalSpacing(12)
    fmt_grid.addLayout(_field_export(QLabel("Output preset"), preset_combo), 0, 0)
    fmt_grid.addLayout(_field_export(QLabel("Container"), container_combo), 0, 1)
    root.addWidget(_content_width_wrap(fmt_host))

    fname_block = QWidget()
    fname_block_lay = QVBoxLayout(fname_block)
    fname_block_lay.setContentsMargins(0, 0, 0, 0)
    fname_block_lay.setSpacing(4)

    if fname_cap is not None:
        fname_cap.setText("Output Filename")
        fname_cap.setStyleSheet(_FIELD_LABEL_QSS)
        fname_block_lay.addWidget(fname_cap)

    name_row = QHBoxLayout()
    name_row.setSpacing(8)
    if fname_input is not None:
        fname_input.setMinimumWidth(0)
        fname_input.setMaximumWidth(16777215)
        name_row.addWidget(fname_input, 1)
    if dest_btn is not None:
        dest_btn.setText("Save as…")
        name_row.addWidget(dest_btn, 0)
    fname_block_lay.addLayout(name_row)
    root.addWidget(_content_width_wrap(fname_block))

    if loc_label is not None:
        path_row = QFrame()
        path_row.setObjectName("outputPathRow")
        path_row.setStyleSheet(
            "QFrame#outputPathRow { background-color: #252525; border-radius: 10px; }"
        )
        path_row.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        path_row.setMaximumWidth(SETTINGS_CONTENT_WIDTH)
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(12, 8, 8, 8)
        path_layout.setSpacing(6)
        if not isinstance(loc_label, ElidedLabel):
            smart_label = ElidedLabel()
            smart_label.setStyleSheet(loc_label.styleSheet())
            smart_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            loc_label.deleteLater()
            loc_label = smart_label
            ui.label_location = smart_label
        loc_label.setStyleSheet(
            "background: transparent; border: none; color: #b29ae7; font-size: 11px;"
            " font-weight: bold; font-family: 'Consolas', monospace;"
        )
        loc_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        path_layout.addWidget(loc_label, 1)
        ui.output_path_row = path_row
        root.addWidget(path_row)

    root.addStretch()


class _WheelToScrollFilter(QObject):
    """Forward wheel events from locked controls to the settings scroll area."""

    def __init__(self, scroll_area: QScrollArea):
        super().__init__()
        self._scroll = scroll_area

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel and self._scroll is not None:
            vp = self._scroll.viewport()
            if vp is not None:
                QGuiApplication.sendEvent(vp, event)
                return True
        return False


def _is_lockable_widget(widget: QWidget) -> bool:
    if isinstance(widget, QLabel):
        return False
    if isinstance(widget, (QComboBox, QLineEdit, QSlider, QAbstractSpinBox)):
        return True
    return isinstance(widget, QAbstractButton)


def _iter_settings_pages(app):
    ui = getattr(app, 'ui', None)
    if ui is None or not hasattr(ui, 'settings_tabs'):
        return
    tabs = ui.settings_tabs
    for i in range(tabs.count()):
        page = tabs.widget(i)
        if page is not None:
            yield page


def set_settings_panel_locked(app, locked: bool):
    """Freeze render settings controls while keeping sidebar nav and scrolling usable."""
    if locked:
        disabled = []
        seen = set()
        scroll = getattr(app, 'right_scroll', None)
        if scroll is not None and not hasattr(app, '_render_wheel_filter'):
            app._render_wheel_filter = _WheelToScrollFilter(scroll)
        wheel_filter = getattr(app, '_render_wheel_filter', None)

        def lock_widget(widget):
            if widget is None or id(widget) in seen:
                return
            seen.add(id(widget))
            if not widget.isEnabled():
                return
            widget.setEnabled(False)
            disabled.append(widget)
            if wheel_filter is not None:
                widget.installEventFilter(wheel_filter)

        for page in _iter_settings_pages(app):
            for child in page.findChildren(QWidget):
                if _is_lockable_widget(child):
                    lock_widget(child)

        app._render_locked_widgets = disabled
    else:
        wheel_filter = getattr(app, '_render_wheel_filter', None)
        for widget in getattr(app, '_render_locked_widgets', []):
            if wheel_filter is not None:
                widget.removeEventFilter(wheel_filter)
            try:
                widget.setEnabled(True)
            except RuntimeError:
                pass
        app._render_locked_widgets = []

    for btn in getattr(app, 'neo_nav_buttons', []):
        btn.setEnabled(True)
    if hasattr(app, 'right_scroll'):
        app.right_scroll.setEnabled(True)
    if hasattr(app, 'neo_wrapper'):
        app.neo_wrapper.setEnabled(True)
_EXPORT_COMBO_NAMES = frozenset({"combo_output_preset", "combo_container"})


def apply_settings_panel_density(ui, dense) -> None:
    """Resize Source/Video/Audio/Export chrome for Deck-class windows."""
    content_w = int(dense.settings_content_w)
    combo_w = int(dense.settings_combo_w)
    stat_w = int(dense.settings_stat_w)
    export_w = max(120, (content_w - 16) // 2)
    title_font = int(dense.settings_title_font)
    margins = dense.settings_page_margin

    tabs = getattr(ui, "settings_tabs", None)
    root = tabs if tabs is not None else ui

    for wrap in root.findChildren(QWidget, "settingsContentWrap"):
        wrap.setMaximumWidth(content_w)

    for block in root.findChildren(QFrame, "settingsStatBlock"):
        block.setFixedWidth(stat_w)

    for card in root.findChildren(QFrame, "summaryCard"):
        card.setFixedWidth(content_w)

    for path_row in root.findChildren(QFrame, "outputPathRow"):
        path_row.setMaximumWidth(content_w)

    src = getattr(ui, "source_label", None)
    if src is not None:
        src.setMinimumWidth(content_w)
        src.setMaximumWidth(content_w)

    for title in root.findChildren(QLabel, "settingsPageTitle"):
        title.setStyleSheet(
            f"color: #ffffff; font-size: {title_font}px; font-weight: bold; "
            f"background: transparent; {_FONT}"
        )

    for combo in root.findChildren(QComboBox):
        name = combo.objectName() or ""
        if name in _EXPORT_COMBO_NAMES:
            combo.setFixedWidth(export_w)
        elif combo.minimumWidth() > 0 or combo.maximumWidth() < 16777215:
            combo.setFixedWidth(combo_w)

    for page_attr in ("tab_source", "tab_video", "tab_audio", "tab_export"):
        page = getattr(ui, page_attr, None)
        if page is None:
            continue
        lay = page.layout()
        if lay is not None:
            lay.setContentsMargins(*margins)
            lay.setSpacing(6 if dense.compact else 10)

