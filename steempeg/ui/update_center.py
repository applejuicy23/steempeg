"""Update Center — pick any installable release to upgrade or downgrade."""
from __future__ import annotations

import logging
import os
import re
import webbrowser

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.paths import get_resource_path
from steempeg.services.release_catalog import (
    FetchError,
    InstallTier,
    LocalBackup,
    RateLimitInfo,
    ReleaseEntry,
    default_selected_release,
    fetch_releases,
    group_releases_by_major,
    info_tooltip_text,
    latest_release_version,
    selection_marker_text,
    selection_notice,
    shows_info_icon,
    version_label_color,
    versions_equal,
)
from steempeg.ui import design_tokens as tok
from steempeg.ui.widgets.dialog_chrome import SteempegDialog
from steempeg.version import APP_VERSION_FLOAT, APP_VERSION_STR

_ROW_NORMAL = """
    QFrame#versionRow {
        background-color: #2a2a2a;
        border: 1px solid #353535;
        border-radius: 8px;
    }
"""
_ROW_SELECTED = """
    QFrame#versionRow {
        background-color: #3a324a;
        border: 1px solid #6b5a8e;
        border-radius: 8px;
    }
"""
_ROW_CHILD = """
    QFrame#versionRow {
        background-color: #262626;
        border: 1px solid #333333;
        border-radius: 6px;
    }
"""

_SCROLL_STYLE = """
    QScrollArea { background: transparent; border: none; }
    QWidget#releaseListHost { background: transparent; }
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

_ICON_BTN = """
    QPushButton {
        background-color: #383838; color: #ccc; border: 1px solid #555;
        border-radius: 10px; min-width: 20px; max-width: 20px;
        min-height: 20px; max-height: 20px; font-size: 10px; font-weight: bold; padding: 0;
    }
    QPushButton:hover { background-color: #454545; color: #fff; border-color: #6b5a8e; }
"""

_ACK_FRAME_STYLE = """
    QFrame#updateAckFrame {
        background-color: #3a324a;
        border: 1px solid #6b5a8e;
        border-radius: 8px;
    }
    QFrame#updateAckFrame QCheckBox {
        color: #ffffff;
        font-family: """ + tok.FONT_APP + """;
        font-size: 11px;
        background: transparent;
        spacing: 8px;
    }
    QFrame#updateAckFrame QCheckBox::indicator {
        width: 16px;
        height: 16px;
        border: 1px solid #b29ae7;
        border-radius: 4px;
        background: #2a2238;
    }
    QFrame#updateAckFrame QCheckBox::indicator:checked {
        background: #6b5a8e;
        border-color: #b29ae7;
    }
