"""Update Center — pick any installable release to upgrade or downgrade."""
from __future__ import annotations

import logging
import re
import webbrowser

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from steempeg.services.release_catalog import (
    FetchError,
    LocalBackup,
    ReleaseEntry,
    fetch_releases,
    jump_warnings,
)
from steempeg.ui import design_tokens as tok
from steempeg.ui.widgets.dialog_chrome import SteempegDialog
from steempeg.version import APP_VERSION_FLOAT, APP_VERSION_STR

_BADGE_LABELS = {
    "current": "● current",
    "newer": "↑ newer",
    "older": "↓ older",
    "manual only": "manual only",
    "browser-era": "browser era",
    "unavailable": "no zip",
}

_BADGE_COLORS = {
    "current": "#7ec8a3",
    "newer": "#8ec5ff",
    "older": "#c4b5e8",
    "manual only": "#888888",
    "browser-era": "#d4a574",
    "unavailable": "#888888",
}

_LIST_STYLE = """
    QListWidget {
        background-color: #242424;
        border: 1px solid #3d3d3d;
        border-radius: 8px;
        color: #ddd;
        font-size: 12px;
        padding: 4px;
    }
    QListWidget::item {
        border-radius: 6px;
        padding: 8px 10px;
        margin: 2px 0;
    }
    QListWidget::item:selected {
        background-color: #3a324a;
        border: 1px solid #6b5a8e;
    }
    QListWidget::item:hover:!selected {
        background-color: #2e2e2e;
    }
"""

_NOTES_STYLE = """
    QTextEdit {
        background-color: #1a1a1a;
        border: 1px solid #3d3d3d;
        border-radius: 8px;
        color: #bbb;
        font-size: 11px;
        padding: 8px;
    }
"""

_BTN_PRIMARY = """
    QPushButton {
        background-color: #4a3d66; color: #f0ecff; border: 2px solid #6b5a8e;
        border-radius: 8px; padding: 6px 14px; font-size: 12px; font-weight: bold;
    }
    QPushButton:hover { background-color: #5a4d76; border-color: #b29ae7; }
    QPushButton:pressed { background-color: #3a324a; }
    QPushButton:disabled { background-color: #2a2a2a; color: #666; border-color: #444; }
"""

_BTN_SECONDARY = """
    QPushButton {
        background-color: #333; color: #ccc; border: 1px solid #555;
        border-radius: 8px; padding: 6px 14px; font-size: 12px;
    }
    QPushButton:hover { background-color: #444; color: #fff; }
    QPushButton:disabled { background-color: #2a2a2a; color: #666; border-color: #444; }
"""


def _release_row_text(entry: ReleaseEntry, badge_key: str) -> str:
    tag = entry.tag_name or f"v{entry.version_str}"
    title = (entry.name or "").strip()
    if title and title.lower().replace("steempeg", "").strip() in (
        tag.lower(),
        f"v{entry.version_str}".lower(),
        entry.version_str,
    ):
        title = ""
    badge = _BADGE_LABELS.get(badge_key, badge_key)
    if title and title != tag:
        return f"{tag}   {title}   ·   {badge}"
    return f"{tag}   ·   {badge}"


def _render_release_notes(edit: QTextEdit, body: str) -> None:
    text = (body or "").strip() or "_No release notes provided._"
    edit.document().setDefaultStyleSheet(
        f"""
        body {{ color: {tok.TEXT_PRIMARY}; font-family: {tok.FONT_UI}; font-size: 11px; }}
        h1, h2, h3, h4 {{ color: {tok.TEXT_TITLE}; margin: 10px 0 4px 0; font-size: 12px; }}
        strong {{ color: {tok.TEXT_TITLE}; font-weight: 600; }}
        em {{ color: {tok.TEXT_MUTED}; }}
        li {{ margin: 3px 0; }}
        ul, ol {{ margin: 4px 0 8px 16px; }}
        p {{ margin: 4px 0; }}
        a {{ color: {tok.ACCENT_PRIMARY}; text-decoration: none; }}
        code {{ background: #2a2a2a; padding: 1px 4px; border-radius: 3px; }}
        """
    )
    try:
        edit.setMarkdown(text)
    except Exception:
        # Fallback for odd markdown: strip common markers to readable plain text.
        plain = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        plain = re.sub(r"^#+\s*", "", plain, flags=re.MULTILINE)
        edit.setPlainText(plain)


class _ReleaseFetchThread(QThread):
    finished_ok = Signal(list)
    finished_error = Signal(str)

    def run(self):
        try:
            releases = fetch_releases()
            self.finished_ok.emit(releases)
        except FetchError as exc:
            self.finished_error.emit(str(exc))
        except Exception as exc:
            logging.exception("UPDATE_CENTER: release fetch failed")
            self.finished_error.emit(f"Could not load releases:\n{exc}")


