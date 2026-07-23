"""App-wide Settings dialog — prefs that are not one click away elsewhere."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from steempeg.ui import design_tokens as tok
from steempeg.ui.message_dialog import _BTN_PRIMARY, _BTN_SECONDARY, dialog_theme
from steempeg.ui.shell_chooser import (
    UI_SHELL_DESKTOP,
    UI_SHELL_PORTABLE,
    load_ui_shell,
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
)

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
        root.addWidget(self._hint("Applies the next time Steempeg starts."))

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
        self.accept()


def show_settings_dialog(app) -> None:
    dlg = SettingsDialog(app, parent=getattr(app, "ui", None))
    dlg.exec()
