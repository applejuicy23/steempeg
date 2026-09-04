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
from __future__ import annotations

from steempeg.ui import design_tokens as tok
import re

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QFont, QGuiApplication, QIcon

from steempeg.ui.icon_assets import arrow_icon, warning_icon
from steempeg.ui import ui_theme as ut
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

def _font_css() -> str:
    return "font-family: " + tok.FONT_APP + ";"
# Match Video Settings combo text (see combo_chrome.SETTINGS_COMBO_FIELD_RULES + app.py).
_FONT_COMBO = _font_css() + " font-size: 13px; font-weight: bold;"
# Video/Audio: two combos + warn slots must fit inside SETTINGS_CONTENT_WIDTH (Source Info).
_GRID_H = 16
_WARN_GAP = 8
_WARN_SLOT = 16
_WARN_RESERVE = _WARN_GAP + _WARN_SLOT  # 24 — spacing + icon column after each combo
_COMBO_W = (SETTINGS_CONTENT_WIDTH - _GRID_H - 2 * _WARN_RESERVE) // 2  # 291
# Two export-tab combos side-by-side (no warn slots) must fit inside SETTINGS_CONTENT_WIDTH.
_EXPORT_COMBO_W = (SETTINGS_CONTENT_WIDTH - _GRID_H) // 2
_FIELD_LABEL_QSS = "color: #8a8a8a; font-size: 13px; font-weight: bold; background: transparent; " + _font_css()
_TOGGLE_LABEL_QSS = "color: #cccccc; font-size: 12px; font-weight: bold; background: transparent; " + _font_css()
_TITLE_QSS = "color: #ffffff; font-size: 15px; font-weight: bold; background: transparent; " + _font_css()
_PATHBOX_QSS = ("QLabel { background-color: #353535; border-radius: 10px; padding: 8px 12px;"
                " color: #b29ae7; font-size: 11px; font-weight: bold; font-family: 'Consolas', monospace; }")
_STAT_CAP_QSS = "color: #8a8a8a; font-size: 13px; font-weight: bold; background: transparent; border: none; " + _font_css()
_STAT_VAL_QSS = "color: #ffffff; font-size: 15px; font-weight: bold; background: transparent; border: none; " + _font_css()
_STAT_FRAME_QSS = "QFrame { background-color: #303030; border: 1px solid #3a3a3a; border-radius: 12px; }"

# The overlay chip blends into the combo body and leaves the drop-down arrow uncovered.
# (Combo QSS: 2px border, 30px drop-down cell + its 2px left border -> reserve 32px on the right.)
_ARROW_RESERVE = 32
_BORDER = 2


def _stat_frame_qss() -> str:
    from steempeg.ui import ui_theme as ut

    return ut.render_settings_plate_stylesheet(radius=12)


def _target_readout_qss() -> str:
    from steempeg.ui import ui_theme as ut

    return ut.render_settings_target_readout_stylesheet()


def _overlay_qss() -> str:
    from steempeg.ui import ui_theme as ut

    return ut.render_settings_combo_overlay_stylesheet()


def _source_row_qss() -> str:
    from steempeg.ui import ui_theme as ut

    return ut.render_settings_source_row_stylesheet()


def _summary_card_qss() -> str:
    from steempeg.ui import ui_theme as ut

    return ut.render_settings_plate_stylesheet(radius=14, object_name="summaryCard")
_CUSTOM_EDIT_QSS = ("QLineEdit { background: transparent; border: none; color: #ffffff;"
                    " font-size: 12px; font-weight: bold; " + _font_css() + " }"
                    " QLineEdit:hover, QLineEdit:focus { border: none; background: transparent; }")
_GEAR_QSS = "color: #b29ae7; background: transparent; font-size: 13px;"
_UNIT_QSS = "color: #8a8a8a; background: transparent; font-size: 11px; font-weight: bold; " + _font_css()


