"""Desktop hover slide-out for Render Queue.

Same panel as the splitter pane, clipped into a rounded overlay over mpv.
No drop shadow — Windows fills unpainted mask leftovers with black squares.
"""
from __future__ import annotations

import logging
import sys

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    Property,
)
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

def _hotspot_width(app=None) -> int:
    """Window-edge chrome only — same air as ClipCards / footer, not a second gutter."""
    try:
        from steempeg.ui.layout_defaults import shell_edge_inset

        ui = getattr(app, "ui", None) if app is not None else None
        return max(6, int(shell_edge_inset(ui)))
    except Exception:
        return 9


_PAD = 14
_BULGE_OUT = 22
_BULGE_OVERLAP = 12
_BULGE_H = 128
_RADIUS = 16
_SHEET_INSET_Y = 18
_SHEET_INSET_OUTER = 8
_ANIM_MS = 240
_HIDE_MS = 160
_WATCH_MS = 50
_DWMWA_TRANSITIONS_FORCEDISABLED = 3
_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMSBT_NONE = 1


def _contains_global(widget: QWidget | None, pos) -> bool:
    if widget is None:
        return False
    try:
        if not widget.isVisible():
            return False
        return widget.rect().contains(widget.mapFromGlobal(pos))
    except RuntimeError:
        return False


def _overlay_chrome() -> tuple[QColor, QColor, QColor, QColor]:
    """Plate fill + the same 1px hairline the player / Render Settings use."""
    try:
        from steempeg.ui import ui_theme as ut

        pal = ut.active_palette()
        return (
            QColor(pal.bg_shell),
            QColor(ut.player_chrome_border_color()),
            QColor("#888888"),
            QColor("#c0c0c0"),
        )
    except Exception:
        return (
            QColor("#121212"),
            QColor("#383838"),
            QColor("#888888"),
            QColor("#c0c0c0"),
        )


def _rail_path(
    card: QRect, bulge: QRect, *, radius: int, inflate: float = 0.0
) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    cr = QRectF(card).adjusted(-inflate, -inflate, inflate, inflate)
    rad = float(max(0, radius))
    if rad > 0:
        path.addRoundedRect(cr, rad, rad)
    else:
        path.addRect(cr)
    if bulge.width() > 2 and bulge.height() > 2:
        br = QRectF(bulge).adjusted(-inflate, -inflate, inflate, inflate)
        tab_r = min(br.width(), br.height()) * 0.5
        path.addRoundedRect(br, tab_r, tab_r)
    return path


def _round_region(rect: QRect, radius: float) -> QRegion:
    if rect.width() < 2 or rect.height() < 2:
        return QRegion()
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect), float(radius), float(radius))
    poly = path.toFillPolygon().toPolygon()
    return QRegion(poly) if not poly.isEmpty() else QRegion()


def _shape_mask(card: QRect, bulge: QRect, *, radius: int) -> QRegion:
    """Union card + grip as separate regions.

    ``toFillPolygon`` on a two-subpath path can bite a pill-shaped hole
    opposite the handle; Win32 then fills that leftover black.
    """
    # +1px so the hairline sits inside the HWND mask (else DWM paints a
    # black halo around the grip).
    pad = 1
    region = _round_region(
        card.adjusted(-pad, -pad, pad, pad), float(max(0, radius))
    )
    if bulge.width() > 2 and bulge.height() > 2:
        tab_r = min(bulge.width(), bulge.height()) * 0.5
        region = region.united(
            _round_region(bulge.adjusted(-pad, -pad, pad, pad), tab_r)
        )
    return region


def _strip_overlay_dwm(widget: QWidget) -> None:
    """Kill Win11 mica / accent glow / DWM hide-transition on the Tool HWND."""
    if sys.platform != "win32" or widget is None:
        return
    try:
        from steempeg.ui.window_chrome import refresh_dwm_chrome

        refresh_dwm_chrome(widget)
    except Exception:
        pass
    try:
        import ctypes

        hwnd = int(widget.winId())
        if not hwnd:
            return
        dwm = ctypes.windll.dwmapi
        none = ctypes.c_int(_DWMSBT_NONE)
        dwm.DwmSetWindowAttribute(
            hwnd, _DWMWA_SYSTEMBACKDROP_TYPE, ctypes.byref(none), ctypes.sizeof(none)
        )
        freeze = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(
            hwnd,
            _DWMWA_TRANSITIONS_FORCEDISABLED,
            ctypes.byref(freeze),
            ctypes.sizeof(freeze),
        )
    except Exception:
        pass


