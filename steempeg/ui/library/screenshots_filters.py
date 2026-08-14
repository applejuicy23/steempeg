"""Filter popup for the Screenshots library (games only)."""
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


class ScreenshotsFilterMenu(PillPaintDragMixin, QWidget):
    """Screenshots filter — Games chips only (no Type / Health)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(460)

        self.app = None
        self._game_buttons: dict[str, QPushButton] = {}

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
        title_lbl = QLabel("🎮 Games:")
        title_lbl.setObjectName("CategoryTitle")
        cap_layout.addWidget(title_lbl, 0)

        self.games_container = QWidget()
        self.games_container.setStyleSheet("background: transparent;")
        self.games_container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.games_layout = FlowLayout()
        self.games_container.setLayout(self.games_layout)
        cap_layout.addWidget(self.games_container, 0)
        layout.addWidget(capsule, 0)

        self._init_pill_paint_drag()
        self._register_pill_paint_zone(
            self.games_container, self.games_layout, self._update_apply_label
        )

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

    def eventFilter(self, source, event):  # noqa: N802
        if self._try_handle_pill_paint_filter(source, event):
            return True
        return super().eventFilter(source, event)

    # Match Clips Manager / Rendered videos game chips (filters.py / rendered_filters.py).
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
        h = max(1, int(self.games_layout.heightForWidth(width)))
        self.games_container.setFixedHeight(h)
        self.adjustSize()

    def set_content_max_height(self, max_px: int) -> None:
        _ = max_px
        self._tighten_flow_sections()

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
        from steempeg.ui.library.rendered_library import _SHOT_APP_ID_ROLE, _SHOT_GAME_ROLE

        self.app = app_window
        grid = getattr(app_window, "grid_screenshots", None)

        # name → app_id (prefer first non-empty app_id for the logo)
        unique_games: dict[str, str] = {}
        if grid is not None:
            for i in range(grid.count()):
                item = grid.item(i)
                if item is None:
                    continue
                gname = str(item.data(_SHOT_GAME_ROLE) or "").strip() or "Unknown"
                app_id = str(item.data(_SHOT_APP_ID_ROLE) or "").strip()
                if gname not in unique_games:
                    unique_games[gname] = app_id
                elif app_id and not unique_games[gname]:
                    unique_games[gname] = app_id

        self._drop_pill_layout_buttons(self.games_layout)
        while self.games_layout.count():
            item = self.games_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._game_buttons.clear()

        saved_games = getattr(app_window, "_screenshots_filter_games", None)
        for name, app_id in sorted(unique_games.items(), key=lambda kv: kv[0].lower()):
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

    def _live_match_count(self) -> int:
        if not self.app:
            return 0
        games = self._selected_games()
        grid = getattr(self.app, "grid_screenshots", None)
        if grid is None:
            return 0
        from steempeg.ui.library.rendered_library import _SHOT_GAME_ROLE

        count = 0
        for i in range(grid.count()):
            item = grid.item(i)
            if item is None:
                continue
            gname = str(item.data(_SHOT_GAME_ROLE) or "").strip() or "Unknown"
            if games is not None and gname not in games:
                continue
            count += 1
        return count

    def _update_apply_label(self):
        self.btn_apply.setText(f"Apply Filters ({self._live_match_count()})")

    def _clear_all(self):
        for btn in self._game_buttons.values():
            btn.setChecked(True)
        self._update_apply_label()

    def _apply(self):
        if not self.app:
            return
        self.app._screenshots_filter_games = self._selected_games()
        self.app._apply_screenshots_filters()
        self.hide()
