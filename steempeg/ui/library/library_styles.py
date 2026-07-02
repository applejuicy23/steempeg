"""Shared Qt stylesheets for Clips Manager and Rendered videos library views."""

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
