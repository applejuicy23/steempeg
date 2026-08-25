"""Styled bug-report dialog."""
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
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
from steempeg.ui import ui_theme as ut
from steempeg.ui.message_dialog import steempeg_critical, steempeg_information
from steempeg.ui.widgets.steempeg_check import SteempegCheckBox


def show_report_dialog(app):
    if getattr(app, "_report_dialog_open", False):
        return
    app._report_dialog_open = True

    dialog = QDialog(app.ui)
    dialog.setObjectName("SteempegReportDialog")
    dialog.setWindowFlag(Qt.WindowType.FramelessWindowHint)
    dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    from steempeg.ui.ui_density import scaled_dialog_size

    dialog.setFixedSize(*scaled_dialog_size(560, 460, parent=app.ui))
    # TrueDark / OLED via shared frameless card tokens (same family as About).
    dialog.setStyleSheet(ut.report_dialog_stylesheet())

    shell = QVBoxLayout(dialog)
    shell.setContentsMargins(0, 0, 0, 0)

    card = QWidget(dialog)
    card.setObjectName("ReportCard")
    card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
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

    chk_app = SteempegCheckBox("Include App + FFmpeg log", accent_label=False, font_size=12)
    chk_app.setChecked(True)
    chk_mpv = SteempegCheckBox("Include MPV player log", accent_label=False, font_size=12)
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
