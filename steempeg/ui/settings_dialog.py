"""App-wide Settings dialog — prefs that are not one click away elsewhere."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
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
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from steempeg.ui.icon_assets import title_bar_info_pixmap
from steempeg.ui import design_tokens as tok
from steempeg.ui.design_tokens import (
    KEY_UI_FONT,
    UI_FONT_DEFAULT,
    UI_FONT_LABELS,
    apply_ui_font_preference,
    normalize_ui_font,
    ui_font_preference_supported,
)
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
from steempeg.ui.player_outline import (
    KEY_PLAYER_OUTLINE,
    PLAYER_OUTLINE_DEFAULT,
    PLAYER_OUTLINE_LABELS,
    get_player_outline,
    normalize_player_outline,
    set_player_outline,
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
    dialog_theme,
    steempeg_information,
    steempeg_question,
    steempeg_warning,
)
from steempeg.infra.autostart import (
    autostart_is_supported,
    read_autostart_enabled,
    set_autostart_enabled,
)
from steempeg.ui.tray import tray_is_supported
from steempeg.ui.shell_chooser import (
    UI_SHELL_ASK_KEY,
    UI_SHELL_DESKTOP,
    UI_SHELL_KEY,
    UI_SHELL_PORTABLE,
    is_steamdeck_build,
    load_ask_ui_shell,
    load_ui_shell,
)
from steempeg.ui.settings_prefs import (
    CLOCK_FORMAT_LABELS,
    DATE_FORMAT_LABELS,
    DEFAULT_MARKERS_ON_STRIP,
    DISPLAY_TIMEZONE_LABELS,
    HWDEC_LABELS,
    KEY_APP_LOG_LEVEL,
    KEY_CLOCK_FORMAT,
    KEY_CONFIRM_BEFORE_DELETE,
    KEY_DATE_FORMAT,
    KEY_DEFAULT_RENDER_TAB,
    KEY_DECK_CONTROLS,
    KEY_DESKTOP_RENDER_LAYOUT,
    KEY_DEV_MODE,
    KEY_STEEMPEG_PRO,
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
    KEY_LIBRARY_ALLOW_LIST_VIEW,
    KEY_SCREENSHOTS_FOLDER,
    KEY_SCREENSHOTS_SHELF_LOAD,
    KEY_QUEUE_HOVER,
    KEY_DESKTOP_SHELL_TOOLS_IN_TITLE_BAR,
    KEY_SHELL_SIDE_LAYOUT,
    KEY_STARTUP_LIBRARY_SCAN,
    KEY_TEST_NEW_FULLSCREEN,
    KEY_HIDE_UPDATE_AVAILABLE_BADGE,
    KEY_HIDE_SETTINGS_HINTS,
    KEY_HIDE_SPLITTER_HANDLES,
    KEY_KEEP_RUNNING_IN_TRAY,
    KEY_SHELL_PANE_PERCENTS,
    KEY_UPDATE_CHECK_INTERVAL,
    LOG_LEVEL_LABELS,
    MARKER_TRIM_LABELS,
    MEDIA_CACHE_LIMIT_LABELS,
    DESKTOP_RENDER_LAYOUT_LABELS,
    RENDER_TAB_LABELS,
    SHELL_SIDE_LAYOUT_LABELS,
    SCREENSHOTS_SHELF_LOAD_LABELS,
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
    load_deck_controls,
    load_dev_mode,
    load_steempeg_pro,
    load_desktop_render_layout,
    load_display_timezone,
    load_ffmpeg_log_level,
    load_hwdec_preview,
    load_hide_settings_hints,
    load_hide_splitter_handles,
    load_hide_update_available_badge,
    load_keep_running_in_tray,
    DEFAULT_SHELL_PANE_PERCENTS,
    load_shell_pane_percents,
    read_shell_pane_percents,
    load_marker_trim_offset_ms,
    load_markers_on_strip,
    load_media_cache_limit_gb,
    load_mpv_log_level,
    load_remember_library_tab,
    load_library_allow_list_view,
    load_screenshots_shelf_load,
    load_queue_hover,
    load_desktop_shell_tools_in_title_bar,
    load_shell_side_layout,
    load_startup_library_scan,
    load_test_new_fullscreen,
    normalize_clock_format,
    normalize_date_format,
    normalize_deck_controls,
    normalize_dev_mode,
    normalize_steempeg_pro,
    normalize_desktop_render_layout,
    normalize_desktop_shell_tools_in_title_bar,
    normalize_display_timezone,
    normalize_export_folder,
    normalize_hide_update_available_badge,
    normalize_hwdec_preview,
    normalize_log_level,
    normalize_marker_trim_offset_ms,
    normalize_markers_on_strip,
    normalize_media_cache_limit_gb,
    normalize_render_tab,
    normalize_screenshots_folder,
    normalize_screenshots_shelf_load,
    normalize_queue_hover,
    normalize_shell_side_layout,
    normalize_startup_library_scan,
    normalize_update_check_interval,
    notify_export_folder_fallback,
    resolve_permanent_export_folder,
    resolve_screenshots_folder,
    resolve_update_check_interval,
    set_markers_on_strip,
    get_queue_hover,
    set_queue_hover,
    set_desktop_shell_tools_in_title_bar,
    set_shell_side_layout,
    get_shell_side_layout,
    DEFAULT_QUEUE_HOVER,
    DEFAULT_DESKTOP_SHELL_TOOLS_IN_TITLE_BAR,
    DEFAULT_APP_LOG_LEVEL,
    DEFAULT_FFMPEG_LOG_LEVEL,
    DEFAULT_MPV_LOG_LEVEL,
    DEFAULT_SHELL_SIDE_LAYOUT,
)
from steempeg.ui import settings_layouts
from steempeg.ui.widgets.combo_chrome import apply_dark_combo_popup
from steempeg.ui.widgets.dialog_chrome import SteempegDialog
from steempeg.ui.widgets.steempeg_check import SteempegCheckBox
from steempeg.ui.ui_theme import (
    DEFAULT_UI_THEME,
    KEY_UI_THEME,
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
# Rail and one-scroll frames carry a section rail beside the cards.
_SETTINGS_RAIL_DESIGN_W = 780
_SETTINGS_RAIL_MIN_W = 640
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


def _settings_page_inner_stylesheet(bg: str) -> str:
    """Shell fill for the scroll body only; children keep their own faces (section cards)."""
    return f"QWidget#settingsPageInner {{ background-color: {bg}; }}"


def _scroll_settings_tab(inner: QWidget, bg: str | None = None) -> QScrollArea:
    """Wrap a settings tab page; lavender pill scrollbar matches the library."""
    from steempeg.ui.library.library_styles import (
        LIBRARY_SCROLLBAR_VERTICAL,
        install_library_vertical_scrollbar,
    )

    bg = bg or tok.BG_SHELL
    inner.setObjectName("settingsPageInner")
    inner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    inner.setStyleSheet(_settings_page_inner_stylesheet(bg))

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


def _pro_action_button_stylesheet() -> str:
    """Solid red face for Get it now for free and Turn off PRO."""
    return f"""
        QPushButton {{
            background-color: #d64545;
            color: #ffffff;
            border: 1px solid #e85a5a;
            border-radius: 10px;
            padding: 10px 18px;
            font-size: 13px;
            font-weight: bold;
            font-family: {tok.FONT_APP};
        }}
        QPushButton:hover {{
            background-color: #e25555;
            border-color: #ff8a8a;
        }}
        QPushButton:pressed {{
            background-color: #b33838;
        }}
    """


def _pro_kofi_support_stylesheet() -> str:
    """Cream Ko-fi pill, the same height as the red PRO action."""
    return """
        QPushButton {
            background-color: #FFF9F3;
            color: #3A342E;
            border: 1px solid #E0D5C8;
            border-radius: 18px;
            padding: 10px 18px 10px 12px;
            font-family: "Fredoka", "Candara", "Calibri", "Segoe UI", sans-serif;
            font-size: 13px;
            font-weight: 700;
            outline: none;
        }
        QPushButton:hover {
            background-color: #F3EBE2;
            border-color: #D4C8B8;
        }
        QPushButton:pressed {
            background-color: #EDE4D8;
        }
    """


def _kofi_cup_pixmap(height: int):
    """Crop kofi.png to the cup and scale that ink to ``height`` px."""
    from PySide6.QtGui import QPixmap

    from steempeg.infra.paths import get_resource_path
    from steempeg.ui.icon_assets import _opaque_content_rect

    raw = QPixmap(get_resource_path("kofi.png"))
    if raw.isNull() or height <= 0:
        return QPixmap()
    x, y, width, tall = _opaque_content_rect(raw)
    cropped = raw.copy(x, y, max(width, 1), max(tall, 1))
    target_w = max(1, round(cropped.width() * height / max(cropped.height(), 1)))
    return cropped.scaled(
        target_w,
        height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class _PromoKofiMark(QLabel):
    """Ko-fi cup at the link's text size. A click opens the tip page."""

    def __init__(self, on_click, parent=None):
        super().__init__(parent)
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Opens Ko-fi")
        self.setStyleSheet("background: transparent; border: none; padding: 0;")

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        """Open the tip page. The cup is the click target, not a second button."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class SettingsDialog(SteempegDialog):
    """App Settings — General · Visual · Notifications · Performance · Support · PRO · Advanced.

    Stock frame is the section rail with cards; Dev can open the one-scroll or
    classic-tabs frame (``settings_layout``).
    """

    def __init__(self, app, parent=None, *, settings_layout: str | None = None, **theme_kwargs):
        parent_w = parent or getattr(app, "ui", None)
        if not theme_kwargs.get("bar_color"):
            theme_kwargs = {**dialog_theme(parent_w), **theme_kwargs}
        super().__init__("Settings", parent_w, **theme_kwargs)
        self._app = app
        self._settings_layout = settings_layouts.normalize_settings_layout(settings_layout)
        if self._settings_layout == settings_layouts.SETTINGS_LAYOUT_TABS:
            self._design_w = _SETTINGS_DESIGN_W
            self.setMinimumWidth(480)
        else:
            self._design_w = _SETTINGS_RAIL_DESIGN_W
            self.setMinimumWidth(_SETTINGS_RAIL_MIN_W)
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

        self._settings_pages: list[tuple[str, QWidget, QVBoxLayout]] = []
        self._settings_frame = None

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
        upd_row.addWidget(upd_lbl)
        upd_row.addWidget(self._combo_update_interval, 1)
        g.addLayout(upd_row)
        self._chk_hide_update_available = SteempegCheckBox(
            "Never show Update Available badge"
        )
        self._chk_hide_update_available.setChecked(
            load_hide_update_available_badge(settings)
        )
        g.addWidget(self._chk_hide_update_available)

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
        self._export_folder_hint = self._hint("")
        self._export_folder_hint.setProperty("helper_when_outside", True)
        g.addWidget(self._export_folder_hint)
        self._refresh_export_folder_hint()

        portable_shell = bool(getattr(self._app, "_portable_shell", False))

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
        if portable_shell:
            self._combo_desktop_render.setEnabled(False)
            g.addWidget(
                self._hint(
                    "Desktop only. Portable has one Render window, with the queue "
                    "and the render controls in it."
                )
            )
        else:
            g.addWidget(
                self._hint(
                    "Like a Portable is stock: purple Render Settings beside Start opens a "
                    "floating settings window (minimize / maximize; click again to close). "
                    "It's a Desktop keeps the classic docked Render panel."
                )
            )

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
                    "Steam Deck builds start in Portable. "
                    "Applies the next time Steempeg starts."
                )
            )
        else:
            g.addWidget(self._chk_ask_shell)
            g.addWidget(self._hint("Applies the next time Steempeg starts."))

        self._chk_hide_splitter_handles = SteempegCheckBox("Hide splitter handles")
        handles_hidden = load_hide_splitter_handles(settings)
        self._chk_hide_splitter_handles.setChecked(handles_hidden)
        g.addWidget(self._chk_hide_splitter_handles)
        if portable_shell:
            self._chk_hide_splitter_handles.setEnabled(False)
            g.addWidget(
                self._hint(
                    "Desktop only. Portable has no splitter handles to hide."
                )
            )
        else:
            g.addWidget(
                self._hint(
                    "Hides the splitter handles and the hover queue's drag tab. "
                    "Drag the panes first, then turn this on, or set the widths below. "
                    "Clips cannot pass its minimum; raising it shrinks the player. "
                    "The queue keeps the minimum and maximum of its current mode, "
                    "hover or the docked splitter. Off, the handles stay."
                )
            )
        # Filter time fields put the face on the field (bold 13px, padding
        # 4px 10px, min-height 24). Three of those beside their names do not
        # fit this card, so the name sits above the field. The whole group
        # hides while the handles stay.
        # A parentless QWidget is its own window. setVisible while the handles
        # are hidden would map that window (caption «Steempeg», then the row's
        # own 400×83) before Settings exists. Parent it first.
        self._pane_row_host = QWidget(general)
        self._pane_row_host.setStyleSheet("background: transparent;")
        pane_row = QHBoxLayout(self._pane_row_host)
        pane_row.setContentsMargins(0, 0, 0, 0)
        pane_row.setSpacing(12)
        self._pane_spins = {}
        self._pane_percent_lock = False
        self._pane_percent_baseline = None
        saved_percents = read_shell_pane_percents(settings) or DEFAULT_SHELL_PANE_PERCENTS
        label_qss = (
            "color: #888888; font-weight: bold; font-size: 13px; "
            f"font-family: {tok.FONT_APP}; background: transparent;"
        )
        for key, label, value in (
            ("clips", "Clips", saved_percents[0]),
            ("player", "Player", saved_percents[1]),
            ("queue", "Queue", saved_percents[2]),
        ):
            column = QWidget(self._pane_row_host)
            column.setStyleSheet("background: transparent;")
            col = QVBoxLayout(column)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(4)
            name = QLabel(label, column)
            name.setStyleSheet(label_qss)
            col.addWidget(name)
            spin = QSpinBox(column)
            spin.setRange(0, 100)
            spin.setSuffix(" %")
            spin.setValue(int(value))
            # 112 is the narrowest width where "100 %" still fits this field.
            spin.setFixedWidth(120)
            spin.setCursor(Qt.CursorShape.PointingHandCursor)
            spin.valueChanged.connect(
                lambda _value, pane=key: self._on_pane_percent_edited(pane)
            )
            self._pane_spins[key] = spin
            col.addWidget(spin)
            pane_row.addWidget(column)
        pane_row.addStretch(1)
        g.addWidget(self._pane_row_host)
        self._pane_row_host.setVisible(handles_hidden and not portable_shell)
        if portable_shell:
            for spin in self._pane_spins.values():
                spin.setEnabled(False)
        else:
            self._chk_hide_splitter_handles.toggled.connect(
                self._on_hide_splitter_handles_toggled
            )

        self._chk_keep_running_in_tray = SteempegCheckBox("Keep Steempeg running in the tray")
        self._chk_keep_running_in_tray.setChecked(load_keep_running_in_tray(settings))
        self._chk_autostart = SteempegCheckBox("Start Steempeg with Windows")
        self._chk_autostart.setChecked(read_autostart_enabled())
        self._chk_autostart.toggled.connect(self._on_autostart_toggled)
        if tray_is_supported():
            g.addWidget(self._chk_keep_running_in_tray)
            g.addWidget(
                self._hint(
                    "The red close button hides Steempeg to the tray, so new Steam "
                    "clips still pop up. Quit from the tray icon menu."
                )
            )
            if autostart_is_supported():
                g.addWidget(self._chk_autostart)
                g.addWidget(
                    self._hint(
                        "Starts hidden in the tray when you sign in to Windows. "
                        "Same as the installer's «Start Steempeg with Windows» box."
                    )
                )

        self._chk_deck_controls = SteempegCheckBox("Console mode (gamepad)")
        self._chk_deck_controls.setChecked(load_deck_controls(settings))
        if is_steamdeck_build():
            self._chk_deck_controls.setToolTip(
                "Gamepad mapping for Portable: player, Choose a Clip, Render. "
                "On by default for Steam Deck builds. Developer mode also enables it."
            )
        else:
            self._chk_deck_controls.setToolTip(
                "Gamepad mapping for Portable: player, Choose a Clip, Render. "
                "Off by default on Windows / Linux. Turn on to test with a pad "
                "or Dev Mode → Deck pad. Developer mode also enables it."
            )
        g.addWidget(self._chk_deck_controls)
        g.addWidget(
            self._hint(
                "Player: A play · Y trim · L1/R1 ±15s · R2 fullscreen · "
                "in trim X/A = start/end. Sheets: View / Menu / D-pad. "
                "Later: a simpler ▲▼◀▶-only Console style."
            )
        )

        restart_row = QHBoxLayout()
        restart_row.setSpacing(8)
        restart_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        btn_restart = QPushButton("Restart app")
        btn_restart.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_restart.clicked.connect(self._restart_app)
        restart_row.addWidget(btn_restart, 0, Qt.AlignmentFlag.AlignVCenter)
        g.addLayout(restart_row)
        g.addStretch(1)
        self._settings_pages.append(("General", general, g))

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
        cur_theme = normalize_ui_theme(settings.get(KEY_UI_THEME, DEFAULT_UI_THEME))
        self._committed_ui_theme = cur_theme
        tidx = self._combo_ui_theme.findData(cur_theme)
        self._combo_ui_theme.setCurrentIndex(max(0, tidx))
        theme_row.addWidget(theme_lbl)
        theme_row.addWidget(self._combo_ui_theme, 1)
        v.addLayout(theme_row)
        v.addWidget(
            self._hint(
                "TrueDark is the stock look. Default keeps the classic chrome. "
                "TrueDark OLED is pure black with hairline borders."
            )
        )

        # Linux-only: Windows stays classic Segoe with no UI font setting.
        self._combo_ui_font = None
        self._committed_ui_font = UI_FONT_DEFAULT
        if ui_font_preference_supported():
            font_row = QHBoxLayout()
            font_row.setSpacing(8)
            font_lbl = QLabel("UI font")
            font_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
            self._combo_ui_font = QComboBox()
            for value, label in UI_FONT_LABELS:
                self._combo_ui_font.addItem(label, value)
            cur_font = normalize_ui_font(settings.get(KEY_UI_FONT, UI_FONT_DEFAULT))
            self._committed_ui_font = cur_font
            fidx = self._combo_ui_font.findData(cur_font)
            self._combo_ui_font.setCurrentIndex(max(0, fidx))
            font_row.addWidget(font_lbl)
            font_row.addWidget(self._combo_ui_font, 1)
            v.addLayout(font_row)
            v.addWidget(
                self._hint(
                    "Auto uses real Segoe UI files when they are present, otherwise "
                    "bundled Selawik. A fontconfig alias that only substitutes "
                    "Adwaita or Noto does not count as Segoe."
                )
            )

        v.addWidget(self._section("Side panels"))
        sides_row = QHBoxLayout()
        sides_row.setSpacing(8)
        sides_lbl = QLabel("Sides")
        sides_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_shell_sides = QComboBox()
        for value, label in SHELL_SIDE_LAYOUT_LABELS:
            self._combo_shell_sides.addItem(label, value)
        cur_sides = load_shell_side_layout(settings)
        self._committed_shell_sides = cur_sides
        sides_idx = self._combo_shell_sides.findData(cur_sides)
        self._combo_shell_sides.setCurrentIndex(max(0, sides_idx))
        sides_row.addWidget(sides_lbl)
        sides_row.addWidget(self._combo_shell_sides, 1)
        v.addLayout(sides_row)
        if portable_shell:
            self._combo_shell_sides.setEnabled(False)
            v.addWidget(self._hint("Desktop only. Portable has no side docks."))

        self._chk_queue_hover = SteempegCheckBox("Hover Render Queue")
        cur_hover = load_queue_hover(settings)
        self._committed_queue_hover = cur_hover
        self._chk_queue_hover.setChecked(cur_hover)
        v.addWidget(self._chk_queue_hover)
        if portable_shell:
            self._chk_queue_hover.setEnabled(False)
            v.addWidget(
                self._hint(
                    "Desktop only. Hover the window edge to slide Render Queue out. "
                    "Off keeps the docked splitter pane."
                )
            )
        else:
            v.addWidget(
                self._hint(
                    "Hover the window edge on the Render Queue side to slide a "
                    "rounded copy out. Drag the inner edge to resize. "
                    "Off keeps the docked splitter pane."
                )
            )
            self._chk_queue_hover.toggled.connect(self._preview_queue_hover)
        self._refit_pane_percent_spins(seed_hover_queue=True, remember_baseline=True)

        self._chk_shell_tools_title = SteempegCheckBox(
            "About / Updates / Settings / Dev in title bar"
        )
        cur_shell_tools = load_desktop_shell_tools_in_title_bar(settings)
        self._committed_shell_tools_title = cur_shell_tools
        self._chk_shell_tools_title.setChecked(cur_shell_tools)
        v.addWidget(self._chk_shell_tools_title)
        if portable_shell:
            self._chk_shell_tools_title.setEnabled(False)
            v.addWidget(
                self._hint(
                    "Desktop only. Portable already keeps these tools in the title bar."
                )
            )
        else:
            v.addWidget(
                self._hint(
                    "Off: those tools stay in the library footer. "
                    "Folder and Refresh always stay in the footer."
                )
            )
            self._chk_shell_tools_title.toggled.connect(self._preview_shell_tools_title)

        self._shell_sides_preview_timer = QTimer(self)
        self._shell_sides_preview_timer.setSingleShot(True)
        self._shell_sides_preview_timer.setInterval(200)
        self._shell_sides_preview_timer.timeout.connect(self._apply_shell_sides_preview)
        if not portable_shell:
            self._combo_shell_sides.currentIndexChanged.connect(
                self._preview_shell_sides
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
                "SteempegUI: flat top on the first row, flat bottom on the last, "
                "middle rows fully round. Square: square top, round bottom. "
                "Round: round top and bottom. Clips, Rendered videos, and Choose a Clip."
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
                "Steam-like: centered logo and game name. Date and duration sit in "
                "the info tip. SteempegUI: left-aligned title with date, time, and duration."
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
                "Changes the header height, padding, and chips. "
                "The typeface stays the same. Large is the stock height."
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
                "Reunited: header, video, and footer sit flush. "
                "Fractured: gaps between them. Outline is the setting below."
            )
        )
        self._player_layout_preview_timer = QTimer(self)
        self._player_layout_preview_timer.setSingleShot(True)
        self._player_layout_preview_timer.setInterval(200)
        self._player_layout_preview_timer.timeout.connect(self._apply_player_layout_preview)
        self._combo_player_layout.currentIndexChanged.connect(self._preview_player_layout)

        outline_row = QHBoxLayout()
        outline_row.setSpacing(8)
        outline_lbl = QLabel("Outline")
        outline_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_player_outline = QComboBox()
        for value, label in PLAYER_OUTLINE_LABELS:
            self._combo_player_outline.addItem(label, value)
        cur_player_outline = normalize_player_outline(
            settings.get(KEY_PLAYER_OUTLINE, PLAYER_OUTLINE_DEFAULT)
        )
        self._committed_player_outline = cur_player_outline
        oidx = self._combo_player_outline.findData(cur_player_outline)
        self._combo_player_outline.setCurrentIndex(max(0, oidx))
        outline_row.addWidget(outline_lbl)
        outline_row.addWidget(self._combo_player_outline, 1)
        v.addLayout(outline_row)
        v.addWidget(
            self._hint(
                "With lines: borders on the player chrome. Without lines: no outline. "
                "With lines, not wrapping the video: header and footer keep borders, "
                "and the video plane stays flush. Theatre and fullscreen hide outlines. "
                "Portable keeps this setting."
            )
        )
        self._player_outline_preview_timer = QTimer(self)
        self._player_outline_preview_timer.setSingleShot(True)
        self._player_outline_preview_timer.setInterval(200)
        self._player_outline_preview_timer.timeout.connect(
            self._apply_player_outline_preview
        )
        self._combo_player_outline.currentIndexChanged.connect(
            self._preview_player_outline
        )

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
                "The progress track stays the same height."
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
                "Raises the slider past the normal cap. "
                "Volume starts at 100%. Speed starts at 5.0x."
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

        v.addWidget(self._section("Markers"))
        self._chk_markers_on_strip = SteempegCheckBox("Markers on the strip")
        cur_on_strip = load_markers_on_strip(settings)
        self._committed_markers_on_strip = cur_on_strip
        self._chk_markers_on_strip.setChecked(cur_on_strip)
        self._chk_markers_on_strip.toggled.connect(self._preview_markers_on_strip)
        v.addWidget(self._chk_markers_on_strip)
        v.addWidget(
            self._hint(
                "Draws kill and round icons on the purple seekbar instead of "
                "the row above. Hover shows a tooltip. Ctrl+click jumps to a marker."
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

        v.addStretch(1)
        self._settings_pages.append(("Visual", visual, v))

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
        self._settings_pages.append(("Notifications", notify, n))

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
                "A card stays once it has loaded. A new stretch of the grid may hitch. "
                "The first launch after Steam folders are found runs Full once. "
                "Refresh and adding a clips folder always run Full, even when "
                "Progressive is selected. Skip can feel as slow as a full scan."
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
        self._settings_pages.append(("Performance", perf, p))

        # ----- Support -----
        support, s = _tab_page()
        s.addWidget(self._section("Hints"))
        self._chk_hide_helper_text = SteempegCheckBox("Hide helper text")
        self._committed_hide_helper_text = load_hide_settings_hints(settings)
        self._chk_hide_helper_text.setChecked(self._committed_hide_helper_text)
        self._chk_hide_helper_text.toggled.connect(self._apply_helper_visibility)
        s.addWidget(self._chk_hide_helper_text)
        hints_row = QHBoxLayout()
        hints_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        hints_row.addWidget(
            self._hint(
                "Restore dismissed «Don't show again» dialogs.",
                optional=False,
            ),
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
        self._settings_pages.append(("Support", support, s))

        # ----- PRO -----
        pro_page, pro_lay = _tab_page()
        self._steempeg_pro = bool(load_steempeg_pro(settings))
        self._pro_banner = self._build_pro_promo_banner()
        pro_lay.addWidget(self._pro_banner)
        pro_lay.addStretch(1)
        self._settings_pages.append(("PRO", pro_page, pro_lay))

        # ----- Advanced -----
        advanced, a = _tab_page()
        a.addWidget(self._section("Fullscreen"))
        self._chk_test_new_fullscreen = SteempegCheckBox(
            "Skip grey flash on fullscreen enter/exit",
            font_size=13,
            label_bold=True,
            label_color="#ffffff",
        )
        self._chk_test_new_fullscreen.setChecked(load_test_new_fullscreen(settings))
        a.addWidget(self._chk_test_new_fullscreen)
        a.addWidget(
            self._hint(
                "May briefly show a black edge on exit. "
                "Turn off to bring the grey cover back."
            )
        )

        a.addWidget(self._section("Safety"))
        self._chk_confirm_delete = SteempegCheckBox("Confirm before deleting clips / renders")
        self._chk_confirm_delete.setChecked(load_confirm_before_delete(settings))
        a.addWidget(self._chk_confirm_delete)

        a.addWidget(self._section("Library"))
        self._chk_remember_tab = SteempegCheckBox("Remember last library tab")
        self._chk_remember_tab.setChecked(load_remember_library_tab(settings))
        a.addWidget(self._chk_remember_tab)
        self._chk_allow_list = SteempegCheckBox(
            "Restore classic List view (Clips / Rendered / Screenshots)"
        )
        self._chk_allow_list.setChecked(load_library_allow_list_view(settings))
        a.addWidget(self._chk_allow_list)
        a.addWidget(
            self._hint(
                "Off (default) = Size Big/Medium/Small only. "
                "On = add a List tile inside the Size popup (classic table layout)."
            )
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

        shelf_row = QHBoxLayout()
        shelf_row.setSpacing(8)
        shelf_lbl = QLabel("Library shelf")
        shelf_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_shots_shelf = QComboBox()
        for value, label in SCREENSHOTS_SHELF_LOAD_LABELS:
            self._combo_shots_shelf.addItem(label, value)
        cur_shelf = load_screenshots_shelf_load(settings)
        shelf_idx = self._combo_shots_shelf.findData(cur_shelf)
        self._combo_shots_shelf.setCurrentIndex(max(0, shelf_idx))
        self._committed_shots_shelf = cur_shelf
        shelf_row.addWidget(shelf_lbl)
        shelf_row.addWidget(self._combo_shots_shelf, 1)
        a.addLayout(shelf_row)
        a.addWidget(
            self._hint(
                "Full shelf plants every placeholder after launch, so the scrollbar "
                "fills sooner. The UI may hitch while they land."
            )
        )

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
                "Applies the next time the player is created. On Linux, Auto uses "
                "software on NVIDIA and VAAPI on Deck, AMD, and Intel. "
                "Force on uses auto-copy."
            )
        )

        a.addWidget(self._section("Dev tools"))
        self._chk_dev_mode = SteempegCheckBox("Developer mode")
        self._chk_dev_mode.setChecked(load_dev_mode(settings))
        self._chk_dev_mode.setToolTip(
            "Show the Dev footer/title-bar button and Developer Tools dialog. "
            "Also enables Console gamepad actions for QA."
        )
        a.addWidget(self._chk_dev_mode)

        a.addStretch(1)
        self._settings_pages.append(("Advanced", advanced, a))
        self._mount_settings_frame(root)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("Save")
        btn_save.setObjectName("settingsPrimaryBtn")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.clicked.connect(self._save)
        self._btn_cancel = btn_cancel
        self._btn_save = btn_save
        actions.addWidget(btn_cancel)
        actions.addWidget(btn_save)
        root.addLayout(actions)

        # Wheel over closed combos/spins must scroll the tab, not change values.
        from steempeg.ui.widgets.no_wheel_filter import install_no_wheel_value_filter

        install_no_wheel_value_filter(self)

        self._apply_settings_form_chrome()
        self._apply_helper_visibility()

        # Content can inflate sizeHint during build — re-cap before first map/center.
        self._apply_settings_geometry()

    def _mount_settings_frame(self, root: QVBoxLayout) -> None:
        """Puts the built pages into the picked frame: rail + cards, one scroll, or classic tabs."""
        from steempeg.ui import ui_theme as ut

        if self._settings_layout == settings_layouts.SETTINGS_LAYOUT_TABS:
            tabs = QTabWidget()
            tabs.setStyleSheet(ut.settings_dialog_tabs_stylesheet())
            tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            for title, page, _layout in self._settings_pages:
                tabs.addTab(_scroll_settings_tab(page), title)
            self._settings_tabs = tabs
            root.addWidget(tabs, 1)
            return

        for title, _page, page_layout in self._settings_pages:
            # PRO is only the red banner. A section card would paint a gray
            # frame around it and shrink the banner inside the card padding.
            if title == "PRO":
                continue
            settings_layouts.regroup_page_into_cards(page_layout)
        pages = [(title, page) for title, page, _layout in self._settings_pages]

        def wrap_on_dialog_face(page: QWidget) -> QScrollArea:
            """Cards sit straight on the dialog face, same as the rail beside them."""
            return _scroll_settings_tab(page, bg=self._settings_body_bg())

        if self._settings_layout == settings_layouts.SETTINGS_LAYOUT_SCROLL:
            frame = settings_layouts.SettingsScrollFrame(pages, wrap_on_dialog_face)
        else:
            frame = settings_layouts.SettingsRailFrame(pages, wrap_on_dialog_face)
        self._settings_frame = frame
        self._settings_tabs = frame.stack
        root.addWidget(frame, 1)

    def _settings_body_bg(self) -> str:
        """Fill behind the pages: shell gray for classic tabs, the dialog face for card frames."""
        if self._settings_layout == settings_layouts.SETTINGS_LAYOUT_TABS:
            return tok.BG_SHELL
        return getattr(self, "_bg_color", None) or tok.BG_SHELL

    def _apply_settings_geometry(self) -> None:
        """Comfort design size, capped so the shell stays on-screen and centerable."""
        from steempeg.ui.ui_density import scaled_dialog_size

        parent = self.parentWidget()
        w, h = scaled_dialog_size(
            getattr(self, "_design_w", _SETTINGS_DESIGN_W), _SETTINGS_DESIGN_H, parent=parent
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
        """Bold section title; in the rail / scroll frames each one opens a new card."""
        lbl = QLabel(text)
        lbl.setStyleSheet(_SECTION)
        settings_layouts.mark_section_title(lbl)
        return lbl

    @staticmethod
    def _hint(text: str, *, optional: bool = True) -> QWidget:
        """Muted helper line with circled info icon, optically centered on the text.

        Optional lines hide together from Support → Hints. A line that is the
        only label for a control stays (``optional=False``).
        """
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        if optional:
            row.setProperty("settings_helper", True)
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

    def _apply_helper_visibility(self, *_args) -> None:
        """Show or hide every optional helper line. The checkbox itself stays."""
        chk = getattr(self, "_chk_hide_helper_text", None)
        show = True if chk is None else not chk.isChecked()
        edit = getattr(self, "_edit_export_folder", None)
        folder = ""
        if edit is not None:
            folder = normalize_export_folder(edit.text()) or default_export_dir()
        outside = is_outside_default_rendered(folder) if folder else False
        for widget in self.findChildren(QWidget):
            if not widget.property("settings_helper"):
                continue
            if widget.property("helper_when_outside"):
                widget.setVisible(show and outside)
            else:
                widget.setVisible(show)

    def _build_pro_promo_banner(self) -> QFrame:
        """Red promo card — Get free / already unlocked."""
        from steempeg.infra.paths import get_resource_path
        from steempeg.ui.icon_utils import apply_square_icon, app_logo_pixmap
        from steempeg.ui.widgets.pro_badge import ProBadge

        frame = QFrame()
        frame.setObjectName("ProPromoBanner")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        frame.setStyleSheet(
            f"""
            QFrame#ProPromoBanner {{
                background-color: #2a1818;
                border: 1px solid #8b3a3a;
                border-radius: 12px;
            }}
            QLabel#ProPromoTitle {{
                color: #ffb3b3;
                font-size: 18px;
                font-weight: bold;
                background: transparent;
                font-family: {tok.FONT_APP};
            }}
            QLabel#ProPromoPitch {{
                color: #e0c0c0;
                font-size: 12px;
                background: transparent;
                font-family: {tok.FONT_APP};
            }}
            """
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(18, 18, 18, 16)
        # Gaps are explicit: +3px only under the title block. The link keeps
        # the old 10px, and nothing extra is added under ko-fi.com.
        lay.setSpacing(0)

        head = QHBoxLayout()
        head.setSpacing(12)
        logo = QLabel()
        logo.setFixedSize(48, 48)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet("background: transparent; border: none;")
        from steempeg.ui.icon_shape import ICON_SHAPE_CIRCLE, shaped_game_icon_pixmap

        pix = app_logo_pixmap(48, dpr=1.0)
        if pix is None or pix.isNull():
            from PySide6.QtGui import QPixmap

            pix = QPixmap(get_resource_path("logo.png"))
        # logo.png is a disc on an opaque square — mask corners for the red banner.
        if pix is not None and not pix.isNull():
            pix = shaped_game_icon_pixmap(pix, 48, ICON_SHAPE_CIRCLE)
        apply_square_icon(logo, pix, 48)
        head.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        title = QLabel("Steempeg")
        title.setObjectName("ProPromoTitle")
        name_row.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        name_row.addWidget(ProBadge(size="splash", parent=frame), 0, Qt.AlignmentFlag.AlignVCenter)
        name_row.addStretch(1)
        title_col.addLayout(name_row)
        pitch = QLabel()
        pitch.setObjectName("ProPromoPitch")
        pitch.setWordWrap(True)
        title_col.addWidget(pitch)
        head.addLayout(title_col, 1)
        lay.addLayout(head)
        lay.addSpacing(13)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_get = QPushButton("Get it now for free")
        btn_get.setObjectName("ProPromoGetBtn")
        btn_get.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_get.setStyleSheet(_pro_action_button_stylesheet())
        btn_get.clicked.connect(self._on_get_steempeg_pro)
        btn_off = QPushButton("Turn off PRO")
        btn_off.setObjectName("ProPromoOffBtn")
        btn_off.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_off.setStyleSheet(_pro_action_button_stylesheet())
        btn_off.setToolTip("Hide PRO badge / red splash chrome (settings only).")
        btn_off.clicked.connect(lambda: self._apply_steempeg_pro(False))
        btn_support = QPushButton("Support on Ko-fi")
        btn_support.setObjectName("ProPromoSupportBtn")
        btn_support.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_support.setStyleSheet(_pro_kofi_support_stylesheet())
        btn_support.setToolTip("Opens the tip URL from steempeg-meta.json on the website.")
        btn_support.clicked.connect(self._on_pro_support_kofi)
        from steempeg.ui.kofi_dialog import register_bundled_fredoka

        fredoka = register_bundled_fredoka()
        support_font = QFont()
        if fredoka:
            support_font.setFamily(fredoka)
        else:
            support_font.setFamilies(["Candara", "Calibri", "Segoe UI"])
        support_font.setPixelSize(13)
        support_font.setWeight(QFont.Weight.Bold)
        btn_support.setFont(support_font)
        from PySide6.QtGui import QIcon

        cup_btn = _kofi_cup_pixmap(16)
        if not cup_btn.isNull():
            btn_support.setIcon(QIcon(cup_btn))
            btn_support.setIconSize(cup_btn.size())
        btn_row.addWidget(btn_get)
        btn_row.addWidget(btn_off)
        btn_row.addWidget(btn_support)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)
        lay.addSpacing(10)

        host_row = QHBoxLayout()
        host_row.setSpacing(6)
        host_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        # Pitch label is 12px. The cup is cropped to its ink and scaled to that
        # same size so it sits on the link, not above it.
        mark = _PromoKofiMark(self._on_pro_support_kofi, frame)
        cup = _kofi_cup_pixmap(12)
        if not cup.isNull():
            mark.setPixmap(cup)
            mark.setFixedSize(cup.size())
        host_row.addWidget(mark, 0, Qt.AlignmentFlag.AlignVCenter)
        host = QLabel("")
        host.setObjectName("ProPromoPitch")
        host.setWordWrap(False)
        host_row.addWidget(host, 0, Qt.AlignmentFlag.AlignVCenter)
        host_row.addStretch(1)
        lay.addLayout(host_row)

        frame._pro_pitch = pitch  # type: ignore[attr-defined]
        frame._pro_btn_get = btn_get  # type: ignore[attr-defined]
        frame._pro_btn_off = btn_off  # type: ignore[attr-defined]
        frame._pro_btn_support = btn_support  # type: ignore[attr-defined]
        frame._pro_host = host  # type: ignore[attr-defined]
        self._sync_pro_promo_banner(frame)
        return frame

    def _sync_pro_promo_banner(self, frame: QFrame | None = None) -> None:
        banner = frame if frame is not None else getattr(self, "_pro_banner", None)
        if banner is None:
            return
        pitch = getattr(banner, "_pro_pitch", None)
        btn_get = getattr(banner, "_pro_btn_get", None)
        btn_off = getattr(banner, "_pro_btn_off", None)
        btn_support = getattr(banner, "_pro_btn_support", None)
        host = getattr(banner, "_pro_host", None)
        enabled = bool(getattr(self, "_steempeg_pro", False))
        if isinstance(pitch, QLabel):
            if enabled:
                pitch.setText(
                    "You're on Steempeg PRO."
                )
            else:
                pitch.setText("Get it now for free.")
        if isinstance(btn_get, QPushButton):
            btn_get.setVisible(not enabled)
        if isinstance(btn_off, QPushButton):
            btn_off.setVisible(enabled)
        if isinstance(btn_support, QPushButton):
            btn_support.setVisible(True)
        if isinstance(host, QLabel):
            try:
                from steempeg.services.kofi_remote import display_kofi_host, resolve_kofi_url

                host.setText(display_kofi_host(resolve_kofi_url(refresh=False)))
            except Exception:
                host.setText("ko-fi.com/applejuicy23")

    def _on_pro_support_kofi(self) -> None:
        import webbrowser

        from steempeg.services.kofi_remote import resolve_kofi_url

        webbrowser.open(resolve_kofi_url(refresh=True, timeout=2.5))
        self._sync_pro_promo_banner()

    def _on_get_steempeg_pro(self) -> None:
        from steempeg.ui.pro_unlock_dialog import ask_steempeg_pro_unlock

        choice = ask_steempeg_pro_unlock(self)
        if choice == "dismiss":
            return
        # Free unlock — Donate opens Ko-fi first; Cancel skips the tip.
        self._apply_steempeg_pro(True)

    def _apply_steempeg_pro(self, enabled: bool) -> None:
        self._steempeg_pro = bool(enabled)
        value = normalize_steempeg_pro(enabled)
        if hasattr(self._app, "save_user_settings"):
            self._app.save_user_settings(KEY_STEEMPEG_PRO, value)
        if hasattr(self._app, "_refresh_steempeg_pro_chrome"):
            try:
                self._app._refresh_steempeg_pro_chrome()
            except Exception:
                pass
        self._sync_pro_promo_banner()

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
        """Warn only when the export folder leaves the Rendered library."""
        folder = normalize_export_folder(self._edit_export_folder.text()) or default_export_dir()
        if is_outside_default_rendered(folder):
            self._set_hint_text(
                self._export_folder_hint,
                "Outside rendered_videos: exports still work, and the Rendered "
                "library still scans this path. Open in Steempeg may be limited.",
            )
        self._apply_helper_visibility()

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

    def _form_has_unsaved_changes(self) -> bool:
        """True when current widgets differ from last Save / dialog open baseline."""
        from steempeg.ui.shell_chooser import load_ask_ui_shell, load_ui_shell

        # Shell — Restart's main reason to care about dirty.
        current_shell = load_ui_shell() or UI_SHELL_DESKTOP
        if self._combo_shell.currentData() != current_shell:
            return True
        ask_chk = getattr(self, "_chk_ask_shell", None)
        if ask_chk is not None and ask_chk.isEnabled():
            if bool(ask_chk.isChecked()) != bool(load_ask_ui_shell()):
                return True

        def _combo_diff(combo_attr: str, committed_attr: str, normalize) -> bool:
            combo = getattr(self, combo_attr, None)
            if combo is None:
                return False
            cur = normalize(combo.currentData())
            opened = normalize(getattr(self, committed_attr, cur))
            return cur != opened

        from steempeg.ui.clip_card_style import normalize_clip_card_style
        from steempeg.ui.design_tokens import normalize_ui_font
        from steempeg.ui.icon_shape import normalize_icon_shape
        from steempeg.ui.player_boost import (
            normalize_speed_boost_ceiling,
            normalize_volume_boost_ceiling,
        )
        from steempeg.ui.player_header_layout import normalize_header_layout
        from steempeg.ui.player_header_size import normalize_player_header_size
        from steempeg.ui.player_layout import normalize_player_layout
        from steempeg.ui.player_outline import normalize_player_outline
        from steempeg.ui.settings_prefs import (
            normalize_desktop_render_layout,
            normalize_desktop_shell_tools_in_title_bar,
            normalize_markers_on_strip,
            normalize_queue_hover,
            normalize_render_tab,
            normalize_shell_side_layout,
        )
        from steempeg.ui.timeline_strip_size import normalize_timeline_strip_size
        from steempeg.ui.ui_theme import normalize_ui_theme

        checks = (
            ("_combo_ui_theme", "_committed_ui_theme", normalize_ui_theme),
            ("_combo_shell_sides", "_committed_shell_sides", normalize_shell_side_layout),
            (
                "_combo_desktop_render",
                "_committed_desktop_render",
                normalize_desktop_render_layout,
            ),
            ("_combo_icon_shape", "_committed_icon_shape", normalize_icon_shape),
            (
                "_combo_clip_card_style",
                "_committed_clip_card_style",
                normalize_clip_card_style,
            ),
            ("_combo_header_layout", "_committed_header_layout", normalize_header_layout),
            (
                "_combo_header_size",
                "_committed_header_size",
                normalize_player_header_size,
            ),
            ("_combo_player_layout", "_committed_player_layout", normalize_player_layout),
            (
                "_combo_player_outline",
                "_committed_player_outline",
                normalize_player_outline,
            ),
            (
                "_combo_timeline_strip",
                "_committed_timeline_strip",
                normalize_timeline_strip_size,
            ),
            (
                "_combo_volume_ceiling",
                "_committed_volume_ceiling",
                normalize_volume_boost_ceiling,
            ),
            (
                "_combo_speed_ceiling",
                "_committed_speed_ceiling",
                normalize_speed_boost_ceiling,
            ),
            ("_combo_render_tab", "_committed_render_tab", normalize_render_tab),
        )
        for combo_attr, committed_attr, normalize in checks:
            if _combo_diff(combo_attr, committed_attr, normalize):
                return True

        if self._combo_ui_font is not None and _combo_diff(
            "_combo_ui_font", "_committed_ui_font", normalize_ui_font
        ):
            return True

        chk_hover = getattr(self, "_chk_queue_hover", None)
        if chk_hover is not None:
            if normalize_queue_hover(chk_hover.isChecked()) != normalize_queue_hover(
                getattr(self, "_committed_queue_hover", chk_hover.isChecked())
            ):
                return True

        chk_tools = getattr(self, "_chk_shell_tools_title", None)
        if chk_tools is not None:
            if normalize_desktop_shell_tools_in_title_bar(
                chk_tools.isChecked()
            ) != normalize_desktop_shell_tools_in_title_bar(
                getattr(
                    self,
                    "_committed_shell_tools_title",
                    chk_tools.isChecked(),
                )
            ):
                return True

        chk_markers = getattr(self, "_chk_markers_on_strip", None)
        if chk_markers is not None:
            if normalize_markers_on_strip(
                chk_markers.isChecked()
            ) != normalize_markers_on_strip(
                getattr(self, "_committed_markers_on_strip", chk_markers.isChecked())
            ):
                return True

        # Export folder text vs committed path.
        edit = getattr(self, "_edit_export_folder", None)
        committed_export = getattr(self, "_committed_export_folder", None)
        if edit is not None and committed_export is not None:
            from steempeg.ui.settings_prefs import normalize_export_folder

            if normalize_export_folder(edit.text()) != normalize_export_folder(
                committed_export
            ):
                return True

        # Allow-list + other Advanced toggles vs disk (no committed_*).
        prev: dict = {}
        if hasattr(self._app, "load_user_settings"):
            try:
                prev = self._app.load_user_settings() or {}
            except Exception:
                prev = {}
        chk_allow = getattr(self, "_chk_allow_list", None)
        if chk_allow is not None:
            from steempeg.ui.settings_prefs import load_library_allow_list_view

            if bool(chk_allow.isChecked()) != bool(load_library_allow_list_view(prev)):
                return True

        chk_notify = getattr(self, "_chk_notify", None)
        if chk_notify is not None:
            if bool(chk_notify.isChecked()) != bool(
                prev.get(KEY_NOTIFY_ON_RENDER_COMPLETE, True)
            ):
                return True

        chk_tray = getattr(self, "_chk_keep_running_in_tray", None)
        if chk_tray is not None:
            if bool(chk_tray.isChecked()) != load_keep_running_in_tray(prev):
                return True

        chk_handles = getattr(self, "_chk_hide_splitter_handles", None)
        if chk_handles is not None:
            if bool(chk_handles.isChecked()) != load_hide_splitter_handles(prev):
                return True
            baseline = getattr(self, "_pane_percent_baseline", None)
            if baseline is None:
                baseline = load_shell_pane_percents(prev)
            if self._shell_pane_percent_values() != tuple(baseline):
                return True

        chk_autostart = getattr(self, "_chk_autostart", None)
        if chk_autostart is not None and autostart_is_supported():
            if bool(chk_autostart.isChecked()) != read_autostart_enabled():
                return True

        chk_hints = getattr(self, "_chk_hide_helper_text", None)
        if chk_hints is not None:
            if bool(chk_hints.isChecked()) != bool(
                getattr(self, "_committed_hide_helper_text", False)
            ):
                return True

        return False

    def _on_hide_splitter_handles_toggled(self, checked: bool) -> None:
        """Show the width row only while the handles are hidden, and copy the live panes."""
        host = getattr(self, "_pane_row_host", None)
        if host is not None:
            host.setVisible(bool(checked))
        if not checked:
            return
        snapshot = getattr(self._app, "snapshot_shell_pane_percents", None)
        if not callable(snapshot):
            return
        clips, player, queue = snapshot()
        self._pane_percent_lock = True
        try:
            self._pane_spins["clips"].setValue(int(clips))
            self._pane_spins["player"].setValue(int(player))
            self._pane_spins["queue"].setValue(int(queue))
        finally:
            self._pane_percent_lock = False
        # A hover snapshot reports queue 0 because the dock is shut. The spin
        # shows the overlay width instead, then both modes get their floors.
        self._refit_pane_percent_spins(seed_hover_queue=True)

    def _pane_queue_is_hover(self) -> bool:
        """True when the queue spin edits the slide-out, not the docked pane."""
        chk = getattr(self, "_chk_queue_hover", None)
        if chk is not None:
            return bool(chk.isChecked())
        return bool(get_queue_hover())

    def _shell_pane_measure(self) -> tuple[int, int]:
        """Return (window width, shell splitter width) for the pane percents."""
        ui = getattr(self._app, "ui", None)
        win_w = 0
        if ui is not None:
            try:
                win_w = int(ui.width() or 0)
            except RuntimeError:
                win_w = 0
        main = getattr(ui, "main_splitter", None) if ui is not None else None
        shell = 0
        if main is not None:
            try:
                sizes = main.sizes()
                shell = sum(int(part) for part in sizes)
                if shell <= 0:
                    shell = int(main.width() or 0)
            except RuntimeError:
                shell = 0
        if shell <= 0:
            shell = win_w
        return win_w, shell

    def _hover_overlay_width(self) -> int:
        """Pixel width of the hover queue, or 0 when that controller is absent."""
        ctrl = getattr(self._app, "_queue_hover", None)
        if ctrl is None or not hasattr(ctrl, "overlay_width"):
            return 0
        try:
            return max(0, int(ctrl.overlay_width()))
        except (RuntimeError, TypeError, ValueError):
            return 0

    def _on_pane_percent_edited(self, changed: str) -> None:
        """Keep the other two panes inside their floors after one spin moves."""
        if getattr(self, "_pane_percent_lock", False):
            return
        self._refit_pane_percent_spins(changed)

    def _refit_pane_percent_spins(
        self,
        changed: str | None = None,
        *,
        seed_hover_queue: bool = False,
        remember_baseline: bool = False,
    ) -> None:
        """Clamp the three spins to the live Clips / player / queue floors.

        Raising Clips or a docked queue lowers the player. Hover queue is a
        separate percent of the window: it does not take width from the shell.
        """
        spins = getattr(self, "_pane_spins", None)
        if not spins or "clips" not in spins:
            return
        win_w, shell = self._shell_pane_measure()
        if win_w <= 0 or shell <= 0:
            return
        from steempeg.ui.layout_defaults import (
            fit_shell_pane_pixels,
            percent_at_least,
            percent_at_most,
            shell_pane_pixel_limits,
            shell_percents_to_pixels,
            shell_pixels_to_percents,
        )

        hover = self._pane_queue_is_hover()
        limits = shell_pane_pixel_limits(win_w, hover=hover, shell_width=shell)
        clips, player, queue = self._shell_pane_percent_values()
        if hover and seed_hover_queue and queue <= 0:
            overlay = self._hover_overlay_width()
            if overlay > 0:
                queue = int(round(100 * overlay / win_w))
        # The edited spin is the one that wins. The player is the slack, except
        # when the player itself moved: then Clips (hover) or the queue (docked)
        # gives up the room.
        if hover and changed == "clips":
            player = max(0, 100 - int(clips))
        elif hover and changed == "player":
            clips = max(0, 100 - int(player))
        elif changed == "player" and not hover:
            rest = max(0, 100 - int(player))
            pair = max(int(clips) + int(queue), 1)
            clips = rest * int(clips) // pair
            queue = rest - clips
        clips_w, player_w, queue_w = shell_percents_to_pixels(
            clips, player, queue, shell=shell, window=win_w, hover=hover
        )
        clips_w, player_w, queue_w = fit_shell_pane_pixels(
            clips_w,
            player_w,
            queue_w,
            limits,
            shell,
            hover=hover,
            changed=changed or "clips",
        )
        clips, player, queue = shell_pixels_to_percents(
            clips_w, player_w, queue_w, shell=shell, window=win_w, hover=hover
        )
        (clips_min, _), (player_min, player_max), (queue_min, queue_max) = limits
        if hover:
            clips_hi = max(clips_min, shell - player_min)
            player_hi = max(player_min, shell - clips_min)
            queue_base = win_w
            queue_lo, queue_hi_px = queue_min, queue_max
        else:
            clips_hi = max(clips_min, shell - player_min - queue_w)
            player_hi = max(player_min, min(player_max, shell - clips_min - queue_min))
            queue_base = shell
            queue_lo = queue_min
            queue_hi_px = max(queue_min, shell - player_min - clips_w)
        ranges = {
            "clips": (percent_at_least(clips_min, shell), percent_at_most(clips_hi, shell)),
            "player": (percent_at_least(player_min, shell), percent_at_most(player_hi, shell)),
            "queue": (percent_at_least(queue_lo, queue_base), percent_at_most(queue_hi_px, queue_base)),
        }
        values = {"clips": clips, "player": player, "queue": queue}
        tips = {
            "clips": "Clips stays on the left. It cannot go under its minimum, and raising it shrinks the player.",
            "player": "The player gives up width when Clips or the queue grows, and it cannot go under its own minimum.",
            "queue": (
                "Hover queue, as a percent of the window. It slides over the player and stops at the drag handle's minimum and maximum."
                if hover
                else "Docked queue. It keeps its splitter minimum and maximum, and the difference comes out of the player."
            ),
        }
        self._pane_percent_lock = True
        try:
            clamped: dict[str, tuple[int, int]] = {}
            for key, spin in spins.items():
                low, high = ranges[key]
                low = max(0, min(100, int(low)))
                high = max(low, min(100, int(high)))
                clamped[key] = (low, high)
                spin.setRange(low, high)
                spin.setValue(max(low, min(high, int(values[key]))))
                spin.setToolTip(tips[key])
            if hover:
                low, high = clamped["player"]
                player_now = max(low, min(high, 100 - spins["clips"].value()))
                spins["player"].setValue(player_now)
                low, high = clamped["clips"]
                spins["clips"].setValue(max(low, min(high, 100 - player_now)))
            else:
                low, high = clamped["player"]
                player_now = 100 - spins["clips"].value() - spins["queue"].value()
                spins["player"].setValue(max(low, min(high, player_now)))
        finally:
            self._pane_percent_lock = False
        if remember_baseline:
            self._pane_percent_baseline = self._shell_pane_percent_values()

    def _shell_pane_percent_values(self) -> tuple[int, int, int]:
        """Read the three width fields as Clips, player, queue percentages."""
        spins = getattr(self, "_pane_spins", {})
        return (
            int(spins["clips"].value()),
            int(spins["player"].value()),
            int(spins["queue"].value()),
        )

    def _on_autostart_toggled(self, checked: bool) -> None:
        """Ticking autostart also ticks the tray box: a Windows-start launch lives in the tray."""
        if checked:
            self._chk_keep_running_in_tray.setChecked(True)

    def _restart_app(self) -> None:
        from steempeg.ui.message_dialog import (
            steempeg_question,
            steempeg_save_discard_cancel,
        )

        if self._form_has_unsaved_changes():
            choice = steempeg_save_discard_cancel(
                self,
                "Unsaved changes",
                "You have unsaved settings. Save before restarting?",
                detail="Save keeps these choices. Don't save restarts with the last saved settings.",
            )
            if choice == "cancel":
                return
            if choice == "save":
                deferred = self._persist_settings()
                if deferred is None:
                    return
                for fn in deferred:
                    try:
                        fn()
                    except Exception:
                        import logging

                        logging.exception(
                            "Settings Save deferred apply failed before restart"
                        )
            # discard → leave disk as-is; process restart drops live previews
        else:
            if not steempeg_question(
                self,
                "Restart Steempeg?",
                "Steempeg will quit and open again.",
            ):
                return

        app = self._app
        from steempeg.ui.shell_chooser import load_ui_shell, set_shell_skip_ask_once

        running_shell = getattr(app, "_ui_shell", None)
        saved_shell = load_ui_shell()
        if running_shell and saved_shell and saved_shell != running_shell:
            set_shell_skip_ask_once(True, app=app)
        # Flush queue + panel before relaunch so the other shell sees the same state.
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

        restart_application(app)

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
            # The spin's own editor is a QLineEdit. This field rule gives it a
            # 26px min-height and a border, which is taller than the spin, so
            # the glyphs draw outside the box. Filter time fields leave that
            # editor alone and put the face on the field itself.
            if isinstance(edit.parentWidget(), QSpinBox):
                continue
            edit.setStyleSheet(edit_qss)

        from steempeg.ui.smart_deletor_panel import _field_style

        pane_qss = _field_style()
        for spin in getattr(self, "_pane_spins", {}).values():
            inner = spin.lineEdit()
            if inner is not None:
                inner.setStyleSheet("")
            spin.setStyleSheet(pane_qss)

        sec_qss = ut.settings_dialog_secondary_button_stylesheet()
        about_sec = ut.about_secondary_button_stylesheet()
        about_accent = ut.about_accent_button_stylesheet()
        for btn in self.findChildren(QPushButton):
            # Title-bar traffic lights are QPushButtons — never restyle them as
            # form secondary buttons (idle becomes a gray square outline; they
            # paint the disc themselves).
            if isinstance(btn, _TrafficLight):
                btn.update()
                continue
            if btn.objectName() == settings_layouts.RAIL_BUTTON_OBJECT_NAME:
                continue
            if btn.objectName() in ("ProPromoGetBtn", "ProPromoOffBtn"):
                btn.setStyleSheet(_pro_action_button_stylesheet())
                continue
            if btn.objectName() == "ProPromoSupportBtn":
                btn.setStyleSheet(_pro_kofi_support_stylesheet())
                continue
            if btn.objectName() == "settingsPrimaryBtn" or btn is getattr(
                self, "_btn_save", None
            ):
                btn.setStyleSheet(about_accent)
                continue
            if btn is getattr(self, "_btn_cancel", None):
                btn.setStyleSheet(about_sec)
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
        if isinstance(tabs, QTabWidget):
            tabs.setStyleSheet(ut.settings_dialog_tabs_stylesheet())
        frame = getattr(self, "_settings_frame", None)
        if frame is not None:
            frame.apply_ui_theme_chrome()
        card_qss = settings_layouts.settings_card_stylesheet()
        for card in self.findChildren(QFrame, settings_layouts.CARD_OBJECT_NAME):
            card.setStyleSheet(card_qss)
        bg = self._settings_body_bg()
        for scroll in self.findChildren(QScrollArea):
            inner = scroll.widget()
            if inner is None:
                continue
            if inner.objectName() == "settingsPageInner":
                inner.setStyleSheet(_settings_page_inner_stylesheet(bg))
            else:
                inner.setStyleSheet(f"background-color: {bg};")
            tok.apply_dialog_scroll_bg(scroll, bg)
            scroll.setStyleSheet(tok.dialog_scroll_stylesheet(bg) + LIBRARY_SCROLLBAR_VERTICAL)
            install_library_vertical_scrollbar(scroll)
        self._apply_settings_form_chrome()

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
            getattr(self, "_committed_ui_theme", DEFAULT_UI_THEME)
        )
        live = get_ui_theme()
        combo = normalize_ui_theme(self._combo_ui_theme.currentData())
        if live == committed and combo == committed:
            return
        logging.info("UI theme cancelled → restored %s", committed)
        self._refresh_ui_theme(committed)

    def _refresh_ui_font(self, pref: str) -> None:
        if not ui_font_preference_supported():
            return
        apply_ui_font_preference(pref, app=QApplication.instance())
        live = normalize_ui_theme(get_ui_theme())
        self._refresh_ui_theme(live)

    def _restore_ui_font_on_cancel(self) -> None:
        if not ui_font_preference_supported() or self._combo_ui_font is None:
            return
        committed = normalize_ui_font(
            getattr(self, "_committed_ui_font", UI_FONT_DEFAULT)
        )
        combo = normalize_ui_font(self._combo_ui_font.currentData())
        if combo == committed:
            return
        import logging

        logging.info("UI font cancelled → restored %s", committed)
        self._refresh_ui_font(committed)

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

    def _preview_shell_sides(self, *_args) -> None:
        self._shell_sides_preview_timer.start()

    def _apply_shell_sides_preview(self) -> None:
        import logging

        layout = normalize_shell_side_layout(self._combo_shell_sides.currentData())
        set_shell_side_layout(layout)
        logging.info("Shell side layout preview → %s", layout)
        self._refresh_shell_sides(layout)

    def _refresh_shell_sides(self, layout: str) -> None:
        if hasattr(self._app, "refresh_shell_side_layout"):
            try:
                self._app.refresh_shell_side_layout(layout)
            except Exception:
                import logging

                logging.exception("Shell side layout refresh failed for %s", layout)

    def _preview_queue_hover(self, *_args) -> None:
        import logging

        enabled = normalize_queue_hover(self._chk_queue_hover.isChecked())
        set_queue_hover(enabled)
        logging.info("Queue hover preview → %s", enabled)
        self._refresh_queue_hover(enabled)
        self._refit_pane_percent_spins()

    def _refresh_queue_hover(self, enabled: bool) -> None:
        if hasattr(self._app, "refresh_queue_hover"):
            try:
                self._app.refresh_queue_hover(enabled)
            except Exception:
                import logging

                logging.exception("Queue hover refresh failed for %s", enabled)

    def _preview_shell_tools_title(self, *_args) -> None:
        import logging

        if getattr(self._app, "_portable_shell", False):
            return
        enabled = normalize_desktop_shell_tools_in_title_bar(
            self._chk_shell_tools_title.isChecked()
        )
        set_desktop_shell_tools_in_title_bar(enabled)
        logging.info("Desktop shell tools title-bar preview → %s", enabled)
        self._refresh_shell_tools_title(enabled)

    def _refresh_shell_tools_title(self, enabled: bool) -> None:
        if hasattr(self._app, "refresh_desktop_shell_tools_placement"):
            try:
                self._app.refresh_desktop_shell_tools_placement(enabled)
            except Exception:
                import logging

                logging.exception(
                    "Desktop shell tools title-bar refresh failed for %s", enabled
                )

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

    def _preview_player_outline(self, *_args) -> None:
        self._player_outline_preview_timer.start()

    def _apply_player_outline_preview(self) -> None:
        import logging

        mode = normalize_player_outline(self._combo_player_outline.currentData())
        set_player_outline(mode)
        logging.info("Player outline preview → %s", mode)
        self._refresh_player_outline(mode)

    def _refresh_player_outline(self, mode: str) -> None:
        if hasattr(self._app, "refresh_player_outline_mode"):
            try:
                self._app.refresh_player_outline_mode(mode)
            except Exception:
                import logging

                logging.exception("Player outline refresh failed for %s", mode)

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

    def _restore_shell_sides_on_cancel(self) -> None:
        """Undo live Library ↔ Queue side preview that was never Saved."""
        import logging

        if getattr(self, "_shell_sides_preview_timer", None) is not None:
            self._shell_sides_preview_timer.stop()
        committed = normalize_shell_side_layout(
            getattr(self, "_committed_shell_sides", DEFAULT_SHELL_SIDE_LAYOUT)
        )
        live = get_shell_side_layout()
        combo = normalize_shell_side_layout(self._combo_shell_sides.currentData())
        if live == committed and combo == committed:
            return
        set_shell_side_layout(committed)
        logging.info("Shell side layout cancelled → restored %s", committed)
        self._refresh_shell_sides(committed)

    def _restore_queue_hover_on_cancel(self) -> None:
        """Undo live queue-hover preview that was never Saved."""
        import logging

        chk = getattr(self, "_chk_queue_hover", None)
        if chk is None:
            return
        committed = normalize_queue_hover(
            getattr(self, "_committed_queue_hover", DEFAULT_QUEUE_HOVER)
        )
        live = normalize_queue_hover(chk.isChecked())
        if live == committed:
            return
        chk.blockSignals(True)
        chk.setChecked(committed)
        chk.blockSignals(False)
        set_queue_hover(committed)
        logging.info("Queue hover cancelled → restored %s", committed)
        self._refresh_queue_hover(committed)

    def _restore_shell_tools_title_on_cancel(self) -> None:
        """Undo live title-bar shell-tools preview that was never Saved."""
        import logging

        chk = getattr(self, "_chk_shell_tools_title", None)
        if chk is None:
            return
        committed = normalize_desktop_shell_tools_in_title_bar(
            getattr(
                self,
                "_committed_shell_tools_title",
                DEFAULT_DESKTOP_SHELL_TOOLS_IN_TITLE_BAR,
            )
        )
        live = normalize_desktop_shell_tools_in_title_bar(chk.isChecked())
        if live == committed:
            return
        chk.blockSignals(True)
        chk.setChecked(committed)
        chk.blockSignals(False)
        set_desktop_shell_tools_in_title_bar(committed)
        logging.info("Desktop shell tools title-bar cancelled → restored %s", committed)
        self._refresh_shell_tools_title(committed)

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

    def _restore_player_outline_on_cancel(self) -> None:
        """Undo live player outline preview that was never Saved."""
        import logging

        if getattr(self, "_player_outline_preview_timer", None) is not None:
            self._player_outline_preview_timer.stop()
        committed = normalize_player_outline(
            getattr(self, "_committed_player_outline", PLAYER_OUTLINE_DEFAULT)
        )
        live = get_player_outline()
        combo = normalize_player_outline(self._combo_player_outline.currentData())
        if live == committed and combo == committed:
            return
        set_player_outline(committed)
        logging.info("Player outline cancelled → restored %s", committed)
        self._refresh_player_outline(committed)

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
        self._restore_ui_font_on_cancel()
        self._restore_icon_shape_on_cancel()
        self._restore_clip_card_style_on_cancel()
        self._restore_shell_sides_on_cancel()
        self._restore_queue_hover_on_cancel()
        self._restore_shell_tools_title_on_cancel()
        self._restore_header_layout_on_cancel()
        self._restore_header_size_on_cancel()
        self._restore_player_layout_on_cancel()
        self._restore_player_outline_on_cancel()
        self._restore_timeline_strip_on_cancel()
        self._restore_markers_on_strip_on_cancel()
        self._restore_player_boost_on_cancel()
        super().reject()

    def _stop_visual_preview_timers(self) -> None:
        for attr in (
            "_icon_shape_preview_timer",
            "_clip_card_style_preview_timer",
            "_shell_sides_preview_timer",
            "_header_layout_preview_timer",
            "_header_size_preview_timer",
            "_player_layout_preview_timer",
            "_player_outline_preview_timer",
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
        hide_badge = normalize_hide_update_available_badge(
            self._chk_hide_update_available.isChecked()
        )
        pending[KEY_HIDE_UPDATE_AVAILABLE_BADGE] = hide_badge
        if hasattr(self._app, "apply_hide_update_available_badge"):
            deferred.append(
                lambda h=hide_badge: self._app.apply_hide_update_available_badge(h)
            )

        keep_in_tray = bool(self._chk_keep_running_in_tray.isChecked())
        pending[KEY_KEEP_RUNNING_IN_TRAY] = keep_in_tray
        if hasattr(self._app, "apply_keep_running_in_tray"):
            deferred.append(lambda k=keep_in_tray: self._app.apply_keep_running_in_tray(k))
        if autostart_is_supported():
            want_autostart = bool(self._chk_autostart.isChecked())
            if want_autostart != read_autostart_enabled():
                set_autostart_enabled(want_autostart)

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
        # Air-gap only — middle splitter opt-in removed (Emily 4 Sep 2026).
        pending[KEY_PORTABLE_LIKE_MIDDLE_SPLITTER] = False
        layout_apply = desktop_layout != getattr(
            self, "_committed_desktop_render", desktop_layout
        )
        if layout_apply and hasattr(self._app, "apply_desktop_render_layout"):
            deferred.append(self._app.apply_desktop_render_layout)
        self._committed_desktop_render = desktop_layout

        pending[KEY_NOTIFY_ON_RENDER_COMPLETE] = self._chk_notify.isChecked()
        pending[KEY_PAUSE_PREVIEW_DURING_RENDER] = self._chk_pause_preview.isChecked()
        prio = self._combo_priority.currentData()
        pending[KEY_RENDER_PROCESS_PRIORITY] = prio if prio else PRIORITY_NORMAL

        self._stop_visual_preview_timers()

        ui_theme = normalize_ui_theme(self._combo_ui_theme.currentData())
        pending[KEY_UI_THEME] = ui_theme
        opened_theme = normalize_ui_theme(
            getattr(self, "_committed_ui_theme", DEFAULT_UI_THEME)
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

        ui_font = normalize_ui_font(
            self._combo_ui_font.currentData()
            if self._combo_ui_font is not None
            else getattr(self, "_committed_ui_font", UI_FONT_DEFAULT)
        )
        if ui_font_preference_supported() and self._combo_ui_font is not None:
            pending[KEY_UI_FONT] = ui_font
            opened_font = normalize_ui_font(
                getattr(self, "_committed_ui_font", UI_FONT_DEFAULT)
            )
            if ui_font != opened_font:
                logging.info("UI font applied → %s", ui_font)
                deferred.append(lambda f=ui_font: self._refresh_ui_font(f))
            self._committed_ui_font = ui_font

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

        sides = normalize_shell_side_layout(self._combo_shell_sides.currentData())
        pending[KEY_SHELL_SIDE_LAYOUT] = sides
        set_shell_side_layout(sides)
        if sides != getattr(self, "_committed_shell_sides", sides):
            deferred.append(lambda s=sides: self._refresh_shell_sides(s))
        self._committed_shell_sides = sides

        hover = normalize_queue_hover(self._chk_queue_hover.isChecked())
        pending[KEY_QUEUE_HOVER] = hover
        set_queue_hover(hover)
        if hover != getattr(self, "_committed_queue_hover", hover):
            deferred.append(lambda h=hover: self._refresh_queue_hover(h))
        self._committed_queue_hover = hover

        hide_hints = bool(self._chk_hide_helper_text.isChecked())
        pending[KEY_HIDE_SETTINGS_HINTS] = hide_hints
        self._committed_hide_helper_text = hide_hints

        shell_tools = normalize_desktop_shell_tools_in_title_bar(
            self._chk_shell_tools_title.isChecked()
        )
        pending[KEY_DESKTOP_SHELL_TOOLS_IN_TITLE_BAR] = shell_tools
        set_desktop_shell_tools_in_title_bar(shell_tools)
        if shell_tools != getattr(self, "_committed_shell_tools_title", shell_tools):
            deferred.append(lambda e=shell_tools: self._refresh_shell_tools_title(e))
        self._committed_shell_tools_title = shell_tools

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

        player_outline = normalize_player_outline(
            self._combo_player_outline.currentData()
        )
        pending[KEY_PLAYER_OUTLINE] = player_outline
        set_player_outline(player_outline)
        if player_outline != self._committed_player_outline:
            deferred.append(lambda m=player_outline: self._refresh_player_outline(m))
        self._committed_player_outline = player_outline

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
        pending[KEY_LIBRARY_ALLOW_LIST_VIEW] = self._chk_allow_list.isChecked()
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

        pending[KEY_SCREENSHOTS_SHELF_LOAD] = normalize_screenshots_shelf_load(
            self._combo_shots_shelf.currentData()
        )
        new_shelf = pending[KEY_SCREENSHOTS_SHELF_LOAD]
        if new_shelf != getattr(self, "_committed_shots_shelf", None):
            self._committed_shots_shelf = new_shelf
            if hasattr(self._app, "reset_screenshots_shelf_for_load_mode"):
                deferred.append(self._app.reset_screenshots_shelf_for_load_mode)

        pending[KEY_HWDEC_PREVIEW] = normalize_hwdec_preview(self._combo_hwdec.currentData())

        dev_mode = normalize_dev_mode(self._chk_dev_mode.isChecked())
        steempeg_pro = normalize_steempeg_pro(getattr(self, "_steempeg_pro", False))
        deck_controls = normalize_deck_controls(self._chk_deck_controls.isChecked())
        pending[KEY_DEV_MODE] = dev_mode
        pending[KEY_STEEMPEG_PRO] = steempeg_pro
        pending[KEY_DECK_CONTROLS] = deck_controls
        if hasattr(self._app, "_refresh_dev_button_visibility"):
            deferred.append(self._app._refresh_dev_button_visibility)
        if hasattr(self._app, "_refresh_steempeg_pro_chrome"):
            deferred.append(self._app._refresh_steempeg_pro_chrome)
        if hasattr(self._app, "_sync_library_view_toggle_for_mode"):
            deferred.append(self._app._sync_library_view_toggle_for_mode)

        shell = self._combo_shell.currentData()
        if shell in (UI_SHELL_DESKTOP, UI_SHELL_PORTABLE):
            pending[UI_SHELL_KEY] = shell
        if getattr(self, "_chk_ask_shell", None) is not None and self._chk_ask_shell.isEnabled():
            pending[UI_SHELL_ASK_KEY] = self._chk_ask_shell.isChecked()
        elif is_steamdeck_build():
            pending[UI_SHELL_ASK_KEY] = False

        hide_handles = bool(self._chk_hide_splitter_handles.isChecked())
        self._refit_pane_percent_spins()
        pane_percents = self._shell_pane_percent_values()
        pending[KEY_HIDE_SPLITTER_HANDLES] = hide_handles
        pending[KEY_SHELL_PANE_PERCENTS] = list(pane_percents)
        win_w, shell = self._shell_pane_measure()
        if win_w > 0 and shell > 0:
            from steempeg.ui.layout_defaults import (
                fit_shell_pane_pixels,
                shell_pane_pixel_limits,
                shell_percents_to_pixels,
            )

            hover = self._pane_queue_is_hover()
            limits = shell_pane_pixel_limits(win_w, hover=hover, shell_width=shell)
            clips_w, player_w, queue_w = shell_percents_to_pixels(
                pane_percents[0],
                pane_percents[1],
                pane_percents[2],
                shell=shell,
                window=win_w,
                hover=hover,
            )
            _clips_w, _player_w, queue_w = fit_shell_pane_pixels(
                clips_w,
                player_w,
                queue_w,
                limits,
                shell,
                hover=hover,
                changed="clips",
            )
            baseline = getattr(self, "_pane_percent_baseline", None)
            queue_moved = baseline is None or int(baseline[2]) != int(pane_percents[2])
            if queue_moved:
                pending["queue_panel_width"] = int(queue_w)
        if hasattr(self._app, "apply_hidden_shell_splitter_handles"):
            deferred.append(self._app.apply_hidden_shell_splitter_handles)

        if hasattr(self._app, "save_user_settings_batch"):
            saved = self._app.save_user_settings_batch(pending)
        else:
            saved = True
            for key, value in pending.items():
                if hasattr(self._app, "save_user_settings"):
                    if not self._app.save_user_settings(key, value):
                        saved = False
                else:
                    self._save_setting(key, value)
        if not saved:
            from steempeg.ui.message_dialog import steempeg_warning

            steempeg_warning(
                self,
                "Settings not saved",
                "Could not write settings.json.",
                detail="Check that the Steempeg cache folder is writable, then try again.",
            )
            return None

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
        if deferred is None:
            return
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


def show_settings_dialog(app, *, settings_layout: str | None = None) -> None:
    """Opens Settings modally; Dev passes ``settings_layout`` to preview the other frames."""
    from PySide6.QtWidgets import QWidget

    from steempeg.ui.window_chrome import force_app_cursor_resync

    dlg = SettingsDialog(
        app, parent=getattr(app, "ui", None), settings_layout=settings_layout
    )
    app._app_settings_dlg = dlg
    app._app_settings_open = True
    app._deck_app_settings_focus_idx = 0
    try:
        from steempeg.input.deck_navigation import (
            console_focus_ring_allowed,
            hide_deck_focus_ring,
        )

        if console_focus_ring_allowed(app):
            from steempeg.input.deck_navigation import reset_app_settings_deck_focus

            QTimer.singleShot(0, lambda: reset_app_settings_deck_focus(app))
        else:
            # Console off (Dev mode may still be on): no lavender DeckFocusRing.
            hide_deck_focus_ring(app)

            def _clear_settings_pad_focus(d=dlg, a=app) -> None:
                try:
                    hide_deck_focus_ring(a)
                    d.setFocus(Qt.FocusReason.OtherFocusReason)
                    fw = QApplication.focusWidget()
                    if fw is not None and d.isAncestorOf(fw):
                        fw.clearFocus()
                    d.clearFocus()
                except RuntimeError:
                    pass

            QTimer.singleShot(0, _clear_settings_pad_focus)
    except Exception:
        pass
    try:
        dlg.exec()
    finally:
        app._app_settings_open = False
        if getattr(app, "_app_settings_dlg", None) is dlg:
            app._app_settings_dlg = None
        try:
            from steempeg.input.deck_navigation import hide_deck_focus_ring

            hide_deck_focus_ring(app)
        except Exception:
            pass
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