class UpdateCenterDialog(SteempegDialog):
    """Frameless sheet for browsing and installing any public release."""

    install_requested = Signal(object)  # ReleaseEntry
    restore_requested = Signal(object)  # LocalBackup

    def __init__(
        self,
        *,
        local_backups: list[LocalBackup],
        parent=None,
        bar_color: str | None = None,
        bg_color: str | None = None,
    ):
        super().__init__("Update Center", parent, bar_color=bar_color, bg_color=bg_color)
        self.setMinimumSize(560, 560)
        self.resize(620, 640)
        self._releases: list[ReleaseEntry] = []
        self._local_backups = local_backups
        self._fetch_thread: _ReleaseFetchThread | None = None

        self.setStyleSheet(self.styleSheet() + _LIST_STYLE + _NOTES_STYLE)

        root = self.content_layout

        header = QLabel(f"You are on <b>v{APP_VERSION_STR}</b>")
        header.setTextFormat(Qt.TextFormat.RichText)
        header.setStyleSheet(f"color: {tok.TEXT_TITLE}; font-size: 14px; font-weight: bold;")
        root.addWidget(header)

        self._status_label = QLabel("Loading releases from GitHub…")
        self._status_label.setStyleSheet(f"color: {tok.TEXT_MUTED}; font-size: 11px;")
        root.addWidget(self._status_label)

        self._release_list = QListWidget()
        self._release_list.setMinimumHeight(180)
        self._release_list.currentRowChanged.connect(self._on_release_selected)
        root.addWidget(self._release_list, 1)

        notes_label = QLabel("Release notes")
        notes_label.setStyleSheet(f"color: {tok.TEXT_MUTED}; font-size: 11px;")
        root.addWidget(notes_label)

        self._notes = QTextEdit()
        self._notes.setReadOnly(True)
        self._notes.setMinimumHeight(100)
        self._notes.setPlaceholderText("Select a release to preview its notes.")
        root.addWidget(self._notes)

        self._warning_label = QLabel()
        self._warning_label.setWordWrap(True)
        self._warning_label.setStyleSheet("color: #e8b86d; font-size: 11px;")
        self._warning_label.hide()
        root.addWidget(self._warning_label)

        self._downgrade_check = QCheckBox(
            "I understand settings, queue, and rendered sidecars may not match the target version."
        )
        self._downgrade_check.setStyleSheet(f"color: {tok.TEXT_PRIMARY}; font-size: 11px;")
        self._downgrade_check.hide()
        self._downgrade_check.stateChanged.connect(self._refresh_actions)
        root.addWidget(self._downgrade_check)

        if len(local_backups) > 1:
            backup_row = QHBoxLayout()
            backup_label = QLabel("Local backup")
            backup_label.setStyleSheet(f"color: {tok.TEXT_MUTED}; font-size: 11px;")
            backup_row.addWidget(backup_label)
            self._backup_combo = QComboBox()
            for backup in local_backups:
                self._backup_combo.addItem(f"v{backup.version_str} ({backup.folder_name})", backup)
            self._backup_combo.setStyleSheet(
                "QComboBox { background: #242424; color: #ddd; border: 1px solid #555; "
                "border-radius: 6px; padding: 4px 8px; }"
            )
            backup_row.addWidget(self._backup_combo, 1)
            root.addLayout(backup_row)
        else:
            self._backup_combo = None

        actions = QHBoxLayout()
        actions.setSpacing(8)

        self._btn_install = QPushButton("Install selected")
        self._btn_install.setCursor(Qt.PointingHandCursor)
        self._btn_install.setStyleSheet(_BTN_PRIMARY)
        self._btn_install.setEnabled(False)
        self._btn_install.clicked.connect(self._on_install_clicked)
        actions.addWidget(self._btn_install)

        self._btn_github = QPushButton("Open on GitHub")
        self._btn_github.setCursor(Qt.PointingHandCursor)
        self._btn_github.setStyleSheet(_BTN_SECONDARY)
        self._btn_github.setEnabled(False)
        self._btn_github.clicked.connect(self._on_github_clicked)
        actions.addWidget(self._btn_github)

        self._btn_restore = QPushButton("Restore local backup")
        self._btn_restore.setCursor(Qt.PointingHandCursor)
        self._btn_restore.setStyleSheet(_BTN_SECONDARY)
        self._btn_restore.setVisible(bool(local_backups))
        self._btn_restore.clicked.connect(self._on_restore_clicked)
        actions.addWidget(self._btn_restore)

        actions.addStretch()
        root.addLayout(actions)

        self._start_fetch()

    def _start_fetch(self):
        self._fetch_thread = _ReleaseFetchThread(self)
        self._fetch_thread.finished_ok.connect(self._on_releases_loaded)
        self._fetch_thread.finished_error.connect(self._on_fetch_error)
        self._fetch_thread.start()

    def _on_releases_loaded(self, releases: list):
        self._releases = releases
        self._release_list.clear()

        if not releases:
            self._status_label.setText("No public releases found.")
            return

        self._status_label.setText(f"{len(releases)} public releases — newest first.")
        current_row = 0
        for index, entry in enumerate(releases):
            badge_key = entry.badge(APP_VERSION_FLOAT)
            item = QListWidgetItem(_release_row_text(entry, badge_key))
            item.setData(Qt.ItemDataRole.UserRole, entry)
            item.setToolTip(entry.html_url)
            badge_color = _BADGE_COLORS.get(badge_key, "#aaaaaa")
            item.setForeground(QColor(badge_color) if badge_key in ("manual only", "unavailable") else QColor("#e0e0e0"))
            self._release_list.addItem(item)

            if badge_key == "current":
                current_row = index

        self._release_list.setCurrentRow(current_row)
        self._refresh_actions()

    def _on_fetch_error(self, message: str):
        self._status_label.setText(message)
        self._status_label.setStyleSheet("color: #ff8a80; font-size: 11px;")

    def _selected_release(self) -> ReleaseEntry | None:
        item = self._release_list.currentItem()
        if not item:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _on_release_selected(self, _row: int):
        entry = self._selected_release()
        if entry:
            _render_release_notes(self._notes, entry.body)
        else:
            self._notes.clear()
        self._refresh_actions()

    def _refresh_actions(self):
        entry = self._selected_release()
        self._btn_github.setEnabled(entry is not None)

        if not entry:
            self._btn_install.setEnabled(False)
            self._warning_label.hide()
            self._downgrade_check.hide()
            return

        is_downgrade = entry.version_float < APP_VERSION_FLOAT - 0.001
        is_current = abs(entry.version_float - APP_VERSION_FLOAT) < 0.001
        can_install = entry.installable and not is_current

        warnings = jump_warnings(APP_VERSION_FLOAT, entry.version_float)
        if warnings:
            self._warning_label.setText("⚠ " + " ".join(warnings))
            self._warning_label.show()
        else:
            self._warning_label.hide()

        if is_downgrade and can_install:
            self._downgrade_check.show()
            can_install = self._downgrade_check.isChecked()
        else:
            self._downgrade_check.hide()
            self._downgrade_check.setChecked(False)

        if entry.installable:
            if is_current:
                self._btn_install.setText("Already on this version")
            elif entry.version_float > APP_VERSION_FLOAT:
                self._btn_install.setText(f"Upgrade to v{entry.version_str}")
            else:
                self._btn_install.setText(f"Downgrade to v{entry.version_str}")
        else:
            if entry.era.value == "alpha":
                self._btn_install.setText("Manual install only (pre-updater)")
            elif entry.era.value in ("browser", "early"):
                self._btn_install.setText("Open GitHub to install")
            else:
                self._btn_install.setText("No .zip available")

        self._btn_install.setEnabled(can_install)

    def _on_install_clicked(self):
        entry = self._selected_release()
        if not entry:
            return

        if not entry.installable:
            webbrowser.open(entry.html_url)
            return

        warnings = jump_warnings(APP_VERSION_FLOAT, entry.version_float)
        if warnings:
            detail = "\n".join(f"• {line}" for line in warnings)
            reply = QMessageBox.warning(
                self,
                "Large version jump",
                f"Installing v{entry.version_str} may affect compatibility:\n\n{detail}\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.install_requested.emit(entry)
        self.accept()

    def _on_github_clicked(self):
        entry = self._selected_release()
        if entry:
            webbrowser.open(entry.html_url)

    def _on_restore_clicked(self):
        if not self._local_backups:
            return

        backup = self._selected_backup()
        if not backup:
            return

        reply = QMessageBox.question(
            self,
            "Restore local backup",
            f"Restore backed-up v{backup.version_str} from:\n{backup.folder_name}\n\n"
            "Current files will be moved aside before restore.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.restore_requested.emit(backup)
        self.accept()

    def _selected_backup(self) -> LocalBackup | None:
        if self._backup_combo is not None:
            return self._backup_combo.currentData()
        return self._local_backups[0] if self._local_backups else None
