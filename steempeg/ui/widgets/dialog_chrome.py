"""Shared frameless dialog chrome — a custom title bar (logo + title + close dot)
that matches the main window's SteempegTitleBar, plus a draggable rounded card.

Dialogs subclass ``SteempegDialog`` and add their widgets to ``self.content_layout``
instead of building their own outer layout, so every window shares one top bar.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QPoint, QRectF, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from steempeg.infra.paths import get_resource_path
from steempeg.ui import design_tokens as tok
from steempeg.ui.window_chrome import _TrafficLight

_SIDE_RAIL_PX = 2
_CARD_RADIUS_PX = 10


class _DialogTitleBar(QWidget):
    """Logo + title on the left, optional minimize + close dots on the right. Draggable."""

    close_requested = Signal()

    def __init__(
        self,
        dialog: QDialog,
        *,
        title: str,
        bar_color: str,
        show_minimize: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._dialog = dialog
        self._drag_offset: QPoint | None = None
        self.setObjectName("SteempegDialogBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(tok.TITLE_BAR_HEIGHT)

        bar_h = tok.TITLE_BAR_HEIGHT
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 0, 10, 0)
        root.setSpacing(0)

        icon_path = get_resource_path("logo.png")
        if os.path.isfile(icon_path):
            icon_lbl = QLabel()
            icon_lbl.setPixmap(
                QPixmap(icon_path).scaled(
                    16, 16, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                )
            )
            icon_lbl.setFixedSize(16, bar_h)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)
            root.addWidget(icon_lbl)
            root.addSpacing(7)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("SteempegDialogTitle")
        font = QFont()
        font.setFamilies(["Cascadia UI", "Segoe UI Variable", "Segoe UI"])
        font.setPointSize(tok.FONT_TITLE_SIZE)
        font.setWeight(QFont.Weight.DemiBold)
        title_lbl.setFont(font)
        title_lbl.setFixedHeight(bar_h)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        title_lbl.setContentsMargins(0, 0, 0, 2)
        root.addWidget(title_lbl)

        root.addStretch(1)

        if show_minimize:
            self.btn_minimize = _TrafficLight(
                tok.TRAFFIC_MINIMIZE, tok.TRAFFIC_MINIMIZE_HOVER, "minimize"
            )
            self.btn_minimize.clicked.connect(dialog.showMinimized)
            root.addWidget(self.btn_minimize, 0, Qt.AlignmentFlag.AlignVCenter)
            root.addSpacing(6)
        else:
            self.btn_minimize = None

        self.btn_close = _TrafficLight(tok.TRAFFIC_CLOSE, tok.TRAFFIC_CLOSE_HOVER, "close")
        self.btn_close.clicked.connect(self.close_requested.emit)
        root.addWidget(self.btn_close, 0, Qt.AlignmentFlag.AlignVCenter)

        self.setStyleSheet(
            f"""
            QWidget#SteempegDialogBar {{
                background-color: {bar_color};
                border-top-left-radius: {_CARD_RADIUS_PX}px;
                border-top-right-radius: {_CARD_RADIUS_PX}px;
                border-bottom: 1px solid {tok.BORDER_SUBTLE};
            }}
            QLabel#SteempegDialogTitle {{
                color: {tok.TEXT_TITLE};
                font-family: {tok.FONT_UI};
                background: transparent;
            }}
            """
        )

    # --- Drag the frameless dialog by its title bar -----------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Wayland/X11: compositor-owned move (manual QWidget.move is often ignored).
            handle = self._dialog.windowHandle()
            if handle is not None:
                try:
                    if handle.startSystemMove():
                        event.accept()
                        return
                except Exception:
                    pass
            self._drag_offset = (
                event.globalPosition().toPoint() - self._dialog.frameGeometry().topLeft()
            )
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._dialog.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class _DialogCard(QWidget):
    """Rounded shell painted with antialiasing — avoids jagged QRegion masks."""

    def __init__(self, parent=None, *, radius: int = _CARD_RADIUS_PX, fill: str = "#1a1a1a"):
        super().__init__(parent)
        self._radius = float(radius)
        self._fill = QColor(fill)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_fill(self, color: str) -> None:
        self._fill = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        # Inset by 0.5px so the AA edge sits on pixel centers (less staircasing).
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillPath(path, self._fill)


class SteempegDialog(QDialog):
    """Frameless dialog with the shared Steempeg title bar.

    Subclasses add their content to ``self.content_layout``. Colors default to the
    active chrome theme so dialogs match the main window's title bar / background.

    ``suppress_map=True`` (portable prewarm): the dialog is demoted to a plain
    ``Qt.Widget`` inside a hidden garage — no top-level HWND, so Windows never
    flashes a native «Steempeg» caption. Call ``release_map_suppression(host)``
    before ``exec()`` to promote it back to a real frameless dialog.
    """

    def __init__(
        self,
        title: str,
        parent=None,
        *,
        bar_color: str | None = None,
        bg_color: str | None = None,
        content_margins: tuple[int, int, int, int] = (16, 16, 16, 16),
        show_minimize: bool = False,
        suppress_map: bool = False,
    ):
        super().__init__(parent)
        self._map_suppressed = bool(suppress_map)
        self._map_host = None
        if self._map_suppressed:
            # Demote BEFORE any polish/winId — embedded widget, not a top-level window.
            self.setWindowFlags(Qt.WindowType.Widget)
            self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        else:
            self.setWindowFlags(
                Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
            )

        theme = tok.chrome_theme_colors(tok.DEFAULT_CHROME_THEME)
        bar_color = bar_color or theme["title_bar"]
        bg_color = bg_color or theme["app_bg"]
        self._bar_color = bar_color
        self._bg_color = bg_color

        self.setWindowTitle(title)
        # Translucent only when allowed on screen — otherwise DWM paints a gray ghost.
        if not self._map_suppressed:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._card = _DialogCard(self, radius=_CARD_RADIUS_PX, fill=bar_color)
        self._card.setObjectName("SteempegDialogCard")
        outer.addWidget(self._card)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        self._title_bar = _DialogTitleBar(
            self, title=title, bar_color=bar_color, show_minimize=show_minimize
        )
        self._title_bar.close_requested.connect(self.reject)
        card_layout.addWidget(self._title_bar)

        body_host = QWidget(self._card)
        body_host.setObjectName("SteempegDialogBodyHost")
        body_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        body_layout = QVBoxLayout(body_host)
        body_layout.setContentsMargins(_SIDE_RAIL_PX, 0, _SIDE_RAIL_PX, _SIDE_RAIL_PX)
        body_layout.setSpacing(0)

        content = QWidget(body_host)
        content.setObjectName("SteempegDialogContent")
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(*content_margins)
        self.content_layout.setSpacing(12)
        body_layout.addWidget(content, 1)
        card_layout.addWidget(body_host, 1)

        self._apply_card_chrome(bar_color, bg_color)
        self._comfort_size: tuple[int, int] | None = None
        # Never use QRegion masks for rounding — they are binary and look jagged.
        self.clearMask()

        if self._map_suppressed:
            self.hide()

    def setVisible(self, visible: bool) -> None:
        if self._map_suppressed and visible:
            return
        super().setVisible(visible)

    def _park_as_embedded_widget(self, garage: QWidget | None = None) -> None:
        """First-time park: embed as Qt.Widget in the garage (no top-level HWND).

        Only used during prewarm construction. After the first real open we keep a
        Dialog HWND and use ``_park_hidden_dialog`` instead — demoting every close
        forced a full setWindowFlags recreate on each Add a Clip (slow open).
        """
        self._map_suppressed = True
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setWindowFlags(Qt.WindowType.Widget)
        if garage is not None:
            self.setParent(garage)
        self.hide()

    def _park_hidden_dialog(self) -> None:
        """Keep the Dialog HWND alive but unmapped between opens (fast reopen)."""
        self._map_suppressed = True
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        # Do NOT clear WA_TranslucentBackground here — after winId() exists,
        # flipping it off/on leaves opaque black corners on the next show.
        self.hide()

    # Back-compat name used by portable sheets / chrome.
    def _park_offscreen(self) -> None:
        flags = self.windowFlags()
        if flags & Qt.WindowType.Dialog:
            self._park_hidden_dialog()
        else:
            self._park_as_embedded_widget(self.parentWidget())

    def release_map_suppression(self, host: QWidget | None = None) -> None:
        """Promote / unsuspend immediately before exec()/show()."""
        if host is not None:
            self._map_host = host
        host = self._map_host or host
        flags = self.windowFlags()
        already_dialog = bool(flags & Qt.WindowType.Dialog)

        self._map_suppressed = False
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, False)

        if not already_dialog:
            # One-time promote from garage Widget → frameless Dialog.
            if host is not None:
                self.setParent(host)
            self.setWindowFlags(
                Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
            )
            self.hide()

        # Must be True before the window is exposed — opaque HWND = black corners
        # around the rounded card.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setWindowOpacity(1.0)

    def silent_promote_for_prewarm(self, host: QWidget) -> None:
        """After garage build: create the Dialog HWND once while still unmapped.

        Pays the setWindowFlags cost during idle startup so the first Add a Clip
        click does not stall on HWND creation.
        """
        if not self._map_suppressed:
            return
        if self.windowFlags() & Qt.WindowType.Dialog:
            return
        self._map_host = host
        # Stay DontShowOnScreen for the entire promote — no visible flash.
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.setParent(host)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        # Build the HWND already translucent so later opens keep rounded corners.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setWindowOpacity(0.0)
        self.hide()
        self._map_suppressed = True
        # Touch winId only while DontShowOnScreen is set so DWM does not map us.
        try:
            _ = int(self.winId())
        except Exception:
            pass
        self.hide()
        self.setWindowOpacity(0.0)

    def set_comfort_size(self, width: int, height: int) -> None:
        """Design size at desktop density; auto-shrinks on Deck-class screens."""
        self._comfort_size = (int(width), int(height))
        self._apply_scaled_size()

    def _apply_scaled_size(self) -> None:
        if not self._comfort_size:
            return
        from steempeg.ui.ui_density import scaled_dialog_size

        w, h = scaled_dialog_size(*self._comfort_size, parent=self.parent())
        self.setFixedSize(w, h)

    def showEvent(self, event):
        if self._map_suppressed:
            event.ignore()
            self.hide()
            return
        super().showEvent(event)
        self._apply_scaled_size()
        self._center_on_parent()
        self.clearMask()

    def _center_on_parent(self) -> None:
        """Place the dialog on the parent (or available screen) so HD/Deck windows stay in view."""
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication, QWidget

        ref: QWidget | None = None
        parent = self.parentWidget()
        if isinstance(parent, QWidget) and parent.isVisible():
            ref = parent.window() if parent.window() is not None else parent
        if ref is None:
            aw = QApplication.activeWindow()
            if isinstance(aw, QWidget):
                ref = aw

        if ref is not None and ref.isVisible():
            geo = ref.frameGeometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2
        else:
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                return
            avail = screen.availableGeometry()
            x = avail.x() + (avail.width() - self.width()) // 2
            y = avail.y() + (avail.height() - self.height()) // 2

        # Keep fully inside the screen that contains the reference point.
        screen = QGuiApplication.screenAt(ref.frameGeometry().center()) if ref else None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            x = max(avail.x(), min(x, avail.x() + avail.width() - self.width()))
            y = max(avail.y(), min(y, avail.y() + avail.height() - self.height()))
        self.move(x, y)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.clearMask()

    def _apply_card_chrome(self, bar_color: str, bg_color: str) -> None:
        """Title-bar-colored side rails so the shell does not melt into the desktop."""
        if hasattr(self._card, "set_fill"):
            self._card.set_fill(bar_color)
        inner_radius = max(_CARD_RADIUS_PX - _SIDE_RAIL_PX, 0)
        # Card fill is painted in _DialogCard.paintEvent (antialiased).
        # Children keep stylesheet radii so their opaque rects match the shell.
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: transparent;
            }}
            QWidget#SteempegDialogCard {{
                background-color: transparent;
                border: none;
            }}
            QWidget#SteempegDialogBodyHost {{
                background-color: transparent;
            }}
            QWidget#SteempegDialogContent {{
                background-color: {bg_color};
                border-bottom-left-radius: {inner_radius}px;
                border-bottom-right-radius: {inner_radius}px;
            }}
            """
        )
