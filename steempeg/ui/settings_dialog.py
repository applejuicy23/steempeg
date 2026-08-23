"""App-wide Settings dialog — prefs that are not one click away elsewhere."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from steempeg.ui.icon_assets import title_bar_info_pixmap
from steempeg.ui import design_tokens as tok
from steempeg.ui.icon_shape import (
    ICON_SHAPE_DEFAULT,
    ICON_SHAPE_LABELS,
    KEY_GAME_ICON_SHAPE,
    get_icon_shape,
    normalize_icon_shape,
    set_icon_shape,
)
from steempeg.ui.clip_card_style import (
    CARD_STYLE_DEFAULT,
    CARD_STYLE_LABELS,
    CLIP_CARD_STYLE_REV_CURRENT,
    KEY_CLIP_CARD_STYLE,
    KEY_CLIP_CARD_STYLE_REV,
    get_clip_card_style,
    migrate_clip_card_style_in_settings,
    normalize_clip_card_style,
    set_clip_card_style,
)
from steempeg.ui.player_header_layout import (
    HEADER_LAYOUT_DEFAULT,
    HEADER_LAYOUT_LABELS,
    KEY_PLAYER_HEADER_LAYOUT,
    get_header_layout,
    normalize_header_layout,
    set_header_layout,
)
from steempeg.ui.player_layout import (
    KEY_PLAYER_LAYOUT,
    PLAYER_LAYOUT_DEFAULT,
    PLAYER_LAYOUT_LABELS,
    get_player_layout,
    normalize_player_layout,
    set_player_layout,
)
from steempeg.ui.player_header_size import (
    KEY_PLAYER_HEADER_SIZE,
    KEY_PLAYER_HEADER_SIZE_REV,
    PLAYER_HEADER_DEFAULT,
    PLAYER_HEADER_SIZE_LABELS,
    PLAYER_HEADER_SIZE_REV_CURRENT,
    get_player_header_size,
    migrate_player_header_size_in_settings,
    normalize_player_header_size,
    set_player_header_size,
)
from steempeg.ui.player_boost import (
    KEY_SPEED_BOOST_CEILING,
    KEY_VOLUME_BOOST_CEILING,
    SPEED_CEILING_DEFAULT,
    SPEED_CEILING_LABELS,
    VOLUME_CEILING_DEFAULT,
    VOLUME_CEILING_LABELS,
    get_speed_boost_ceiling,
    get_volume_boost_ceiling,
    normalize_speed_boost_ceiling,
    normalize_volume_boost_ceiling,
    set_speed_boost_ceiling,
    set_volume_boost_ceiling,
)
from steempeg.ui.timeline_strip_size import (
    KEY_TIMELINE_STRIP_SIZE,
    KEY_TIMELINE_STRIP_SIZE_REV,
    TIMELINE_STRIP_DEFAULT,
    TIMELINE_STRIP_LABELS,
    TIMELINE_STRIP_SIZE_REV_CURRENT,
    get_timeline_strip_size,
    migrate_timeline_strip_size_in_settings,
    normalize_timeline_strip_size,
    set_timeline_strip_size,
)
from steempeg.ui.message_dialog import (
    _BTN_PRIMARY,
    dialog_theme,
    steempeg_information,
    steempeg_question,
    steempeg_warning,
)
from steempeg.ui.shell_chooser import (
    UI_SHELL_ASK_KEY,
    UI_SHELL_DESKTOP,
    UI_SHELL_KEY,
    UI_SHELL_PORTABLE,
    is_steamdeck_build,
    load_ask_ui_shell,
    load_ui_shell,
    save_ask_ui_shell,
    save_ui_shell,
)
from steempeg.ui.settings_prefs import (
    CLOCK_FORMAT_LABELS,
    DATE_FORMAT_LABELS,
    DEFAULT_CLOCK_FORMAT,
    DEFAULT_DATE_FORMAT,
    DEFAULT_DISPLAY_TIMEZONE,
    DEFAULT_HWDEC_PREVIEW,
    DEFAULT_MARKER_TRIM_OFFSET_MS,
    DEFAULT_MARKERS_ON_STRIP,
    DEFAULT_MEDIA_CACHE_LIMIT_GB,
    DEFAULT_STARTUP_LIBRARY_SCAN,
    DISPLAY_TIMEZONE_LABELS,
    HWDEC_LABELS,
    KEY_APP_LOG_LEVEL,
    KEY_CLOCK_FORMAT,
    KEY_CONFIRM_BEFORE_DELETE,
    KEY_DATE_FORMAT,
    KEY_DEFAULT_RENDER_TAB,
    KEY_DESKTOP_RENDER_LAYOUT,
    KEY_DISPLAY_TIMEZONE,
    KEY_FFMPEG_LOG_LEVEL,
    KEY_HWDEC_PREVIEW,
    KEY_MARKER_TRIM_OFFSET_MS,
    KEY_MARKERS_ON_STRIP,
    KEY_MEDIA_CACHE_LIMIT_GB,
    KEY_MPV_LOG_LEVEL,
    KEY_PERMANENT_EXPORT_FOLDER,
    KEY_PORTABLE_LIKE_MIDDLE_SPLITTER,
    KEY_REMEMBER_LIBRARY_TAB,
    KEY_SCREENSHOTS_FOLDER,
    KEY_STARTUP_LIBRARY_SCAN,
    KEY_TEST_NEW_FULLSCREEN,
    KEY_UPDATE_CHECK_INTERVAL,
    LOG_LEVEL_LABELS,
    MARKER_TRIM_LABELS,
    MEDIA_CACHE_LIMIT_LABELS,
    DESKTOP_RENDER_LIKE_A_PORTABLE,
    DESKTOP_RENDER_LAYOUT_LABELS,
    RENDER_TAB_LABELS,
    STARTUP_SCAN_LABELS,
    TZ_SYSTEM,
    UPDATE_INTERVAL_LABELS,
    apply_default_render_tab,
    apply_export_folder,
    configure_runtime_prefs,
    default_export_dir,
    default_screenshots_dir,
    ensure_usable_export_folder,
    is_outside_default_rendered,
    load_app_log_level,
    load_clock_format,
    load_confirm_before_delete,
    load_date_format,
    load_default_render_tab,
    load_desktop_render_layout,
    load_display_timezone,
    load_ffmpeg_log_level,
    load_hwdec_preview,
    load_marker_trim_offset_ms,
    load_markers_on_strip,
    load_media_cache_limit_gb,
    load_mpv_log_level,
    load_portable_like_middle_splitter,
    load_remember_library_tab,
    load_startup_library_scan,
    load_test_new_fullscreen,
    normalize_clock_format,
    normalize_date_format,
    normalize_desktop_render_layout,
    normalize_display_timezone,
    normalize_export_folder,
    normalize_hwdec_preview,
    normalize_log_level,
    normalize_marker_trim_offset_ms,
    normalize_markers_on_strip,
    normalize_media_cache_limit_gb,
    normalize_portable_like_middle_splitter,
    normalize_render_tab,
    normalize_screenshots_folder,
    normalize_startup_library_scan,
    normalize_update_check_interval,
    notify_export_folder_fallback,
    resolve_permanent_export_folder,
    resolve_screenshots_folder,
    resolve_update_check_interval,
    set_markers_on_strip,
    DEFAULT_APP_LOG_LEVEL,
    DEFAULT_FFMPEG_LOG_LEVEL,
    DEFAULT_MPV_LOG_LEVEL,
)
from steempeg.ui.widgets.combo_chrome import apply_dark_combo_popup
from steempeg.ui.widgets.dialog_chrome import SteempegDialog
from steempeg.ui.widgets.steempeg_check import SteempegCheckBox
from steempeg.ui.ui_theme import (
    KEY_UI_THEME,
    UI_THEME_DEFAULT,
    UI_THEME_LABELS,
    get_ui_theme,
    normalize_ui_theme,
)

# Persisted preference keys
KEY_NOTIFY_ON_RENDER_COMPLETE = "notify_on_render_complete"
KEY_RENDER_PROCESS_PRIORITY = "render_process_priority"
KEY_PAUSE_PREVIEW_DURING_RENDER = "pause_preview_during_render"

HINT_DISMISS_KEYS: tuple[str, ...] = (
    "original_preset_warning_dismissed",
    "render_queue_duplicate_notice_dismissed",
    "render_queue_empty_hint_dismissed",
    "portable_queue_empty_hint_dismissed",
    "small_screen_warning_dismissed",
)

KEY_SMALL_SCREEN_WARNING_DISMISSED = "small_screen_warning_dismissed"

PRIORITY_NORMAL = "normal"
PRIORITY_ABOVE = "above_normal"
PRIORITY_HIGH = "high"
_PRIORITY_LABELS = (
    (PRIORITY_NORMAL, "Normal"),
    (PRIORITY_ABOVE, "Above normal"),
    (PRIORITY_HIGH, "High"),
)

_SECTION = (
    f"color: {tok.TEXT_TITLE}; font-size: 13px; font-weight: bold; "
    f"background: transparent; font-family: {tok.FONT_APP};"
)
_HINT = (
    f"color: {tok.TEXT_MUTED}; font-size: 11px; background: transparent; "
    f"font-family: {tok.FONT_APP};"
)

_SETTINGS_DESIGN_W = 540
_SETTINGS_DESIGN_H = 560
# Keep the shell shorter than the Steempeg window / work area so it can center.
_SETTINGS_HEIGHT_FRAC = 0.85
_SETTINGS_MIN_H = 320


def _tab_page() -> tuple[QWidget, QVBoxLayout]:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)
    return page, layout


def _settings_max_height(parent) -> int:
    """Cap Settings height to ~85% of the Steempeg window (or screen work area)."""
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QWidget

    host = parent
    if isinstance(parent, QWidget):
        win = parent.window()
        if win is not None:
            host = win

    host_h = 0
    if host is not None and hasattr(host, "height"):
        try:
            host_h = int(host.height())
        except Exception:
            host_h = 0
    if host_h <= 0:
        aw = QApplication.activeWindow()
        if aw is not None:
            host_h = int(aw.height())
            host = aw

    max_h = int(host_h * _SETTINGS_HEIGHT_FRAC) if host_h > 0 else 0

    screen = None
    try:
        if host is not None and hasattr(host, "screen"):
            screen = host.screen()
    except Exception:
        screen = None
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is not None:
        avail_h = int(screen.availableGeometry().height() * _SETTINGS_HEIGHT_FRAC)
        max_h = min(max_h, avail_h) if max_h > 0 else avail_h

    return max(_SETTINGS_MIN_H, max_h) if max_h > 0 else _SETTINGS_DESIGN_H


class _SettingsTabScroll(QScrollArea):
    """Per-tab scroll body — compact size hints so the dialog does not grow to content."""

    def sizeHint(self) -> QSize:
        return QSize(400, 280)

    def minimumSizeHint(self) -> QSize:
        return QSize(200, 120)


def _scroll_settings_tab(inner: QWidget) -> QScrollArea:
    """Wrap a settings tab page; lavender pill scrollbar matches the library."""
    from steempeg.ui.library.library_styles import (
        LIBRARY_SCROLLBAR_VERTICAL,
        install_library_vertical_scrollbar,
    )

    bg = tok.BG_SHELL
    inner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    inner.setStyleSheet(f"background-color: {bg};")

    scroll = _SettingsTabScroll()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    scroll.setMinimumHeight(0)
    tok.apply_dialog_scroll_bg(scroll, bg)
    scroll.setStyleSheet(tok.dialog_scroll_stylesheet(bg) + LIBRARY_SCROLLBAR_VERTICAL)
    install_library_vertical_scrollbar(scroll)
    scroll.setWidget(inner)
    return scroll


class SettingsDialog(SteempegDialog):
    """App Settings — tabbed: General · Visual · Notifications · Performance · Support · Advanced."""

    def __init__(self, app, parent=None, **theme_kwargs):
        parent_w = parent or getattr(app, "ui", None)
        if not theme_kwargs.get("bar_color"):
            theme_kwargs = {**dialog_theme(parent_w), **theme_kwargs}
        super().__init__("Settings", parent_w, **theme_kwargs)
        self._app = app
        self.setMinimumWidth(480)
        self.setMinimumHeight(_SETTINGS_MIN_H)
        self._apply_settings_geometry()

        settings = {}
        if hasattr(app, "load_user_settings"):
            try:
                settings = app.load_user_settings() or {}
            except Exception:
                settings = {}

        root = self.content_layout
        root.setSpacing(10)

        tabs = QTabWidget()
        from steempeg.ui import ui_theme as ut

        tabs.setStyleSheet(ut.settings_dialog_tabs_stylesheet())
        self._settings_tabs = tabs
        tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(tabs, 1)

        # ----- General (Updates + Export + Render landing + Shell) -----
        general, g = _tab_page()
        g.addWidget(self._section("Updates"))
        upd_row = QHBoxLayout()
        upd_row.setSpacing(8)
        upd_lbl = QLabel("Check for updates")
        upd_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_update_interval = QComboBox()
        for value, label in UPDATE_INTERVAL_LABELS:
            self._combo_update_interval.addItem(label, value)
        cur_upd = resolve_update_check_interval(settings)
        uidx = self._combo_update_interval.findData(cur_upd)
        self._combo_update_interval.setCurrentIndex(max(0, uidx))
        self._combo_update_interval.setToolTip(
            "Every launch checks once each time the app starts. "
            "Daily and Weekly wait for that cooldown."
        )
        upd_row.addWidget(upd_lbl)
        upd_row.addWidget(self._combo_update_interval, 1)
        g.addLayout(upd_row)
        g.addWidget(self._hint("Quiet badge only: never installs without you."))

        g.addWidget(self._section("Export"))
        export_row = QHBoxLayout()
        export_row.setSpacing(8)
        self._edit_export_folder = QLineEdit()
        self._edit_export_folder.setPlaceholderText(default_export_dir())
        self._committed_export_folder = resolve_permanent_export_folder(settings)
        self._edit_export_folder.setText(self._committed_export_folder)
        btn_browse_export = QPushButton("Browse…")
        btn_browse_export.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse_export.clicked.connect(self._browse_export_folder)
        btn_clear_export = QPushButton("Reset")
        btn_clear_export.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear_export.setToolTip("Reset to the default rendered_videos folder")
        btn_clear_export.clicked.connect(self._reset_export_folder)
        export_row.addWidget(self._edit_export_folder, 1)
        export_row.addWidget(btn_browse_export, 0)
        export_row.addWidget(btn_clear_export, 0)
        g.addLayout(export_row)
        self._export_folder_hint = self._hint(
            "Permanent output folder for exports. Save syncs the Export panel. "
            "Folders outside rendered_videos still work; Open in Steempeg may be limited."
        )
        g.addWidget(self._export_folder_hint)
        self._refresh_export_folder_hint()

        g.addWidget(self._section("Render panel"))
        tab_row = QHBoxLayout()
        tab_row.setSpacing(8)
        tab_lbl = QLabel("Default tab")
        tab_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_render_tab = QComboBox()
        for value, label in RENDER_TAB_LABELS:
            self._combo_render_tab.addItem(label, value)
        cur_tab = load_default_render_tab(settings)
        self._committed_render_tab = cur_tab
        tidx = self._combo_render_tab.findData(cur_tab)
        self._combo_render_tab.setCurrentIndex(max(0, tidx))
        tab_row.addWidget(tab_lbl)
        tab_row.addWidget(self._combo_render_tab, 1)
        g.addLayout(tab_row)
        g.addWidget(
            self._hint(
                "Landing tab when the Render panel / neo-nav opens. "
                "Default is Video Settings. Save switches the open panel."
            )
        )

        layout_row = QHBoxLayout()
        layout_row.setSpacing(8)
        layout_lbl = QLabel("Desktop layout")
        layout_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_desktop_render = QComboBox()
        for value, label in DESKTOP_RENDER_LAYOUT_LABELS:
            self._combo_desktop_render.addItem(label, value)
        cur_layout = load_desktop_render_layout(settings)
        self._committed_desktop_render = cur_layout
        lidx = self._combo_desktop_render.findData(cur_layout)
        self._combo_desktop_render.setCurrentIndex(max(0, lidx))
        layout_row.addWidget(layout_lbl)
        layout_row.addWidget(self._combo_desktop_render, 1)
        g.addLayout(layout_row)
        g.addWidget(
            self._hint(
                "It's a Desktop, classic docked Render panel. "
                "Like a Portable, purple Render Settings beside Start opens a "
                "floating settings window (minimize / maximize; click again to close)."
            )
        )
        self._chk_portable_like_middle_splitter = SteempegCheckBox(
            "Show middle splitter (Like a Portable)"
        )
        cur_middle = load_portable_like_middle_splitter(settings)
        self._committed_portable_like_middle_splitter = cur_middle
        self._chk_portable_like_middle_splitter.setChecked(cur_middle)
        g.addWidget(self._chk_portable_like_middle_splitter)
        g.addWidget(
            self._hint(
                "Restore the player↔dash drag handle in Like a Portable layout. "
                "Off keeps the fixed air gap (default). Save applies live."
            )
        )
        self._combo_desktop_render.currentIndexChanged.connect(
            self._sync_portable_like_middle_splitter_enabled
        )
        self._sync_portable_like_middle_splitter_enabled()

        g.addWidget(self._section("Shell"))
        shell_row = QHBoxLayout()
        shell_row.setSpacing(8)
        shell_lbl = QLabel("UI shell")
        shell_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_shell = QComboBox()
        self._combo_shell.addItem("Desktop", UI_SHELL_DESKTOP)
        self._combo_shell.addItem("Portable (theatre)", UI_SHELL_PORTABLE)
        current_shell = load_ui_shell() or UI_SHELL_DESKTOP
        idx = self._combo_shell.findData(current_shell)
        self._combo_shell.setCurrentIndex(max(0, idx))
        shell_row.addWidget(shell_lbl)
        shell_row.addWidget(self._combo_shell, 1)
        g.addLayout(shell_row)
        self._chk_ask_shell = SteempegCheckBox("Ask which shell on startup")
        self._chk_ask_shell.setChecked(load_ask_ui_shell())
        if is_steamdeck_build():
            self._chk_ask_shell.setChecked(False)
            self._chk_ask_shell.setEnabled(False)
            g.addWidget(
                self._hint(
                    "Steam Deck builds start in Portable. Desktop is available "
                    "here if you want it. Applies next launch."
                )
            )
        else:
            g.addWidget(self._chk_ask_shell)
            g.addWidget(self._hint("Applies the next time Steempeg starts."))

        restart_row = QHBoxLayout()
        restart_row.setSpacing(8)
        restart_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        btn_restart = QPushButton("Restart app")
        btn_restart.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_restart.clicked.connect(self._restart_app)
        restart_row.addWidget(btn_restart, 0, Qt.AlignmentFlag.AlignVCenter)
        restart_row.addWidget(
            self._hint("Quit and relaunch. Use after changing shell."),
            1,
            Qt.AlignmentFlag.AlignVCenter,
        )
        g.addLayout(restart_row)
        g.addStretch(1)
        tabs.addTab(_scroll_settings_tab(general), "General")

        # ----- Visual -----
        visual, v = _tab_page()
        v.addWidget(self._section("Theme"))
        theme_row = QHBoxLayout()
        theme_row.setSpacing(8)
        theme_lbl = QLabel("Theme")
        theme_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_ui_theme = QComboBox()
        for value, label in UI_THEME_LABELS:
            self._combo_ui_theme.addItem(label, value)
        cur_theme = normalize_ui_theme(settings.get(KEY_UI_THEME, UI_THEME_DEFAULT))
        self._committed_ui_theme = cur_theme
        tidx = self._combo_ui_theme.findData(cur_theme)
        self._combo_ui_theme.setCurrentIndex(max(0, tidx))
        theme_row.addWidget(theme_lbl)
        theme_row.addWidget(self._combo_ui_theme, 1)
        v.addLayout(theme_row)
        v.addWidget(
            self._hint(
                "Default matches the stock Steempeg look. TrueDark is a darker unified "
                "family. TrueDark OLED uses pure black shell and player canvas with "
                "slightly elevated cards. Save applies; Cancel keeps the last saved theme."
            )
        )

        v.addWidget(self._section("Game icons"))
        shape_row = QHBoxLayout()
        shape_row.setSpacing(8)
        shape_lbl = QLabel("Corner shape")
        shape_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_icon_shape = QComboBox()
        for value, label in ICON_SHAPE_LABELS:
            self._combo_icon_shape.addItem(label, value)
        cur_shape = normalize_icon_shape(
            settings.get(KEY_GAME_ICON_SHAPE, ICON_SHAPE_DEFAULT)
        )
        self._committed_icon_shape = cur_shape
        sidx = self._combo_icon_shape.findData(cur_shape)
        self._combo_icon_shape.setCurrentIndex(max(0, sidx))
        shape_row.addWidget(shape_lbl)
        shape_row.addWidget(self._combo_icon_shape, 1)
        v.addLayout(shape_row)
        v.addWidget(
            self._hint(
                "Square · Soft (Steam-like, default) · Circle. "
                "Applies to Clips list/grid, Rendered, queue cards, and headers. "
                "Combo previews live; Save persists. Cancel restores "
                "the last saved shape."
            )
        )
        self._icon_shape_preview_timer = QTimer(self)
        self._icon_shape_preview_timer.setSingleShot(True)
        self._icon_shape_preview_timer.setInterval(200)
        self._icon_shape_preview_timer.timeout.connect(self._apply_icon_shape_preview)
        self._combo_icon_shape.currentIndexChanged.connect(self._preview_icon_shape)

        v.addWidget(self._section("Library cards"))
        card_row = QHBoxLayout()
        card_row.setSpacing(8)
        card_lbl = QLabel("ClipCard style")
        card_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_clip_card_style = QComboBox()
        for value, label in CARD_STYLE_LABELS:
            self._combo_clip_card_style.addItem(label, value)
        migrate_clip_card_style_in_settings(settings)
        cur_card = normalize_clip_card_style(
            settings.get(KEY_CLIP_CARD_STYLE, get_clip_card_style())
        )
        self._committed_clip_card_style = cur_card
        csidx = self._combo_clip_card_style.findData(cur_card)
        self._combo_clip_card_style.setCurrentIndex(max(0, csidx))
        card_row.addWidget(card_lbl)
        card_row.addWidget(self._combo_clip_card_style, 1)
        v.addLayout(card_row)
        v.addWidget(
            self._hint(
                "SteempegUI (default: shelf — flat top on first row, flat bottom on last; "
                "middle rows fully round) · Square (square top, round bottom on every card) · "
                "Round (round top and bottom everywhere). "
                "Applies to Clips Manager, Rendered videos, and Choose a Clip. "
                "Combo previews live; Save persists. Cancel restores "
                "the last saved style."
            )
        )
        self._clip_card_style_preview_timer = QTimer(self)
        self._clip_card_style_preview_timer.setSingleShot(True)
        self._clip_card_style_preview_timer.setInterval(200)
        self._clip_card_style_preview_timer.timeout.connect(self._apply_clip_card_style_preview)
        self._combo_clip_card_style.currentIndexChanged.connect(self._preview_clip_card_style)

        v.addWidget(self._section("Player header"))
        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        header_lbl = QLabel("Layout")
        header_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_header_layout = QComboBox()
        for value, label in HEADER_LAYOUT_LABELS:
            self._combo_header_layout.addItem(label, value)
        cur_header = normalize_header_layout(
            settings.get(KEY_PLAYER_HEADER_LAYOUT, HEADER_LAYOUT_DEFAULT)
        )
        self._committed_header_layout = cur_header
        hidx = self._combo_header_layout.findData(cur_header)
        self._combo_header_layout.setCurrentIndex(max(0, hidx))
        header_row.addWidget(header_lbl)
        header_row.addWidget(self._combo_header_layout, 1)
        v.addLayout(header_row)
        v.addWidget(
            self._hint(
                "Steam-like (default): centered logo + game name; date/duration only in the "
                "info (i) tip. SteempegUI: left-aligned title with date/time and duration. "
                "Combo previews live; Save persists. "
                "Cancel restores the last saved layout."
            )
        )
        self._header_layout_preview_timer = QTimer(self)
        self._header_layout_preview_timer.setSingleShot(True)
        self._header_layout_preview_timer.setInterval(200)
        self._header_layout_preview_timer.timeout.connect(self._apply_header_layout_preview)
        self._combo_header_layout.currentIndexChanged.connect(self._preview_header_layout)

        header_size_row = QHBoxLayout()
        header_size_row.setSpacing(8)
        header_size_lbl = QLabel("Size")
        header_size_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_header_size = QComboBox()
        for value, label in PLAYER_HEADER_SIZE_LABELS:
            self._combo_header_size.addItem(label, value)
        migrate_player_header_size_in_settings(settings)
        cur_header_size = normalize_player_header_size(
            settings.get(KEY_PLAYER_HEADER_SIZE, get_player_header_size())
        )
        self._committed_header_size = cur_header_size
        hsidx = self._combo_header_size.findData(cur_header_size)
        self._combo_header_size.setCurrentIndex(max(0, hsidx))
        header_size_row.addWidget(header_size_lbl)
        header_size_row.addWidget(self._combo_header_size, 1)
        v.addLayout(header_size_row)
        v.addWidget(
            self._hint(
                "Mostly height, padding, and chips of the upper player header "
                "(game title / Select a clip chrome, status chips, queue badges); "
                "same typeface at all sizes (mild size only). "
                "Small / Medium / Large — Large is the stock default "
                "(pre-pref height). "
                "Works with window density; empty and filled stay the same height. "
                "Combo previews live; Save persists. Cancel restores "
                "the last saved size."
            )
        )
        self._header_size_preview_timer = QTimer(self)
        self._header_size_preview_timer.setSingleShot(True)
        self._header_size_preview_timer.setInterval(200)
        self._header_size_preview_timer.timeout.connect(self._apply_header_size_preview)
        self._combo_header_size.currentIndexChanged.connect(self._preview_header_size)

        v.addWidget(self._section("Player layout"))
        player_layout_row = QHBoxLayout()
        player_layout_row.setSpacing(8)
        player_layout_lbl = QLabel("Layout")
        player_layout_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_player_layout = QComboBox()
        for value, label in PLAYER_LAYOUT_LABELS:
            self._combo_player_layout.addItem(label, value)
        cur_player_layout = normalize_player_layout(
            settings.get(KEY_PLAYER_LAYOUT, PLAYER_LAYOUT_DEFAULT)
        )
        self._committed_player_layout = cur_player_layout
        plidx = self._combo_player_layout.findData(cur_player_layout)
        self._combo_player_layout.setCurrentIndex(max(0, plidx))
        player_layout_row.addWidget(player_layout_lbl)
        player_layout_row.addWidget(self._combo_player_layout, 1)
        v.addLayout(player_layout_row)
        v.addWidget(
            self._hint(
                "Reunited: unified flush player stack (header, canvas, footer). "
                "Fractured: separated panels with visible gaps between header, "
                "video, and controls. Combo previews live; Save persists. "
                "Cancel restores the last saved layout."
            )
        )
        self._player_layout_preview_timer = QTimer(self)
        self._player_layout_preview_timer.setSingleShot(True)
        self._player_layout_preview_timer.setInterval(200)
        self._player_layout_preview_timer.timeout.connect(self._apply_player_layout_preview)
        self._combo_player_layout.currentIndexChanged.connect(self._preview_player_layout)

        v.addWidget(self._section("Player timeline"))
        strip_row = QHBoxLayout()
        strip_row.setSpacing(8)
        strip_lbl = QLabel("Strip size")
        strip_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_timeline_strip = QComboBox()
        for value, label in TIMELINE_STRIP_LABELS:
            self._combo_timeline_strip.addItem(label, value)
        migrate_timeline_strip_size_in_settings(settings)
        cur_strip = normalize_timeline_strip_size(
            settings.get(KEY_TIMELINE_STRIP_SIZE, get_timeline_strip_size())
        )
        self._committed_timeline_strip = cur_strip
        tsidx = self._combo_timeline_strip.findData(cur_strip)
        self._combo_timeline_strip.setCurrentIndex(max(0, tsidx))
        strip_row.addWidget(strip_lbl)
        strip_row.addWidget(self._combo_timeline_strip, 1)
        v.addLayout(strip_row)
        v.addWidget(
            self._hint(
                "Time labels and tick marks under the scrubber. "
                "Small / Medium / Large — Large is the stock default "
                "(full-size ruler). The progress track stays the same "
                "height. Same typeface at all sizes. "
                "Combo previews live; Save persists. Cancel restores "
                "the last saved size."
            )
        )
        self._timeline_strip_preview_timer = QTimer(self)
        self._timeline_strip_preview_timer.setSingleShot(True)
        self._timeline_strip_preview_timer.setInterval(200)
        self._timeline_strip_preview_timer.timeout.connect(self._apply_timeline_strip_preview)
        self._combo_timeline_strip.currentIndexChanged.connect(self._preview_timeline_strip)

        v.addWidget(self._section("Player controls"))
        vol_row = QHBoxLayout()
        vol_row.setSpacing(8)
        vol_lbl = QLabel("Volume ceiling")
        vol_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_volume_ceiling = QComboBox()
        for value, label in VOLUME_CEILING_LABELS:
            self._combo_volume_ceiling.addItem(label, value)
        cur_vol = normalize_volume_boost_ceiling(
            settings.get(KEY_VOLUME_BOOST_CEILING, get_volume_boost_ceiling())
        )
        self._committed_volume_ceiling = cur_vol
        vidx = self._combo_volume_ceiling.findData(cur_vol)
        self._combo_volume_ceiling.setCurrentIndex(max(0, vidx))
        vol_row.addWidget(vol_lbl)
        vol_row.addWidget(self._combo_volume_ceiling, 1)
        v.addLayout(vol_row)

        spd_row = QHBoxLayout()
        spd_row.setSpacing(8)
        spd_lbl = QLabel("Speed ceiling")
        spd_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_speed_ceiling = QComboBox()
        for value, label in SPEED_CEILING_LABELS:
            self._combo_speed_ceiling.addItem(label, value)
        cur_spd = normalize_speed_boost_ceiling(
            settings.get(KEY_SPEED_BOOST_CEILING, get_speed_boost_ceiling())
        )
        self._committed_speed_ceiling = cur_spd
        sidx = self._combo_speed_ceiling.findData(cur_spd)
        self._combo_speed_ceiling.setCurrentIndex(max(0, sidx))
        spd_row.addWidget(spd_lbl)
        spd_row.addWidget(self._combo_speed_ceiling, 1)
        v.addLayout(spd_row)
        v.addWidget(
            self._hint(
                "Optional boost above the normal player caps. "
                "Volume default is 100% (unity); choose 150%–500% to soft-amp louder. "
                "Speed default is 5.0x; choose 8.0x or 10.0x to extend the slider. "
                "Combo previews live; Save persists. Cancel restores the last saved ceilings."
            )
        )
        self._player_boost_preview_timer = QTimer(self)
        self._player_boost_preview_timer.setSingleShot(True)
        self._player_boost_preview_timer.setInterval(200)
        self._player_boost_preview_timer.timeout.connect(self._apply_player_boost_preview)
        self._combo_volume_ceiling.currentIndexChanged.connect(self._preview_player_boost)
        self._combo_speed_ceiling.currentIndexChanged.connect(self._preview_player_boost)

        v.addWidget(self._section("Date & time"))
        date_row = QHBoxLayout()
        date_row.setSpacing(8)
        date_lbl = QLabel("Date format")
        date_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_date_format = QComboBox()
        for value, label in DATE_FORMAT_LABELS:
            self._combo_date_format.addItem(label, value)
        cur_date = load_date_format(settings)
        didx = self._combo_date_format.findData(cur_date)
        self._combo_date_format.setCurrentIndex(max(0, didx))
        date_row.addWidget(date_lbl)
        date_row.addWidget(self._combo_date_format, 1)
        v.addLayout(date_row)

        clock_row = QHBoxLayout()
        clock_row.setSpacing(8)
        clock_lbl = QLabel("Clock")
        clock_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_clock_format = QComboBox()
        for value, label in CLOCK_FORMAT_LABELS:
            self._combo_clock_format.addItem(label, value)
        cur_clock = load_clock_format(settings)
        cidx = self._combo_clock_format.findData(cur_clock)
        self._combo_clock_format.setCurrentIndex(max(0, cidx))
        clock_row.addWidget(clock_lbl)
        clock_row.addWidget(self._combo_clock_format, 1)
        v.addLayout(clock_row)

        tz_row = QHBoxLayout()
        tz_row.setSpacing(8)
        tz_lbl = QLabel("Timezone")
        tz_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_timezone = QComboBox()
        for value, label in DISPLAY_TIMEZONE_LABELS:
            self._combo_timezone.addItem(label, value)
        cur_tz = load_display_timezone(settings)
        tidx = self._combo_timezone.findData(cur_tz)
        if tidx < 0 and cur_tz != TZ_SYSTEM:
            self._combo_timezone.addItem(cur_tz, cur_tz)
            tidx = self._combo_timezone.findData(cur_tz)
        self._combo_timezone.setCurrentIndex(max(0, tidx))
        tz_row.addWidget(tz_lbl)
        tz_row.addWidget(self._combo_timezone, 1)
        v.addLayout(tz_row)
        v.addWidget(
            self._hint(
                "Queue, library, filters, and render history. "
                "Named timezones use Qt IANA data. "
                "Save updates date labels instantly, with no library reload."
            )
        )

        v.addWidget(self._section("Markers"))
        self._chk_markers_on_strip = SteempegCheckBox("Markers on the strip")
        cur_on_strip = load_markers_on_strip(settings)
        self._committed_markers_on_strip = cur_on_strip
        self._chk_markers_on_strip.setChecked(cur_on_strip)
        self._chk_markers_on_strip.toggled.connect(self._preview_markers_on_strip)
        v.addWidget(self._chk_markers_on_strip)
        v.addWidget(
            self._hint(
                "Optional: draw kill/round icons on the purple seekbar "
                "(v20-style) instead of the row above. Saves vertical space "
                "on small screens. Off by default. Hover shows a tooltip; "
                "Ctrl+click jumps to a marker so scrubbing stays free."
            )
        )
        trim_row = QHBoxLayout()
        trim_row.setSpacing(8)
        trim_lbl = QLabel("Trim from marker")
        trim_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_marker_trim = QComboBox()
        for value, label in MARKER_TRIM_LABELS:
            self._combo_marker_trim.addItem(label, value)
        cur_trim = load_marker_trim_offset_ms(settings)
        tridx = self._combo_marker_trim.findData(cur_trim)
        self._combo_marker_trim.setCurrentIndex(max(0, tridx))
        trim_row.addWidget(trim_lbl)
        trim_row.addWidget(self._combo_marker_trim, 1)
        v.addLayout(trim_row)
        v.addWidget(
            self._hint(
                "When setting trim start from a marker: Exact snaps to the mark; "
                "lead-in starts 1s or 2s earlier."
            )
        )

        v.addStretch(1)
        tabs.addTab(_scroll_settings_tab(visual), "Visual")

        # ----- Notifications -----
        notify, n = _tab_page()
        n.addWidget(self._section("Notifications"))
        self._chk_notify = SteempegCheckBox("Notify when render finishes or fails")
        self._chk_notify.setChecked(
            bool(settings.get(KEY_NOTIFY_ON_RENDER_COMPLETE, True))
        )
        n.addWidget(self._chk_notify)
        n.addWidget(
            self._hint(
                "When Steempeg is minimized: OS notification center toast + "
                "system alert sound (Windows / Linux / SteamOS). Off = silent."
            )
        )
        n.addStretch(1)
        tabs.addTab(_scroll_settings_tab(notify), "Notifications")

        # ----- Performance -----
        perf, p = _tab_page()
        p.addWidget(self._section("Performance"))
        prio_row = QHBoxLayout()
        prio_row.setSpacing(8)
        prio_lbl = QLabel("Priority while rendering")
        prio_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_priority = QComboBox()
        for value, label in _PRIORITY_LABELS:
            self._combo_priority.addItem(label, value)
        cur_prio = str(settings.get(KEY_RENDER_PROCESS_PRIORITY, PRIORITY_NORMAL))
        pidx = self._combo_priority.findData(cur_prio)
        self._combo_priority.setCurrentIndex(max(0, pidx))
        prio_row.addWidget(prio_lbl)
        prio_row.addWidget(self._combo_priority, 1)
        p.addLayout(prio_row)

        self._chk_pause_preview = SteempegCheckBox("Pause preview while rendering")
        self._chk_pause_preview.setChecked(
            bool(settings.get(KEY_PAUSE_PREVIEW_DURING_RENDER, False))
        )
        p.addWidget(self._chk_pause_preview)
        p.addWidget(self._hint("Keeps CPU/GPU freer for FFmpeg. Off by default."))

        p.addWidget(self._section("Library startup"))
        scan_row = QHBoxLayout()
        scan_row.setSpacing(8)
        scan_lbl = QLabel("On launch")
        scan_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_startup_scan = QComboBox()
        for value, label in STARTUP_SCAN_LABELS:
            self._combo_startup_scan.addItem(label, value)
        cur_scan = load_startup_library_scan(settings)
        scidx = self._combo_startup_scan.findData(cur_scan)
        self._combo_startup_scan.setCurrentIndex(max(0, scidx))
        scan_row.addWidget(scan_lbl)
        scan_row.addWidget(self._combo_startup_scan, 1)
        p.addLayout(scan_row)
        p.addWidget(
            self._hint(
                "Quick rescans folders using cached health (default). "
                "Full re-runs ffprobe. "
                "Skip paints last session’s list instantly (no folder I/O). "
                "Refresh rebuilds the whole library."
            )
        )

        p.addWidget(self._section("Media cache"))
        cache_row = QHBoxLayout()
        cache_row.setSpacing(8)
        cache_lbl = QLabel("Size limit")
        cache_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_cache_limit = QComboBox()
        for value, label in MEDIA_CACHE_LIMIT_LABELS:
            self._combo_cache_limit.addItem(label, value)
        cur_cache = load_media_cache_limit_gb(settings)
        caidx = self._combo_cache_limit.findData(cur_cache)
        self._combo_cache_limit.setCurrentIndex(max(0, caidx))
        cache_row.addWidget(cache_lbl)
        cache_row.addWidget(self._combo_cache_limit, 1)
        p.addLayout(cache_row)
        p.addWidget(
            self._hint(
                "Caps clip posters, rendered posters, and remux leftovers. "
                "Oldest files prune first. Deleting a clip also purges its cache."
            )
        )

        p.addStretch(1)
        tabs.addTab(_scroll_settings_tab(perf), "Performance")

        # ----- Support -----
        support, s = _tab_page()
        s.addWidget(self._section("Hints"))
        hints_row = QHBoxLayout()
        hints_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        hints_row.addWidget(
            self._hint("Restore dismissed «Don't show again» dialogs."),
            1,
            Qt.AlignmentFlag.AlignVCenter,
        )
        btn_reset_hints = QPushButton("Reset all")
        btn_reset_hints.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset_hints.clicked.connect(self._reset_hints)
        hints_row.addWidget(btn_reset_hints, 0, Qt.AlignmentFlag.AlignVCenter)
        s.addLayout(hints_row)
        self._hints_status = QLabel("")
        self._hints_status.setStyleSheet(_HINT)
        s.addWidget(self._hints_status)

        s.addWidget(self._section("Logs / support"))
        support_row = QHBoxLayout()
        support_row.setSpacing(8)
        btn_logs = QPushButton("Open logs folder")
        btn_logs.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_logs.clicked.connect(self._open_logs)
        btn_cache = QPushButton("Clear cache…")
        btn_cache.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cache.clicked.connect(self._clear_cache)
        support_row.addWidget(btn_logs)
        support_row.addWidget(btn_cache)
        support_row.addStretch(1)
        s.addLayout(support_row)

        s.addWidget(self._section("Log levels"))
        for attr, label, loader, _default in (
            ("_combo_app_log", "App", load_app_log_level, DEFAULT_APP_LOG_LEVEL),
            ("_combo_ffmpeg_log", "FFmpeg", load_ffmpeg_log_level, DEFAULT_FFMPEG_LOG_LEVEL),
            ("_combo_mpv_log", "MPV", load_mpv_log_level, DEFAULT_MPV_LOG_LEVEL),
        ):
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(label)
            lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
            combo = QComboBox()
            for value, text in LOG_LEVEL_LABELS:
                combo.addItem(text, value)
            cur = loader(settings)
            idx = combo.findData(cur)
            combo.setCurrentIndex(max(0, idx))
            setattr(self, attr, combo)
            row.addWidget(lbl)
            row.addWidget(combo, 1)
            s.addLayout(row)
        s.addWidget(
            self._hint(
                "App applies immediately. FFmpeg on the next encode/thumb. "
                "MPV on the next player create / app restart."
            )
        )

        import_row = QHBoxLayout()
        import_row.setSpacing(8)
        import_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        import_row.addWidget(
            self._hint(
                "Pull rendered videos, Screenshots, and cache from an "
                "old_version backup (skips files that already exist)."
            ),
            1,
            Qt.AlignmentFlag.AlignVCenter,
        )
        btn_import = QPushButton("Import from backup…")
        btn_import.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_import.clicked.connect(self._import_from_backup)
        import_row.addWidget(btn_import, 0, Qt.AlignmentFlag.AlignVCenter)
        s.addLayout(import_row)
        self._import_status = QLabel("")
        self._import_status.setWordWrap(True)
        self._import_status.setStyleSheet(_HINT)
        s.addWidget(self._import_status)
        s.addStretch(1)
        tabs.addTab(_scroll_settings_tab(support), "Support")

        # ----- Advanced -----
        advanced, a = _tab_page()
        a.addWidget(self._section("Fullscreen"))
        self._chk_test_new_fullscreen = SteempegCheckBox(
            "TEST NEW FULLSCREEN, no grey flash on enter/exit",
            font_size=13,
            label_bold=True,
            label_color="#ffffff",
        )
        self._chk_test_new_fullscreen.setChecked(load_test_new_fullscreen(settings))
        a.addWidget(self._chk_test_new_fullscreen)
        loud_hint = QLabel(
            "If the old grey screen before enter/exit bothers you, turn this on. "
            "Skips the transition cover (same as STEEMPEG_FS_COVER=0). "
            "May briefly show a black edge on exit."
        )
        loud_hint.setWordWrap(True)
        loud_hint.setStyleSheet(
            f"color: {tok.TEXT_TITLE}; font-size: 12px; font-weight: bold; "
            f"background: transparent; font-family: {tok.FONT_APP};"
        )
        a.addWidget(loud_hint)

        a.addWidget(self._section("Safety"))
        self._chk_confirm_delete = SteempegCheckBox("Confirm before deleting clips / renders")
        self._chk_confirm_delete.setChecked(load_confirm_before_delete(settings))
        a.addWidget(self._chk_confirm_delete)

        a.addWidget(self._section("Library"))
        self._chk_remember_tab = SteempegCheckBox("Remember last library tab")
        self._chk_remember_tab.setChecked(load_remember_library_tab(settings))
        a.addWidget(self._chk_remember_tab)
        a.addWidget(
            self._hint("Off = always open Clips Manager. On = restore Clips / Rendered.")
        )

        a.addWidget(self._section("Screenshots"))
        shot_row = QHBoxLayout()
        shot_row.setSpacing(8)
        self._edit_screenshots = QLineEdit()
        self._edit_screenshots.setPlaceholderText(default_screenshots_dir())
        self._edit_screenshots.setText(resolve_screenshots_folder(settings))
        btn_browse_shots = QPushButton("Browse…")
        btn_browse_shots.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse_shots.clicked.connect(self._browse_screenshots_folder)
        btn_reset_shots = QPushButton("Reset")
        btn_reset_shots.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset_shots.clicked.connect(self._reset_screenshots_folder)
        shot_row.addWidget(self._edit_screenshots, 1)
        shot_row.addWidget(btn_browse_shots, 0)
        shot_row.addWidget(btn_reset_shots, 0)
        a.addLayout(shot_row)
        a.addWidget(self._hint("Player screenshots save here (PNG)."))

        a.addWidget(self._section("Preview decode"))
        hw_row = QHBoxLayout()
        hw_row.setSpacing(8)
        hw_lbl = QLabel("Hardware decode")
        hw_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_hwdec = QComboBox()
        for value, label in HWDEC_LABELS:
            self._combo_hwdec.addItem(label, value)
        cur_hw = load_hwdec_preview(settings)
        hwidx = self._combo_hwdec.findData(cur_hw)
        self._combo_hwdec.setCurrentIndex(max(0, hwidx))
        hw_row.addWidget(hw_lbl)
        hw_row.addWidget(self._combo_hwdec, 1)
        a.addLayout(hw_row)
        a.addWidget(
            self._hint(
                "MPV hwdec for preview. Applies on next player create / restart. "
                "Off if hardware decode glitches."
            )
        )
        a.addStretch(1)
        tabs.addTab(_scroll_settings_tab(advanced), "Advanced")

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("Save")
        btn_save.setObjectName("settingsPrimaryBtn")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setStyleSheet(_BTN_PRIMARY)
        btn_save.clicked.connect(self._save)
        actions.addWidget(btn_cancel)
        actions.addWidget(btn_save)
        root.addLayout(actions)

        # Wheel over closed combos/spins must scroll the tab, not change values.
        from steempeg.ui.widgets.no_wheel_filter import install_no_wheel_value_filter

        install_no_wheel_value_filter(self)

        self._apply_settings_form_chrome()

        # Content can inflate sizeHint during build — re-cap before first map/center.
        self._apply_settings_geometry()

    def _apply_settings_geometry(self) -> None:
        """Comfort design size, capped so the shell stays on-screen and centerable."""
        from steempeg.ui.ui_density import scaled_dialog_size

        parent = self.parentWidget()
        w, h = scaled_dialog_size(
            _SETTINGS_DESIGN_W, _SETTINGS_DESIGN_H, parent=parent
        )
        max_h = _settings_max_height(parent)
        target_h = min(h, max_h)
        self.setMaximumHeight(max_h)
        self.setMinimumHeight(min(_SETTINGS_MIN_H, target_h))
        self._map_w = w
        self._map_h = target_h
        self.resize(w, target_h)

    def _prepare_geometry_before_map(self) -> None:
        # Re-apply cap + exact parent center on every open (before DWM maps us).
        self._apply_settings_geometry()
        self.ensurePolished()
        self._center_on_parent()

    def _center_on_parent(self) -> None:
        """Dead-center on the Steempeg main window using the capped map size."""
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication, QWidget

        ref: QWidget | None = None
        parent = self.parentWidget()
        if isinstance(parent, QWidget) and parent.isVisible():
            ref = parent.window() if parent.window() is not None else parent
        if ref is None:
            aw = QApplication.activeWindow()
            if isinstance(aw, QWidget):
                ref = aw

        dw = max(int(getattr(self, "_map_w", 0) or self.width() or 1), 1)
        dh = max(int(getattr(self, "_map_h", 0) or self.height() or 1), 1)

        if ref is not None and ref.isVisible():
            origin = ref.mapToGlobal(QPoint(0, 0))
            rw, rh = max(ref.width(), 1), max(ref.height(), 1)
            x = origin.x() + (rw - dw) // 2
            y = origin.y() + (rh - dh) // 2
            # If somehow still taller/wider than the host, pin to the host origin
            # rather than drifting with negative half-deltas.
            if dw > rw:
                x = origin.x()
            if dh > rh:
                y = origin.y()
        else:
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                return
            avail = screen.availableGeometry()
            x = avail.x() + (avail.width() - dw) // 2
            y = avail.y() + (avail.height() - dh) // 2

        screen = None
        if ref is not None:
            screen = QGuiApplication.screenAt(ref.mapToGlobal(ref.rect().center()))
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            x = max(avail.x(), min(x, avail.x() + max(0, avail.width() - dw)))
            y = max(avail.y(), min(y, avail.y() + max(0, avail.height() - dh)))
        self.move(x, y)

    @staticmethod
    def _section(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_SECTION)
        return lbl

    @staticmethod
    def _hint(text: str) -> QWidget:
        """Muted helper line with circled info icon, optically centered on the text."""
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        # Prefer intrinsic height so a button row cannot stretch the icon to the top.
        row.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum
        )
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(_HINT)
        font = QFont()
        font.setFamilies(["Segoe UI", "Noto Sans", "Arial"])
        font.setPointSize(11)
        lbl.setFont(font)
        line_h = max(QFontMetrics(font).height(), 14)

        icon_sz = 12
        icon_lbl = QLabel()
        # Slot = one text line so the glyph sits on the same center as the first line.
        icon_lbl.setFixedSize(icon_sz, line_h)
        icon_lbl.setStyleSheet("background: transparent; border: none; padding: 0;")
        pix = title_bar_info_pixmap(tok.TEXT_MUTED, icon_sz)
        if pix is not None and not pix.isNull():
            icon_lbl.setPixmap(pix)
        icon_lbl.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
        )

        lay.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(lbl, 1, Qt.AlignmentFlag.AlignTop)
        lay.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        row._hint_label = lbl  # type: ignore[attr-defined]
        return row

    @staticmethod
    def _set_hint_text(hint_widget: QWidget, text: str) -> None:
        lbl = getattr(hint_widget, "_hint_label", None)
        if isinstance(lbl, QLabel):
            lbl.setText(text)
        elif isinstance(hint_widget, QLabel):
            hint_widget.setText(text)

    def _save_setting(self, key: str, value) -> None:
        if hasattr(self._app, "save_user_settings"):
            self._app.save_user_settings(key, value)

    def _browse_export_folder(self) -> None:
        start = normalize_export_folder(self._edit_export_folder.text()) or default_export_dir()
        folder = QFileDialog.getExistingDirectory(
            self, "Select export folder", start
        )
        if not folder:
            return
        folder = normalize_export_folder(folder)
        self._edit_export_folder.setText(folder)
        self._refresh_export_folder_hint()
        if is_outside_default_rendered(folder):
            steempeg_information(
                self,
                "Custom export folder",
                "This folder is outside the default rendered_videos library.\n\n"
                "Exports still work. The Rendered tab keeps scanning this path "
                "while it is set, but «Open in Steempeg» after render is limited "
                "to files inside rendered_videos.",
            )

    def _reset_export_folder(self) -> None:
        self._edit_export_folder.setText(default_export_dir())
        self._refresh_export_folder_hint()

    def _browse_screenshots_folder(self) -> None:
        start = normalize_screenshots_folder(
            self._edit_screenshots.text()
        ) or default_screenshots_dir()
        folder = QFileDialog.getExistingDirectory(
            self, "Select screenshots folder", start
        )
        if not folder:
            return
        self._edit_screenshots.setText(normalize_screenshots_folder(folder))

    def _reset_screenshots_folder(self) -> None:
        self._edit_screenshots.setText(default_screenshots_dir())

    def _refresh_export_folder_hint(self) -> None:
        folder = normalize_export_folder(self._edit_export_folder.text()) or default_export_dir()
        if is_outside_default_rendered(folder):
            self._set_hint_text(
                self._export_folder_hint,
                "Outside rendered_videos: exports OK; Rendered library still "
                "scans this path, but «Open in Steempeg» may be limited.",
            )
        else:
            self._set_hint_text(
                self._export_folder_hint,
                "Permanent output folder for exports. Save syncs the Export "
                "panel. Reset returns to the default rendered_videos folder.",
            )

    def _reset_hints(self) -> None:
        for key in HINT_DISMISS_KEYS:
            self._save_setting(key, False)
        # Refresh live empty-queue panels if present.
        panel = getattr(self._app, "render_queue_panel", None)
        if panel is not None and hasattr(panel, "set_empty_hint_dismissed"):
            panel.set_empty_hint_dismissed(False)
        self._hints_status.setText("Dismissed hints restored.")

    def _open_logs(self) -> None:
        if hasattr(self._app, "open_logs_folder"):
            self._app.open_logs_folder()

    def _clear_cache(self) -> None:
        if hasattr(self._app, "confirm_clear_cache"):
            self._app.confirm_clear_cache()

    def _import_from_backup(self) -> None:
        """Merge user data from an ``old_version_v*`` folder into the live install."""
        from steempeg.infra.paths import get_install_root
        from steempeg.services.backup_import import import_user_data_from_backup
        from steempeg.services.release_catalog import find_local_backups

        root = get_install_root()
        backups = find_local_backups(root)
        if not backups:
            steempeg_warning(
                self,
                "No backups found",
                "No old_version_v… folders next to Steempeg.\n"
                "Keep a backup when updating to create one.",
            )
            self._import_status.setText("No local backups found.")
            return

        labels = [f"v{b.version_str}  ({b.folder_name})" for b in backups]
        chosen, ok = QInputDialog.getItem(
            self,
            "Import from backup",
            "Choose a local backup to copy from:",
            labels,
            0,
            False,
        )
        if not ok or not chosen:
            return
        backup = backups[labels.index(chosen)]

        if not steempeg_question(
            self,
            "Import from backup?",
            f"Copy missing files from {backup.folder_name} into the current install?\n\n"
            "Folders: rendered_videos, Screenshots, cache.\n"
            "Existing files are left alone.",
        ):
            return

        result = import_user_data_from_backup(backup.path, root)
        if result.errors and result.copied_files == 0 and not result.folders_touched:
            steempeg_warning(
                self,
                "Import failed",
                "\n".join(result.errors[:6]),
            )
            self._import_status.setText("Import failed.")
            return

        folders = ", ".join(result.folders_touched) or "nothing to copy"
        msg = (
            f"Copied {result.copied_files} file(s), "
            f"skipped {result.skipped_existing} existing. "
            f"Touched: {folders}."
        )
        if result.errors:
            msg += f" ({len(result.errors)} error(s))"
        self._import_status.setText(msg)
        steempeg_information(self, "Import finished", msg)

        # Refresh rendered library if it is already built.
        if hasattr(self._app, "scan_rendered_outputs"):
            try:
                self._app.scan_rendered_outputs()
            except Exception:
                pass

    def _restart_app(self) -> None:
        from steempeg.ui.message_dialog import steempeg_question

        if not steempeg_question(
            self,
            "Restart Steempeg?",
            "Steempeg will quit and open again.",
            detail="Unsaved dialog choices in this window are discarded. Save first if needed.",
        ):
            return
        # Persist shell prefs before relaunch so Restart after a shell change works
        # even if the user forgot Save.
        shell = self._combo_shell.currentData()
        if shell in (UI_SHELL_DESKTOP, UI_SHELL_PORTABLE):
            save_ui_shell(shell)
        if getattr(self, "_chk_ask_shell", None) is not None and self._chk_ask_shell.isEnabled():
            save_ask_ui_shell(self._chk_ask_shell.isChecked())
        # Flush queue + panel before relaunch so the other shell sees the same state.
        app = self._app
        if hasattr(app, "_persist_render_queue"):
            try:
                app._persist_render_queue()
            except Exception:
                pass
        try:
            from steempeg.ui.portable.sheets import persist_render_settings

            persist_render_settings(app)
        except Exception:
            pass
        self.accept()
        from steempeg.ui.app_restart import restart_application

        restart_application(self._app)

    def _apply_settings_form_chrome(self) -> None:
        """Theme-aware combos, line edits, and secondary buttons across all tabs."""
        from steempeg.ui import ui_theme as ut
        from steempeg.ui.window_chrome import _TrafficLight

        combo_qss = ut.settings_dialog_combo_stylesheet()
        for combo in self.findChildren(QComboBox):
            combo.setStyleSheet(combo_qss)
            apply_dark_combo_popup(combo)

        edit_qss = ut.settings_dialog_line_edit_stylesheet()
        for edit in self.findChildren(QLineEdit):
            edit.setStyleSheet(edit_qss)

        sec_qss = ut.settings_dialog_secondary_button_stylesheet()
        for btn in self.findChildren(QPushButton):
            # Title-bar traffic lights are QPushButtons — never restyle them as
            # form secondary buttons (idle becomes a gray square outline; hover
            # re-applies the red circle via _TrafficLight._apply_style).
            if isinstance(btn, _TrafficLight):
                btn._apply_style()
                continue
            if btn.objectName() == "settingsPrimaryBtn":
                btn.setStyleSheet(_BTN_PRIMARY)
                continue
            btn.setStyleSheet(sec_qss)

    def apply_ui_theme_chrome(self) -> None:
        """Re-tint dialog shell + tab scroll areas after a Visual theme change."""
        from steempeg.ui import ui_theme as ut
        from steempeg.ui.library.library_styles import (
            LIBRARY_SCROLLBAR_VERTICAL,
            install_library_vertical_scrollbar,
        )

        super().apply_ui_theme_chrome()
        tabs = getattr(self, "_settings_tabs", None)
        if tabs is not None:
            tabs.setStyleSheet(ut.settings_dialog_tabs_stylesheet())
        bg = tok.BG_SHELL
        for scroll in self.findChildren(QScrollArea):
            inner = scroll.widget()
            if inner is not None:
                inner.setStyleSheet(f"background-color: {bg};")
            tok.apply_dialog_scroll_bg(scroll, bg)
            scroll.setStyleSheet(tok.dialog_scroll_stylesheet(bg) + LIBRARY_SCROLLBAR_VERTICAL)
            install_library_vertical_scrollbar(scroll)
        self._apply_settings_form_chrome()

    def _sync_portable_like_middle_splitter_enabled(self, *_args) -> None:
        chk = getattr(self, "_chk_portable_like_middle_splitter", None)
        combo = getattr(self, "_combo_desktop_render", None)
        if chk is None or combo is None:
            return
        portable = (
            normalize_desktop_render_layout(combo.currentData())
            == DESKTOP_RENDER_LIKE_A_PORTABLE
        )
        chk.setEnabled(portable)

    def _refresh_ui_theme(self, theme: str, *, preview: bool = False) -> None:
        if hasattr(self._app, "apply_ui_theme"):
            try:
                self._app.apply_ui_theme(theme, persist=False, preview=preview)
            except Exception:
                import logging

                logging.exception("UI theme refresh failed for %s", theme)
                return
        if preview:
            self.apply_ui_theme_chrome()

    def _restore_ui_theme_on_cancel(self) -> None:
        """No live theme preview — only restore if runtime drifted from saved."""
        import logging

        committed = normalize_ui_theme(
            getattr(self, "_committed_ui_theme", UI_THEME_DEFAULT)
        )
        live = get_ui_theme()
        combo = normalize_ui_theme(self._combo_ui_theme.currentData())
        if live == committed and combo == committed:
            return
        logging.info("UI theme cancelled → restored %s", committed)
        self._refresh_ui_theme(committed)

    def _preview_icon_shape(self, *_args) -> None:
        """Debounced live preview (not persisted until Save)."""
        self._icon_shape_preview_timer.start()

    def _apply_icon_shape_preview(self) -> None:
        import logging

        shape = normalize_icon_shape(self._combo_icon_shape.currentData())
        set_icon_shape(shape)
        logging.info("Icon shape preview → %s", shape)
        if hasattr(self._app, "refresh_game_icon_shapes"):
            try:
                self._app.refresh_game_icon_shapes(shape)
            except Exception:
                logging.exception("Icon shape preview refresh failed")

    def _refresh_icon_shapes(self, shape: str) -> None:
        if hasattr(self._app, "refresh_game_icon_shapes"):
            try:
                self._app.refresh_game_icon_shapes(shape)
            except Exception:
                import logging

                logging.exception("Icon shape refresh failed for %s", shape)

    def _preview_clip_card_style(self, *_args) -> None:
        self._clip_card_style_preview_timer.start()

    def _apply_clip_card_style_preview(self) -> None:
        import logging

        style = normalize_clip_card_style(self._combo_clip_card_style.currentData())
        set_clip_card_style(style)
        logging.info("ClipCard style preview → %s", style)
        self._refresh_clip_card_styles(style)

    def _refresh_clip_card_styles(self, style: str) -> None:
        if hasattr(self._app, "refresh_clip_card_styles"):
            try:
                self._app.refresh_clip_card_styles(style)
            except Exception:
                import logging

                logging.exception("ClipCard style refresh failed for %s", style)

    def _preview_header_layout(self, *_args) -> None:
        self._header_layout_preview_timer.start()

    def _apply_header_layout_preview(self) -> None:
        import logging

        layout = normalize_header_layout(self._combo_header_layout.currentData())
        set_header_layout(layout)
        logging.info("Player header layout preview → %s", layout)
        self._refresh_header_layout(layout)

    def _refresh_header_layout(self, layout: str) -> None:
        if hasattr(self._app, "refresh_player_header_layout"):
            try:
                self._app.refresh_player_header_layout(layout)
            except Exception:
                import logging

                logging.exception("Player header layout refresh failed for %s", layout)

    def _preview_header_size(self, *_args) -> None:
        self._header_size_preview_timer.start()

    def _apply_header_size_preview(self) -> None:
        import logging

        size = normalize_player_header_size(self._combo_header_size.currentData())
        set_player_header_size(size)
        logging.info("Player header size preview → %s", size)
        self._refresh_header_size(size)

    def _refresh_header_size(self, size: str) -> None:
        if hasattr(self._app, "refresh_player_header_size"):
            try:
                self._app.refresh_player_header_size(size)
            except Exception:
                import logging

                logging.exception("Player header size refresh failed for %s", size)

    def _preview_player_layout(self, *_args) -> None:
        self._player_layout_preview_timer.start()

    def _apply_player_layout_preview(self) -> None:
        import logging

        layout = normalize_player_layout(self._combo_player_layout.currentData())
        set_player_layout(layout)
        logging.info("Player layout preview → %s", layout)
        self._refresh_player_layout(layout)

    def _refresh_player_layout(self, layout: str) -> None:
        if hasattr(self._app, "refresh_player_layout_mode"):
            try:
                self._app.refresh_player_layout_mode(layout)
            except Exception:
                import logging

                logging.exception("Player layout refresh failed for %s", layout)

    def _preview_timeline_strip(self, *_args) -> None:
        self._timeline_strip_preview_timer.start()

    def _apply_timeline_strip_preview(self) -> None:
        import logging

        size = normalize_timeline_strip_size(self._combo_timeline_strip.currentData())
        set_timeline_strip_size(size)
        logging.info("Timeline strip size preview → %s", size)
        self._refresh_timeline_strip(size)

    def _refresh_timeline_strip(self, size: str) -> None:
        if hasattr(self._app, "refresh_timeline_strip_size"):
            try:
                self._app.refresh_timeline_strip_size(size)
            except Exception:
                import logging

                logging.exception("Timeline strip size refresh failed for %s", size)

    def _preview_markers_on_strip(self, *_args) -> None:
        enabled = bool(self._chk_markers_on_strip.isChecked())
        set_markers_on_strip(enabled)
        self._refresh_markers_on_strip(enabled)

    def _refresh_markers_on_strip(self, enabled: bool) -> None:
        if hasattr(self._app, "refresh_markers_on_strip"):
            try:
                self._app.refresh_markers_on_strip(enabled)
            except Exception:
                import logging

                logging.exception("Markers-on-strip refresh failed for %s", enabled)

    def _restore_markers_on_strip_on_cancel(self) -> None:
        """Undo live markers-on-strip preview that was never Saved."""
        committed = normalize_markers_on_strip(
            getattr(self, "_committed_markers_on_strip", DEFAULT_MARKERS_ON_STRIP)
        )
        live = normalize_markers_on_strip(self._chk_markers_on_strip.isChecked())
        if live == committed:
            return
        self._chk_markers_on_strip.blockSignals(True)
        self._chk_markers_on_strip.setChecked(committed)
        self._chk_markers_on_strip.blockSignals(False)
        set_markers_on_strip(committed)
        self._refresh_markers_on_strip(committed)

    def _preview_player_boost(self, *_args) -> None:
        self._player_boost_preview_timer.start()

    def _apply_player_boost_preview(self) -> None:
        import logging

        vol = normalize_volume_boost_ceiling(self._combo_volume_ceiling.currentData())
        spd = normalize_speed_boost_ceiling(self._combo_speed_ceiling.currentData())
        set_volume_boost_ceiling(vol)
        set_speed_boost_ceiling(spd)
        logging.info("Player boost preview → volume %s%% / speed %s", vol, spd)
        self._refresh_player_boost(vol, spd)

    def _refresh_player_boost(self, volume: int, speed: int) -> None:
        if hasattr(self._app, "refresh_player_boost_ceilings"):
            try:
                self._app.refresh_player_boost_ceilings(volume, speed)
            except Exception:
                import logging

                logging.exception(
                    "Player boost refresh failed for volume=%s speed=%s", volume, speed
                )

    def _restore_icon_shape_on_cancel(self) -> None:
        """Undo live preview mutations that were never Saved."""
        import logging

        if getattr(self, "_icon_shape_preview_timer", None) is not None:
            self._icon_shape_preview_timer.stop()
        committed = normalize_icon_shape(
            getattr(self, "_committed_icon_shape", ICON_SHAPE_DEFAULT)
        )
        live = get_icon_shape()
        combo = normalize_icon_shape(self._combo_icon_shape.currentData())
        if live == committed and combo == committed:
            return
        set_icon_shape(committed)
        logging.info("Icon shape cancelled → restored %s", committed)
        self._refresh_icon_shapes(committed)

    def _restore_clip_card_style_on_cancel(self) -> None:
        """Undo live ClipCard style preview that was never Saved."""
        import logging

        if getattr(self, "_clip_card_style_preview_timer", None) is not None:
            self._clip_card_style_preview_timer.stop()
        committed = normalize_clip_card_style(
            getattr(self, "_committed_clip_card_style", CARD_STYLE_DEFAULT)
        )
        live = get_clip_card_style()
        combo = normalize_clip_card_style(self._combo_clip_card_style.currentData())
        if live == committed and combo == committed:
            return
        set_clip_card_style(committed)
        logging.info("ClipCard style cancelled → restored %s", committed)
        self._refresh_clip_card_styles(committed)

    def _restore_header_layout_on_cancel(self) -> None:
        """Undo live header-layout preview that was never Saved."""
        import logging

        if getattr(self, "_header_layout_preview_timer", None) is not None:
            self._header_layout_preview_timer.stop()
        committed = normalize_header_layout(
            getattr(self, "_committed_header_layout", HEADER_LAYOUT_DEFAULT)
        )
        live = get_header_layout()
        combo = normalize_header_layout(self._combo_header_layout.currentData())
        if live == committed and combo == committed:
            return
        set_header_layout(committed)
        logging.info("Player header layout cancelled → restored %s", committed)
        self._refresh_header_layout(committed)

    def _restore_header_size_on_cancel(self) -> None:
        """Undo live player header size preview that was never Saved."""
        import logging

        if getattr(self, "_header_size_preview_timer", None) is not None:
            self._header_size_preview_timer.stop()
        committed = normalize_player_header_size(
            getattr(self, "_committed_header_size", PLAYER_HEADER_DEFAULT)
        )
        live = get_player_header_size()
        combo = normalize_player_header_size(self._combo_header_size.currentData())
        if live == committed and combo == committed:
            return
        set_player_header_size(committed)
        logging.info("Player header size cancelled → restored %s", committed)
        self._refresh_header_size(committed)

    def _restore_player_layout_on_cancel(self) -> None:
        """Undo live player layout preview that was never Saved."""
        import logging

        if getattr(self, "_player_layout_preview_timer", None) is not None:
            self._player_layout_preview_timer.stop()
        committed = normalize_player_layout(
            getattr(self, "_committed_player_layout", PLAYER_LAYOUT_DEFAULT)
        )
        live = get_player_layout()
        combo = normalize_player_layout(self._combo_player_layout.currentData())
        if live == committed and combo == committed:
            return
        set_player_layout(committed)
        logging.info("Player layout cancelled → restored %s", committed)
        self._refresh_player_layout(committed)

    def _restore_timeline_strip_on_cancel(self) -> None:
        """Undo live timeline strip size preview that was never Saved."""
        import logging

        if getattr(self, "_timeline_strip_preview_timer", None) is not None:
            self._timeline_strip_preview_timer.stop()
        committed = normalize_timeline_strip_size(
            getattr(self, "_committed_timeline_strip", TIMELINE_STRIP_DEFAULT)
        )
        live = get_timeline_strip_size()
        combo = normalize_timeline_strip_size(self._combo_timeline_strip.currentData())
        if live == committed and combo == committed:
            return
        set_timeline_strip_size(committed)
        logging.info("Timeline strip size cancelled → restored %s", committed)
        self._refresh_timeline_strip(committed)

    def _restore_player_boost_on_cancel(self) -> None:
        """Undo live volume/speed ceiling preview that was never Saved."""
        import logging

        if getattr(self, "_player_boost_preview_timer", None) is not None:
            self._player_boost_preview_timer.stop()
        committed_vol = normalize_volume_boost_ceiling(
            getattr(self, "_committed_volume_ceiling", VOLUME_CEILING_DEFAULT)
        )
        committed_spd = normalize_speed_boost_ceiling(
            getattr(self, "_committed_speed_ceiling", SPEED_CEILING_DEFAULT)
        )
        live_vol = get_volume_boost_ceiling()
        live_spd = get_speed_boost_ceiling()
        combo_vol = normalize_volume_boost_ceiling(
            self._combo_volume_ceiling.currentData()
        )
        combo_spd = normalize_speed_boost_ceiling(
            self._combo_speed_ceiling.currentData()
        )
        if (
            live_vol == committed_vol
            and live_spd == committed_spd
            and combo_vol == committed_vol
            and combo_spd == committed_spd
        ):
            return
        set_volume_boost_ceiling(committed_vol)
        set_speed_boost_ceiling(committed_spd)
        logging.info(
            "Player boost cancelled → restored volume %s%% / speed %s",
            committed_vol,
            committed_spd,
        )
        self._refresh_player_boost(committed_vol, committed_spd)

    def reject(self) -> None:
        self._restore_ui_theme_on_cancel()
        self._restore_icon_shape_on_cancel()
        self._restore_clip_card_style_on_cancel()
        self._restore_header_layout_on_cancel()
        self._restore_header_size_on_cancel()
        self._restore_player_layout_on_cancel()
        self._restore_timeline_strip_on_cancel()
        self._restore_markers_on_strip_on_cancel()
        self._restore_player_boost_on_cancel()
        super().reject()

    def _stop_visual_preview_timers(self) -> None:
        for attr in (
            "_icon_shape_preview_timer",
            "_clip_card_style_preview_timer",
            "_header_layout_preview_timer",
            "_header_size_preview_timer",
            "_player_layout_preview_timer",
            "_timeline_strip_preview_timer",
            "_player_boost_preview_timer",
        ):
            timer = getattr(self, attr, None)
            if timer is not None:
                timer.stop()

    def _persist_settings(self) -> list:
        """Write settings.json once; return deferred UI apply callbacks."""
        import logging
        import time

        deferred: list = []
        pending: dict = {}
        t0 = time.perf_counter()

        prev: dict = {}
        if hasattr(self._app, "load_user_settings"):
            try:
                prev = self._app.load_user_settings() or {}
            except Exception:
                prev = {}

        interval = normalize_update_check_interval(
            self._combo_update_interval.currentData()
        )
        pending[KEY_UPDATE_CHECK_INTERVAL] = interval

        requested = normalize_export_folder(self._edit_export_folder.text()) or default_export_dir()
        folder, fell_back = ensure_usable_export_folder(requested)
        if fell_back:
            notify_export_folder_fallback(
                self, requested, folder, use_dialog=True
            )
        pending[KEY_PERMANENT_EXPORT_FOLDER] = folder
        blob = prev.get("render_export_settings")
        if isinstance(blob, dict):
            export_blob = dict(blob)
            export_blob["save_dir"] = folder
            pending["render_export_settings"] = export_blob
        apply_export_folder(self._app, folder, persist=False)
        self._committed_export_folder = folder
        self._edit_export_folder.setText(folder)
        self._refresh_export_folder_hint()

        render_tab = normalize_render_tab(self._combo_render_tab.currentData())
        pending[KEY_DEFAULT_RENDER_TAB] = render_tab
        self._committed_render_tab = render_tab
        apply_default_render_tab(self._app, render_tab)

        desktop_layout = normalize_desktop_render_layout(
            self._combo_desktop_render.currentData()
        )
        pending[KEY_DESKTOP_RENDER_LAYOUT] = desktop_layout
        middle_splitter = normalize_portable_like_middle_splitter(
            self._chk_portable_like_middle_splitter.isChecked()
        )
        pending[KEY_PORTABLE_LIKE_MIDDLE_SPLITTER] = middle_splitter
        layout_apply = desktop_layout != getattr(
            self, "_committed_desktop_render", desktop_layout
        ) or middle_splitter != getattr(
            self, "_committed_portable_like_middle_splitter", middle_splitter
        )
        if layout_apply and hasattr(self._app, "apply_desktop_render_layout"):
            deferred.append(self._app.apply_desktop_render_layout)
        self._committed_desktop_render = desktop_layout
        self._committed_portable_like_middle_splitter = middle_splitter

        pending[KEY_NOTIFY_ON_RENDER_COMPLETE] = self._chk_notify.isChecked()
        pending[KEY_PAUSE_PREVIEW_DURING_RENDER] = self._chk_pause_preview.isChecked()
        prio = self._combo_priority.currentData()
        pending[KEY_RENDER_PROCESS_PRIORITY] = prio if prio else PRIORITY_NORMAL

        self._stop_visual_preview_timers()

        ui_theme = normalize_ui_theme(self._combo_ui_theme.currentData())
        pending[KEY_UI_THEME] = ui_theme
        opened_theme = normalize_ui_theme(
            getattr(self, "_committed_ui_theme", UI_THEME_DEFAULT)
        )
        live_theme = normalize_ui_theme(get_ui_theme())
        if ui_theme != live_theme:
            logging.info(
                "UI theme applied → %s (runtime was %s; settings.json)",
                ui_theme,
                live_theme,
            )
            deferred.append(lambda t=ui_theme: self._refresh_ui_theme(t))
        elif ui_theme != opened_theme:
            logging.info("UI theme persisted → %s (already live)", ui_theme)
        self._committed_ui_theme = ui_theme

        shape = normalize_icon_shape(self._combo_icon_shape.currentData())
        pending[KEY_GAME_ICON_SHAPE] = shape
        set_icon_shape(shape)
        if shape != self._committed_icon_shape:
            deferred.append(lambda s=shape: self._refresh_icon_shapes(s))
        self._committed_icon_shape = shape

        card_style = normalize_clip_card_style(self._combo_clip_card_style.currentData())
        pending[KEY_CLIP_CARD_STYLE] = card_style
        pending[KEY_CLIP_CARD_STYLE_REV] = CLIP_CARD_STYLE_REV_CURRENT
        set_clip_card_style(card_style)
        if card_style != self._committed_clip_card_style:
            deferred.append(lambda s=card_style: self._refresh_clip_card_styles(s))
        self._committed_clip_card_style = card_style

        header_layout = normalize_header_layout(self._combo_header_layout.currentData())
        pending[KEY_PLAYER_HEADER_LAYOUT] = header_layout
        set_header_layout(header_layout)
        if header_layout != self._committed_header_layout:
            deferred.append(lambda l=header_layout: self._refresh_header_layout(l))
        self._committed_header_layout = header_layout

        header_size = normalize_player_header_size(self._combo_header_size.currentData())
        pending[KEY_PLAYER_HEADER_SIZE] = header_size
        pending[KEY_PLAYER_HEADER_SIZE_REV] = PLAYER_HEADER_SIZE_REV_CURRENT
        set_player_header_size(header_size)
        if header_size != self._committed_header_size:
            deferred.append(lambda s=header_size: self._refresh_header_size(s))
        self._committed_header_size = header_size

        player_layout = normalize_player_layout(self._combo_player_layout.currentData())
        pending[KEY_PLAYER_LAYOUT] = player_layout
        set_player_layout(player_layout)
        if player_layout != self._committed_player_layout:
            deferred.append(lambda l=player_layout: self._refresh_player_layout(l))
        self._committed_player_layout = player_layout

        strip_size = normalize_timeline_strip_size(self._combo_timeline_strip.currentData())
        pending[KEY_TIMELINE_STRIP_SIZE] = strip_size
        pending[KEY_TIMELINE_STRIP_SIZE_REV] = TIMELINE_STRIP_SIZE_REV_CURRENT
        set_timeline_strip_size(strip_size)
        if strip_size != self._committed_timeline_strip:
            deferred.append(lambda s=strip_size: self._refresh_timeline_strip(s))
        self._committed_timeline_strip = strip_size

        vol_ceiling = normalize_volume_boost_ceiling(
            self._combo_volume_ceiling.currentData()
        )
        spd_ceiling = normalize_speed_boost_ceiling(
            self._combo_speed_ceiling.currentData()
        )
        pending[KEY_VOLUME_BOOST_CEILING] = vol_ceiling
        pending[KEY_SPEED_BOOST_CEILING] = spd_ceiling
        set_volume_boost_ceiling(vol_ceiling)
        set_speed_boost_ceiling(spd_ceiling)
        if (
            vol_ceiling != self._committed_volume_ceiling
            or spd_ceiling != self._committed_speed_ceiling
        ):
            deferred.append(
                lambda v=vol_ceiling, s=spd_ceiling: self._refresh_player_boost(v, s)
            )
        self._committed_volume_ceiling = vol_ceiling
        self._committed_speed_ceiling = spd_ceiling

        date_fmt = normalize_date_format(self._combo_date_format.currentData())
        clock_fmt = normalize_clock_format(self._combo_clock_format.currentData())
        tz = normalize_display_timezone(self._combo_timezone.currentData())
        date_changed = (
            normalize_date_format(prev.get(KEY_DATE_FORMAT)) != date_fmt
            or normalize_clock_format(prev.get(KEY_CLOCK_FORMAT)) != clock_fmt
            or normalize_display_timezone(prev.get(KEY_DISPLAY_TIMEZONE)) != tz
        )
        pending[KEY_DATE_FORMAT] = date_fmt
        pending[KEY_CLOCK_FORMAT] = clock_fmt
        pending[KEY_DISPLAY_TIMEZONE] = tz

        pending[KEY_MARKER_TRIM_OFFSET_MS] = normalize_marker_trim_offset_ms(
            self._combo_marker_trim.currentData()
        )
        on_strip = normalize_markers_on_strip(self._chk_markers_on_strip.isChecked())
        pending[KEY_MARKERS_ON_STRIP] = on_strip
        set_markers_on_strip(on_strip)
        if on_strip != self._committed_markers_on_strip:
            deferred.append(lambda e=on_strip: self._refresh_markers_on_strip(e))
        self._committed_markers_on_strip = on_strip
        pending[KEY_STARTUP_LIBRARY_SCAN] = normalize_startup_library_scan(
            self._combo_startup_scan.currentData()
        )

        cache_gb = normalize_media_cache_limit_gb(self._combo_cache_limit.currentData())
        pending[KEY_MEDIA_CACHE_LIMIT_GB] = cache_gb
        cache_dir = getattr(self._app, "cache_dir", None)

        def _prune_cache() -> None:
            try:
                from steempeg.infra.media_cache import prune_media_cache

                prune_media_cache(cache_dir, cache_gb)
            except Exception:
                logging.exception("media cache prune on Save failed")

        deferred.append(_prune_cache)

        pending[KEY_APP_LOG_LEVEL] = normalize_log_level(
            self._combo_app_log.currentData(), default=DEFAULT_APP_LOG_LEVEL
        )
        pending[KEY_FFMPEG_LOG_LEVEL] = normalize_log_level(
            self._combo_ffmpeg_log.currentData(), default=DEFAULT_FFMPEG_LOG_LEVEL
        )
        pending[KEY_MPV_LOG_LEVEL] = normalize_log_level(
            self._combo_mpv_log.currentData(), default=DEFAULT_MPV_LOG_LEVEL
        )
        pending[KEY_CONFIRM_BEFORE_DELETE] = self._chk_confirm_delete.isChecked()
        pending[KEY_REMEMBER_LIBRARY_TAB] = self._chk_remember_tab.isChecked()
        pending[KEY_TEST_NEW_FULLSCREEN] = self._chk_test_new_fullscreen.isChecked()

        shots = normalize_screenshots_folder(self._edit_screenshots.text())
        if not shots:
            shots = default_screenshots_dir()
        else:
            try:
                os.makedirs(shots, exist_ok=True)
            except OSError:
                shots = default_screenshots_dir()
        pending[KEY_SCREENSHOTS_FOLDER] = shots
        self._edit_screenshots.setText(shots)
        if hasattr(self._app, "screenshots_dir"):
            self._app.screenshots_dir = shots

        pending[KEY_HWDEC_PREVIEW] = normalize_hwdec_preview(self._combo_hwdec.currentData())

        shell = self._combo_shell.currentData()
        if shell in (UI_SHELL_DESKTOP, UI_SHELL_PORTABLE):
            pending[UI_SHELL_KEY] = shell
        if getattr(self, "_chk_ask_shell", None) is not None and self._chk_ask_shell.isEnabled():
            pending[UI_SHELL_ASK_KEY] = self._chk_ask_shell.isChecked()
        elif is_steamdeck_build():
            pending[UI_SHELL_ASK_KEY] = False

        if hasattr(self._app, "save_user_settings_batch"):
            self._app.save_user_settings_batch(pending)
        else:
            for key, value in pending.items():
                self._save_setting(key, value)

        merged = dict(prev)
        merged.update(pending)
        try:
            configure_runtime_prefs(merged)
        except Exception:
            logging.exception("configure_runtime_prefs after Save failed")

        if date_changed and hasattr(self._app, "refresh_library_datetime_displays"):
            deferred.append(self._app.refresh_library_datetime_displays)

        logging.info(
            "Settings Save persisted in %.0f ms (%d deferred task(s))",
            (time.perf_counter() - t0) * 1000,
            len(deferred),
        )
        return deferred

    def _save(self) -> None:
        import logging
        import time

        deferred = self._persist_settings()
        self.accept()
        if not deferred:
            return

        def _run_deferred() -> None:
            t0 = time.perf_counter()
            for fn in deferred:
                try:
                    fn()
                except Exception:
                    logging.exception("Settings Save deferred apply failed")
            logging.info(
                "Settings Save deferred apply finished in %.0f ms",
                (time.perf_counter() - t0) * 1000,
            )

        QTimer.singleShot(0, _run_deferred)


def show_settings_dialog(app) -> None:
    from PySide6.QtWidgets import QWidget

    from steempeg.ui.window_chrome import force_app_cursor_resync

    dlg = SettingsDialog(app, parent=getattr(app, "ui", None))
    try:
        dlg.exec()
    finally:
        # Modal buttons keep PointingHand on the cursor stack until destroyed.
        # Strip them now, then resync after deleteLater so Qt re-queries a live widget.
        try:
            for w in dlg.findChildren(QWidget):
                try:
                    if hasattr(w, "_set_hovered"):
                        w._set_hovered(False)
                    w.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
                    w.unsetCursor()
                except RuntimeError:
                    pass
            dlg.unsetCursor()
        except RuntimeError:
            pass
        tb = getattr(getattr(app, "ui", None), "title_bar", None)
        if tb is not None and hasattr(tb, "clear_shell_tool_hover"):
            tb.clear_shell_tool_hover()
        else:
            force_app_cursor_resync()
        try:
            dlg.deleteLater()
        except RuntimeError:
            pass
        QTimer.singleShot(0, force_app_cursor_resync)
        QTimer.singleShot(50, force_app_cursor_resync)


def maybe_show_small_screen_warning(app, ui_shell: str | None = None) -> None:
    """Startup tip when resolution / inches are below comfort (dismissable).

    Shown only in Desktop — cramped panels actually hurt there. Portable
    (PC and Deck) skips this modal; the shell chooser already warns inline.
    """
    try:
        from steempeg.ui.screen_metrics import (
            is_screen_undersized,
            screen_size_summary,
        )
        from steempeg.ui.shell_chooser import UI_SHELL_DESKTOP
    except Exception:
        return

    shell = ui_shell or getattr(app, "_ui_shell", None) or load_ui_shell()
    if shell != UI_SHELL_DESKTOP:
        return

    parent = getattr(app, "ui", None)
    if not is_screen_undersized(widget=parent):
        return

    settings = {}
    if hasattr(app, "load_user_settings"):
        try:
            settings = app.load_user_settings() or {}
        except Exception:
            settings = {}
    if settings.get(KEY_SMALL_SCREEN_WARNING_DISMISSED):
        return

    from steempeg.ui.message_dialog import steempeg_information_dont_ask

    summary = screen_size_summary(widget=parent)
    checked = steempeg_information_dont_ask(
        parent,
        "Small display",
        "Your screen is a bit small for Steempeg's comfort layout. "
        "You may see cramped panels or visual artifacts, especially in Desktop mode.",
        detail=(
            f"Detected: {summary}. Portable (theatre) usually fits small screens "
            "better. Switch shells anytime in Settings."
        ),
        checkbox_label="Don't show again",
    )
    if checked and hasattr(app, "save_user_settings"):
        app.save_user_settings(KEY_SMALL_SCREEN_WARNING_DISMISSED, True)
