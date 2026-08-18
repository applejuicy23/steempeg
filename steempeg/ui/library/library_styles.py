"""Shared Qt stylesheets for Clips Manager and Rendered videos library views."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QAbstractItemView, QWidget

# Capsule chrome aligned with TimelineOverviewScrollBar (player timeline strip).
_LIBRARY_SCROLLBAR_TRACK = "#4a4a4a"
_LIBRARY_SCROLLBAR_THUMB = "#9f8dba"
_LIBRARY_SCROLLBAR_THUMB_HOVER = "#cdbfe6"
_LIBRARY_SCROLLBAR_WIDTH = 12
_LIBRARY_SCROLLBAR_RADIUS = 6

LIBRARY_SCROLLBAR_VERTICAL = f"""
    QScrollBar:vertical {{
        border: none;
        background: {_LIBRARY_SCROLLBAR_TRACK};
        width: {_LIBRARY_SCROLLBAR_WIDTH}px;
        margin: 4px 2px;
        border-radius: {_LIBRARY_SCROLLBAR_RADIUS}px;
    }}
    QScrollBar::handle:vertical {{
        background: {_LIBRARY_SCROLLBAR_THUMB};
        min-height: 30px;
        border-radius: {_LIBRARY_SCROLLBAR_RADIUS}px;
        margin: 0px 1px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {_LIBRARY_SCROLLBAR_THUMB_HOVER};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
        border: none;
        background: none;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
    }}
"""

def library_table_stylesheet() -> str:
    """List/table chrome — reads active ``design_tokens`` (UI theme synced)."""
    from steempeg.ui import design_tokens as tok
    from steempeg.ui import ui_theme as ut

    p = ut.active_palette()
    # v45.1 stock row chrome — do not substitute panel border / nav hover on Default.
    if p.name == ut.UI_THEME_DEFAULT:
        row_border = "#282828"
        row_hover = "#303030"
    else:
        row_border = p.border_panel
        row_hover = p.neo_nav_hover_bg
    return f"""
    QTableWidget {{
        background: transparent;
        border: none;
        outline: none;
    }}
    QTableWidget::item {{
        padding: 4px 12px;
        border-bottom: 1px solid {row_border};
        color: #d1d1d1;
        font-size: 13px;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
    }}
    QTableWidget::item:hover {{
        background-color: {row_hover};
    }}
    QTableWidget::item:selected {{
        background-color: #3a2e54;
        color: #ffffff;
    }}
    QHeaderView {{
        background-color: transparent;
        border: none;
    }}
    QHeaderView::section {{
        background-color: transparent;
        color: #d1d1d1;
        padding: 6px;
        border: none;
        border-bottom: 1px solid {tok.BORDER_DEFAULT};
        font-size: 13px;
        font-weight: bold;
    }}
    QHeaderView::section:hover {{
        color: #ffffff;
    }}
    QHeaderView::section:checked {{
        color: #b29ae7;
    }}
    QHeaderView::up-arrow, QHeaderView::down-arrow {{
        width: 0px; height: 0px;
    }}
""" + LIBRARY_SCROLLBAR_VERTICAL


def library_grid_stylesheet() -> str:
    """Grid item slot fill — ``BG_CARD`` from the active UI theme."""
    from steempeg.ui import design_tokens as tok

    card = tok.BG_CARD
    return f"""
    QListWidget {{ background: transparent; border: none; outline: none; }}
    QListWidget::item {{
        border-radius: 0px;
        border: none;
        background-color: {card};
        padding: 0px;
        margin: 0px;
    }}
    QListWidget::item:selected {{
        background-color: {card};
    }}
    QListWidget::item:focus {{
        outline: none;
    }}
""" + LIBRARY_SCROLLBAR_VERTICAL


# Call sites must invoke the functions below so tokens stay in sync after theme changes.


def library_view_needs_vertical_scroll(view: QAbstractItemView) -> bool:
    """True when the view's content extends past the visible viewport."""
    bar = view.verticalScrollBar()
    return bar is not None and bar.maximum() > 0


def sync_library_vertical_scrollbar(
    view: QAbstractItemView | None,
    *,
    force_hide: bool = False,
) -> None:
    """Keep the vertical scrollbar visible when content overflows."""
    if view is None:
        return
    if force_hide or not library_view_needs_vertical_scroll(view):
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    else:
        # AlwaysOn keeps the purple track visible (not a fading AsNeeded hairline).
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)


def _library_scroll_views(host) -> list[QAbstractItemView]:
    views: list[QAbstractItemView] = []
    ui = getattr(host, "ui", None)
    if ui is not None and hasattr(ui, "table_clips"):
        views.append(ui.table_clips)
    # Screenshots use AlwaysOn (see sync_screenshots_vertical_scrollbar) so AsNeeded
    # does not shrink the IconMode viewport near a column threshold.
    for name in ("grid_clips", "table_rendered", "grid_rendered"):
        widget = getattr(host, name, None)
        if widget is not None:
            views.append(widget)
    return views


def sync_screenshots_vertical_scrollbar(
    view: QAbstractItemView | None,
    *,
    force_hide: bool = False,
) -> None:
    """Screenshots: AlwaysOn when overflowing so wrap width stays stable.

    AsNeeded takes ~10px from the viewport and can sticky-lock IconMode at 2
    columns with empty room for a third. AlwaysOn reserves the gutter once.

    Prefer AlwaysOn from item count before the first layout pass so wrap is
    never computed at the wider AlwaysOff width then shrunk.
    """
    if view is None:
        return
    if force_hide:
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return
    n = 0
    try:
        n = int(view.count())  # type: ignore[attr-defined]
    except Exception:
        n = 0
    # ~3 cols × ~4 visible rows; more than that usually needs a bar with 8k shelves.
    if n > 12 or library_view_needs_vertical_scroll(view):
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    else:
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)


def sync_library_scrollbars(host, *, force_hide: bool = False) -> None:
    """Sync clips + rendered list/grid vertical scrollbars on ``host`` (SteempegApp)."""
    scanning = bool(
        getattr(host, "_clips_scan_active", False)
        or getattr(host, "_rendered_scan_active", False)
    )
    hide = force_hide or scanning
    for view in _library_scroll_views(host):
        sync_library_vertical_scrollbar(view, force_hide=hide)
    sync_screenshots_vertical_scrollbar(
        getattr(host, "grid_screenshots", None), force_hide=hide
    )
    if hasattr(host, "sync_clip_card_edge_roles"):
        try:
            host.sync_clip_card_edge_roles()
        except Exception:
            pass


class LibraryScrollSyncFilter(QObject):
    """Re-sync library scrollbars when the views container is resized."""

    def __init__(self, host, parent: QWidget | None = None):
        super().__init__(parent)
        self._host = host
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_resize_settle)

    def _on_resize_settle(self) -> None:
        sync_library_scrollbars(self._host)
        host = self._host
        if (
            getattr(host, "_library_panel_mode", "") == "screenshots"
            and hasattr(host, "_schedule_screenshots_grid_reflow")
        ):
            host._schedule_screenshots_grid_reflow(0)

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Type.Resize:
            self._timer.start(0)
        return False


def install_library_scroll_sync(host) -> None:
    """Initial scrollbar policy + resize hook for the library views stack."""
    for view in _library_scroll_views(host):
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    container = getattr(host, "library_views_container", None)
    if container is not None:
        filt = LibraryScrollSyncFilter(host, container)
        container.installEventFilter(filt)
        host._library_scroll_sync_filter = filt
