"""A square icon button that opens the filter panel (matches sort-combo chrome)."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QLabel, QPushButton

from steempeg.infra.paths import get_resource_path
from steempeg.ui.design_tokens import ACCENT_PRIMARY
from steempeg.ui.ui_density import COMFORT, UiDensity


class FilterPillButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FilterPill")
        self.setText("")
        self.setToolTip("Filters")
        self.setIcon(QIcon(get_resource_path("filter.png")))
        self.setCursor(Qt.PointingHandCursor)
        self._active_count = 0
        self._badge = QLabel(self)
        self._badge.setObjectName("FilterPillBadge")
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._badge.hide()
        self.apply_density(COMFORT)

    def apply_density(self, dense: UiDensity) -> None:
        from steempeg.ui import ui_theme as ut

        # Same outer box as the Sorting combo (comfort ~36px ≈ combo min-h + pad + border).
        sz = dense.filter_size
        icon = max(10, sz // 2 - (1 if dense.compact else 2))
        # Rounded square like compact_combo — not a circle (radius ≠ sz/2).
        border = 1 if dense.compact else 2
        radius = 6 if dense.compact else 8
        pad = 1 if dense.compact else 2
        self.setFixedSize(sz, sz)
        self.setIconSize(QSize(icon, icon))
        if ut.get_ui_theme() != ut.UI_THEME_DEFAULT:
            p = ut.active_palette()
            self.setStyleSheet(f"""
        QPushButton#FilterPill {{
            background-color: {p.button_secondary_bg};
            border: {border}px solid {p.button_secondary_border};
            border-radius: {radius}px;
            padding: {pad}px;
        }}
        QPushButton#FilterPill:hover {{
            background-color: {p.button_secondary_hover_bg};
            border: {border}px solid #6b5a8e;
        }}
        QPushButton#FilterPill:pressed {{
            background-color: {p.button_secondary_pressed_bg};
            border: {border}px solid #b29ae7;
        }}
        QPushButton#FilterPill:disabled {{
            background-color: {p.button_disabled_bg};
            border: {border}px solid {p.button_disabled_border};
            color: #777777;
        }}
    """)
        else:
            self.setStyleSheet(f"""
        QPushButton#FilterPill {{
            background-color: #383838;
            border: {border}px solid #444444;
            border-radius: {radius}px;
            padding: {pad}px;
        }}
        QPushButton#FilterPill:hover {{
            background-color: #404040;
            border: {border}px solid #6b5a8e;
        }}
        QPushButton#FilterPill:pressed {{
            background-color: #3a324a;
            border: {border}px solid #b29ae7;
        }}
        QPushButton#FilterPill:disabled {{
            background-color: #2f2f2f;
            border: {border}px solid #3a3a3a;
            color: #777777;
        }}
    """)
        self._restyle_badge(dense)
        if self._active_count > 0:
            self._badge.show()
            self._badge.raise_()
        self._place_badge()

    def set_active_count(self, count: int) -> None:
        """Corner badge: how many filter *categories* are narrowed (0 hides)."""
        n = max(0, int(count or 0))
        self._active_count = n
        if n <= 0:
            self._badge.hide()
            self.setToolTip("Filters")
            return
        label = "9+" if n > 9 else str(n)
        self._badge.setText(label)
        self._badge.show()
        self._badge.raise_()
        self._place_badge()
        noun = "filter" if n == 1 else "filters"
        self.setToolTip(f"Filters · {n} active {noun}")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_badge()

    def _restyle_badge(self, dense: UiDensity) -> None:
        side = 14 if dense.compact else 16
        font_px = 8 if dense.compact else 9
        self._badge.setFixedSize(side, side)
        self._badge.setStyleSheet(
            f"""
            QLabel#FilterPillBadge {{
                background-color: {ACCENT_PRIMARY};
                color: #1a1228;
                border: none;
                border-radius: {side // 2}px;
                font-size: {font_px}px;
                font-weight: 800;
                font-family: Segoe UI, Arial, sans-serif;
                padding: 0px;
            }}
            """
        )

    def _place_badge(self) -> None:
        if not self._badge.isVisible() and self._active_count <= 0:
            return
        # Overlap the top-right corner of the funnel (notification-style).
        bw = self._badge.width()
        bh = self._badge.height()
        x = max(-2, self.width() - bw + 2)
        y = max(-2, -2)
        self._badge.move(x, y)
