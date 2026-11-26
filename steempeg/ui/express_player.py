"""Express player — Steam-like mini player for one fresh clip.

The window is the player: a near-invisible top strip (Steempeg logo left,
traffic lights right) is the only drag area. Below sit the game title,
the video, the regular Steempeg timeline with trim, and the action row:
Delete (to Recycle Bin), Trim, and the Express split button.

Has its own libmpv handle so it never touches the main editor's player.
"""
from __future__ import annotations

import logging
import os
import sys
import time

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QCursor, QGuiApplication, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.core.rendered_media import is_sane_media_duration
from steempeg.infra.paths import get_resource_path
from steempeg.ui.icon_assets import tinted_pixmap
from steempeg.ui.player.mpv_osd import MpvPlayPausePulse
from steempeg.ui.player.surface_input import VideoSurfaceInput
from steempeg.ui.pro_appearance import set_accent_stylesheet, themed_asset_path
from steempeg.services.new_clip_watcher import NewClipInfo
from steempeg.ui import design_tokens as tok
from steempeg.ui import ui_theme as ut
from steempeg.ui.widgets import ElidedLabel

_TOP_STRIP_H = 30
_SKIP_MS = 15000
_POLL_MS = 50
_DEFAULT_SIZE = QSize(1040, 720)
_MIN_SIZE = QSize(720, 480)
_SCREEN_WIDTH_SHARE = 0.62
_SCREEN_HEIGHT_CAP = 0.88


