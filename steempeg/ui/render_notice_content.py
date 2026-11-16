"""Shared content chrome for queue duplicates, render cancellation and deletion."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from steempeg.ui import design_tokens as tok, ui_theme as ut
from steempeg.ui.icon_assets import tinted_pixmap


def _text(text, *, heading=False, muted=False):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setProperty("noticeHeading", heading)
    label.setProperty("noticeMuted", muted)
    return label


def build_render_notice(dialog, kind, message, detail, buttons):
    dialog._render_notice_kind = kind
    dialog._notice_labels = []
    dialog._notice_buttons = []
    dialog._notice_panel = None
    dialog._notice_warning = None
    root = dialog.content_layout
    root.setContentsMargins(20, 20, 20, 18)
    root.setSpacing(16)
    heading, asset = {
        "queue_duplicate": ("Already in Render Queue", "queue.png"),
        "render_cancelled": ("Render cancelled", "cancelrender.png"),
        "render_delete": (dialog.windowTitle(), "cancel.png"),
    }[kind]
    top = QHBoxLayout()
    top.setSpacing(12)
    icon = QLabel()
    icon.setFixedSize(38, 38)
    icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icon.setPixmap(tinted_pixmap(asset, "#e4dcf3", 26))
    icon.setStyleSheet("background: transparent; border: none;")
    title = _text(heading, heading=True)
    dialog._notice_labels.append(title)
    top.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
    top.addWidget(title, 1, Qt.AlignmentFlag.AlignVCenter)
    root.addLayout(top)

    if kind == "queue_duplicate":
        primary, _, secondary = message.partition("\n\n")
        panel_text = primary
        after = secondary
    elif kind == "render_delete":
        summary = _text(message)
        dialog._notice_labels.append(summary)
        root.addWidget(summary)
        # Existing production copy separates the filename list from its warning.
        panel_text, _, warning = (detail or "").rpartition("\n\n")
        if not panel_text:
            warning = detail or ""
        after = ""
        if warning:
            dialog._notice_warning = _text(warning)
    else:
        panel_text = ""
        after = message

    if panel_text:
        panel = QFrame()
        panel.setObjectName("renderNoticePanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        label = _text(panel_text)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        dialog._notice_labels.append(label)
        layout.addWidget(label)
        dialog._notice_panel = panel
        root.addWidget(panel)
    if after:
        label = _text(after, muted=kind == "queue_duplicate")
        dialog._notice_labels.append(label)
        root.addWidget(label)
    if dialog._notice_warning is not None:
        root.addWidget(dialog._notice_warning)

    root.addSpacing(2)
    actions = QHBoxLayout()
    actions.setSpacing(8)
    actions.addStretch(1)
    for index, spec in enumerate(buttons):
        button = QPushButton(spec.label)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAutoDefault(False)
        button.clicked.connect(lambda _=False, i=index, acc=spec.accept: dialog._on_button(i, acc))
        dialog._notice_buttons.append((button, spec.role))
        actions.addWidget(button)
    root.addLayout(actions)
    refresh_render_notice_theme(dialog)
    from steempeg.ui.ui_density import scaled_dialog_size

    width, _ = scaled_dialog_size(460 if kind == "render_delete" else 420, 200, parent=dialog.parentWidget())
    dialog.setMinimumWidth(width)
    fit_render_notice(dialog, width)


def fit_render_notice(dialog, width=None):
    """Resolve wrapped filename height before mapping, including a late checkbox."""
    width = width or dialog.width()
    dialog.ensurePolished()
    panel = dialog._notice_panel
    if panel is not None:
        label = panel.layout().itemAt(0).widget()
        # Width excludes the dialog rails, content margins and panel padding.
        text_width = max(1, width - 4 - 40 - 28)
        label.setMinimumHeight(label.heightForWidth(text_width))
        panel.setMinimumHeight(label.minimumHeight() + 26)
    dialog.layout().activate()
    dialog.content_layout.invalidate()
    height = dialog.content_layout.totalHeightForWidth(max(1, width - 4)) + dialog._title_bar.height() + 2
    dialog.resize(width, height)


def refresh_render_notice_theme(dialog):
    palette = ut.active_palette()
    for label in dialog._notice_labels:
        heading = label.property("noticeHeading")
        color = tok.TEXT_MUTED if label.property("noticeMuted") else tok.TEXT_PRIMARY
        label.setStyleSheet(
            f"background: transparent; border: none; color: {color}; "
            f"font-family: {tok.FONT_SEMIBOLD if heading else tok.FONT_APP}; "
            f"font-size: {16 if heading else 13}px; font-weight: {700 if heading else 400};"
        )
    if dialog._notice_panel is not None:
        dialog._notice_panel.setStyleSheet(
            f"QFrame#renderNoticePanel {{background: {palette.bg_card}; "
            f"border: 1px solid {palette.border_card}; border-radius: 10px;}}"
        )
    if dialog._notice_warning is not None:
        dialog._notice_warning.setStyleSheet(
            f"background: transparent; color: #e5a7a7; font-family: {tok.FONT_APP}; font-size: 12px;"
        )
    styles = {"primary": ut.about_accent_button_stylesheet,
              "secondary": ut.about_secondary_button_stylesheet,
              "danger": ut.about_danger_button_stylesheet}
    for button, role in dialog._notice_buttons:
        button.setStyleSheet(styles[role]())
