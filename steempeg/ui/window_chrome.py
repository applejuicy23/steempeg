"""Custom main-window chrome.

Approach: keep the window fully NATIVE (all Win32 styles: frame, shadow, Aero
Snap, min/max animations) and only intercept WM_NCCALCSIZE so Windows stops
*painting* its title bar. We then draw our own SteempegTitleBar in the client
area and route drag / resize through WM_NCHITTEST. This is how VS Code / Windows
Terminal do frameless — unlike stripping WS_CAPTION, it preserves snap & animations.
"""
from __future__ import annotations

import os
import sys

import ctypes
from ctypes import POINTER, cast, wintypes

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.paths import get_resource_path
from steempeg.ui.icon_utils import (
    app_logo_pixmap,
    apply_square_icon,
    chrome_icon_slot_size,
)
from steempeg.services.release_catalog import COLOR_VERSION_NEW
from steempeg.ui import design_tokens as tok
from steempeg.ui.icon_assets import (
    title_bar_info_icons,
    title_bar_settings_icons,
    title_bar_update_pixmap,
)

_CONTROL_STRIP_WIDTH = 84

# Win32 constants
_GWL_STYLE = -16
_WS_CAPTION = 0x00C00000
_WS_THICKFRAME = 0x00040000
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000
_WS_SYSMENU = 0x00080000

_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001
_SWP_NOZORDER = 0x0004
_SWP_FRAMECHANGED = 0x0020

_WM_NCCALCSIZE = 0x0083
_WM_NCHITTEST = 0x0084
_WM_NCLBUTTONDOWN = 0x00A1
_WM_SYSCOMMAND = 0x0112

_SC_CLOSE = 0xF060
_SC_MINIMIZE = 0xF020
_SC_MAXIMIZE = 0xF030
_SC_RESTORE = 0xF120

_SW_SHOWMAXIMIZED = 3


class _WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.UINT),
        ("flags", wintypes.UINT),
        ("showCmd", wintypes.UINT),
        ("ptMinPosition", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("rcNormalPosition", wintypes.RECT),
    ]

_SM_CXSIZEFRAME = 32
_SM_CXPADDEDBORDER = 92

_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_BORDER_COLOR = 34
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_DONOTROUND = 1
_DWMWA_COLOR_NONE = 0xFFFFFFFE  # removes the window border line entirely (Win11)

HTCLIENT = 1
HTCAPTION = 2
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [
        ("rgrc", _RECT * 3),
        ("lppos", ctypes.c_void_p),
    ]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