"""

_NOTICE_WARN = f"color: #e8b86d; font-size: 11px; font-family: {tok.FONT_APP};"
_NOTICE_DANGER = f"color: #ff8a80; font-size: 11px; font-family: {tok.FONT_APP};"


def _logo_pixmap(size: int = 18) -> QPixmap | None:
    path = get_resource_path("logo.png")
    if not os.path.isfile(path):
        return None
    return QPixmap(path).scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )


def _sanitize_notes(text: str) -> str:
    return text.replace(" — ", ": ").replace("— ", "")


def _render_release_notes(edit: QTextEdit, body: str) -> None:
    text = _sanitize_notes((body or "").strip() or "_No release notes provided._")
    edit.document().setDefaultStyleSheet(
        f"""
        body {{ color: {tok.TEXT_PRIMARY}; font-family: {tok.FONT_UI}; font-size: 11px; }}
        h1, h2, h3, h4 {{ color: {tok.TEXT_TITLE}; margin: 10px 0 4px 0; font-size: 12px; }}
        strong {{ color: {tok.TEXT_TITLE}; font-weight: 600; }}
        li {{ margin: 3px 0; }}
        ul, ol {{ margin: 4px 0 8px 16px; }}
        p {{ margin: 4px 0; }}
        a {{ color: {tok.ACCENT_PRIMARY}; text-decoration: none; }}
        """
    )
    try:
        edit.setMarkdown(text)
    except Exception:
        plain = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        edit.setPlainText(plain)


class _VersionRow(QFrame):
    """Single release row: logo, version label, optional (i) and expand buttons."""

    activated = Signal(object)

    def __init__(
        self,
        entry: ReleaseEntry,
        *,
        installed: float,
        latest: float,
        indent: int = 0,
        expand_handler=None,
        expanded: bool = False,
    ):
        super().__init__()
        self._entry = entry
        self._indent = indent
        self._installed = installed
        self._latest = latest
        self._expand_handler = expand_handler
        self.setObjectName("versionRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(_ROW_CHILD if indent else _ROW_NORMAL)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8 + indent * 14, 6, 8, 6)
        outer.setSpacing(8)

        logo = QLabel()
        pix = _logo_pixmap(18 if not indent else 16)
        if pix is not None:
            logo.setPixmap(pix)
        logo.setFixedSize(18 if not indent else 16, 18 if not indent else 16)
        outer.addWidget(logo)

        label = entry.tag_name or f"v{entry.version_str}"
        color = version_label_color(entry.version_float, installed=installed, latest=latest)
        self._version_label = QLabel(label)
        self._version_label.setStyleSheet(
            f"color: {color}; "
            f"font-size: {'12px' if not indent else '11px'}; font-weight: 600; background: transparent;"
        )
        outer.addWidget(self._version_label)
        outer.addStretch()

        if shows_info_icon(entry):
            tip = info_tooltip_text(entry)
            info_btn = QPushButton("i")
            if tip:
                info_btn.setToolTip(tip)
            info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            info_btn.setStyleSheet(_ICON_BTN)
            info_btn.clicked.connect(lambda *_: None)
            info_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            outer.addWidget(info_btn)

        if expand_handler is not None:
            self._expand_btn = QPushButton("▾" if expanded else "▸")
            self._expand_btn.setToolTip("Show other patches in this version line")
            self._expand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._expand_btn.setStyleSheet(_ICON_BTN)
            self._expand_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._expand_btn.clicked.connect(self._on_expand_clicked)
            outer.addWidget(self._expand_btn)
        else:
            self._expand_btn = None

    def _on_expand_clicked(self):
        if self._expand_handler:
            self._expand_handler()

    def set_expanded(self, expanded: bool) -> None:
        if self._expand_btn is not None:
            self._expand_btn.setText("▾" if expanded else "▸")

    def set_selected(self, selected: bool) -> None:
        if selected:
            self.setStyleSheet(_ROW_SELECTED)
        else:
            self.setStyleSheet(_ROW_CHILD if self._indent else _ROW_NORMAL)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self._entry)
            event.accept()
        else:
            super().mousePressEvent(event)


class _PatchGroupWidget(QWidget):
    """Collapsed by default: shows newest patch; expand reveals older patches."""

    activated = Signal(object)

    def __init__(self, group: list[ReleaseEntry], *, installed: float, latest: float):
        super().__init__()
        self._group = group
        self._installed = installed
        self._latest = latest
        self._expanded = False
        self._rows: list[_VersionRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._child_host = QWidget()
        child_layout = QVBoxLayout(self._child_host)
        child_layout.setContentsMargins(0, 0, 0, 0)
        child_layout.setSpacing(4)

        header = _VersionRow(
            group[0],
            installed=installed,
            latest=latest,
            expand_handler=self._toggle,
            expanded=False,
        )
        header.activated.connect(self.activated.emit)
        layout.addWidget(header)
        self._rows.append(header)

        for entry in group[1:]:
            row = _VersionRow(
                entry,
                installed=installed,
                latest=latest,
                indent=1,
            )
            row.activated.connect(self.activated.emit)
            child_layout.addWidget(row)
            self._rows.append(row)

        layout.addWidget(self._child_host)
        self._child_host.hide()

    def _toggle(self):
        self._expanded = not self._expanded
        self._child_host.setVisible(self._expanded)
        self._rows[0].set_expanded(self._expanded)

    def expand(self):
        if not self._expanded:
            self._toggle()

    def set_selected_entry(self, entry: ReleaseEntry | None) -> None:
        for row in self._rows:
            row.set_selected(entry is not None and row._entry.version_float == entry.version_float)


class _ReleaseFetchThread(QThread):
    finished_ok = Signal(list)
    finished_error = Signal(str)
    finished_rate_limited = Signal(object)

    def run(self):
        try:
            releases = fetch_releases()
            self.finished_ok.emit(releases)
        except FetchError as exc:
            if exc.rate_limit:
                self.finished_rate_limited.emit(exc.rate_limit)
            else:
                self.finished_error.emit(str(exc))
        except Exception as exc:
            logging.exception("UPDATE_CENTER: release fetch failed")
            self.finished_error.emit(f"Could not load releases:\n{exc}")


class UpdateCenterDialog(SteempegDialog):
    install_requested = Signal(object)
    restore_requested = Signal(object)
    rate_limited = Signal(object)

    def __init__(
        self,
        *,
        local_backups: list[LocalBackup],
        parent=None,
        bar_color: str | None = None,
        bg_color: str | None = None,
    ):
        super().__init__("Update Center", parent, bar_color=bar_color, bg_color=bg_color)
        self.setMinimumSize(520, 520)
        self.resize(560, 600)
        self._releases: list[ReleaseEntry] = []
        self._local_backups = local_backups
        self._fetch_thread: _ReleaseFetchThread | None = None
        self._selected: ReleaseEntry | None = None
        self._latest_version = APP_VERSION_FLOAT
        self._row_widgets: list[_VersionRow | _PatchGroupWidget] = []
        self._group_widgets: list[_PatchGroupWidget] = []

        self.setStyleSheet(self.styleSheet() + _SCROLL_STYLE + _NOTES_STYLE)

        root = self.content_layout

        title = QLabel("Update Center")
        title.setStyleSheet(tok.STYLE_PANEL_TITLE)
        root.addWidget(title)

        version_line = QLabel(f"Current version is v{APP_VERSION_STR}")
        version_line.setStyleSheet(tok.STYLE_PANEL_SUBTITLE)
        root.addWidget(version_line)

        self._status_label = QLabel("Loading releases…")
        self._status_label.setStyleSheet(f"color: {tok.TEXT_MUTED}; font-size: 11px;")
        root.addWidget(self._status_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_host = QWidget()
        self._list_host.setObjectName("releaseListHost")
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 4, 0)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch()
        scroll.setWidget(self._list_host)
        scroll.setMinimumHeight(200)
        root.addWidget(scroll, 1)

        notes_label = QLabel("Release notes")
        notes_label.setStyleSheet(f"color: {tok.TEXT_MUTED}; font-size: 11px;")
        root.addWidget(notes_label)

        self._notes = QTextEdit()
        self._notes.setReadOnly(True)
        self._notes.setMinimumHeight(90)
        self._notes.setPlaceholderText("Select a version.")
        root.addWidget(self._notes)

        self._notice_label = QLabel()
        self._notice_label.setWordWrap(True)
        self._notice_label.setStyleSheet(_NOTICE_WARN)
        self._notice_label.hide()
        root.addWidget(self._notice_label)

        self._marker_label = QLabel()
        self._marker_label.setWordWrap(True)
        self._marker_label.setStyleSheet(
            f"color: {tok.ACCENT_PRIMARY}; font-family: {tok.FONT_UI}; "
            "font-size: 11px; font-weight: 600; background: transparent;"
        )
        self._marker_label.hide()
        root.addWidget(self._marker_label)

        self._ack_frame = QFrame()
        self._ack_frame.setObjectName("updateAckFrame")
        ack_layout = QHBoxLayout(self._ack_frame)
        ack_layout.setContentsMargins(10, 8, 10, 8)
        self._ack_check = QCheckBox(
            "I understand settings, queue, and rendered sidecars may not match the target version."
        )
        self._ack_check.stateChanged.connect(self._refresh_actions)
        ack_layout.addWidget(self._ack_check)
        self._ack_frame.setStyleSheet(_ACK_FRAME_STYLE)
        self._ack_frame.hide()
        root.addWidget(self._ack_frame)

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
        self._btn_install.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_install.setStyleSheet(_BTN_PRIMARY)
        self._btn_install.setEnabled(False)
        self._btn_install.clicked.connect(self._on_install_clicked)
        actions.addWidget(self._btn_install)

        self._btn_github = QPushButton("Open on GitHub")
        self._btn_github.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_github.setStyleSheet(_BTN_SECONDARY)
        self._btn_github.setEnabled(False)
        self._btn_github.clicked.connect(self._on_github_clicked)
        actions.addWidget(self._btn_github)

        self._btn_restore = QPushButton("Restore local backup")
        self._btn_restore.setCursor(Qt.CursorShape.PointingHandCursor)
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
        self._fetch_thread.finished_rate_limited.connect(self._on_fetch_rate_limited)
        self._fetch_thread.start()

    def _clear_list(self):
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._row_widgets.clear()
        self._group_widgets.clear()

    def _on_releases_loaded(self, releases: list):
        self._releases = releases
        self._clear_list()

        if not releases:
            self._status_label.setText("No public releases found.")
            return

        self._latest_version = latest_release_version(releases)
        latest_str = releases[0].version_str
        if self._latest_version > APP_VERSION_FLOAT + 0.001:
            self._status_label.setText(f"Update available: v{latest_str}")
            self._status_label.setStyleSheet("color: #7ec8a3; font-size: 11px; font-weight: 600;")
        else:
            self._status_label.setText(f"{len(releases)} releases · you are on the latest")
            self._status_label.setStyleSheet(f"color: {tok.TEXT_MUTED}; font-size: 11px;")

        groups = group_releases_by_major(releases)
        initial_entry = default_selected_release(releases, APP_VERSION_FLOAT)

        for group in groups:
            if len(group) == 1:
                entry = group[0]
                row = _VersionRow(
                    entry,
                    installed=APP_VERSION_FLOAT,
                    latest=self._latest_version,
                )
                row.activated.connect(self._select_entry)
                self._list_layout.insertWidget(self._list_layout.count() - 1, row)
                self._row_widgets.append(row)
            else:
                block = _PatchGroupWidget(
                    group,
                    installed=APP_VERSION_FLOAT,
                    latest=self._latest_version,
                )
                block.activated.connect(self._select_entry)
                self._list_layout.insertWidget(self._list_layout.count() - 1, block)
                self._row_widgets.append(block)
                self._group_widgets.append(block)

        for block in self._group_widgets:
            for entry in block._group:
                if versions_equal(entry.version_float, initial_entry.version_float):
                    block.expand()
                    break

        self._select_entry(initial_entry)

    def _on_fetch_error(self, message: str):
        self._status_label.setText(message)
        self._status_label.setStyleSheet("color: #ff8a80; font-size: 11px;")

    def _on_fetch_rate_limited(self, info: RateLimitInfo):
        self._status_label.setText("GitHub API rate limit exceeded — waiting to retry…")
        self._status_label.setStyleSheet("color: #e8b86d; font-size: 11px;")
        self.rate_limited.emit(info)
        self.reject()

    def _select_entry(self, entry: ReleaseEntry):
        self._selected = entry
        for widget in self._row_widgets:
            if isinstance(widget, _VersionRow):
                widget.set_selected(widget._entry.version_float == entry.version_float)
            else:
                widget.set_selected_entry(entry)
        _render_release_notes(self._notes, entry.body)

        notice = selection_notice(entry, APP_VERSION_FLOAT)
        if notice:
            self._notice_label.setText(f"⚠️ {notice}")
            if entry.version_float <= 11.0:
                self._notice_label.setStyleSheet(_NOTICE_DANGER)
            else:
                self._notice_label.setStyleSheet(_NOTICE_WARN)
            self._notice_label.show()
        else:
            self._notice_label.hide()

        marker = selection_marker_text(entry)
        if marker:
            self._marker_label.setText(marker)
            self._marker_label.show()
        else:
            self._marker_label.hide()

        self._refresh_actions()

    def _refresh_actions(self):
        entry = self._selected
        self._btn_github.setEnabled(entry is not None)

        if not entry:
            self._btn_install.setEnabled(False)
            self._ack_frame.hide()
            return

        is_current = abs(entry.version_float - APP_VERSION_FLOAT) < 0.001
        is_downgrade = entry.version_float < APP_VERSION_FLOAT - 0.001
        base_can_install = entry.installable and not is_current
        needs_ack = is_downgrade and base_can_install

        if needs_ack:
            self._ack_frame.show()
        else:
            self._ack_frame.hide()
            self._ack_check.setChecked(False)

        can_install = base_can_install and (not needs_ack or self._ack_check.isChecked())

        if entry.install_tier == InstallTier.BROKEN:
            self._btn_install.setText("Blocked")
        elif entry.installable:
            if is_current:
                self._btn_install.setText("Current version")
            elif entry.version_float > APP_VERSION_FLOAT:
                if versions_equal(entry.version_float, self._latest_version):
                    self._btn_install.setText(f"⚙️ Update to v{entry.version_str}")
                else:
                    self._btn_install.setText(f"Upgrade to v{entry.version_str}")
            else:
                self._btn_install.setText(f"Downgrade to v{entry.version_str}")
        elif entry.install_tier == InstallTier.MANUAL:
            self._btn_install.setText("Manual .exe only")
        else:
            self._btn_install.setText("Open on GitHub")

        self._btn_install.setEnabled(can_install)

    def _on_install_clicked(self):
        entry = self._selected
        if not entry:
            return
        if not entry.installable:
            webbrowser.open(entry.html_url)
            return
        self.install_requested.emit(entry)
        self.accept()

    def _on_github_clicked(self):
        if self._selected:
            webbrowser.open(self._selected.html_url)

    def _on_restore_clicked(self):
        if not self._local_backups:
            return
        backup = self._selected_backup()
        if not backup:
            return
        reply = QMessageBox.question(
            self,
            "Restore local backup",
            f"Restore v{backup.version_str} from {backup.folder_name}?",
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