def _resolve_host(app) -> QWidget | None:
    """Content wrap sits above the splitter; the window itself is covered by appShell."""
    ui = getattr(app, "ui", None)
    if ui is None:
        return None
    wrap = getattr(ui, "_custom_content_wrap", None)
    if wrap is not None:
        return wrap
    shell = getattr(ui, "_custom_chrome_shell", None)
    if shell is not None:
        return shell
    return ui


def _queue_on_left(app) -> bool:
    check = getattr(app, "_queue_on_left", None)
    if callable(check):
        try:
            return bool(check())
        except Exception:
            return False
    return False


class _Hotspot(QWidget):
    """Thin strip on the window's queue-side edge."""

    def __init__(self, controller: "QueueHoverController", parent=None):
        super().__init__(parent)
        self._controller = controller
        self.setObjectName("queueHoverHotspot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setStyleSheet("background: transparent; border: none;")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def enterEvent(self, event):  # noqa: N802
        self._controller._on_hot_enter()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._controller._on_hot_leave()
        super().leaveEvent(event)


class _Grip(QWidget):
    """Short protruding handle on the player-facing edge."""

    def __init__(self, overlay: "QueueHoverOverlay", parent=None):
        super().__init__(parent)
        self._overlay = overlay
        self.setObjectName("queueHoverGrip")
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setStyleSheet("background: transparent; border: none;")
        self._drag_origin = None
        self._start_w = 0
        self._hovered = False

    def enterEvent(self, event):  # noqa: N802
        self._hovered = True
        self._overlay.update()
        self._overlay._controller._on_hot_enter()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hovered = False
        self._overlay.update()
        if self._drag_origin is None:
            self._overlay._controller._on_hot_leave()
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._drag_origin = event.globalPosition().toPoint().x()
        self._start_w = int(self._overlay._panel_w)
        self._overlay._controller._resizing = True
        self.grabMouse()
        event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_origin is None:
            return
        now = event.globalPosition().toPoint().x()
        delta = now - self._drag_origin
        if self._overlay._from_left:
            self._overlay.set_panel_width(self._start_w + delta)
        else:
            self._overlay.set_panel_width(self._start_w - delta)
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._finish_drag()
        event.accept()

    def _finish_drag(self) -> None:
        if self._drag_origin is None:
            return
        self._drag_origin = None
        try:
            self.releaseMouse()
        except RuntimeError:
            pass
        ctrl = self._overlay._controller
        ctrl._resizing = False
        ctrl._persist_width()


class QueueHoverOverlay(QWidget):
    """Rounded host that holds the real Render Queue panel.

    A child widget cannot paint over embedded mpv (``wid=`` HWND). Same family
    as buffering / timeline chips: a frameless ``Qt.Tool`` composited by the OS.
    """

    def __init__(self, controller: "QueueHoverController", parent=None):
        ui = getattr(getattr(controller, "_app", None), "ui", None)
        super().__init__(None if sys.platform == "win32" else (parent or ui))
        self._controller = controller
        self._slide = 0.0
        self._panel_w = 360
        self._from_left = False
        self._card = QRect()
        self._bulge = QRect()
        self.setObjectName("queueHoverOverlay")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self.hide()
        if sys.platform == "win32":
            try:
                from steempeg.infra.window_focus import detach_tool_ownership

                detach_tool_ownership(self)
            except Exception:
                pass

        self._body = QFrame(self)
        self._body.setObjectName("queueHoverBody")
        self._body.setStyleSheet("background: transparent; border: none;")
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(_PAD, _PAD, _PAD, _PAD)
        self._body_lay.setSpacing(0)

        self._grip = _Grip(self, self)

        self._anim = QPropertyAnimation(self, b"slide", self)
        self._anim.setDuration(_ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._on_anim_finished)

    def get_slide(self) -> float:
        return float(self._slide)

    def set_slide(self, value: float) -> None:
        self._slide = max(0.0, min(1.0, float(value)))
        self._apply_geometry()
        self.update()

    slide = Property(float, get_slide, set_slide)

    def set_panel_width(self, width: int) -> None:
        self._panel_w = self._clamp_width(width)
        self._apply_geometry()

    def _clamp_width(self, width: int) -> int:
        app = self._controller._app
        win = getattr(app, "ui", None)
        win_w = int(win.width() or 0) if win is not None else 0
        min_w = 520
        floor = 360
        try:
            from steempeg.ui.layout_defaults import (
                PLAYER_COLUMN_FLOOR,
                queue_hover_min_width,
            )

            floor = int(PLAYER_COLUMN_FLOOR)
            min_w = int(queue_hover_min_width(win_w, widget=win) if win_w else min_w)
        except Exception:
            pass
        max_w = max(min_w, win_w - floor - 80) if win_w else max(min_w, int(width))
        return max(min_w, min(int(width), int(max_w)))

    def host_panel(self, panel: QWidget) -> None:
        if panel is None:
            return
        self._body_lay.addWidget(panel)
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        if hasattr(panel, "set_hover_hosted"):
            try:
                panel.set_hover_hosted(True)
            except RuntimeError:
                pass
        panel.show()

    def enterEvent(self, event):  # noqa: N802
        self._controller._on_hot_enter()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._controller._on_hot_leave()
        super().leaveEvent(event)

    def _on_anim_finished(self) -> None:
        if self._slide <= 0.001 and not self._controller.is_revealed():
            self.hide()

    def _apply_geometry(self) -> None:
        host = self._controller._host
        if host is None:
            return
        span = self._controller._span_rect()
        if span.width() <= 0 or span.height() <= 0:
            return
        card_w = int(self._panel_w)
        inset_y = min(_SHEET_INSET_Y, max(12, int(span.height() * 0.03)))
        card_h = max(180, int(span.height()) - inset_y * 2)
        shown = int(round(card_w * self._slide))
        bulge_out = _BULGE_OUT
        outer = _SHEET_INSET_OUTER
        if self.isWindow():
            origin = host.mapToGlobal(span.topLeft())
            ox, oy = int(origin.x()), int(origin.y())
        else:
            parent = self.parentWidget()
            top_left = (
                host.mapTo(parent, span.topLeft()) if parent is not None else span.topLeft()
            )
            ox, oy = int(top_left.x()), int(top_left.y())
        if self._from_left:
            card_x = ox + shown - card_w + outer
            overlay_x = card_x
            overlay_w = card_w + bulge_out
            local_x = 0
        else:
            card_x = ox + int(span.width()) - shown - outer
            overlay_x = card_x - bulge_out
            overlay_w = card_w + bulge_out
            local_x = bulge_out
        overlay_y = oy + inset_y
        overlay_h = card_h
        local_y = 0
        self.setGeometry(overlay_x, overlay_y, overlay_w, overlay_h)
        if sys.platform == "win32":
            try:
                from steempeg.infra.window_focus import detach_tool_ownership

                # setGeometry can re-own the Tool to the shell HWND.
                detach_tool_ownership(self)
            except Exception:
                pass
        self._card = QRect(local_x, local_y, card_w, card_h)
        grip_h = min(_BULGE_H, max(64, card_h - 48))
        grip_y = local_y + max(8, (card_h - grip_h) // 2)
        if self._from_left:
            self._bulge = QRect(
                self._card.right() - _BULGE_OVERLAP,
                grip_y,
                bulge_out + _BULGE_OVERLAP,
                grip_h,
            )
        else:
            self._bulge = QRect(
                local_x - bulge_out,
                grip_y,
                bulge_out + _BULGE_OVERLAP,
                grip_h,
            )
        self._body.setGeometry(self._card)
        self._grip.setGeometry(self._bulge)
        self._grip.raise_()
        try:
            region = _shape_mask(self._card, self._bulge, radius=_RADIUS)
            if region.isEmpty():
                self.clearMask()
            else:
                self.setMask(region)
        except RuntimeError:
            self.clearMask()

    def paintEvent(self, event):  # noqa: N802
        if self._slide <= 0.0:
            return
        card = self._card
        if card.width() <= 2 or card.height() <= 2:
            return
        bg, border, grip_idle, grip_hot = _overlay_chrome()
        # Fill 1px past the plate so the mask/stroke halo is panel colour, not black.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillPath(
            _rail_path(card, self._bulge, radius=_RADIUS, inflate=1.0), bg
        )
        rim = QPen(border)
        rim.setWidthF(1.0)
        rim.setCosmetic(True)
        painter.setPen(rim)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(_rail_path(card, self._bulge, radius=_RADIUS))
        bulge = QRectF(self._bulge)
        if bulge.width() > 2 and bulge.height() > 2:
            line_w = 5.0
            pad = 26.0
            if self._from_left:
                cx = bulge.left() + _BULGE_OVERLAP + _BULGE_OUT * 0.5
            else:
                cx = bulge.left() + _BULGE_OUT * 0.5
            line = QRectF(
                cx - line_w * 0.5,
                bulge.top() + pad,
                line_w,
                max(24.0, bulge.height() - pad * 2.0),
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(grip_hot if self._grip._hovered else grip_idle)
            painter.drawRoundedRect(line, 2.5, 2.5)
        painter.end()


class QueueHoverController(QObject):
    """Owns overlay + hotspot and reparents the real queue panel."""

    def __init__(self, app):
        super().__init__(app.ui if getattr(app, "ui", None) is not None else None)
        self._app = app
        self._enabled = False
        self._suspended = False
        self._revealed = False
        self._resizing = False
        self._add_peek = False
        self._host = _resolve_host(app)
        self._overlay = QueueHoverOverlay(self, self._host)
        self._hotspot = _Hotspot(self, self._host)
        self._hotspot.hide()
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(_HIDE_MS)
        self._hide_timer.timeout.connect(self._conceal_if_idle)
        # Tool HWND leave events are unreliable; poll cursor while the panel is out.
        self._watch = QTimer(self)
        self._watch.setInterval(_WATCH_MS)
        self._watch.timeout.connect(self._watch_cursor)
        if self._host is not None:
            self._host.installEventFilter(self)
        ui = getattr(app, "ui", None)
        if ui is not None and ui is not self._host:
            ui.installEventFilter(self)
        qapp = QApplication.instance()
        if qapp is not None:
            qapp.installEventFilter(self)

    def is_enabled(self) -> bool:
        return bool(self._enabled) and not bool(self._suspended)

    def is_revealed(self) -> bool:
        return bool(self._revealed)

    def peek_add_to_queue(self, clip_paths: list[str]) -> None:
        """Open the hover drawer and preview where Add to queue would land."""
        self._add_peek = True
        self._set_peek_click_through(True)
        if self.is_enabled():
            self.reveal()
        panel = getattr(self._app, "render_queue_panel", None)
        if panel is not None and hasattr(panel, "set_add_peek"):
            try:
                panel.set_add_peek(list(clip_paths or []))
            except RuntimeError:
                pass

    def clear_add_peek(self) -> None:
        was = self._add_peek
        self._add_peek = False
        self._set_peek_click_through(False)
        panel = getattr(self._app, "render_queue_panel", None)
        if panel is not None and hasattr(panel, "clear_add_peek"):
            try:
                panel.clear_add_peek()
            except RuntimeError:
                pass
        if was and self._revealed:
            self._on_hot_leave()

    def _set_peek_click_through(self, enabled: bool) -> None:
        """Menu + Tool HWND click is a Win32 hang. Peek is preview-only."""
        targets = [self._overlay]
        grip = getattr(self._overlay, "_grip", None)
        if grip is not None:
            targets.append(grip)
        body = getattr(self._overlay, "_body", None)
        if body is not None:
            targets.append(body)
        panel = getattr(self._app, "render_queue_panel", None)
        if panel is not None:
            targets.append(panel)
        for widget in targets:
            try:
                widget.setAttribute(
                    Qt.WidgetAttribute.WA_TransparentForMouseEvents, bool(enabled)
                )
            except RuntimeError:
                pass

    def _forward_peek_wheel(self, event) -> bool:
        panel = getattr(self._app, "render_queue_panel", None)
        if panel is None or not hasattr(panel, "apply_wheel_delta"):
            return False
        try:
            return bool(panel.apply_wheel_delta(event))
        except RuntimeError:
            return False

    def _obj_is_peek_chrome(self, obj) -> bool:
        roots = (
            self._overlay,
            getattr(self._overlay, "_body", None),
            getattr(self._overlay, "_grip", None),
            getattr(self._app, "render_queue_panel", None),
        )
        walk = obj
        while walk is not None:
            if walk in roots:
                return True
            try:
                walk = walk.parentWidget() if hasattr(walk, "parentWidget") else None
            except RuntimeError:
                break
        return False

    def _popup_belongs_to_queue(self, popup) -> bool:
        roots = {self._overlay, getattr(self._app, "render_queue_panel", None)}
        walk = popup
        while walk is not None:
            if walk in roots:
                return True
            try:
                walk = walk.parentWidget()
            except RuntimeError:
                break
        return False

    def set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if getattr(self._app, "_portable_shell", False):
            enabled = False
        if enabled == self._enabled:
            if enabled:
                self.sync_side()
                self.sync_geometry()
            return
        if enabled:
            self._adopt_host()
            self._dock_to_overlay()
            self._enabled = True
            self._suspended = False
            self.sync_side()
            self.sync_geometry()
            self._hotspot.show()
            self.conceal(animated=False)
        else:
            was_open = self._revealed
            self.conceal(animated=False)
            self._enabled = False
            self._hotspot.hide()
            self._restore_to_splitter(open_docked=was_open)

    def set_suspended(self, suspended: bool) -> None:
        suspended = bool(suspended)
        if self._suspended == suspended:
            if suspended:
                try:
                    self._hotspot.hide()
                except RuntimeError:
                    pass
            return
        self._suspended = suspended
        if not self._enabled:
            return
        if suspended:
            self.conceal(animated=False)
            self._hotspot.hide()
        else:
            self.sync_geometry()

    def reveal(self, *, animated: bool = True) -> None:
        if not self.is_enabled():
            return
        self._hide_timer.stop()
        panel = getattr(self._app, "render_queue_panel", None)
        opening = not self._revealed
        if panel is not None:
            try:
                panel.show()
            except RuntimeError:
                pass
            if opening and not self._add_peek and hasattr(panel, "restore_rest_scroll"):
                try:
                    panel.restore_rest_scroll()
                except RuntimeError:
                    pass
        self._overlay._from_left = _queue_on_left(self._app)
        if not self._revealed and not self._resizing:
            self._overlay.set_panel_width(self._current_width())
        self._overlay._apply_geometry()
        self._show_overlay()
        self._revealed = True
        self._watch.start()
        self._run_slide(1.0, animated=animated)
        QTimer.singleShot(0, self.sync_geometry)

    def conceal(self, *, animated: bool = True) -> None:
        if not self._add_peek:
            panel = getattr(self._app, "render_queue_panel", None)
            if panel is not None and hasattr(panel, "remember_rest_scroll"):
                try:
                    panel.remember_rest_scroll()
                except RuntimeError:
                    pass
        self._hide_timer.stop()
        self._watch.stop()
        self._revealed = False
        if not animated or self._overlay._slide <= 0.001:
            self._overlay.set_slide(0.0)
            self._overlay.hide()
            return
        self._run_slide(0.0, animated=True)

    def sync_side(self) -> None:
        self._overlay._from_left = _queue_on_left(self._app)
        self.sync_geometry()

    def sync_geometry(self) -> None:
        self._place_hotspot()
        if self._revealed or self._overlay.isVisible():
            self._overlay._from_left = _queue_on_left(self._app)
            self._overlay._apply_geometry()

    def eventFilter(self, obj, event):  # noqa: N802
        et = event.type()
        ui = getattr(self._app, "ui", None)
        if obj in (self._host, ui) and et in (
            QEvent.Type.Resize,
            QEvent.Type.Move,
            QEvent.Type.WindowStateChange,
        ):
            self.sync_geometry()
            return False
        if (
            self._add_peek
            and et
            in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseButtonDblClick,
            )
            and self._obj_is_peek_chrome(obj)
        ):
            return True
        if et == QEvent.Type.Wheel and self._add_peek:
            return self._forward_peek_wheel(event)
        if not self.is_enabled():
            return False
        if self._resizing:
            if et == QEvent.Type.MouseButtonRelease:
                grip = getattr(self._overlay, "_grip", None)
                if grip is not None:
                    grip._finish_drag()
            return False
        if et not in (
            QEvent.Type.MouseMove,
            QEvent.Type.HoverMove,
            QEvent.Type.HoverEnter,
            QEvent.Type.Leave,
            QEvent.Type.HoverLeave,
        ):
            return False
        if self._should_stay_open():
            self._on_hot_enter()
        elif self._revealed:
            self._on_hot_leave()
        return False

    def _adopt_host(self) -> None:
        host = _resolve_host(self._app)
        if host is None or host is self._host:
            return
        if self._host is not None:
            try:
                self._host.removeEventFilter(self)
            except RuntimeError:
                pass
        self._host = host
        self._hotspot.setParent(host)
        host.installEventFilter(self)

    def _show_overlay(self) -> None:
        overlay = self._overlay
        overlay.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        if sys.platform == "win32":
            try:
                from steempeg.infra.window_focus import detach_tool_ownership

                detach_tool_ownership(overlay)
            except Exception:
                pass
            try:
                import ctypes

                overlay.createWinId()
                hwnd = int(overlay.winId())
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
                    if not overlay.isVisible():
                        overlay.setVisible(True)
                    _strip_overlay_dwm(overlay)
                    # No raise_() — that re-stacks the shell over other apps
                    # without touching the mpv embed HWND.
                    return
            except Exception:
                pass
        overlay.show()
        _strip_overlay_dwm(overlay)

    def _run_slide(self, target: float, *, animated: bool) -> None:
        anim = self._overlay._anim
        # stop() emits finished(); don't let that unmap the window mid-slide.
        anim.blockSignals(True)
        anim.stop()
        anim.blockSignals(False)
        if not animated:
            self._overlay.set_slide(target)
            if target <= 0.0:
                self._overlay.hide()
            return
        # OutCubic both ways — InCubic hide starts slow then snaps, which reads
        # as "no animation" when the cursor is already far away.
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(float(self._overlay._slide))
        anim.setEndValue(float(target))
        anim.start()

    def _on_hot_enter(self) -> None:
        if not self.is_enabled() or self._resizing:
            return
        self._hide_timer.stop()
        if self._revealed:
            return
        self.reveal()

    def _on_hot_leave(self) -> None:
        if not self.is_enabled() or not self._revealed or self._resizing:
            return
        if self._should_stay_open():
            return
        # Do not restart — every player MouseMove used to push hide forever.
        if not self._hide_timer.isActive():
            self._hide_timer.start()

    def _watch_cursor(self) -> None:
        if not self.is_enabled() or not self._revealed or self._resizing:
            return
        if self._should_stay_open():
            self._hide_timer.stop()
            return
        if not self._hide_timer.isActive():
            self._hide_timer.start()

    def _should_stay_open(self) -> bool:
        if self._resizing:
            return True
        if self._add_peek:
            return True
        if self._pointer_over_chrome() or self._edge_contains_cursor():
            return True
        try:
            popup = QApplication.activePopupWidget()
        except RuntimeError:
            popup = None
        if popup is not None and self._popup_belongs_to_queue(popup):
            return True
        return False

    def _conceal_if_idle(self) -> None:
        if self._should_stay_open():
            return
        self.conceal()

    def _edge_contains_cursor(self) -> bool:
        try:
            if not self._hotspot.isVisible():
                self._place_hotspot()
        except RuntimeError:
            return False
        return _contains_global(self._hotspot, QCursor.pos())

    def _pointer_over_chrome(self) -> bool:
        overlay = self._overlay
        pos = QCursor.pos()
        if overlay is not None:
            try:
                if overlay.isVisible() and float(overlay._slide) > 0.01:
                    local = overlay.mapFromGlobal(pos)
                    if overlay._card.contains(local) or overlay._bulge.contains(local):
                        return True
            except RuntimeError:
                pass
        if _contains_global(self._hotspot, pos):
            return True
        if _contains_global(getattr(overlay, "_grip", None), pos):
            return True
        under = None
        app = QApplication.instance()
        if app is not None:
            try:
                under = app.widgetAt(pos)
            except RuntimeError:
                under = None
        roots = (
            overlay,
            self._hotspot,
            getattr(overlay, "_grip", None) if overlay is not None else None,
            getattr(overlay, "_body", None) if overlay is not None else None,
            getattr(self._app, "render_queue_panel", None),
        )
        walk = under
        while walk is not None:
            if walk in roots:
                return True
            try:
                walk = walk.parentWidget()
            except RuntimeError:
                break
        return False

    def _span_rect(self) -> QRect:
        """Drawer X uses the content edge; Y/H match the splitter (title/bottom inset)."""
        host = self._host
        if host is None:
            return QRect()
        hr = host.rect()
        ui = getattr(self._app, "ui", None)
        splitter = getattr(ui, "main_splitter", None) if ui is not None else None
        y, h = int(hr.y()), int(hr.height())
        if splitter is not None:
            try:
                top_left = splitter.mapTo(host, splitter.rect().topLeft())
                y = int(top_left.y())
                h = int(splitter.height())
            except RuntimeError:
                y, h = int(hr.y()), int(hr.height())
        else:
            margins = (9, 11, 9, 9)
            if ui is not None:
                margins = getattr(ui, "_custom_content_margins", margins)
            y = int(hr.y()) + int(margins[1])
            h = int(hr.height()) - int(margins[1]) - int(margins[3])
        return QRect(int(hr.x()), y, int(hr.width()), max(0, h))

    def _immersive_chrome(self) -> bool:
        """Fullscreen / theatre — no hover strip (hover is suspended)."""
        app = self._app
        return bool(getattr(app, "is_fullscreen", False)) or bool(
            getattr(app, "is_theater", False)
        )

    def _place_hotspot(self) -> None:
        span = self._span_rect()
        if span.width() <= 0:
            return
        strip = _hotspot_width(self._app)
        if _queue_on_left(self._app):
            self._hotspot.setGeometry(span.x(), span.y(), strip, span.height())
        else:
            self._hotspot.setGeometry(
                span.x() + span.width() - strip,
                span.y(),
                strip,
                span.height(),
            )
        # Resize / sync_geometry must not resurrect the strip in immersive.
        if self.is_enabled() and not self._immersive_chrome():
            self._hotspot.show()
        else:
            self._hotspot.hide()

    def _current_width(self) -> int:
        app = self._app
        saved = None
        if hasattr(app, "get_layout_setting"):
            saved = app.get_layout_setting("queue_panel_width", None)
        try:
            saved_w = int(saved) if saved is not None else 0
        except (TypeError, ValueError):
            saved_w = 0
        if saved_w > 48:
            try:
                from steempeg.ui.layout_defaults import queue_hover_min_width

                win = getattr(app, "ui", None)
                win_w = int(win.width() or 0) if win is not None else 0
                return max(saved_w, int(queue_hover_min_width(win_w, widget=win)))
            except Exception:
                return max(saved_w, 520)
        win = getattr(app, "ui", None)
        win_w = int(win.width() or 0) if win is not None else 0
        try:
            from steempeg.ui.layout_defaults import (
                queue_hover_min_width,
                queue_panel_open_width,
            )

            opened = int(queue_panel_open_width(win_w) if win_w else 520)
            return max(opened, int(queue_hover_min_width(win_w, widget=win)))
        except Exception:
            return 520

    def _persist_width(self) -> None:
        app = self._app
        width = int(self._overlay._panel_w)
        if width > 48 and hasattr(app, "save_layout_setting"):
            try:
                app.save_layout_setting("queue_panel_width", width)
            except Exception:
                logging.debug("queue hover width persist skipped", exc_info=True)

    def _ensure_slot(self) -> QWidget:
        slot = getattr(self._app, "_queue_hover_slot", None)
        if slot is not None:
            return slot
        slot = QWidget()
        slot.setObjectName("queueHoverSlot")
        slot.setMinimumWidth(0)
        slot.setMaximumWidth(0)
        slot.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        slot.setStyleSheet("background: transparent; border: none;")
        self._app._queue_hover_slot = slot
        return slot

    def _dock_to_overlay(self) -> None:
        app = self._app
        panel = getattr(app, "render_queue_panel", None)
        if panel is None:
            return
        splitter, idx = (None, -1)
        if hasattr(app, "_queue_splitter_and_index"):
            splitter, idx = app._queue_splitter_and_index()
        slot = self._ensure_slot()
        if isinstance(splitter, QSplitter) and idx >= 0:
            try:
                if splitter.indexOf(slot) < 0:
                    if hasattr(app, "_queue_pane_width"):
                        live_w = int(app._queue_pane_width())
                        if live_w > 48:
                            self._overlay.set_panel_width(live_w)
                    # Parent onto the hidden overlay first so the panel never
                    # becomes a top-level window (xcb flash).
                    self._overlay.host_panel(panel)
                    if splitter.indexOf(slot) < 0:
                        if idx >= splitter.count():
                            splitter.addWidget(slot)
                        else:
                            splitter.insertWidget(idx, slot)
            except RuntimeError:
                self._overlay.host_panel(panel)
        else:
            self._overlay.host_panel(panel)
        if hasattr(app, "_set_queue_pane_width"):
            try:
                app._set_queue_pane_width(0)
            except Exception:
                pass
        self._set_queue_handle_visible(False)
        if hasattr(panel, "set_hover_hosted"):
            try:
                panel.set_hover_hosted(True)
            except RuntimeError:
                pass

    def _restore_to_splitter(self, *, open_docked: bool) -> None:
        app = self._app
        panel = getattr(app, "render_queue_panel", None)
        slot = getattr(app, "_queue_hover_slot", None)
        if panel is None:
            return
        splitter, idx = (None, -1)
        if slot is not None and hasattr(app, "_queue_splitter_and_index"):
            splitter, idx = app._queue_splitter_and_index()
        self._set_queue_handle_visible(True)
        if panel is not None and hasattr(panel, "set_hover_hosted"):
            try:
                panel.set_hover_hosted(False)
            except RuntimeError:
                pass
        if isinstance(splitter, QSplitter) and idx >= 0 and slot is not None:
            try:
                if splitter.indexOf(slot) >= 0:
                    splitter.replaceWidget(idx, panel)
            except RuntimeError:
                pass
        if slot is not None:
            try:
                slot.setParent(None)
                slot.deleteLater()
            except RuntimeError:
                pass
            app._queue_hover_slot = None
        if hasattr(panel, "setMaximumWidth"):
            try:
                panel.setMaximumWidth(16777215)
            except RuntimeError:
                pass
        panel.show()
        if open_docked and hasattr(app, "_open_queue_in_right_splitter"):
            # Hover is already off — this opens the docked pane.
            app._open_queue_in_right_splitter()
        elif hasattr(app, "_set_queue_pane_width"):
            app._set_queue_pane_width(0)

    def _queue_handle_splitter(self):
        app = self._app
        if _queue_on_left(app):
            return getattr(getattr(app, "ui", None), "main_splitter", None)
        return getattr(app, "right_h_splitter", None)

    def _set_queue_handle_visible(self, visible: bool) -> None:
        app = self._app
        splitter = self._queue_handle_splitter()
        if splitter is None:
            return
        setter = getattr(app, "_set_splitter_handle_visible", None)
        if callable(setter):
            setter(splitter, visible, 1)
        try:
            if visible:
                width = int(getattr(app, "_queue_hover_saved_handle_w", 0) or 0)
                splitter.setHandleWidth(width if width > 0 else 6)
            else:
                live = int(splitter.handleWidth() or 0)
                if live > 0:
                    app._queue_hover_saved_handle_w = live
                splitter.setHandleWidth(0)
            handle = splitter.handle(1) if splitter.count() >= 2 else None
            if handle is not None:
                handle.setVisible(bool(visible))
        except RuntimeError:
            pass
