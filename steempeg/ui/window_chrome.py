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

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.paths import get_resource_path
from steempeg.services.release_catalog import COLOR_VERSION_NEW
from steempeg.ui import design_tokens as tok
from steempeg.ui.icon_assets import title_bar_info_icons, title_bar_settings_icons

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

    def enterEvent(self, event):
        self._hovered = True
        self._apply_style()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._apply_style()
        self.update()
        super().leaveEvent(event)

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


class SteempegTitleBar(QWidget):
    """Top chrome: branding left, window controls right (Windows order)."""

    close_requested = Signal()
    minimize_requested = Signal()
    maximize_requested = Signal()
    about_requested = Signal()
    settings_requested = Signal()
    update_available_clicked = Signal()

    def __init__(self, window: QWidget, *, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self._window = window
        self.setObjectName("SteempegTitleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(tok.TITLE_BAR_HEIGHT)
        # Caption drag area must stay arrow; only the (i) / Update chip use hand.
        self.setCursor(Qt.CursorShape.ArrowCursor)

        bar_h = tok.TITLE_BAR_HEIGHT
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 0, 12, 0)
        root.setSpacing(0)

        icon_path = get_resource_path("logo.png")
        if os.path.isfile(icon_path):
            icon_lbl = QLabel()
            icon_lbl.setPixmap(QPixmap(icon_path).scaled(16, 16, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            icon_lbl.setFixedHeight(bar_h)
            icon_lbl.setFixedWidth(16)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)
            icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            root.addWidget(icon_lbl)
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

        # About (i) — glyph size stays 16px; hitbox is centered in the title bar
        # (ceiling↔floor), not on the v40 text baseline. QToolButton centers the
        # icon inside the hitbox more reliably than QPushButton on Windows.
        _info_px = 16
        _hit_px = 26
        self.btn_about_info = QToolButton()
        self.btn_about_info.setObjectName("TitleBarAboutInfo")
        self.btn_about_info.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_about_info.setAutoRaise(True)
        self._about_info_icon_idle, self._about_info_icon_hot = title_bar_info_icons(_info_px)
        self.btn_about_info.setIcon(self._about_info_icon_idle)
        self.btn_about_info.setIconSize(QSize(_info_px, _info_px))
        self.btn_about_info.setFixedSize(_hit_px, _hit_px)
        self.btn_about_info.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_about_info.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_about_info.setToolTip("About")
        self.btn_about_info.clicked.connect(self.about_requested.emit)
        self.btn_about_info.installEventFilter(self)

        info_wrap = QWidget()
        info_wrap.setObjectName("TitleBarAboutInfoWrap")
        info_wrap.setFixedHeight(bar_h)
        info_wrap.setFixedWidth(_hit_px)
        info_lay = QVBoxLayout(info_wrap)
        info_lay.setContentsMargins(0, 0, 0, 0)
        info_lay.setSpacing(0)
        info_lay.addStretch(1)
        info_lay.addWidget(self.btn_about_info, 0, Qt.AlignmentFlag.AlignHCenter)
        info_lay.addStretch(1)

        root.addSpacing(4)
        root.addWidget(info_wrap)

        # Settings (settings2.png) — same hitbox geometry as About (i).
        self.btn_title_settings = QToolButton()
        self.btn_title_settings.setObjectName("TitleBarSettings")
        self.btn_title_settings.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_title_settings.setAutoRaise(True)
        self._settings_icon_idle, self._settings_icon_hot = title_bar_settings_icons(_info_px)
        self.btn_title_settings.setIcon(self._settings_icon_idle)
        self.btn_title_settings.setIconSize(QSize(_info_px, _info_px))
        self.btn_title_settings.setFixedSize(_hit_px, _hit_px)
        self.btn_title_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_title_settings.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_title_settings.setToolTip("Settings")
        self.btn_title_settings.clicked.connect(self.settings_requested.emit)
        self.btn_title_settings.installEventFilter(self)

        settings_wrap = QWidget()
        settings_wrap.setObjectName("TitleBarSettingsWrap")
        settings_wrap.setFixedHeight(bar_h)
        settings_wrap.setFixedWidth(_hit_px)
        settings_lay = QVBoxLayout(settings_wrap)
        settings_lay.setContentsMargins(0, 0, 0, 0)
        settings_lay.setSpacing(0)
        settings_lay.addStretch(1)
        settings_lay.addWidget(self.btn_title_settings, 0, Qt.AlignmentFlag.AlignHCenter)
        settings_lay.addStretch(1)

        root.addSpacing(2)
        root.addWidget(settings_wrap)

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

        handle = self._window.windowHandle()
        if handle is not None:
            handle.startSystemMove()
            event.accept()
            return
        super().mousePressEvent(event)

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
                padding-left: 4px;
            }}
            QToolButton#TitleBarAboutInfo,
            QToolButton#TitleBarSettings {{
                background: transparent;
                border: none;
                padding: 0;
                margin: 0;
            }}
            QToolButton#TitleBarAboutInfo:hover,
            QToolButton#TitleBarSettings:hover {{
                background-color: rgba(255, 255, 255, 0.08);
                border-radius: 13px;
            }}
            QToolButton#TitleBarAboutInfo:pressed,
            QToolButton#TitleBarSettings:pressed {{
                background-color: rgba(255, 255, 255, 0.12);
                border-radius: 13px;
            }}
            """
        )

    def set_bar_color(self, bg_color: str) -> None:
        """Re-tint the title bar background (used by the experimental themes)."""
        self._apply_bar_style(bg_color)

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
    # Windows gets edge/corner resize via WM_NCHITTEST. Frameless on Linux has no
    # native thick frame — manual grips on xcb, startSystemResize on Wayland.
    if os.name != "nt":
        enable_linux_edge_resize(main_window)
    return title_bar


_LINUX_RESIZE_BORDER = 8
_LINUX_RESIZE_CORNER = 18


def _linux_nearly_maximized(window: QWidget) -> bool:
    if window.isMaximized():
        return True
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


def _linux_edges_at(window: QWidget, global_pos: QPoint):
    """Map a global mouse position to Qt resize edges, or None if not on a grip."""
    tb = getattr(window, "title_bar", None)
    if tb is None or not tb.isVisible():
        return None
    if _linux_nearly_maximized(window):
        return None

    # frameGeometry includes any WM frame; for frameless equals geometry.
    geo = window.frameGeometry()
    x, y = global_pos.x(), global_pos.y()
    left, top = geo.x(), geo.y()
    right, bottom = left + geo.width(), top + geo.height()
    border, corner = _LINUX_RESIZE_BORDER, _LINUX_RESIZE_CORNER

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


def _linux_cursor_for_edges(edges) -> Qt.CursorShape:
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


class _LinuxEdgeResizeFilter(QObject):
    """Edge/corner resize for frameless Linux windows.

    On xcb (XWayland) use manual setGeometry — startSystemResize feels jumpy /
    mirrored. On native Wayland, prefer compositor startSystemResize.
    """

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        self._overriding = False
        self._drag_edges = None
        self._drag_origin: QPoint | None = None
        self._drag_geo = None
        self._manual = _linux_prefer_manual_resize()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if not isinstance(obj, QWidget):
            return False
        try:
            if obj.window() is not self._window:
                return False
        except RuntimeError:
            return False

        window = self._window
        if not window.isVisible():
            self._end_drag()
            self._clear_cursor()
            return False

        et = event.type()

        # Active drag: only track moves/releases globally for our window tree.
        if self._drag_edges is not None:
            if et == QEvent.Type.MouseMove:
                global_pos = (
                    event.globalPosition().toPoint()
                    if hasattr(event, "globalPosition")
                    else event.globalPos()
                )
                if self._manual and self._drag_origin is not None and self._drag_geo is not None:
                    _linux_apply_manual_resize(
                        window,
                        self._drag_edges,
                        self._drag_origin,
                        self._drag_geo,
                        global_pos,
                    )
                    return True
                return False
            if et == QEvent.Type.MouseButtonRelease:
                self._end_drag()
                self._clear_cursor()
                return True
            return False

        if et in (
            QEvent.Type.MouseMove,
            QEvent.Type.HoverMove,
            QEvent.Type.Enter,
            QEvent.Type.HoverEnter,
        ):
            global_pos = None
            if hasattr(event, "globalPosition"):
                global_pos = event.globalPosition().toPoint()
            elif hasattr(event, "globalPos"):
                global_pos = event.globalPos()
            if global_pos is None:
                return False
            edges = _linux_edges_at(window, global_pos)
            if edges:
                shape = _linux_cursor_for_edges(edges)
                if not self._overriding:
                    QApplication.setOverrideCursor(QCursor(shape))
                    self._overriding = True
                else:
                    QApplication.changeOverrideCursor(QCursor(shape))
            else:
                self._clear_cursor()
            return False

        if et in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
            if obj is window and self._drag_edges is None:
                self._clear_cursor()
            return False

        if et == QEvent.Type.MouseButtonPress:
            if event.button() != Qt.MouseButton.LeftButton:
                return False
            global_pos = (
                event.globalPosition().toPoint()
                if hasattr(event, "globalPosition")
                else event.globalPos()
            )
            edges = _linux_edges_at(window, global_pos)
            if not edges:
                return False

            if self._manual:
                self._drag_edges = edges
                self._drag_origin = QPoint(global_pos)
                self._drag_geo = window.geometry()
                window.grabMouse()
                event.accept()
                return True

            handle = window.windowHandle()
            if handle is None:
                return False
            self._clear_cursor()
            if handle.startSystemResize(edges):
                event.accept()
                return True
            # Fallback if compositor refuses.
            self._manual = True
            self._drag_edges = edges
            self._drag_origin = QPoint(global_pos)
            self._drag_geo = window.geometry()
            window.grabMouse()
            event.accept()
            return True

        return False

    def _end_drag(self) -> None:
        if self._drag_edges is not None:
            try:
                self._window.releaseMouse()
            except Exception:
                pass
        self._drag_edges = None
        self._drag_origin = None
        self._drag_geo = None

    def _clear_cursor(self) -> None:
        if self._overriding:
            QApplication.restoreOverrideCursor()
            self._overriding = False


def enable_linux_edge_resize(window: QWidget) -> None:
    """Enable corner/edge resize for frameless windows on Linux (and macOS)."""
    if os.name == "nt":
        return
    existing = getattr(window, "_linux_edge_resize_filter", None)
    if existing is not None:
        return
    window._linux_edge_resize_filter = _LinuxEdgeResizeFilter(window)


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
                window.setGeometry(avail.adjusted(80, 60, -80, -60))
            else:
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


def handle_native_event(window, eventType, message):
    """Return (True, result) for handled WM_* messages, else None.

    Call from MainWindow.nativeEvent."""
    if os.name != "nt" or eventType != b"windows_generic_MSG":
        return None
    try:
        msg = _MSG.from_address(int(message))
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

    # lParam is physical screen coords — match against GetWindowRect (also physical).
    # mapFromGlobal + logical sizes breaks resize hit bands under DPI scaling.
    x = ctypes.c_short(msg.lParam & 0xFFFF).value
    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
    hwnd = int(window.winId())
    rect = _RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))

    maximized = bool(window.isMaximized()) or bool(ctypes.windll.user32.IsZoomed(hwnd))
    if not maximized:
        border = max(_resize_border_thickness(window), 12)
        corner = max(border * 2, 24)
        left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom

        in_left_c = left <= x < left + corner
        in_right_c = right - corner <= x < right
        in_top_c = top <= y < top + corner
        in_bottom_c = bottom - corner <= y < bottom
        if in_top_c and in_left_c:
            return True, HTTOPLEFT
        if in_top_c and in_right_c:
            return True, HTTOPRIGHT
        if in_bottom_c and in_left_c:
            return True, HTBOTTOMLEFT
        if in_bottom_c and in_right_c:
            return True, HTBOTTOMRIGHT

        if left <= x < left + border:
            return True, HTLEFT
        if right - border <= x < right:
            return True, HTRIGHT
        if top <= y < top + border:
            return True, HTTOP
        if bottom - border <= y < bottom:
            return True, HTBOTTOM

    # Title-bar caption strip (logical) — drag via mousePress → WM_NCLBUTTONDOWN.
    dpr = max(1.0, float(window.devicePixelRatioF()))
    pos = window.mapFromGlobal(QPoint(int(round(x / dpr)), int(round(y / dpr))))
    px, py = int(pos.x()), int(pos.y())
    w = window.width()
    if py < tok.TITLE_BAR_HEIGHT and px < (w - _CONTROL_STRIP_WIDTH):
        return True, HTCLIENT

    return None
