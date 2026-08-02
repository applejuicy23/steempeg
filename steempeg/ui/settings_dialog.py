"""App-wide Settings dialog — prefs that are not one click away elsewhere."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from steempeg.ui import design_tokens as tok
from steempeg.ui.icon_shape import (
    ICON_SHAPE_DEFAULT,
    ICON_SHAPE_LABELS,
    KEY_GAME_ICON_SHAPE,
    get_icon_shape,
    normalize_icon_shape,
    set_icon_shape,
)
from steempeg.ui.player_header_layout import (
    HEADER_LAYOUT_DEFAULT,
    HEADER_LAYOUT_LABELS,
    KEY_PLAYER_HEADER_LAYOUT,
    get_header_layout,
    normalize_header_layout,
    set_header_layout,
)
from steempeg.ui.message_dialog import (
    _BTN_PRIMARY,
    _BTN_SECONDARY,
    dialog_theme,
    steempeg_information,
    steempeg_question,
    steempeg_warning,
)
from steempeg.ui.shell_chooser import (
    UI_SHELL_DESKTOP,
    UI_SHELL_PORTABLE,
    is_steamdeck_build,
    load_ask_ui_shell,
    load_ui_shell,
    save_ask_ui_shell,
    save_ui_shell,
)
from steempeg.ui.settings_prefs import (
    KEY_DEFAULT_RENDER_TAB,
    KEY_UPDATE_CHECK_INTERVAL,
    RENDER_TAB_LABELS,
    UPDATE_INTERVAL_LABELS,
    apply_default_render_tab,
    apply_export_folder,
    default_export_dir,
    ensure_usable_export_folder,
    is_outside_default_rendered,
    load_default_render_tab,
    normalize_export_folder,
    normalize_render_tab,
    normalize_update_check_interval,
    notify_export_folder_fallback,
    resolve_permanent_export_folder,
    resolve_update_check_interval,
)
from steempeg.ui.widgets.combo_chrome import COMBO_POPUP_ITEM_RULES
from steempeg.ui.widgets.dialog_chrome import SteempegDialog
from steempeg.ui.widgets.steempeg_check import SteempegCheckBox

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
_COMBO = """
    QComboBox {
        background-color: #383838; color: #ffffff;
        border: 2px solid #4a4a4a; border-radius: 8px;
        padding: 4px 10px; font-size: 12px; font-weight: bold;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
        min-height: 26px;
    }
    QComboBox:hover { border: 2px solid #6b5a8e; }
    QComboBox::drop-down { border: none; width: 22px; }
""" + COMBO_POPUP_ITEM_RULES
_EDIT = """
    QLineEdit {
        background-color: #383838; color: #ffffff;
        border: 2px solid #4a4a4a; border-radius: 8px;
        padding: 4px 10px; font-size: 12px;
        font-family: 'Segoe UI', 'Noto Sans', Arial, sans-serif;
        min-height: 26px;
    }
    QLineEdit:hover { border: 2px solid #6b5a8e; }
    QLineEdit:focus { border: 2px solid #8e7cc3; }
"""
_TABS = """
    QTabWidget::pane {
        border: 1px solid #444; border-radius: 8px;
        background: #1e1e1e; top: -1px;
    }
    QTabBar::tab {
        background: #2a2a2a; color: #aaa; padding: 8px 14px; margin-right: 4px;
        border-top-left-radius: 6px; border-top-right-radius: 6px;
        font-family: 'Segoe UI', 'Noto Sans', Arial, sans-serif;
        font-size: 12px; font-weight: bold;
    }
    QTabBar::tab:selected { background: #4a3d66; color: #fff; }
    QTabBar::tab:hover:!selected { background: #353535; color: #ddd; }
"""


def _tab_page() -> tuple[QWidget, QVBoxLayout]:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)
    return page, layout


class SettingsDialog(SteempegDialog):
    """App Settings — tabbed: General · Visual · Notifications · Performance · Support."""

    def __init__(self, app, parent=None, **theme_kwargs):
        if not theme_kwargs.get("bar_color"):
            theme_kwargs = {**dialog_theme(parent or getattr(app, "ui", None)), **theme_kwargs}
        super().__init__("Settings", parent or getattr(app, "ui", None), **theme_kwargs)
        self._app = app
        self.setMinimumWidth(480)
        from steempeg.ui.ui_density import scaled_dialog_size

        w, h = scaled_dialog_size(520, 560, parent=parent or getattr(app, "ui", None))
        self.resize(w, h)

        settings = {}
        if hasattr(app, "load_user_settings"):
            try:
                settings = app.load_user_settings() or {}
            except Exception:
                settings = {}

        root = self.content_layout
        root.setSpacing(10)

        tabs = QTabWidget()
        tabs.setStyleSheet(_TABS)
        root.addWidget(tabs, 1)

        # ----- General (Updates + Export + Render landing + Shell) -----
        general, g = _tab_page()
        g.addWidget(self._section("Updates"))
        upd_row = QHBoxLayout()
        upd_row.setSpacing(8)
        upd_lbl = QLabel("Check for updates")
        upd_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_update_interval = QComboBox()
        self._combo_update_interval.setStyleSheet(_COMBO)
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
        g.addWidget(self._hint("Quiet badge only — never installs without you."))

        g.addWidget(self._section("Export"))
        export_row = QHBoxLayout()
        export_row.setSpacing(8)
        self._edit_export_folder = QLineEdit()
        self._edit_export_folder.setStyleSheet(_EDIT)
        self._edit_export_folder.setPlaceholderText(default_export_dir())
        self._committed_export_folder = resolve_permanent_export_folder(settings)
        self._edit_export_folder.setText(self._committed_export_folder)
        btn_browse_export = QPushButton("Browse…")
        btn_browse_export.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse_export.setStyleSheet(_BTN_SECONDARY)
        btn_browse_export.clicked.connect(self._browse_export_folder)
        btn_clear_export = QPushButton("Reset")
        btn_clear_export.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear_export.setStyleSheet(_BTN_SECONDARY)
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
        self._combo_render_tab.setStyleSheet(_COMBO)
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

        g.addWidget(self._section("Shell"))
        shell_row = QHBoxLayout()
        shell_row.setSpacing(8)
        shell_lbl = QLabel("UI shell")
        shell_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_shell = QComboBox()
        self._combo_shell.setStyleSheet(_COMBO)
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
                    "here if you want it — applies next launch."
                )
            )
        else:
            g.addWidget(self._chk_ask_shell)
            g.addWidget(self._hint("Applies the next time Steempeg starts."))

        restart_row = QHBoxLayout()
        restart_row.setSpacing(8)
        btn_restart = QPushButton("Restart app")
        btn_restart.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_restart.setStyleSheet(_BTN_SECONDARY)
        btn_restart.clicked.connect(self._restart_app)
        restart_row.addWidget(btn_restart, 0)
        restart_row.addWidget(
            self._hint("Quit and relaunch — use after changing shell."), 1
        )
        g.addLayout(restart_row)
        g.addStretch(1)
        tabs.addTab(general, "General")

        # ----- Visual -----
        visual, v = _tab_page()
        v.addWidget(self._section("Game icons"))
        shape_row = QHBoxLayout()
        shape_row.setSpacing(8)
        shape_lbl = QLabel("Corner shape")
        shape_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_icon_shape = QComboBox()
        self._combo_icon_shape.setStyleSheet(_COMBO)
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

        v.addWidget(self._section("Player header"))
        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        header_lbl = QLabel("Layout")
        header_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_header_layout = QComboBox()
        self._combo_header_layout.setStyleSheet(_COMBO)
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
                "SteempegUI — left-aligned title with date/time and duration. "
                "Steam-like — centered logo + game name; date/duration only in the "
                "info (i) tip. Combo previews live; Save persists. "
                "Cancel restores the last saved layout."
            )
        )
        self._header_layout_preview_timer = QTimer(self)
        self._header_layout_preview_timer.setSingleShot(True)
        self._header_layout_preview_timer.setInterval(200)
        self._header_layout_preview_timer.timeout.connect(self._apply_header_layout_preview)
        self._combo_header_layout.currentIndexChanged.connect(self._preview_header_layout)

        v.addStretch(1)
        tabs.addTab(visual, "Visual")

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
        tabs.addTab(notify, "Notifications")

        # ----- Performance -----
        perf, p = _tab_page()
        p.addWidget(self._section("Performance"))
        prio_row = QHBoxLayout()
        prio_row.setSpacing(8)
        prio_lbl = QLabel("Priority while rendering")
        prio_lbl.setStyleSheet(_HINT.replace(tok.TEXT_MUTED, tok.TEXT_PRIMARY))
        self._combo_priority = QComboBox()
        self._combo_priority.setStyleSheet(_COMBO)
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
        p.addStretch(1)
        tabs.addTab(perf, "Performance")

        # ----- Support -----
        support, s = _tab_page()
        s.addWidget(self._section("Hints"))
        hints_row = QHBoxLayout()
        hints_row.addWidget(
            self._hint("Restore dismissed «Don't show again» dialogs."), 1
        )
        btn_reset_hints = QPushButton("Reset all")
        btn_reset_hints.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset_hints.setStyleSheet(_BTN_SECONDARY)
        btn_reset_hints.clicked.connect(self._reset_hints)
        hints_row.addWidget(btn_reset_hints, 0)
        s.addLayout(hints_row)
        self._hints_status = QLabel("")
        self._hints_status.setStyleSheet(_HINT)
        s.addWidget(self._hints_status)

        s.addWidget(self._section("Logs / support"))
        support_row = QHBoxLayout()
        support_row.setSpacing(8)
        btn_logs = QPushButton("Open logs folder")
        btn_logs.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_logs.setStyleSheet(_BTN_SECONDARY)
        btn_logs.clicked.connect(self._open_logs)
        btn_cache = QPushButton("Clear cache…")
        btn_cache.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cache.setStyleSheet(_BTN_SECONDARY)
        btn_cache.clicked.connect(self._clear_cache)
        support_row.addWidget(btn_logs)
        support_row.addWidget(btn_cache)
        support_row.addStretch(1)
        s.addLayout(support_row)

        import_row = QHBoxLayout()
        import_row.setSpacing(8)
        import_row.addWidget(
            self._hint(
                "Pull rendered videos, Screenshots, and cache from an "
                "old_version backup (skips files that already exist)."
            ),
            1,
        )
        btn_import = QPushButton("Import from backup…")
        btn_import.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_import.setStyleSheet(_BTN_SECONDARY)
        btn_import.clicked.connect(self._import_from_backup)
        import_row.addWidget(btn_import, 0)
        s.addLayout(import_row)
        self._import_status = QLabel("")
        self._import_status.setWordWrap(True)
        self._import_status.setStyleSheet(_HINT)
        s.addWidget(self._import_status)
        s.addStretch(1)
        tabs.addTab(support, "Support")

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet(_BTN_SECONDARY)
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("Save")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setStyleSheet(_BTN_PRIMARY)
        btn_save.clicked.connect(self._save)
        actions.addWidget(btn_cancel)
        actions.addWidget(btn_save)
        root.addLayout(actions)

    @staticmethod
    def _section(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_SECTION)
        return lbl

    @staticmethod
    def _hint(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(_HINT)
        return lbl

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

    def _refresh_export_folder_hint(self) -> None:
        folder = normalize_export_folder(self._edit_export_folder.text()) or default_export_dir()
        if is_outside_default_rendered(folder):
            self._export_folder_hint.setText(
                "Outside rendered_videos — exports OK; Rendered library still "
                "scans this path, but «Open in Steempeg» may be limited."
            )
        else:
            self._export_folder_hint.setText(
                "Permanent output folder for exports. Save syncs the Export "
                "panel. Reset returns to the default rendered_videos folder."
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
            detail="Unsaved dialog choices in this window are discarded — Save first if needed.",
        ):
            return
        # Persist shell prefs before relaunch so Restart after a shell change works
        # even if the user forgot Save.
        shell = self._combo_shell.currentData()
        if shell in (UI_SHELL_DESKTOP, UI_SHELL_PORTABLE):
            save_ui_shell(shell)
        if getattr(self, "_chk_ask_shell", None) is not None and self._chk_ask_shell.isEnabled():
            save_ask_ui_shell(self._chk_ask_shell.isChecked())
        self.accept()
        from steempeg.ui.app_restart import restart_application

        restart_application(self._app)

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

    def reject(self) -> None:
        self._restore_icon_shape_on_cancel()
        self._restore_header_layout_on_cancel()
        super().reject()

    def _persist_settings(self) -> None:
        import logging

        interval = normalize_update_check_interval(
            self._combo_update_interval.currentData()
        )
        self._save_setting(KEY_UPDATE_CHECK_INTERVAL, interval)

        requested = normalize_export_folder(self._edit_export_folder.text()) or default_export_dir()
        folder, fell_back = ensure_usable_export_folder(requested)
        if fell_back:
            notify_export_folder_fallback(
                self, requested, folder, use_dialog=True
            )
        apply_export_folder(self._app, folder, persist=True)
        self._committed_export_folder = folder
        self._edit_export_folder.setText(folder)
        self._refresh_export_folder_hint()

        render_tab = normalize_render_tab(self._combo_render_tab.currentData())
        self._save_setting(KEY_DEFAULT_RENDER_TAB, render_tab)
        self._committed_render_tab = render_tab
        apply_default_render_tab(self._app, render_tab)

        self._save_setting(
            KEY_NOTIFY_ON_RENDER_COMPLETE, self._chk_notify.isChecked()
        )
        self._save_setting(
            KEY_PAUSE_PREVIEW_DURING_RENDER,
            self._chk_pause_preview.isChecked(),
        )
        prio = self._combo_priority.currentData()
        self._save_setting(
            KEY_RENDER_PROCESS_PRIORITY,
            prio if prio else PRIORITY_NORMAL,
        )
        # Cancel pending preview so Save is the sole refresh.
        if getattr(self, "_icon_shape_preview_timer", None) is not None:
            self._icon_shape_preview_timer.stop()
        shape = normalize_icon_shape(self._combo_icon_shape.currentData())
        self._save_setting(KEY_GAME_ICON_SHAPE, shape)
        set_icon_shape(shape)
        self._committed_icon_shape = shape
        logging.info("Icon shape applied → %s (settings.json)", shape)
        self._refresh_icon_shapes(shape)

        if getattr(self, "_header_layout_preview_timer", None) is not None:
            self._header_layout_preview_timer.stop()
        header_layout = normalize_header_layout(self._combo_header_layout.currentData())
        self._save_setting(KEY_PLAYER_HEADER_LAYOUT, header_layout)
        set_header_layout(header_layout)
        self._committed_header_layout = header_layout
        logging.info("Player header layout applied → %s (settings.json)", header_layout)
        self._refresh_header_layout(header_layout)

        shell = self._combo_shell.currentData()
        if shell in (UI_SHELL_DESKTOP, UI_SHELL_PORTABLE):
            save_ui_shell(shell)
        if getattr(self, "_chk_ask_shell", None) is not None and self._chk_ask_shell.isEnabled():
            save_ask_ui_shell(self._chk_ask_shell.isChecked())
        elif is_steamdeck_build():
            # Deck never shows the chooser.
            save_ask_ui_shell(False)

    def _save(self) -> None:
        self._persist_settings()
        self.accept()


def show_settings_dialog(app) -> None:
    dlg = SettingsDialog(app, parent=getattr(app, "ui", None))
    try:
        dlg.exec()
    finally:
        tb = getattr(getattr(app, "ui", None), "title_bar", None)
        if tb is not None and hasattr(tb, "clear_shell_tool_hover"):
            tb.clear_shell_tool_hover()


def maybe_show_small_screen_warning(app, ui_shell: str | None = None) -> None:
    """Startup tip when resolution / inches are below comfort (dismissable).

    Skipped on Steam Deck Portable (that shell is built for 1280×800). Still
    shown for Desktop on Deck, and for every cramped PC display.
    """
    try:
        from steempeg.ui.screen_metrics import (
            is_screen_undersized,
            screen_size_summary,
        )
        from steempeg.ui.shell_chooser import UI_SHELL_DESKTOP, is_steamdeck_build
    except Exception:
        return

    shell = ui_shell or getattr(app, "_ui_shell", None) or load_ui_shell()
    if is_steamdeck_build() and shell != UI_SHELL_DESKTOP:
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
        "You may see cramped panels or visual artifacts — especially in Desktop mode.",
        detail=(
            f"Detected: {summary}. Portable (theatre) usually fits small screens "
            "better. Switch shells anytime in Settings."
        ),
        checkbox_label="Don't show again",
    )
    if checked and hasattr(app, "save_user_settings"):
        app.save_user_settings(KEY_SMALL_SCREEN_WARNING_DISMISSED, True)
