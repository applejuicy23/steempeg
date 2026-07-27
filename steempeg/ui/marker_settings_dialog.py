"""Marker settings — CS2 / Classes / On clip tabs."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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

from steempeg.services import marker_prefs as mprefs
from steempeg.ui import design_tokens as tok
from steempeg.ui.marker_icons import load_scaled_pixmap, tint_pixmap
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
    QListWidget::item { padding: 8px 10px; }
    QListWidget::item:selected { background-color: #4a3d66; }
    QListWidget::item:hover { background-color: #333; }
"""
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
        super().__init__("Marker settings", parent, **theme_kwargs)
        self._app = app
        self._app_id = str(app_id or "") or None
        self._clip_markers = list(clip_markers or [])
        self._is_cs2_clip = str(self._app_id or "") == mprefs.CS2_APP_ID
        self.setMinimumSize(680, 520)
        self.resize(720, 560)

        self._prefs = mprefs.load_marker_prefs()
        self._clip_rows = mprefs.clip_marker_setting_rows(self._clip_markers)
        self._selected_key: str | None = None

        root = self.content_layout
        root.setSpacing(10)

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
        intro.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
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
        color_row.addWidget(self._cls_color_btn)
        color_row.addWidget(self._cls_color_swatch)
        color_row.addStretch(1)
        ed.addWidget(QLabel("Marker color"))
        ed.addLayout(color_row)

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
                "Marker types present on the open clip. Changes apply to every "
                "matching marker on the timeline."
            )
        )

        row = QHBoxLayout()
        row.setSpacing(12)

        left = QVBoxLayout()
        left.addWidget(self._section("Markers on clip"))
        self._marker_list = QListWidget()
        self._marker_list.setStyleSheet(_LIST)
        self._marker_list.setMinimumWidth(220)
        self._marker_list.setMinimumHeight(240)
        self._marker_list.currentRowChanged.connect(self._on_marker_row)
        left.addWidget(self._marker_list, 1)
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
        self._class_list.blockSignals(True)
        self._class_list.clear()
        for cls in self._prefs.get("classes") or []:
            item = QListWidgetItem(
                f"{cls.get('name', 'Class')}  ·  {cls.get('color', '')}"
            )
            item.setData(Qt.ItemDataRole.UserRole, cls.get("id"))
            self._class_list.addItem(item)
        self._class_list.blockSignals(False)
        self._on_class_row(self._class_list.currentRow())
        self._reload_class_combo()

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
        color = str(cls.get("color") or "#b29ae7")
        self._cls_color_swatch.setStyleSheet(
            f"background: {color}; border-radius: 6px; border: 1px solid #888;"
        )

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

    def _clear_class_icon(self) -> None:
        cid = self._current_class_id()
        if cid:
            mprefs.update_class(cid, icon="")
            self._emit_changed()

    def _repopulate_markers(self) -> None:
        if not hasattr(self, "_marker_list"):
            return
        self._marker_list.blockSignals(True)
        self._marker_list.clear()
        for row in self._clip_rows:
            key = row["key"]
            ov = mprefs.marker_override(key, self._prefs)
            suffix = ""
            if ov.get("class_id"):
                cls = mprefs.get_class(ov["class_id"], self._prefs)
                if cls:
                    suffix = f"  ·  {cls.get('name')}"
            item = QListWidgetItem(f"{row['label']}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setToolTip(key)
            self._marker_list.addItem(item)
        self._marker_list.blockSignals(False)
        self._on_marker_row(self._marker_list.currentRow())

    def _on_marker_row(self, row: int) -> None:
        if not hasattr(self, "_mk_editor"):
            return
        item = self._marker_list.item(row) if row >= 0 else None
        self._selected_key = (
            item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        )
        has = bool(self._selected_key)
        self._mk_empty.setVisible(not has)
        self._mk_editor.setVisible(has)
        if not has:
            return
        key = self._selected_key
        label = mprefs.friendly_marker_label(key)
        for r in self._clip_rows:
            if r["key"] == key:
                label = r.get("label") or label
                break
        self._mk_id_lbl.setText(f"{label}\nID: {key}")
        ov = mprefs.marker_override(key, self._prefs)
        self._mk_label.blockSignals(True)
        self._mk_label.setText(ov.get("label") or "")
        self._mk_label.blockSignals(False)
        self._mk_class.blockSignals(True)
        idx = self._mk_class.findData(ov.get("class_id") or "")
        self._mk_class.setCurrentIndex(max(0, idx))
        self._mk_class.blockSignals(False)
        self._refresh_marker_preview()

    def _refresh_marker_preview(self) -> None:
        key = self._selected_key
        if not key or not hasattr(self, "_mk_preview"):
            return
        path = mprefs.resolve_custom_icon_path(key, prefs=self._prefs)
        pix = load_scaled_pixmap(path, 40) if path else None
        if pix is None:
            legacy = mprefs.legacy_asset_path(key)
            pix = load_scaled_pixmap(legacy, 40) if legacy else None
        if pix is None and self._app_id:
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
        if pix is not None and tint and key in ("usermarker", "steam_marker"):
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
        )
        self._emit_changed()
        self._repopulate_markers()
        for i in range(self._marker_list.count()):
            it = self._marker_list.item(i)
            if it and it.data(Qt.ItemDataRole.UserRole) == key:
                self._marker_list.setCurrentRow(i)
                break

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

    def _clear_marker_icon(self) -> None:
        key = self._selected_key
        if not key:
            return
        mprefs.set_marker_override(key, custom_icon="")
        self._emit_changed()
        self._refresh_marker_preview()
        self._repopulate_markers()

    def _reset_one_marker(self) -> None:
        key = self._selected_key
        if not key:
            return
        mprefs.reset_marker_override(key)
        self._emit_changed()
        self._on_marker_row(self._marker_list.currentRow())
        self._repopulate_markers()

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
