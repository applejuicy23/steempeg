"""Chrome-style library panel tab with a hover-only close control."""
from PySide6.QtCore import QMimeData, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from steempeg.ui import design_tokens as tok
from steempeg.ui.ui_density import COMFORT, UiDensity

LIBRARY_TAB_MIME = "application/x-steempeg-library-tab"
_CARET_W = 3


def _tab_qss(font_px: int, radius: int, *, active: bool, hover: bool) -> str:
    from steempeg.ui import ui_theme as ut

    return ut.library_tab_stylesheet(
        font_px=font_px, radius=radius, active=active, hover=hover
    )


_CLOSE_HIDDEN = """
    QPushButton {
        background: transparent;
        border: none;
        color: transparent;
        font-size: 15px;
        font-weight: bold;
        padding: 0;
        margin: 0;
    }
"""
_CLOSE_VISIBLE = """
    QPushButton {
        background: transparent;
        border: none;
        color: #888888;
        font-size: 15px;
        font-weight: bold;
        padding: 0;
        margin: 0;
    }
    QPushButton:hover { color: #ffffff; background: rgba(255, 255, 255, 20); border-radius: 8px; }
"""


class LibraryTabWidget(QFrame):
    """Single library panel tab; close button is invisible until the tab is hovered."""

    activated = Signal(str)
    close_requested = Signal(str)

    def __init__(self, label: str, mode: str, parent=None, *, closable: bool = True):
        super().__init__(parent)
        self.mode = mode
        self._closable = closable
        self._active = False
        self._hovered = False
        self._label = label
        self._density = COMFORT
        self._drag_start = QPoint()
        self._dragging = False
        self.setObjectName("libraryTab")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Drops land on LibraryTabStrip (whole row), not the tab's own rect.

        self._row = QHBoxLayout(self)
        self._row.setSpacing(2)

        self._text = QLabel(label)
        self._text.setObjectName("libraryTabText")
        self._text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._row.addWidget(self._text)

        self._close = QPushButton("×")
        self._close.setFixedSize(18, 18)
        self._close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close.setToolTip("Close panel")
        self._close.setStyleSheet(_CLOSE_HIDDEN)
        self._close.clicked.connect(self._emit_close)
        if not closable:
            self._close.hide()
            self._close.setEnabled(False)
        self._row.addWidget(self._close, 0, Qt.AlignmentFlag.AlignVCenter)

        self.apply_density(COMFORT)
        self.set_active(False)

    def set_label(self, label: str) -> None:
        self._label = label
        self._text.setText(label)
        self._recompute_min_width()

    def apply_density(self, dense: UiDensity) -> None:
        self._density = dense
        self.setFixedHeight(dense.tab_height)
        pad_r = dense.tab_pad_r if self._closable else dense.tab_pad_l
        self._row.setContentsMargins(dense.tab_pad_l, 0, pad_r, 0)
        close_sz = 16 if dense.compact else 18
        self._close.setFixedSize(close_sz, close_sz)
        self._apply_style()
        self._recompute_min_width()

    def _recompute_min_width(self) -> None:
        d = self._density
        text_w = self._text.fontMetrics().horizontalAdvance(self._label)
        close_w = self._close.width() if self._closable else 0
        pad_r = d.tab_pad_r if self._closable else d.tab_pad_l
        self.setMinimumWidth(text_w + close_w + d.tab_pad_l + pad_r + 6)

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._apply_style()

    def _emit_close(self) -> None:
        self.close_requested.emit(self.mode)

    def _apply_style(self) -> None:
        d = self._density
        self.setStyleSheet(
            _tab_qss(
                d.tab_font,
                d.tab_radius,
                active=self._active,
                hover=self._hovered and not self._active,
            )
        )

    def enterEvent(self, event):
        self._hovered = True
        if self._closable:
            self._close.setStyleSheet(_CLOSE_VISIBLE)
        self._apply_style()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        if self._closable:
            self._close.setStyleSheet(_CLOSE_HIDDEN)
        self._apply_style()
        super().leaveEvent(event)

    def _resync_traffic_lights(self) -> None:
        try:
            from PySide6.QtCore import QEvent, QTimer
            from PySide6.QtWidgets import QApplication as _QApp

            self.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
            _QApp.sendEvent(self, QEvent(QEvent.Type.Leave))
            self._hovered = False
            if self._closable:
                self._close.setStyleSheet(_CLOSE_HIDDEN)
            self._apply_style()

            def _resync_lights() -> None:
                from steempeg.ui.window_chrome import (
                    force_app_cursor_resync,
                    refresh_traffic_lights_under_cursor,
                )

                win = self.window()
                if win is not None:
                    refresh_traffic_lights_under_cursor(win)
                force_app_cursor_resync()

            QTimer.singleShot(0, _resync_lights)
        except Exception:
            pass

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
            self._dragging = False
            self.activated.emit(self.mode)
            event.accept()
            # Clicking a tab can leave WA_UnderMouse stuck here so the title-bar
            # traffic lights never get HoverEnter until they are clicked.
            self._resync_traffic_lights()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._closable:
            return super().mouseMoveEvent(event)
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return super().mouseMoveEvent(event)
        if self._dragging:
            return
        if (event.position().toPoint() - self._drag_start).manhattanLength() < (
            QApplication.startDragDistance()
        ):
            return
        self._dragging = True
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(LIBRARY_TAB_MIME, self.mode.encode("utf-8"))
        drag.setMimeData(mime)
        pix = self.grab()
        if not pix.isNull():
            drag.setPixmap(pix)
            # Hotspot at the grab X, near the top — like a browser tab: the
            # cursor stays on the strip while the ghost hangs below it.
            hot = event.position().toPoint()
            drag.setHotSpot(QPoint(max(0, min(hot.x(), pix.width() - 1)), 6))
        drag.exec(Qt.DropAction.MoveAction)
        self._dragging = False
        self.update()


