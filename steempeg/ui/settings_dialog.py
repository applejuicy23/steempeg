"""App-wide Settings dialog — prefs that are not one click away elsewhere."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from steempeg.ui import design_tokens as tok
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
from steempeg.ui.widgets.dialog_chrome import SteempegDialog
from steempeg.ui.widgets.steempeg_check import SteempegCheckBox

# Persisted preference keys
KEY_CHECK_UPDATES_ON_STARTUP = "check_updates_on_startup"
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
"""


class SettingsDialog(SteempegDialog):
    """Library-footer Settings: updates, shell, notify, hints, support, performance."""

    def __init__(self, app, parent=None, **theme_kwargs):
        if not theme_kwargs.get("bar_color"):
            theme_kwargs = {**dialog_theme(parent or getattr(app, "ui", None)), **theme_kwargs}
        super().__init__("Settings", parent or getattr(app, "ui", None), **theme_kwargs)
        self._app = app
        self.setMinimumWidth(440)
        from steempeg.ui.ui_density import scaled_dialog_size

        w, h = scaled_dialog_size(460, 520, parent=parent or getattr(app, "ui", None))
        self.resize(w, h)

        settings = {}
        if hasattr(app, "load_user_settings"):
            try:
                settings = app.load_user_settings() or {}
            except Exception:
                settings = {}

        root = self.content_layout
        root.setSpacing(10)

        # --- Updates ---
        root.addWidget(self._section("Updates"))
        self._chk_updates = SteempegCheckBox("Check for updates on startup")
        self._chk_updates.setChecked(
            bool(settings.get(KEY_CHECK_UPDATES_ON_STARTUP, True))
        )
        root.addWidget(self._chk_updates)
        root.addWidget(
            self._hint("Quiet badge only — never installs without you.")
        )

        # --- Shell ---
        root.addWidget(self._section("Shell"))
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
        root.addLayout(shell_row)
        self._chk_ask_shell = SteempegCheckBox("Ask which shell on startup")
        self._chk_ask_shell.setChecked(load_ask_ui_shell())
        if is_steamdeck_build():
            # Deck builds skip the chooser; still allow Desktop via this combo.
            self._chk_ask_shell.setChecked(False)
            self._chk_ask_shell.setEnabled(False)
            root.addWidget(
                self._hint(
                    "Steam Deck builds start in Portable. Desktop is available "
                    "here if you want it — applies next launch."
                )
            )
        else:
            root.addWidget(self._chk_ask_shell)
            root.addWidget(
                self._hint("Applies the next time Steempeg starts.")
            )

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
        root.addLayout(restart_row)

        # --- Notifications ---
        root.addWidget(self._section("Notifications"))
        self._chk_notify = SteempegCheckBox("Notify when render finishes")
        self._chk_notify.setChecked(
            bool(settings.get(KEY_NOTIFY_ON_RENDER_COMPLETE, True))
        )
        root.addWidget(self._chk_notify)
        root.addWidget(
            self._hint("OS toast when minimized — wired as notifications land.")
        )

        # --- Hints ---
        root.addWidget(self._section("Hints"))
        hints_row = QHBoxLayout()
        hints_row.addWidget(
            self._hint("Restore dismissed «Don't show again» dialogs."), 1
        )
        btn_reset_hints = QPushButton("Reset all")
        btn_reset_hints.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset_hints.setStyleSheet(_BTN_SECONDARY)
        btn_reset_hints.clicked.connect(self._reset_hints)
        hints_row.addWidget(btn_reset_hints, 0)
        root.addLayout(hints_row)
        self._hints_status = QLabel("")
        self._hints_status.setStyleSheet(_HINT)
        root.addWidget(self._hints_status)

        # --- Logs / support ---
        root.addWidget(self._section("Logs / support"))
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
        root.addLayout(support_row)

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
        root.addLayout(import_row)
        self._import_status = QLabel("")
        self._import_status.setWordWrap(True)
        self._import_status.setStyleSheet(_HINT)
        root.addWidget(self._import_status)

        # --- Performance ---
        root.addWidget(self._section("Performance"))
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
        root.addLayout(prio_row)

        self._chk_pause_preview = SteempegCheckBox(
            "Pause preview while rendering"
        )
        self._chk_pause_preview.setChecked(
            bool(settings.get(KEY_PAUSE_PREVIEW_DURING_RENDER, False))
        )
        root.addWidget(self._chk_pause_preview)
        root.addWidget(
            self._hint("Keeps CPU/GPU freer for FFmpeg. Off by default.")
        )

        root.addStretch(1)

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

    def _save(self) -> None:
        self._save_setting(
            KEY_CHECK_UPDATES_ON_STARTUP, self._chk_updates.isChecked()
        )
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
        shell = self._combo_shell.currentData()
        if shell in (UI_SHELL_DESKTOP, UI_SHELL_PORTABLE):
            save_ui_shell(shell)
        if getattr(self, "_chk_ask_shell", None) is not None and self._chk_ask_shell.isEnabled():
            save_ask_ui_shell(self._chk_ask_shell.isChecked())
        elif is_steamdeck_build():
            # Deck never shows the chooser.
            save_ask_ui_shell(False)
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
