"""A flow layout that wraps its items onto new rows when they run out of width.

Pure Qt layout, no application logic.
"""
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout


class FlowLayout(QLayout):
    """Arranges child items left to right, wrapping to a new line when a row is full."""

    def __init__(self):
        super().__init__()
        self.items = []

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, idx):
        return self.items[idx] if 0 <= idx < len(self.items) else None

    def takeAt(self, idx):
        return self.items.pop(idx) if 0 <= idx < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        # Width 0/1 would stack every pill on its own row and invent a huge height;
        # parents then keep that height after reflow → empty gaps (Rendered Type bug).
        if w < 32:
            w = 360
        return self.doLayout(QRect(0, 0, w, 0), True)

    def setGeometry(self, r):
        super().setGeometry(r)
        self.doLayout(r, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        w = 360
        parent = self.parentWidget()
        if parent is not None and parent.width() > 32:
            w = parent.width()
        h = self.heightForWidth(w)
        min_w = 0
        for item in self.items:
            min_w = max(min_w, item.sizeHint().width())
        return QSize(min_w, max(0, h))

    def doLayout(self, r, test):
        x, y, line_h = r.x(), r.y(), 0
        for item in self.items:
            w, h = item.sizeHint().width(), item.sizeHint().height()
            # Move to the next row when this item would overflow the current one.
            if x + w > r.right() and line_h > 0:
                x, y, line_h = r.x(), y + line_h + 8, 0
            if not test:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x += w + 8
            line_h = max(line_h, h)
        return y + line_h - r.y()