class LibraryTabStrip(QWidget):
    """Drop target for the whole chrome tab row (browser-style).

    Hit-tests X along the strip — not a tiny tab rect — and lights a caret
    between tabs. Layout stays flush with the old tab row (no extra pad).
    """

    tab_moved = Signal(str, int)  # source mode, insert index among remaining tabs

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("libraryTabStrip")
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("QWidget#libraryTabStrip { background: transparent; }")
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(8)
        self._caret = QFrame(self)
        self._caret.setObjectName("libraryTabInsertCaret")
        self._caret.setFixedWidth(_CARET_W)
        self._caret.setStyleSheet(
            f"QFrame#libraryTabInsertCaret {{"
            f" background-color: {tok.ACCENT_PRIMARY}; border: none; border-radius: 2px; }}"
        )
        self._caret.hide()
        self._caret.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    @property
    def tabs_layout(self) -> QHBoxLayout:
        return self._row

    def _tab_widgets(self) -> list[LibraryTabWidget]:
        tabs: list[LibraryTabWidget] = []
        for i in range(self._row.count()):
            item = self._row.itemAt(i)
            w = item.widget() if item is not None else None
            if isinstance(w, LibraryTabWidget):
                tabs.append(w)
        return tabs

    def _insert_index_at(self, local_x: int, source: str) -> int:
        """Index among tabs *excluding* ``source`` (where source will land)."""
        others = [t for t in self._tab_widgets() if t.mode != source]
        if not others:
            return 0
        for i, tab in enumerate(others):
            mid = tab.geometry().center().x()
            if local_x < mid:
                return i
        return len(others)

    def _place_caret(self, insert_idx: int, source: str) -> None:
        others = [t for t in self._tab_widgets() if t.mode != source]
        tabs = self._tab_widgets()
        if not tabs:
            self._caret.hide()
            return
        height = max((t.height() for t in tabs), default=32)
        y = others[0].geometry().top() if others else tabs[0].geometry().top()
        if not others:
            x = 0
        elif insert_idx <= 0:
            x = others[0].geometry().left() - 4
        elif insert_idx >= len(others):
            x = others[-1].geometry().right() + 2
        else:
            x = others[insert_idx].geometry().left() - 4
        x = max(0, x)
        self._caret.setGeometry(QRect(x, y, _CARET_W, height))
        self._caret.show()
        self._caret.raise_()

    def _hide_caret(self) -> None:
        self._caret.hide()

    def dragEnterEvent(self, event):
        if not event.mimeData().hasFormat(LIBRARY_TAB_MIME):
            return
        source = _tab_mode_from_mime(event.mimeData())
        if not source:
            return
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        idx = self._insert_index_at(int(event.position().x()), source)
        self._place_caret(idx, source)

    def dragMoveEvent(self, event):
        if not event.mimeData().hasFormat(LIBRARY_TAB_MIME):
            return
        source = _tab_mode_from_mime(event.mimeData())
        if not source:
            return
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        idx = self._insert_index_at(int(event.position().x()), source)
        self._place_caret(idx, source)

    def dragLeaveEvent(self, event):
        self._hide_caret()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        source = _tab_mode_from_mime(event.mimeData())
        self._hide_caret()
        if not source:
            return
        idx = self._insert_index_at(int(event.position().x()), source)
        self.tab_moved.emit(source, idx)
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()


def _tab_mode_from_mime(mime: QMimeData) -> str:
    raw = mime.data(LIBRARY_TAB_MIME)
    if not raw:
        return ""
    try:
        return bytes(raw).decode("utf-8")
    except Exception:
        return ""
