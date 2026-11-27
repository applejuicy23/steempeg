"""The notice inbox and first-launch release highlights."""
from __future__ import annotations

import json
import webbrowser

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QScrollArea, QSizePolicy, QTextEdit,
    QVBoxLayout, QWidget,
)

from steempeg.ui import design_tokens as tok
from steempeg.ui import ui_theme as ut
from steempeg.services.release_catalog import REPO
from steempeg.infra.paths import get_resource_path
from steempeg.ui.icon_utils import app_logo_pixmap
from steempeg.ui.pro_appearance import accent_qcolor, visible_accent
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


def add_release_card(
    dialog, title: str, description: str, *, artwork: str = "", heading_detail: QLabel | None = None
) -> QVBoxLayout:
    colors = ut._frameless_card_dialog_colors()
    frame = QFrame()
    frame.setObjectName("ReleaseCard")
    ut.set_stylesheet_if_changed(
        frame, f"QFrame#ReleaseCard {{ background: {colors['card_bg']};"
               f" border: 1px solid {colors['card_border']}; border-radius: 12px; }}"
    )
    outer = QHBoxLayout(frame)
    outer.setContentsMargins(16, 14, 16, 14)
    outer.setSpacing(16)
    if artwork:
        mascot = QLabel(frame)
        mascot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        artwork_pixmap = QPixmap(get_resource_path(artwork))
        if not artwork_pixmap.isNull():
            artwork_pixmap = artwork_pixmap.scaledToHeight(
                124, Qt.TransformationMode.SmoothTransformation
            )
            mascot.setPixmap(artwork_pixmap)
            mascot.setFixedSize(artwork_pixmap.size())
            frame.setMinimumHeight(mascot.height() + outer.contentsMargins().top()
                                   + outer.contentsMargins().bottom() + frame.lineWidth() * 2)
            outer.addWidget(mascot, 0, Qt.AlignmentFlag.AlignBottom)
    layout = QVBoxLayout()
    layout.setSpacing(3 if artwork else 8)
    outer.addLayout(layout, 1)
    heading = QLabel(title)
    heading.setTextFormat(Qt.TextFormat.PlainText)
    heading.setWordWrap(True)
    heading.setStyleSheet("font-size: 20px; font-weight: bold; color: #eeeeee;")
    if heading_detail is None:
        layout.addWidget(heading)
    else:
        heading_row = QHBoxLayout()
        heading_row.addWidget(heading, 1)
        heading_row.addWidget(heading_detail, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(heading_row)
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


class WhatsNewDialog(SteempegDialog):
    def __init__(self, version, previous, changelog_url, parent=None):
        super().__init__("Steempeg is Updated!", parent)
        self.set_comfort_size(740, 880)
        self._notes_image_loader = None
        self.finished.connect(self._cancel_notes_images)

        header = QVBoxLayout()
        header.setSpacing(6)
        alignment = Qt.AlignmentFlag.AlignHCenter
        logo = app_logo_pixmap(92, dpr=self.devicePixelRatioF())
        if logo is not None and not logo.isNull():
            brand = QLabel()
            brand.setPixmap(logo)
            brand.setFixedSize(92, 92)
            brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header.addWidget(brand, 0, alignment)

        colors = ut._frameless_card_dialog_colors()
        foreground = visible_accent(accent_qcolor(QColor(colors["title"])), QColor(colors["card_bg"]))
        heading = QLabel("Steempeg is Updated!")
        heading.setStyleSheet(
            f"font-family: {tok.FONT_APP}; font-size: 24px; font-weight: bold;"
            f" color: {foreground.name()}; background: transparent;"
        )
        header.addWidget(heading, 0, alignment)

        versions = QLabel(f"{previous} → {version}")
        versions.setTextFormat(Qt.TextFormat.PlainText)
        versions.setStyleSheet(
            f"font-family: {tok.FONT_APP}; font-size: 14px;"
            f" color: {tok.TEXT_MUTED}; background: transparent;"
        )
        header.addWidget(versions, 0, alignment)
        self.content_layout.addLayout(header)

        self._release_date = QLabel()
        self._release_date.setTextFormat(Qt.TextFormat.PlainText)
        self._release_date.setStyleSheet(
            f"color: {tok.TEXT_MUTED}; font-family: {tok.FONT_APP}; "
            "font-size: 12px; background: transparent;"
        )
        self._release_date.hide()
        card = add_release_card(self, f"What's new in v{version}?", "", heading_detail=self._release_date)
        card.parentWidget().setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.content_layout.setStretchFactor(card.parentWidget(), 1)
        self._notes = QTextEdit()
        self._notes.setReadOnly(True)
        self._notes.setMinimumHeight(80)
        self._notes.setStyleSheet(ut.update_center_notes_stylesheet())
        self._notes.setPlaceholderText("Open the full changelog to read the release notes.")
        card.addWidget(self._notes, 1)

        support = add_release_card(
            self,
            "Found a bug?",
            "I usually build and test Steempeg on my own. If something breaks, "
            "let me know on GitHub so I can look into it.",
            artwork="chupiwarn.png",
        )
        support.parentWidget().setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        support.addStretch(1)
        report_actions = QHBoxLayout()
        release_button(
            report_actions, "Open GitHub Issues",
            lambda: webbrowser.open(f"https://github.com/{REPO}/issues"),
        )
        report_actions.addStretch()
        support.addLayout(report_actions)

        footer = QWidget()
        footer.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        actions = QHBoxLayout(footer)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(12)
        release_button(actions, "Full changelog", lambda: webbrowser.open(changelog_url))
        actions.addStretch()
        release_button(actions, "Continue", self.accept, primary=True)
        self.content_layout.addWidget(footer)

    def _resolve_map_size(self) -> QSize:
        work_area = self.screen().availableGeometry()
        return super()._resolve_map_size().boundedTo(work_area.size() - QSize(24, 24))

    def set_notes(self, body: str, *, published_at: str = "") -> None:
        from steempeg.ui.update_center import release_date_label, render_release_notes

        date = release_date_label(published_at)
        if date:
            self._release_date.setText(date)
            self._release_date.show()
        self._cancel_notes_images()
        self._notes_image_loader = render_release_notes(self._notes, body, self)

    def _cancel_notes_images(self) -> None:
        if self._notes_image_loader is not None:
            self._notes_image_loader.cancel()
            self._notes_image_loader.deleteLater()
            self._notes_image_loader = None


class ReleaseNoticesPopup(QWidget):
    """A scrollable inbox and notice details anchored to the title bar bell."""

    closed = Signal()
    update_requested = Signal()

    def __init__(self, bell):
        super().__init__(bell, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._bell = bell
        self._notices = []
        self._unread: set[str] = set()
        self._list_scroll = 0
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Steempeg announcements")

        colors = ut.card_size_popup_chrome()
        foreground = ut.menu_popup_colors().fg
        accent = visible_accent(accent_qcolor(QColor("#b29ae7")), QColor(colors.tile_bg)).name()
        self.setStyleSheet(f"""
            QFrame#ReleaseNoticesCard {{
                background: {colors.panel_bg}; border: 1px solid {colors.panel_border};
                border-radius: 12px;
            }}
            QLabel {{ color: {foreground}; background: transparent; font-family: {tok.FONT_APP}; }}
            QLabel#NoticeHeading {{ font-size: 16px; font-weight: bold; }}
            QLabel#NoticeTitle {{ font-size: 14px; font-weight: bold; }}
            QLabel#NoticeSummary {{ color: {colors.label}; font-size: 13px; }}
            QLabel#NoticeTag {{ color: {accent}; font-size: 12px; font-weight: bold; }}
            QWidget#NoticeBody {{ background: transparent; }}
            QFrame#NoticeRow, QPushButton#NoticeRow {{
                background: {colors.tile_bg}; border: 1px solid {colors.tile_border};
                border-radius: 8px;
            }}
            QPushButton#NoticeRow:hover, QPushButton#NoticeRow:focus {{
                background: {colors.tile_hover_bg}; border-color: {accent};
            }}
            {tok.dialog_scroll_stylesheet(colors.panel_bg)}
            QScrollBar:vertical {{ background: {colors.panel_bg}; width: 6px; margin: 0; }}
            QScrollBar::handle:vertical {{ background: {accent}; border-radius: 3px; min-height: 24px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame(self)
        card.setObjectName("ReleaseNoticesCard")
        outer.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        heading = QHBoxLayout()
        self._back = release_button(heading, "‹ Back", self._show_list)
        self._back.hide()
        heading.addWidget(self._label("Announcements", "NoticeHeading"), 1)
        layout.addLayout(heading)

        self._scroll = QScrollArea(self)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self._scroll, 1)

    def set_notices(self, notices, unread_ids: set[str]) -> None:
        self._notices = notices
        self._unread = unread_ids
        self._list_scroll = 0
        self._show_list()

    def _label(self, text: str, name: str = "") -> QLabel:
        label = QLabel(self)
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setText(text)
        return label

    def _body_layout(self) -> QVBoxLayout:
        body = QWidget()
        body.setObjectName("NoticeBody")
        layout = QVBoxLayout(body)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(6)
        self._scroll.setWidget(body)
        self._scroll.viewport().setAutoFillBackground(False)
        body.show()
        return layout

    def _place(self, desired_height: int) -> None:
        area = self._bell.screen().availableGeometry()
        below = self._bell.mapToGlobal(QPoint(self._bell.width(), self._bell.height() + 5))
        above = self._bell.mapToGlobal(QPoint(0, -5)).y()
        room_below = area.bottom() - below.y() - 5
        room_above = above - area.top() - 6
        open_below = desired_height <= room_below or room_below >= room_above
        height = min(desired_height, room_below if open_below else room_above)
        width = min(368, area.width() - 12)
        self.setFixedSize(width, max(100, height))
        x = max(area.left() + 6, min(below.x() + 8 - width, area.right() - width - 5))
        self.move(x, below.y() if open_below else above - self.height())

    def _show_list(self) -> None:
        self._back.hide()
        self._place(min(380, 64 + len(self._notices) * 68) if self._notices else 112)
        layout = self._body_layout()
        for notice in self._notices:
            title = self._label("", "NoticeTitle")
            summary = self._label("", "NoticeSummary")
            title.ensurePolished()
            summary.ensurePolished()
            text_width = self.width() - 68
            shown_title = title.fontMetrics().elidedText(
                notice.title, Qt.TextElideMode.ElideRight, text_width
            )
            shown_summary = summary.fontMetrics().elidedText(
                " ".join(notice.message.split()), Qt.TextElideMode.ElideRight, text_width
            )
            title.setText(shown_title)
            summary.setText(shown_summary)
            expandable = (
                notice.details or notice.offer_update
                or shown_title != notice.title or shown_summary != notice.message
            )
            row = QPushButton() if expandable else QFrame()
            row.setObjectName("NoticeRow")
            row.setFixedHeight(62)
            if expandable:
                row.setCursor(Qt.CursorShape.PointingHandCursor)
                row.setAccessibleName(notice.title)
                row.clicked.connect(lambda _checked=False, item=notice: self._show_details(item))
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(10, 5, 10, 5)
            text_layout = QVBoxLayout()
            text_layout.setSpacing(1)
            if notice.critical or notice.id in self._unread:
                tag = self._label("Important" if notice.critical else "New", "NoticeTag")
                tag.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                text_layout.addWidget(tag)
            for label in (title, summary):
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                text_layout.addWidget(label)
            row_layout.addLayout(text_layout, 1)
            if expandable:
                arrow = self._label("›", "NoticeTitle")
                arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                row_layout.addWidget(arrow)
            layout.addWidget(row)
        if not self._notices:
            layout.addWidget(self._label("You're all caught up.", "NoticeSummary"))
        layout.addStretch()
        if self._list_scroll:
            scrollbar = self._scroll.verticalScrollBar()
            QTimer.singleShot(0, self, lambda: scrollbar.setValue(self._list_scroll))

    def _show_details(self, notice) -> None:
        self._list_scroll = self._scroll.verticalScrollBar().value()
        self._back.show()
        self._place(300)
        layout = self._body_layout()
        for text, name in (
            (notice.title, "NoticeTitle"), (notice.message, ""), (notice.details, ""),
        ):
            if text:
                label = self._label(text, name)
                label.setWordWrap(True)
                label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
                label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                layout.addWidget(label)
        if notice.offer_update:
            actions = QHBoxLayout()
            release_button(actions, "Open Update Center", self._choose_update, primary=True)
            actions.addStretch()
            layout.addLayout(actions)
        layout.addStretch()
        self._scroll.verticalScrollBar().setValue(0)
        self._back.setFocus()

    def _choose_update(self) -> None:
        self.close()
        self.update_requested.emit()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        bell_pos = self._bell.mapFromGlobal(event.globalPosition().toPoint())
        if self._bell.rect().contains(bell_pos):
            self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self.closed.emit()
