"""Restore mpv's own X11 child after a media/stack visibility transition."""
from __future__ import annotations

import ctypes as c
import logging


class _Cookie(c.Structure):
    _fields_ = [("sequence", c.c_uint)]


def map_mpv_child(parent_id: int) -> int:
    """Map direct mpv children without raising/focusing or mapping placeholders.

    Showing a Qt parent does not map a child explicitly unmapped by libmpv.
    Checked XCB requests tolerate windows disappearing during a media switch;
    unlike default Xlib error handling they cannot terminate the application.
    """
    if not parent_id:
        return 0
    try:
        x = c.CDLL("libxcb.so.1")
        libc = c.CDLL(None)
        libc.free.argtypes = [c.c_void_p]
        x.xcb_connect.argtypes = [c.c_char_p, c.POINTER(c.c_int)]
        x.xcb_connect.restype = c.c_void_p
        x.xcb_connection_has_error.argtypes = [c.c_void_p]
        x.xcb_disconnect.argtypes = [c.c_void_p]
        x.xcb_query_tree.argtypes = [c.c_void_p, c.c_uint32]
        x.xcb_query_tree.restype = _Cookie
        x.xcb_query_tree_reply.argtypes = [c.c_void_p, _Cookie, c.c_void_p]
        x.xcb_query_tree_reply.restype = c.c_void_p
        x.xcb_query_tree_children_length.argtypes = [c.c_void_p]
        x.xcb_query_tree_children.argtypes = [c.c_void_p]
        x.xcb_query_tree_children.restype = c.POINTER(c.c_uint32)
        x.xcb_get_property.argtypes = [c.c_void_p, c.c_uint8, c.c_uint32,
                                      c.c_uint32, c.c_uint32, c.c_uint32, c.c_uint32]
        x.xcb_get_property.restype = _Cookie
        x.xcb_get_property_reply.argtypes = [c.c_void_p, _Cookie, c.c_void_p]
        x.xcb_get_property_reply.restype = c.c_void_p
        x.xcb_get_property_value.argtypes = [c.c_void_p]
        x.xcb_get_property_value.restype = c.c_void_p
        x.xcb_get_property_value_length.argtypes = [c.c_void_p]
        x.xcb_get_window_attributes.argtypes = [c.c_void_p, c.c_uint32]
        x.xcb_get_window_attributes.restype = _Cookie
        x.xcb_get_window_attributes_reply.argtypes = [c.c_void_p, _Cookie, c.c_void_p]
        x.xcb_get_window_attributes_reply.restype = c.c_void_p
        x.xcb_map_window_checked.argtypes = [c.c_void_p, c.c_uint32]
        x.xcb_map_window_checked.restype = _Cookie
        x.xcb_request_check.argtypes = [c.c_void_p, _Cookie]
        x.xcb_request_check.restype = c.c_void_p
        conn = x.xcb_connect(None, None)
        if not conn:
            return 0
        tree = None
        try:
            if x.xcb_connection_has_error(conn):
                return 0
            tree = x.xcb_query_tree_reply(conn, x.xcb_query_tree(conn, parent_id), None)
            if not tree:
                return 0
            children = x.xcb_query_tree_children(tree)
            mapped = 0
            for index in range(x.xcb_query_tree_children_length(tree)):
                child = children[index]
                # Predefined atoms: WM_CLASS=67, STRING=31. Property consists
                # of instance\0class\0; mpv's GL child identifies as gl\0mpv\0.
                prop = x.xcb_get_property_reply(
                    conn, x.xcb_get_property(conn, 0, child, 67, 31, 0, 256), None)
                if not prop:
                    continue
                try:
                    length = x.xcb_get_property_value_length(prop)
                    value = c.string_at(x.xcb_get_property_value(prop), length)
                    fields = value.rstrip(b"\0").split(b"\0")
                    if len(fields) < 2 or fields[1].lower() != b"mpv":
                        continue
                    attrs = x.xcb_get_window_attributes_reply(
                        conn, x.xcb_get_window_attributes(conn, child), None)
                    if not attrs:
                        continue
                    try:
                        # xcb_get_window_attributes_reply_t.map_state, byte 26.
                        state = c.string_at(attrs, 27)[26]
                    finally:
                        libc.free(attrs)
                    if state == 0:
                        logging.warning("[embed-visibility] restoring unmapped mpv child=0x%x "
                                        "parent=0x%x", child, parent_id)
                    error = x.xcb_request_check(conn, x.xcb_map_window_checked(conn, child))
                    if error:
                        libc.free(error)
                    else:
                        mapped += 1
                finally:
                    libc.free(prop)
            return mapped
        finally:
            if tree:
                libc.free(tree)
            x.xcb_disconnect(conn)
    except OSError:
        logging.debug("X11 mpv child mapping unavailable", exc_info=True)
        return 0
