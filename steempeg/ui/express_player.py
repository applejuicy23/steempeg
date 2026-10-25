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

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QCursor, QGuiApplication, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.paths import get_resource_path
from steempeg.services.new_clip_watcher import NewClipInfo
from steempeg.ui import design_tokens as tok
from steempeg.ui import ui_theme as ut

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
        color: #e0e0e0; font-family: {tok.FONT_APP}; font-size: 12px; font-weight: bold;
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
        from steempeg.ui.window_chrome import _TrafficLight, app_logo_pixmap

        self._window = window
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
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def mousePressEvent(self, event) -> None:  # noqa: N802 — Qt override
        """Starts a native window move when the strip is dragged."""
        if event.button() == Qt.MouseButton.LeftButton:
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


class ExpressPlayerWindow(QWidget):
    """Mini player window for one clip with Express export."""

    def __init__(self, app, info: NewClipInfo):
        """Builds the window for ``info``; call ``open_clip()`` after ``show()``."""
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self._app = app
        self._info = info
        self._player = None
        self._duration_ms = 0
        self._was_playing_before_drag = False
        self._render = None
        self._last_output = ""
        self._marks_gen = 0
        self._marks_worker = None
        self._shot_preview = None
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
        body.addWidget(self._build_footer())

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
        if hasattr(self._timeline, "_apply_timeline_chrome_stylesheet"):
            self._timeline._apply_timeline_chrome_stylesheet()
        self._timeline.canvas.update()

    # -- layout ---------------------------------------------------------------

    def _build_header(self) -> QFrame:
        """Game icon + name centred, at the desktop player header's height and font."""
        from steempeg.ui.icon_utils import apply_square_icon
        from steempeg.ui.layout_defaults import (
            PLAYER_HEADER_CANVAS_GAP,
            PLAYER_HEADER_FRAME_BORDER_V,
        )
        from steempeg.ui.new_clip_popup import build_game_icon_pixmap
        from steempeg.ui.player_header_layout import player_header_title_qfont
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
        lay = QHBoxLayout(header)
        lay.setContentsMargins(int(COMFORT.header_pad_h), 0, int(COMFORT.header_pad_h), 0)
        lay.addStretch(1)
        icon_px = int(COMFORT.header_icon)
        icon = QLabel()
        icon.setStyleSheet("background: transparent;")
        apply_square_icon(icon, build_game_icon_pixmap(self._info.icon_path, icon_px), icon_px)
        lay.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addSpacing(8)
        title = QLabel(self._info.game_name)
        title.setObjectName("ExpressTitle")
        title.setFont(player_header_title_qfont(int(COMFORT.header_font)))
        lay.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addStretch(1)
        self._header = header
        return header

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
        self._result_text = QLabel("")
        self._result_text.setObjectName("ExpressResultText")
        lay.addWidget(self._result_text, 1)
        self._btn_show_folder = QPushButton("Show in folder")
        self._btn_copy = QPushButton("Copy")
        for btn in (self._btn_show_folder, self._btn_copy):
            btn.setObjectName("ExpressPill")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            lay.addWidget(btn)
        self._btn_show_folder.clicked.connect(self.show_last_output_in_folder)
        self._btn_copy.clicked.connect(self.copy_last_output)
        close = QPushButton("✕")
        close.setObjectName("ExpressFlat")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(strip.hide)
        lay.addWidget(close)
        strip.hide()
        self._result_strip = strip
        return strip

    def _make_icon_button(self, asset: str, icon_px: int, tip: str, *, box: int = 40) -> QPushButton:
        """Round transparent button with a bundled icon."""
        btn = QPushButton()
        btn.setObjectName("ExpressIconBtn")
        btn.setFixedSize(box, box)
        btn.setIcon(QIcon(get_resource_path(asset)))
        btn.setIconSize(QSize(icon_px, icon_px))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setToolTip(tip)
        return btn

    # -- playback -------------------------------------------------------------

    def open_clip(self) -> None:
        """Creates the mpv handle on the video surface and starts playing the clip."""
        from steempeg.core.dash.discovery import find_mpd_paths

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
        play_path = os.path.abspath(mpds[0]).replace("\\", "/")
        logging.info("Express player: play %s", play_path)
        self._attach_hover_preview(play_path)
        self._load_timeline_marks(play_path)
        self._player.play(play_path)
        self._player.pause = False
        self._poll.start()

    def _attach_hover_preview(self, play_path: str) -> None:
        """Points the timeline's PyAV hover preview at this clip and the app's frame cache."""
        cache_dir = getattr(self._app, "cache_dir", None)
        if cache_dir:
            self._timeline.canvas._markers_cache_dir = cache_dir
            self._timeline.canvas.sniper.cache_dir = cache_dir
        self._timeline.sniper_source_path = play_path
        self._timeline.current_video_path = play_path

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
            duration = player.duration
            position = player.time_pos
            paused = bool(player.pause)
            at_end = bool(player.eof_reached)
        except Exception:
            return
        if duration and int(duration * 1000) != self._duration_ms:
            self._duration_ms = int(duration * 1000)
            self._timeline.set_duration(self._duration_ms)
        position_ms = float(position or 0.0) * 1000.0
        playing = not paused and not at_end
        canvas = self._timeline.canvas
        if playing and canvas.is_trim_mode and canvas.trim_end_ms > canvas.trim_start_ms:
            if position_ms >= canvas.trim_end_ms:
                self._seek_ms(canvas.trim_start_ms)
                position_ms = canvas.trim_start_ms
        self._timeline.set_vlc_time(position_ms, playing)
        self._time_label.setText(
            f"{format_player_time(position_ms)} / {format_player_time(self._duration_ms)}"
        )
        icon = "icon_pause.png" if playing else "icon_play.png"
        if self._btn_play.property("glyph") != icon:
            self._btn_play.setProperty("glyph", icon)
            self._btn_play.setIcon(QIcon(get_resource_path(icon)))

    def toggle_play(self) -> None:
        """Plays or pauses; restarts from the beginning (or trim start) at the end."""
        player = self._player
        if player is None:
            return
        try:
            if bool(player.eof_reached) or (
                self._duration_ms and (player.time_pos or 0) * 1000 >= self._duration_ms - 50
            ):
                canvas = self._timeline.canvas
                start = canvas.trim_start_ms if canvas.is_trim_mode else 0
                self._seek_ms(start)
                player.pause = False
                return
            player.pause = not player.pause
        except Exception:
            logging.debug("Express player: toggle play failed", exc_info=True)

    def skip_by(self, delta_ms: int) -> None:
        """Jumps forward / back by ``delta_ms`` through the timeline engine."""
        if self._duration_ms <= 0:
            return
        target = max(0.0, min(float(self._duration_ms), self._timeline.canvas.visual_ms + delta_ms))
        self._timeline.force_jump(target)

    def _seek_ms(self, ms: float) -> None:
        """Seeks mpv to an absolute position in milliseconds."""
        if self._player is None:
            return
        try:
            self._player.seek(max(0.0, ms / 1000.0), reference="absolute", precision="exact")
        except Exception:
            logging.debug("Express player: seek failed", exc_info=True)

    def _on_timeline_press(self) -> None:
        """Pauses while the playhead is dragged."""
        if self._player is None:
            return
        try:
            self._was_playing_before_drag = not self._player.pause
            self._player.pause = True
        except Exception:
            self._was_playing_before_drag = False

    def _on_timeline_seek(self, position_ms: int) -> None:
        """Seeks to where the timeline was clicked / dragged."""
        self._seek_ms(position_ms)

    def _on_timeline_release(self) -> None:
        """Resumes playback if it was playing before the drag."""
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

    def current_trim_ms(self) -> tuple[int, int] | None:
        """Returns the active trim range, or None when the whole clip is used."""
        canvas = self._timeline.canvas
        if canvas.is_trim_mode and canvas.trim_end_ms > canvas.trim_start_ms:
            return int(canvas.trim_start_ms), int(canvas.trim_end_ms)
        return None

    # -- export ---------------------------------------------------------------

    def _refresh_express_tooltip(self) -> None:
        """Shows which recipe the Express button will use."""
        from steempeg.ui.express_render import load_express_preset_name

        name = load_express_preset_name(self._app)
        recipe = name or "Original (max quality re-encode for clips with Issues)"
        self._btn_express.setToolTip(f"Render now · {recipe}")

    def _on_express_clicked(self) -> None:
        """Starts Express with the remembered recipe, or cancels a running one."""
        if self._render is not None and self._render.is_running:
            self._render.cancel()
            return
        self.start_express(preset_name=None)

    def start_express(self, *, preset_name: str | None) -> None:
        """Builds and starts an Express render for this clip (trim respected)."""
        from steempeg.ui.message_dialog import steempeg_warning

        render = self._app.start_express_render(
            self._info.path, preset_name=preset_name, trim_ms=self.current_trim_ms()
        )
        if render is None:
            steempeg_warning(self, "Express render", "Could not prepare this clip for rendering.")
            return
        self._render = render
        self._result_strip.hide()
        render.progress_changed.connect(self._on_render_progress)
        render.finished.connect(self._on_render_finished)
        self._btn_express.setToolTip("Click to cancel")
        self._on_render_progress(0.0)

    def _on_render_progress(self, percent: float) -> None:
        """Fills the Express button like a progress bar."""
        self._btn_express.setText(f"Rendering {int(percent)}%")
        self._btn_express.setStyleSheet(build_express_progress_qss(percent))

    def _on_render_finished(self, success: bool, error: str, output_file: str) -> None:
        """Resets the button and shows the result strip."""
        self._render = None
        self._btn_express.setText("⚡ Express")
        self._btn_express.setStyleSheet("")
        self._refresh_express_tooltip()
        if success and output_file:
            self._last_output = output_file
            self._result_text.setText(f"✓ Saved · {os.path.basename(output_file)}")
            self._btn_show_folder.show()
            self._btn_copy.show()
        elif "cancel" in (error or "").lower():
            self._result_text.setText("Render cancelled")
            self._btn_show_folder.hide()
            self._btn_copy.hide()
        else:
            self._result_text.setText(f"Render failed · {error or 'unknown error'}")
            self._btn_show_folder.hide()
            self._btn_copy.hide()
        self._result_strip.show()

    def _show_export_menu(self) -> None:
        """Opens the export menu under the arrow (Steam-style)."""
        from steempeg.render.export_presets import list_preset_names
        from steempeg.ui.express_render import load_express_preset_name

        menu = QMenu(self)
        menu.setStyleSheet(ut.menu_stylesheet())
        current = load_express_preset_name(self._app)

        express = QAction("⚡ Express render", menu)
        express.triggered.connect(lambda: self.start_express(preset_name=None))
        menu.addAction(express)

        presets = menu.addMenu("🎛️ Render with preset")
        auto = QAction("Automatic (Original / max for Issues)", presets)
        auto.setCheckable(True)
        auto.setChecked(not current)
        auto.triggered.connect(lambda: self._render_with_preset(""))
        presets.addAction(auto)
        names = list_preset_names(self._app.load_user_settings)
        if names:
            presets.addSeparator()
        for name in names:
            action = QAction(name, presets)
            action.setCheckable(True)
            action.setChecked(name == current)
            action.triggered.connect(lambda _=False, n=name: self._render_with_preset(n))
            presets.addAction(action)

        queue = QAction("📋 Add to Render Queue", menu)
        queue.triggered.connect(self.add_to_render_queue)
        menu.addAction(queue)
        menu.addSeparator()

        settings = QAction("⚙️ Render settings…", menu)
        settings.triggered.connect(self.open_render_settings)
        menu.addAction(settings)
        open_main = QAction("🖥️ Open in Steempeg", menu)
        open_main.triggered.connect(self.open_in_steempeg)
        menu.addAction(open_main)
        menu.addSeparator()

        copy = QAction("📎 Copy to clipboard", menu)
        copy.setEnabled(bool(self._last_output and os.path.isfile(self._last_output)))
        copy.setToolTip("Copies the last Express render")
        copy.triggered.connect(self.copy_last_output)
        menu.addAction(copy)

        anchor = self._btn_arrow.mapToGlobal(QPoint(self._btn_arrow.width(), 0))
        size = menu.sizeHint()
        menu.exec(QPoint(anchor.x() - size.width(), anchor.y() - size.height() - 6))

    def _render_with_preset(self, name: str) -> None:
        """Remembers ``name`` as the Express preset and renders with it."""
        from steempeg.ui.express_render import save_express_preset_name

        save_express_preset_name(self._app, name)
        self._refresh_express_tooltip()
        self.start_express(preset_name=name)

    def add_to_render_queue(self) -> None:
        """Queues this clip (with trim) in the main Render Queue."""
        if self._app.add_express_clip_to_queue(self._info.path, trim_ms=self.current_trim_ms()):
            self._result_text.setText("✓ Added to Render Queue")
            self._btn_show_folder.hide()
            self._btn_copy.hide()
            self._result_strip.show()

    def open_render_settings(self) -> None:
        """Hands the clip to the main editor and opens its Render Settings window."""
        path = self._info.path
        self.close()
        self._app.open_new_clip_from_popup(path, open_render_settings=True)

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
            self._result_text.setText(f"📎 Copied · {os.path.basename(self._last_output)}")
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
        self._player = None
        if player is None:
            return
        try:
            player.terminate()
        except Exception:
            logging.debug("Express player: mpv terminate failed", exc_info=True)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt override
        """Frees mpv; a running Express render keeps going in the background."""
        self._release_player()
        super().closeEvent(event)
