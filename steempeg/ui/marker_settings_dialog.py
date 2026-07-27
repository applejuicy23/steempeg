"""Marker settings — CS2 / Classes / On clip tabs."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.paths import get_resource_path, reveal_in_file_manager
from steempeg.services import marker_prefs as mprefs
from steempeg.ui import design_tokens as tok
from steempeg.ui.marker_icons import (
    class_display_pixmap,
    class_has_custom_icon,
    load_scaled_pixmap,
    tint_pixmap,
)
from steempeg.ui.message_dialog import (
    _BTN_DANGER,
    _BTN_PRIMARY,
    _BTN_SECONDARY,
    dialog_theme,
    steempeg_question,
)
from steempeg.ui.widgets.dialog_chrome import SteempegDialog
from steempeg.ui.widgets.steempeg_check import SteempegCheckBox

_SECTION = (
    f"color: {tok.TEXT_TITLE}; font-size: 13px; font-weight: bold; "
    f"background: transparent; font-family: {tok.FONT_APP};"
)
_HINT = (
    f"color: {tok.TEXT_MUTED}; font-size: 12px; background: transparent; "
    f"font-family: {tok.FONT_APP};"
)
_FIELD = """
    QLineEdit, QComboBox {
        background-color: #2d2d2d; color: #f0f0f0; border: 1px solid #555;
        border-radius: 6px; padding: 6px 10px; font-size: 12px;
        font-family: 'Segoe UI', 'Noto Sans', Arial, sans-serif;
        min-height: 28px;
    }
    QLineEdit:focus, QComboBox:focus { border-color: #6b5a8e; }
    QComboBox::drop-down { border: none; width: 24px; }
"""
_LIST = """
    QListWidget {
        background-color: #242424; border: 1px solid #444; border-radius: 8px;
        color: #eee; font-size: 12px; outline: none;
    }
    QListWidget::item { padding: 2px 4px; margin: 2px 4px; border-radius: 6px; }
    QListWidget::item:selected { background-color: #4a3d66; }
    QListWidget::item:hover:!selected { background-color: #333; }
"""
_MARKER_HOST = """
    QWidget#markerListInner {
        background-color: #242424; border: 1px solid #444; border-radius: 8px;
    }
"""
_PICK_ROW = """
    QFrame#mkPick {
        background: transparent; border-radius: 6px;
    }
    QFrame#mkPick:hover {
        background-color: #333;
    }
"""
_PICK_ROW_SEL = """
    QFrame#mkPick {
        background-color: #4a3d66; border-radius: 6px;
    }