class SourcePathsBox(QWidget):
    """Source directories rendered as individual field-styled rows, each with its own
    copy button on the right. render_controller calls set_sources([...]) with full
    directory paths; legacy setText() resets/placeholders are still handled."""

    _CAP_QSS = "color: #8a8a8a; font-size: 11px; font-weight: bold; background: transparent; " + _font_css()
    _ROW_QSS = "QFrame#srcRow { background-color: #252525; border-radius: 10px; }"
    _PATH_QSS = ("color: #b29ae7; font-size: 11px; font-weight: bold;"
                 " font-family: 'Consolas', monospace; background: transparent; border: none;")
    _MSG_QSS = ("color: #8a8a8a; font-size: 11px; font-weight: bold;"
                " background: transparent; border: none; " + _font_css())
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
        row.setStyleSheet(_source_row_qss())
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 8, 12, 8)
        lbl = QLabel(text)
        lbl.setStyleSheet(self._MSG_QSS)
        h.addWidget(lbl, 1)
        return row

    def _make_path_row(self, display_text, full_path):
        row = QFrame()
        row.setObjectName("srcRow")
        row.setStyleSheet(_source_row_qss())
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 6, 6, 6)
        h.setSpacing(8)

        path_field = QLineEdit(full_path)
        path_field.setReadOnly(True)
        path_field.setFrame(False)
        path_field.setCursorPosition(0)
        path_field.setStyleSheet(ut.render_settings_source_path_field_stylesheet())
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

    # Match post-density comfort sizes (settings_title_font 15 → keys 13 / values 15).
    # Hardcoding the pre-density 12px made first paint look wrong until a window resize
    # re-ran apply_settings_panel_density — and every setText/_rebuild wiped that fix.
    _KEY_QSS = "color: #8a8a8a; background: transparent; font-size: 13px; " + _font_css()
    _VAL_QSS = (
        "color: #ffffff; background: transparent; font-size: 15px; font-weight: bold; "
        + _font_css()
    )

    def __init__(self):
        super().__init__()
        self._pairs = []
        self._plain = None
        self._cols = 2
        self._key_qss = self._KEY_QSS
        self._val_qss = self._VAL_QSS
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setVerticalSpacing(7)
        self._grid.setHorizontalSpacing(10)

    def apply_density(self, dense) -> None:
        """Keep key/value faces in sync with settings density across rebuilds."""
        title = int(getattr(dense, "settings_title_font", 15) or 15)
        key_px = max(9, title - 2)
        val_px = max(10, title)
        self._key_qss = (
            f"color: #8a8a8a; background: transparent; font-size: {key_px}px; {_font_css()}"
        )
        self._val_qss = (
            f"color: #ffffff; background: transparent; font-size: {val_px}px; "
            f"font-weight: bold; {_font_css()}"
        )
        if self._plain is not None or self._pairs:
            self._rebuild()

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
        # Hide + reparent immediately. deleteLater alone leaves the old
        # "Waiting for clip selection…" label painted over the new grid until
        # the event loop runs (common when switching Queue cards in portable).
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def _label(self, text, qss, *, elide: bool = False):
        if elide:
            lbl = ElidedLabel(text)
            lbl.setMinimumWidth(0)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        else:
            lbl = QLabel(text)
            lbl.setTextFormat(Qt.PlainText)
        lbl.setStyleSheet(qss)
        return lbl

    def _rebuild(self):
        self._clear()
        for col in (1, 2, 4):
            self._grid.setColumnStretch(col, 0)
            self._grid.setColumnMinimumWidth(col, 0)

        if self._plain is not None:
            self._grid.addWidget(self._label(self._plain, self._val_qss), 0, 0)
            return

        cols = self._cols
        for idx, (k, v) in enumerate(self._pairs):
            r, c = idx // cols, idx % cols
            base = c * 3  # left pair -> cols 0/1, right pair -> cols 3/4, col 2 is the gutter
            self._grid.addWidget(
                self._label(k, self._key_qss), r, base, Qt.AlignLeft | Qt.AlignVCenter
            )
            # No AlignLeft — that sizes the cell to sizeHint (0 for ElidedLabel)
            # and blanks every value. Fill the cell so stretch width elides properly.
            self._grid.addWidget(self._label(v, self._val_qss, elide=True), r, base + 1)

        # Value columns share width and elide (Est. File Size was clipped hard).
        if cols == 2:
            self._grid.setColumnMinimumWidth(2, 24)  # gutter between the two pairs
            self._grid.setColumnStretch(1, 1)
            self._grid.setColumnStretch(4, 1)


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


def _page_title_icon_label(icon_index: int, size: int = 16) -> QLabel:
    """Monochrome neo glyph beside a content page title (colorized assets later)."""
    from steempeg.ui.icon_assets import neo_page_title_icon

    icon_lbl = QLabel()
    icon_lbl.setObjectName("settingsPageTitleIcon")
    icon_lbl.setProperty("neo_icon_index", int(icon_index))
    icon_lbl.setFixedSize(size, size)
    icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icon_lbl.setStyleSheet("background: transparent; border: none;")
    pix = neo_page_title_icon(icon_index, size).pixmap(size, size)
    if not pix.isNull():
        icon_lbl.setPixmap(pix)
    return icon_lbl


def _page_title_row(text: str, icon_index: int, *, icon_size: int = 16) -> QWidget:
    """Content panel header: white glyph + bold title (also on neo sidebar tabs)."""
    row = QWidget()
    row.setObjectName("settingsPageTitleRow")
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    lay.addWidget(_page_title_icon_label(icon_index, icon_size), 0, Qt.AlignmentFlag.AlignVCenter)
    lay.addWidget(_page_title(text), 0, Qt.AlignmentFlag.AlignVCenter)
    lay.addStretch(1)
    return row


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


def _icon_slot(side_widget: QWidget | None = None) -> QWidget:
    """Fixed 16×16 column reserved for help / validation icons (may be empty)."""
    slot = QWidget()
    slot.setFixedSize(_WARN_SLOT, _WARN_SLOT)
    lay = QHBoxLayout(slot)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    if side_widget is not None:
        lay.addWidget(side_widget)
    return slot


def _combo_row_with_slot(combo, side_widget: QWidget | None = None) -> QHBoxLayout:
    """Combo + reserved warn/help slot so Video/Audio columns share one grid."""
    combo.setFixedWidth(_COMBO_W)
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(_WARN_GAP)
    row.addWidget(combo, 0, Qt.AlignLeft)
    row.addWidget(_icon_slot(side_widget), 0, Qt.AlignVCenter)
    row.addStretch()
    return row