class _TrafficLight(QPushButton):
    """macOS-style window control dot with a thin painted glyph (no Unicode junk)."""

    def __init__(self, color: str, hover_color: str, glyph: str = "close", parent=None):
        super().__init__(parent)
        self._base = color
        self._hover = hover_color
        # "close" | "minimize" | "maximize"
        self._glyph = glyph
        self._hovered = False
        self.setFixedSize(13, 13)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setText("")
        self._apply_style()

    def _apply_style(self) -> None:
        bg = self._hover if self._hovered else self._base
        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {bg};
                border: none;
                border-radius: 6px;
                padding: 0;
                margin: 0;
            }}
            """
        )

    def _set_hovered(self, hovered: bool) -> None:
        if self._hovered == hovered:
            return
        self._hovered = hovered
        self._apply_style()
        self.update()

    def enterEvent(self, event):
        self._set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._set_hovered(False)
        super().leaveEvent(event)

    def hideEvent(self, event):
        # Hide/park (portable sheets) often skips leaveEvent → glyph stuck on next open.
        self._set_hovered(False)
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        # Park/unpark (portable warm sheets) often leaves underMouse() true on Windows
        # even when the pointer is elsewhere — never trust it on first map.
        self._set_hovered(False)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._hovered:
            return

        painter = QPainter(self)
        # Hairlines stay crisp without AA mush on a 13px dot.
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        if self._glyph == "close":
            color = QColor(35, 14, 12, 200)
        elif self._glyph == "minimize":
            color = QColor(50, 36, 6, 200)
        else:
            color = QColor(10, 42, 16, 200)

        pen = QPen(color)
        pen.setWidthF(1.0)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        # Close / minimize stay near the rim; maximize glyphs sit smaller in the center.
        inset = 3.0
        left = inset
        right = self.width() - inset
        top = inset
        bottom = self.height() - inset

        if self._glyph == "close":
            painter.drawLine(QPointF(left, top), QPointF(right, bottom))
            painter.drawLine(QPointF(right, top), QPointF(left, bottom))
        elif self._glyph == "minimize":
            painter.drawLine(QPointF(left, cy), QPointF(right, cy))
        elif self._glyph == "restore":
            # Two offset squares; group bbox centered on (cx, cy).
            s = 3.0
            gap = 2.0
            group = s + gap
            ox = cx - group / 2.0
            oy = cy - group / 2.0
            back = QRectF(ox + gap, oy, s, s)
            front = QRectF(ox, oy + gap, s, s)
            painter.drawRect(back)
            painter.fillRect(
                QRectF(front.left() + 0.5, front.top() + 0.5, s - 1.0, s - 1.0),
                QColor(self._hover),
            )
            painter.drawRect(front)
        else:
            # True geometric center: path midpoint == widget midpoint. No optical nudge.
            side = 5.0
            painter.drawRect(QRectF(cx - side / 2.0, cy - side / 2.0, side, side))

        painter.end()


class _TitleBarUpdateButton(QPushButton):
    """Portable title-bar Updates control — ``update.png`` in a circle.

    Spins continuously (clockwise) while hovered, pressed, or marked busy
    (Update Center open). Spin is not a CSS trick — the pixmap is rotated in
    ``paintEvent``.
    """

    _TICK_MS = 16
    _DEG_PER_TICK = 7.5  # clockwise (top moves left→right)

    def __init__(self, *, hit_px: int, icon_px: int, parent=None):
        super().__init__(parent)
        self.setObjectName("TitleBarCheckUpdates")
        self.setFlat(True)
        self.setFixedSize(hit_px, hit_px)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("Check for updates")
        self._hit_r = hit_px // 2
        self._angle = 0.0
        self._busy = False
        self._idle_pix = title_bar_update_pixmap("#b8b8b8", icon_px)
        self._hot_pix = title_bar_update_pixmap("#e8e8e8", icon_px)
        self._timer = QTimer(self)
        self._timer.setInterval(self._TICK_MS)
        self._timer.timeout.connect(self._on_tick)

    def set_busy(self, busy: bool) -> None:
        """Keep spinning while Update Center / check is in flight."""
        self._busy = bool(busy)
        self._sync_spin()
        self.update()

    def clear_hover_spin(self) -> None:
        """After a modal eats Leave — re-evaluate spin without underMouse stuck."""
        self.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        self._sync_spin()

    def _wants_spin(self) -> bool:
        return bool(self._busy or self.isDown() or self.underMouse())

    def _sync_spin(self) -> None:
        if self._wants_spin():
            if not self._timer.isActive():
                self._timer.start()
            return
        if self._timer.isActive():
            self._timer.stop()
        if self._angle != 0.0:
            self._angle = 0.0
            self.update()

    def _on_tick(self) -> None:
        if not self._wants_spin():
            self._sync_spin()
            return
        self._angle = (self._angle + self._DEG_PER_TICK) % 360.0
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        self._sync_spin()

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self._sync_spin()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        super().mousePressEvent(event)
        self._sync_spin()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        self._sync_spin()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        hot = bool(self._busy or self.isDown() or self.underMouse())
        if hot:
            alpha = 31 if (self.isDown() or self._busy) else 20
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, alpha))
            painter.drawEllipse(0, 0, self.width() - 1, self.height() - 1)
        pix = self._hot_pix if hot else self._idle_pix
        if pix.isNull():
            painter.end()
            return
        # Rotate around widget + glyph center (float offsets; no int truncation).
        cx = self.width() * 0.5
        cy = self.height() * 0.5
        dpr = max(float(pix.devicePixelRatio()), 1.0)
        logical_w = pix.width() / dpr
        logical_h = pix.height() / dpr
        painter.translate(cx, cy)
        painter.rotate(self._angle)
        painter.drawPixmap(QPointF(-logical_w * 0.5, -logical_h * 0.5), pix)
        painter.end()


class SteempegTitleBar(QWidget):
    """Top chrome: branding left, window controls right (Windows order)."""

    close_requested = Signal()
    minimize_requested = Signal()
    maximize_requested = Signal()
    about_requested = Signal()
    settings_requested = Signal()
    check_updates_requested = Signal()
    update_available_clicked = Signal()

    def __init__(self, window: QWidget, *, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self._window = window
        self.setObjectName("SteempegTitleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(tok.TITLE_BAR_HEIGHT)
        # Caption drag area must stay arrow; only the shell tools use hand.
        self.setCursor(Qt.CursorShape.ArrowCursor)

        bar_h = tok.TITLE_BAR_HEIGHT
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 0, 12, 0)
        root.setSpacing(0)

        # Square slot only — a 16×bar_h label stretches/clips the logo on short HD bars.
        icon_sz = chrome_icon_slot_size(16, bar_height=bar_h)
        pixmap = app_logo_pixmap(icon_sz)
        if pixmap is not None and not pixmap.isNull():
            icon_lbl = QLabel()
            apply_square_icon(icon_lbl, pixmap, icon_sz)
            icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            root.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
            root.addSpacing(7)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("TitleBarTitle")
        font = QFont()
        font.setFamilies(["Cascadia UI", "Segoe UI Variable", "Segoe UI"])
        font.setPointSize(tok.FONT_TITLE_SIZE)
        font.setWeight(QFont.Weight.DemiBold)
        title_lbl.setFont(font)
        title_lbl.setFixedHeight(bar_h)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        title_lbl.setContentsMargins(0, 0, 0, 2)
        title_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        root.addWidget(title_lbl)

        if subtitle:
            sub_lbl = QLabel(subtitle)
            sub_lbl.setObjectName("TitleBarSubtitle")
            sub_font = QFont(font)
            sub_font.setWeight(QFont.Weight.Normal)
            sub_font.setPointSize(tok.FONT_SUBTITLE_SIZE)
            sub_lbl.setFont(sub_font)
            sub_lbl.setFixedHeight(bar_h)
            sub_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            sub_lbl.setContentsMargins(0, 0, 0, 2)
            sub_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            root.addWidget(sub_lbl)

        # Portable shell tools: (i) near version | Settings + Check for updates.
        # Hidden until ``set_shell_tools_visible(True)`` from the portable theatre path.
        # QPushButton (not QToolButton) — Windows styles offset QToolButton icons inside
        # the hover circle, which looked like a crooked hitbox on the About (i).
        _icon_px = 16
        _hit_px = 22
        _hit_r = _hit_px // 2

        def _shell_icon_btn(object_name: str, idle: object, tooltip: str) -> QPushButton:
            btn = QPushButton()
            btn.setObjectName(object_name)
            btn.setIcon(idle)
            btn.setIconSize(QSize(_icon_px, _icon_px))
            btn.setFixedSize(_hit_px, _hit_px)
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setToolTip(tooltip)
            btn.installEventFilter(self)
            return btn

        self._about_info_icon_idle, self._about_info_icon_hot = title_bar_info_icons(_icon_px)
        self.btn_about_info = _shell_icon_btn(
            "TitleBarAboutInfo", self._about_info_icon_idle, "About"
        )
        self.btn_about_info.clicked.connect(self.about_requested.emit)

        self._settings_icon_idle, self._settings_icon_hot = title_bar_settings_icons(_icon_px)
        self.btn_title_settings = _shell_icon_btn(
            "TitleBarSettings", self._settings_icon_idle, "Settings"
        )
        self.btn_title_settings.clicked.connect(self.settings_requested.emit)

        self.btn_check_updates = _TitleBarUpdateButton(hit_px=_hit_px, icon_px=_icon_px)
        self.btn_check_updates.clicked.connect(self.check_updates_requested.emit)

        divider = QFrame()
        divider.setObjectName("TitleBarShellDivider")
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFixedWidth(1)
        divider.setFixedHeight(14)
        divider.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        shell_tools = QWidget()
        shell_tools.setObjectName("TitleBarShellTools")
        shell_tools.setFixedHeight(bar_h)
        shell_tools_lay = QHBoxLayout(shell_tools)
        shell_tools_lay.setContentsMargins(0, 0, 0, 0)
        shell_tools_lay.setSpacing(0)
        # Sit (i) tight against vXX.X — was a wide gap with old spacing + subtitle pad.
        shell_tools_lay.addSpacing(2)
        shell_tools_lay.addWidget(
            self.btn_about_info, 0, Qt.AlignmentFlag.AlignVCenter
        )
        shell_tools_lay.addSpacing(6)
        shell_tools_lay.addWidget(divider, 0, Qt.AlignmentFlag.AlignVCenter)
        shell_tools_lay.addSpacing(6)
        shell_tools_lay.addWidget(
            self.btn_title_settings, 0, Qt.AlignmentFlag.AlignVCenter
        )
        shell_tools_lay.addSpacing(4)
        shell_tools_lay.addWidget(
            self.btn_check_updates, 0, Qt.AlignmentFlag.AlignVCenter
        )
        self._shell_tools = shell_tools
        self._shell_hit_radius = _hit_r
        shell_tools.hide()
        root.addWidget(shell_tools)

        # Compact Health-style chip; hidden until a silent check finds a newer release.
        self.btn_update_available = QPushButton("Update Available")
        self.btn_update_available.setObjectName("TitleBarUpdateAvailable")
        self.btn_update_available.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_update_available.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_update_available.setFixedHeight(20)
        self.btn_update_available.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        self.btn_update_available.clicked.connect(self.update_available_clicked.emit)
        self.btn_update_available.hide()
        root.addSpacing(8)
        root.addWidget(self.btn_update_available, 0, Qt.AlignmentFlag.AlignVCenter)

        root.addStretch(1)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.btn_minimize = _TrafficLight(tok.TRAFFIC_MINIMIZE, tok.TRAFFIC_MINIMIZE_HOVER, "minimize")
        self.btn_maximize = _TrafficLight(tok.TRAFFIC_MAXIMIZE, tok.TRAFFIC_MAXIMIZE_HOVER, "maximize")
        self.btn_close = _TrafficLight(tok.TRAFFIC_CLOSE, tok.TRAFFIC_CLOSE_HOVER, "close")
        controls.addWidget(self.btn_minimize, 0, Qt.AlignmentFlag.AlignVCenter)
        controls.addWidget(self.btn_maximize, 0, Qt.AlignmentFlag.AlignVCenter)
        controls.addWidget(self.btn_close, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(controls)

        self.btn_close.clicked.connect(self.close_requested.emit)
        self.btn_minimize.clicked.connect(self.minimize_requested.emit)
        self.btn_maximize.clicked.connect(self.maximize_requested.emit)

        self._apply_bar_style(tok.BG_TITLE_BAR)
        self.set_update_available(False)

    def eventFilter(self, watched, event):
        pairs = (
            (
                getattr(self, "btn_about_info", None),
                getattr(self, "_about_info_icon_idle", None),
                getattr(self, "_about_info_icon_hot", None),
            ),
            (
                getattr(self, "btn_title_settings", None),
                getattr(self, "_settings_icon_idle", None),
                getattr(self, "_settings_icon_hot", None),
            ),
        )
        for btn, idle, hot in pairs:
            if btn is None or watched is not btn or idle is None or hot is None:
                continue
            et = event.type()
            if et in (QEvent.Type.Enter, QEvent.Type.MouseButtonPress):
                btn.setIcon(hot)
            elif et == QEvent.Type.Leave:
                btn.setIcon(idle)
            elif et == QEvent.Type.MouseButtonRelease:
                btn.setIcon(hot if btn.underMouse() else idle)
            break
        return super().eventFilter(watched, event)

    def clear_shell_tool_hover(self) -> None:
        """Reset About/Settings hot icon + cursor after a modal eats Leave events."""
        pairs = (
            (
                getattr(self, "btn_about_info", None),
                getattr(self, "_about_info_icon_idle", None),
            ),
            (
                getattr(self, "btn_title_settings", None),
                getattr(self, "_settings_icon_idle", None),
            ),
        )
        for btn, idle in pairs:
            if btn is None:
                continue
            try:
                if idle is not None:
                    btn.setIcon(idle)
                btn.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
                QApplication.sendEvent(btn, QEvent(QEvent.Type.Leave))
                btn.unsetCursor()
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
            except RuntimeError:
                pass
        for name in ("btn_check_updates", "btn_update_available"):
            btn = getattr(self, name, None)
            if btn is None:
                continue
            try:
                if hasattr(btn, "clear_hover_spin"):
                    btn.clear_hover_spin()
                btn.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
                QApplication.sendEvent(btn, QEvent(QEvent.Type.Leave))
                btn.unsetCursor()
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
            except RuntimeError:
                pass
        try:
            self.unsetCursor()
            parent = self.window()
            if parent is not None:
                parent.unsetCursor()
        except RuntimeError:
            pass
        # Drop any leftover override cursors from modal open.
        app = QApplication.instance()
        if app is not None:
            while app.overrideCursor() is not None:
                app.restoreOverrideCursor()

    def _title_bar_press_is_interactive(self, pos: QPoint) -> bool:
        hit = self.childAt(pos)
        while hit is not None and hit is not self:
            if isinstance(hit, QAbstractButton):
                return True
            hit = hit.parentWidget()
        return False

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if self._title_bar_press_is_interactive(pos):
            super().mousePressEvent(event)
            return

        # Native caption drag. Used on Windows too: with buttons in the bar we
        # return HTCLIENT from NCHITTEST, so Qt must start the drag itself.
        if os.name == "nt":
            try:
                hwnd = int(self._window.winId())
                ctypes.windll.user32.ReleaseCapture()
                ctypes.windll.user32.SendMessageW(
                    hwnd, _WM_NCLBUTTONDOWN, HTCAPTION, 0
                )
                event.accept()
                return
            except Exception:
                pass

        # Linux xcb/XWayland: manual move via the shell filter (no startSystemMove —
        # it warps the cursor to the last edge-resize grab point).
        if sys.platform != "win32" and _linux_prefer_manual_resize():
            filt = getattr(self._window, "_linux_edge_resize_filter", None)
            if filt is not None and hasattr(filt, "begin_title_drag"):
                filt.begin_title_drag(event.globalPosition().toPoint())
                event.accept()
                return

        if sys.platform != "win32":
            handle = self._window.windowHandle()
            if handle is not None:
                try:
                    if handle.startSystemMove():
                        event.accept()
                        return
                except Exception:
                    pass
            event.accept()
            return

        handle = self._window.windowHandle()
        if handle is not None:
            handle.startSystemMove()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if sys.platform != "win32":
            _linux_refresh_traffic_lights(self._window)
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            if not self._title_bar_press_is_interactive(pos):
                self.maximize_requested.emit()
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def _apply_bar_style(self, bg_color: str) -> None:
        self._bar_bg = bg_color
        self.setStyleSheet(
            f"""
            QWidget#SteempegTitleBar {{
                background-color: {bg_color};
                border-bottom: 1px solid {tok.BORDER_SUBTLE};
            }}
            QLabel#TitleBarTitle {{
                color: {tok.TEXT_TITLE};
                font-family: {tok.FONT_UI};
            }}
            QLabel#TitleBarSubtitle {{
                color: {tok.TEXT_MUTED};
                font-family: {tok.FONT_UI};
                padding-left: 2px;
            }}
            QPushButton#TitleBarAboutInfo,
            QPushButton#TitleBarSettings,
            QPushButton#TitleBarCheckUpdates {{
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
                text-align: center;
            }}
            QPushButton#TitleBarAboutInfo:hover,
            QPushButton#TitleBarSettings:hover {{
                background-color: rgba(255, 255, 255, 0.08);
                border-radius: {getattr(self, "_shell_hit_radius", 11)}px;
            }}
            QPushButton#TitleBarAboutInfo:pressed,
            QPushButton#TitleBarSettings:pressed {{
                background-color: rgba(255, 255, 255, 0.12);
                border-radius: {getattr(self, "_shell_hit_radius", 11)}px;
            }}
            QFrame#TitleBarShellDivider {{
                color: #555555;
                background-color: #555555;
                border: none;
                margin: 0px;
            }}
            """
        )

    def set_bar_color(self, bg_color: str) -> None:
        """Re-tint the title bar background (used by the experimental themes)."""
        self._apply_bar_style(bg_color)

    def set_shell_tools_visible(self, visible: bool) -> None:
        """Show About (i) | Settings + Updates in the title bar (Portable only)."""
        tools = getattr(self, "_shell_tools", None)
        if tools is not None:
            tools.setVisible(bool(visible))

    def set_update_available(self, available: bool, *, version: str | None = None) -> None:
        """Show/hide the compact Update available chip next to the version."""
        btn = self.btn_update_available
        if not available:
            btn.hide()
            btn.setToolTip("")
            return
        label = "Update Available"
        if version:
            btn.setToolTip(f"Update Available: v{version.lstrip('v')}")
        else:
            btn.setToolTip(label)
        color = COLOR_VERSION_NEW
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        btn.setText(label)
        btn.setStyleSheet(
            f"QPushButton#TitleBarUpdateAvailable {{"
            f"background-color: rgba({r}, {g}, {b}, 0.18);"
            f"color: {color};"
            f"border: 1px solid {color};"
            f"border-radius: 6px;"
            f"font-family: {tok.FONT_APP};"
            f"font-size: 10px;"
            f"font-weight: bold;"
            f"padding: 0 8px;"
            f"}}"
            f"QPushButton#TitleBarUpdateAvailable:hover {{"
            f"background-color: rgba({r}, {g}, {b}, 0.30);"
            f"}}"
        )
        # Pin to content width only — never max() with current width (a stretched
        # layout width would lock the chip across the caption drag strip).
        hint_w = max(btn.sizeHint().width(), 96)
        btn.setFixedWidth(min(hint_w, 160))
        btn.show()

    def reset_traffic_lights(self) -> None:
        """Repaint window controls after maximize/DWM refresh (sticky hover / missed paint)."""
        for attr in ("btn_close", "btn_minimize", "btn_maximize"):
            btn = getattr(self, attr, None)
            if btn is None:
                continue
            if hasattr(btn, "_set_hovered"):
                btn._set_hovered(False)
            btn.setVisible(True)
            btn.setEnabled(True)
            btn.raise_()
            btn.update()
        self.update()

    def sync_window_state(self) -> None:
        # Linux fake-maximize uses work-area geometry (isMaximized() stays False).
        maximized = self._window.isMaximized()
        if not maximized and sys.platform != "win32":
            from PySide6.QtWidgets import QApplication

            screen = self._window.screen() or QApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                geo = self._window.geometry()
                maximized = (
                    abs(geo.x() - avail.x()) <= 16
                    and abs(geo.y() - avail.y()) <= 16
                    and abs(geo.width() - avail.width()) <= 48
                    and abs(geo.height() - avail.height()) <= 48
                )
        if maximized:
            self.btn_maximize.setToolTip("Restore")
            self.btn_maximize._glyph = "restore"
        else:
            self.btn_maximize.setToolTip("Maximize")
            self.btn_maximize._glyph = "maximize"
        self.btn_maximize.update()
        self.reset_traffic_lights()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Maximize/restore often skips leaveEvent on the traffic lights — refresh
        # once layout has settled so the dots are not stuck invisible/glyph-only.
        if event.size().width() != event.oldSize().width():
            QTimer.singleShot(0, self.reset_traffic_lights)


def install_title_bar(main_window) -> SteempegTitleBar:
    """Wrap main_splitter with a vertical shell that includes the custom title bar."""
    from steempeg.version import APP_VERSION_STR

    layout = main_window.horizontalLayout_main
    layout.removeWidget(main_window.main_splitter)
    # Flush the shell to the window edges so the title bar fills the very top
    # (no window-background strip above/around it).
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    shell = QWidget(main_window)
    shell.setObjectName("appShell")
    shell.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    shell.setStyleSheet(f"QWidget#appShell {{ background-color: {tok.BG_SHELL}; }}")
    shell_layout = QVBoxLayout(shell)
    shell_layout.setContentsMargins(0, 0, 0, 0)
    shell_layout.setSpacing(0)

    title_bar = SteempegTitleBar(
        main_window,
        title="Steempeg",
        subtitle=f"v{APP_VERSION_STR}",
    )
    shell_layout.addWidget(title_bar)

    # Title bar stays flush to the window edges; the content keeps the old
    # breathing room around the splitter (restored after zeroing outer margins).
    content_wrap = QWidget()
    content_wrap.setObjectName("appContent")
    content_wrap.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    content_wrap.setStyleSheet(f"QWidget#appContent {{ background-color: {tok.BG_SHELL}; }}")
    content_layout = QVBoxLayout(content_wrap)
    content_layout.setContentsMargins(9, 11, 9, 9)
    content_layout.setSpacing(0)
    content_layout.addWidget(main_window.main_splitter)
    shell_layout.addWidget(content_wrap, 1)

    layout.addWidget(shell)

    main_window._custom_content_wrap = content_wrap
    main_window._custom_content_margins = (9, 11, 9, 9)

    title_bar.close_requested.connect(lambda: win32_window_command(main_window, "close"))
    title_bar.minimize_requested.connect(lambda: win32_window_command(main_window, "minimize"))
    title_bar.maximize_requested.connect(lambda: win32_window_command(main_window, "maximize_toggle"))

    main_window.title_bar = title_bar
    main_window._custom_chrome_shell = shell
    # Platform-split edge/corner resize — keep both paths independent.
    # Windows: overlay grip widgets + HTCLIENT on grip bands (see enable_windows_*).
    # Linux: xcb manual / Wayland startSystemResize (unchanged).
    if os.name == "nt":
        enable_windows_edge_resize(main_window)
    else:
        enable_linux_edge_resize(main_window)
    return title_bar


# --- Shared edge geometry (used by Windows + Linux filters) -----------------

_WIN_RESIZE_BORDER = 8
_WIN_RESIZE_CORNER = 14
# Top corners stay tiny so traffic-light dots stay clickable.
_WIN_RESIZE_TOP_CORNER = 8
_LINUX_RESIZE_BORDER = 8
_LINUX_RESIZE_CORNER = 18
# Top corners stay tiny so title-bar traffic lights stay clickable (match Windows).
_LINUX_RESIZE_TOP_CORNER = 8


def _nearly_maximized(window: QWidget) -> bool:
    if window.isMaximized():
        return True
    if os.name == "nt":
        # Windows: only trust real maximized state. A "fills most of the screen"
        # heuristic blocked corner drag after restore on large monitors.
        try:
            return bool(ctypes.windll.user32.IsZoomed(int(window.winId())))
        except Exception:
            return False
    screen = window.screen() or QApplication.primaryScreen()
    if screen is None:
        return False
    avail = screen.availableGeometry()
    geo = window.frameGeometry()
    return (
        abs(geo.x() - avail.x()) <= 16
        and abs(geo.y() - avail.y()) <= 16
        and abs(geo.width() - avail.width()) <= 48
        and abs(geo.height() - avail.height()) <= 48
    )


def _linux_restore_target_geometry(window: QWidget) -> QRect:
    """Preferred size when leaving Linux fake-maximize (work-area fill)."""
    saved = getattr(window, "_linux_restore_geometry", None)
    if isinstance(saved, QRect) and saved.isValid() and saved.width() >= 200:
        return saved
    screen = window.screen() or QApplication.primaryScreen()
    if screen is None:
        return window.geometry()
    return screen.availableGeometry().adjusted(80, 60, -80, -60)


def _linux_refresh_traffic_lights(window: QWidget) -> None:
    """Re-sync traffic-light hover after a shell-level mouse grab (drag/resize)."""
    tb = getattr(window, "title_bar", None)
    if tb is None:
        return
    pos = QCursor.pos()
    for attr in ("btn_close", "btn_minimize", "btn_maximize"):
        btn = getattr(tb, attr, None)
        if btn is None or not btn.isVisible():
            continue
        try:
            hovered = btn.rect().contains(btn.mapFromGlobal(pos))
        except RuntimeError:
            hovered = False
        if hasattr(btn, "_set_hovered"):
            btn._set_hovered(hovered)


def _linux_snap_title_drag_to_top(window: QWidget) -> None:
    """Fake-maximize when the title-bar drag ends flush with the screen top."""
    if os.name == "nt":
        return
    screen = window.screen() or QApplication.primaryScreen()
    if screen is None:
        return
    avail = screen.availableGeometry()
    if window.frameGeometry().y() > avail.top() + 12:
        return
    if not _nearly_maximized(window):
        window._linux_restore_geometry = QRect(window.geometry())
    window.setGeometry(avail)
    tb = getattr(window, "title_bar", None)
    if tb is not None and hasattr(tb, "sync_window_state"):
        tb.sync_window_state()


def _linux_unsnap_from_fake_maximize(window: QWidget, global_pos: QPoint) -> None:
    """Shrink a work-area-filled shell so title-bar drag can move it (Linux only)."""
    if os.name == "nt" or not _nearly_maximized(window):
        return
    restore = _linux_restore_target_geometry(window)
    geo = window.geometry()
    width = max(int(restore.width()), window.minimumWidth())
    height = max(int(restore.height()), window.minimumHeight())
    frac_x = 0.5
    if geo.width() > 1:
        frac_x = (global_pos.x() - geo.x()) / float(geo.width())
    frac_x = max(0.08, min(0.92, frac_x))
    anchor_y = max(8, tok.TITLE_BAR_HEIGHT // 2)
    new_x = int(global_pos.x() - width * frac_x)
    new_y = int(global_pos.y() - anchor_y)
    screen = window.screen() or QApplication.primaryScreen()
    if screen is not None:
        avail = screen.availableGeometry()
        new_x = max(avail.left(), min(new_x, avail.right() - width + 1))
        new_y = max(avail.top(), min(new_y, avail.bottom() - height + 1))
    window.setGeometry(new_x, new_y, width, height)
    tb = getattr(window, "title_bar", None)
    if tb is not None and hasattr(tb, "sync_window_state"):
        tb.sync_window_state()


def _edge_resize_blocked(window: QWidget) -> bool:
    """True when edge/corner resize must not run (maximize or immersive fullscreen).

    Immersive fullscreen clears WindowMaximized and hides the title bar so the
    shell can fill the monitor — grips must follow that chrome, not maximize alone.
    """
    if _nearly_maximized(window):
        return True
    tb = getattr(window, "title_bar", None)
    if tb is None or not tb.isVisible():
        return True
    host = getattr(window, "_app_host", None)
    if host is not None and getattr(host, "is_fullscreen", False):
        return True
    return False


def _edges_at(window: QWidget, global_pos: QPoint, *, border: int, corner: int):
    """Map a global mouse position to Qt resize edges, or None if not on a grip."""
    if _edge_resize_blocked(window):
        return None

    geo = window.frameGeometry()
    x, y = global_pos.x(), global_pos.y()
    left, top = geo.x(), geo.y()
    right, bottom = left + geo.width(), top + geo.height()

    on_left = left <= x < left + border
    on_right = right - border <= x < right
    on_top = top <= y < top + border
    on_bottom = bottom - border <= y < bottom
    in_left_c = left <= x < left + corner
    in_right_c = right - corner <= x < right
    in_top_c = top <= y < top + corner
    in_bottom_c = bottom - corner <= y < bottom

    if in_top_c and in_left_c:
        return Qt.Edge.TopEdge | Qt.Edge.LeftEdge
    if in_top_c and in_right_c:
        return Qt.Edge.TopEdge | Qt.Edge.RightEdge
    if in_bottom_c and in_left_c:
        return Qt.Edge.BottomEdge | Qt.Edge.LeftEdge
    if in_bottom_c and in_right_c:
        return Qt.Edge.BottomEdge | Qt.Edge.RightEdge
    if on_left:
        return Qt.Edge.LeftEdge
    if on_right:
        return Qt.Edge.RightEdge
    if on_top:
        return Qt.Edge.TopEdge
    if on_bottom:
        return Qt.Edge.BottomEdge
    return None


def _cursor_for_edges(edges) -> Qt.CursorShape:
    left = bool(edges & Qt.Edge.LeftEdge)
    right = bool(edges & Qt.Edge.RightEdge)
    top = bool(edges & Qt.Edge.TopEdge)
    bottom = bool(edges & Qt.Edge.BottomEdge)
    if (top and left) or (bottom and right):
        return Qt.CursorShape.SizeFDiagCursor
    if (top and right) or (bottom and left):
        return Qt.CursorShape.SizeBDiagCursor
    if left or right:
        return Qt.CursorShape.SizeHorCursor
    return Qt.CursorShape.SizeVerCursor


def _apply_manual_resize(
    window: QWidget,
    edges,
    origin: QPoint,
    start_geo,
    global_pos: QPoint,
) -> None:
    dx = global_pos.x() - origin.x()
    dy = global_pos.y() - origin.y()
    x, y, w, h = start_geo.x(), start_geo.y(), start_geo.width(), start_geo.height()
    min_w = max(window.minimumWidth(), 200)
    min_h = max(window.minimumHeight(), 150)

    if edges & Qt.Edge.LeftEdge:
        new_w = max(min_w, w - dx)
        x = x + (w - new_w)
        w = new_w
    if edges & Qt.Edge.RightEdge:
        w = max(min_w, w + dx)
    if edges & Qt.Edge.TopEdge:
        new_h = max(min_h, h - dy)
        y = y + (h - new_h)
        h = new_h
    if edges & Qt.Edge.BottomEdge:
        h = max(min_h, h + dy)

    window.setGeometry(x, y, w, h)


# --- Windows edge resize ----------------------------------------------------
# Dedicated path (not shared with Linux): transparent grip widgets on top of
# the shell. App-wide mouse filters miss presses when DWM/NCHITTEST owns the
# border; HTLEFT/… system resize was also unreliable with our NCCALCSIZE chrome.


class _WinResizeGrip(QWidget):
    """Invisible hit target for one edge or corner on Windows."""

    def __init__(self, host: QWidget, edges):
        super().__init__(host)
        self._host = host
        self._edges = edges
        self._origin: QPoint | None = None
        self._start_geo = None
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setStyleSheet("background: transparent;")
        self.setCursor(QCursor(_cursor_for_edges(edges)))
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        if _edge_resize_blocked(self._host):
            return
        self._origin = event.globalPosition().toPoint()
        self._start_geo = self._host.geometry()
        self.grabMouse()
        event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._origin is None or self._start_geo is None:
            return super().mouseMoveEvent(event)
        _apply_manual_resize(
            self._host,
            self._edges,
            self._origin,
            self._start_geo,
            event.globalPosition().toPoint(),
        )
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._origin is not None:
            try:
                self.releaseMouse()
            except Exception:
                pass
            self._origin = None
            self._start_geo = None
            event.accept()
            return
        return super().mouseReleaseEvent(event)


class _WindowsEdgeResizeController(QObject):
    """Positions 8 transparent grips over the window border (Windows only)."""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        specs = (
            Qt.Edge.LeftEdge,
            Qt.Edge.RightEdge,
            Qt.Edge.TopEdge,
            Qt.Edge.BottomEdge,
            Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
            Qt.Edge.TopEdge | Qt.Edge.RightEdge,
            Qt.Edge.BottomEdge | Qt.Edge.LeftEdge,
            Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
        )
        self._grips = [_WinResizeGrip(window, edges) for edges in specs]
        window.installEventFilter(self)
        self._layout_grips()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._window and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.WindowStateChange,
        ):
            self._layout_grips()
        return False

    def _layout_grips(self) -> None:
        window = self._window
        if _edge_resize_blocked(window):
            for g in self._grips:
                g.hide()
                g.setEnabled(False)
            return

        w, h = window.width(), window.height()
        b, c = _WIN_RESIZE_BORDER, _WIN_RESIZE_CORNER
        tc = _WIN_RESIZE_TOP_CORNER
        # Order matches specs in __init__.
        # Top corners stay small — a big square ate the close/min/max dots.
        geos = (
            (0, c, b, max(0, h - 2 * c)),  # left
            (max(0, w - b), c, b, max(0, h - 2 * c)),  # right
            (tc, 0, max(0, w - 2 * tc), b),  # top
            (c, max(0, h - b), max(0, w - 2 * c), b),  # bottom
            (0, 0, tc, tc),  # top-left
            (max(0, w - tc), 0, tc, tc),  # top-right
            (0, max(0, h - c), c, c),  # bottom-left
            (max(0, w - c), max(0, h - c), c, c),  # bottom-right
        )
        for grip, (x, y, gw, gh) in zip(self._grips, geos):
            if gw <= 0 or gh <= 0:
                grip.hide()
                grip.setEnabled(False)
                continue
            grip.setGeometry(x, y, gw, gh)
            grip.setEnabled(True)
            grip.show()
            grip.raise_()
        tb = getattr(window, "title_bar", None)
        if tb is not None and hasattr(tb, "reset_traffic_lights"):
            tb.reset_traffic_lights()


def enable_windows_edge_resize(window: QWidget) -> None:
    """Windows-only: overlay grip widgets for edge/corner resize."""
    if os.name != "nt":
        return
    existing = getattr(window, "_windows_edge_resize_filter", None)
    if existing is not None:
        return
    window._windows_edge_resize_filter = _WindowsEdgeResizeController(window)


def refresh_windows_edge_resize(window: QWidget) -> None:
    """Re-layout / hide grips after immersive fullscreen or title-bar show/hide."""
    ctrl = getattr(window, "_windows_edge_resize_filter", None)
    if ctrl is not None and hasattr(ctrl, "_layout_grips"):
        ctrl._layout_grips()


# --- Linux edge resize (unchanged behaviour) --------------------------------


def _linux_nearly_maximized(window: QWidget) -> bool:
    return _nearly_maximized(window)


def _linux_edges_at(window: QWidget, global_pos: QPoint):
    return _edges_at(
        window,
        global_pos,
        border=_LINUX_RESIZE_BORDER,
        corner=_LINUX_RESIZE_CORNER,
    )


def _linux_cursor_for_edges(edges) -> Qt.CursorShape:
    return _cursor_for_edges(edges)


def _linux_prefer_manual_resize() -> bool:
    """XWayland/xcb often mishandles startSystemResize for frameless windows."""
    app = QApplication.instance()
    if app is None:
        return True
    name = (app.platformName() or "").lower()
    return name in ("xcb", "offscreen", "minimal")


def _linux_apply_manual_resize(
    window: QWidget,
    edges,
    origin: QPoint,
    start_geo,
    global_pos: QPoint,
) -> None:
    _apply_manual_resize(window, edges, origin, start_geo, global_pos)


class _LinuxEdgeResizeFilter(QObject):
    """Title-bar window move on xcb/XWayland (manual move, no startSystemMove warp).

    Edge/corner resize uses transparent grip widgets (``_LinuxEdgeResizeGrips``),
    same approach as Windows — app-wide filters miss presses under the title bar.
    """

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        self._title_drag_offset: QPoint | None = None
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def begin_title_drag(self, global_pos: QPoint) -> None:
        if sys.platform != "win32":
            _linux_unsnap_from_fake_maximize(self._window, global_pos)
        self._title_drag_offset = global_pos - self._window.pos()
        try:
            self._window.grabMouse()
        except Exception:
            pass

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if self._title_drag_offset is None:
            return False

        et = event.type()
        if et in (
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.WindowDeactivate,
            QEvent.Type.Hide,
            QEvent.Type.Close,
        ):
            self._end_title_drag()
            return False
        if et == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self._end_title_drag()
            return True
        if et == QEvent.Type.MouseMove:
            global_pos = (
                event.globalPosition().toPoint()
                if hasattr(event, "globalPosition")
                else event.globalPos()
            )
            self._window.move(global_pos - self._title_drag_offset)
            return True
        return False

    def _end_title_drag(self) -> None:
        self._title_drag_offset = None
        try:
            self._window.releaseMouse()
        except Exception:
            pass
        if sys.platform != "win32":
            _linux_snap_title_drag_to_top(self._window)
            win = self._window
            QTimer.singleShot(0, lambda w=win: _linux_refresh_traffic_lights(w))


class _LinuxEdgeResizeGrips(QObject):
    """Transparent resize grips over the shell (Linux / macOS)."""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        specs = (
            Qt.Edge.LeftEdge,
            Qt.Edge.RightEdge,
            Qt.Edge.TopEdge,
            Qt.Edge.BottomEdge,
            Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
            Qt.Edge.TopEdge | Qt.Edge.RightEdge,
            Qt.Edge.BottomEdge | Qt.Edge.LeftEdge,
            Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
        )
        self._grips = [_WinResizeGrip(window, edges) for edges in specs]
        window.installEventFilter(self)
        self._layout_grips()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._window and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.WindowStateChange,
        ):
            self._layout_grips()
        return False

    def _layout_grips(self) -> None:
        window = self._window
        if _edge_resize_blocked(window):
            for grip in self._grips:
                grip.hide()
                grip.setEnabled(False)
            return

        w, h = window.width(), window.height()
        b, c = _LINUX_RESIZE_BORDER, _LINUX_RESIZE_CORNER
        tc = _LINUX_RESIZE_TOP_CORNER
        geos = (
            (0, c, b, max(0, h - 2 * c)),  # left
            (max(0, w - b), c, b, max(0, h - 2 * c)),  # right
            (tc, 0, max(0, w - 2 * tc), b),  # top
            (c, max(0, h - b), max(0, w - 2 * c), b),  # bottom
            (0, 0, tc, tc),  # top-left
            (max(0, w - tc), 0, tc, tc),  # top-right
            (0, max(0, h - c), c, c),  # bottom-left
            (max(0, w - c), max(0, h - c), c, c),  # bottom-right
        )
        for grip, (x, y, gw, gh) in zip(self._grips, geos):
            if gw <= 0 or gh <= 0:
                grip.hide()
                grip.setEnabled(False)
                continue
            grip.setGeometry(x, y, gw, gh)
            grip.setEnabled(True)
            grip.show()
            grip.raise_()
        tb = getattr(window, "title_bar", None)
        if tb is not None and hasattr(tb, "reset_traffic_lights"):
            tb.reset_traffic_lights()


def enable_linux_edge_resize(window: QWidget) -> None:
    """Enable corner/edge resize for frameless windows on Linux (and macOS)."""
    if os.name == "nt":
        return
    if getattr(window, "_linux_edge_resize_filter", None) is None:
        window._linux_edge_resize_filter = _LinuxEdgeResizeFilter(window)
    if getattr(window, "_linux_edge_resize_grips", None) is None:
        window._linux_edge_resize_grips = _LinuxEdgeResizeGrips(window)


def _hex_to_colorref(hex_color: str) -> int:
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return (b << 16) | (g << 8) | r


def _resize_border_thickness(window: QWidget) -> int:
    gsm = ctypes.windll.user32.GetSystemMetrics
    return gsm(_SM_CXSIZEFRAME) + gsm(_SM_CXPADDEDBORDER)


def win32_window_command(window: QWidget, action: str) -> None:
    """Route min/max/close through WM_SYSCOMMAND for native Windows behavior."""
    if os.name != "nt":
        if action == "close":
            window.close()
        elif action == "minimize":
            window.showMinimized()
        elif action == "maximize_toggle":
            # Native showMaximized hard-freezes Qt on NVIDIA XWayland. Fake maximize
            # by snapping to the screen work area (and restore the inset window).
            from PySide6.QtWidgets import QApplication

            screen = window.screen() or QApplication.primaryScreen()
            if screen is None:
                return
            avail = screen.availableGeometry()
            geo = window.geometry()
            nearly_max = (
                abs(geo.x() - avail.x()) <= 16
                and abs(geo.y() - avail.y()) <= 16
                and abs(geo.width() - avail.width()) <= 48
                and abs(geo.height() - avail.height()) <= 48
            )
            if window.isMaximized() or nearly_max:
                window.showNormal()
                restore = getattr(window, "_linux_restore_geometry", None)
                if isinstance(restore, QRect) and restore.isValid():
                    window.setGeometry(restore)
                else:
                    window.setGeometry(avail.adjusted(80, 60, -80, -60))
            else:
                window._linux_restore_geometry = QRect(window.geometry())
                if window.isMaximized():
                    window.showNormal()
                window.setGeometry(avail)
        return

    hwnd = int(window.winId())
    if action == "close":
        ctypes.windll.user32.SendMessageW(hwnd, _WM_SYSCOMMAND, _SC_CLOSE, 0)
    elif action == "minimize":
        ctypes.windll.user32.SendMessageW(hwnd, _WM_SYSCOMMAND, _SC_MINIMIZE, 0)
    elif action == "maximize_toggle":
        cmd = _SC_RESTORE if window.isMaximized() else _SC_MAXIMIZE
        ctypes.windll.user32.SendMessageW(hwnd, _WM_SYSCOMMAND, cmd, 0)


def enable_frameless(window: QWidget) -> None:
    """Keep all native window styles, then trigger a frame recalc so our
    WM_NCCALCSIZE handler removes the *painted* caption. Preserves Snap/animations."""
    if os.name != "nt":
        return
    hwnd = int(window.winId())
    user32 = ctypes.windll.user32
    style = user32.GetWindowLongW(hwnd, _GWL_STYLE)
    style |= _WS_CAPTION | _WS_THICKFRAME | _WS_MINIMIZEBOX | _WS_MAXIMIZEBOX | _WS_SYSMENU
    user32.SetWindowLongW(hwnd, _GWL_STYLE, style)
    user32.SetWindowPos(
        hwnd, 0, 0, 0, 0, 0,
        _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_FRAMECHANGED,
    )
    refresh_dwm_chrome(window)


def _seed_startup_restore_rect(window: QWidget) -> None:
    """While maximized, ensure Win32 has a real restore target for Aero.

    Cold-start ``showMaximized`` plus a later FRAMECHANGED poke can leave
    ``rcNormalPosition`` empty or equal to the work area. The first
    SC_RESTORE then snaps with no animation; after one max↔restore cycle
    Windows has a proper rect and later toggles animate. Re-seed placement
    without changing show state (no flash).
    """
    if os.name != "nt":
        return
    try:
        hwnd = int(window.winId())
        user32 = ctypes.windll.user32
        if not user32.IsZoomed(hwnd):
            return
        normal = getattr(window, "_startup_restore_geometry", None)
        if not isinstance(normal, QRect) or not normal.isValid() or normal.isEmpty():
            screen = window.screen() or QApplication.primaryScreen()
            if screen is None:
                return
            # Match app.py startup inset used before the first showMaximized.
            normal = screen.availableGeometry().adjusted(80, 60, -80, -60)
        wp = _WINDOWPLACEMENT()
        wp.length = ctypes.sizeof(_WINDOWPLACEMENT)
        if not user32.GetWindowPlacement(hwnd, ctypes.byref(wp)):
            return
        wp.showCmd = _SW_SHOWMAXIMIZED
        # Win32 RECT is exclusive on right/bottom; QRect right()/bottom() are inclusive.
        wp.rcNormalPosition.left = int(normal.x())
        wp.rcNormalPosition.top = int(normal.y())
        wp.rcNormalPosition.right = int(normal.x() + normal.width())
        wp.rcNormalPosition.bottom = int(normal.y() + normal.height())
        user32.SetWindowPlacement(hwnd, ctypes.byref(wp))
    except Exception:
        pass


def ensure_startup_maximized(window: QWidget) -> None:
    """Re-assert maximize after Win32 chrome / post-update settle.

    Startup pre-sizes to an inset rect, then ``showMaximized()``. A later
    ``enable_frameless`` (FRAMECHANGED) or the post-update success dialog can
    leave the shell on that inset — especially noticeable in portable after
    ``--updated-from`` relaunches. Skip immersive fullscreen.
    """
    if os.name != "nt":
        return
    host = getattr(window, "_app_host", None)
    if host is not None and getattr(host, "is_fullscreen", False):
        return
    try:
        if not window.isMaximized():
            window.showMaximized()
    except RuntimeError:
        return
    # After FRAMECHANGED settle, re-plant restore geometry so the first
    # green-button restore still gets a DWM animation.
    _seed_startup_restore_rect(window)


# Back-compat name used by app.py.
apply_native_caption_hidden = enable_frameless


def collapse_content_insets(main_window) -> None:
    """Zero the content wrapper margins for immersive / fullscreen (edge-to-edge video)."""
    wrap = getattr(main_window, "_custom_content_wrap", None)
    if wrap is not None and wrap.layout() is not None:
        wrap.layout().setContentsMargins(0, 0, 0, 0)


def restore_content_insets(main_window) -> None:
    """Restore the normal content wrapper padding after leaving immersive/fullscreen."""
    wrap = getattr(main_window, "_custom_content_wrap", None)
    margins = getattr(main_window, "_custom_content_margins", (9, 11, 9, 9))
    if wrap is not None and wrap.layout() is not None:
        wrap.layout().setContentsMargins(*margins)


_RDW_INVALIDATE = 0x0001
_RDW_ERASE = 0x0004
_RDW_ERASENOW = 0x0200
_RDW_UPDATENOW = 0x0100
_RDW_ALLCHILDREN = 0x0080
_RDW_FRAME = 0x0400


def soft_full_redraw(window) -> None:
    """Invalidate + erase the window tree without changing size.

    Prefer this after ordinary resizes: a 1px SetWindowPos nudge re-enters
    resizeEvent and can leave extra DWM ghost frames when the queue panel is open.
    """
    if os.name != "nt":
        window.update()
        return
    try:
        hwnd = int(window.winId())
        redraw = (
            _RDW_INVALIDATE | _RDW_ERASE | _RDW_ERASENOW
            | _RDW_UPDATENOW | _RDW_ALLCHILDREN | _RDW_FRAME
        )
        ctypes.windll.user32.RedrawWindow(hwnd, None, None, redraw)
        window.update()
    except Exception:
        window.update()


def force_full_redraw(window) -> None:
    """Clear a stale native/DWM ghost left after switching into immersive fullscreen.

    A 1px size nudge alone doesn't erase hidden child regions, so also force a
    full RedrawWindow that invalidates + erases every child (mpv surface included).
    Do not call this from resizeEvent — use soft_full_redraw instead."""
    if os.name != "nt":
        window.update()
        return
    try:
        hwnd = int(window.winId())
        user32 = ctypes.windll.user32
        rect = _RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        x, y = rect.left, rect.top
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        flags = _SWP_NOZORDER | 0x0010  # SWP_NOACTIVATE
        user32.SetWindowPos(hwnd, 0, x, y, w, h - 1, flags)
        user32.SetWindowPos(hwnd, 0, x, y, w, h, flags)
        redraw = (
            _RDW_INVALIDATE | _RDW_ERASE | _RDW_ERASENOW
            | _RDW_UPDATENOW | _RDW_ALLCHILDREN | _RDW_FRAME
        )
        user32.RedrawWindow(hwnd, None, None, redraw)
    except Exception:
        window.update()


_SW_HIDE = 0
_SW_SHOWNA = 8  # show in current state, do not activate / change z-order


def rebuild_window_surface(window) -> None:
    """Force DWM to allocate a fresh redirection surface for the window.

    Growing a frameless window from the maximized work-area size to the full
    monitor leaves a stale composited strip (the old taskbar-height bottom) that
    a plain RedrawWindow can't erase — only a minimize/restore fixes it. This
    does the equivalent surface teardown/recreate (hide + show-no-activate)
    without the visible animation; call it while a solid cover masks the window."""
    if os.name != "nt":
        return
    try:
        hwnd = int(window.winId())
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, _SW_HIDE)
        user32.ShowWindow(hwnd, _SW_SHOWNA)
        redraw = (
            _RDW_INVALIDATE | _RDW_ERASE | _RDW_ERASENOW
            | _RDW_UPDATENOW | _RDW_ALLCHILDREN | _RDW_FRAME
        )
        user32.RedrawWindow(hwnd, None, None, redraw)
    except Exception:
        pass


_DWMWA_TRANSITIONS_FORCEDISABLED = 3


def set_window_transitions(window, enabled: bool) -> None:
    """Toggle the window's native min/max/restore animations.

    Un-maximizing into fullscreen fires the SW_RESTORE cross-fade, which briefly
    shows the desktop through the not-yet-painted window (transparent edges + torn
    animation). Disabling transitions for the duration of the switch makes it
    instant; re-enable afterwards so normal minimize/maximize animations stay."""
    if os.name != "nt":
        return
    try:
        hwnd = int(window.winId())
        # attribute is BOOL: TRUE = transitions DISABLED
        val = ctypes.c_int(0 if enabled else 1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, _DWMWA_TRANSITIONS_FORCEDISABLED, ctypes.byref(val), ctypes.sizeof(val),
        )
    except Exception:
        pass


def poke_frame(window: QWidget) -> None:
    """Re-trigger WM_NCCALCSIZE so the native caption stays hidden after a
    maximize/restore state change (Windows re-adds it otherwise)."""
    if os.name != "nt":
        return
    try:
        hwnd = int(window.winId())
        ctypes.windll.user32.SetWindowPos(
            hwnd, 0, 0, 0, 0, 0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_FRAMECHANGED,
        )
    except Exception:
        pass


def refresh_dwm_chrome(window: QWidget) -> None:
    """Dark immersive mode + matching border color (no glass, no frame extend)."""
    if os.name != "nt":
        return
    try:
        hwnd = int(window.winId())
        dwm = ctypes.windll.dwmapi
        dark = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(
            hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(dark), ctypes.sizeof(dark),
        )
        # Remove the window border line entirely so no white/black 1px edge shows.
        no_border = ctypes.c_uint(_DWMWA_COLOR_NONE)
        try:
            dwm.DwmSetWindowAttribute(
                hwnd, _DWMWA_BORDER_COLOR, ctypes.byref(no_border), ctypes.sizeof(no_border),
            )
        except Exception:
            pass
        # Square corners — Win11 otherwise rounds the window, showing dark gaps at
        # the corners (most visible in borderless fullscreen / theatre).
        square = ctypes.c_int(_DWMWCP_DONOTROUND)
        try:
            dwm.DwmSetWindowAttribute(
                hwnd, _DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(square), ctypes.sizeof(square),
            )
        except Exception:
            pass
    except Exception:
        pass


def _native_event_type_bytes(eventType) -> bytes:
    """Normalize Qt/PySide nativeEvent type to bytes.

    PySide6 may pass ``b'windows_generic_MSG'``, a QByteArray, or a plain
    ``str``. Comparing only to ``bytes`` silently disables WM_NCHITTEST and
    kills corner/edge resize on Windows.
    """
    if isinstance(eventType, (bytes, bytearray)):
        return bytes(eventType)
    if isinstance(eventType, memoryview):
        return eventType.tobytes()
    # QByteArray / str / anything with data()
    data = getattr(eventType, "data", None)
    if callable(data):
        try:
            raw = data()
            if isinstance(raw, (bytes, bytearray)):
                return bytes(raw)
        except Exception:
            pass
    return str(eventType).encode("ascii", "ignore")


def handle_native_event(window, eventType, message):
    """Return (True, result) for handled WM_* messages, else None.

    Call from MainWindow.nativeEvent."""
    if os.name != "nt":
        return None
    et = _native_event_type_bytes(eventType)
    if et not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
        return None
    try:
        addr = int(message) if not hasattr(message, "__int__") else int(message.__int__())
        msg = _MSG.from_address(addr)
    except (TypeError, ValueError):
        return None

    # NCCALCSIZE is handled unconditionally so the native caption stays suppressed
    # in every state, including immersive fullscreen (where the title bar is hidden).
    # Fullscreen makes the window a plain non-maximized window sized to the monitor,
    # so there is nothing to double up with and no Aero "box in a box" halo.
    if msg.message == _WM_NCCALCSIZE:
        return _on_nccalcsize(window, msg)
    if msg.message == _WM_NCHITTEST:
        return _on_nchittest(window, msg)
    return None


def _on_nccalcsize(window, msg):
    if not msg.wParam:
        return True, 0
    params = cast(msg.lParam, POINTER(_NCCALCSIZE_PARAMS)).contents
    rect = params.rgrc[0]
    tb = getattr(window, "title_bar", None)
    tb_visible = tb is not None and tb.isVisible()
    if window.isMaximized() and tb_visible:
        # A maximized native window overhangs the monitor by the frame thickness;
        # inset the client so content isn't clipped and the taskbar stays visible.
        # Skipped in immersive fullscreen (title bar hidden) so the client fills the
        # entire monitor edge-to-edge with no inset border.
        th = _resize_border_thickness(window)
        rect.left += th
        rect.top += th
        rect.right -= th
        rect.bottom -= th
    # Returning 0 (full client rect) removes the standard title bar/frame paint.
    # The stray 1px border line is killed via DWMWA_BORDER_COLOR = COLOR_NONE.
    return True, 0


def _on_nchittest(window, msg):
    tb = getattr(window, "title_bar", None)
    if tb is None or not tb.isVisible():
        # Immersive fullscreen: whole window is client area — no resize borders,
        # no caption drag.
        return True, HTCLIENT

    # lParam is physical screen coords.
    x = ctypes.c_short(msg.lParam & 0xFFFF).value
    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value

    # Edge/corner resize is owned by ``enable_windows_edge_resize`` (Qt grips).
    # Force HTCLIENT on the grip bands so Win32 does not swallow presses via
    # HTLEFT/HTBOTTOMRIGHT (broken under our DWM + NCCALCSIZE chrome).
    hwnd = int(window.winId())
    maximized = bool(window.isMaximized()) or bool(ctypes.windll.user32.IsZoomed(hwnd))
    if not maximized:
        rect = _RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        dpr = max(1.0, float(window.devicePixelRatioF()))
        border = max(int(round(_WIN_RESIZE_BORDER * dpr)), 8)
        corner = max(int(round(_WIN_RESIZE_CORNER * dpr)), 12)
        top_corner = max(int(round(_WIN_RESIZE_TOP_CORNER * dpr)), 8)
        left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
        on_edge = (
            left <= x < left + border
            or right - border <= x < right
            or top <= y < top + border
            or bottom - border <= y < bottom
            or (left <= x < left + top_corner and top <= y < top + top_corner)
            or (right - top_corner <= x < right and top <= y < top + top_corner)
            or (left <= x < left + corner and bottom - corner <= y < bottom)
            or (right - corner <= x < right and bottom - corner <= y < bottom)
        )
        if on_edge:
            return True, HTCLIENT

    # Title-bar caption strip (logical) — drag via mousePress → WM_NCLBUTTONDOWN.
    dpr = max(1.0, float(window.devicePixelRatioF()))
    pos = window.mapFromGlobal(QPoint(int(round(x / dpr)), int(round(y / dpr))))
    px, py = int(pos.x()), int(pos.y())
    w = window.width()
    if py < tok.TITLE_BAR_HEIGHT and px < (w - _CONTROL_STRIP_WIDTH):
        return True, HTCLIENT

    return None
