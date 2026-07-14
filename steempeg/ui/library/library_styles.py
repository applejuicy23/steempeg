"""Shared Qt stylesheets for Clips Manager and Rendered videos library views."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QAbstractItemView, QWidget

LIBRARY_SCROLLBAR_VERTICAL = """
    QScrollBar:vertical { border: none; background: transparent; width: 10px; margin: 2px; }
    QScrollBar::handle:vertical { background: #4e4e4e; min-height: 30px; border-radius: 4px; }
    QScrollBar::handle:vertical:hover { background: #b29ae7; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
"""

LIBRARY_TABLE_STYLE = """
    QTableWidget {
        background: transparent;
        border: none;
        outline: none;
    }
    QTableWidget::item {
        padding: 4px 12px;
        border-bottom: 1px solid #282828;
        color: #d1d1d1;
        font-size: 13px;
        font-family: 'Segoe UI', Arial, sans-serif;
    }
    QTableWidget::item:hover {
        background-color: #303030;
    }
    QTableWidget::item:selected {
        background-color: #3a2e54;
        color: #ffffff;
    }
    QHeaderView {
        background-color: transparent;
        border: none;
    }
    QHeaderView::section {
        background-color: transparent;
        color: #d1d1d1;
        padding: 6px;
        border: none;
        border-bottom: 1px solid #333333;
        font-size: 13px;
        font-weight: bold;
    }
    QHeaderView::section:hover {
        color: #ffffff;
    }
    QHeaderView::section:checked {
        color: #b29ae7;
    }
    QHeaderView::up-arrow, QHeaderView::down-arrow {
        width: 0px; height: 0px;
    }
""" + LIBRARY_SCROLLBAR_VERTICAL

LIBRARY_GRID_STYLE = """
    QListWidget { background: transparent; border: none; outline: none; }
    QListWidget::item {
        border-top-left-radius: 0px;
        border-top-right-radius: 0px;
        border-bottom-left-radius: 12px;
        border-bottom-right-radius: 12px;
        border: none;
        background-color: #2d2d2d;
        padding: 0px;
        margin: 0px;
    }
    QListWidget::item:selected {
        background-color: #2d2d2d;
    }
    QListWidget::item:focus {
        outline: none;
    }
""" + LIBRARY_SCROLLBAR_VERTICAL


def library_view_needs_vertical_scroll(view: QAbstractItemView) -> bool:
    """True when the view's content extends past the visible viewport."""
    bar = view.verticalScrollBar()
    return bar is not None and bar.maximum() > 0


def sync_library_vertical_scrollbar(
    view: QAbstractItemView | None,
    *,
    force_hide: bool = False,
) -> None:
    """Show the vertical scrollbar only when content actually overflows."""
    if view is None:
        return
    if force_hide or not library_view_needs_vertical_scroll(view):
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    else:
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)


def _library_scroll_views(host) -> list[QAbstractItemView]:
    views: list[QAbstractItemView] = []
    ui = getattr(host, "ui", None)
    if ui is not None and hasattr(ui, "table_clips"):
        views.append(ui.table_clips)
    for name in ("grid_clips", "table_rendered", "grid_rendered"):
        widget = getattr(host, name, None)
        if widget is not None:
            views.append(widget)
    return views


def sync_library_scrollbars(host, *, force_hide: bool = False) -> None:
    """Sync clips + rendered list/grid vertical scrollbars on ``host`` (SteempegApp)."""
    scanning = bool(
        getattr(host, "_clips_scan_active", False)
        or getattr(host, "_rendered_scan_active", False)
    )
    hide = force_hide or scanning
    for view in _library_scroll_views(host):
        sync_library_vertical_scrollbar(view, force_hide=hide)


class LibraryScrollSyncFilter(QObject):
    """Re-sync library scrollbars when the views container is resized."""

    def __init__(self, host, parent: QWidget | None = None):
        super().__init__(parent)
        self._host = host
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: sync_library_scrollbars(self._host))

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
