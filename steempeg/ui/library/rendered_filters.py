"""Filter popup for the rendered media library (games + file types only)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QLabel,
)

from steempeg.ui.widgets import FlowLayout

_PILL_BTN_STYLE = """
    QPushButton {
        background-color: #383838;
        color: #aaaaaa;
        border: 2px solid #444444;
        border-radius: 10px;
        font-family: 'Segoe UI', Arial, sans-serif;
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


class RenderedFilterMenu(QWidget):
    """Clips Manager–style filter popup without health/date/duration sections."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.app = None
        self._game_buttons: dict[str, QPushButton] = {}
        self._type_buttons: dict[str, QPushButton] = {}

        self.container = QFrame()
        self.container.setObjectName("FilterContainer")
        self.container.setStyleSheet("""
            QFrame#FilterContainer {
                background-color: #1e1e1e;
                border: 1px solid #444444;
                border-radius: 16px;
            }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        def _capsule(title_text, content_widget):
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
                    font-family: 'Segoe UI';
                }
            """)
            cap_layout = QVBoxLayout(capsule)
            cap_layout.setContentsMargins(12, 12, 12, 12)
            cap_layout.setSpacing(8)
            title_lbl = QLabel(title_text)
            title_lbl.setObjectName("CategoryTitle")
            cap_layout.addWidget(title_lbl)
            cap_layout.addWidget(content_widget)
            return capsule

        self.games_container = QWidget()
        self.games_container.setStyleSheet("background: transparent;")
        self.games_layout = FlowLayout()
        self.games_container.setLayout(self.games_layout)

        self._games_scroll = QScrollArea()
        self._games_scroll.setWidgetResizable(True)
        self._games_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._games_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._games_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._games_scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { border: none; background: transparent; width: 8px; margin: 2px; }
            QScrollBar::handle:vertical { background: #4e4e4e; min-height: 24px; border-radius: 4px; }
            QScrollBar::handle:vertical:hover { background: #b29ae7; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)
        self._games_scroll.setWidget(self.games_container)
        layout.addWidget(_capsule("🎮 Games:", self._games_scroll))

        self.types_container = QWidget()
        self.types_layout = FlowLayout()
        self.types_container.setLayout(self.types_layout)
        layout.addWidget(_capsule("📂 Type:", self.types_container))

        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(8)

        clear_style = """
            QPushButton {
                background-color: #2d2d2d;
                color: #aaaaaa;
                border: 2px solid #444444;
                border-radius: 10px;
                font-weight: bold;
                padding: 8px 16px;
            }
            QPushButton:hover { background-color: #383838; color: white; }
        """
        unified_table_style = """
            QPushButton {
                background-color: #5138e6;
                color: white;
                border: none;
                border-radius: 10px;
                font-weight: bold;
                padding: 8px 16px;
            }
            QPushButton:hover { background-color: #6b5aee; }
        """

        self.btn_clear = QPushButton("Clear All")
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.setStyleSheet(clear_style)
        self.btn_clear.clicked.connect(self._clear_all)

        self.btn_apply = QPushButton("Apply Filters")
        self.btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply.setStyleSheet(unified_table_style)
        self.btn_apply.clicked.connect(self._apply)

        bottom_layout.addWidget(self.btn_clear)
        bottom_layout.addWidget(self.btn_apply)
        layout.addLayout(bottom_layout)

        self.setFixedWidth(460)

    def set_content_max_height(self, max_px: int) -> None:
        self._games_scroll.setFixedHeight(0)
        self.adjustSize()
        non_games = self.height()
        cap = max(70, max_px - non_games)
        width = max(120, self.width() - 84)
        content = self.games_layout.heightForWidth(width) + 4
        height = max(40, min(content, cap))
        self._games_scroll.setFixedHeight(height)
        self.adjustSize()

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
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(_PILL_BTN_STYLE)
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
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(_PILL_BTN_STYLE)
            btn.setProperty("raw_type", type_label)
            btn.clicked.connect(self._update_apply_label)
            self.types_layout.addWidget(btn)
            self._type_buttons[type_label] = btn

        self._update_apply_label()

    def _selected_games(self) -> set[str] | None:
        if not self._game_buttons:
            return None
        selected = {n for n, b in self._game_buttons.items() if b.isChecked()}
        if len(selected) == len(self._game_buttons):
            return None
        # IMPORTANT:
        # If user unchecked *all* games, we must treat it as an active filter
        # selecting zero games (so live count becomes 0 and applying hides all
        # rows). Returning None here would mean "no filter" => count would
        # incorrectly stay at the full library size.
        return selected  # could be an empty set

    def _selected_types(self) -> set[str] | None:
        if not self._type_buttons:
            return None
        selected = {t for t, b in self._type_buttons.items() if b.isChecked()}
        if len(selected) == len(self._type_buttons):
            return None
        # Same semantics as games: an empty selection means "match nothing".
        return selected  # could be an empty set

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
