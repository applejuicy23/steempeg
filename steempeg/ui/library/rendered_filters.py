"""Filter popup for the rendered media library (games + file types only)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.ui.widgets import FlowLayout


class RenderedFilterMenu(QWidget):
    """Rendered filter — Games sits like Type (no scroll padding)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(460)

        self.app = None
        self._game_buttons: dict[str, QPushButton] = {}
        self._type_buttons: dict[str, QPushButton] = {}

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

        # Games = same structure as Type (FlowLayout directly in capsule).
        self.games_container = QWidget()
        self.games_container.setStyleSheet("background: transparent;")
        self.games_container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.games_layout = FlowLayout()
        self.games_container.setLayout(self.games_layout)
        layout.addWidget(create_category_capsule("🎮 Games:", self.games_container), 0)

        self.types_container = QWidget()
        self.types_container.setStyleSheet("background: transparent;")
        self.types_container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.types_layout = FlowLayout()
        self.types_container.setLayout(self.types_layout)
        layout.addWidget(create_category_capsule("📂 Type:", self.types_container), 0)

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
        bottom_layout.addWidget(self.btn_apply)
        layout.addLayout(bottom_layout)

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
        # popup − outer inset − container margins − capsule margins
        return max(120, self.width() - 10 * 2 - 16 * 2 - 12 * 2)

    def _tighten_flow_sections(self) -> None:
        """Lock Games/Type height to real wrapped pill rows (no stretch gaps)."""
        width = self._flow_inner_width()
        for container, flow in (
            (self.games_container, self.games_layout),
            (self.types_container, self.types_layout),
        ):
            h = max(1, int(flow.heightForWidth(width)))
            container.setFixedHeight(h)
        self.adjustSize()

    def set_content_max_height(self, max_px: int) -> None:
        _ = max_px
        self._tighten_flow_sections()

    def gather_statistics(self, app_window):
        from steempeg.ui.library.rendered_library import (
            _RENDERED_GAME_FILTER_ROLE,
            _RENDERED_TYPE_FILTER_ROLE,
        )

        self.app = app_window
        table = app_window.table_rendered

        unique_games: dict[str, object] = {}
        unique_types: set[str] = set()
        for row in range(table.rowCount()):
            name_item = table.item(row, 0)
            type_item = table.item(row, 1)
            if name_item:
                gname = name_item.data(_RENDERED_GAME_FILTER_ROLE) or "Unknown"
                if gname not in unique_games:
                    unique_games[gname] = name_item.icon()
            if type_item:
                tlabel = type_item.data(_RENDERED_TYPE_FILTER_ROLE)
                if tlabel:
                    unique_types.add(str(tlabel))

        while self.games_layout.count():
            item = self.games_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._game_buttons.clear()

        saved_games = getattr(app_window, "_rendered_filter_games", None)
        for name, icon in sorted(unique_games.items(), key=lambda kv: kv[0].lower()):
            short_name = name[:14] + "..." if len(name) > 14 else name
            btn = QPushButton(icon, f" {short_name}")
            btn.setCheckable(True)
            if saved_games is None:
                btn.setChecked(True)
            else:
                btn.setChecked(name in saved_games)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._PILL_BTN_STYLE)
            btn.setProperty("raw_name", name)
            btn.clicked.connect(self._update_apply_label)
            self.games_layout.addWidget(btn)
            self._game_buttons[name] = btn

        while self.types_layout.count():
            item = self.types_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._type_buttons.clear()

        saved_types = getattr(app_window, "_rendered_filter_types", None)
        for type_label in sorted(unique_types):
            btn = QPushButton(f"🎬 {type_label}")
            btn.setCheckable(True)
            if saved_types is None:
                btn.setChecked(True)
            else:
                btn.setChecked(type_label in saved_types)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._PILL_BTN_STYLE)
            btn.setProperty("raw_type", type_label)
            btn.clicked.connect(self._update_apply_label)
            self.types_layout.addWidget(btn)
            self._type_buttons[type_label] = btn

        self._update_apply_label()
        self._tighten_flow_sections()

    def _selected_games(self) -> set[str] | None:
        if not self._game_buttons:
            return None
        selected = {n for n, b in self._game_buttons.items() if b.isChecked()}
        if len(selected) == len(self._game_buttons):
            return None
        return selected

    def _selected_types(self) -> set[str] | None:
        if not self._type_buttons:
            return None
        selected = {t for t, b in self._type_buttons.items() if b.isChecked()}
        if len(selected) == len(self._type_buttons):
            return None
        return selected

    def _live_match_count(self) -> int:
        if not self.app:
            return 0
        games = self._selected_games()
        types = self._selected_types()
        from steempeg.ui.library.rendered_library import (
            _RENDERED_GAME_FILTER_ROLE,
            _RENDERED_TYPE_FILTER_ROLE,
        )
        count = 0
        table = self.app.table_rendered
        for row in range(table.rowCount()):
            name_item = table.item(row, 0)
            type_item = table.item(row, 1)
            gname = name_item.data(_RENDERED_GAME_FILTER_ROLE) if name_item else "Unknown"
            tlabel = type_item.data(_RENDERED_TYPE_FILTER_ROLE) if type_item else ""
            if games is not None and gname not in games:
                continue
            if types is not None and tlabel not in types:
                continue
            count += 1
        return count

    def _update_apply_label(self):
        self.btn_apply.setText(f"Apply Filters ({self._live_match_count()})")

    def _clear_all(self):
        for btn in self._game_buttons.values():
            btn.setChecked(True)
        for btn in self._type_buttons.values():
            btn.setChecked(True)
        self._update_apply_label()

    def _apply(self):
        if not self.app:
            return
        self.app._rendered_filter_games = self._selected_games()
        self.app._rendered_filter_types = self._selected_types()
        self.app._apply_rendered_filters()
        self.hide()
