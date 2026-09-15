"""Marker settings — On clip / CS2 / Classes tabs."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.paths import (
    get_resource_path,
    open_path_with_default_app,
    reveal_in_file_manager,
)
from steempeg.services import marker_prefs as mprefs
from steempeg.ui import design_tokens as tok
from steempeg.ui import ui_theme as ut
from steempeg.ui.icon_utils import apply_square_icon
from steempeg.ui.marker_icons import (
    class_display_pixmap,
    class_has_custom_icon,
    load_scaled_pixmap,
    tint_pixmap,
)
from steempeg.ui.message_dialog import (
    dialog_theme,
    steempeg_information,
    steempeg_question,
)
from steempeg.ui.widgets.combo_chrome import apply_dark_combo_popup
from steempeg.ui.widgets.dialog_chrome import SteempegDialog
from steempeg.ui.widgets.overflow_marquee import OverflowMarqueeLabel
from steempeg.ui.widgets.steempeg_check import SteempegCheckBox

_SECTION = (
    f"color: {tok.TEXT_TITLE}; font-size: 13px; font-weight: bold; "
    f"background: transparent; font-family: {tok.FONT_APP};"
)
_HINT = (
    f"color: {tok.TEXT_MUTED}; font-size: 12px; background: transparent; "
    f"font-family: {tok.FONT_APP};"
)
_ICON_BTN = """
    QPushButton {
        background: transparent; border: none; color: #ccc;
        font-size: 12px; padding: 2px 6px; min-width: 22px;
    }
    QPushButton:hover { color: #fff; }
"""
_CLASS_ROW_H = 36
_CLASS_ICON = 22
_COL_ICON = 0
_COL_NAME = 1
_COL_TIME = 2
_COL_KIND = 3
_TABLE_ICON = 22
_TABLE_ROW_H = 36
_KIND_COL_W = 78
_TIME_COL_W = 56  # default ≤ 9:59; see mprefs.time_column_width_for_duration_ms


def _kind_label(kind: str) -> str:
    key = str(kind or "").strip().lower()
    if key == "user":
        return "Custom"
    if key == "screenshot":
        return "Screenshot"
    if key in ("steam", "legacy"):
        return "Game"
    return key.title() or "Marker"


class _SortableTableItem(QTableWidgetItem):
    """Numeric-aware sort via UserRole payload."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        a = self.data(Qt.ItemDataRole.UserRole + 1)
        b = other.data(Qt.ItemDataRole.UserRole + 1) if other is not None else None
        if a is not None and b is not None:
            try:
                return a < b
            except TypeError:
                pass
        return super().__lt__(other)


def _marker_tabs_stylesheet() -> str:
    p = ut.active_palette()
    tab_bg = "#2a2a2a" if p.name == ut.UI_THEME_DEFAULT else p.bg_elevated
    tab_hover = "#353535" if p.name == ut.UI_THEME_DEFAULT else p.neo_nav_hover_bg
    return f"""
    QTabWidget {{ background-color: {tok.BG_SHELL}; border: none; }}
    QTabWidget > QStackedWidget {{ background-color: {tok.BG_SHELL}; }}
    QTabWidget::pane {{
        border: 1px solid {p.border_default}; border-radius: 8px;
        background-color: {tok.BG_SHELL};
    }}
    QTabBar::tab {{
        background: {tab_bg}; color: #aaa; padding: 8px 16px; margin-right: 4px;
        border-top-left-radius: 6px; border-top-right-radius: 6px;
        font-family: {tok.FONT_APP}; font-size: 12px; font-weight: bold;
    }}
    QTabBar::tab:selected {{ background: #4a3d66; color: #fff; }}
    QTabBar::tab:hover:!selected {{ background: {tab_hover}; color: #ddd; }}
"""


def _scroll_page(inner: QWidget) -> QScrollArea:
    inner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    inner.setStyleSheet(f"background-color: {tok.BG_SHELL};")
    from steempeg.ui.library.library_styles import (
        LIBRARY_SCROLLBAR_VERTICAL,
        install_library_vertical_scrollbar,
    )

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    tok.apply_dialog_scroll_bg(scroll, tok.BG_SHELL)
    scroll.setStyleSheet(tok.dialog_scroll_stylesheet(tok.BG_SHELL) + LIBRARY_SCROLLBAR_VERTICAL)
    install_library_vertical_scrollbar(scroll)
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
        self.setMinimumSize(960, 680)
        self.resize(1080, 780)

        self._prefs = mprefs.load_marker_prefs()
        self._clip_rows = mprefs.clip_marker_setting_rows(self._clip_markers)
        self._selected_row_id: str | None = None
        self._selected_key: str | None = None
        self._list_icon_cache: dict[str, object] = {}
        self._shot_file_path: str | None = None
        self._shot_folder_path: str | None = None
        self._suppress_marker_seek = False
        # Modeless — keep player / timeline / dash clickable underneath
        # (same pattern as Desktop Render Settings).
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)

        root = self.content_layout
        root.setSpacing(10)

        from steempeg.ui.icon_assets import load_pixmap

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        from steempeg.ui.icon_utils import apply_square_icon, square_fit_pixmap

        title_icon = QLabel()
        title_pix = load_pixmap("pointuser.png", 26)
        if title_pix.isNull():
            # Fallback if icon_assets path misses the asset.
            from PySide6.QtGui import QPixmap

            raw = get_resource_path("pointuser.png")
            if os.path.isfile(raw):
                title_pix = square_fit_pixmap(QPixmap(raw), 26, dpr=1.0)
        apply_square_icon(title_icon, title_pix, 28)
        title_icon.setStyleSheet("background: transparent;")
        title_row.addWidget(title_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        title = QLabel("Marker settings")
        title.setStyleSheet(tok.STYLE_PANEL_TITLE)
        title_row.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        root.addLayout(title_row)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(_marker_tabs_stylesheet())
        self._tabs.addTab(self._build_markers_tab(), "On clip")
        if self._is_cs2_clip:
            self._tabs.addTab(self._build_cs2_tab(), "CS2")
        self._tabs.addTab(self._build_classes_tab(), "Classes")
        root.addWidget(self._tabs, 1)

        foot = QHBoxLayout()
        btn_reset_steam = QPushButton("Reset game markers")
        btn_reset_steam.setObjectName("markerFooterSecondary")
        btn_reset_steam.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset_steam.clicked.connect(self._reset_steam)
        btn_reset_all = QPushButton("Reset all")
        btn_reset_all.setObjectName("markerFooterDanger")
        btn_reset_all.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset_all.clicked.connect(self._reset_all)
        foot.addWidget(btn_reset_steam)
        foot.addWidget(btn_reset_all)
        foot.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.setObjectName("markerFooterSecondary")
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        foot.addWidget(btn_close)
        root.addLayout(foot)

        self._reload_classes()
        self._repopulate_markers()
        self._reload_class_combo()
        self._apply_marker_form_chrome()

    def apply_ui_theme_chrome(self) -> None:
        """Live-retint when Settings switches UI theme while Marker Settings is open."""
        super().apply_ui_theme_chrome()
        self._apply_marker_form_chrome()

    def _apply_marker_form_chrome(self) -> None:
        """Re-bake tabs, fields, lists, and footer actions from active tokens."""
        from steempeg.ui.library.library_styles import (
            LIBRARY_SCROLLBAR_VERTICAL,
            install_library_vertical_scrollbar,
        )

        field_qss = ut.marker_settings_field_stylesheet()
        host_qss = ut.marker_settings_list_host_stylesheet()
        class_list_qss = ut.marker_settings_class_list_stylesheet()
        preview_qss = ut.marker_settings_preview_plate_stylesheet()
        primary = ut.update_center_btn_primary_stylesheet()
        secondary = ut.settings_dialog_secondary_button_stylesheet()
        danger = ut.dialog_btn_danger_stylesheet()
        about_sec = ut.about_secondary_button_stylesheet()
        about_danger = ut.about_danger_button_stylesheet()

        if hasattr(self, "_tabs"):
            self._tabs.setStyleSheet(_marker_tabs_stylesheet())
        for scroll in self.findChildren(QScrollArea):
            inner = scroll.widget()
            if inner is not None:
                inner.setStyleSheet(f"background-color: {tok.BG_SHELL};")
            tok.apply_dialog_scroll_bg(scroll, tok.BG_SHELL)
            scroll.setStyleSheet(
                tok.dialog_scroll_stylesheet(tok.BG_SHELL) + LIBRARY_SCROLLBAR_VERTICAL
            )
            install_library_vertical_scrollbar(scroll)
        if hasattr(self, "_marker_table"):
            self._marker_table.setStyleSheet(host_qss)
            install_library_vertical_scrollbar(self._marker_table)
        if hasattr(self, "_class_list"):
            self._class_list.setStyleSheet(class_list_qss)
        for edit in self.findChildren(QLineEdit):
            edit.setStyleSheet(field_qss)
        for combo in self.findChildren(QComboBox):
            combo.setStyleSheet(field_qss)
            apply_dark_combo_popup(combo)
        for preview in (
            getattr(self, "_mk_preview", None),
            getattr(self, "_mk_shot_preview", None),
        ):
            if preview is not None:
                extra = " color: #888;" if preview is getattr(self, "_mk_shot_preview", None) else ""
                preview.setStyleSheet(preview_qss + extra)
        from steempeg.ui.window_chrome import _TrafficLight

        for btn in self.findChildren(QPushButton):
            # Title-bar traffic lights are QPushButtons — never restyle them as
            # form buttons (idle becomes a gray square; they paint the disc).
            if isinstance(btn, _TrafficLight):
                btn.update()
                continue
            if btn.styleSheet().strip() == _ICON_BTN.strip():
                continue
            name = (btn.objectName() or "").strip()
            if name == "markerFooterSecondary":
                btn.setStyleSheet(about_sec)
                continue
            if name == "markerFooterDanger":
                btn.setStyleSheet(about_danger)
                continue
            label = (btn.text() or "").strip().lower()
            if label in ("close", "+ create"):
                btn.setStyleSheet(primary)
            elif (
                "delete" in label
                or label == "reset all"
                or label == "remove"
                or label.startswith("reset this")
            ):
                btn.setStyleSheet(danger)
            else:
                btn.setStyleSheet(secondary)

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

        row = QHBoxLayout()
        row.setSpacing(12)

        left = QVBoxLayout()
        left.addWidget(self._section("Class list"))
        self._class_list = QListWidget()
        self._class_list.setObjectName("markerClassList")
        self._class_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._class_list.setSelectionRectVisible(True)
        self._class_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._class_list.customContextMenuRequested.connect(self._class_context_menu)
        self._class_list.setMinimumWidth(200)
        self._class_list.setMinimumHeight(220)
        self._class_list.setSpacing(0)
        self._class_list.currentRowChanged.connect(self._on_class_row)
        self._class_list.itemSelectionChanged.connect(self._on_class_selection_changed)
        left.addWidget(self._class_list, 1)
        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Create")
        btn_add.clicked.connect(self._add_class)
        btn_del = QPushButton("Delete")
        btn_del.clicked.connect(self._delete_class)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_del)
        left.addLayout(btn_row)
        row.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(8)

        self._cls_editor = QWidget()
        ed = QVBoxLayout(self._cls_editor)
        ed.setContentsMargins(0, 0, 0, 0)
        ed.setSpacing(8)
        ed.addWidget(self._section("Class editor"))

        ed.addWidget(QLabel("Name"))
        self._cls_name = QLineEdit()
        self._cls_name.setPlaceholderText("e.g. Clutches")
        self._cls_name.editingFinished.connect(self._save_class_fields)
        ed.addWidget(self._cls_name)

        color_row = QHBoxLayout()
        self._cls_color_btn = QPushButton("Pick color…")
        self._cls_color_btn.clicked.connect(self._pick_class_color)
        self._cls_color_swatch = QLabel()
        self._cls_color_swatch.setFixedSize(32, 32)
        self._cls_color_clear = QPushButton("No color")
        self._cls_color_clear.setToolTip(
            "Group-only class — members keep default colors (no tint)."
        )
        self._cls_color_clear.clicked.connect(self._clear_class_color)
        color_row.addWidget(self._cls_color_btn)
        color_row.addWidget(self._cls_color_swatch)
        color_row.addWidget(self._cls_color_clear)
        color_row.addStretch(1)
        ed.addWidget(QLabel("Marker color (optional)"))
        ed.addLayout(color_row)

        icon_row = QHBoxLayout()
        self._cls_icon_btn = QPushButton("Class icon…")
        self._cls_icon_btn.clicked.connect(self._pick_class_icon)
        self._cls_icon_clear = QPushButton("Remove")
        self._cls_icon_clear.clicked.connect(self._clear_class_icon)
        icon_row.addWidget(self._cls_icon_btn)
        icon_row.addWidget(self._cls_icon_clear)
        ed.addWidget(QLabel("Icon (optional)"))
        ed.addLayout(icon_row)
        ed.addStretch(1)

        right.addWidget(self._cls_editor, 1)
        row.addLayout(right, 2)
        lay.addLayout(row, 1)
        self._clear_class_editor()
        return _scroll_page(page)

    def _build_markers_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        if not self._clip_rows:
            empty = QLabel("List is empty")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(
                f"color: {tok.TEXT_MUTED}; font-size: 13px; background: transparent; "
                f"font-family: {tok.FONT_APP};"
            )
            lay.addStretch(1)
            lay.addWidget(empty)
            lay.addStretch(2)
            return _scroll_page(page)

        row = QHBoxLayout()
        row.setSpacing(12)

        left = QVBoxLayout()
        left.addWidget(self._section("Markers on clip"))
        self._marker_table = QTableWidget(0, 4)
        self._marker_table.setObjectName("markerOnClipTable")
        self._marker_table.setHorizontalHeaderLabels(["", "Name", "Time", "Kind"])
        self._marker_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._marker_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._marker_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._marker_table.setAlternatingRowColors(False)
        self._marker_table.setShowGrid(False)
        self._marker_table.setWordWrap(False)
        self._marker_table.setIconSize(QSize(_TABLE_ICON, _TABLE_ICON))
        self._marker_table.verticalHeader().setVisible(False)
        self._marker_table.verticalHeader().setDefaultSectionSize(_TABLE_ROW_H)
        self._marker_table.setSortingEnabled(True)
        hdr = self._marker_table.horizontalHeader()
        hdr.setSectionsClickable(True)
        hdr.setSortIndicatorShown(True)
        hdr.setMinimumSectionSize(28)
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(_COL_ICON, QHeaderView.ResizeMode.Fixed)
        self._marker_table.setColumnWidth(_COL_ICON, 40)
        hdr.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(_COL_TIME, QHeaderView.ResizeMode.Fixed)
        self._marker_table.setColumnWidth(_COL_TIME, _TIME_COL_W)
        hdr.setSectionResizeMode(_COL_KIND, QHeaderView.ResizeMode.Fixed)
        self._marker_table.setColumnWidth(_COL_KIND, _KIND_COL_W)
        self._marker_table.setMinimumWidth(280)
        self._marker_table.setMinimumHeight(240)
        self._marker_table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._marker_table.customContextMenuRequested.connect(
            self._on_marker_table_context_menu
        )
        self._marker_table.itemSelectionChanged.connect(self._on_marker_table_selection)
        self._marker_table.itemDoubleClicked.connect(self._on_marker_table_double_clicked)
        self._apply_time_column_width()
        left.addWidget(self._marker_table, 1)
        row.addLayout(left, 2)

        right = QVBoxLayout()
        right.setSpacing(8)

        self._mk_editor = QWidget()
        ed = QVBoxLayout(self._mk_editor)
        ed.setContentsMargins(0, 0, 0, 0)
        ed.setSpacing(8)
        ed.addWidget(self._section("Selected marker"))

        prev_row = QHBoxLayout()
        self._mk_preview = QLabel()
        self._mk_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        apply_square_icon(self._mk_preview, None, 48)
        self._mk_id_lbl = QLabel("")
        self._mk_id_lbl.setWordWrap(True)
        self._mk_id_lbl.setStyleSheet(
            _HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY)
        )
        prev_row.addWidget(self._mk_preview)
        prev_row.addWidget(self._mk_id_lbl, 1)
        ed.addLayout(prev_row)

        ed.addWidget(QLabel("Name"))
        self._mk_label = QLineEdit()
        self._mk_label.setPlaceholderText("Display name")
        self._mk_label.editingFinished.connect(self._save_marker_fields)
        ed.addWidget(self._mk_label)

        ed.addWidget(QLabel("Description"))
        self._mk_description = QLineEdit()
        self._mk_description.setPlaceholderText("Optional notes")
        self._mk_description.editingFinished.connect(self._save_marker_fields)
        ed.addWidget(self._mk_description)

        ed.addWidget(QLabel("Class"))
        self._mk_class = QComboBox()
        apply_dark_combo_popup(self._mk_class)
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
        self._mk_icon_btn.clicked.connect(self._pick_marker_icon)
        self._mk_icon_clear = QPushButton("Remove")
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
        self._mk_path_open.clicked.connect(self._open_selected_screenshot)
        self._mk_path_folder = QPushButton("Open folder")
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

        self._mk_reset_btn = QPushButton("Reset this marker")
        self._mk_reset_btn.clicked.connect(self._reset_one_marker)
        ed.addWidget(self._mk_reset_btn)
        ed.addStretch(1)

        right.addWidget(self._mk_editor, 1)
        row.addLayout(right, 3)
        lay.addLayout(row, 1)
        self._clear_marker_editor()
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

    def showEvent(self, event) -> None:
        _dismiss_timeline_hover_tools(self._app)
        super().showEvent(event)

    def enterEvent(self, event) -> None:
        _dismiss_timeline_hover_tools(self._app)
        super().enterEvent(event)

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
        for cls in mprefs.classes_for_app(self._app_id, self._prefs):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, cls.get("id"))
            item.setSizeHint(QSize(180, _CLASS_ROW_H))
            self._class_list.addItem(item)
            self._class_list.setItemWidget(item, self._make_class_row_widget(cls))
        self._class_list.blockSignals(False)
        if prev_id:
            for i in range(self._class_list.count()):
                it = self._class_list.item(i)
                if it and it.data(Qt.ItemDataRole.UserRole) == prev_id:
                    self._class_list.setCurrentRow(i)
                    break
        if self._class_list.currentRow() < 0:
            self._clear_class_editor()
        else:
            self._on_class_row(self._class_list.currentRow())
        self._reload_class_combo()

    def _make_class_row_widget(self, cls: dict) -> QWidget:
        row = QWidget()
        row.setFixedHeight(_CLASS_ROW_H)
        row.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(8, 0, 10, 0)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        icon_lbl = QLabel()
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        pix = class_display_pixmap(cls, height=_CLASS_ICON)
        apply_square_icon(icon_lbl, pix, _CLASS_ICON)
        lay.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        name_lbl = QLabel(str(cls.get("name") or "Class"))
        name_lbl.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        name_lbl.setStyleSheet(
            f"color: {tok.TEXT_PRIMARY}; font-size: 13px; background: transparent; "
            f"font-family: {tok.FONT_APP};"
        )
        lay.addWidget(name_lbl, 1, Qt.AlignmentFlag.AlignVCenter)

        if not class_has_custom_icon(cls):
            color = str(cls.get("color") or "").strip()
            if color:
                color_lbl = QLabel(color)
                color_lbl.setAlignment(
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
                )
                color_lbl.setStyleSheet(
                    f"color: {tok.TEXT_MUTED}; font-size: 11px; background: transparent; "
                    f"font-family: {tok.FONT_APP};"
                )
                lay.addWidget(color_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
            else:
                mute = QLabel("no color")
                mute.setAlignment(
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
                )
                mute.setStyleSheet(
                    f"color: {tok.TEXT_MUTED}; font-size: 11px; background: transparent; "
                    f"font-family: {tok.FONT_APP}; font-style: italic;"
                )
                lay.addWidget(mute, 0, Qt.AlignmentFlag.AlignVCenter)

        return row

    def _reload_class_combo(self) -> None:
        if not hasattr(self, "_mk_class"):
            return
        self._mk_class.blockSignals(True)
        cur = self._mk_class.currentData()
        keep: set[str] = set()
        if cur:
            keep.add(str(cur))
        key = getattr(self, "_selected_key", None)
        if key:
            ov = mprefs.marker_override(str(key), self._prefs)
            cid = str(ov.get("class_id") or "")
            if cid:
                keep.add(cid)
        self._mk_class.clear()
        self._mk_class.addItem("— no class —", "")
        for cls in mprefs.classes_for_app(
            self._app_id, self._prefs, include_ids=keep or None
        ):
            self._mk_class.addItem(str(cls.get("name")), cls.get("id"))
        if cur:
            idx = self._mk_class.findData(cur)
            if idx >= 0:
                self._mk_class.setCurrentIndex(idx)
        self._mk_class.blockSignals(False)

    def _current_class_id(self) -> str | None:
        item = self._class_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _set_class_editor_enabled(self, enabled: bool) -> None:
        for w in (
            self._cls_name,
            self._cls_color_btn,
            self._cls_color_clear,
            self._cls_icon_btn,
            self._cls_icon_clear,
        ):
            w.setEnabled(enabled)

    def _clear_class_editor(self) -> None:
        self._cls_name.blockSignals(True)
        self._cls_name.clear()
        self._cls_name.blockSignals(False)
        self._cls_color_swatch.setStyleSheet(
            "background: transparent; border-radius: 6px; border: 1px dashed #666;"
        )
        self._cls_color_swatch.setToolTip("")
        self._set_class_editor_enabled(False)

    def _on_class_row(self, row: int) -> None:
        if row < 0:
            self._clear_class_editor()
            return
        cid = self._current_class_id()
        cls = mprefs.get_class(cid, self._prefs)
        if not cls:
            self._clear_class_editor()
            return
        self._set_class_editor_enabled(True)
        self._cls_name.blockSignals(True)
        self._cls_name.setText(str(cls.get("name") or ""))
        self._cls_name.blockSignals(False)
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
        if not str(self._app_id or "").strip():
            steempeg_information(
                self,
                "No game on this clip",
                "Open a clip with a known Steam game first — classes are saved "
                "per game (e.g. CS2), not for every clip.",
            )
            return
        mprefs.create_class("New class", app_id=self._app_id)
        self._emit_changed()
        self._reload_classes()
        self._class_list.setCurrentRow(self._class_list.count() - 1)
        self._on_class_row(self._class_list.currentRow())

    def _selected_class_ids(self) -> list[str]:
        ids: list[str] = []
        for item in self._class_list.selectedItems():
            cid = item.data(Qt.ItemDataRole.UserRole)
            if cid:
                ids.append(str(cid))
        return ids

    def _on_class_selection_changed(self) -> None:
        # Keep editor on the current (focused) row within a multi-selection.
        row = self._class_list.currentRow()
        if row < 0:
            self._clear_class_editor()
        else:
            self._on_class_row(row)

    def _class_context_menu(self, pos) -> None:
        item = self._class_list.itemAt(pos)
        if item is None:
            return
        if item not in self._class_list.selectedItems():
            self._class_list.setCurrentItem(item)
        menu = QMenu(self)
        menu.setStyleSheet(ut.library_menu_stylesheet())
        act_dup = self._add_dup_del_action(menu, "Duplicate", kind="duplicate")
        act_del = self._add_dup_del_action(menu, "Delete", kind="delete")
        chosen = menu.exec(self._class_list.mapToGlobal(pos))
        if chosen is act_dup:
            self._duplicate_selected_classes()
        elif chosen is act_del:
            self._delete_class()

    def _duplicate_selected_classes(self) -> None:
        ids = self._selected_class_ids()
        if not ids:
            return
        last = None
        for cid in ids:
            last = mprefs.duplicate_class(cid)
        self._emit_changed()
        self._reload_classes()
        if last and last.get("id"):
            target = str(last["id"])
            for i in range(self._class_list.count()):
                it = self._class_list.item(i)
                if it and it.data(Qt.ItemDataRole.UserRole) == target:
                    self._class_list.setCurrentRow(i)
                    break

    def _delete_class(self) -> None:
        ids = self._selected_class_ids()
        if not ids:
            return
        for cid in ids:
            mprefs.delete_class(cid)
        self._emit_changed()
        self._reload_classes()

    def keyPressEvent(self, event):
        if (
            event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
            and hasattr(self, "_class_list")
            and self._class_list.hasFocus()
            and self._selected_class_ids()
        ):
            self._delete_class()
            event.accept()
            return
        super().keyPressEvent(event)

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

    def _row_by_id(self, row_id: str | None) -> dict | None:
        if not row_id:
            return None
        for r in self._clip_rows:
            if (r.get("row_id") or r["key"]) == row_id:
                return r
        return None

    def _canvas(self):
        return getattr(getattr(self._app, "custom_timeline", None), "canvas", None)

    def _clip_duration_ms(self) -> int:
        canvas = self._canvas()
        dur = int(getattr(canvas, "duration_ms", 0) or 0) if canvas is not None else 0
        if dur > 0:
            return dur
        times = [
            int(m.get("time_ms") or 0)
            for m in (self._clip_markers or [])
            if m.get("time_ms") is not None
        ]
        return max(times) if times else 0

    def _apply_time_column_width(self) -> None:
        if not hasattr(self, "_marker_table"):
            return
        w = mprefs.time_column_width_for_duration_ms(self._clip_duration_ms())
        self._marker_table.setColumnWidth(_COL_TIME, w)

    def _sync_clip_markers_from_canvas(self) -> None:
        canvas = self._canvas()
        if canvas is None:
            return
        self._clip_markers = list(getattr(canvas, "markers", []) or [])
        self._clip_rows = mprefs.clip_marker_setting_rows(self._clip_markers)
        self._prefs = mprefs.load_marker_prefs()
        self._apply_time_column_width()
        self._repopulate_markers()

    def _canvas_marker_for_row(self, row_info: dict | None) -> dict | None:
        if not row_info:
            return None
        canvas = self._canvas()
        if canvas is None:
            return None
        mid = str(row_info.get("marker_id") or "")
        for m in getattr(canvas, "markers", []) or []:
            if mid and str(m.get("id") or "") == mid:
                return m
            if mprefs.is_user_marker(m):
                key = mprefs.user_instance_prefs_key(
                    m.get("id"), time_ms=m.get("time_ms")
                )
                if key == row_info.get("key"):
                    return m
        return None

    def _selected_marker_row_info(self) -> dict | None:
        return self._row_by_id(self._selected_row_id)

    def _on_marker_table_context_menu(self, pos) -> None:
        table = self._marker_table
        item = table.itemAt(pos)
        if item is None:
            return
        row = item.row()
        # Select the row under the cursor (same feel as Classes list).
        id_item = table.item(row, _COL_ICON) or table.item(row, _COL_TIME)
        row_id = id_item.data(Qt.ItemDataRole.UserRole) if id_item else None
        if row_id:
            self._select_marker_row_id(str(row_id), seek=False)
        row_info = self._row_by_id(str(row_id) if row_id else None)
        if not row_info:
            return

        is_user = str(row_info.get("kind") or "") == "user"
        if not is_user:
            return

        menu = QMenu(self)
        menu.setStyleSheet(ut.library_menu_stylesheet())
        act_dup = self._add_dup_del_action(menu, "Duplicate", kind="duplicate")
        act_del = self._add_dup_del_action(menu, "Delete", kind="delete")
        chosen = menu.exec(table.viewport().mapToGlobal(pos))
        if chosen is act_dup:
            self._duplicate_on_clip_marker(row_info)
        elif chosen is act_del:
            self._delete_on_clip_marker(row_info)

    @staticmethod
    def _add_dup_del_action(menu: QMenu, label: str, *, kind: str):
        """Emoji-in-text like ClipCard — QIcon on one row alone makes a huge left gutter."""
        if kind == "duplicate":
            return menu.addAction(f"📋  {label}")
        return menu.addAction(f"🗑️  {label}")

    def _delete_on_clip_marker(self, row_info: dict) -> None:
        canvas = self._canvas()
        marker = self._canvas_marker_for_row(row_info)
        if canvas is None or marker is None:
            return
        if not mprefs.is_user_marker(marker):
            return
        if hasattr(canvas, "delete_user_marker"):
            canvas.delete_user_marker(marker)
        self._sync_clip_markers_from_canvas()
        self._emit_changed()

    def _duplicate_on_clip_marker(self, row_info: dict) -> None:
        app = self._app
        if app is None or not hasattr(app, "duplicate_user_marker"):
            return
        src = self._canvas_marker_for_row(row_info)
        if src is None:
            return
        new_marker = app.duplicate_user_marker(src, parent=self)
        self._sync_clip_markers_from_canvas()
        self._emit_changed()
        if not new_marker:
            return
        for r in self._clip_rows:
            if str(r.get("marker_id") or "") == str(new_marker.get("id") or ""):
                self._select_marker_row_id(
                    r.get("row_id") or r.get("key"), seek=False
                )
                break

    def select_canvas_marker(self, marker: dict | None) -> None:
        """Focus On clip on the timeline pin (stock / custom / screenshot)."""
        if not marker:
            return
        self._sync_clip_markers_from_canvas()
        row_id = mprefs.row_id_for_canvas_marker(marker)
        if hasattr(self, "_tabs"):
            self._tabs.setCurrentIndex(0)
        if not row_id or not hasattr(self, "_marker_table"):
            return
        self._select_marker_row_id(row_id, seek=False)

    def _list_icon_for_row(self, row: dict):
        """Resolve a small pixmap for an On clip list row (cached by prefs key)."""
        key = str(row.get("key") or "")
        kind = str(row.get("kind") or "")
        cache_key = f"{kind}:{key}"
        if cache_key in self._list_icon_cache:
            return self._list_icon_cache[cache_key]

        pix = None
        path = mprefs.resolve_custom_icon_path(key, prefs=self._prefs)
        if path:
            pix = load_scaled_pixmap(path, _CLASS_ICON)
        if pix is None:
            if kind == "user":
                legacy_key = "usermarker"
            elif kind == "screenshot":
                legacy_key = "screenshot"
            else:
                legacy_key = str(row.get("icon_key") or key)
            legacy = mprefs.legacy_asset_path(legacy_key)
            if legacy:
                pix = load_scaled_pixmap(legacy, _CLASS_ICON)
        if pix is None and kind in ("steam", "legacy") and self._app_id:
            try:
                store = getattr(
                    getattr(
                        getattr(self._app, "custom_timeline", None), "canvas", None
                    ),
                    "marker_store",
                    None,
                )
                steam_id = str(row.get("icon") or key)
                if store is not None and steam_id:
                    pix = store.get_icon(self._app_id, steam_id, _CLASS_ICON)
            except Exception:
                pix = None

        tintable = kind in ("user", "screenshot")
        tint = mprefs.resolve_tint_color(key, prefs=self._prefs)
        if pix is not None and tint and tintable:
            pix = tint_pixmap(pix, tint, height=_CLASS_ICON)

        self._list_icon_cache[cache_key] = pix
        return pix

    def _repopulate_markers(self) -> None:
        if not hasattr(self, "_marker_table"):
            return
        prev = self._selected_row_id
        self._suppress_marker_seek = True
        self._marker_table.blockSignals(True)
        self._marker_table.setSortingEnabled(False)
        self._marker_table.setRowCount(0)
        self._list_icon_cache = {}
        self._apply_time_column_width()

        for row in self._clip_rows:
            row_id = row.get("row_id") or row["key"]
            key = row["key"]
            ov = mprefs.marker_override(key, self._prefs)
            name = (ov.get("label") or "").strip() or row["label"]
            time_ms = row.get("time_ms")
            tc = (
                mprefs.format_marker_timecode(time_ms)
                if time_ms is not None
                else "—"
            )
            kind = _kind_label(str(row.get("kind") or ""))
            tip = key
            if time_ms is not None:
                tip = f"{key}  ·  {int(time_ms)} ms"

            r = self._marker_table.rowCount()
            self._marker_table.insertRow(r)
            self._marker_table.setRowHeight(r, _TABLE_ROW_H)

            icon_item = _SortableTableItem("")
            pix = self._list_icon_for_row(row)
            if pix is not None and not pix.isNull():
                icon_item.setIcon(QIcon(pix))
            icon_item.setData(Qt.ItemDataRole.UserRole, row_id)
            icon_item.setData(Qt.ItemDataRole.UserRole + 1, kind.lower())
            icon_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_item.setToolTip(tip)

            time_item = _SortableTableItem(tc)
            time_item.setData(Qt.ItemDataRole.UserRole, row_id)
            sort_ms = int(time_ms) if time_ms is not None else 10**15
            time_item.setData(Qt.ItemDataRole.UserRole + 1, sort_ms)
            time_item.setToolTip(tip)

            kind_item = _SortableTableItem(kind)
            kind_item.setData(Qt.ItemDataRole.UserRole, row_id)
            kind_item.setData(Qt.ItemDataRole.UserRole + 1, kind.lower())
            kind_item.setToolTip(tip)

            # Display text lives in the marquee cell widget; item keeps sort key.
            name_item = _SortableTableItem("")
            name_item.setData(Qt.ItemDataRole.UserRole, row_id)
            name_item.setData(Qt.ItemDataRole.UserRole + 1, name.lower())
            name_item.setToolTip(tip)

            self._marker_table.setItem(r, _COL_ICON, icon_item)
            self._marker_table.setItem(r, _COL_NAME, name_item)
            self._marker_table.setItem(r, _COL_TIME, time_item)
            self._marker_table.setItem(r, _COL_KIND, kind_item)
            self._marker_table.setCellWidget(
                r, _COL_NAME, self._make_name_marquee(name)
            )

        self._marker_table.setSortingEnabled(True)
        self._marker_table.sortItems(_COL_TIME, Qt.SortOrder.AscendingOrder)
        self._marker_table.blockSignals(False)
        self._sync_name_marquee_selection()

        if prev:
            self._select_marker_row_id(prev, seek=False)
        else:
            self._on_marker_selected(None)
        self._suppress_marker_seek = False

    @staticmethod
    def _name_marquee_stylesheet(*, selected: bool) -> str:
        color = "#ffffff" if selected else "#d1d1d1"
        return (
            f"background: transparent; border: none; padding: 0 2px; "
            f"color: {color}; font-size: 13px; font-family: {tok.FONT_APP};"
        )

    def _make_name_marquee(self, text: str) -> OverflowMarqueeLabel:
        marquee = OverflowMarqueeLabel(
            text, align=Qt.AlignmentFlag.AlignHCenter
        )
        marquee.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        marquee.setStyleSheet(self._name_marquee_stylesheet(selected=False))
        return marquee

    def _sync_name_marquee_selection(self) -> None:
        if not hasattr(self, "_marker_table"):
            return
        selected_rows: set[int] = set()
        sm = self._marker_table.selectionModel()
        if sm is not None:
            selected_rows = {idx.row() for idx in sm.selectedRows()}
        for r in range(self._marker_table.rowCount()):
            w = self._marker_table.cellWidget(r, _COL_NAME)
            if isinstance(w, OverflowMarqueeLabel):
                w.setStyleSheet(
                    self._name_marquee_stylesheet(selected=(r in selected_rows))
                )

    def _select_marker_row_id(self, row_id: str | None, *, seek: bool = False) -> None:
        if not hasattr(self, "_marker_table") or not row_id:
            self._on_marker_selected(None)
            return
        for r in range(self._marker_table.rowCount()):
            item = self._marker_table.item(r, _COL_TIME)
            if item and item.data(Qt.ItemDataRole.UserRole) == row_id:
                self._marker_table.blockSignals(True)
                self._marker_table.selectRow(r)
                self._marker_table.blockSignals(False)
                self._sync_name_marquee_selection()
                self._on_marker_selected(row_id)
                if seek:
                    row_info = self._row_by_id(row_id)
                    if row_info:
                        self._seek_player_to_ms(row_info.get("time_ms"))
                return
        self._on_marker_selected(None)

    def _on_marker_table_selection(self) -> None:
        items = self._marker_table.selectedItems()
        self._sync_name_marquee_selection()
        if not items:
            self._on_marker_selected(None)
            return
        row_id = items[0].data(Qt.ItemDataRole.UserRole)
        self._on_marker_selected(str(row_id) if row_id else None)

    def _on_marker_table_double_clicked(self, item) -> None:
        """Double-click seeks the player timeline; single click only fills the editor."""
        if item is None:
            return
        row_id = item.data(Qt.ItemDataRole.UserRole)
        row_info = self._row_by_id(str(row_id) if row_id else None)
        if not row_info:
            return
        self._seek_player_to_ms(row_info.get("time_ms"))

    def _seek_player_to_ms(self, time_ms) -> None:
        if time_ms is None or self._suppress_marker_seek:
            return
        try:
            ms = int(time_ms)
        except (TypeError, ValueError):
            return
        timeline = getattr(self._app, "custom_timeline", None)
        if timeline is not None and hasattr(timeline, "force_jump"):
            timeline.force_jump(ms)

    def _set_marker_editor_enabled(self, enabled: bool) -> None:
        for w in (
            self._mk_label,
            self._mk_description,
            self._mk_class,
            self._mk_no_tint,
            self._mk_icon_btn,
            self._mk_icon_clear,
            self._mk_reset_btn,
            self._mk_path_open,
            self._mk_path_folder,
        ):
            w.setEnabled(enabled)

    def _clear_marker_editor(self) -> None:
        self._selected_row_id = None
        self._selected_key = None
        self._mk_id_lbl.setText("")
        self._mk_label.blockSignals(True)
        self._mk_label.clear()
        self._mk_label.blockSignals(False)
        if hasattr(self, "_mk_description"):
            self._mk_description.blockSignals(True)
            self._mk_description.clear()
            self._mk_description.blockSignals(False)
        self._mk_class.blockSignals(True)
        self._mk_class.setCurrentIndex(0)
        self._mk_class.blockSignals(False)
        if hasattr(self, "_mk_no_tint"):
            self._mk_no_tint.blockSignals(True)
            self._mk_no_tint.setChecked(False)
            self._mk_no_tint.blockSignals(False)
        apply_square_icon(self._mk_preview, None, 48)
        self._mk_preview.setText("")
        self._mk_path_section.hide()
        self._set_shot_preview(None)
        self._mk_path_lbl.setText("")
        self._set_marker_editor_enabled(False)

    def _on_marker_selected(self, row_id: str | None) -> None:
        if not hasattr(self, "_mk_editor"):
            return
        self._selected_row_id = row_id or None
        row_info = self._row_by_id(self._selected_row_id)
        self._selected_key = row_info["key"] if row_info else None

        if not self._selected_key or not row_info:
            self._clear_marker_editor()
            return

        self._set_marker_editor_enabled(True)
        key = self._selected_key
        label = row_info.get("label") or mprefs.friendly_marker_label(key)
        ov = mprefs.marker_override(key, self._prefs)
        if (ov.get("label") or "").strip():
            label = ov["label"].strip()
        tc = ""
        if row_info.get("time_ms") is not None:
            tc = mprefs.format_marker_timecode(row_info.get("time_ms"))
        id_line = f"{label}"
        if tc:
            id_line = f"{label}  ·  {tc}"
        self._mk_id_lbl.setText(f"{id_line}\nID: {key}")

        if hasattr(self, "_mk_reset_btn"):
            if row_info.get("shared_type"):
                self._mk_reset_btn.setText("Reset this type")
            else:
                self._mk_reset_btn.setText("Reset this marker")

        self._mk_label.blockSignals(True)
        # Prefs label wins; else canvas title so Settings matches the pin.
        self._mk_label.setText(
            (ov.get("label") or "").strip()
            or str(row_info.get("title") or "").strip()
        )
        self._mk_label.blockSignals(False)
        if hasattr(self, "_mk_description"):
            self._mk_description.blockSignals(True)
            canvas_desc = ""
            live = self._canvas_marker_for_row(row_info)
            if live is not None:
                canvas_desc = str(live.get("desc") or "").strip()
            self._mk_description.setText(
                (ov.get("description") or "").strip() or canvas_desc
            )
            self._mk_description.blockSignals(False)
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
            open_path_with_default_app(path)

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
        apply_square_icon(self._mk_preview, pix, 48)
        if pix is not None:
            self._mk_preview.setText("")
        else:
            self._mk_preview.setText("?")

    def _save_marker_fields(self) -> None:
        key = self._selected_key
        row_id = self._selected_row_id
        if not key:
            return
        label = self._mk_label.text().strip()
        description = (
            self._mk_description.text().strip()
            if hasattr(self, "_mk_description")
            else ""
        )
        mprefs.set_marker_override(
            key,
            class_id=self._mk_class.currentData() or "",
            label=label,
            description=description,
            no_tint=bool(
                getattr(self, "_mk_no_tint", None) and self._mk_no_tint.isChecked()
            ),
        )
        # Keep live canvas + clip cache in sync with prefs (Edit Marker used to
        # read only title/desc and drift apart from Marker Settings).
        row_info = self._selected_marker_row_info()
        marker = self._canvas_marker_for_row(row_info)
        if marker is not None and mprefs.is_user_marker(marker):
            marker["title"] = label
            marker["desc"] = description
            canvas = self._canvas()
            if canvas is not None:
                if hasattr(canvas, "text_tooltip"):
                    canvas.text_tooltip.hide()
                canvas.update()
                try:
                    from steempeg.core.clip_markers_cache import (
                        update_user_marker_fields,
                    )

                    update_user_marker_fields(
                        getattr(canvas, "_markers_cache_dir", None),
                        marker,
                        clip_path=getattr(canvas, "current_clip_path", None),
                        json_path=getattr(canvas, "current_json_path", None),
                    )
                except Exception:
                    pass
        self._emit_changed()
        self._repopulate_markers()
        self._select_marker_row_id(row_id, seek=False)

    def _pick_marker_icon(self) -> None:
        key = self._selected_key
        row_id = self._selected_row_id
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
            self._select_marker_row_id(row_id, seek=False)

    def _clear_marker_icon(self) -> None:
        key = self._selected_key
        row_id = self._selected_row_id
        if not key:
            return
        mprefs.set_marker_override(key, custom_icon="")
        self._emit_changed()
        self._refresh_marker_preview()
        self._repopulate_markers()
        self._select_marker_row_id(row_id, seek=False)

    def _reset_one_marker(self) -> None:
        key = self._selected_key
        row_id = self._selected_row_id
        if not key:
            return
        mprefs.reset_marker_override(key)
        self._emit_changed()
        self._repopulate_markers()
        self._select_marker_row_id(row_id, seek=False)

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


def _dismiss_timeline_hover_tools(app) -> None:
    """Drop strip preview/tip so they cannot float over Marker Settings."""
    tl = getattr(app, "custom_timeline", None)
    canvas = getattr(tl, "canvas", None) if tl is not None else None
    if canvas is not None and hasattr(canvas, "dismiss_hover_tools"):
        try:
            canvas.dismiss_hover_tools()
            return
        except RuntimeError:
            pass
    if canvas is not None:
        try:
            if hasattr(canvas, "_hide_hover_preview"):
                canvas._hide_hover_preview()
            tip = getattr(canvas, "text_tooltip", None)
            if tip is not None:
                tip.hide()
        except RuntimeError:
            pass


def show_marker_settings_dialog(app, *, select_marker=None) -> None:
    """Open Marker Settings modeless so the player underneath stays usable.

    ``select_marker`` — optional live timeline marker dict; focuses that On clip row.
    """
    _dismiss_timeline_hover_tools(app)
    existing = getattr(app, "_marker_settings_dlg", None)
    if existing is not None:
        try:
            if existing.isVisible():
                # Empty-on-open shell has no table — rebuild if we need a row.
                if select_marker is not None and not hasattr(
                    existing, "_marker_table"
                ):
                    existing.close()
                else:
                    if select_marker is not None:
                        existing.select_canvas_marker(select_marker)
                    elif hasattr(existing, "_sync_clip_markers_from_canvas"):
                        existing._sync_clip_markers_from_canvas()
                    existing.raise_()
                    existing.activateWindow()
                    return
        except RuntimeError:
            pass
        app._marker_settings_dlg = None

    canvas = getattr(getattr(app, "custom_timeline", None), "canvas", None)
    app_id = getattr(canvas, "current_app_id", None) if canvas else None
    markers = list(getattr(canvas, "markers", []) or []) if canvas else []
    dlg = MarkerSettingsDialog(
        app,
        parent=getattr(app, "ui", None),
        app_id=app_id,
        clip_markers=markers,
    )
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    app._marker_settings_dlg = dlg

    def _on_changed():
        live = getattr(getattr(app, "custom_timeline", None), "canvas", None)
        if live is not None and hasattr(live, "invalidate_marker_prefs_cache"):
            live.invalidate_marker_prefs_cache()

    def _on_finished(*_args):
        if getattr(app, "_marker_settings_dlg", None) is dlg:
            app._marker_settings_dlg = None
        _on_changed()

    dlg.prefs_changed.connect(_on_changed)
    dlg.finished.connect(_on_finished)
    dlg.show()
    if select_marker is not None:
        dlg.select_canvas_marker(select_marker)
