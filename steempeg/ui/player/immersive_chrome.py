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


def win32_set_bounds(widget, x, y, w, h):
    ctypes.windll.user32.SetWindowPos(_hwnd(widget), 0, int(x), int(y), int(w), int(h), SWP_NOZORDER)


def enter_immersive_chrome(window, screen_geometry):
    """Hide the native title bar. State is stored on *window*."""
    window._immersive_chrome_mode = None
    window._immersive_was_maximized = window.isMaximized()
    window._immersive_saved_geometry = (
        window.normalGeometry() if window._immersive_was_maximized else window.geometry()
    )

    if os.name == 'nt':
        window._immersive_win32_style = win32_hide_title_bar(window)
        window._immersive_chrome_mode = 'win32'
        win32_set_bounds(
            window,
            screen_geometry.x(),
            screen_geometry.y(),
            screen_geometry.width(),
            screen_geometry.height(),
        )
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

    if mode == 'win32':
        saved_style = getattr(window, '_immersive_win32_style', None)
        if saved_style is not None:
            win32_restore_title_bar(window, saved_style)
        window._immersive_win32_style = None
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