def format_player_time(ms: float) -> str:
    """Formats milliseconds as m:ss (or h:mm:ss) for the time label."""
    total = max(0, int(ms // 1000))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def build_express_player_qss() -> str:
    """Builds the window stylesheet from the active theme tokens."""
    from steempeg.ui.ui_density import COMFORT

    palette = ut.active_palette()
    c = ut._frameless_card_dialog_colors()
    return f"""
    QWidget#ExpressPlayer {{ background-color: {palette.bg_shell}; }}
    QFrame#ExpressHeader {{
        background-color: {palette.bg_player_header};
        border: none;
        border-top-left-radius: 10px;
        border-top-right-radius: 10px;
    }}
    QFrame#ExpressVideo {{ background-color: #000000; border: none; }}
    QFrame#ExpressFooter {{
        background-color: {palette.bg_player_footer};
        border: none;
        border-bottom-left-radius: 10px;
        border-bottom-right-radius: 10px;
    }}
    QLabel#ExpressTitle {{
        color: white; font-family: {tok.FONT_APP}; font-size: {COMFORT.header_font}px;
        font-weight: 700; background: transparent;
    }}
    QLabel#ExpressTime {{
        color: #cccccc; font-family: {tok.FONT_APP}; font-size: 13px; font-weight: bold;
        background: transparent;
    }}
    QPushButton#ExpressFlat {{
        color: #cfcfcf; background: transparent; border: none; border-radius: 8px;
        font-family: {tok.FONT_APP}; font-size: 13px; font-weight: bold; padding: 4px 10px;
    }}
    QPushButton#ExpressFlat:hover {{ color: #ffffff; background: rgba(255, 255, 255, 22); }}
    QPushButton#ExpressIconBtn {{
        background: transparent; border: none; border-radius: 20px; padding: 0;
    }}
    QPushButton#ExpressIconBtn:hover {{ background: rgba(255, 255, 255, 30); }}
    QPushButton#ExpressPill {{
        background-color: {c["btn_bg"]}; color: white; border: 1px solid {c["btn_border"]};
        border-radius: 15px; padding: 0 14px; min-height: 30px;
        font-family: {tok.FONT_APP}; font-size: 12px; font-weight: bold;
    }}
    QPushButton#ExpressPill:hover {{
        background-color: {c["btn_hover_bg"]}; border: 1px solid {c["btn_hover_border"]};
    }}
    QPushButton#ExpressPill:pressed {{ background-color: {c["btn_pressed_bg"]}; }}
    QPushButton#ExpressMain, QPushButton#ExpressArrow {{
        background-color: {c["accent_bg"]}; color: {c["accent_fg"]};
        border: 1px solid {c["accent_border"]}; min-height: 30px; font-weight: bold;
    }}
    QPushButton#ExpressMain {{
        border-top-left-radius: 15px; border-bottom-left-radius: 15px;
        border-top-right-radius: 0; border-bottom-right-radius: 0;
        border-right: none; padding: 0 14px 0 16px;
    }}
    QPushButton#ExpressArrow {{
        border-top-right-radius: 15px; border-bottom-right-radius: 15px;
        border-top-left-radius: 0; border-bottom-left-radius: 0;
        padding: 0 10px 0 8px;
    }}
    QPushButton#ExpressMain:hover, QPushButton#ExpressArrow:hover {{
        background-color: {c["accent_hover_bg"]}; border-color: {c["title"]};
    }}
    QPushButton#ExpressMain:pressed, QPushButton#ExpressArrow:pressed {{
        background-color: {c["accent_pressed_bg"]};
    }}
    QFrame#ExpressResult {{
        background-color: {c["card_bg"]}; border: 1px solid {c["card_border"]};
        border-radius: 10px;
    }}
    QLabel#ExpressResultText {{
        color: {tok.TEXT_TITLE}; font-family: {tok.FONT_APP}; font-size: 13px; font-weight: bold;
        background: transparent; border: none;
    }}
    """


def build_express_progress_qss(percent: float) -> str:
    """Paints the Express button as a progress bar filled up to ``percent``."""
    c = ut._frameless_card_dialog_colors()
    stop = max(0.001, min(0.999, percent / 100.0))
    return (
        "QPushButton#ExpressMain { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
        f" stop:0 {c['accent_hover_bg']}, stop:{stop:.3f} {c['accent_hover_bg']},"
        f" stop:{stop + 0.001:.3f} {c['btn_pressed_bg']}, stop:1 {c['btn_pressed_bg']}); }}"
    )


def copy_file_to_clipboard(path: str) -> None:
    """Puts the file itself on the clipboard so it pastes into Discord / Telegram / Explorer."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(os.path.abspath(path))])
    QGuiApplication.clipboard().setMimeData(mime)


class _TopStrip(QWidget):
    """Near-invisible top strip: logo left, traffic lights right, drags the window."""

    def __init__(self, window: QWidget):
        """Builds the strip for ``window`` (move / minimize / maximize / close)."""
        super().__init__(window)
        from steempeg.ui.icon_utils import apply_square_icon
        from steempeg.ui.window_chrome import (
            _LinuxEdgeResizeFilter,
            _TrafficLight,
            _linux_prefer_manual_resize,
            app_logo_pixmap,
        )

        self._window = window
        self._linux_drag = None
        if sys.platform.startswith("linux") and _linux_prefer_manual_resize():
            self._linux_drag = _LinuxEdgeResizeFilter(window)
        self.setFixedHeight(_TOP_STRIP_H)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 14, 0)
        lay.setSpacing(0)
        logo = QLabel()
        logo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        apply_square_icon(logo, app_logo_pixmap(16), 16)
        logo.setStyleSheet("background: transparent;")
        lay.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addStretch(1)
        lights = QHBoxLayout()
        lights.setSpacing(12)
        self.btn_minimize = _TrafficLight(tok.TRAFFIC_MINIMIZE, tok.TRAFFIC_MINIMIZE_HOVER, "minimize")
        self.btn_maximize = _TrafficLight(tok.TRAFFIC_MAXIMIZE, tok.TRAFFIC_MAXIMIZE_HOVER, "maximize")
        self.btn_close = _TrafficLight(tok.TRAFFIC_CLOSE, tok.TRAFFIC_CLOSE_HOVER, "close")
        for btn in (self.btn_minimize, self.btn_maximize, self.btn_close):
            lights.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(lights)
        self.btn_minimize.clicked.connect(window.showMinimized)
        self.btn_maximize.clicked.connect(self.toggle_maximized)
        self.btn_close.clicked.connect(window.close)

    def toggle_maximized(self) -> None:
        """Maximizes the window or restores it."""
        if self._linux_drag is not None:
            from steempeg.ui.window_chrome import win32_window_command

            win32_window_command(self._window, "maximize_toggle")
        elif self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def mousePressEvent(self, event) -> None:  # noqa: N802 — Qt override
        """Moves the Express window when its title strip is dragged."""
        if event.button() == Qt.MouseButton.LeftButton:
            if self._linux_drag is not None:
                self._linux_drag.begin_title_drag(event.globalPosition().toPoint())
            else:
                handle = self._window.windowHandle()
                if handle is not None:
                    handle.startSystemMove()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 — Qt override
        """Double-click on the strip toggles maximize, like a normal title bar."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class ExpressScreenshotPreview(QWidget):
    """One Steam screenshot, nothing else. Not the Screenshots manager."""

    def __init__(self, host: QWidget):
        super().__init__(
            host,
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint,
        )
        self.setObjectName("ExpressShotPreview")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        palette = ut.active_palette()
        self.setStyleSheet(
            "QWidget#ExpressShotPreview {"
            f" background-color: {palette.bg_shell};"
            " border: 1px solid rgba(255, 255, 255, 0.12);"
            " border-radius: 10px;"
            "}"
            "QLabel { color: white; background: transparent; }"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(8)
        header = QHBoxLayout()
        title = QLabel("Screenshot")
        title.setObjectName("ExpressShotTitle")
        header.addWidget(title, 1)
        close = QPushButton("✕")
        close.setObjectName("ExpressFlat")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.hide)
        header.addWidget(close)
        lay.addLayout(header)
        self._image = QLabel("No screenshot for this mark.")
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setMinimumSize(320, 180)
        lay.addWidget(self._image)
        self.hide()

    def show_file(self, path: str | None) -> None:
        """Shows ``path``, or a short note when that shot is not on disk."""
        pix = QPixmap(path) if path and os.path.isfile(path) else QPixmap()
        if pix.isNull():
            self._image.setPixmap(QPixmap())
            self._image.setText("No screenshot for this mark.")
        else:
            self._image.setText("")
            self._image.setPixmap(
                pix.scaled(
                    720,
                    405,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self.adjustSize()
        host = self.parentWidget()
        if host is not None:
            frame = host.frameGeometry()
            self.move(frame.center() - self.rect().center())
        self.show()
        self.raise_()


class ExpressPlayerWindow(VideoSurfaceInput, QWidget):
    """Mini player window for one clip with Express export."""

    def __init__(self, app, info: NewClipInfo):
        """Builds the window for ``info``; call ``open_clip()`` after ``show()``."""
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self._app = app
        self._info = info
        self._player = None
        self._duration_ms = 0
        self._replay_deadline: float | None = None
        self._eof_drag_target: int | None = None
        self._was_playing_before_drag = False
        self._render = None
        self._last_output = ""
        self._marks_gen = 0
        self._marks_worker = None
        self._shot_preview = None
        self._health_report = None
        self._preview_quality_id = "source"
        self.setObjectName("ExpressPlayer")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(f"{info.game_name} — Steempeg Express")
        self.setMinimumSize(_MIN_SIZE)
        self.resize(_DEFAULT_SIZE)
        self.setStyleSheet(build_express_player_qss())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._top_strip = _TopStrip(self)
        # Edge-resize grips only show while the window has a visible ``title_bar``.
        self.title_bar = self._top_strip
        root.addWidget(self._top_strip)

        body = QVBoxLayout()
        body.setContentsMargins(12, 0, 12, 12)
        body.setSpacing(0)
        root.addLayout(body, 1)

        body.addWidget(self._build_header())
        body.addWidget(self._build_video(), 1)
        self._play_pause_pulse = MpvPlayPausePulse(lambda: self._player, self.mpv_screen)
        body.addWidget(self._build_footer())
        self.install_video_surface_click_handler()

        self._poll = QTimer(self)
        self._poll.setInterval(_POLL_MS)
        self._poll.timeout.connect(self._sync_from_player)

        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.toggle_play)
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, activated=lambda: self.skip_by(-_SKIP_MS))
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, activated=lambda: self.skip_by(_SKIP_MS))
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._on_escape)
        QShortcut(QKeySequence(Qt.Key.Key_F), self, activated=self.toggle_fullscreen)

        if sys.platform == "win32":
            try:
                from steempeg.ui.window_chrome import enable_windows_edge_resize

                enable_windows_edge_resize(self)
            except Exception:
                logging.debug("Express player: edge resize unavailable", exc_info=True)

        self.fit_to_screen()
        QTimer.singleShot(0, self, self._refresh_clip_health)

    def fit_to_screen(self) -> None:
        """Sizes the window to a share of the screen under the cursor so 16:9 video fills it, then centres it."""
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(_DEFAULT_SIZE)
            return
        area = screen.availableGeometry()
        side_margins = 24
        chrome_h = (
            self._top_strip.sizeHint().height()
            + self._header.sizeHint().height()
            + self._footer.sizeHint().height()
            + 12
        )
        width = int(area.width() * _SCREEN_WIDTH_SHARE)
        height = int((width - side_margins) * 9 / 16) + chrome_h
        max_height = int(area.height() * _SCREEN_HEIGHT_CAP)
        if height > max_height:
            height = max_height
            width = int((height - chrome_h) * 16 / 9) + side_margins
        width = max(_MIN_SIZE.width(), min(width, area.width()))
        height = max(_MIN_SIZE.height(), min(height, area.height()))
        self.resize(width, height)
        self.move(
            area.x() + (area.width() - width) // 2,
            area.y() + (area.height() - height) // 2,
        )

    @property
    def clip_path(self) -> str:
        """Returns the clip folder shown in this player."""
        return self._info.path

    def apply_ui_theme_chrome(self) -> None:
        """Repaints the window when the user switches theme (Default / TrueDark / OLED)."""
        self.setStyleSheet(build_express_player_qss())
        from steempeg.ui.player_zoom_chrome import sync_preview_zoom_chrome

        sync_preview_zoom_chrome(self)
        if self._health_report is not None:
            self._paint_clip_health(self._health_report)
        if hasattr(self._timeline, "_apply_timeline_chrome_stylesheet"):
            self._timeline._apply_timeline_chrome_stylesheet()
        self._timeline.canvas.update()

    def refresh_playback_artwork(self) -> None:
        self._btn_skip_back.setIcon(QIcon(themed_asset_path("less15.png")))
        self._btn_skip_forward.setIcon(QIcon(themed_asset_path("more15.png")))
        glyph = self._btn_play.property("glyph") or "icon_play.png"
        self._btn_play.setIcon(QIcon(themed_asset_path(glyph)))

    # -- layout ---------------------------------------------------------------

    def _build_header(self) -> QFrame:
        """Preview controls flank the game identity, using the desktop header metrics."""
        from steempeg.ui.icon_assets import preview_settings_icon
        from steempeg.ui.icon_utils import apply_square_icon
        from steempeg.ui.layout_defaults import (
            PLAYER_HEADER_CANVAS_GAP,
            PLAYER_HEADER_FRAME_BORDER_V,
        )
        from steempeg.ui.new_clip_popup import build_game_icon_pixmap
        from steempeg.ui.player_header_layout import player_header_title_qfont
        from steempeg.ui.player_zoom_chrome import install_player_zoom_chrome, sync_preview_zoom_chrome
        from steempeg.ui.ui_density import COMFORT

        header = QFrame()
        header.setObjectName("ExpressHeader")
        header.setFixedHeight(
            max(
                int(COMFORT.header_chip) + 2 * int(COMFORT.header_pad_v),
                int(COMFORT.header_min_h),
                int(COMFORT.header_icon) + 2 * int(COMFORT.header_pad_v),
            )
            + PLAYER_HEADER_CANVAS_GAP
            + int(PLAYER_HEADER_FRAME_BORDER_V)
        )
        lay = QGridLayout(header)
        lay.setContentsMargins(int(COMFORT.header_pad_h), 0, int(COMFORT.header_pad_h), 0)
        lay.setColumnStretch(0, 1)
        lay.setColumnStretch(2, 1)
        zoom = install_player_zoom_chrome(self)
        sync_preview_zoom_chrome(self)
        lay.addWidget(zoom, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        identity = QWidget()
        identity_row = QHBoxLayout(identity)
        identity_row.setContentsMargins(0, 0, 0, 0)
        identity_row.setSpacing(8)
        icon_px = int(COMFORT.header_icon)
        icon = QLabel()
        icon.setStyleSheet("background: transparent;")
        apply_square_icon(icon, build_game_icon_pixmap(self._info.icon_path, icon_px), icon_px)
        identity_row.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
        title = QLabel(self._info.game_name)
        title.setObjectName("ExpressTitle")
        title.setFont(player_header_title_qfont(int(COMFORT.header_font)))
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setText(title.fontMetrics().elidedText(self._info.game_name, Qt.TextElideMode.ElideRight, 300))
        title.setToolTip(self._info.game_name)
        identity_row.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(identity, 0, 1, Qt.AlignmentFlag.AlignCenter)

        right = QWidget()
        actions = QHBoxLayout(right)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self._health_button = QPushButton("Checking…")
        self._health_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._health_button.clicked.connect(self._show_clip_health)
        actions.addWidget(self._health_button)
        divider = QFrame()
        divider.setFixedSize(1, 16)
        divider.setStyleSheet("background: rgba(255, 255, 255, 55); border: none;")
        actions.addWidget(divider, 0, Qt.AlignmentFlag.AlignVCenter)
        gear = QPushButton()
        chip = int(COMFORT.header_chip)
        glyph = int(COMFORT.header_chip_icon)
        gear.setFixedSize(chip, chip)
        gear.setIcon(preview_settings_icon(glyph))
        gear.setIconSize(QSize(glyph, glyph))
        gear.setToolTip("Preview quality · Does not affect export")
        gear.setAccessibleName("Preview quality")
        gear.setCursor(Qt.CursorShape.PointingHandCursor)
        gear.setStyleSheet(
            "QPushButton { background: rgba(74, 159, 216, 46); border: 2px solid #4a9fd8;"
            " border-radius: 7px; padding: 0; }"
            "QPushButton:hover { background: rgba(74, 159, 216, 82); }"
        )
        gear.clicked.connect(self._show_preview_quality_menu)
        self.btn_preview_settings = gear
        actions.addWidget(gear)
        lay.addWidget(right, 0, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._header = header
        return header

    def _refresh_clip_health(self) -> None:
        from steempeg.ui.express_render import express_clip_health

        self._health_report = express_clip_health(self._app, self._info.path)
        self._paint_clip_health(self._health_report)
        self._refresh_express_tooltip()

    def _paint_clip_health(self, report) -> None:
        from steempeg.ui.player.clip_health_chrome import apply_clip_health_button

        apply_clip_health_button(self._health_button, report)

    def _show_clip_health(self) -> None:
        from steempeg.ui.player.clip_health_chrome import build_clip_health_menu

        report = self._health_report
        if report is not None:
            button = self._health_button
            menu = build_clip_health_menu(self, report)
            menu.exec(button.mapToGlobal(QPoint(0, button.height())))
            menu.deleteLater()

    def _show_preview_quality_menu(self) -> None:
        from steempeg.ui.player import preview_quality as pq

        menu = QMenu(self)
        ut.set_stylesheet_if_changed(menu, pq.menu_stylesheet())
        menu.addAction("Preview quality").setEnabled(False)
        group = QActionGroup(menu)
        for preset in pq.PRESETS:
            action = menu.addAction(preset.label)
            group.addAction(action)
            action.setCheckable(True)
            action.setChecked(preset.id == self._preview_quality_id)
            action.setData(preset.id)
        def apply_choice(action):
            preset_id = action.data()
            QTimer.singleShot(0, self, lambda: self._set_preview_quality(preset_id))

        group.triggered.connect(apply_choice)
        menu.addSeparator()
        menu.addAction("Does not affect export").setEnabled(False)
        gear = self.btn_preview_settings
        menu.exec(gear.mapToGlobal(gear.rect().bottomLeft()))
        menu.deleteLater()

    def _set_preview_quality(self, preset_id: str) -> None:
        from steempeg.ui.player import preview_quality as pq

        if self._player is None:
            return
        height = pq.decoded_source_height(self._player)
        if preset_id != "source" and not height:
            return
        if pq.apply_mpv_preview_quality(self._player, preset_id, source_height=height):
            self._preview_quality_id = preset_id
        else:
            self._preview_quality_id = "source"
        label = next(preset.label for preset in pq.PRESETS if preset.id == self._preview_quality_id)
        self.btn_preview_settings.setToolTip(f"Preview quality · {label} · Does not affect export")

    def _build_video(self) -> QFrame:
        """Black frame holding the mpv surface."""
        from steempeg.ui.player.surface import MPVWrapper

        frame = QFrame()
        frame.setObjectName("ExpressVideo")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        self._mpv_wrapper = MPVWrapper(frame)
        self._mpv_wrapper.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay.addWidget(self._mpv_wrapper)
        self._video_frame = frame
        return frame

    @property
    def player(self):
        return self._player

    @property
    def mpv_screen(self):
        return self._mpv_wrapper.mpv_screen

    def _on_video_surface_click(self) -> None:
        if (
            self.isVisible()
            and QApplication.activePopupWidget() is None
            and QApplication.activeModalWidget() is None
        ):
            self.toggle_play(pulse=True)

    def _build_footer(self) -> QFrame:
        """Timeline, result strip and the controls row."""
        from steempeg.ui.player.controls.audio import VolumeControlWidget
        from steempeg.ui.player.controls.center_pinned_row import CenterPinnedRow
        from steempeg.ui.player.controls.timeline import CustomTimelineWidget

        footer = QFrame()
        footer.setObjectName("ExpressFooter")
        lay = QVBoxLayout(footer)
        lay.setContentsMargins(15, 10, 15, 12)
        lay.setSpacing(6)

        self._timeline = CustomTimelineWidget()
        self._timeline.canvas.light_screenshot_marks = True
        self._timeline.screenshot_preview_requested.connect(self._show_screenshot_preview)
        self._timeline.pause_requested.connect(self._on_timeline_press)
        self._timeline.seek_requested.connect(self._on_timeline_seek)
        self._timeline.resume_requested.connect(self._on_timeline_release)
        lay.addWidget(self._timeline)

        lay.addWidget(self._build_result_strip())

        left = QWidget()
        left_lay = QHBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(6)
        self._volume = VolumeControlWidget(footer)
        self._volume.slider.valueChanged.connect(self._on_volume_changed)
        left_lay.addWidget(self._volume, 0, Qt.AlignmentFlag.AlignVCenter)
        self._btn_fullscreen = self._make_icon_button("btn_fullscreen.png", 22, "Fullscreen (F)")
        self._btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        left_lay.addWidget(self._btn_fullscreen, 0, Qt.AlignmentFlag.AlignVCenter)
        left_lay.addStretch(1)

        center = QWidget()
        center_lay = QVBoxLayout(center)
        center_lay.setContentsMargins(0, 0, 0, 0)
        center_lay.setSpacing(0)
        transport = QHBoxLayout()
        transport.setSpacing(6)
        self._btn_skip_back = self._make_icon_button("less15.png", 28, "Back 15 s (←)")
        self._btn_skip_back.clicked.connect(lambda: self.skip_by(-_SKIP_MS))
        self._btn_play = self._make_icon_button("icon_play.png", 40, "Play / Pause (Space)", box=48)
        self._btn_play.clicked.connect(self.toggle_play)
        self._btn_skip_forward = self._make_icon_button("more15.png", 28, "Forward 15 s (→)")
        self._btn_skip_forward.clicked.connect(lambda: self.skip_by(_SKIP_MS))
        transport.addStretch(1)
        transport.addWidget(self._btn_skip_back)
        transport.addWidget(self._btn_play)
        transport.addWidget(self._btn_skip_forward)
        transport.addStretch(1)
        center_lay.addLayout(transport)
        center_lay.addSpacing(4)
        self._time_label = QLabel("0:00 / 0:00")
        self._time_label.setObjectName("ExpressTime")
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_lay.addWidget(self._time_label)
        center.setFixedWidth(220)

        right = QWidget()
        right_lay = QHBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(8)
        right_lay.addStretch(1)
        btn_delete = QPushButton("🗑")
        btn_delete.setObjectName("ExpressPill")
        btn_delete.setToolTip("Move this clip to the Recycle Bin")
        btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_delete.clicked.connect(self.delete_clip)
        right_lay.addWidget(btn_delete)
        self._btn_trim = QPushButton(" Trim")
        self._btn_trim.setIcon(QIcon(get_resource_path("trim_icon.png")))
        self._btn_trim.setFixedHeight(30)
        self._btn_trim.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_trim.setToolTip("Pick the part to export")
        self._btn_trim.setStyleSheet(tok.STYLE_TRIM_BUTTON)
        self._btn_trim.clicked.connect(self.toggle_trim)
        right_lay.addWidget(self._btn_trim)
        split = QHBoxLayout()
        split.setSpacing(0)
        self._btn_express = QPushButton("⚡ Express")
        self._btn_express.setObjectName("ExpressMain")
        self._btn_express.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_express.clicked.connect(self._on_express_clicked)
        self._btn_arrow = QPushButton("▾")
        self._btn_arrow.setObjectName("ExpressArrow")
        self._btn_arrow.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_arrow.setToolTip("More export options")
        self._btn_arrow.clicked.connect(self._show_export_menu)
        split.addWidget(self._btn_express)
        split.addWidget(self._btn_arrow)
        right_lay.addLayout(split)
        self._refresh_express_tooltip()

        row = CenterPinnedRow(left, center, right, footer)
        row.setMinimumHeight(70)
        lay.addWidget(row)
        self._footer = footer
        return footer

    def _build_result_strip(self) -> QFrame:
        """Hidden strip that appears after an Express render finishes."""
        strip = QFrame()
        strip.setObjectName("ExpressResult")
        lay = QHBoxLayout(strip)
        lay.setContentsMargins(12, 6, 8, 6)
        lay.setSpacing(8)
        self._result_check = QLabel()
        self._result_check.setFixedSize(16, 16)
        self._result_check.setPixmap(tinted_pixmap("success.png", "#94dc83", 16))
        self._result_check.hide()
        lay.addWidget(self._result_check, 0, Qt.AlignmentFlag.AlignVCenter)
        self._result_text = ElidedLabel("")
        self._result_text.setObjectName("ExpressResultText")
        self._result_text.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(self._result_text, 1)
        self._btn_show_folder = QPushButton("Show in folder")
        self._btn_copy = QPushButton("Copy")
        self._btn_open_queue = QPushButton("Open in Steempeg")
        self._btn_open_queue.setToolTip("Show Render Queue in the main Steempeg window")
        for btn in (self._btn_show_folder, self._btn_copy, self._btn_open_queue):
            set_accent_stylesheet(
                btn,
                ut.dash_secondary_button_stylesheet(radius=16, pad="4px 12px")
                + "QPushButton:focus:enabled { border-color: #b29ae7; }",
            )
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            lay.addWidget(btn)
        self._btn_show_folder.clicked.connect(self.show_last_output_in_folder)
        self._btn_copy.clicked.connect(self.copy_last_output)
        self._btn_open_queue.clicked.connect(self._app.open_render_queue_from_express)
        self._btn_open_queue.hide()
        close = QPushButton("✕")
        close.setObjectName("ExpressFlat")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(strip.hide)
        lay.addWidget(close)
        strip.hide()
        self._result_strip = strip
        return strip

    def _set_result_message(self, text: str, *, confirmed: bool = False) -> None:
        self._result_text.setText(text)
        self._result_text.setToolTip(text)
        self._result_check.setVisible(confirmed)
        self._btn_open_queue.hide()

    def _make_icon_button(self, asset: str, icon_px: int, tip: str, *, box: int = 40) -> QPushButton:
        """Round transparent button with a bundled icon."""
        btn = QPushButton()
        btn.setObjectName("ExpressIconBtn")
        btn.setFixedSize(box, box)
        btn.setIcon(QIcon(themed_asset_path(asset)))
        btn.setIconSize(QSize(icon_px, icon_px))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setToolTip(tip)
        return btn

    # -- playback -------------------------------------------------------------

    def open_clip(self) -> None:
        """Creates the mpv handle on the video surface and starts playing the clip."""
        from steempeg.core.dash.discovery import find_mpd_paths
        from steempeg.core.dash.mpd import parse_duration_seconds

        mpds = find_mpd_paths(self._info.path)
        if not mpds:
            self._time_label.setText("No playable video")
            return
        try:
            self._player = self._create_player()
        except Exception:
            logging.exception("Express player: mpv init failed")
            self._time_label.setText("Video engine failed")
            return
        self._install_linux_mpv_pointer_bindings()
        play_path = os.path.abspath(mpds[0]).replace("\\", "/")
        self._duration_ms = 0
        try:
            with open(play_path, encoding="utf-8") as manifest:
                duration = parse_duration_seconds(manifest.read())
            if is_sane_media_duration(duration):
                self._duration_ms = round(duration * 1000)
        except (OSError, ValueError):
            logging.debug("Express player: could not read DASH duration", exc_info=True)
        self._timeline.set_duration(self._duration_ms)
        logging.info("Express player: play %s", play_path)
        self._attach_hover_preview(play_path)
        self._prefetch_marker_sprite()
        self._load_timeline_marks(play_path)
        self._replay_deadline = None
        self._player.play(play_path)
        self._player.pause = False
        self._poll.start()

    def _attach_hover_preview(self, play_path: str) -> None:
        """Points the timeline's PyAV hover preview at this clip and the app's frame cache."""
        cache_dir = getattr(self._app, "cache_dir", None)
        if cache_dir:
            self._timeline.canvas._markers_cache_dir = cache_dir
            self._timeline.canvas.sniper.cache_dir = cache_dir
            store = getattr(self._timeline.canvas, "marker_store", None)
            if store is not None and getattr(store, "_cache_dir", None) != cache_dir:
                store.set_cache_dir(cache_dir)
        self._timeline.sniper_source_path = play_path
        self._timeline.current_video_path = play_path

    def _prefetch_marker_sprite(self) -> None:
        """Start the same markers.svg fetch the main player does before pins paint."""
        from steempeg.services.steam_markers import app_id_from_clip_paths

        canvas = self._timeline.canvas
        store = getattr(canvas, "marker_store", None)
        if store is None:
            return
        app_id = app_id_from_clip_paths(clip_path=self._info.path)
        if not app_id:
            return
        store.prefetch(app_id, on_ready=canvas.update)

    def _load_timeline_marks(self, mpd_path: str) -> None:
        """Loads this clip's timeline pins onto the Express timeline, off the UI thread."""
        from steempeg.ui.player.timeline_markers_worker import TimelineMarkersLoadWorker

        self._stop_timeline_marks()
        self._marks_gen += 1
        generation = self._marks_gen
        worker = TimelineMarkersLoadWorker(
            self._info.path,
            mpd_path,
            getattr(self._app, "cache_dir", None),
            None,
        )
        self._marks_worker = worker

        def _on_done(result: object, gen: int = generation) -> None:
            if gen != self._marks_gen:
                return
            try:
                self._apply_timeline_marks(result)
            except RuntimeError:
                return

        worker.finished_load.connect(_on_done)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _stop_timeline_marks(self) -> None:
        """Drops a timeline-pin load that is still running for the previous clip."""
        self._marks_gen += 1
        worker = getattr(self, "_marks_worker", None)
        self._marks_worker = None
        if worker is None:
            return
        try:
            worker.requestInterruption()
            worker.finished_load.disconnect()
        except (RuntimeError, TypeError):
            pass

    def _apply_timeline_marks(self, result: object) -> None:
        """Paints every pin: game events, screenshots and recording errors."""
        if not isinstance(result, dict):
            return
        markers = [
            marker
            for marker in (result.get("markers") or [])
            if isinstance(marker, dict)
        ]
        logging.info(
            "Express markers: %d pin(s) from %s",
            len(markers),
            result.get("json_path") or "(no timeline json)",
        )
        canvas = self._timeline.canvas
        canvas.light_screenshot_marks = True
        canvas.apply_preparsed_timeline(
            json_path=result.get("json_path"),
            offset_ms=int(result.get("offset_ms") or 0),
            clip_path=self._info.path,
            cache_dir=getattr(self._app, "cache_dir", None),
            markers=markers,
            mode_segments=list(result.get("mode_segments") or []),
            clip_ranges=list(result.get("clip_ranges") or []),
            remembered_ids=list(result.get("remembered_ids") or []),
            json_start_utc=result.get("json_start_utc"),
            app_id=result.get("app_id"),
            reveal=True,
        )

    def _show_screenshot_preview(self, marker: object) -> None:
        """Opens the one Steam shot that belongs to this timeline pin."""
        if not isinstance(marker, dict):
            return
        if self._shot_preview is None:
            self._shot_preview = ExpressScreenshotPreview(self)
        self._shot_preview.show_file(self._screenshot_path_for_marker(marker))

    def _screenshot_path_for_marker(self, marker: dict) -> str | None:
        """Finds the Steam file for a screenshot pin, or None when it is missing."""
        from steempeg.core.steam_screenshots import (
            find_steam_screenshot_files,
            resolve_steam_id_for_clip,
            timeline_json_start_utc,
        )

        canvas = self._timeline.canvas
        clip_path = getattr(canvas, "current_clip_path", None) or self._info.path
        app_id = getattr(canvas, "current_app_id", None)
        if not clip_path or not app_id:
            return None
        folders = getattr(self._app, "clips_folders", None) or []
        steam_id = resolve_steam_id_for_clip(clip_path, folders)
        if not steam_id:
            return None
        marker_ms = float(marker.get("time_ms", 0) or 0)
        raw_time_ms = marker.get("raw_time_ms")
        if raw_time_ms is None:
            raw_time_ms = marker_ms + float(getattr(canvas, "current_offset_ms", 0) or 0)
        json_start = getattr(canvas, "current_json_start_utc", None)
        if json_start is None:
            json_start = timeline_json_start_utc(getattr(canvas, "current_json_path", None))
        files = find_steam_screenshot_files(
            steam_id=steam_id,
            app_id=str(app_id),
            json_start_utc=json_start,
            raw_time_ms=float(raw_time_ms),
            clip_path=clip_path,
            marker_time_ms=marker_ms,
        )
        if not files:
            return None
        return files[0]

    def _create_player(self):
        """Builds a libmpv instance embedded in this window's video surface."""
        import mpv

        from steempeg.ui.settings_prefs import current_hwdec_preview

        if hasattr(self._mpv_wrapper, "prepare_native_embed"):
            self._mpv_wrapper.prepare_native_embed()
        opts = {
            "panscan": 1.0,
            "keepaspect": "no",
            "keep_open": "yes",
            "wid": int(self._mpv_wrapper.mpv_screen.winId()),
            "vo": "gpu",
            "hwdec": current_hwdec_preview(),
        }
        if sys.platform == "win32":
            opts["ao"] = "wasapi"
        elif sys.platform.startswith("linux") and QApplication.platformName() == "xcb":
            # Keep wid= attached to the Qt X11 surface on an XWayland desktop.
            opts["gpu_context"] = (os.environ.get("STEEMPEG_GPU_CONTEXT") or "").strip() or "x11egl"
            logging.debug(
                "Express player: xcb embed wid=%#x gpu_context=%s",
                opts["wid"], opts["gpu_context"],
            )
        player = mpv.MPV(**opts)
        player.volume = self._volume.slider.value()
        if sys.platform == "win32":
            try:
                from steempeg.infra.window_focus import mark_embed_noactivate

                mark_embed_noactivate(self._mpv_wrapper.mpv_screen)
            except Exception:
                logging.debug("Express player: noactivate failed", exc_info=True)
        return player

    def _sync_from_player(self) -> None:
        """Feeds mpv time / duration / pause into the timeline, time label and play icon."""
        player = self._player
        if player is None:
            return
        try:
            # A seek can still be decoding while time_pos reports the old frame.
            if player.seeking:
                return
            duration = player.duration
            position = player.time_pos
            paused = bool(player.pause)
            at_end = bool(player.eof_reached)
        except Exception:
            return
        # DASH duration estimates drift as mpv reads the last segments.
        if not self._duration_ms and is_sane_media_duration(duration):
            self._duration_ms = round(duration * 1000)
            self._timeline.set_duration(self._duration_ms)
        if position is None and not at_end:
            return
        position_ms = self._duration_ms if at_end else max(0.0, float(position) * 1000)
        if self._duration_ms:
            position_ms = min(position_ms, self._duration_ms)
        playing = not paused and not at_end
        if self._replay_deadline is not None:
            # mpv can still expose EOF while the new position is loading.
            if at_end and time.monotonic() < self._replay_deadline:
                return
            self._replay_deadline = None
            self._timeline.force_jump(position_ms, seek=False)
        self._timeline.set_vlc_time(position_ms, playing)
        if at_end and self._timeline.canvas.drag_state != "playhead":
            if self._timeline.canvas.visual_ms != position_ms:
                self._timeline.force_jump(position_ms, seek=False)
        self._time_label.setText(
            f"{format_player_time(position_ms)} / {format_player_time(self._duration_ms)}"
        )
        icon = "icon_pause.png" if playing else "icon_play.png"
        if self._btn_play.property("glyph") != icon:
            self._btn_play.setProperty("glyph", icon)
            self._btn_play.setIcon(QIcon(themed_asset_path(icon)))

    def toggle_play(self, *, pulse: bool = False) -> None:
        """Plays or pauses the full clip, restarting it at EOF."""
        player = self._player
        if player is None:
            return
        try:
            if self._replay_deadline is None and (
                bool(player.eof_reached) or (
                    self._duration_ms and (player.time_pos or 0) * 1000 >= self._duration_ms - 50
                )
            ):
                if not self._restart_playback():
                    return
                paused = False
            else:
                paused = not player.pause
            player.pause = paused
            if pulse:
                self._play_pause_pulse.pulse(paused=paused)
        except Exception:
            logging.debug("Express player: toggle play failed", exc_info=True)

    def skip_by(self, delta_ms: int) -> None:
        """Jumps forward / back by ``delta_ms`` through the timeline engine."""
        if self._duration_ms <= 0:
            return
        target = max(0.0, min(float(self._duration_ms), self._timeline.canvas.visual_ms + delta_ms))
        self._timeline.force_jump(target)

    def _restart_playback(self) -> bool:
        if not self._seek_ms(0):
            return False
        if self._replay_deadline is None:
            self._timeline.force_jump(0, seek=False)
        return True

    def _seek_ms(self, ms: float) -> bool:
        """Seeks mpv to an absolute position in milliseconds."""
        if self._player is None:
            return False
        player = self._player
        target_ms = max(0.0, ms)
        try:
            at_end = bool(player.eof_reached)
            path = player.path if at_end and sys.platform.startswith("linux") else None
            if path and path.lower().endswith(".mpd"):
                # A completed DASH stream can keep returning EOF on a normal seek.
                player.loadfile(path, start=target_ms / 1000.0)
            else:
                player.seek(target_ms / 1000.0, reference="absolute", precision="exact")
        except Exception:
            logging.debug("Express player: seek failed", exc_info=True)
            return False
        else:
            self._replay_deadline = time.monotonic() + 1.5 if at_end else None
            if at_end:
                self._timeline.force_jump(target_ms, seek=False)
            return True

    def _on_timeline_press(self) -> None:
        """Pauses while the playhead is dragged."""
        if self._player is None:
            return
        try:
            self._was_playing_before_drag = not (self._player.pause or self._player.eof_reached)
            self._player.pause = True
        except Exception:
            self._was_playing_before_drag = False

    def _on_timeline_seek(self, position_ms: int) -> None:
        """Seeks to where the timeline was clicked / dragged."""
        if (
            self._player is not None
            and self._timeline.canvas.drag_state == "playhead"
            and self._player.eof_reached
        ):
            self._eof_drag_target = position_ms
            return
        self._seek_ms(position_ms)

    def _on_timeline_release(self) -> None:
        """Resumes playback if it was playing before the drag."""
        target = self._eof_drag_target
        self._eof_drag_target = None
        if target is not None:
            self._seek_ms(target)
        if self._player is not None and self._was_playing_before_drag:
            try:
                self._player.pause = False
            except Exception:
                pass

    def _on_volume_changed(self, value: int) -> None:
        """Applies the volume slider to mpv."""
        if self._player is not None:
            try:
                self._player.volume = int(value)
            except Exception:
                pass

    def toggle_fullscreen(self) -> None:
        """Fullscreen hides the top strip and header; video and controls stay."""
        if self.isFullScreen():
            self._leave_fullscreen()
            return
        self._top_strip.hide()
        self._header.hide()
        self.showFullScreen()
        self._btn_fullscreen.setIcon(QIcon(get_resource_path("btn_exit_fullscreen.png")))

    def _on_escape(self) -> None:
        """Closes the screenshot preview, or leaves fullscreen when it is closed."""
        preview = getattr(self, "_shot_preview", None)
        if preview is not None and preview.isVisible():
            preview.hide()
            return
        self._leave_fullscreen()

    def _leave_fullscreen(self) -> None:
        """Restores the windowed layout."""
        if not self.isFullScreen():
            return
        self.showNormal()
        self._top_strip.show()
        self._header.show()
        self._btn_fullscreen.setIcon(QIcon(get_resource_path("btn_fullscreen.png")))

    # -- trim -----------------------------------------------------------------

    def toggle_trim(self) -> None:
        """Turns the timeline trim handles on / off."""
        canvas = self._timeline.canvas
        if canvas.is_trim_mode:
            self._timeline.disable_trim_mode()
            self._show_trim_button_state(cancel=False)
        else:
            self._timeline.enable_trim_mode()
            if not canvas.is_trim_mode:
                return
            self._show_trim_button_state(cancel=True)

    def _show_trim_button_state(self, *, cancel: bool) -> None:
        """Shows the button as gold "✂ Trim" or red "✕ Cancel", icons like the desktop player."""
        if cancel:
            self._btn_trim.setIcon(QIcon(get_resource_path("cancel.png")))
            self._btn_trim.setText(" Cancel")
            self._btn_trim.setStyleSheet(tok.STYLE_TRIM_CANCEL_BUTTON)
        else:
            self._btn_trim.setIcon(QIcon(get_resource_path("trim_icon.png")))
            self._btn_trim.setText(" Trim")
            self._btn_trim.setStyleSheet(tok.STYLE_TRIM_BUTTON)
        self._refresh_express_tooltip()

    def current_trim_ms(self) -> tuple[int, int] | None:
        """Returns the active trim range, or None when the whole clip is used."""
        canvas = self._timeline.canvas
        if canvas.is_trim_mode and canvas.trim_end_ms > canvas.trim_start_ms:
            return int(canvas.trim_start_ms), int(canvas.trim_end_ms)
        return None

    # -- export ---------------------------------------------------------------

    def _refresh_express_tooltip(self) -> None:
        """Shows which recipe the Express button will use."""
        from steempeg.core.dash.health import ClipHealth
        from steempeg.ui.express_render import load_express_preset_name

        if self._render is not None and self._render.is_running:
            return
        name = load_express_preset_name(self._app)
        if name:
            recipe = name
        elif self._health_report is None:
            recipe = "Automatic"
        elif self._health_report.level != ClipHealth.HEALTHY:
            recipe = "Re-encode · clip has issues"
        elif self.current_trim_ms() is not None:
            recipe = "Re-encode for exact trim"
        else:
            recipe = "Stream copy · no re-encode"
        self._btn_express.setToolTip(f"Render now · {recipe}")

    def _on_express_clicked(self) -> None:
        """Starts Express with the remembered recipe, or cancels a running one."""
        if self._render is not None and self._render.is_running:
            self._render.cancel()
            return
        self.start_express(preset_name=None)

    def start_express(self, *, preset_name: str | None, options=None) -> None:
        """Builds and starts an Express render for this clip (trim respected)."""
        from steempeg.ui.express_render import build_express_job, confirm_express_export
        from steempeg.ui.message_dialog import steempeg_warning

        if self._render is not None and self._render.is_running:
            return
        job = build_express_job(
            self._app, self._info.path, preset_name=preset_name,
            trim_ms=self.current_trim_ms(), options=options,
        )
        if job is None:
            steempeg_warning(self, "Express render", "Could not prepare this clip for rendering.")
            return
        self._health_report = job.health_report
        self._paint_clip_health(job.health_report)
        self._refresh_express_tooltip()
        if not confirm_express_export(self, job):
            return
        render = self._app.start_prepared_express_render(job)
        if render is None:
            steempeg_warning(self, "Express render", "Could not prepare this clip for rendering.")
            return
        self._render = render
        self._result_strip.hide()
        render.progress_changed.connect(self._on_render_progress)
        render.finished.connect(self._on_render_finished)
        self._btn_arrow.setEnabled(False)
        self._btn_express.setToolTip(f"{job.method_label} · Click to cancel")
        self._on_render_progress(0.0)

    def _on_render_progress(self, percent: float) -> None:
        """Fills the Express button like a progress bar."""
        self._btn_express.setText(f"Rendering {int(percent)}%")
        self._btn_express.setStyleSheet(build_express_progress_qss(percent))

    def _on_render_finished(self, success: bool, error: str, output_file: str) -> None:
        """Resets the button and shows the result strip."""
        self._render = None
        self._btn_arrow.setEnabled(True)
        self._btn_express.setText("⚡ Express")
        self._btn_express.setStyleSheet("")
        self._refresh_express_tooltip()
        if success and output_file:
            self._last_output = output_file
            self._set_result_message(f"Saved · {os.path.basename(output_file)}", confirmed=True)
            self._btn_show_folder.show()
            self._btn_copy.show()
        elif "cancel" in (error or "").lower():
            self._set_result_message("Render cancelled")
            self._btn_show_folder.hide()
            self._btn_copy.hide()
        else:
            self._set_result_message(f"Render failed · {error or 'unknown error'}")
            self._btn_show_folder.hide()
            self._btn_copy.hide()
        self._result_strip.show()

    def _show_export_menu(self) -> None:
        menu = self._build_export_menu()
        anchor = self._btn_arrow.mapToGlobal(QPoint(self._btn_arrow.width(), 0))
        size = menu.sizeHint()
        menu.exec(QPoint(anchor.x() - size.width(), anchor.y() - size.height() - 6))
        menu.deleteLater()

    def _build_export_menu(self) -> QMenu:
        from steempeg.render.export_presets import list_preset_names
        from steempeg.ui.express_render import load_express_preset_name

        menu = QMenu(self)
        menu.setStyleSheet(ut.menu_stylesheet())
        current = load_express_preset_name(self._app)

        express = QAction("⚡ Express render", menu)
        express.triggered.connect(lambda: self.start_express(preset_name=None))
        menu.addAction(express)

        names = list_preset_names(self._app.load_user_settings)
        presets = menu.addMenu("🎛️ Render with preset")
        presets.setEnabled(bool(names))
        for name in names:
            presets.addAction(name).triggered.connect(lambda _=False, n=name: self.start_express(preset_name=n))
        defaults = menu.addMenu("⭐ Use as Express default")
        default_group = QActionGroup(defaults)
        for label, name in [("Automatic", ""), *((name, name) for name in names)]:
            action = defaults.addAction(label)
            default_group.addAction(action)
            action.setCheckable(True)
            action.setChecked(name == (current if current in names else ""))
            action.triggered.connect(lambda _=False, n=name: self._set_express_default(n))

        queue = QAction("📋 Add to Render Queue", menu)
        queue.triggered.connect(self.add_to_render_queue)
        menu.addAction(queue)
        menu.addSeparator()

        settings = QAction("⚙️ Render settings…", menu)
        settings.triggered.connect(self.open_render_settings)
        menu.addAction(settings)
        menu.addAction("📏 Target File Size…").triggered.connect(
            lambda: self.open_render_settings(target_size=True)
        )
        open_main = QAction("🖥️ Open in Steempeg", menu)
        open_main.triggered.connect(self.open_in_steempeg)
        menu.addAction(open_main)
        menu.addSeparator()

        copy = QAction("📎 Copy to clipboard", menu)
        copy.setEnabled(bool(self._last_output and os.path.isfile(self._last_output)))
        copy.setToolTip("Copies the last Express render")
        copy.triggered.connect(self.copy_last_output)
        menu.addAction(copy)

        return menu

    def _set_express_default(self, name: str) -> None:
        from steempeg.ui.express_render import save_express_preset_name

        save_express_preset_name(self._app, name)
        self._refresh_express_tooltip()

    def add_to_render_queue(self) -> None:
        """Queues this clip (with trim) in the main Render Queue."""
        if self._app.add_express_clip_to_queue(self._info.path, trim_ms=self.current_trim_ms()):
            self._set_result_message("Added to Render Queue", confirmed=True)
            self._btn_show_folder.hide()
            self._btn_copy.hide()
            self._btn_open_queue.show()
            self._result_strip.show()

    def open_render_settings(self, *, target_size: bool = False) -> None:
        """Choose one-off export settings while staying in Express Player."""
        from steempeg.ui.express_export_dialog import ExpressExportDialog
        from steempeg.ui.player.preview_quality import decoded_source_height
        from steempeg.ui.settings_prefs import default_export_dir

        target_job = None
        if target_size:
            from steempeg.ui.express_render import build_express_job
            from steempeg.ui.message_dialog import steempeg_warning

            ready = build_express_job(
                self._app, self._info.path, preset_name="", trim_ms=self.current_trim_ms()
            )
            if ready is None:
                steempeg_warning(self, "Target File Size", "Could not read the clip's source format.")
                return
            target_job = ready.job
        player = self._player
        height = decoded_source_height(player) if player is not None else 0
        try:
            fps = float(player.container_fps or 0) if player is not None else 0.0
        except (AttributeError, TypeError, ValueError):
            fps = 0.0
        dialog = ExpressExportDialog(
            self, source_height=height, source_fps=fps,
            destination=getattr(self._app, "custom_destination", "") or default_export_dir(),
            target_job=target_job,
        )
        options = dialog.choose()
        dialog.deleteLater()
        if options is not None:
            self.start_express(preset_name="", options=options)

    def open_in_steempeg(self) -> None:
        """Closes the mini player and opens the clip in the full editor."""
        path = self._info.path
        self.close()
        self._app.open_new_clip_from_popup(path)

    def show_last_output_in_folder(self) -> None:
        """Selects the last Express render in Explorer."""
        from steempeg.infra.paths import reveal_in_file_manager

        if self._last_output:
            reveal_in_file_manager(self._last_output)

    def copy_last_output(self) -> None:
        """Copies the last Express render file to the clipboard."""
        if self._last_output and os.path.isfile(self._last_output):
            copy_file_to_clipboard(self._last_output)
            self._set_result_message(f"Copied · {os.path.basename(self._last_output)}", confirmed=True)
            self._result_strip.show()

    # -- delete / close -------------------------------------------------------

    def delete_clip(self) -> None:
        """Asks, then moves the clip folder to the Recycle Bin and closes the player."""
        from steempeg.ui.message_dialog import steempeg_confirm_delete, steempeg_critical

        if not steempeg_confirm_delete(
            self,
            "Delete Clip",
            "Move this clip to the Recycle Bin?",
            detail="You can restore it from the Recycle Bin later.",
        ):
            return
        if self._render is not None and self._render.is_running:
            self._render.cancel()
        self._release_player()
        try:
            self._app.recycle_clip(self._info.path)
        except Exception as exc:
            logging.exception("Express player: recycle failed")
            steempeg_critical(self, "Error", f"Could not move the clip to the Recycle Bin.\n\n{exc}")
            return
        self.close()

    def _release_player(self) -> None:
        """Stops polling, the PyAV hover decoder and the mpv handle (frees the clip files)."""
        self._stop_timeline_marks()
        preview = getattr(self, "_shot_preview", None)
        if preview is not None:
            preview.hide()
        self._poll.stop()
        sniper = getattr(self._timeline.canvas, "sniper", None)
        if sniper is not None:
            try:
                sniper.kill_worker()
            except Exception:
                logging.debug("Express player: sniper stop failed", exc_info=True)
        self._timeline.current_video_path = ""
        player = self._player
        self._play_pause_pulse.cancel()
        self._player = None
        if player is None:
            return
        try:
            player.terminate()
        except Exception:
            logging.debug("Express player: mpv terminate failed", exc_info=True)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt override
        """Frees mpv; a running Express render keeps going in the background."""
        self._remove_video_surface_click_handler()
        self._release_player()
        super().closeEvent(event)
