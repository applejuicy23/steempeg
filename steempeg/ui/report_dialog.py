"""Styled bug-report dialog."""
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra import paths
from steempeg.infra.reports import (
    GITHUB_ISSUES_URL,
    build_report_text,
    collect_context,
    create_report_bundle,
    github_issue_body,
)
from steempeg.version import APP_VERSION_STR
from steempeg.ui.message_dialog import steempeg_critical, steempeg_information


_REPORT_DIALOG_STYLE = """
    QWidget#ReportCard {
        background-color: #202020;
        border: 1px solid #444444;
        border-radius: 8px;
    }
    QLabel#ReportTitle { color: #b29ae7; font-size: 18px; font-weight: bold; }
    QLabel#ReportHint { color: #888888; font-size: 11px; }
    QLabel { background: transparent; color: #dddddd; font-size: 12px; }
    QTextEdit {
        background-color: #2a2a2a;
        color: #eeeeee;
        border: 1px solid #555555;
        border-radius: 6px;
        padding: 8px;
        font-size: 12px;
    }
    QCheckBox { color: #cccccc; font-size: 12px; spacing: 6px; }
    QCheckBox::indicator { width: 14px; height: 14px; }
    QPushButton {
        background-color: #333333;
        color: white;
        border: 1px solid #555555;
        border-radius: 16px;
        padding: 6px 18px;
        font-weight: bold;
        font-size: 12px;
        min-height: 30px;
    }
    QPushButton:hover { background-color: #444444; border: 1px solid #777777; }
    QPushButton:pressed { background-color: #222222; }
    QPushButton#ReportPrimary {
        background-color: #3a324a;
        border: 1px solid #6b5a8e;
    }
    QPushButton#ReportPrimary:hover {
        background-color: #4a3f5c;
        border: 1px solid #b29ae7;
    }
"""


def show_report_dialog(app):
    if getattr(app, "_report_dialog_open", False):
        return
    app._report_dialog_open = True

    dialog = QDialog(app.ui)
    dialog.setWindowFlag(Qt.WindowType.FramelessWindowHint)
    dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    dialog.setFixedSize(560, 460)
    dialog.setStyleSheet(_REPORT_DIALOG_STYLE)

    shell = QVBoxLayout(dialog)
    shell.setContentsMargins(0, 0, 0, 0)

    card = QWidget(dialog)
    card.setObjectName("ReportCard")
    shell.addWidget(card)

    layout = QVBoxLayout(card)
    layout.setContentsMargins(22, 20, 22, 18)
    layout.setSpacing(10)

    title = QLabel(f"Report a bug — v{APP_VERSION_STR}")
    title.setObjectName("ReportTitle")
    layout.addWidget(title)

    hint = QLabel(
        "Describe what went wrong. A report bundle with logs and diagnostics "
        "can be saved or pasted into GitHub Issues."
    )
    hint.setObjectName("ReportHint")
    hint.setWordWrap(True)
    layout.addWidget(hint)

    editor = QTextEdit()
    editor.setPlaceholderText(
        "Example: clip won't render, preview is black, FFmpeg failed at 42%…"
    )
    editor.setMinimumHeight(140)
    layout.addWidget(editor)

    chk_app = QCheckBox("Include App + FFmpeg log")
    chk_app.setChecked(True)
    chk_mpv = QCheckBox("Include MPV player log")
    chk_mpv.setChecked(True)
    layout.addWidget(chk_app)
    layout.addWidget(chk_mpv)

    btn_row = QHBoxLayout()
    btn_row.addStretch()

    btn_cancel = QPushButton("Cancel")
    btn_copy = QPushButton("Copy summary")
    btn_save = QPushButton("Save bundle…")
    btn_save.setObjectName("ReportPrimary")
    btn_github = QPushButton("Open GitHub Issues")
    btn_github.setObjectName("ReportPrimary")

    btn_row.addWidget(btn_cancel)
    btn_row.addWidget(btn_copy)
    btn_row.addWidget(btn_save)
    btn_row.addWidget(btn_github)
    layout.addLayout(btn_row)

    def _description():
        return editor.toPlainText().strip()

    def _context():
        return collect_context(app)

    def on_copy():
        text = build_report_text(_description(), _context())
        QGuiApplication.clipboard().setText(text)
        steempeg_information(dialog, "Copied", "Report summary copied to clipboard.")

    def on_save():
        try:
            path = create_report_bundle(
                app,
                _description(),
                include_app_log=chk_app.isChecked(),
                include_mpv_log=chk_mpv.isChecked(),
            )
            paths.open_in_file_manager(path)
            steempeg_information(
                dialog,
                "Report saved",
                f"Report bundle saved:\n{path}\n\nAttach this zip to a GitHub issue.",
            )
        except Exception as exc:
            steempeg_critical(dialog, "Error", f"Could not create report bundle:\n{exc}")

    def on_github():
        body = github_issue_body(_description(), _context())
        QGuiApplication.clipboard().setText(body)
        webbrowser.open(GITHUB_ISSUES_URL)
        steempeg_information(
            dialog,
            "GitHub Issues",
            "Issue page opened in your browser.\n"
            "The report summary is on your clipboard — paste it into the issue body "
            "and attach the saved bundle if you created one.",
        )

    btn_cancel.clicked.connect(dialog.reject)
    btn_copy.clicked.connect(on_copy)
    btn_save.clicked.connect(on_save)
    btn_github.clicked.connect(on_github)

    dialog.exec()
    app._report_dialog_open = False
