"""The notice inbox and first-launch release highlights."""
from __future__ import annotations

import json
import re
import webbrowser

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout

from steempeg.ui import ui_theme as ut
from steempeg.ui.widgets.dialog_chrome import SteempegDialog


def request_release_json(parent, url: str, callback, *, limit: int) -> None:
    """Fetch a bounded JSON document off the UI's critical path using Qt networking."""
    manager = QNetworkAccessManager(parent)
    request = QNetworkRequest(QUrl(url))
    request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                         QNetworkRequest.RedirectPolicy.SameOriginRedirectPolicy)
    reply = manager.get(request)
    timeout = QTimer(reply, singleShot=True, interval=8000)
    timeout.timeout.connect(reply.abort)
    data = bytearray()

    def read_pending():
        data.extend(bytes(reply.read(limit + 1 - len(data))))
        if len(data) > limit:
            reply.abort()

    def finish():
        timeout.stop()
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                data.extend(bytes(reply.read(limit + 1 - len(data))))
                if len(data) <= limit:
                    try:
                        payload = json.loads(data)
                    except (ValueError, UnicodeError, RecursionError):
                        return
                    callback(payload)
        finally:
            manager.deleteLater()

    reply.readyRead.connect(read_pending)
    reply.finished.connect(finish)
    timeout.start()


def release_highlights(body: str) -> str:
    """Extract the first few short changelog bullets for the welcome card."""
    bullets = re.findall(r"^\s*[-*+]\s+(.+)$", body, re.MULTILINE)
    highlights = []
    for bullet in bullets:
        bullet = re.sub(r"!\[[^]]*\]\([^)]*\)", "", bullet)
        bullet = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", bullet)
        bullet = bullet.replace("**", "").replace("`", "").strip()
        if bullet:
            highlights.append("• " + (bullet if len(bullet) <= 240 else bullet[:237].rstrip() + "…"))
        if len(highlights) == 6:
            break
    return "\n\n".join(highlights)


def add_release_card(dialog, title: str, description: str) -> QVBoxLayout:
    colors = ut._frameless_card_dialog_colors()
    frame = QFrame()
    frame.setObjectName("ReleaseCard")
    ut.set_stylesheet_if_changed(
        frame, f"QFrame#ReleaseCard {{ background: {colors['card_bg']};"
               f" border: 1px solid {colors['card_border']}; border-radius: 12px; }}"
    )
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(8)
    heading = QLabel(title)
    heading.setTextFormat(Qt.TextFormat.PlainText)
    heading.setWordWrap(True)
    heading.setStyleSheet("font-size: 20px; font-weight: bold; color: #eeeeee;")
    layout.addWidget(heading)
    if description:
        caption = QLabel(description)
        caption.setTextFormat(Qt.TextFormat.PlainText)
        caption.setWordWrap(True)
        caption.setStyleSheet("font-size: 13px; color: #cccccc;")
        layout.addWidget(caption)
    dialog.content_layout.addWidget(frame)
    return layout


def release_button(layout, label, callback, *, primary=False):
    button = QPushButton(label)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    style = ut.about_accent_button_stylesheet if primary else ut.about_secondary_button_stylesheet
    ut.set_stylesheet_if_changed(button, style())
    button.clicked.connect(callback)
    layout.addWidget(button)
    return button


def release_text(parent, message: str) -> QTextEdit:
    edit = QTextEdit(parent)
    edit.setReadOnly(True)
    edit.setAcceptRichText(False)
    edit.setFrameShape(QFrame.Shape.NoFrame)
    edit.setStyleSheet("background: transparent; color: #e0e0e0; font-size: 13px;")
    edit.setPlainText(message)
    return edit


class WhatsNewDialog(SteempegDialog):
    def __init__(self, version, previous, changelog_url, parent=None):
        super().__init__("What's new", parent)
        self.set_comfort_size(540, 400)
        card = add_release_card(self, f"What's new in v{version}", f"Updated from v{previous}")
        self._notes = release_text(self, "Open the full changelog to read the release notes.")
        self._notes.setMinimumHeight(135)
        card.addWidget(self._notes, 1)
        actions = QHBoxLayout()
        release_button(actions, "Full changelog", lambda: webbrowser.open(changelog_url))
        actions.addStretch()
        release_button(actions, "Continue", self.accept, primary=True)
        self.content_layout.addLayout(actions)

    def set_notes(self, body: str):
        text = release_highlights(body)
        if text:
            self._notes.setPlainText(text)


class ReleaseNoticesDialog(SteempegDialog):
    def __init__(self, notices, parent=None):
        super().__init__("Announcements", parent)
        self.set_comfort_size(500, 345)
        self.open_update_center = False
        entries = [
            (f"Important · {notice.title}" if notice.critical else notice.title) + "\n" + notice.message
            for notice in notices
        ]
        card = add_release_card(self, "Steempeg announcements", "")
        card.addWidget(release_text(self, "\n\n".join(entries) or "You're all caught up."), 1)
        actions = QHBoxLayout()
        if any(notice.offer_update for notice in notices):
            release_button(actions, "Open Update Center", self._choose_update, primary=True)
        actions.addStretch()
        release_button(actions, "Close", self.accept)
        self.content_layout.addLayout(actions)

    def _choose_update(self):
        self.open_update_center = True
        self.accept()