"""
_ICON_BTN = """
    QPushButton {
        background: transparent; border: none; color: #ccc;
        font-size: 12px; padding: 2px 6px; min-width: 22px;
    }
    QPushButton:hover { color: #fff; }
"""
_CLASS_ROW_H = 40
_CLASS_ICON = 22
_SHOT_EXPAND_AT = 5
_TABS = """
    QTabWidget::pane { border: 1px solid #444; border-radius: 8px; background: #1e1e1e; }
    QTabBar::tab {
        background: #2a2a2a; color: #aaa; padding: 8px 16px; margin-right: 4px;
        border-top-left-radius: 6px; border-top-right-radius: 6px;
        font-family: 'Segoe UI', Arial; font-size: 12px; font-weight: bold;
    }
    QTabBar::tab:selected { background: #4a3d66; color: #fff; }
    QTabBar::tab:hover:!selected { background: #353535; color: #ddd; }
"""


class _MarkerPickRow(QFrame):
    """One selectable marker row in the On clip list."""

    activated = Signal(str)

    def __init__(
        self,
        key: str,
        label: str,
        *,
        indent: int = 0,
        tip: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._key = key
        self.setObjectName("mkPick")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(_PICK_ROW)
        if tip:
            self.setToolTip(tip)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8 + indent * 14, 6, 8, 6)
        lay.setSpacing(6)
        self._lbl = QLabel(label)
        self._lbl.setStyleSheet(
            f"color: {tok.TEXT_PRIMARY}; font-size: 12px; background: transparent; "
            f"font-family: {tok.FONT_APP};"
        )
        lay.addWidget(self._lbl, 1)

    def set_selected(self, selected: bool) -> None:
        self.setStyleSheet(_PICK_ROW_SEL if selected else _PICK_ROW)

    def set_label(self, text: str) -> None:
        self._lbl.setText(text)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self._key)
            event.accept()
        else:
            super().mousePressEvent(event)


class _ScreenshotGroup(QWidget):
    """Collapsed by default when many screenshots — expand like Update Center."""

    activated = Signal(str)

    def __init__(self, rows: list[dict], parent=None):
        super().__init__(parent)
        self._rows = rows
        self._expanded = False
        self._pick_rows: list[_MarkerPickRow] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        header = QFrame()
        header.setObjectName("mkPick")
        header.setStyleSheet(_PICK_ROW)
        h = QHBoxLayout(header)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(6)
        title = QLabel(f"Screenshots ({len(rows)})")
        title.setStyleSheet(
            f"color: {tok.TEXT_PRIMARY}; font-size: 12px; font-weight: 600; "
            f"background: transparent; font-family: {tok.FONT_APP};"
        )
        h.addWidget(title, 1)
        self._expand_btn = QPushButton("▸")
        self._expand_btn.setToolTip("Show all screenshots on this clip")
        self._expand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._expand_btn.setStyleSheet(_ICON_BTN)
        self._expand_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._expand_btn.clicked.connect(self._toggle)
        h.addWidget(self._expand_btn)
        root.addWidget(header)

        self._child_host = QWidget()
        child = QVBoxLayout(self._child_host)
        child.setContentsMargins(0, 0, 0, 0)
        child.setSpacing(2)
        for row in rows:
            pick = _MarkerPickRow(
                row["key"],
                row.get("_display") or row["label"],
                indent=1,
                tip=row.get("_tip") or row["key"],
            )
            pick.activated.connect(self.activated.emit)
            child.addWidget(pick)
            self._pick_rows.append(pick)
        root.addWidget(self._child_host)
        self._child_host.hide()

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._child_host.setVisible(self._expanded)
        self._expand_btn.setText("▾" if self._expanded else "▸")

    def expand(self) -> None:
        if not self._expanded:
            self._toggle()

    def set_selected_key(self, key: str | None) -> None:
        for pick in self._pick_rows:
            pick.set_selected(pick._key == key)
        if key and any(p._key == key for p in self._pick_rows):
            self.expand()


def _scroll_page(inner: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(inner)
    return scroll


class MarkerSettingsDialog(SteempegDialog):
    prefs_changed = Signal()

    def __init__(
        self,
        app=None,
        parent=None,
        *,
        app_id: str | None = None,
        clip_markers: list | None = None,
        **theme_kwargs,
    ):
        if not theme_kwargs.get("bar_color"):
            theme_kwargs = {**dialog_theme(parent), **theme_kwargs}
        marker_bar_icon = get_resource_path("pointuser.png")
        super().__init__(
            "Marker settings",
            parent,
            bar_icon=marker_bar_icon if os.path.isfile(marker_bar_icon) else None,
            **theme_kwargs,
        )
        self._app = app
        self._app_id = str(app_id or "") or None
        self._clip_markers = list(clip_markers or [])
        self._is_cs2_clip = str(self._app_id or "") == mprefs.CS2_APP_ID
        self.setMinimumSize(900, 680)
        self.resize(1000, 780)

        self._prefs = mprefs.load_marker_prefs()
        self._clip_rows = mprefs.clip_marker_setting_rows(self._clip_markers)
        self._selected_key: str | None = None

        root = self.content_layout
        root.setSpacing(10)

        from steempeg.ui.icon_assets import load_pixmap

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        title_icon = QLabel()
        title_icon.setFixedSize(28, 28)
        title_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_pix = load_pixmap("pointuser.png", 26)
        if title_pix.isNull():
            # Fallback if icon_assets path misses the asset.
            from PySide6.QtGui import QPixmap

            raw = get_resource_path("pointuser.png")
            if os.path.isfile(raw):
                title_pix = QPixmap(raw).scaled(
                    26,
                    26,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
        if not title_pix.isNull():
            title_icon.setPixmap(title_pix)
        title_icon.setStyleSheet("background: transparent;")
        title_row.addWidget(title_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        title = QLabel("Marker settings")
        title.setStyleSheet(tok.STYLE_PANEL_TITLE)
        title_row.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        root.addLayout(title_row)

        if self._is_cs2_clip:
            intro_text = (
                "Configure timeline marker icons here. Open a CS2 clip to see its "
                "markers on the On clip tab."
            )
        else:
            intro_text = (
                "Configure timeline marker icons here. Open a clip in the player to "
                "edit its markers on the On clip tab."
            )
        intro = QLabel(intro_text)
        intro.setWordWrap(True)
        intro.setStyleSheet(tok.STYLE_PANEL_SUBTITLE)
        root.addWidget(intro)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(_TABS)
        if self._is_cs2_clip:
            self._tabs.addTab(self._build_cs2_tab(), "CS2")
        self._tabs.addTab(self._build_classes_tab(), "Classes")
        self._tabs.addTab(self._build_markers_tab(), "On clip")
        root.addWidget(self._tabs, 1)

        foot = QHBoxLayout()
        btn_reset_steam = QPushButton("Reset game markers")
        btn_reset_steam.setStyleSheet(_BTN_SECONDARY)
        btn_reset_steam.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset_steam.clicked.connect(self._reset_steam)
        btn_reset_all = QPushButton("Reset all")
        btn_reset_all.setStyleSheet(_BTN_DANGER)
        btn_reset_all.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset_all.clicked.connect(self._reset_all)
        foot.addWidget(btn_reset_steam)
        foot.addWidget(btn_reset_all)
        foot.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.setStyleSheet(_BTN_PRIMARY)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        foot.addWidget(btn_close)
        root.addLayout(foot)

        self._reload_classes()
        self._repopulate_markers()
        self._reload_class_combo()

    def _build_cs2_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        lay.addWidget(self._section("Counter-Strike 2 icons"))
        self._chk_steempeg = SteempegCheckBox(
            "Use Steempeg hand-drawn icons (kill.png, death.png, grenades…)"
        )
        self._chk_steempeg.setChecked(
            mprefs.cs2_icon_pack(self._prefs) == mprefs.PACK_STEEMPEG
        )
        self._chk_steempeg.toggled.connect(self._on_pack_toggled)
        lay.addWidget(self._chk_steempeg)

        lay.addWidget(
            self._hint(
                "Off — Steam style (markers.svg, white silhouettes).\n"
                "On — colored PNGs from Steempeg, like legacy v20.\n"
                "Applies immediately to the open CS2 clip timeline."
            )
        )
        lay.addStretch(1)
        return _scroll_page(page)

    def _build_classes_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        lay.addWidget(
            self._hint(
                "A class groups your markers: shared name and color (the white dot "
                "will be tinted). You can set one icon for the whole class."
            )
        )

        row = QHBoxLayout()
        row.setSpacing(12)

        left = QVBoxLayout()
        left.addWidget(self._section("Class list"))
        self._class_list = QListWidget()
        self._class_list.setStyleSheet(_LIST)
        self._class_list.setMinimumWidth(200)
        self._class_list.setMinimumHeight(220)
        self._class_list.currentRowChanged.connect(self._on_class_row)
        left.addWidget(self._class_list, 1)
        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Create")
        btn_add.setStyleSheet(_BTN_PRIMARY)
        btn_add.clicked.connect(self._add_class)
        btn_del = QPushButton("Delete")
        btn_del.setStyleSheet(_BTN_DANGER)
        btn_del.clicked.connect(self._delete_class)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_del)
        left.addLayout(btn_row)
        row.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(8)
        self._cls_empty = QLabel("Select a class on the left, or click Create.")
        self._cls_empty.setWordWrap(True)
        self._cls_empty.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._cls_empty.setStyleSheet(_HINT)
        right.addWidget(self._cls_empty, 1)

        self._cls_editor = QWidget()
        ed = QVBoxLayout(self._cls_editor)
        ed.setContentsMargins(0, 0, 0, 0)
        ed.setSpacing(8)
        ed.addWidget(self._section("Class editor"))

        ed.addWidget(QLabel("Name"))
        self._cls_name = QLineEdit()
        self._cls_name.setPlaceholderText("e.g. Clutches")
        self._cls_name.setStyleSheet(_FIELD)
        self._cls_name.editingFinished.connect(self._save_class_fields)
        ed.addWidget(self._cls_name)

        color_row = QHBoxLayout()
        self._cls_color_btn = QPushButton("Pick color…")
        self._cls_color_btn.setStyleSheet(_BTN_SECONDARY)
        self._cls_color_btn.clicked.connect(self._pick_class_color)
        self._cls_color_swatch = QLabel()
        self._cls_color_swatch.setFixedSize(32, 32)
        self._cls_color_clear = QPushButton("No color")
        self._cls_color_clear.setToolTip(
            "Group-only class — members keep default colors (no tint)."
        )
        self._cls_color_clear.setStyleSheet(_BTN_SECONDARY)
        self._cls_color_clear.clicked.connect(self._clear_class_color)
        color_row.addWidget(self._cls_color_btn)
        color_row.addWidget(self._cls_color_swatch)
        color_row.addWidget(self._cls_color_clear)
        color_row.addStretch(1)
        ed.addWidget(QLabel("Marker color (optional)"))
        ed.addLayout(color_row)
        ed.addWidget(
            self._hint(
                "Leave empty for a plain group. Color tints white pin / screenshot "
                "glyphs — custom pictures are never recolored."
            )
        )

        icon_row = QHBoxLayout()
        self._cls_icon_btn = QPushButton("Class icon…")
        self._cls_icon_btn.setStyleSheet(_BTN_SECONDARY)
        self._cls_icon_btn.clicked.connect(self._pick_class_icon)
        self._cls_icon_clear = QPushButton("Remove")
        self._cls_icon_clear.setStyleSheet(_BTN_SECONDARY)
        self._cls_icon_clear.clicked.connect(self._clear_class_icon)
        icon_row.addWidget(self._cls_icon_btn)
        icon_row.addWidget(self._cls_icon_clear)
        ed.addWidget(QLabel("Icon (optional)"))
        ed.addLayout(icon_row)
        ed.addStretch(1)

        self._cls_editor.hide()
        right.addWidget(self._cls_editor, 1)
        row.addLayout(right, 2)
        lay.addLayout(row, 1)
        return _scroll_page(page)

    def _build_markers_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        if not self._clip_rows:
            empty = QLabel(
                "No configurable markers on this clip — or no clip is open.\n"
                "Open a CS2 recording in the player and open Marker settings again."
            )
            empty.setWordWrap(True)
            empty.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, "#e8c87a"))
            lay.addWidget(empty)
            lay.addStretch(1)
            return _scroll_page(page)

        lay.addWidget(
            self._hint(
                "Markers on this clip. Custom pins and screenshots are listed "
                "one-by-one. If there are more than 5 screenshots, expand the "
                "Screenshots group (like Check for updates). Game types (kill, "
                "death, …) share one setting for every match on the timeline."
            )
        )

        row = QHBoxLayout()
        row.setSpacing(12)

        left = QVBoxLayout()
        left.addWidget(self._section("Markers on clip"))
        self._marker_scroll = QScrollArea()
        self._marker_scroll.setWidgetResizable(True)
        self._marker_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._marker_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._marker_scroll.setMinimumWidth(220)
        self._marker_scroll.setMinimumHeight(240)
        self._marker_scroll.setStyleSheet(_MARKER_HOST)
        self._marker_list_inner = QWidget()
        self._marker_list_inner.setObjectName("markerListInner")
        self._marker_list_layout = QVBoxLayout(self._marker_list_inner)
        self._marker_list_layout.setContentsMargins(4, 4, 4, 4)
        self._marker_list_layout.setSpacing(2)
        self._marker_list_layout.addStretch(1)
        self._marker_scroll.setWidget(self._marker_list_inner)
        left.addWidget(self._marker_scroll, 1)
        self._pick_rows: dict[str, _MarkerPickRow] = {}
        self._shot_group: _ScreenshotGroup | None = None
        row.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(8)

        self._mk_empty = QLabel("Select a marker on the left.")
        self._mk_empty.setWordWrap(True)
        self._mk_empty.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._mk_empty.setStyleSheet(_HINT)
        right.addWidget(self._mk_empty, 1)

        self._mk_editor = QWidget()
        ed = QVBoxLayout(self._mk_editor)
        ed.setContentsMargins(0, 0, 0, 0)
        ed.setSpacing(8)
        ed.addWidget(self._section("Selected marker"))

        prev_row = QHBoxLayout()
        self._mk_preview = QLabel()
        self._mk_preview.setFixedSize(48, 48)
        self._mk_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mk_preview.setStyleSheet(
            "background: #1a1a1a; border-radius: 8px; border: 1px solid #555;"
        )
        self._mk_id_lbl = QLabel("")
        self._mk_id_lbl.setWordWrap(True)
        self._mk_id_lbl.setStyleSheet(
            _HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY)
        )
        prev_row.addWidget(self._mk_preview)
        prev_row.addWidget(self._mk_id_lbl, 1)
        ed.addLayout(prev_row)

        ed.addWidget(QLabel("Label (optional)"))
        self._mk_label = QLineEdit()
        self._mk_label.setPlaceholderText("How to show in tooltips")
        self._mk_label.setStyleSheet(_FIELD)
        self._mk_label.editingFinished.connect(self._save_marker_fields)
        ed.addWidget(self._mk_label)

        ed.addWidget(QLabel("Class"))
        self._mk_class = QComboBox()
        self._mk_class.setStyleSheet(_FIELD)
        self._mk_class.currentIndexChanged.connect(self._save_marker_fields)
        ed.addWidget(self._mk_class)

        self._mk_no_tint = SteempegCheckBox(
            "Don't apply class color (keep original look)"
        )
        self._mk_no_tint.setToolTip(
            "Stay in the class for grouping/name, but skip the class tint. "
            "Custom icons already keep their own colors."
        )
        self._mk_no_tint.toggled.connect(self._save_marker_fields)
        ed.addWidget(self._mk_no_tint)

        icon_row = QHBoxLayout()
        self._mk_icon_btn = QPushButton("Custom icon…")
        self._mk_icon_btn.setStyleSheet(_BTN_SECONDARY)
        self._mk_icon_btn.clicked.connect(self._pick_marker_icon)
        self._mk_icon_clear = QPushButton("Remove")
        self._mk_icon_clear.setStyleSheet(_BTN_SECONDARY)
        self._mk_icon_clear.clicked.connect(self._clear_marker_icon)
        icon_row.addWidget(self._mk_icon_btn)
        icon_row.addWidget(self._mk_icon_clear)
        ed.addWidget(QLabel("Icon"))
        ed.addLayout(icon_row)

        self._mk_path_section = QWidget()
        path_lay = QVBoxLayout(self._mk_path_section)
        path_lay.setContentsMargins(0, 4, 0, 0)
        path_lay.setSpacing(6)
        path_lay.addWidget(QLabel("Saved file"))

        path_body = QHBoxLayout()
        path_body.setSpacing(10)
        self._mk_shot_preview = QLabel()
        self._mk_shot_preview.setFixedSize(120, 68)
        self._mk_shot_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mk_shot_preview.setStyleSheet(
            "background: #1a1a1a; border-radius: 8px; border: 1px solid #555; color: #888;"
        )
        self._mk_shot_preview.setScaledContents(False)
        path_body.addWidget(self._mk_shot_preview, 0, Qt.AlignmentFlag.AlignTop)

        path_col = QVBoxLayout()
        path_col.setSpacing(6)
        self._mk_path_lbl = QLabel("")
        self._mk_path_lbl.setWordWrap(True)
        self._mk_path_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._mk_path_lbl.setStyleSheet(_HINT)
        path_col.addWidget(self._mk_path_lbl)
        path_btns = QHBoxLayout()
        self._mk_path_open = QPushButton("Open file")
        self._mk_path_open.setStyleSheet(_BTN_SECONDARY)
        self._mk_path_open.clicked.connect(self._open_selected_screenshot)
        self._mk_path_folder = QPushButton("Open folder")
        self._mk_path_folder.setStyleSheet(_BTN_SECONDARY)
        self._mk_path_folder.clicked.connect(self._open_selected_screenshot_folder)
        path_btns.addWidget(self._mk_path_open)
        path_btns.addWidget(self._mk_path_folder)
        path_btns.addStretch(1)
        path_col.addLayout(path_btns)
        path_col.addStretch(1)
        path_body.addLayout(path_col, 1)
        path_lay.addLayout(path_body)
        self._mk_path_section.hide()
        ed.addWidget(self._mk_path_section)

        btn_reset_one = QPushButton("Reset this marker")
        btn_reset_one.setStyleSheet(_BTN_SECONDARY)
        btn_reset_one.clicked.connect(self._reset_one_marker)
        ed.addWidget(btn_reset_one)
        ed.addStretch(1)

        self._mk_editor.hide()
        right.addWidget(self._mk_editor, 1)
        row.addLayout(right, 2)
        lay.addLayout(row, 1)
        return _scroll_page(page)

    @staticmethod
    def _section(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_SECTION)
        return lbl

    @staticmethod
    def _hint(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(_HINT)
        return lbl

    def _emit_changed(self) -> None:
        self._prefs = mprefs.load_marker_prefs()
        self.prefs_changed.emit()

    def _on_pack_toggled(self, checked: bool) -> None:
        mprefs.set_cs2_icon_pack(
            mprefs.PACK_STEEMPEG if checked else mprefs.PACK_STEAM
        )
        self._emit_changed()
        self._refresh_marker_preview()

    def _reload_classes(self) -> None:
        prev_id = self._current_class_id()
        self._class_list.blockSignals(True)
        self._class_list.clear()
        for cls in self._prefs.get("classes") or []:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, cls.get("id"))
            item.setSizeHint(QSize(0, _CLASS_ROW_H))
            self._class_list.addItem(item)
            self._class_list.setItemWidget(item, self._make_class_row_widget(cls))
        self._class_list.blockSignals(False)
        if prev_id:
            for i in range(self._class_list.count()):
                it = self._class_list.item(i)
                if it and it.data(Qt.ItemDataRole.UserRole) == prev_id:
                    self._class_list.setCurrentRow(i)
                    break
        self._on_class_row(self._class_list.currentRow())
        self._reload_class_combo()

    def _make_class_row_widget(self, cls: dict) -> QWidget:
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(6, 4, 8, 4)
        lay.setSpacing(10)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(_CLASS_ICON, _CLASS_ICON)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("background: transparent;")
        pix = class_display_pixmap(cls, height=_CLASS_ICON)
        if pix is not None and not pix.isNull():
            icon_lbl.setPixmap(pix)
        lay.addWidget(icon_lbl)

        name_lbl = QLabel(str(cls.get("name") or "Class"))
        name_lbl.setStyleSheet(
            f"color: {tok.TEXT_PRIMARY}; font-size: 12px; background: transparent; "
            f"font-family: {tok.FONT_APP};"
        )
        lay.addWidget(name_lbl, 1)

        if not class_has_custom_icon(cls):
            color = str(cls.get("color") or "").strip()
            if color:
                color_lbl = QLabel(color)
                color_lbl.setStyleSheet(
                    f"color: {tok.TEXT_MUTED}; font-size: 11px; background: transparent; "
                    f"font-family: {tok.FONT_APP};"
                )
                lay.addWidget(color_lbl)
            else:
                mute = QLabel("no color")
                mute.setStyleSheet(
                    f"color: {tok.TEXT_MUTED}; font-size: 11px; background: transparent; "
                    f"font-family: {tok.FONT_APP}; font-style: italic;"
                )
                lay.addWidget(mute)

        return row

    def _reload_class_combo(self) -> None:
        if not hasattr(self, "_mk_class"):
            return
        self._mk_class.blockSignals(True)
        cur = self._mk_class.currentData()
        self._mk_class.clear()
        self._mk_class.addItem("— no class —", "")
        for cls in self._prefs.get("classes") or []:
            self._mk_class.addItem(str(cls.get("name")), cls.get("id"))
        if cur:
            idx = self._mk_class.findData(cur)
            if idx >= 0:
                self._mk_class.setCurrentIndex(idx)
        self._mk_class.blockSignals(False)

    def _current_class_id(self) -> str | None:
        item = self._class_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_class_row(self, row: int) -> None:
        has_sel = row >= 0
        self._cls_empty.setVisible(not has_sel)
        self._cls_editor.setVisible(has_sel)
        if not has_sel:
            return
        cid = self._current_class_id()
        cls = mprefs.get_class(cid, self._prefs)
        if not cls:
            return
        self._cls_name.setText(str(cls.get("name") or ""))
        color = str(cls.get("color") or "").strip()
        if color:
            self._cls_color_swatch.setStyleSheet(
                f"background: {color}; border-radius: 6px; border: 1px solid #888;"
            )
            self._cls_color_swatch.setToolTip(color)
        else:
            self._cls_color_swatch.setStyleSheet(
                "background: transparent; border-radius: 6px; "
                "border: 1px dashed #666;"
            )
            self._cls_color_swatch.setToolTip("No color — group only")

    def _add_class(self) -> None:
        mprefs.create_class("New class")
        self._emit_changed()
        self._reload_classes()
        self._class_list.setCurrentRow(self._class_list.count() - 1)
        self._on_class_row(self._class_list.currentRow())

    def _delete_class(self) -> None:
        cid = self._current_class_id()
        if not cid:
            return
        if not steempeg_question(
            self, "Delete class?", "Markers will stay, but without this class."
        ):
            return
        mprefs.delete_class(cid)
        self._emit_changed()
        self._reload_classes()

    def _save_class_fields(self) -> None:
        cid = self._current_class_id()
        if not cid:
            return
        mprefs.update_class(cid, name=self._cls_name.text())
        self._emit_changed()
        row = self._class_list.currentRow()
        self._reload_classes()
        if 0 <= row < self._class_list.count():
            self._class_list.setCurrentRow(row)

    def _pick_class_color(self) -> None:
        cid = self._current_class_id()
        if not cid:
            return
        cls = mprefs.get_class(cid, self._prefs) or {}
        color = QColorDialog.getColor(
            QColor(str(cls.get("color") or "#b29ae7")), self, "Class color"
        )
        if not color.isValid():
            return
        mprefs.update_class(cid, color=color.name())
        self._emit_changed()
        self._on_class_row(self._class_list.currentRow())
        self._reload_classes()

    def _clear_class_color(self) -> None:
        cid = self._current_class_id()
        if not cid:
            return
        mprefs.update_class(cid, color="")
        self._emit_changed()
        self._on_class_row(self._class_list.currentRow())
        self._reload_classes()

    def _pick_class_icon(self) -> None:
        cid = self._current_class_id()
        if not cid:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Class icon", "", "Images (*.png *.jpg *.jpeg *.webp)"
        )
        if path:
            mprefs.update_class(cid, icon=path)
            self._emit_changed()
            row = self._class_list.currentRow()
            self._reload_classes()
            if 0 <= row < self._class_list.count():
                self._class_list.setCurrentRow(row)

    def _clear_class_icon(self) -> None:
        cid = self._current_class_id()
        if cid:
            mprefs.update_class(cid, icon="")
            self._emit_changed()
            row = self._class_list.currentRow()
            self._reload_classes()
            if 0 <= row < self._class_list.count():
                self._class_list.setCurrentRow(row)

    def _repopulate_markers(self) -> None:
        if not hasattr(self, "_marker_list_layout"):
            return
        prev = self._selected_key
        # Clear previous widgets (keep trailing stretch).
        while self._marker_list_layout.count() > 1:
            item = self._marker_list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._pick_rows = {}
        self._shot_group = None

        users: list[dict] = []
        shots: list[dict] = []
        others: list[dict] = []
        for row in self._clip_rows:
            key = row["key"]
            ov = mprefs.marker_override(key, self._prefs)
            display = (ov.get("label") or "").strip() or row["label"]
            if ov.get("class_id"):
                cls = mprefs.get_class(ov["class_id"], self._prefs)
                if cls:
                    display = f"{display}  ·  {cls.get('name')}"
            tip = key
            if row.get("time_ms") is not None and row.get("kind") in (
                "user",
                "screenshot",
            ):
                tip = f"{key}  ·  {int(row['time_ms'])} ms"
            decorated = {**row, "_display": display, "_tip": tip}
            kind = row.get("kind")
            if kind == "user":
                users.append(decorated)
            elif kind == "screenshot":
                shots.append(decorated)
            else:
                others.append(decorated)

        def _add_pick(row: dict, *, indent: int = 0) -> None:
            pick = _MarkerPickRow(
                row["key"],
                row["_display"],
                indent=indent,
                tip=row["_tip"],
            )
            pick.activated.connect(self._on_marker_selected)
            self._marker_list_layout.insertWidget(
                self._marker_list_layout.count() - 1, pick
            )
            self._pick_rows[row["key"]] = pick

        for row in users:
            _add_pick(row)

        if len(shots) > _SHOT_EXPAND_AT:
            group = _ScreenshotGroup(shots)
            group.activated.connect(self._on_marker_selected)
            self._marker_list_layout.insertWidget(
                self._marker_list_layout.count() - 1, group
            )
            self._shot_group = group
            for pick in group._pick_rows:
                self._pick_rows[pick._key] = pick
        else:
            for row in shots:
                _add_pick(row)

        for row in others:
            _add_pick(row)

        if prev and prev in self._pick_rows:
            self._on_marker_selected(prev)
        else:
            self._on_marker_selected(None)

    def _on_marker_selected(self, key: str | None) -> None:
        if not hasattr(self, "_mk_editor"):
            return
        self._selected_key = key or None
        for k, pick in self._pick_rows.items():
            pick.set_selected(k == self._selected_key)
        if self._shot_group is not None:
            self._shot_group.set_selected_key(self._selected_key)

        has = bool(self._selected_key)
        self._mk_empty.setVisible(not has)
        self._mk_editor.setVisible(has)
        if not has:
            return
        key = self._selected_key
        label = mprefs.friendly_marker_label(key)
        row_info = None
        for r in self._clip_rows:
            if r["key"] == key:
                label = r.get("label") or label
                row_info = r
                break
        ov = mprefs.marker_override(key, self._prefs)
        if (ov.get("label") or "").strip():
            label = ov["label"].strip()
        self._mk_id_lbl.setText(f"{label}\nID: {key}")
        self._mk_label.blockSignals(True)
        self._mk_label.setText(ov.get("label") or "")
        self._mk_label.blockSignals(False)
        self._mk_class.blockSignals(True)
        idx = self._mk_class.findData(ov.get("class_id") or "")
        self._mk_class.setCurrentIndex(max(0, idx))
        self._mk_class.blockSignals(False)
        if hasattr(self, "_mk_no_tint"):
            self._mk_no_tint.blockSignals(True)
            self._mk_no_tint.setChecked(bool(ov.get("no_tint")))
            self._mk_no_tint.setEnabled(bool(ov.get("class_id")))
            self._mk_no_tint.setVisible(True)
            self._mk_no_tint.blockSignals(False)
        self._refresh_marker_preview()
        self._refresh_screenshot_path(row_info)

    def _refresh_screenshot_path(self, row_info: dict | None) -> None:
        if not hasattr(self, "_mk_path_section"):
            return
        is_shot = bool(row_info and row_info.get("kind") == "screenshot")
        self._mk_path_section.setVisible(is_shot)
        self._shot_file_path = None
        self._shot_folder_path = None
        if not is_shot:
            self._set_shot_preview(None)
            return
        file_path, folder, note = self._resolve_screenshot_paths(row_info)
        self._shot_file_path = file_path
        self._shot_folder_path = folder
        if file_path:
            self._mk_path_lbl.setText(file_path)
            self._mk_path_open.setEnabled(True)
        else:
            self._mk_path_lbl.setText(
                note or "No matching Steam screenshot found on disk."
            )
            self._mk_path_open.setEnabled(False)
        self._mk_path_folder.setEnabled(bool(folder and os.path.isdir(folder)))
        self._set_shot_preview(file_path)

    def _set_shot_preview(self, file_path: str | None) -> None:
        if not hasattr(self, "_mk_shot_preview"):
            return
        if file_path and os.path.isfile(file_path):
            pix = load_scaled_pixmap(file_path, 64)
            if pix is not None and not pix.isNull():
                # Fit inside 120×68 box keeping aspect.
                scaled = pix.scaled(
                    116,
                    64,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._mk_shot_preview.setPixmap(scaled)
                self._mk_shot_preview.setText("")
                self._mk_shot_preview.setToolTip(file_path)
                return
        self._mk_shot_preview.clear()
        self._mk_shot_preview.setText("?")
        self._mk_shot_preview.setToolTip("")

    def _resolve_screenshot_paths(
        self, row_info: dict
    ) -> tuple[str | None, str | None, str]:
        """Quiet lookup — no modal dialogs."""
        try:
            from steempeg.core.steam_screenshots import (
                find_steam_screenshot_files,
                resolve_steam_id_for_clip,
                steam_screenshots_dir,
                timeline_json_start_utc,
            )
        except Exception:
            return None, None, "Screenshot lookup unavailable."

        canvas = getattr(
            getattr(self._app, "custom_timeline", None), "canvas", None
        )
        if canvas is None:
            return None, None, "Open a clip in the player first."

        clip_path = getattr(canvas, "current_clip_path", None) or getattr(
            self._app, "_preview_clip_path", None
        )
        app_id = getattr(canvas, "current_app_id", None) or self._app_id
        if not clip_path or not app_id:
            return None, None, "Need an open Steam Game Recording clip."

        steam_id = resolve_steam_id_for_clip(
            clip_path, getattr(self._app, "clips_folders", None) or []
        )
        if not steam_id:
            return None, None, "Could not resolve Steam user id from the clip path."

        folder = steam_screenshots_dir(steam_id, str(app_id))
        marker_ms = float(row_info.get("time_ms") or 0)
        raw_time_ms = row_info.get("raw_time_ms")
        if raw_time_ms is None:
            raw_time_ms = marker_ms + float(
                getattr(canvas, "current_offset_ms", 0) or 0
            )
        else:
            raw_time_ms = float(raw_time_ms)
        json_start_utc = getattr(canvas, "current_json_start_utc", None)
        if json_start_utc is None:
            json_start_utc = timeline_json_start_utc(
                getattr(canvas, "current_json_path", None)
            )

        files = find_steam_screenshot_files(
            steam_id=steam_id,
            app_id=str(app_id),
            json_start_utc=json_start_utc,
            raw_time_ms=raw_time_ms,
            clip_path=clip_path,
            marker_time_ms=marker_ms,
        )
        if files:
            return files[0], folder, ""
        return None, folder, f"Looked in:\n{folder}"

    def _open_selected_screenshot(self) -> None:
        path = getattr(self, "_shot_file_path", None)
        if path and os.path.isfile(path):
            reveal_in_file_manager(path)

    def _open_selected_screenshot_folder(self) -> None:
        path = getattr(self, "_shot_file_path", None)
        folder = getattr(self, "_shot_folder_path", None)
        if path and os.path.isfile(path):
            reveal_in_file_manager(path)
        elif folder and os.path.isdir(folder):
            reveal_in_file_manager(folder)

    def _refresh_marker_preview(self) -> None:
        key = self._selected_key
        if not key or not hasattr(self, "_mk_preview"):
            return
        is_user = str(key).startswith("user_") or key in (
            "usermarker",
            "steam_marker",
        )
        is_shot = str(key).startswith("shot_") or key in (
            "screenshot",
            "steam_screenshot",
        )
        tintable = is_user or is_shot
        path = mprefs.resolve_custom_icon_path(key, prefs=self._prefs)
        pix = load_scaled_pixmap(path, 40) if path else None
        if pix is None:
            if is_user:
                legacy_key = "usermarker"
            elif is_shot:
                legacy_key = "screenshot"
            else:
                legacy_key = key
            legacy = mprefs.legacy_asset_path(legacy_key)
            pix = load_scaled_pixmap(legacy, 40) if legacy else None
        if pix is None and self._app_id and not tintable:
            try:
                store = getattr(
                    getattr(
                        getattr(self._app, "custom_timeline", None), "canvas", None
                    ),
                    "marker_store",
                    None,
                )
                if store is not None:
                    pix = store.get_icon(self._app_id, key, 40)
            except Exception:
                pix = None
        tint = mprefs.resolve_tint_color(key, prefs=self._prefs)
        if pix is not None and tint and tintable:
            pix = tint_pixmap(pix, tint, height=40)
        if pix is not None:
            self._mk_preview.setPixmap(pix)
            self._mk_preview.setText("")
        else:
            self._mk_preview.clear()
            self._mk_preview.setText("?")

    def _save_marker_fields(self) -> None:
        key = self._selected_key
        if not key:
            return
        mprefs.set_marker_override(
            key,
            class_id=self._mk_class.currentData() or "",
            label=self._mk_label.text().strip(),
            no_tint=bool(
                getattr(self, "_mk_no_tint", None) and self._mk_no_tint.isChecked()
            ),
        )
        self._emit_changed()
        self._repopulate_markers()
        self._on_marker_selected(key)

    def _pick_marker_icon(self) -> None:
        key = self._selected_key
        if not key:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Marker icon", "", "Images (*.png *.jpg *.jpeg *.webp)"
        )
        if path:
            mprefs.set_marker_override(key, custom_icon=path)
            self._emit_changed()
            self._refresh_marker_preview()
            self._repopulate_markers()
            self._on_marker_selected(key)

    def _clear_marker_icon(self) -> None:
        key = self._selected_key
        if not key:
            return
        mprefs.set_marker_override(key, custom_icon="")
        self._emit_changed()
        self._refresh_marker_preview()
        self._repopulate_markers()
        self._on_marker_selected(key)

    def _reset_one_marker(self) -> None:
        key = self._selected_key
        if not key:
            return
        mprefs.reset_marker_override(key)
        self._emit_changed()
        self._repopulate_markers()
        self._on_marker_selected(key)

    def _reset_steam(self) -> None:
        if not steempeg_question(
            self,
            "Reset game markers?",
            "Removes classes/icons for kill, death, etc. Custom markers and classes stay.",
        ):
            return
        mprefs.reset_steam_marker_overrides()
        self._emit_changed()
        self._repopulate_markers()

    def _reset_all(self) -> None:
        if not steempeg_question(
            self,
            "Reset all?",
            "Deletes all classes and marker settings. The CS2 pack toggle stays. Clip JSON is untouched.",
        ):
            return
        pack = mprefs.cs2_icon_pack()
        mprefs.reset_all_marker_overrides(keep_classes=False)
        mprefs.set_cs2_icon_pack(pack)
        self._emit_changed()
        self._reload_classes()
        self._repopulate_markers()


def show_marker_settings_dialog(app) -> None:
    canvas = getattr(getattr(app, "custom_timeline", None), "canvas", None)
    app_id = getattr(canvas, "current_app_id", None) if canvas else None
    markers = list(getattr(canvas, "markers", []) or []) if canvas else []
    dlg = MarkerSettingsDialog(
        app,
        parent=getattr(app, "ui", None),
        app_id=app_id,
        clip_markers=markers,
    )

    def _on_changed():
        if canvas is not None and hasattr(canvas, "invalidate_marker_prefs_cache"):
            canvas.invalidate_marker_prefs_cache()

    dlg.prefs_changed.connect(_on_changed)
    dlg.exec()
    _on_changed()
