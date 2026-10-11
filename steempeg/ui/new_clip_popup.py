"""«New clip» popup — corner card shown when Steam saves a clip.

Same face as the other frameless Steempeg cards (Dead Clip, Render Failed):
accent title, one rounded thumbnail, game row, pill buttons bottom-right.
Never steals focus (the user is usually in a game). Several popups stack
upwards from the bottom-right corner of the primary screen.
"""
from __future__ import annotations

import os

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from steempeg.services.new_clip_watcher import NewClipInfo
from steempeg.ui import design_tokens as tok

_SHELL_PAD = 14
_SCREEN_MARGIN = 18
_STACK_GAP = 10
_SLIDE_PX = 14
_SHOW_MS = 220
_HIDE_MS = 160
AUTO_DISMISS_MS = 15000

_THUMB_W = 280
_THUMB_H = _THUMB_W * 9 // 16
_THUMB_RADIUS = 8
_ICON_PX = 32

_TITLE_QSS = "font-size: 15px;"
_CLOSE_QSS = "QPushButton#ErrorLogToggle { font-size: 14px; padding: 0 2px; }"
_CHIP_QSS = (
    "background-color: #b29ae7; color: black; font-weight: bold; font-size: 11px;"
    f" font-family: {tok.FONT_APP}; border-radius: 4px; padding: 2px 6px;"
)
_GAME_QSS = (
    "color: #e0e0e0; font-weight: bold; font-size: 13px;"
    f" font-family: {tok.FONT_APP}; background: transparent; border: none;"
)
_SAVED_QSS = (
    "color: #888888; font-size: 12px;"
    f" font-family: {tok.FONT_APP}; background: transparent; border: none;"
)


