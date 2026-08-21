"""Filter popup for the Screenshots library (folders + games)."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.ui.library.filter_pill_paint import PillPaintDragMixin
from steempeg.ui.widgets import FlowLayout

_FOLDER_KEYS = ("steam", "steempeg")
_FOLDER_LABELS = {"steam": "Steam", "steempeg": "Steempeg"}


class ScreenshotsFilterMenu(PillPaintDragMixin, QWidget):
    """Screenshots filter — Folders (Steam / Steempeg) + Games chips."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(460)

        self.app = None
        self._game_buttons: dict[str, QPushButton] = {}
        self._folder_buttons: dict[str, QPushButton] = {}

        self.container = QFrame(self)
        self.container.setObjectName("MainFilterContainer")
        self.container.setStyleSheet("""
            QFrame#MainFilterContainer {
                background-color: #252525;
                border: 1px solid #3d3d3d;
                border-radius: 16px;
            }
        """)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.addWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        def create_category_capsule(title_text, content_widget):
            capsule = QFrame()
            capsule.setObjectName("CategoryCapsule")
            capsule.setStyleSheet("""
                QFrame#CategoryCapsule {
                    background-color: #2d2d2d;
                    border: 1px solid #383838;
                    border-radius: 14px;
                }
                QLabel#CategoryTitle {
                    color: #cccccc;
                    border: none;
                    background: transparent;
                    font-size: 13px;
                    font-weight: bold;
                    font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji';
                }
            """)
            cap_layout = QVBoxLayout(capsule)
            cap_layout.setContentsMargins(12, 12, 12, 12)
            cap_layout.setSpacing(8)
            title_lbl = QLabel(title_text)
            title_lbl.setObjectName("CategoryTitle")
            cap_layout.addWidget(title_lbl, 0)
            cap_layout.addWidget(content_widget, 0)
            return capsule

        self.folders_container = QWidget()
        self.folders_container.setStyleSheet("background: transparent;")
        self.folders_container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.folders_layout = FlowLayout()
        self.folders_container.setLayout(self.folders_layout)
        layout.addWidget(
            create_category_capsule("📁 Folders:", self.folders_container), 0
        )

        self.games_container = QWidget()
        self.games_container.setStyleSheet("background: transparent;")
        self.games_container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.games_layout = FlowLayout()
        self.games_container.setLayout(self.games_layout)
        layout.addWidget(
            create_category_capsule("🎮 Games:", self.games_container), 0
        )

        self._init_pill_paint_drag()
        self._register_pill_paint_zone(
            self.folders_container, self.folders_layout, self._update_apply_label
        )
        self._register_pill_paint_zone(
            self.games_container, self.games_layout, self._update_apply_label
        )

        for key in _FOLDER_KEYS:
            icon = self._icon_for_source(key)
            btn = QPushButton(icon, f" {_FOLDER_LABELS[key]}")
            if not icon.isNull():
                btn.setIconSize(QSize(16, 16))
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._PILL_BTN_STYLE)
            btn.setProperty("raw_name", key)
            btn.clicked.connect(self._update_apply_label)
            self._wire_pill_paint_button(btn)
            self.folders_layout.addWidget(btn)
            self._folder_buttons[key] = btn

        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 10, 0, 0)

        unified_table_style = """
            QPushButton {
                background-color: #383838;
                color: #ffffff;
                border: 2px solid #444444;
                border-radius: 14px;
                font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
                font-weight: bold;
                font-size: 13px;
                padding: 4px 12px;
                min-height: 24px;
            }
            QPushButton:hover { background-color: #404040; border: 2px solid #6b5a8e; }
            QPushButton:pressed { background-color: #3a324a; border: 2px solid #b29ae7; }
            QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }
            QPushButton::menu-indicator { image: none; }
        """
        clear_style = unified_table_style.replace(
            "color: #ffffff;", "color: #ff7777;"
        ).replace("#6b5a8e", "#e05555").replace("#b29ae7", "#ff7777")

        self.btn_clear = QPushButton("🗑 Clear")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.setStyleSheet(clear_style)
        self.btn_clear.clicked.connect(self._clear_all)

        self.btn_apply = QPushButton("Apply Filters (0)")
        self.btn_apply.setCursor(Qt.PointingHandCursor)
        self.btn_apply.setStyleSheet(unified_table_style)
        self.btn_apply.clicked.connect(self._apply)

        bottom_layout.addWidget(self.btn_clear)
        bottom_layout.addStretch(1)
        bottom_layout.addWidget(self.btn_apply)
        layout.addLayout(bottom_layout)

        self._outer_layout = main_layout
        self._inner_layout = layout
        self._bottom_layout = bottom_layout

    def eventFilter(self, source, event):  # noqa: N802
        if self._try_handle_pill_paint_filter(source, event):
            return True
        return super().eventFilter(source, event)

    def apply_density(self, dense) -> None:
        """Shrink popup chrome for Deck / ultra-narrow windows; re-tint for UI theme."""
        from steempeg.ui import ui_theme as ut

        compact = bool(getattr(dense, "compact", False))
        width = 340 if compact else 460
        self.setFixedWidth(width)

        font = 11 if compact else 13
        pad_v = 2 if compact else 4
        pad_h = 8 if compact else 12
        min_h = 18 if compact else 24
        radius = 8 if compact else 10
        border = 1 if compact else 2
        outer_m = 6 if compact else 10
        inner_m = 8 if compact else 16
        gap = 6 if compact else 12
        cap_m = 8 if compact else 12
        title_font = 11 if compact else 13
        pill_r = 10 if compact else 14

        if getattr(self, "_outer_layout", None) is not None:
            self._outer_layout.setContentsMargins(outer_m, outer_m, outer_m, outer_m)
        if getattr(self, "_inner_layout", None) is not None:
            self._inner_layout.setContentsMargins(inner_m, inner_m, inner_m, inner_m)
            self._inner_layout.setSpacing(gap)
        if getattr(self, "_bottom_layout", None) is not None:
            self._bottom_layout.setContentsMargins(0, 6 if compact else 10, 0, 0)

        self.container.setStyleSheet(
            ut.filter_menu_container_stylesheet(radius=pill_r + 2)
        )
        for capsule in self.findChildren(QFrame, "CategoryCapsule"):
            capsule.setStyleSheet(
                ut.filter_menu_capsule_stylesheet(radius=pill_r, title_font=title_font)
            )
            lay = capsule.layout()
            if lay is not None:
                lay.setContentsMargins(cap_m, cap_m, cap_m, cap_m)
                lay.setSpacing(4 if compact else 8)

        self._PILL_BTN_STYLE = ut.filter_chip_button_stylesheet(
            font=font,
            pad_v=pad_v,
            pad_h=pad_h,
            min_h=min_h,
            radius=radius,
            border=border,
        )
        for btn in self.findChildren(QPushButton):
            if btn in (self.btn_clear, self.btn_apply):
                continue
            if btn.isCheckable() or btn.parent() in (
                getattr(self, "games_container", None),
                getattr(self, "folders_container", None),
            ):
                btn.setStyleSheet(self._PILL_BTN_STYLE)

        unified = ut.filter_action_button_stylesheet(
            font=font,
            pad_v=pad_v,
            pad_h=pad_h,
            min_h=min_h,
            radius=radius + 2,
            border=border,
        )
        clear_style = (
            unified.replace("color: #ffffff;", "color: #ff7777;")
            .replace("#6b5a8e", "#e05555")
            .replace("#b29ae7", "#ff7777")
        )
        self.btn_clear.setStyleSheet(clear_style)
        self.btn_apply.setStyleSheet(unified)

    # Default fallback until apply_density (matches Clips / Rendered).
    _PILL_BTN_STYLE = """
        QPushButton {
            background-color: #383838;
            color: #aaaaaa;
            border: 2px solid #444444;
            border-radius: 10px;
            font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
            font-weight: bold;
            font-size: 13px;
            padding: 4px 12px;
            min-height: 24px;
        }
        QPushButton:hover {
            background-color: #404040;
            color: #ffffff;
            border: 2px solid #555555;
        }
        QPushButton:checked {
            background-color: #404040;
            color: #ffffff;
            border: 2px solid #6b5a8e;
        }
        QPushButton:checked:hover {
            background-color: #3a324a;
            border: 2px solid #b29ae7;
        }
    """

    def _flow_inner_width(self) -> int:
        return max(120, self.width() - 10 * 2 - 16 * 2 - 12 * 2)

    def _tighten_flow_sections(self) -> None:
        width = self._flow_inner_width()
        for container, flow in (
            (self.folders_container, self.folders_layout),
            (self.games_container, self.games_layout),
        ):
            h = max(1, int(flow.heightForWidth(width)))
            container.setFixedHeight(h)
        self.adjustSize()

    def set_content_max_height(self, max_px: int) -> None:
        _ = max_px
        self._tighten_flow_sections()

    @staticmethod
    def _icon_for_source(source: str) -> QIcon:
        """Steam / Steempeg logo matching screenshot card footer badges."""
        try:
            from steempeg.ui.library.screenshot_photo import _load_source_icon

            pix = _load_source_icon(source)
            if pix is None or pix.isNull():
                return QIcon()
            return QIcon(pix)
        except Exception:
            return QIcon()

    @staticmethod
    def _icon_for_app_id(app_window, app_id: str) -> QIcon:
        """Local logo only (cache/{appid}.jpg or Steam librarycache). Empty if missing."""
        aid = str(app_id or "").strip()
        if not aid or app_window is None:
            return QIcon()
        path = ""
        resolver = getattr(app_window, "_screenshot_icon_path_for_app_id", None)
        if callable(resolver):
            try:
                path = str(resolver(aid) or "")
            except Exception:
                path = ""
        if not path:
            return QIcon()
        try:
            from steempeg.ui.icon_shape import shaped_game_icon

            pix = QPixmap(path)
            if pix.isNull():
                return QIcon()
            return shaped_game_icon(pix)
        except Exception:
            return QIcon(path)

    def gather_statistics(self, app_window):
        self.app = app_window
        grid = getattr(app_window, "grid_screenshots", None)

        catalog: dict[str, dict] = {}
        if hasattr(app_window, "_collect_screenshot_games_catalog"):
            try:
                catalog = app_window._collect_screenshot_games_catalog() or {}
            except Exception:
                catalog = {}
        if not catalog and grid is not None:
            from steempeg.ui.library.rendered_library import (
                _SHOT_APP_ID_ROLE,
                _SHOT_GAME_ROLE,
                _SHOT_MTIME_ROLE,
                _SHOT_SOURCE_ROLE,
            )

            for i in range(grid.count()):
                item = grid.item(i)
                if item is None:
                    continue
                gname = str(item.data(_SHOT_GAME_ROLE) or "").strip() or "Unknown"
                app_id = str(item.data(_SHOT_APP_ID_ROLE) or "").strip()
                if not app_id:
                    lookup = getattr(app_window, "_screenshot_app_id_for_game_label", None)
                    if callable(lookup):
                        try:
                            source = str(item.data(_SHOT_SOURCE_ROLE) or "steempeg")
                            app_id = str(
                                lookup(gname, app_id="", source=source) or ""
                            ).strip()
                        except Exception:
                            app_id = ""
                try:
                    mtime = float(item.data(_SHOT_MTIME_ROLE) or 0.0)
                except (TypeError, ValueError):
                    mtime = 0.0
                rec = catalog.setdefault(
                    gname, {"app_id": app_id, "count": 0, "max_mtime": 0.0}
                )
                rec["count"] = int(rec.get("count") or 0) + 1
                rec["max_mtime"] = max(float(rec.get("max_mtime") or 0.0), mtime)
                if app_id and not rec.get("app_id"):
                    rec["app_id"] = app_id

        if hasattr(app_window, "_sort_screenshot_game_catalog_items"):
            try:
                game_rows = app_window._sort_screenshot_game_catalog_items(catalog)
            except Exception:
                game_rows = sorted(catalog.items(), key=lambda kv: kv[0].lower())
        else:
            game_rows = sorted(catalog.items(), key=lambda kv: kv[0].lower())

        saved_folders = getattr(app_window, "_screenshots_filter_folders", None)
        for key, btn in self._folder_buttons.items():
            if saved_folders is None:
                btn.setChecked(True)
            else:
                btn.setChecked(key in saved_folders)

        self._drop_pill_layout_buttons(self.games_layout)
        while self.games_layout.count():
            item = self.games_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._game_buttons.clear()

        saved_games = getattr(app_window, "_screenshots_filter_games", None)
        for name, rec in game_rows:
            app_id = str((rec or {}).get("app_id") or "").strip()
            if not app_id:
                lookup = getattr(app_window, "_screenshot_app_id_for_game_label", None)
                if callable(lookup):
                    try:
                        app_id = str(lookup(name, app_id="", source="steempeg") or "").strip()
                    except Exception:
                        app_id = ""
            short_name = name[:14] + "..." if len(name) > 14 else name
            icon = self._icon_for_app_id(app_window, app_id)
            btn = QPushButton(icon, f" {short_name}")
            if not icon.isNull():
                btn.setIconSize(QSize(16, 16))
            btn.setCheckable(True)
            if saved_games is None:
                btn.setChecked(True)
            else:
                btn.setChecked(name in saved_games)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._PILL_BTN_STYLE)
            btn.setProperty("raw_name", name)
            btn.clicked.connect(self._update_apply_label)
            self._wire_pill_paint_button(btn)
            self.games_layout.addWidget(btn)
            self._game_buttons[name] = btn

        self._update_apply_label()
        self._tighten_flow_sections()

    def _selected_games(self) -> set[str] | None:
        if not self._game_buttons:
            return None
        selected = {n for n, b in self._game_buttons.items() if b.isChecked()}
        if len(selected) == len(self._game_buttons):
            return None
        return selected

    def _selected_folders(self) -> set[str] | None:
        if not self._folder_buttons:
            return None
        selected = {n for n, b in self._folder_buttons.items() if b.isChecked()}
        if len(selected) == len(self._folder_buttons):
            return None
        return selected

    def _live_match_count(self) -> int:
        if not self.app:
            return 0
        games = self._selected_games()
        folders = self._selected_folders()
        grid = getattr(self.app, "grid_screenshots", None)
        if grid is None:
            return 0
        from steempeg.ui.library.rendered_library import (
            _SHOT_GAME_ROLE,
            _SHOT_SOURCE_ROLE,
        )

        count = 0
        for i in range(grid.count()):
            item = grid.item(i)
            if item is None:
                continue
            gname = str(item.data(_SHOT_GAME_ROLE) or "").strip() or "Unknown"
            if games is not None and gname not in games:
                continue
            source = str(item.data(_SHOT_SOURCE_ROLE) or "steempeg").strip().lower()
            if not source:
                source = "steempeg"
            if folders is not None and source not in folders:
                continue
            count += 1
        return count

    def _update_apply_label(self):
        self.btn_apply.setText(f"Apply Filters ({self._live_match_count()})")

    def _clear_all(self):
        for btn in self._folder_buttons.values():
            btn.setChecked(True)
        for btn in self._game_buttons.values():
            btn.setChecked(True)
        self._update_apply_label()
        if not self.app:
            return
        # Match Clips Clear: apply immediately and wipe persisted filter memory.
        self.app._screenshots_filter_games = None
        self.app._screenshots_filter_folders = None
        self.app._apply_screenshots_filters()
        if hasattr(self.app, "_persist_library_filter_memory"):
            self.app._persist_library_filter_memory()
        self.hide()

    def _apply(self):
        if not self.app:
            return
        self.app._screenshots_filter_games = self._selected_games()
        self.app._screenshots_filter_folders = self._selected_folders()
        self.app._apply_screenshots_filters()
        if hasattr(self.app, "_persist_library_filter_memory"):
            self.app._persist_library_filter_memory()
        self.hide()
