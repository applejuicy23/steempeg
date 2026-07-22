"""Footer control row with a center widget pinned to the geometric midpoint."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget


class CenterPinnedRow(QWidget):
    """Left | right stretch columns with ``center`` overlaid on the true midpoint.

    Side columns may collide under the center when space is tight — the center
    label/timer stays put and stays on top. It is never a layout item, so side
    rails cannot push it aside.
    """

    def __init__(
        self,
        left: QWidget,
        center: QWidget,
        right: QWidget,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(0)
        self._center = center
        self._left = left
        self._right = right
        self.on_resized: Callable[[], None] | None = None

        for side in (left, right):
            side.setMinimumWidth(0)
            # Ignored: allocated half-width may be smaller than content; overflow
            # paints under the pinned center instead of shoving it aside.
            side.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(left, 1)
        lay.addWidget(right, 1)

        center.setParent(self)
        center.raise_()
        center.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_center()
        cb = self.on_resized
        if callable(cb):
            cb()

    def showEvent(self, event):
        super().showEvent(event)
        self._reposition_center()

    def _reposition_center(self) -> None:
        c = self._center
        if c is None:
            return
        c.adjustSize()
        hint = c.sizeHint()
        w = max(hint.width(), c.minimumSizeHint().width(), c.minimumWidth(), 90)
        h = max(hint.height(), c.minimumSizeHint().height(), 16)
        # True geometric center horizontally — never follows side content.
        x = max(0, (self.width() - w) // 2)
        band = self.height()
        if self._left is not None and self._left.height() > 0:
            band = self._left.height()
        y = max(0, (band - h) // 2)
        c.setGeometry(x, y, w, h)
        c.raise_()

    def sizeHint(self) -> QSize:
        h = 0
        for w in (self._left, self._right, self._center):
            if w is not None:
                h = max(h, w.sizeHint().height(), w.minimumSizeHint().height())
        return QSize(200, h or 24)

    def minimumSizeHint(self) -> QSize:
        # Do not reserve horizontal space for side rails — they may overlap.
        h = 0
        if self._center is not None:
            h = max(h, self._center.minimumSizeHint().height())
        for w in (self._left, self._right):
            if w is not None:
                h = max(h, w.minimumSizeHint().height())
        return QSize(0, h or 16)
