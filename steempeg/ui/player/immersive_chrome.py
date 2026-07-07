"""Immersive chrome without Qt showFullScreen() or setWindowFlags ping-pong on Windows.

On Windows we strip the native caption via Win32 so Qt never hides/recreates the
top-level window. Other platforms fall back to FramelessWindowHint.
"""
import ctypes
import os

from PySide6.QtCore import Qt

GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
SWP_FRAMECHANGED = 0x0020
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004

# Hide caption + system menu only — keep MIN/MAX box styles so Aero Snap & animations work.
_CAPTION_ONLY_MASK = WS_CAPTION | WS_SYSMENU
_BORDERLESS_MASK = WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX


def win32_hide_native_caption(widget):
    """Remove native title-bar chrome but keep WS_THICKFRAME for edge resize."""
    hwnd = _hwnd(widget)
    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style & ~_CAPTION_ONLY_MASK)
    _frame_changed(hwnd)
    return style


def win32_restore_native_caption(widget, saved_style):
    hwnd = _hwnd(widget)
    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, saved_style)
    _frame_changed(hwnd)


def _hwnd(widget):
    return int(widget.winId())


def _frame_changed(hwnd):
    ctypes.windll.user32.SetWindowPos(
        hwnd, 0, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
    )


def win32_hide_title_bar(widget):
    hwnd = _hwnd(widget)
    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style & ~_BORDERLESS_MASK)
    _frame_changed(hwnd)
    return style


def win32_restore_title_bar(widget, saved_style):
    hwnd = _hwnd(widget)
    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, saved_style)
    _frame_changed(hwnd)


_SW_SHOWNORMAL = 1
_MONITOR_DEFAULTTONEAREST = 2


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("showCmd", ctypes.c_uint),
        ("ptMinPosition", _POINT),
        ("ptMaxPosition", _POINT),
        ("rcNormalPosition", _RECT),
    ]


def win32_unmaximize_to_rect(widget, x, y, w, h):
    """Drop the maximize state while setting the *normal* geometry directly to the
    target rect — avoids the intermediate small-window paint that leaves a ghost."""
    hwnd = _hwnd(widget)
    wp = _WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(_WINDOWPLACEMENT)
    ctypes.windll.user32.GetWindowPlacement(hwnd, ctypes.byref(wp))
    wp.showCmd = _SW_SHOWNORMAL
    wp.rcNormalPosition = _RECT(int(x), int(y), int(x + w), int(y + h))
    ctypes.windll.user32.SetWindowPlacement(hwnd, ctypes.byref(wp))


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", ctypes.c_ulong),
    ]


def win32_monitor_bounds(widget):
    """Physical-pixel monitor rect for the window's screen (avoids Qt logical/DPI mismatch)."""
    hwnd = _hwnd(widget)
    hmon = ctypes.windll.user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    if not ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
        return None
    r = info.rcMonitor
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def win32_set_bounds(widget, x, y, w, h):
    ctypes.windll.user32.SetWindowPos(
        _hwnd(widget), 0, int(x), int(y), int(w), int(h),
        SWP_NOZORDER | SWP_FRAMECHANGED,
    )


def enter_immersive_chrome(window, screen_geometry):
    """Hide the native title bar. State is stored on *window*."""
    window._immersive_chrome_mode = None
    window._immersive_was_maximized = window.isMaximized()
    window._immersive_saved_geometry = (
        window.normalGeometry() if window._immersive_was_maximized else window.geometry()
    )

    if os.name == 'nt':
        # Do NOT strip Win32 styles or move the window via Win32 here. The window
        # already has its native caption suppressed by the persistent WM_NCCALCSIZE
        # handler (window_chrome.handle_native_event), which stays active even while
        # the title bar is hidden. We only need to (a) drop the maximize state at the
        # Qt level so Qt's layout matches the physical window, and (b) size the window
        # to the full monitor via Qt geometry.
        #
        # Previously we resized a still-"maximized" window with raw Win32 SetWindowPos.
        # Qt kept laying out its content at the old work-area height, so the extra
        # bottom band (taskbar height) was never painted — leaving a stale "ghost" of
        # the windowed bottom UI. Driving the state + geometry through Qt keeps
        # everything consistent, so the client paints edge-to-edge with no ghost.
        window._immersive_chrome_mode = 'nt_geom'
        if window._immersive_was_maximized:
            window.setWindowState(
                window.windowState() & ~Qt.WindowState.WindowMaximized
            )
        window.setGeometry(screen_geometry)
        return

    window._immersive_saved_flags = window.windowFlags()
    window.setWindowFlags(window.windowFlags() | Qt.WindowType.FramelessWindowHint)
    window.setGeometry(screen_geometry)
    window.show()
    window._immersive_chrome_mode = 'qt'


def exit_immersive_chrome(window):
    """Restore title bar / window flags saved by enter_immersive_chrome."""
    mode = getattr(window, '_immersive_chrome_mode', None)
    was_maximized = getattr(window, '_immersive_was_maximized', False)
    saved_geometry = getattr(window, '_immersive_saved_geometry', None)

    if mode == 'nt_geom':
        # Mirror of the Qt-geometry enter path: just restore the window state /
        # geometry. No Win32 style restore needed (styles were never touched).
        if was_maximized:
            window.showMaximized()
        elif saved_geometry is not None:
            window.setGeometry(saved_geometry)
        window._immersive_chrome_mode = None
        return

    if mode == 'qt':
        saved_flags = getattr(window, '_immersive_saved_flags', None)
        if saved_flags is not None:
            window.setWindowFlags(saved_flags)
        if was_maximized:
            window.showMaximized()
        else:
            window.show()
            if saved_geometry is not None:
                window.setGeometry(saved_geometry)
        window._immersive_chrome_mode = None
