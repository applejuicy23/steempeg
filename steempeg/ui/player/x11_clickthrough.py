"""Make an X11 window ignore the pointer without hiding it.

The play/pause pulse is a real Tool window over the video. On Windows it is
``WS_EX_TRANSPARENT``. On Linux/XWayland, ``WA_TransparentForMouseEvents`` only
skips Qt delivery — the X window still hits and eats the next click. An empty
ShapeInput region lets the event fall through to the mpv embed underneath.
"""
from __future__ import annotations

import ctypes
import logging

_XCB_SHAPE_SO_SET = 0
_XCB_SHAPE_SK_INPUT = 2
_XCB_SHAPE_UNSORTED = 0

_libs_ready = False
_xcb = None
_shape = None
_warned = False


class _XcbCookie(ctypes.Structure):
    _fields_ = [("sequence", ctypes.c_uint)]


def _load_shape():
    for name in ("libxcb-shape.so.0", "libxcb-shape.so.1"):
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue
    return None


def _libs():
    global _libs_ready, _xcb, _shape
    if _libs_ready:
        return _xcb, _shape
    _libs_ready = True
    try:
        xcb = ctypes.CDLL("libxcb.so.1")
    except OSError:
        return None, None
    shape = _load_shape()
    if shape is None:
        return None, None

    xcb.xcb_connect.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
    xcb.xcb_connect.restype = ctypes.c_void_p
    xcb.xcb_connection_has_error.argtypes = [ctypes.c_void_p]
    xcb.xcb_connection_has_error.restype = ctypes.c_int
    xcb.xcb_flush.argtypes = [ctypes.c_void_p]
    xcb.xcb_flush.restype = ctypes.c_int
    xcb.xcb_disconnect.argtypes = [ctypes.c_void_p]
    xcb.xcb_disconnect.restype = None

    shape.xcb_shape_rectangles.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint8,
        ctypes.c_uint8,
        ctypes.c_uint8,
        ctypes.c_uint32,
        ctypes.c_int16,
        ctypes.c_int16,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    shape.xcb_shape_rectangles.restype = _XcbCookie
    _xcb, _shape = xcb, shape
    return xcb, shape


def set_x11_input_clickthrough(window_id: int) -> bool:
    """Empty the window's input shape so pointer events pass through it."""
    global _warned
    wid = int(window_id or 0)
    if wid <= 0:
        return False
    xcb, shape = _libs()
    if xcb is None or shape is None:
        return False
    conn = xcb.xcb_connect(None, None)
    if not conn or xcb.xcb_connection_has_error(conn):
        if conn:
            xcb.xcb_disconnect(conn)
        return False
    try:
        shape.xcb_shape_rectangles(
            conn,
            _XCB_SHAPE_SO_SET,
            _XCB_SHAPE_SK_INPUT,
            _XCB_SHAPE_UNSORTED,
            ctypes.c_uint32(wid),
            0,
            0,
            0,
            None,
        )
        xcb.xcb_flush(conn)
        return True
    except Exception:
        if not _warned:
            _warned = True
            logging.debug("X11 input click-through failed", exc_info=True)
        return False
    finally:
        xcb.xcb_disconnect(conn)