def format_clip_duration(seconds: float | None) -> str:
    """Formats a clip length like the library table does: 31s, 2m 5s, 1h 2m 5s."""
    if not seconds or seconds <= 0:
        return ""
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def build_thumbnail_pixmap(path: str, width: int, height: int) -> QPixmap:
    """Draws the clip thumbnail cover-cropped into one rounded plate (empty plate if missing)."""
    from steempeg.ui import ui_theme as ut

    screen = QGuiApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen is not None else 1.0
    out = QPixmap(int(width * dpr), int(height * dpr))
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    plate = QPainterPath()
    plate.addRoundedRect(QRectF(0, 0, width, height), _THUMB_RADIUS, _THUMB_RADIUS)
    painter.setClipPath(plate)
    painter.fillPath(plate, QColor(ut.clip_card_chrome()[1]))
    source = QPixmap(path) if path and os.path.isfile(path) else QPixmap()
    if not source.isNull():
        scaled = source.scaled(
            int(width * dpr),
            int(height * dpr),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(dpr)
        x = (width - scaled.width() / dpr) / 2
        y = (height - scaled.height() / dpr) / 2
        painter.drawPixmap(QPointF(x, y), scaled)
    painter.end()
    return out


def build_game_icon_pixmap(icon_path: str, size: int) -> QPixmap:
    """Loads the game icon in the shape chosen in Settings → Visual (unknown icon if missing)."""
    from steempeg.infra.paths import get_resource_path
    from steempeg.ui.icon_shape import ICON_SHAPE_CIRCLE, get_icon_shape, shaped_game_icon_pixmap

    if icon_path and os.path.isfile(icon_path):
        return shaped_game_icon_pixmap(QPixmap(icon_path), size, get_icon_shape())
    return shaped_game_icon_pixmap(
        QPixmap(get_resource_path("unknown_icon.png")), size, ICON_SHAPE_CIRCLE
    )


class NewClipPopup(QWidget):
    """One corner card for one new clip."""

    open_requested = Signal(str)
    express_requested = Signal(str)
    dismissed = Signal(object)

    def __init__(self, info: NewClipInfo):
        """Builds the card for the given clip; call ``present()`` to show it."""
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        from steempeg.ui import ui_theme as ut
        from steempeg.ui.icon_utils import apply_square_icon

        self._info = info
        self._closing = False
        self._anim: QParallelAnimationGroup | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self.setFixedWidth(_THUMB_W + 2 * _SHELL_PAD)

        shell = QWidget(self)
        shell.setObjectName("RenderErrorShell")
        shell.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shell.setStyleSheet(ut.render_error_dialog_stylesheet())
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(shell)

        body = QVBoxLayout(shell)
        body.setContentsMargins(_SHELL_PAD, 10, _SHELL_PAD, _SHELL_PAD)
        body.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(6)
        title = QLabel("New clip")
        title.setObjectName("AccentTitle")
        title.setStyleSheet(_TITLE_QSS)
        header.addWidget(title)
        header.addStretch(1)
        close_btn = QPushButton("✕")
        close_btn.setObjectName("ErrorLogToggle")
        close_btn.setStyleSheet(_CLOSE_QSS)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setToolTip("Dismiss")
        close_btn.clicked.connect(self.dismiss)
        header.addWidget(close_btn)
        body.addLayout(header)

        thumb = QLabel()
        thumb.setFixedSize(_THUMB_W, _THUMB_H)
        thumb.setStyleSheet("background: transparent; border: none;")
        thumb.setPixmap(build_thumbnail_pixmap(info.thumbnail_path, _THUMB_W, _THUMB_H))
        thumb.setCursor(Qt.CursorShape.PointingHandCursor)
        thumb.setToolTip(info.path)
        thumb.mousePressEvent = lambda _event: QTimer.singleShot(
            0, lambda: self._emit_and_close(self.open_requested)
        )
        body.addWidget(thumb)

        chip_text = format_clip_duration(info.duration_sec) or "CLIP"
        chip = QLabel(chip_text, thumb)
        chip.setStyleSheet(_CHIP_QSS)
        chip.adjustSize()
        chip.move(_THUMB_W - chip.width() - 6, _THUMB_H - chip.height() - 6)

        game_row = QHBoxLayout()
        game_row.setSpacing(10)
        icon = QLabel()
        icon.setStyleSheet("background: transparent; border: none;")
        apply_square_icon(icon, build_game_icon_pixmap(info.icon_path, _ICON_PX), _ICON_PX)
        game_row.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        game = QLabel(info.game_name)
        game.setStyleSheet(_GAME_QSS)
        text_col.addWidget(game)
        saved = QLabel("Saved just now")
        saved.setStyleSheet(_SAVED_QSS)
        text_col.addWidget(saved)
        self._status_label = saved
        game_row.addLayout(text_col, 1)
        body.addLayout(game_row)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        self._open_btn = QPushButton("Open")
        self._open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_btn.clicked.connect(self._on_open_clicked)
        actions.addWidget(self._open_btn)
        self._express_btn = QPushButton("⚡ Express")
        self._express_btn.setObjectName("AccentBtn")
        self._express_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._express_btn.setToolTip("Render now: Original, or max quality re-encode for clips with Issues")
        self._express_btn.clicked.connect(self._on_express_clicked)
        actions.addWidget(self._express_btn)
        body.addLayout(actions)

        self._render = None
        self._output_file = ""

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.setInterval(AUTO_DISMISS_MS)
        self._dismiss_timer.timeout.connect(self.dismiss)
        self.adjustSize()

    @property
    def clip_path(self) -> str:
        """Returns the clip folder this card is about."""
        return self._info.path

    def present(self, target: QPoint) -> None:
        """Shows the card at ``target`` with a short fade + slide up."""
        self.setWindowOpacity(0.0)
        self.move(target + QPoint(0, _SLIDE_PX))
        self.show()
        self._run_animation(target, 1.0, _SHOW_MS, QEasingCurve.Type.OutCubic)
        self._dismiss_timer.start()

    def move_to(self, target: QPoint) -> None:
        """Slides the card to a new stack slot (when a card below it closes)."""
        if self._closing:
            return
        # Always end fully opaque: this can interrupt the fade-in of a card
        # that was presented a moment ago.
        self._run_animation(target, 1.0, _SHOW_MS, QEasingCurve.Type.OutCubic)

    def dismiss(self) -> None:
        """Fades the card out and closes it."""
        if self._closing:
            return
        self._closing = True
        self._dismiss_timer.stop()
        self.dismissed.emit(self)
        self._run_animation(self.pos() + QPoint(0, _SLIDE_PX), 0.0, _HIDE_MS, QEasingCurve.Type.InCubic)
        if self._anim is not None:
            self._anim.finished.connect(self.close)
        else:
            self.close()

    def enterEvent(self, event) -> None:  # noqa: N802 — Qt override
        """Pauses auto-dismiss while the pointer is over the card."""
        self._dismiss_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 — Qt override
        """Restarts auto-dismiss when the pointer leaves the card (not while rendering)."""
        if not self._closing and self._render is None:
            self._dismiss_timer.start()
        super().leaveEvent(event)

    def _on_open_clicked(self) -> None:
        """Open opens the player; after a render it reveals the file instead."""
        if self._output_file:
            from steempeg.infra.paths import reveal_in_file_manager

            reveal_in_file_manager(self._output_file)
            self.dismiss()
            return
        self._emit_and_close(self.open_requested)

    def _on_express_clicked(self) -> None:
        """Starts Express, cancels a running one, or copies the finished file."""
        if self._output_file:
            from steempeg.ui.express_player import copy_file_to_clipboard

            copy_file_to_clipboard(self._output_file)
            self._status_label.setText("📎 Copied to clipboard")
            self._dismiss_timer.start()
            return
        if self._render is not None:
            self._render.cancel()
            return
        self.express_requested.emit(self._info.path)

    def track_render(self, render) -> None:
        """Turns the card into a progress card for an Express render of this clip."""
        if render is None:
            self._status_label.setText("Could not start the render")
            return
        self._render = render
        self._dismiss_timer.stop()
        self._express_btn.setToolTip("Click to cancel")
        render.progress_changed.connect(self._on_render_progress)
        render.finished.connect(self._on_render_finished)
        self._status_label.setText(f"Rendering · {render.recipe_label}")
        self._on_render_progress(0.0)

    def _on_render_progress(self, percent: float) -> None:
        """Fills the Express button like a progress bar."""
        from steempeg.ui.express_player import build_express_progress_qss

        self._express_btn.setText(f"{int(percent)}%")
        qss = build_express_progress_qss(percent).replace("QPushButton#ExpressMain", "QPushButton#AccentBtn")
        self._express_btn.setStyleSheet(qss)

    def _on_render_finished(self, success: bool, error: str, output_file: str) -> None:
        """Shows the result: Show in folder + Copy, or the failure."""
        self._render = None
        self._express_btn.setStyleSheet("")
        if success and output_file:
            self._output_file = output_file
            self._status_label.setText("✓ Rendered")
            self._open_btn.setText("📂 Show")
            self._express_btn.setText("📎 Copy")
            self._express_btn.setToolTip("Copy the video file (paste into Discord / Telegram)")
        else:
            cancelled = "cancel" in (error or "").lower()
            self._status_label.setText("Render cancelled" if cancelled else "Render failed")
            self._express_btn.setText("⚡ Express")
        if not self.underMouse():
            self._dismiss_timer.start()

    def _emit_and_close(self, signal) -> None:
        """Sends the clip path through ``signal`` and dismisses the card."""
        if self._closing:
            return
        signal.emit(self._info.path)
        self.dismiss()

    def _run_animation(self, target: QPoint, opacity: float, ms: int, curve) -> None:
        """Animates position and window opacity together."""
        if self._anim is not None:
            self._anim.stop()
        group = QParallelAnimationGroup(self)
        move = QPropertyAnimation(self, b"pos", group)
        move.setDuration(ms)
        move.setEndValue(target)
        move.setEasingCurve(curve)
        fade = QPropertyAnimation(self, b"windowOpacity", group)
        fade.setDuration(ms)
        fade.setEndValue(opacity)
        fade.setEasingCurve(curve)
        group.addAnimation(move)
        group.addAnimation(fade)
        group.start()
        self._anim = group


class NewClipPopupStack:
    """Keeps «New clip» cards stacked in the bottom-right corner."""

    def __init__(self, on_open, on_express):
        """Remembers what to call when a card's Open / Express is pressed."""
        self._on_open = on_open
        self._on_express = on_express
        self._popups: list[NewClipPopup] = []

    def show_clip(self, info: NewClipInfo) -> None:
        """Adds a card for the clip at the bottom of the stack."""
        for popup in self._popups:
            if popup.clip_path == info.path:
                return
        popup = NewClipPopup(info)
        popup.open_requested.connect(self._on_open)
        popup.express_requested.connect(
            lambda path, p=popup: p.track_render(self._on_express(path))
        )
        popup.dismissed.connect(self._remove_popup)
        self._popups.insert(0, popup)
        targets = self._slot_positions()
        for index, existing in enumerate(self._popups[1:], start=1):
            existing.move_to(targets[index])
        popup.present(targets[0])

    def _remove_popup(self, popup: NewClipPopup) -> None:
        """Drops a closing card and slides the cards above it down."""
        if popup in self._popups:
            self._popups.remove(popup)
        targets = self._slot_positions()
        for index, existing in enumerate(self._popups):
            existing.move_to(targets[index])

    def _slot_positions(self) -> list[QPoint]:
        """Computes top-left positions for every card, bottom card first."""
        screen = QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else None
        right = area.right() if area is not None else 1920
        bottom = area.bottom() if area is not None else 1080
        positions: list[QPoint] = []
        y = bottom - _SCREEN_MARGIN
        for popup in self._popups:
            y -= popup.height()
            positions.append(QPoint(right - _SCREEN_MARGIN - popup.width(), y))
            y -= _STACK_GAP
        return positions
