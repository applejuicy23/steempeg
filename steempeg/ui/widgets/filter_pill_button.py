"""A square icon button that opens the filter panel (matches sort-combo chrome)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter
from PySide6.QtWidgets import QPushButton, QWidget

from steempeg.infra.paths import get_resource_path
from steempeg.ui.design_tokens import ACCENT_PRIMARY
from steempeg.ui.ui_density import COMFORT, UiDensity


class _FilterBadgeSticker(QWidget):
    """Circle + digit — lives outside libraryToolbarPill so radius QSS cannot chop it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FilterPillBadge")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._text = ""
        self._font_px = 9
        self._bg = QColor(ACCENT_PRIMARY)
        self._fg = QColor("#1a1228")

    def set_sticker(self, text: str, side: int, font_px: int) -> None:
        self._text = text
        self._font_px = font_px
        self.setFixedSize(side, side)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt API
        if not self._text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        side = min(self.width(), self.height())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._bg)
        p.drawEllipse(0, 0, side - 1, side - 1)
        font = QFont("Segoe UI", self._font_px)
        font.setBold(True)
        font.setWeight(QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(self._fg)
        # Tight center — ExtraBold digits sit low; nudge up 1px.
        box = QRect(0, -1, side - 1, side - 1)
        p.drawText(box, int(Qt.AlignmentFlag.AlignCenter), self._text)
        p.end()


class FilterPillButton(QWidget):
    """Funnel chip + corner count sticker.

    Host stays ``filter_size``. Badge is reparented to the *parent of*
    ``libraryToolbarPill`` (sibling of the capsule) — the pill's
    ``border-radius`` clips descendants at the round end, which is exactly
    where the filter sits.

    Because the sticker is not a child of this widget, splitter / layout moves
    on ancestors do not fire our ``moveEvent`` — we event-filter the chain up
    to the float host so the badge cannot ghost in place (v49.1).
    """

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FilterPillHost")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self._active_count = 0
        self._dense = COMFORT
        self._badge_side = 17
        self._watched: list[QObject] = []

        self._btn = QPushButton(self)
        self._btn.setObjectName("FilterPill")
        self._btn.setText("")
        self._btn.setToolTip("Filters")
        self._btn.setIcon(QIcon(get_resource_path("filter.png")))
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn.clicked.connect(self.clicked.emit)

        self._badge = _FilterBadgeSticker()
        self._badge.hide()
        # Floated sticker outlives this chip's parent chain — delete with us.
        badge = self._badge
        pill = self

        def _cleanup_floated(_: QObject | None = None) -> None:
            try:
                badge.hide()
                badge.deleteLater()
            except RuntimeError:
                pass
            try:
                pill._clear_watchers()
            except RuntimeError:
                pass

        self.destroyed.connect(_cleanup_floated)

        self.apply_density(COMFORT)

    def apply_density(self, dense: UiDensity) -> None:
        from steempeg.ui import ui_theme as ut

        self._dense = dense
        sz = dense.filter_size
        icon = max(10, sz // 2 - (1 if dense.compact else 2))
        border = 1 if dense.compact else 2
        radius = 6 if dense.compact else 8
        pad = 1 if dense.compact else 2
        # Readable digit; still fits the square without eating the funnel.
        self._badge_side = 14 if dense.compact else 17

        self.setFixedSize(sz, sz)
        self.setMinimumSize(sz, sz)
        self.setMaximumSize(sz, sz)
        self._btn.setFixedSize(sz, sz)
        self._btn.move(0, 0)
        self._btn.setIconSize(QSize(icon, icon))
        if ut.get_ui_theme() != ut.UI_THEME_DEFAULT:
            p = ut.active_palette()
            self._btn.setStyleSheet(f"""
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
            self._btn.setStyleSheet(f"""
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
        self._refresh_badge_chrome()

    def set_active_count(self, count: int) -> None:
        """Corner badge: how many filter *categories* are narrowed (0 hides)."""
        n = max(0, int(count or 0))
        self._active_count = n
        if n <= 0:
            self._badge.hide()
            self._btn.setToolTip("Filters")
            self.setToolTip("Filters")
            return
        noun = "filter" if n == 1 else "filters"
        tip = f"Filters · {n} active {noun}"
        self._btn.setToolTip(tip)
        self.setToolTip(tip)
        self._refresh_badge_chrome()

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 — Qt API
        super().setEnabled(enabled)
        self._btn.setEnabled(enabled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._btn.setGeometry(0, 0, self.width(), self.height())
        self._place_badge()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._place_badge()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_badge_chrome()

    def hideEvent(self, event) -> None:
        self._badge.hide()
        super().hideEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        et = event.type()
        if et in (
            QEvent.Type.Move,
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.LayoutRequest,
            QEvent.Type.ZOrderChange,
        ):
            if self._active_count > 0 and self.isVisible():
                self._place_badge()
            elif not self.isVisible():
                self._badge.hide()
        elif et == QEvent.Type.Hide:
            # Ancestor hidden (tab switch / panel collapse) — park the sticker.
            if watched is not self._badge:
                self._badge.hide()
        return super().eventFilter(watched, event)

    def _font_px(self) -> int:
        return 9 if self._dense.compact else 10

    def _badge_float_host(self) -> QWidget | None:
        """Parent of libraryToolbarPill — sibling layer, no radius clip."""
        w = self.parentWidget()
        while w is not None:
            if w.objectName() == "libraryToolbarPill":
                host = w.parentWidget()
                return host if host is not None else w.window()
            w = w.parentWidget()
        return self.window()

    def _clear_watchers(self) -> None:
        for obj in self._watched:
            try:
                obj.removeEventFilter(self)
            except RuntimeError:
                pass
        self._watched = []

    def _watch_ancestors(self, host: QWidget) -> None:
        """Follow splitter / layout moves between the chip and the float host."""
        chain: list[QObject] = []
        w: QWidget | None = self
        while w is not None:
            chain.append(w)
            if w is host:
                break
            w = w.parentWidget()
        if host not in chain:
            chain.append(host)
        # Replace watchers when the float host changes (rare).
        if chain == self._watched:
            return
        self._clear_watchers()
        for obj in chain:
            obj.installEventFilter(self)
        self._watched = chain

    def _ensure_badge_host(self) -> None:
        host = self._badge_float_host()
        if host is None:
            return
        if self._badge.parentWidget() is not host:
            self._badge.setParent(host)
        self._watch_ancestors(host)

    def _refresh_badge_chrome(self) -> None:
        if self._active_count <= 0:
            self._badge.hide()
            return
        label = "9+" if self._active_count > 9 else str(self._active_count)
        self._badge.set_sticker(label, self._badge_side, self._font_px())
        self._place_badge()

    def _place_badge(self) -> None:
        if self._active_count <= 0 or not self.isVisible():
            self._badge.hide()
            return
        self._ensure_badge_host()
        host = self._badge.parentWidget()
        if host is None:
            return
        side = self._badge_side
        # Park on the top-right corner: slight peek past the rim so the funnel
        # stays clear, without floating far off the chip.
        out_x = 5 if not self._dense.compact else 4
        out_y = 4 if not self._dense.compact else 3
        corner = self.mapTo(host, QPoint(self.width(), 0))
        x = int(corner.x() - side + out_x)
        y = int(corner.y() - out_y)
        self._badge.move(x, y)
        self._badge.show()
        self._badge.raise_()
