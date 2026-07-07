"""Custom main-window chrome.

Approach: keep the window fully NATIVE (all Win32 styles: frame, shadow, Aero
Snap, min/max animations) and only intercept WM_NCCALCSIZE so Windows stops
*painting* its title bar. We then draw our own SteempegTitleBar in the client
area and route drag / resize through WM_NCHITTEST. This is how VS Code / Windows
Terminal do frameless — unlike stripping WS_CAPTION, it preserves snap & animations.
"""
from __future__ import annotations

import os

import ctypes
from ctypes import POINTER, cast, wintypes

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from steempeg.infra.paths import get_resource_path
from steempeg.ui import design_tokens as tok

_CONTROL_STRIP_WIDTH = 84
_RESIZE_BORDER = 6

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
    """Single window control dot."""

    def __init__(self, color: str, hover_color: str, symbol: str, parent=None):
        super().__init__(parent)
        self._base = color
        self._hover = hover_color
        self._symbol = symbol
        self.setFixedSize(13, 13)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._apply_style(show_symbol=False)

    def _apply_style(self, *, show_symbol: bool) -> None:
        fg = "#3b1f1a" if self._base == tok.TRAFFIC_CLOSE else "#4a3a00" if self._base == tok.TRAFFIC_MINIMIZE else "#0f3d18"
        self.setText(self._symbol if show_symbol else "")
        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {self._base};
                color: {fg};
                border: none;
                border-radius: 6px;
                font-family: {tok.FONT_UI};
                font-size: 9px;
                font-weight: bold;
                padding: 0;
                margin: 0;
            }}
            QPushButton:hover {{
                background-color: {self._hover};
            }}
            """
        )

    def enterEvent(self, event):
        self._apply_style(show_symbol=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply_style(show_symbol=False)
        super().leaveEvent(event)


class SteempegTitleBar(QWidget):
    """Top chrome: branding left, window controls right (Windows order)."""

    close_requested = Signal()
    minimize_requested = Signal()
    maximize_requested = Signal()

    def __init__(self, window: QWidget, *, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self._window = window
        self.setObjectName("SteempegTitleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(tok.TITLE_BAR_HEIGHT)

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
            root.addWidget(sub_lbl)

        root.addStretch(1)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.btn_minimize = _TrafficLight(tok.TRAFFIC_MINIMIZE, tok.TRAFFIC_MINIMIZE_HOVER, "−")
        self.btn_maximize = _TrafficLight(tok.TRAFFIC_MAXIMIZE, tok.TRAFFIC_MAXIMIZE_HOVER, "⤢")
        self.btn_close = _TrafficLight(tok.TRAFFIC_CLOSE, tok.TRAFFIC_CLOSE_HOVER, "✕")
        controls.addWidget(self.btn_minimize, 0, Qt.AlignmentFlag.AlignVCenter)
        controls.addWidget(self.btn_maximize, 0, Qt.AlignmentFlag.AlignVCenter)
        controls.addWidget(self.btn_close, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(controls)

        self.btn_close.clicked.connect(self.close_requested.emit)
        self.btn_minimize.clicked.connect(self.minimize_requested.emit)
        self.btn_maximize.clicked.connect(self.maximize_requested.emit)

        self.setStyleSheet(
            f"""
            QWidget#SteempegTitleBar {{
                background-color: {tok.BG_TITLE_BAR};
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
            """
        )

    def sync_window_state(self) -> None:
        if self._window.isMaximized():
            self.btn_maximize.setToolTip("Restore")
            self.btn_maximize._symbol = "⤡"
        else:
            self.btn_maximize.setToolTip("Maximize")
            self.btn_maximize._symbol = "⤢"
        self.btn_maximize._apply_style(show_symbol=self.btn_maximize.underMouse())


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
    return title_bar


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
            window.showNormal() if window.isMaximized() else window.showMaximized()
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


def force_full_redraw(window) -> None:
    """Clear a stale native/DWM ghost left after switching into immersive fullscreen.

    A 1px size nudge alone doesn't erase hidden child regions, so also force a
    full RedrawWindow that invalidates + erases every child (mpv surface included)."""
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

    x = ctypes.c_short(msg.lParam & 0xFFFF).value
    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
    pos = window.mapFromGlobal(QPoint(x, y))
    px, py = int(pos.x()), int(pos.y())
    w, h = window.width(), window.height()
    b = _RESIZE_BORDER
    maximized = window.isMaximized()

    if not maximized:
        on_left = px < b
        on_right = px >= w - b
        on_top = py < b
        on_bottom = py >= h - b
        if on_top and on_left:
            return True, HTTOPLEFT
        if on_top and on_right:
            return True, HTTOPRIGHT
        if on_bottom and on_left:
            return True, HTBOTTOMLEFT
        if on_bottom and on_right:
            return True, HTBOTTOMRIGHT
        if on_left:
            return True, HTLEFT
        if on_right:
            return True, HTRIGHT
        if on_top:
            return True, HTTOP
        if on_bottom:
            return True, HTBOTTOM

    # Title strip (minus the control buttons) = caption → native drag / snap /
    # double-click maximize / drag-from-top-to-restore.
    ctrl_right = w - _CONTROL_STRIP_WIDTH
    if py < tok.TITLE_BAR_HEIGHT and px < ctrl_right:
        return True, HTCAPTION
    return None
