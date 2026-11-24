"""Shared mouse, zoom and pan handling for embedded mpv surfaces."""
from __future__ import annotations

import logging
import sys
import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication


class _LinuxPointerHop(QObject):
    """Run a callable on the GUI thread.

    mpv key bindings fire on libmpv's event thread. ``QTimer.singleShot`` from
    that thread does not land on the Qt loop, so the play/pause click was lost.
    """

    call = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.call.connect(self._run, Qt.ConnectionType.QueuedConnection)

    def _run(self, fn) -> None:
        try:
            fn()
        except Exception:
            logging.debug("linux pointer hop failed", exc_info=True)


class VideoSurfaceInput:
    """Handle pointer events for a host providing player, mpv_screen and a click action."""

    def _preview_zoom_surface_size(self) -> tuple[int, int]:
        screen = getattr(self, "mpv_screen", None)
        if screen is None:
            return (1, 1)
        try:
            return (max(1, int(screen.width())), max(1, int(screen.height())))
        except RuntimeError:
            return (1, 1)

    def _preview_zoom_pan_begin(self, x: float, y: float, *, button: str = "left") -> bool:
        """Start a potential pan when zoomed. Returns True if pan mode is active.

        Loupe mode: LMB or RMB drag pans. Outside loupe: LMB pan still works when
        zoomed (e.g. scale set from the % menu).
        """
        # Release handlers skip play/pause after a drag / RMB themselves, so a
        # suppress flag left from the previous gesture would eat this click.
        self._preview_zoom_suppress_click = False
        try:
            from steempeg.ui.player_zoom_chrome import is_preview_zoomed

            if not is_preview_zoomed(self):
                self._preview_zoom_drag = None
                return False
        except Exception:
            self._preview_zoom_drag = None
            return False
        self._preview_zoom_drag = {
            "x": float(x),
            "y": float(y),
            "moved": False,
            "button": button,
        }
        return True

    def _preview_zoom_pan_move(self, x: float, y: float) -> bool:
        """Update pan from drag. Returns True if this event was consumed as a pan."""
        drag = getattr(self, "_preview_zoom_drag", None)
        if not drag:
            return False
        dx = float(x) - float(drag["x"])
        dy = float(y) - float(drag["y"])
        if not drag["moved"]:
            if (dx * dx + dy * dy) < 9.0:  # ~3px threshold
                return False
            drag["moved"] = True
            screen = getattr(self, "mpv_screen", None)
            if screen is not None:
                try:
                    screen.setCursor(Qt.CursorShape.ClosedHandCursor)
                except RuntimeError:
                    pass
        drag["x"] = float(x)
        drag["y"] = float(y)
        try:
            from steempeg.ui.player_zoom_chrome import nudge_preview_pan

            w, h = self._preview_zoom_surface_size()
            nudge_preview_pan(self, dx, dy, surface_w=w, surface_h=h)
        except Exception:
            pass
        return True

    def _preview_zoom_pan_end(self) -> bool:
        """Finish pan. Returns True if a real drag happened (suppress play/pause)."""
        drag = getattr(self, "_preview_zoom_drag", None)
        self._preview_zoom_drag = None
        moved = bool(drag and drag.get("moved"))
        if moved:
            self._preview_zoom_suppress_click = True
        try:
            from steempeg.ui.player_zoom_chrome import sync_preview_zoom_cursor

            sync_preview_zoom_cursor(self)
        except Exception:
            pass
        return moved

    def _install_linux_mpv_pointer_bindings(self) -> None:
        """Play/pause, pan, and wheel on the embedded picture.

        libmpv reparents its own X window into ``mpv_screen`` and selects the
        pointer there. Those events never reach the Qt filter on the parent
        (Windows has the same hole and uses a native message filter). mpv
        already has the click, so bind its mouse keys and hop back to the GUI
        thread — the binding callback runs on libmpv's event thread.
        """
        if sys.platform == "win32":
            return
        player = getattr(self, "player", None)
        if player is None or getattr(player, "_steempeg_pointer_bound", False):
            return

        def phase(state) -> str:
            if isinstance(state, (bytes, bytearray)):
                state = state.decode("utf-8", "replace")
            text = str(state or "")
            if len(text) > 1 and "c" in text[1:]:
                return "cancel"
            return text[:1]

        def xy() -> tuple[float, float]:
            try:
                value = player._get_property("mouse-pos")
            except Exception:
                value = None
            if isinstance(value, dict):
                return float(value.get("x") or 0.0), float(value.get("y") or 0.0)
            return 0.0, 0.0

        def alive() -> bool:
            return getattr(self, "player", None) is player

        hop = getattr(self, "_linux_pointer_hop", None)
        if hop is None:
            hop = _LinuxPointerHop(self if isinstance(self, QObject) else None)
            self._linux_pointer_hop = hop

        def post(fn) -> None:
            hop.call.emit(lambda: fn() if alive() else None)

        def on_left(state, _name, _char, _scale, _arg) -> None:
            if not alive():
                return
            kind = phase(state)
            logging.debug("[video-click] mpv left state=%r phase=%s", state, kind)
            x, y = xy()
            if kind == "d":
                self._linux_ptr_button = "left"
                post(lambda x=x, y=y: self._preview_zoom_pan_begin(x, y, button="left"))
            elif kind == "u":
                self._linux_ptr_button = None
                post(self._linux_embed_left_release)
            elif kind == "p":
                # mpv can deliver an atomic press instead of a down/up pair.
                post(self._on_video_surface_click)
            elif kind == "cancel":
                self._linux_ptr_button = None
                post(self._preview_zoom_pan_end)

        def on_right(state, _name, _char, _scale, _arg) -> None:
            if not alive():
                return
            kind = phase(state)
            x, y = xy()
            if kind == "d":
                self._linux_ptr_button = "right"
                post(lambda x=x, y=y: self._preview_zoom_pan_begin(x, y, button="right"))
            elif kind == "u":
                self._linux_ptr_button = None
                post(self._preview_zoom_pan_end)

        def on_wheel(direction: int):
            def handler(state, _name, _char, scale, _arg) -> None:
                if not alive():
                    return
                if phase(state) not in ("d", "p"):
                    return
                raw = scale.decode("utf-8", "replace") if isinstance(scale, (bytes, bytearray)) else scale
                try:
                    mag = float(raw)
                except (TypeError, ValueError):
                    mag = 1.0
                if mag <= 0:
                    mag = 1.0
                x, y = xy()
                post(
                    lambda x=x, y=y, mag=mag, direction=direction: self._linux_embed_wheel(
                        direction, x, y, mag
                    )
                )

            return handler

        def on_pos(_name, value) -> None:
            if not alive():
                return
            hover = True
            x = y = 0.0
            if isinstance(value, dict):
                hover = bool(value.get("hover", True))
                x = float(value.get("x") or 0.0)
                y = float(value.get("y") or 0.0)
            if getattr(self, "_linux_ptr_button", None):
                post(lambda x=x, y=y: self._preview_zoom_pan_move(x, y))
            if not hover or not getattr(self, "is_fullscreen", False):
                return
            if not hasattr(self, "wake_up_fullscreen_controls"):
                return
            now = time.monotonic()
            last = float(getattr(self, "_linux_fs_wake_at", 0.0) or 0.0)
            if now - last < 0.25:
                return
            self._linux_fs_wake_at = now
            post(self.wake_up_fullscreen_controls)

        try:
            # Each physical click belongs to our transport, including rapid
            # pairs; do not let mpv turn the second press into MBTN_LEFT_DBL.
            player.input_doubleclick_time = 0
            player.register_key_binding("MBTN_LEFT", on_left, "force")
            player.register_key_binding("MBTN_RIGHT", on_right, "force")
            # python-mpv enables allow-vo-dragging by default. Embedded video
            # must not let mpv turn a slightly moving click into a window drag;
            # zoom panning belongs to our own handlers above.
            for key in ("MBTN_LEFT", "MBTN_RIGHT"):
                player.command("enable-section", player._binding_name(key), "allow-hide-cursor")
            player.register_key_binding("WHEEL_UP", on_wheel(1), "force")
            player.register_key_binding("WHEEL_DOWN", on_wheel(-1), "force")
            player.observe_property("mouse-pos", on_pos)
        except Exception:
            logging.warning("Linux preview pointer bindings failed", exc_info=True)
            return
        player._steempeg_pointer_bound = True
        logging.info(
            "Linux preview pointer: video click toggles play/pause "
            "(mpv embed owns the X window)"
        )

    def _linux_embed_left_release(self) -> None:
        moved = self._preview_zoom_pan_end()
        logging.debug("[video-click] GUI release: pan=%s zoom=%s", moved,
                      getattr(self, "_preview_zoom_pct", 100))
        if not moved:
            self._on_video_surface_click()

    def _linux_embed_wheel(self, direction: int, x: float, y: float, scale: float) -> None:
        try:
            from steempeg.ui.player_zoom_chrome import nudge_preview_zoom_wheel

            w, h = self._preview_zoom_surface_size()
            nudge_preview_zoom_wheel(
                self,
                float(direction) * 120.0 * float(scale),
                cursor_x=x,
                cursor_y=y,
                surface_w=w,
                surface_h=h,
            )
        except Exception:
            logging.debug("Linux embed wheel zoom failed", exc_info=True)

    def install_video_surface_click_handler(self) -> None:
        """Catch LMB on the video surface → play/pause pulse (or pan when zoomed).

        Windows: embedded mpv ``wid=`` HWND — ``WM_LBUTTON*`` / ``WM_MOUSEMOVE`` via
        native filter (Qt mouse on the embed is unreliable).
        Linux: the same hole. The Qt filter below only sees clicks that actually
        land on ``mpv_screen``; the embed's own X window is handled by mpv key
        bindings (``_install_linux_mpv_pointer_bindings``).
        """
        if getattr(self, "_video_surface_click_handler_installed", False):
            return
        self._video_surface_click_handler_installed = True

        if sys.platform == "win32":
            self._install_video_surface_native_click_filter()
            try:
                from steempeg.ui.player_zoom_chrome import sync_preview_zoom_cursor

                sync_preview_zoom_cursor(self)
            except Exception:
                screen = getattr(self, "mpv_screen", None)
                if screen is not None:
                    screen.setCursor(Qt.CursorShape.ArrowCursor)
            return

        class _VideoSurfaceClickFilter(QObject):
            def __init__(self, app):
                super().__init__(app)
                self._app = app

            def eventFilter(self, obj, event):  # noqa: N802
                if obj is not getattr(self._app, "mpv_screen", None):
                    return False
                et = event.type()
                if et == QEvent.Type.Wheel:
                    try:
                        from steempeg.ui.player_zoom_chrome import nudge_preview_zoom_wheel

                        delta = event.angleDelta().y()
                        try:
                            pos = event.position()
                            cx, cy = float(pos.x()), float(pos.y())
                        except Exception:
                            p = event.pos()
                            cx, cy = float(p.x()), float(p.y())
                        w, h = self._app._preview_zoom_surface_size()
                        if nudge_preview_zoom_wheel(
                            self._app,
                            float(delta),
                            cursor_x=cx,
                            cursor_y=cy,
                            surface_w=w,
                            surface_h=h,
                        ):
                            return True
                    except Exception:
                        pass
                    return False
                if et in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
                    btn = event.button()
                    if btn not in (
                        Qt.MouseButton.LeftButton,
                        Qt.MouseButton.RightButton,
                    ):
                        return False
                    pos = event.position() if hasattr(event, "position") else event.pos()
                    which = "right" if btn == Qt.MouseButton.RightButton else "left"
                    self._app._preview_zoom_pan_begin(
                        float(pos.x()), float(pos.y()), button=which
                    )
                    # Eat RMB so a context menu does not steal the pan gesture.
                    return which == "right"
                if et == QEvent.Type.MouseMove:
                    buttons = event.buttons()
                    if not (
                        buttons & Qt.MouseButton.LeftButton
                        or buttons & Qt.MouseButton.RightButton
                    ):
                        return False
                    pos = event.position() if hasattr(event, "position") else event.pos()
                    if self._app._preview_zoom_pan_move(float(pos.x()), float(pos.y())):
                        return True
                    return False
                if et == QEvent.Type.MouseButtonRelease:
                    btn = event.button()
                    if btn not in (
                        Qt.MouseButton.LeftButton,
                        Qt.MouseButton.RightButton,
                    ):
                        return False
                    moved = self._app._preview_zoom_pan_end()
                    if btn == Qt.MouseButton.RightButton:
                        return True
                    if moved:
                        return True
                    self._app._on_video_surface_click()
                    return True
                return False

        filt = _VideoSurfaceClickFilter(self)
        self._video_surface_click_filter = filt
        screen = getattr(self, "mpv_screen", None)
        if screen is not None:
            screen.installEventFilter(filt)
            screen.setMouseTracking(True)
            try:
                from steempeg.ui.player_zoom_chrome import sync_preview_zoom_cursor

                sync_preview_zoom_cursor(self)
            except Exception:
                screen.setCursor(Qt.CursorShape.ArrowCursor)

    def _install_video_surface_native_click_filter(self) -> None:
        """Win32: LMB / move on the embed (or pulse tool) HWND → pan or play/pause."""
        if getattr(self, "_video_surface_native_click_filter", None) is not None:
            return
        try:
            from PySide6.QtCore import QAbstractNativeEventFilter
        except ImportError:
            return

        from steempeg.ui.window_chrome import _MSG, _native_event_type_bytes

        _WM_LBUTTONDOWN = 0x0201
        _WM_LBUTTONDBLCLK = 0x0203
        _WM_LBUTTONUP = 0x0202
        _WM_RBUTTONDOWN = 0x0204
        _WM_RBUTTONUP = 0x0205
        _WM_MOUSEMOVE = 0x0200
        _WM_MOUSEWHEEL = 0x020A
        _MK_LBUTTON = 0x0001
        _MK_RBUTTON = 0x0002

        class _MpvSurfaceClickNativeFilter(QAbstractNativeEventFilter):
            def __init__(self, app):
                super().__init__()
                self._app = app
                self._armed = False
                self._armed_button = "left"

            def _mpv_hwnd(self) -> int:
                screen = getattr(self._app, "mpv_screen", None)
                if screen is None:
                    return 0
                try:
                    return int(screen.winId()) or 0
                except RuntimeError:
                    return 0

            def _pulse_hwnd(self) -> int:
                pulse = getattr(self._app, "_play_pause_pulse", None)
                if pulse is None or not hasattr(pulse, "winId"):
                    return 0
                try:
                    if not pulse.isVisible():
                        return 0
                    return int(pulse.winId()) or 0
                except RuntimeError:
                    return 0

            def _is_surface_click_hwnd(self, hwnd: int) -> bool:
                """True only for the embed / pulse — never HUD buttons over the picture."""
                if not hwnd:
                    return False
                if hwnd == self._mpv_hwnd():
                    return True
                # Fallback if pulse lost WS_EX_TRANSPARENT and ate the click.
                if hwnd == self._pulse_hwnd():
                    return True
                return False

            def _cursor_over_mpv(self) -> bool:
                """True when the cursor sits over the embed (wheel often hits Qt parent)."""
                screen = getattr(self._app, "mpv_screen", None)
                if screen is None:
                    return False
                try:
                    if not screen.isVisible():
                        return False
                    from PySide6.QtGui import QCursor

                    gp = QCursor.pos()
                    local = screen.mapFromGlobal(gp)
                    return screen.rect().contains(local)
                except Exception:
                    return False

            def _cursor_local_xy(self) -> tuple[float, float]:
                screen = getattr(self._app, "mpv_screen", None)
                if screen is None:
                    return (0.0, 0.0)
                try:
                    from PySide6.QtGui import QCursor

                    local = screen.mapFromGlobal(QCursor.pos())
                    return (float(local.x()), float(local.y()))
                except Exception:
                    return (0.0, 0.0)

            @staticmethod
            def _client_xy(lparam: int) -> tuple[float, float]:
                x = int(lparam & 0xFFFF)
                if x >= 0x8000:
                    x -= 0x10000
                y = int((lparam >> 16) & 0xFFFF)
                if y >= 0x8000:
                    y -= 0x10000
                return (float(x), float(y))

            @staticmethod
            def _wheel_delta(wparam: int) -> float:
                delta = (int(wparam) >> 16) & 0xFFFF
                if delta >= 0x8000:
                    delta -= 0x10000
                return float(delta)

            def nativeEventFilter(self, eventType, message):  # noqa: N802
                # One channel only — handling both generic + dispatcher double-fires
                # toggle (play then immediate pause).
                if _native_event_type_bytes(eventType) != b"windows_generic_MSG":
                    return False
                try:
                    addr = (
                        int(message)
                        if not hasattr(message, "__int__")
                        else int(message.__int__())
                    )
                    msg = _MSG.from_address(addr)
                except Exception:
                    return False

                hwnd = int(msg.hwnd) if msg.hwnd else 0
                app = self._app

                if msg.message == _WM_MOUSEWHEEL:
                    # Embed wid= often does not own focus — wheel may target a Qt parent.
                    if not (
                        self._is_surface_click_hwnd(hwnd) or self._cursor_over_mpv()
                    ):
                        return False
                    try:
                        from steempeg.ui.player_zoom_chrome import (
                            nudge_preview_zoom_wheel,
                        )

                        cx, cy = self._cursor_local_xy()
                        w, h = app._preview_zoom_surface_size()
                        if nudge_preview_zoom_wheel(
                            app,
                            self._wheel_delta(int(msg.wParam)),
                            cursor_x=cx,
                            cursor_y=cy,
                            surface_w=w,
                            surface_h=h,
                        ):
                            return True
                    except Exception:
                        pass
                    return False

                if msg.message in (_WM_LBUTTONDOWN, _WM_LBUTTONDBLCLK):
                    self._armed = self._is_surface_click_hwnd(hwnd)
                    self._armed_button = "left"
                    if self._armed:
                        x, y = self._client_xy(int(msg.lParam))
                        app._preview_zoom_pan_begin(x, y, button="left")
                    return False

                if msg.message == _WM_RBUTTONDOWN:
                    if not self._is_surface_click_hwnd(hwnd):
                        return False
                    self._armed = True
                    self._armed_button = "right"
                    x, y = self._client_xy(int(msg.lParam))
                    app._preview_zoom_pan_begin(x, y, button="right")
                    # Consume so Windows does not raise a context menu mid-pan.
                    return True

                if msg.message == _WM_MOUSEMOVE:
                    if not self._armed:
                        return False
                    buttons = int(msg.wParam)
                    want = (
                        _MK_RBUTTON
                        if self._armed_button == "right"
                        else _MK_LBUTTON
                    )
                    if not (buttons & want):
                        return False
                    if not self._is_surface_click_hwnd(hwnd):
                        return False
                    x, y = self._client_xy(int(msg.lParam))
                    app._preview_zoom_pan_move(x, y)
                    return self._armed_button == "right"

                if msg.message == _WM_RBUTTONUP:
                    if not self._armed or self._armed_button != "right":
                        return False
                    self._armed = False
                    app._preview_zoom_pan_end()
                    return True

                if msg.message != _WM_LBUTTONUP:
                    return False
                if not self._armed or self._armed_button != "left":
                    return False
                self._armed = False
                if not self._is_surface_click_hwnd(hwnd):
                    app._preview_zoom_pan_end()
                    return False

                if getattr(app, "_is_closing", False):
                    app._preview_zoom_pan_end()
                    return False
                moved = app._preview_zoom_pan_end()
                if moved:
                    return False
                # Defer so we don't re-enter Win32 dispatch from inside the filter.
                screen = getattr(app, "mpv_screen", None)
                if screen is not None:
                    QTimer.singleShot(0, screen, app._on_video_surface_click)
                return False

        native = _MpvSurfaceClickNativeFilter(self)
        self._video_surface_native_click_filter = native
        app = QApplication.instance()
        if app is not None:
            app.installNativeEventFilter(native)


    def _remove_video_surface_click_handler(self) -> None:
        native = getattr(self, "_video_surface_native_click_filter", None)
        if native is not None:
            QApplication.instance().removeNativeEventFilter(native)
            self._video_surface_native_click_filter = None