def _field(label, combo):
    """A labelled field cell: caption above a fixed-width combo + empty icon slot.

    The empty slot keeps Codec / Encoder / Audio Format aligned with Quality / FPS
    rows that show a warning triangle.
    """
    box = QVBoxLayout()
    box.setSpacing(4)
    box.setContentsMargins(0, 0, 0, 0)
    label.setStyleSheet(_FIELD_LABEL_QSS)
    box.addWidget(label, alignment=Qt.AlignLeft)
    box.addLayout(_combo_row_with_slot(combo))
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

    help_btn = QPushButton()
    help_btn.setIcon(warning_icon(16))
    help_btn.setIconSize(QSize(16, 16))
    help_btn.setFlat(True)
    help_btn.setCursor(Qt.PointingHandCursor)
    help_btn.setStyleSheet(
        "QPushButton { background: transparent; border: none; padding: 0; " + _font_css() + " }"
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

    def _sync_help(text):
        dismissed = bool(help_btn.property("warning_dismissed"))
        help_btn.setVisible("Original" in (text or "") and not dismissed)

    help_btn._sync_help = _sync_help
    combo.currentTextChanged.connect(_sync_help)
    _sync_help(combo.currentText())
    ui.btn_quality_original_help = help_btn

    box.addWidget(label, alignment=Qt.AlignLeft)
    box.addLayout(_combo_row_with_slot(combo, help_btn))
    return box


def _custom_field(ui, label, combo, input_attr, warn_attr, unit):
    """Like _field, but when the combo's last item ('Custom …') is selected it reveals an
    opaque chip overlaid on the combo body: [gear | edit | unit], with a warning icon to the
    right. The combo stays non-editable; we stash the edit + warn on `ui` (as input_attr /
    warn_attr) so render_controller can attach validators and read input.text().
    """
    label.setStyleSheet(_FIELD_LABEL_QSS)

    overlay = QFrame(combo)                      # child of the combo -> paints on top of its body
    overlay.setObjectName("customOverlay")
    overlay.setAttribute(Qt.WA_StyledBackground, True)
    overlay.setStyleSheet(_overlay_qss())
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
    warn.setFixedSize(_WARN_SLOT, _WARN_SLOT)
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

    box = QVBoxLayout()
    box.setSpacing(4)
    box.setContentsMargins(0, 0, 0, 0)
    box.addWidget(label, alignment=Qt.AlignLeft)
    box.addLayout(_combo_row_with_slot(combo, warn))
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
    frame.setStyleSheet(_stat_frame_qss())
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
    root.addWidget(_page_title_row("Video Settings", 1))

    grid = QGridLayout()
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(12)
    grid.addLayout(_quality_field(ui, ui.label_2, ui.combo_quality), 0, 0)
    grid.addLayout(_custom_field(ui, ui.label_5, ui.combo_fps, "input_custom_fps", "warn_fps", "FPS"), 0, 1)
    ui.label_target_size.setStyleSheet(_target_readout_qss())
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
    root.addWidget(_page_title_row("Audio Settings", 2))

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
    root.addWidget(_page_title_row("Source Info", 0))

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
    root.addWidget(_page_title_row("Export Settings", 3))

    card = QFrame()
    card.setObjectName("summaryCard")
    card.setStyleSheet(_summary_card_qss())
    card_box = QVBoxLayout(card)
    card_box.setContentsMargins(16, 12, 16, 14)
    card_box.setSpacing(10)
    cap = QLabel("Final Render Details")
    cap.setStyleSheet(
        "color: #b29ae7; background: transparent; font-size: 11px; font-weight: bold; " + _font_css()
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
        path_row.setStyleSheet(ut.render_settings_output_path_row_stylesheet())
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
        loc_label.setStyleSheet(ut.render_settings_output_path_label_stylesheet())
        loc_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        path_layout.addWidget(loc_label, 1)
        ui.output_path_row = path_row
        path_row.hide()  # only with a real clip / output path
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


def apply_render_panel_theme_chrome(ui) -> None:
    """Re-tint Source Info plates, Export summary card, and custom combo overlays."""
    tabs = getattr(ui, "settings_tabs", None)
    root = tabs if tabs is not None else ui

    stat_qss = _stat_frame_qss()
    for block in root.findChildren(QFrame, "settingsStatBlock"):
        block.setStyleSheet(stat_qss)

    card_qss = _summary_card_qss()
    for card in root.findChildren(QFrame, "summaryCard"):
        card.setStyleSheet(card_qss)

    row_qss = _source_row_qss()
    for row in root.findChildren(QFrame, "srcRow"):
        row.setStyleSheet(row_qss)

    path_row_qss = ut.render_settings_output_path_row_stylesheet()
    path_label_qss = ut.render_settings_output_path_label_stylesheet()
    for path_row in root.findChildren(QFrame, "outputPathRow"):
        path_row.setStyleSheet(path_row_qss)
    loc = getattr(ui, "label_location", None)
    if loc is not None:
        loc.setStyleSheet(path_label_qss)

    # Source path read-only fields inside srcRow widgets.
    path_field_qss = ut.render_settings_source_path_field_stylesheet()
    for field in root.findChildren(QLineEdit):
        parent_row = field.parent()
        if parent_row is not None and parent_row.objectName() == "srcRow":
            field.setStyleSheet(path_field_qss)

    overlay_qss = _overlay_qss()
    for overlay in root.findChildren(QFrame, "customOverlay"):
        overlay.setStyleSheet(overlay_qss)

    target = getattr(ui, "label_target_size", None)
    if target is not None:
        target.setStyleSheet(_target_readout_qss())

    apply_presets_tab_theme_chrome(ui)
    _retint_render_settings_combos(ui)


def _retint_render_settings_combos(ui) -> None:
    """Re-apply Video/Audio/Export combo QSS for the active UI theme.

    Density apply memoizes on size only, and floating Render Settings theme
    chrome used to skip density entirely — Default ``#383838`` faces stuck
    after switching to TrueDark / OLED.
    """
    from steempeg.ui.ui_density import COMFORT
    from steempeg.ui.widgets.combo_chrome import (
        apply_dark_combo_popup,
        settings_panel_stylesheet,
    )

    dense = getattr(ui, "_settings_panel_dense", None) or COMFORT
    field_font = int(dense.footer_font)
    tabs = getattr(ui, "settings_tabs", None)
    root = tabs if tabs is not None else ui
    combo_qss = settings_panel_stylesheet(
        f"QComboBox {{ font-family: {tok.FONT_APP};"
        f" font-size: {field_font}px; font-weight: bold; }}",
        dense=dense,
    )
    for combo in root.findChildren(QComboBox):
        combo.setStyleSheet(combo_qss)
        apply_dark_combo_popup(combo, dense=dense)

    border = 1 if dense.compact else 2
    pad_v = 7 if dense.scale >= 0.85 else 3
    line_h = max(int(dense.combo_min_h), field_font + pad_v * 2 + border * 2 + 2)
    btn_r = max(8, int(dense.footer_radius) - 4) if dense.compact else 12
    ph = 12 if dense.scale >= 0.85 else 8
    fname = getattr(ui, "input_filename", None)
    if fname is not None:
        fname.setStyleSheet(
            ut.settings_density_line_edit_stylesheet(
                border=border, btn_r=btn_r, field_font=field_font, ph=ph
            )
        )
    dest = getattr(ui, "destination_button", None)
    if dest is not None:
        dest.setStyleSheet(
            ut.settings_density_push_button_stylesheet(
                border=border, btn_r=btn_r, field_font=field_font, ph=ph
            )
        )
        dest.setFixedHeight(line_h)


def apply_presets_tab_theme_chrome(ui) -> None:
    """Re-tint Presets tab inputs, list plate, and row Apply chrome."""
    name = getattr(ui, "preset_name_edit", None)
    if name is not None:
        name.setStyleSheet(ut.presets_line_edit_stylesheet())
    search = getattr(ui, "preset_search_edit", None)
    if search is not None:
        search.setStyleSheet(ut.presets_line_edit_stylesheet(compact=True))
    lst = getattr(ui, "preset_list", None)
    if lst is not None:
        lst.setStyleSheet(ut.presets_list_widget_stylesheet())


def apply_settings_panel_density(ui, dense) -> None:
    """Resize Source/Video/Audio/Export chrome for Deck-class windows."""
    content_w = int(dense.settings_content_w)
    combo_w = int(dense.settings_combo_w)
    stat_w = int(dense.settings_stat_w)
    export_w = max(120, (content_w - 16) // 2)
    title_font = int(dense.settings_title_font)
    margins = dense.settings_page_margin
    label_font = max(9, title_font - 2)
    value_font = max(10, title_font)
    # Same face as RefreshButton: Segoe UI bold + footer_font.
    field_font = int(dense.footer_font)
    memo_key = (
        content_w,
        combo_w,
        stat_w,
        export_w,
        title_font,
        field_font,
        margins,
        bool(getattr(dense, "compact", False)),
        float(getattr(dense, "scale", 1.0) or 1.0),
        int(getattr(dense, "neo_nav_icon", 16) or 16),
        int(getattr(dense, "combo_min_h", 0) or 0),
        int(getattr(dense, "footer_radius", 0) or 0),
        # Theme tokens feed combo/line-edit QSS — must invalidate on TrueDark switch.
        ut.get_ui_theme(),
    )
    if getattr(ui, "_settings_panel_density_key", None) == memo_key:
        return
    ui._settings_panel_density_key = memo_key
    ui._settings_panel_dense = dense

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
            f"background: transparent; {_font_css()}"
        )

    from steempeg.ui.icon_assets import neo_page_title_icon

    icon_sz = max(10, int(getattr(dense, "neo_nav_icon", 16) or 16))
    for icon_lbl in root.findChildren(QLabel, "settingsPageTitleIcon"):
        idx = icon_lbl.property("neo_icon_index")
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            continue
        icon_lbl.setFixedSize(icon_sz, icon_sz)
        pix = neo_page_title_icon(idx, icon_sz).pixmap(icon_sz, icon_sz)
        if not pix.isNull():
            icon_lbl.setPixmap(pix)

    summary = getattr(ui, "label_detailed_summary", None)
    if summary is not None and hasattr(summary, "apply_density"):
        summary.apply_density(dense)

    # Field / toggle / caption labels that used fixed comfort sizes.
    for label in root.findChildren(QLabel):
        name = label.objectName() or ""
        if name == "settingsPageTitle":
            continue
        ss = label.styleSheet() or ""
        if "font-size:" not in ss:
            continue
        # Keep monospace path chips / purple accents, just retarget size.
        if "Consolas" in ss or "monospace" in ss.lower():
            new_size = label_font
        elif "#ffffff" in ss and "font-weight: bold" in ss:
            new_size = value_font
        else:
            new_size = label_font
        label.setStyleSheet(
            re.sub(r"font-size:\s*\d+px", f"font-size: {new_size}px", ss, count=1)
        )

    for combo in root.findChildren(QComboBox):
        name = combo.objectName() or ""
        if name in _EXPORT_COMBO_NAMES:
            combo.setFixedWidth(export_w)
        elif combo.minimumWidth() > 0 or combo.maximumWidth() < 16777215:
            combo.setFixedWidth(combo_w)

    from steempeg.ui.widgets.combo_chrome import (
        apply_dark_combo_popup,
        settings_panel_stylesheet,
    )

    combo_qss = settings_panel_stylesheet(
        f"QComboBox {{ font-family: {tok.FONT_APP};"
        f" font-size: {field_font}px; font-weight: bold; }}",
        dense=dense,
    )
    for combo in root.findChildren(QComboBox):
        combo.setStyleSheet(combo_qss)
        apply_dark_combo_popup(combo, dense=dense)
        fnt = combo.font()
        fnt = tok.pin_ui_font(fnt)
        fnt.setBold(True)
        fnt.setPixelSize(field_font)
        combo.setFont(fnt)

    # combo_min_h is the inner chrome target for QComboBox. QLineEdit / Save-as also
    # carry QSS padding + borders, so locking them to combo_min_h alone clips glyphs
    # (half-cut filename, crushed "Save as…").
    border = 1 if dense.compact else 2
    pad_v = 7 if dense.scale >= 0.85 else 3
    line_h = max(int(dense.combo_min_h), field_font + pad_v * 2 + border * 2 + 2)
    btn_r = max(8, int(dense.footer_radius) - 4) if dense.compact else 12
    ph = 12 if dense.scale >= 0.85 else 8
    fname = getattr(ui, "input_filename", None)
    if fname is not None:
        # Same trick as Save as…: vertical centering from fixed height only.
        # QSS padding-top/bottom + setFixedHeight pushes glyphs onto the floor
        # (underscores / descenders clipped).
        fname.setStyleSheet(
            ut.settings_density_line_edit_stylesheet(
                border=border, btn_r=btn_r, field_font=field_font, ph=ph
            )
        )
        fname.setFixedHeight(line_h)
        fname.setTextMargins(0, 0, 0, 0)
        fnt = fname.font()
        fnt = tok.pin_ui_font(fnt)
        fnt.setBold(True)
        fnt.setPixelSize(field_font)
        fname.setFont(fnt)

    dest = getattr(ui, "destination_button", None)
    if dest is not None:
        dest.setFixedHeight(line_h)
        # Horizontal pad only — vertical centering comes from fixed height.
        # Avoid min-height + vertical padding fighting setFixedHeight (crushed label).
        dest.setStyleSheet(
            ut.settings_density_push_button_stylesheet(
                border=border, btn_r=btn_r, field_font=field_font, ph=ph
            )
        )
        fnt = dest.font()
        fnt = tok.pin_ui_font(fnt)
        fnt.setBold(True)
        fnt.setPixelSize(field_font)
        dest.setFont(fnt)

    # Preset create chrome (Save as new). Row actions live on each list item.
    _preset_faces = (
        ("btn_preset_save", "#4a3d66", "#f0ecff", "#6b5a8e", "#5a4d76", "#b29ae7", "#3a324a"),
    )
    for attr, bg, fg, brd, hover_bg, hover_brd, pressed_bg in _preset_faces:
        btn = getattr(ui, attr, None)
        if btn is None:
            continue
        btn.setFixedHeight(line_h)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {bg}; color: {fg};"
            f" border: {border}px solid {brd}; border-radius: {btn_r}px;"
            f" font-family: {tok.FONT_APP};"
            f" font-weight: bold; font-size: {field_font}px; padding: 0px {ph}px; }}"
            f" QPushButton:hover {{ background-color: {hover_bg}; border: {border}px solid {hover_brd}; }}"
            f" QPushButton:pressed {{ background-color: {pressed_bg}; border: {border}px solid {hover_brd}; }}"
        )
        fnt = btn.font()
        fnt = tok.pin_ui_font(fnt)
        fnt.setBold(True)
        fnt.setPixelSize(field_font)
        btn.setFont(fnt)

    for path_row in root.findChildren(QFrame, "outputPathRow"):
        lay = path_row.layout()
        if lay is not None:
            m = 6 if dense.compact else 12
            v = 4 if dense.compact else 8
            lay.setContentsMargins(m, v, v, v)

    for page_attr in ("tab_source", "tab_video", "tab_audio", "tab_export", "tab_presets"):
        page = getattr(ui, page_attr, None)
        if page is None:
            continue
        lay = page.layout()
        if lay is not None:
            gap = int(round(4 + (10 - 4) * getattr(dense, "scale", 0.0 if dense.compact else 1.0)))
            lay.setContentsMargins(*margins)
            lay.setSpacing(gap)


def ensure_presets_tab(ui) -> QWidget:
    """Add the Presets page to ``settings_tabs`` if missing (before neo nav is built)."""
    existing = getattr(ui, "tab_presets", None)
    if existing is not None:
        return existing
    tabs = getattr(ui, "settings_tabs", None)
    if tabs is None:
        raise RuntimeError("settings_tabs missing")
    page = QWidget()
    page.setObjectName("tab_presets")
    ui.tab_presets = page
    tabs.addTab(page, "Presets")
    return page


class PresetListRow(QWidget):
    """Saved-preset row: ★ pin, expandable recipe, Apply ▾ split (Refresh chrome)."""

    _ICON_BTN = (
        "QPushButton {"
        " background: transparent; color: #c8c8c8; border: none; border-radius: 6px;"
        f" font-weight: bold; font-size: 13px; padding: 0px; {_font_css()}"
        "}"
        " QPushButton:hover { background-color: rgba(255,255,255,0.08); color: #ffffff; }"
        " QPushButton:pressed { background-color: rgba(255,255,255,0.14); }"
    )
    # Apply ▾ split chrome resolved in __init__ from active theme tokens.
    _NAME_QSS = (
        f"QLabel {{ color: #f0f0f0; background: transparent; font-size: 13px;"
        f" font-weight: bold; {_font_css()} }}"
    )
    _DETAIL_QSS = (
        f"QLabel {{ color: #b0b0b0; background: transparent; font-size: 11px;"
        f" {_font_css()} }}"
    )

    def __init__(
        self,
        name: str,
        *,
        summary: str,
        is_favourite: bool,
        expanded: bool,
        on_select,
        on_toggle_fav,
        on_toggle_expand,
        on_apply,
        on_update,
        on_rename,
        on_duplicate,
        on_delete,
        parent=None,
    ):
        super().__init__(parent)
        self._name = name
        self._expanded = bool(expanded)
        self._on_select = on_select
        self._on_toggle_expand = on_toggle_expand
        self.setObjectName("PresetListRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("QWidget#PresetListRow { background: transparent; }")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(2)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)

        self._chevron = QPushButton("▾" if self._expanded else "▸")
        self._chevron.setFixedSize(22, 26)
        self._chevron.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chevron.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._chevron.setStyleSheet(self._ICON_BTN)
        self._chevron.setToolTip("Show or hide what's inside")
        self._chevron.clicked.connect(lambda *_: self._emit_toggle_expand())
        header.addWidget(self._chevron, 0, Qt.AlignmentFlag.AlignVCenter)

        self._star = QPushButton("★" if is_favourite else "☆")
        self._star.setFixedSize(26, 26)
        self._star.setCursor(Qt.CursorShape.PointingHandCursor)
        self._star.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._star.setStyleSheet(
            self._ICON_BTN
            + (
                " QPushButton { color: #b29ae7; }"
                if is_favourite
                else " QPushButton { color: #888888; }"
            )
        )
        self._star.setToolTip(
            "Unpin favourite" if is_favourite else "Pin favourite (up to 5)"
        )
        self._star.clicked.connect(lambda *_: on_toggle_fav(name))
        header.addWidget(self._star, 0, Qt.AlignmentFlag.AlignVCenter)

        self._name_lbl = QLabel(name)
        self._name_lbl.setStyleSheet(self._NAME_QSS)
        self._name_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        header.addWidget(self._name_lbl, 1, Qt.AlignmentFlag.AlignVCenter)

        # Refresh-style Apply ▾ split (see RefreshButton + library_menu_stylesheet).
        apply_split = QWidget()
        apply_split.setFixedHeight(26)
        apply_split.setStyleSheet(ut.presets_apply_split_stylesheet())
        apply_lay = QHBoxLayout(apply_split)
        apply_lay.setContentsMargins(0, 0, 0, 0)
        apply_lay.setSpacing(0)

        self._apply = QPushButton("Apply")
        self._apply.setObjectName("PresetApplyMain")
        self._apply.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._apply.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._apply.setToolTip("Apply this preset to the export panel")
        self._apply.clicked.connect(lambda *_: on_apply(name))

        self._apply_menu_btn = QPushButton()
        self._apply_menu_btn.setObjectName("PresetApplyMenu")
        self._apply_menu_btn.setIcon(arrow_icon(10, direction="down"))
        self._apply_menu_btn.setIconSize(QSize(10, 10))
        self._apply_menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_menu_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._apply_menu_btn.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
        self._apply_menu_btn.setToolTip("More preset actions")

        menu = QMenu(apply_split)
        menu.setStyleSheet(ut.library_menu_stylesheet())
        act_update = menu.addAction("Update from panel")
        act_rename = menu.addAction("Rename…")
        act_dup = menu.addAction("Duplicate")
        menu.addSeparator()
        act_del = menu.addAction("Delete")
        act_update.triggered.connect(lambda *_: on_update(name))
        act_rename.triggered.connect(lambda *_: on_rename(name))
        act_dup.triggered.connect(lambda *_: on_duplicate(name))
        act_del.triggered.connect(lambda *_: on_delete(name))

        def _show_apply_menu():
            menu.exec(
                self._apply_menu_btn.mapToGlobal(
                    QPoint(0, self._apply_menu_btn.height())
                )
            )

        self._apply_menu_btn.clicked.connect(_show_apply_menu)

        apply_lay.addWidget(self._apply)
        apply_lay.addWidget(self._apply_menu_btn)
        header.addWidget(apply_split, 0, Qt.AlignmentFlag.AlignVCenter)

        root.addLayout(header)

        self._detail = QLabel(summary or "—")
        self._detail.setObjectName("preset_row_detail")
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet(self._DETAIL_QSS)
        self._detail.setVisible(self._expanded)
        root.addWidget(self._detail)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_select(self._name)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Double-click name area applies (Apply button also available).
            self._apply.click()
        super().mouseDoubleClickEvent(event)

    def _emit_toggle_expand(self) -> None:
        self._on_toggle_expand(self._name)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self._chevron.setText("▾" if self._expanded else "▸")
        self._detail.setVisible(self._expanded)
        self.updateGeometry()

    def preferred_size_hint(self) -> QSize:
        self.ensurePolished()
        return self.sizeHint()


class StandardPresetRow(QWidget):
    """Read-only Standard quality ladder row — Apply only (immutable)."""

    _NAME_QSS = (
        f"QLabel {{ color: #e8e8e8; background: transparent; font-size: 13px;"
        f" font-weight: bold; {_font_css()} }}"
    )
    _HINT_QSS = (
        f"QLabel {{ color: #888888; background: transparent; font-size: 11px;"
        f" {_font_css()} }}"
    )

    def __init__(self, label: str, *, on_apply, parent=None):
        super().__init__(parent)
        self._label = label
        self.setObjectName("StandardPresetRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("QWidget#StandardPresetRow { background: transparent; }")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(8)

        name_col = QVBoxLayout()
        name_col.setContentsMargins(0, 0, 0, 0)
        name_col.setSpacing(0)
        name_lbl = QLabel(label)
        name_lbl.setStyleSheet(self._NAME_QSS)
        name_col.addWidget(name_lbl)
        if "Target File Size" in (label or ""):
            hint_text = "Built-in · custom-standard"
        else:
            hint_text = "Built-in · not editable"
        hint = QLabel(hint_text)
        hint.setStyleSheet(self._HINT_QSS)
        name_col.addWidget(hint)
        row.addLayout(name_col, 1)

        # Solo pill — not PresetApplyMain (that QSS is the left half of Apply ▾
        # and looks like the button floated off / cut open without the menu).
        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("PresetApplySolo")
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        apply_btn.setFixedHeight(26)
        apply_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        apply_btn.setStyleSheet(ut.presets_apply_solo_stylesheet())
        apply_btn.setToolTip("Apply this standard quality to Video Settings")
        apply_btn.clicked.connect(lambda *_: on_apply(label))
        row.addWidget(apply_btn, 0, Qt.AlignmentFlag.AlignVCenter)

    def preferred_size_hint(self) -> QSize:
        self.ensurePolished()
        return self.sizeHint()


class PresetSectionHeader(QWidget):
    """Section caption inside the presets list (Standard / Custom)."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("PresetSectionHeader")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 10, 6, 2)
        # Title-case purple caption — same language as Quality Preset combo.
        display = (title or "").strip().title()
        lbl = QLabel(display)
        lbl.setFont(tok.ui_qfont(11, weight=QFont.Weight.Bold))
        lbl.setStyleSheet(
            "QLabel { color: #b29ae7; background: transparent; }"
        )
        lay.addWidget(lbl)
        lay.addStretch(1)

    def preferred_size_hint(self) -> QSize:
        self.ensurePolished()
        return self.sizeHint()


def restyle_presets_page(ui, app) -> None:
    """Presets tab: create strip + searchable expandable list (row actions)."""
    from steempeg.ui.design_tokens import with_tooltip_style
    from steempeg.ui.icon_assets import info_icon

    page = ensure_presets_tab(ui)
    _drop_layout(page)

    # Drop legacy chrome attrs so density restyle / stale refs don't assume them.
    for attr in (
        "btn_preset_update",
        "btn_preset_rename",
        "btn_preset_duplicate",
        "btn_preset_apply",
        "btn_preset_favourite",
        "btn_preset_delete",
        "preset_detail_label",
        "preset_favourites_host",
        "preset_favourites_layout",
        "preset_favourites_block",
        "preset_selected_label",
    ):
        if hasattr(ui, attr):
            setattr(ui, attr, None)

    root = QVBoxLayout(page)
    root.setContentsMargins(*_settings_page_margins())
    root.setSpacing(10)

    title_row = QHBoxLayout()
    title_row.setContentsMargins(0, 0, 0, 0)
    title_row.setSpacing(8)
    title_row.addWidget(_page_title_icon_label(4), 0, Qt.AlignmentFlag.AlignVCenter)
    title_row.addWidget(_page_title("Presets"), 0, Qt.AlignmentFlag.AlignVCenter)
    info_btn = QPushButton()
    info_btn.setObjectName("preset_help_info")
    info_btn.setIcon(info_icon(14))
    info_btn.setIconSize(QSize(14, 14))
    info_btn.setFixedSize(22, 22)
    info_btn.setFlat(True)
    info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    info_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    info_btn.setToolTip(
        "Standard — built-in quality ladder (immutable).\n"
        "Custom — your saved Video / Audio / Export recipes.\n"
        "Apply from here or pick either kind in Video Settings → Quality Preset.\n"
        "Star Custom rows to pin favourites. Expand a Custom row for details.\n"
        "▾ on Custom: Update / Rename / Duplicate / Delete."
    )
    info_btn.setStyleSheet(
        with_tooltip_style(
            "QPushButton {"
            " background: transparent; border: none; border-radius: 11px;"
            " padding: 0px; margin: 0px;"
            "}"
            " QPushButton:hover { background-color: rgba(255, 255, 255, 0.08); }"
            " QPushButton:pressed { background-color: rgba(255, 255, 255, 0.12); }"
        )
    )
    ui.btn_preset_help = info_btn
    title_row.addWidget(info_btn, 0, Qt.AlignmentFlag.AlignVCenter)
    title_row.addStretch(1)
    root.addLayout(title_row)

    name_cap = QLabel("Preset name")
    name_cap.setStyleSheet(_FIELD_LABEL_QSS)
    name_edit = QLineEdit()
    name_edit.setObjectName("preset_name_edit")
    name_edit.setPlaceholderText("e.g. Discord 720p")
    name_edit.setStyleSheet(ut.presets_line_edit_stylesheet())
    ui.preset_name_edit = name_edit

    def _save_as_like_btn(
        label: str,
        *,
        bg: str,
        fg: str,
        border: str,
        hover_bg: str,
        hover_border: str,
        pressed_bg: str,
    ) -> QPushButton:
        btn = QPushButton(label)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(34)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {bg}; color: {fg};"
            f" border: 2px solid {border}; border-radius: 12px;"
            f" font-family: {tok.FONT_APP};"
            f" font-weight: bold; font-size: 12px; padding: 0px 10px; }}"
            f" QPushButton:hover {{ background-color: {hover_bg}; border: 2px solid {hover_border}; }}"
            f" QPushButton:pressed {{ background-color: {pressed_bg}; border: 2px solid {hover_border}; }}"
            f" QPushButton:disabled {{ color: #777777; border-color: #3a3a3a;"
            f" background-color: #2a2a2a; }}"
        )
        fnt = btn.font()
        fnt = tok.pin_ui_font(fnt)
        fnt.setBold(True)
        fnt.setPixelSize(12)
        btn.setFont(fnt)
        return btn

    btn_save = _save_as_like_btn(
        "Save as new",
        bg="#4a3d66",
        fg="#f0ecff",
        border="#6b5a8e",
        hover_bg="#5a4d76",
        hover_border="#b29ae7",
        pressed_bg="#3a324a",
    )
    btn_save.setToolTip("Save the current Video / Audio / Export panel as a new named preset.")
    ui.btn_preset_save = btn_save

    name_block = QWidget()
    name_lay = QVBoxLayout(name_block)
    name_lay.setContentsMargins(0, 0, 0, 0)
    name_lay.setSpacing(4)
    name_lay.addWidget(name_cap)
    create_row = QHBoxLayout()
    create_row.setContentsMargins(0, 0, 0, 0)
    create_row.setSpacing(8)
    create_row.addWidget(name_edit, 1)
    create_row.addWidget(btn_save, 0)
    name_lay.addLayout(create_row)
    root.addWidget(_content_width_wrap(name_block))

    list_cap = QLabel("Standard & Custom")
    list_cap.setStyleSheet(_FIELD_LABEL_QSS)
    root.addWidget(list_cap)

    search_edit = QLineEdit()
    search_edit.setObjectName("preset_search_edit")
    search_edit.setPlaceholderText("Search…")
    search_edit.setClearButtonEnabled(True)
    search_edit.setStyleSheet(ut.presets_line_edit_stylesheet(compact=True))
    ui.preset_search_edit = search_edit
    root.addWidget(_content_width_wrap(search_edit))

    preset_list = QListWidget()
    preset_list.setObjectName("preset_list")
    preset_list.setMinimumHeight(180)
    preset_list.setSpacing(2)
    preset_list.setUniformItemSizes(False)
    preset_list.setStyleSheet(ut.presets_list_widget_stylesheet())
    ui.preset_list = preset_list
    root.addWidget(_content_width_wrap(preset_list), 1)

    status = QLabel("")
    status.setObjectName("preset_status_label")
    status.setWordWrap(True)
    status.setStyleSheet(f"color: #9a9a9a; background: transparent; font-size: 11px; {_font_css()}")
    ui.preset_status_label = status
    root.addWidget(status)

    btn_save.clicked.connect(lambda: getattr(app, "save_export_preset_from_ui", lambda: None)())
    preset_list.itemSelectionChanged.connect(
        lambda: getattr(app, "_on_export_preset_selection_changed", lambda: None)()
    )
    search_edit.textChanged.connect(
        lambda *_: getattr(app, "refresh_export_presets_list", lambda: None)()
    )

    if hasattr(app, "refresh_export_presets_list"):
        app.refresh_export_presets_list()

