"""Clicking a popup's opener again closes the popup instead of reopening it.

Qt replays the press that dismisses a ``Qt.Popup`` onto the widget underneath —
so a second click on the button / combo that opened it closed and instantly
reopened it. ``QComboBox``'s own list popup suppresses that replay only for its
combo; this does the same for every popup (Big/Small/List, preset dual popup,
filter menus …) by remembering which widget took the opening LMB press.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QWidget

# A popup shown longer than this after the last press was opened some other way
# (keyboard, timer) — it has no opener to guard.
_OPENER_WINDOW_S = 0.6


class _PopupOpenerDismissFilter(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._press_widget: QWidget | None = None
        self._press_at = 0.0

    def eventFilter(self, obj, event):  # noqa: N802
        etype = event.type()
        if etype == QEvent.Type.MouseButtonPress and isinstance(obj, QWidget):
            self._on_press(obj, event)
        elif etype == QEvent.Type.Show and isinstance(obj, QWidget):
            if obj.isWindow() and obj.windowType() == Qt.WindowType.Popup:
                self._on_popup_shown(obj)
        return False

    def _on_press(self, obj: QWidget, event) -> None:
        popup = QApplication.activePopupWidget()
        if popup is None:
            now = time.monotonic()
            prev = self._press_widget
            # An ignored press propagates child → parent through the app filter;
            # keep the first (deepest) receiver as the opener.
            try:
                if prev is not None and now - self._press_at < 0.005 and obj.isAncestorOf(prev):
                    return
            except RuntimeError:
                pass
            if event.button() == Qt.MouseButton.LeftButton:
                self._press_widget = obj
                self._press_at = now
            else:
                self._press_widget = None
            return
        if obj is not popup:
            return
        on_opener = False
        if event.button() == Qt.MouseButton.LeftButton:
            gpos = event.globalPosition().toPoint()
            if not popup.rect().contains(popup.mapFromGlobal(gpos)):
                opener = getattr(popup, "_steempeg_popup_opener", None)
                hit = QApplication.widgetAt(gpos)
                try:
                    on_opener = (
                        opener is not None
                        and hit is not None
                        and (hit is opener or opener.isAncestorOf(hit))
                    )
                except RuntimeError:
                    on_opener = False
        popup.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay, on_opener)

    def _on_popup_shown(self, popup: QWidget) -> None:
        opener = self._press_widget
        if opener is not None and time.monotonic() - self._press_at > _OPENER_WINDOW_S:
            opener = None
        popup._steempeg_popup_opener = opener


def install_popup_opener_dismiss(app: QApplication) -> None:
    filt = _PopupOpenerDismissFilter(app)
    app.installEventFilter(filt)
    app._steempeg_popup_opener_dismiss = filt
