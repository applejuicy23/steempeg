"""Update Center — pick any installable release to upgrade or downgrade."""
from __future__ import annotations

import logging
import os
import re
import webbrowser

from PySide6.QtCore import Qt, QThread, Signal, QSize, QUrl, QObject, QTimer
from PySide6.QtGui import QIcon, QPainter, QPixmap, QShowEvent, QTextCursor, QTextDocument, QTextImageFormat
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from steempeg.ui.widgets import FlowLayout

from steempeg.infra.paths import get_resource_path
from steempeg.ui.icon_assets import (
    info_icon,
    load_icon,
    load_pixmap,
    title_bar_update_pixmap,
)
from steempeg.services.release_catalog import (
    FetchError,
    InstallTier,
    LocalBackup,
    MIN_INSTALL_VERSION,
    RateLimitInfo,
    RECOMMENDED_INSTALL_VERSION,
    ReleaseEntry,
    default_selected_release,
    fetch_releases,
    group_releases_by_major,
    info_tooltip_text,
    latest_release_version,
    load_releases_cache,
    platform_display_name,
    selection_marker_text,
    selection_notice,
    shows_info_icon,
    version_label_color,
    versions_equal,
)

from steempeg.ui import design_tokens as tok
from steempeg.ui.widgets.dialog_chrome import SteempegDialog
from steempeg.ui.widgets.combo_chrome import settings_panel_stylesheet
from steempeg.ui.widgets.steempeg_check import SteempegCheckBox
from steempeg.ui.message_dialog import steempeg_question
from steempeg.version import APP_VERSION_FLOAT, APP_VERSION_STR

# Display order for platform availability icons next to a release version.
_PLATFORM_ICON_ORDER = ("windows", "linux", "steamdeck")
_PLATFORM_ASSET = {
    "windows": "windows.png",
    "linux": "linux.png",
    "steamdeck": "steamdeck.png",
}

def _row_stylesheet(*, band: str, selected: bool, indent: bool) -> str:
    from steempeg.ui import ui_theme as ut

    return ut.update_center_row_stylesheet(band=band, selected=selected, indent=indent)


def _scroll_style() -> str:
    from steempeg.ui import ui_theme as ut

    return ut.update_center_scroll_extras_stylesheet(bg_shell=tok.BG_SHELL)


def _notes_style() -> str:
    from steempeg.ui import ui_theme as ut

    return ut.update_center_notes_stylesheet()


def _btn_primary_style() -> str:
    from steempeg.ui import ui_theme as ut

    return ut.update_center_btn_primary_stylesheet()


def _btn_secondary_style() -> str:
    from steempeg.ui import ui_theme as ut

    return ut.update_center_btn_secondary_stylesheet()


def _btn_current_style() -> str:
    from steempeg.ui import ui_theme as ut

    return ut.update_center_btn_current_stylesheet()


def _icon_btn_style() -> str:
    from steempeg.ui import ui_theme as ut

    return ut.update_center_icon_btn_stylesheet()


def _ack_frame_style() -> str:
    from steempeg.ui import ui_theme as ut

    return ut.update_center_ack_frame_stylesheet()


def _backup_frame_style() -> str:
    from steempeg.ui import ui_theme as ut

    return ut.update_center_backup_frame_stylesheet()


_SCROLL_STYLE = _scroll_style()
_NOTES_STYLE = _notes_style()
_BTN_PRIMARY = _btn_primary_style()
_BTN_SECONDARY = _btn_secondary_style()
_ICON_BTN = _icon_btn_style()
_ACK_FRAME_STYLE = _ack_frame_style()

# Transparent pad after footer CTA glyphs (Qt QSS has no icon→label spacing;
# same approach as neo_nav_icon_gap). Modest nudge — not a redesign.
_FOOTER_ICON_GAP = 4


def _risk_band(version_float: float) -> str:
    """Return ``ancient`` / ``risky`` / ``normal`` for list-row chrome."""
    if version_float < MIN_INSTALL_VERSION - 0.001:
        return "ancient"
    if version_float < RECOMMENDED_INSTALL_VERSION - 0.001:
        return "risky"
    return "normal"


def _footer_cta_icon(pix: QPixmap, size: int = 14, gap: int = _FOOTER_ICON_GAP) -> tuple[QIcon, QSize]:
    """Icon with trailing transparent pad so the label isn't glued to the glyph."""
    gap = max(0, int(gap))
    if pix.isNull():
        return QIcon(), QSize(size, size)
    if gap <= 0:
        return QIcon(pix), QSize(size, size)
    canvas = QPixmap(size + gap, size)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.drawPixmap(0, 0, pix)
    painter.end()
    return QIcon(canvas), QSize(size + gap, size)

_NOTICE_WARN = (
    f"color: #e8b86d; font-size: 11px; font-family: {tok.FONT_APP}; "
    "background-color: #2a2418; padding: 8px 10px; border-radius: 6px; "
    "border: 1px solid #5a4a28;"
)
_NOTICE_DANGER = (
    f"color: #ff8a80; font-size: 11px; font-family: {tok.FONT_APP}; "
    "background-color: #2a1c1c; padding: 8px 10px; border-radius: 6px; "
    "border: 1px solid #5a3030;"
)


def _update_center_dialog_size(parent=None) -> tuple[tuple[int, int], tuple[int, int]]:
    """Min and default (w, h) for Update Center.

    Wide two-column shell (version rail + detail). Extra height leaves room for
    the notes heading subtitle and footer icon buttons; list and notes scroll.
    Cap height to the main window floor / ~85% of work area.
    """
    from PySide6.QtWidgets import QApplication
    from steempeg.ui.layout_defaults import shell_layout_scale

    # Wide two-column baseline; taller so notes keep breathing room.
    min_w, min_h = 860, 620
    def_w, def_h = 960, 700

    host = parent
    win_w = 0
    win_h = 0
    if parent is not None and hasattr(parent, "width"):
        try:
            win_w = int(parent.width())
            win_h = int(parent.height())
        except Exception:
            win_w = win_h = 0
    if win_w <= 0:
        aw = QApplication.activeWindow()
        if aw is not None:
            win_w = int(aw.width())
            win_h = int(aw.height())
            host = aw

    t = shell_layout_scale(win_w, widget=host) if win_w > 0 else 1.0
    cramped = t < 0.85 or (win_h > 0 and win_h < 900)
    if cramped:
        min_w, min_h = 780, 580
        def_w, def_h = 860, 660

    parent_min_h = 0
    if parent is not None and hasattr(parent, "minimumHeight"):
        try:
            parent_min_h = int(parent.minimumHeight())
        except Exception:
            parent_min_h = 0

    screen = None
    try:
        if host is not None and hasattr(host, "screen"):
            screen = host.screen()
    except Exception:
        screen = None
    if screen is None:
        screen = QApplication.primaryScreen()
    if screen is not None:
        avail = screen.availableGeometry()
        max_w = max(420, avail.width() - 48)
        max_h = max(480, int(avail.height() * 0.85))
        if parent_min_h > 0:
            max_h = min(max_h, parent_min_h)
        min_w = min(min_w, max_w)
        min_h = min(min_h, max_h)
        def_w = min(max(def_w, min_w), max_w)
        def_h = min(max(def_h, min_h), max_h)

    elif parent_min_h > 0:
        min_h = min(min_h, parent_min_h)
        def_h = min(max(def_h, min_h), parent_min_h)

    return (min_w, min_h), (def_w, def_h)


_ROW_LOGO_CACHE: dict[int, QPixmap] = {}


def _logo_pixmap(size: int = 18) -> QPixmap | None:
    cached = _ROW_LOGO_CACHE.get(size)
    if cached is not None and not cached.isNull():
        return cached
    from steempeg.ui.icon_utils import app_logo_pixmap, square_fit_pixmap

    pix = app_logo_pixmap(size)
    if pix is None or pix.isNull():
        path = get_resource_path("logo.png")
        if os.path.isfile(path):
            pix = square_fit_pixmap(QPixmap(path), size, dpr=1.0)
    if pix is not None and not pix.isNull():
        _ROW_LOGO_CACHE[size] = pix
        return pix
    return None


def _sanitize_notes(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    # Em dashes break Qt's markdown list parsing mid-bullet on some releases.
    text = text.replace(" — ", ": ").replace("— ", "").replace("—", "-")
    return text


_IMG_MD_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_IMG_HTML_RE = re.compile(
    r'<img\b[^>]*?\bsrc=["\']([^"\']+)["\'][^>]*?/?>',
    re.IGNORECASE | re.DOTALL,
)
_SECTION_BOLD_RE = re.compile(
    r"^\*\*(.+?):\*\*\s*$",
    re.MULTILINE,
)


def _image_placeholder(index: int) -> str:
    # Backtick code survives setMarkdown as searchable plain text.
    return f"`[[steempeg-img:{index}]]`"


def _image_find_token(index: int) -> str:
    return f"[[steempeg-img:{index}]]"


def _split_release_images(body: str) -> tuple[str, list[tuple[str, str]]]:
    images: list[tuple[str, str]] = []

    def add_image(alt: str, url: str) -> str:
        url = (url or "").strip()
        if not url:
            return ""
        index = len(images)
        images.append(((alt or "image").strip() or "image", url))
        return f"\n\n{_image_placeholder(index)}\n\n"

    def repl_md(match: re.Match) -> str:
        return add_image(match.group(1) or "image", match.group(2))

    def repl_html(match: re.Match) -> str:
        return add_image("image", match.group(1))

    stripped = _IMG_HTML_RE.sub(repl_html, body or "")
    stripped = _IMG_MD_RE.sub(repl_md, stripped)
    return stripped, images


def _escape_notes_html_traps(text: str) -> str:
    """Qt setMarkdown treats <id>/<appid> as HTML tags and eats the rest of the notes.

    Release bodies often use angle-bracket placeholders in paths
    (Steam/userdata/<id>/760/...). Escape them after real <img> tags are extracted.
    """
    # <placeholder> → ‹placeholder› (not HTML; survives setMarkdown)
    text = re.sub(
        r"<(/?[A-Za-z][A-Za-z0-9._:-]{0,40})>",
        r"‹\1›",
        text,
    )
    # Strip any other leftover raw tags that would still poison the document.
    text = re.sub(r"</?[A-Za-z][^>]{0,60}>", "", text)
    return text


def _prepare_notes_markdown(body: str) -> str:
    """Normalize GitHub release bodies so Qt setMarkdown keeps bullets + headers."""
    text = _sanitize_notes(body)
    # **🚀 NEW FEATURES:** → ### NEW FEATURES  (emoji+bold headers confuse QTextDocument)
    def _section(match: re.Match) -> str:
        title = match.group(1).strip()
        title = re.sub(r"^[\W_]+", "", title).strip() or match.group(1).strip()
        return f"### {title}"

    text = _SECTION_BOLD_RE.sub(_section, text)
    # Collapse accidental empty list items from blank lines between bullets.
    text = re.sub(r"\n-\s*\n(?=-\s)", "\n", text)
    return text


def _notes_document_style() -> str:
    # GitHub-release feel: readable body, clear section heads, airy lists.
    # FONT_APP matches Steempeg chrome (Segoe/Noto), not Cascadia.
    return f"""
        body {{
            color: {tok.TEXT_PRIMARY};
            font-family: {tok.FONT_APP};
            font-size: 13px;
            line-height: 1.45;
        }}
        h1, h2, h3, h4 {{
            color: {tok.TEXT_TITLE};
            font-family: {tok.FONT_APP};
            font-weight: bold;
            margin: 16px 0 8px 0;
        }}
        h1 {{ font-size: 16px; }}
        h2 {{ font-size: 15px; }}
        h3 {{ font-size: 14px; }}
        h4 {{ font-size: 13px; }}
        strong {{ color: {tok.TEXT_TITLE}; font-weight: 600; }}
        p {{ margin: 0 0 10px 0; }}
        li {{ margin: 5px 0; }}
        ul, ol {{ margin: 4px 0 12px 20px; }}
        a {{ color: {tok.ACCENT_PRIMARY}; text-decoration: none; }}
        code {{
            color: #c8b8e8;
            background: #2a2a2a;
            font-family: {tok.FONT_APP};
        }}
        """


def _apply_notes_markdown(edit: QTextEdit, body: str) -> list[tuple[str, str]]:
    text = _prepare_notes_markdown((body or "").strip() or "_No release notes provided._")
    stripped, images = _split_release_images(text)
    stripped = _escape_notes_html_traps(stripped)
    edit.document().setDefaultStyleSheet(_notes_document_style())
    try:
        edit.setMarkdown(stripped)
    except Exception:
        plain = re.sub(r"\*\*(.+?)\*\*", r"\1", stripped)
        plain = re.sub(r"`\[\[steempeg-img:(\d+)\]\]`", r"[image \1 loading…]", plain)
        edit.setPlainText(plain)
    edit.verticalScrollBar().setValue(0)
    return images


def _insert_note_image(edit: QTextEdit, placeholder: str, pixmap: QPixmap) -> None:
    if pixmap.isNull():
        return
    doc = edit.document()
    token = placeholder.strip("`")
    cursor = QTextCursor(doc)
    cursor.movePosition(QTextCursor.MoveOperation.Start)
    found = doc.find(token, cursor)
    if found.isNull():
        found = doc.find(placeholder, cursor)
    if found.isNull():
        return
    found.removeSelectedText()
    image = pixmap.toImage()
    max_w = 460
    if image.width() > max_w:
        image = image.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
    fmt = QTextImageFormat()
    fmt.setWidth(image.width())
    fmt.setHeight(image.height())
    resource_url = QUrl(f"notesimg://{id(image)}")
    doc.addResource(QTextDocument.ResourceType.ImageResource, resource_url, image)
    fmt.setName(resource_url.toString())
    found.insertImage(fmt)
    found.insertBlock()


class _ReleaseNotesImageLoader(QObject):
    """Fetch release-note images after the markdown text is already on screen."""

    def __init__(self, edit: QTextEdit, images: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self._edit = edit
        self._images = list(images)
        self._nam = QNetworkAccessManager(self)
        self._replies: list[QNetworkReply] = []

    def cancel(self) -> None:
        for reply in self._replies:
            if reply.isRunning():
                reply.abort()
        self._replies.clear()

    def start(self) -> None:
        self.cancel()
        if not self._images:
            return
        for idx, (_alt, url) in enumerate(self._images):
            request = QNetworkRequest(QUrl(url))
            request.setRawHeader(
                b"User-Agent",
                b"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Steempeg/UpdateCenter",
            )
            request.setAttribute(
                QNetworkRequest.Attribute.RedirectPolicyAttribute,
                QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
            )
            request.setAttribute(
                QNetworkRequest.Attribute.CacheLoadControlAttribute,
                QNetworkRequest.CacheLoadControl.PreferCache,
            )
            reply = self._nam.get(request)
            token = _image_find_token(idx)
            reply.finished.connect(
                lambda r=reply, ph=token: self._on_finished(r, ph)
            )
            self._replies.append(reply)

    def _replace_placeholder_text(self, placeholder: str, message: str) -> None:
        doc = self._edit.document()
        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        found = doc.find(placeholder, cursor)
        if found.isNull():
            found = doc.find(f"`{placeholder}`", cursor)
        if found.isNull():
            return
        found.removeSelectedText()
        found.insertText(message)

    def _on_finished(self, reply: QNetworkReply, placeholder: str) -> None:
        if reply in self._replies:
            self._replies.remove(reply)
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._replace_placeholder_text(placeholder, "[image unavailable]")
            reply.deleteLater()
            return
        data = reply.readAll()
        reply.deleteLater()
        if data.isEmpty():
            self._replace_placeholder_text(placeholder, "[image unavailable]")
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            self._replace_placeholder_text(placeholder, "[image unavailable]")
            return
        _insert_note_image(self._edit, placeholder, pixmap)


def _render_release_notes(edit: QTextEdit, body: str, loader_parent: QObject) -> _ReleaseNotesImageLoader | None:
    images = _apply_notes_markdown(edit, body)
    if not images:
        return None
    loader = _ReleaseNotesImageLoader(edit, images, loader_parent)
    loader.start()
    return loader


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
        self._band = _risk_band(entry.version_float)
        self.setObjectName("versionRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            _row_stylesheet(band=self._band, selected=False, indent=bool(indent))
        )

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8 + indent * 14, 6, 8, 6)
        outer.setSpacing(8)

        from steempeg.ui.icon_utils import apply_square_icon

        logo_sz = 18 if not indent else 16
        logo = QLabel()
        apply_square_icon(logo, _logo_pixmap(logo_sz), logo_sz)
        # Match platform badges: without this, selected-row QSS paints an opaque square behind the logo.
        logo.setStyleSheet("background: transparent;")
        outer.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)

        label = entry.tag_name or f"v{entry.version_str}"
        color = version_label_color(entry.version_float, installed=installed, latest=latest)
        self._version_label = QLabel(label)
        self._version_label.setStyleSheet(
            f"color: {color}; "
            f"font-size: {'12px' if not indent else '11px'}; font-weight: 600; background: transparent;"
        )
        outer.addWidget(self._version_label)

        icon_size = 14 if not indent else 12
        for platform in _PLATFORM_ICON_ORDER:
            if platform not in entry.available_platforms:
                continue
            pix = load_pixmap(_PLATFORM_ASSET[platform], icon_size)
            if pix.isNull():
                continue
            from steempeg.ui.icon_utils import apply_square_icon

            icon_lbl = QLabel()
            apply_square_icon(icon_lbl, pix, icon_size)
            icon_lbl.setToolTip(platform_display_name(platform))
            icon_lbl.setStyleSheet("background: transparent;")
            outer.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        outer.addStretch()

        if shows_info_icon(entry):
            tip = info_tooltip_text(entry)
            info_btn = QPushButton()
            info_btn.setIcon(info_icon(14))
            info_btn.setIconSize(QSize(14, 14))
            if tip:
                info_btn.setToolTip(tip)
            info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            info_btn.setStyleSheet(_ICON_BTN)
            info_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            outer.addWidget(info_btn)

        if expand_handler is not None:
            self._expand_btn = QPushButton()
            self._expand_btn.setToolTip("Show other patches in this version line")
            self._expand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._expand_btn.setStyleSheet(_ICON_BTN)
            self._expand_btn.setIconSize(QSize(16, 16))
            self._expand_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._expand_btn.clicked.connect(self._on_expand_clicked)
            self.set_expanded(expanded)
            outer.addWidget(self._expand_btn)
        else:
            self._expand_btn = None

    def _on_expand_clicked(self):
        if self._expand_handler:
            self._expand_handler()

    def set_expanded(self, expanded: bool) -> None:
        if self._expand_btn is not None:
            asset = "arrow_drop.png" if expanded else "arrow_right.png"
            self._expand_btn.setIcon(load_icon(asset, 16))

    def set_selected(self, selected: bool) -> None:
        self.setStyleSheet(
            _row_stylesheet(
                band=self._band,
                selected=selected,
                indent=bool(self._indent),
            )
        )

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


class _ReleaseListHost(QWidget):
    """Scroll body: min height tracks preferred height so version rows are not squashed."""

    def minimumSizeHint(self) -> QSize:  # noqa: N802 — Qt override
        return self.sizeHint()


class UpdateCenterDialog(SteempegDialog):
    install_requested = Signal(object)
    restore_requested = Signal(object)
    rate_limited = Signal(object, bool)

    def __init__(
        self,
        *,
        local_backups: list[LocalBackup],
        parent=None,
        bar_color: str | None = None,
        bg_color: str | None = None,
        settings_host=None,
        keep_prefs: dict[str, bool] | None = None,
    ):
        super().__init__("Update Center", parent, bar_color=bar_color, bg_color=bg_color)

        (mw, mh), (rw, rh) = _update_center_dialog_size(parent)
        # Cap like Settings: notice/ack/Keep must not inflate the shell past the
        # intended footprint — notes and the version list scroll instead.
        self._size_cap_h = rh
        self._map_w = rw
        self._map_h = rh
        self.setMinimumSize(mw, mh)
        self.setMaximumHeight(rh)
        self.resize(rw, rh)
        self._releases: list[ReleaseEntry] = []
        self._local_backups = local_backups
        self._settings_host = settings_host
        self._fetch_thread: _ReleaseFetchThread | None = None
        self._selected: ReleaseEntry | None = None
        self._latest_version = APP_VERSION_FLOAT
        self._row_widgets: list[_VersionRow | _PatchGroupWidget] = []
        self._group_widgets: list[_PatchGroupWidget] = []
        self._notes_image_loader: _ReleaseNotesImageLoader | None = None
        self._refreshing_catalog = False
        self._initial_keep_prefs = keep_prefs
        self._hold_hidden_until_catalog = not bool(load_releases_cache())

        self._apply_dialog_extras_styles()

        root = self.content_layout
        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(16)
        root.addLayout(columns, 1)

        # ----- Left rail: title · versions · Backup -----
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(8)
        left_wrap = QWidget()
        left_wrap.setMinimumWidth(280)
        left_wrap.setMaximumWidth(360)
        left_wrap.setLayout(left)
        columns.addWidget(left_wrap, 0)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        from steempeg.ui.icon_utils import apply_square_icon

        title_icon = QLabel()
        title_pix = title_bar_update_pixmap(tok.TEXT_TITLE, 26)
        if title_pix.isNull():
            title_pix = load_pixmap("update.png", 26)
        apply_square_icon(title_icon, title_pix, 28)
        title_icon.setStyleSheet("background: transparent;")
        title_row.addWidget(title_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        title = QLabel("Update Center")
        title.setStyleSheet(tok.STYLE_PANEL_TITLE)
        title_row.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        left.addLayout(title_row)

        blurb = QLabel(
            f"You are on v{APP_VERSION_STR}. Pick a release to read notes "
            "and update, or restore a local backup."
        )
        blurb.setWordWrap(True)
        blurb.setStyleSheet(tok.STYLE_PANEL_SUBTITLE)
        left.addWidget(blurb)

        self._status_label = QLabel("Loading releases…")
        self._status_label.setStyleSheet(f"color: {tok.TEXT_MUTED}; font-size: 11px;")
        left.addWidget(self._status_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tok.apply_dialog_scroll_bg(scroll, tok.BG_SHELL)
        from steempeg.ui.library.library_styles import (
            LIBRARY_SCROLLBAR_VERTICAL,
            install_library_vertical_scrollbar,
        )

        scroll.setStyleSheet(_scroll_style() + LIBRARY_SCROLLBAR_VERTICAL)
        install_library_vertical_scrollbar(scroll)
        self._release_scroll = scroll
        self._list_host = _ReleaseListHost()
        self._list_host.setObjectName("releaseListHost")
        self._list_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._list_host.setStyleSheet(f"background-color: {tok.BG_SHELL};")
        self._list_host.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 4, 0)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch()
        scroll.setWidget(self._list_host)
        scroll.setMinimumHeight(160)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        left.addWidget(scroll, 1)

        backup_frame = QFrame()
        backup_frame.setObjectName("updateBackupFrame")
        backup_frame.setStyleSheet(_backup_frame_style())
        self._backup_frame = backup_frame
        backup_lay = QVBoxLayout(backup_frame)
        backup_lay.setContentsMargins(12, 10, 12, 10)
        backup_lay.setSpacing(8)

        backup_title = QLabel("Backup")
        backup_title.setStyleSheet(tok.STYLE_PANEL_HEADING)
        backup_lay.addWidget(backup_title)

        if local_backups:
            if len(local_backups) > 1:
                self._backup_combo = QComboBox()
                for backup in local_backups:
                    self._backup_combo.addItem(
                        f"v{backup.version_str} ({backup.folder_name})",
                        backup,
                    )
                self._backup_combo.setStyleSheet(
                    settings_panel_stylesheet(
                        """
                QComboBox {
                    border-radius: 6px;
                    padding: 4px 8px;
                    font-size: 11px;
                    font-weight: bold;
                    min-height: 0px;
                }
                QComboBox::drop-down {
                    width: 22px;
                    border-top-right-radius: 5px;
                    border-bottom-right-radius: 5px;
                }
                QComboBox QAbstractItemView::item {
                    min-height: 22px;
                    padding: 4px 8px;
                }
            """
                    )
                )
                self._backup_combo.currentIndexChanged.connect(self._refresh_restore_button)
                backup_lay.addWidget(self._backup_combo)
                self._backup_version_label = None
            else:
                self._backup_combo = None
                self._backup_version_label = QLabel(f"v{local_backups[0].version_str}")
                self._backup_version_label.setStyleSheet(
                    f"color: {tok.TEXT_PRIMARY}; font-size: 12px; font-weight: 600; "
                    "background: transparent;"
                )
                backup_lay.addWidget(self._backup_version_label)
        else:
            self._backup_combo = None
            self._backup_version_label = QLabel("No local backup")
            self._backup_version_label.setStyleSheet(
                f"color: {tok.TEXT_MUTED}; font-size: 11px; background: transparent;"
            )
            backup_lay.addWidget(self._backup_version_label)

        self._btn_restore = QPushButton("Restore")
        self._btn_restore.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_restore.setStyleSheet(_BTN_SECONDARY)
        self._btn_restore.setEnabled(bool(local_backups))
        self._btn_restore.clicked.connect(self._on_restore_clicked)
        backup_lay.addWidget(self._btn_restore)
        left.addWidget(backup_frame, 0)
        self._refresh_restore_button()

        # ----- Right pane: What's new · Keep when updating · ack · footer -----
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(8)
        right_wrap = QWidget()
        right_wrap.setLayout(right)
        columns.addWidget(right_wrap, 1)

        self._notes_label = QLabel("What's new")
        self._notes_label.setStyleSheet(tok.STYLE_PANEL_HEADING)
        right.addWidget(self._notes_label)

        self._notes_subtitle = QLabel("Changelog for the selected version.")
        self._notes_subtitle.setWordWrap(True)
        self._notes_subtitle.setStyleSheet(
            f"color: {tok.TEXT_MUTED}; font-family: {tok.FONT_APP}; "
            "font-size: 11px; background: transparent;"
        )
        right.addWidget(self._notes_subtitle)

        self._notes = QTextEdit()
        self._notes.setReadOnly(True)
        self._notes.setMinimumHeight(180)
        self._notes.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._notes.setPlaceholderText("Select a version.")
        right.addWidget(self._notes, 1)

        self._notice_label = QLabel()
        self._notice_label.setWordWrap(True)
        self._notice_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._notice_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._notice_label.setStyleSheet(_NOTICE_WARN)
        notice_policy = QSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        notice_policy.setHeightForWidth(False)
        self._notice_label.setSizePolicy(notice_policy)
        self._notice_label.setFixedHeight(0)
        self._notice_label.hide()
        right.addWidget(self._notice_label, 0)

        self._marker_label = QLabel()
        self._marker_label.setWordWrap(True)
        self._marker_label.setStyleSheet(
            f"color: {tok.ACCENT_PRIMARY}; font-family: {tok.FONT_UI}; "
            "font-size: 11px; font-weight: 600; background: transparent;"
        )
        self._marker_label.hide()
        right.addWidget(self._marker_label)

        keep_title = QLabel("Keep when updating")
        keep_title.setStyleSheet(
            f"color: {tok.TEXT_TITLE}; font-size: 12px; font-weight: 600; "
            "background: transparent;"
        )
        right.addWidget(keep_title)

        # Flow so cramped two-column widths (Deck / ~780) wrap instead of
        # clipping "Render history" off the right edge of the detail pane.
        keep_host = QWidget()
        keep_host.setStyleSheet("background: transparent;")
        keep_policy = QSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum
        )
        keep_policy.setHeightForWidth(True)
        keep_host.setSizePolicy(keep_policy)
        keep_row = FlowLayout()
        keep_host.setLayout(keep_row)
        keep_prefs = self._load_keep_prefs()
        self._keep_checks: dict[str, SteempegCheckBox] = {}
        for key, label in (
            ("videos", "Videos"),
            ("settings", "Settings"),
            ("render_history", "Render history"),
            ("presets", "Presets"),
        ):
            check = SteempegCheckBox(label, accent_label=False, label_color=tok.TEXT_PRIMARY)
            check.setChecked(bool(keep_prefs.get(key, True)))
            check.stateChanged.connect(self._on_keep_prefs_changed)
            self._keep_checks[key] = check
            keep_row.addWidget(check)
        right.addWidget(keep_host)

        self._ack_frame = QFrame()
        self._ack_frame.setObjectName("updateAckFrame")
        ack_layout = QHBoxLayout(self._ack_frame)
        ack_layout.setContentsMargins(10, 8, 10, 8)
        self._ack_check = SteempegCheckBox(
            "I understand settings, queue, and rendered sidecars may not match the target version.",
        )
        self._ack_check.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        self._ack_check.stateChanged.connect(self._refresh_actions)
        ack_layout.addWidget(self._ack_check, 1)
        self._ack_frame.setStyleSheet(_ACK_FRAME_STYLE)
        self._ack_frame.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum
        )
        self._ack_frame.hide()
        right.addWidget(self._ack_frame)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        self._btn_install = QPushButton("Update")
        self._btn_install.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_install.setStyleSheet(_BTN_PRIMARY)
        upd_pix = title_bar_update_pixmap("#f0ecff", 14)
        if upd_pix.isNull():
            upd_pix = load_pixmap("update.png", 14)
        upd_icon, upd_sz = _footer_cta_icon(upd_pix, 14)
        self._btn_install.setIcon(upd_icon)
        self._btn_install.setIconSize(upd_sz)
        self._btn_install.setEnabled(False)
        self._btn_install.clicked.connect(self._on_install_clicked)
        actions.addWidget(self._btn_install)

        self._btn_github = QPushButton("View on GitHub")
        self._btn_github.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_github.setStyleSheet(_BTN_SECONDARY)
        gh_icon, gh_sz = _footer_cta_icon(load_pixmap("github.jpg", 14), 14)
        self._btn_github.setIcon(gh_icon)
        self._btn_github.setIconSize(gh_sz)
        self._btn_github.setEnabled(False)
        self._btn_github.clicked.connect(self._on_github_clicked)
        actions.addWidget(self._btn_github)

        actions.addStretch()
        right.addLayout(actions)

        self._refresh_theme_surfaces()
        self._start_fetch()

    def _prepare_geometry_before_map(self) -> None:
        """Re-apply capped size + parent center before DWM maps the shell."""
        w = max(int(getattr(self, "_map_w", 0) or self.width() or 1), 1)
        h = max(int(getattr(self, "_map_h", 0) or self.height() or 1), 1)
        self.setMaximumHeight(int(getattr(self, "_size_cap_h", h) or h))
        self.resize(w, h)
        self.ensurePolished()
        self._center_on_parent()

    def _center_on_parent(self) -> None:
        """Dead-center on the main window using the capped map size (Settings-style)."""
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication, QWidget

        ref: QWidget | None = None
        parent = self.parentWidget()
        if isinstance(parent, QWidget) and parent.isVisible():
            ref = parent.window() if parent.window() is not None else parent
        if ref is None:
            aw = QApplication.activeWindow()
            if isinstance(aw, QWidget):
                ref = aw

        dw = max(int(getattr(self, "_map_w", 0) or self.width() or 1), 1)
        dh = max(int(getattr(self, "_map_h", 0) or self.height() or 1), 1)

        if ref is not None and ref.isVisible():
            origin = ref.mapToGlobal(QPoint(0, 0))
            rw, rh = max(ref.width(), 1), max(ref.height(), 1)
            x = origin.x() + (rw - dw) // 2
            y = origin.y() + (rh - dh) // 2
            if dw > rw:
                x = origin.x()
            if dh > rh:
                y = origin.y()
        else:
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                return
            avail = screen.availableGeometry()
            x = avail.x() + (avail.width() - dw) // 2
            y = avail.y() + (avail.height() - dh) // 2

        screen = None
        if ref is not None:
            screen = QGuiApplication.screenAt(ref.mapToGlobal(ref.rect().center()))
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            x = max(avail.x(), min(x, avail.x() + max(0, avail.width() - dw)))
            y = max(avail.y(), min(y, avail.y() + max(0, avail.height() - dh)))
        self.move(x, y)

    def showEvent(self, event: QShowEvent) -> None:
        if self._hold_hidden_until_catalog and not self._releases:
            event.ignore()
            self.hide()
            return
        super().showEvent(event)

    def _reveal_catalog_shell(self) -> None:
        if not self._hold_hidden_until_catalog:
            return
        self._hold_hidden_until_catalog = False
        self._prepare_geometry_before_map()
        if not self.isVisible():
            self.show()
            self.raise_()
            self.activateWindow()

    def _start_fetch(self):
        QTimer.singleShot(0, self._show_cached_catalog)
        self._fetch_thread = _ReleaseFetchThread(self)
        self._fetch_thread.finished_ok.connect(self._on_fetch_ok)
        self._fetch_thread.finished_error.connect(self._on_fetch_error)
        self._fetch_thread.finished_rate_limited.connect(self._on_fetch_rate_limited)
        self._fetch_thread.start()

    def _show_cached_catalog(self) -> None:
        cached = load_releases_cache()
        if not cached:
            return
        self._refreshing_catalog = True
        self._on_releases_loaded(cached, from_cache=True)
        self._reveal_catalog_shell()
        self._status_label.setText("Refreshing release list…")
        self._status_label.setStyleSheet(f"color: {tok.TEXT_MUTED}; font-size: 11px;")

    def _on_fetch_ok(self, releases: list):
        self._refreshing_catalog = False
        self._on_releases_loaded(releases, from_cache=False)
        self._reveal_catalog_shell()

    def _clear_list(self):
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._row_widgets.clear()
        self._group_widgets.clear()

    def _on_releases_loaded(self, releases: list, *, from_cache: bool = False):
        new_tags = [entry.tag_name for entry in releases]
        old_tags = [entry.tag_name for entry in self._releases] if self._releases else []
        if (
            self._row_widgets
            and new_tags == old_tags
            and not from_cache
        ):
            self._releases = releases
            self._refreshing_catalog = False
            self._latest_version = latest_release_version(releases)
            latest_str = releases[0].version_str if releases else APP_VERSION_STR
            if self._latest_version > APP_VERSION_FLOAT + 0.001:
                self._status_label.setText(f"Update available: v{latest_str}")
                self._status_label.setStyleSheet(
                    "color: #7ec8a3; font-size: 11px; font-weight: 600;"
                )
            else:
                self._status_label.setText(f"{len(releases)} releases · you are on the latest")
                self._status_label.setStyleSheet(f"color: {tok.TEXT_MUTED}; font-size: 11px;")
            return

        self._releases = releases
        self._clear_list()

        if not releases:
            if not from_cache:
                self._status_label.setText("No public releases found.")
            return

        self._latest_version = latest_release_version(releases)
        latest_str = releases[0].version_str
        if self._latest_version > APP_VERSION_FLOAT + 0.001:
            status = f"Update available: v{latest_str}"
            if from_cache and self._refreshing_catalog:
                status += " · refreshing…"
            self._status_label.setText(status)
            self._status_label.setStyleSheet("color: #7ec8a3; font-size: 11px; font-weight: 600;")
        else:
            count_line = f"{len(releases)} releases · you are on the latest"
            if from_cache and self._refreshing_catalog:
                count_line += " · refreshing…"
            self._status_label.setText(count_line)
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
        self._list_host.updateGeometry()

    def _on_fetch_error(self, message: str):
        self._refreshing_catalog = False
        if self._releases:
            self._status_label.setText("Could not refresh. Showing cached releases.")
            self._status_label.setStyleSheet("color: #e8b86d; font-size: 11px;")
            return
        self._status_label.setText(message)
        self._status_label.setStyleSheet("color: #ff8a80; font-size: 11px;")
        self._reveal_catalog_shell()

    def _on_fetch_rate_limited(self, info: RateLimitInfo):
        self._refreshing_catalog = False
        has_cached = bool(self._releases) or not self._hold_hidden_until_catalog
        if has_cached:
            if not self._releases:
                cached = load_releases_cache()
                if cached:
                    self._on_releases_loaded(cached, from_cache=True)
                    self._reveal_catalog_shell()
            self._status_label.setText("Rate limited. Showing cached releases.")
            self._status_label.setStyleSheet("color: #e8b86d; font-size: 11px;")
            self.rate_limited.emit(info, True)
            return
        self._status_label.setText("GitHub API rate limit exceeded.")
        self._status_label.setStyleSheet("color: #e8b86d; font-size: 11px;")
        # Emit before reject so the parent can show the limit dialog while still connected.
        self.rate_limited.emit(info, False)
        QTimer.singleShot(0, self.reject)

    def _select_entry(self, entry: ReleaseEntry):
        self._selected = entry
        if self._notes_image_loader is not None:
            self._notes_image_loader.cancel()
            self._notes_image_loader = None
        for widget in self._row_widgets:
            if isinstance(widget, _VersionRow):
                widget.set_selected(widget._entry.version_float == entry.version_float)
            else:
                widget.set_selected_entry(entry)
        ver = (entry.version_str or "").strip() or "?"
        self._notes_label.setText(f"What's new in v{ver}")
        self._notes_image_loader = _render_release_notes(self._notes, entry.body, self)

        notice = selection_notice(entry, APP_VERSION_FLOAT)
        if notice:
            text = f"⚠️ {notice}"
            self._notice_label.setText(text)
            danger = (
                entry.version_float < MIN_INSTALL_VERSION - 0.001
                or entry.install_tier in (InstallTier.BROKEN, InstallTier.MANUAL)
                or (
                    entry.install_tier == InstallTier.NO_ZIP
                    and bool(entry.block_reason)
                )
            )
            if danger:
                self._notice_label.setStyleSheet(_NOTICE_DANGER)
            else:
                self._notice_label.setStyleSheet(_NOTICE_WARN)
            # Height once from font metrics — same one-line text ⇒ identical height.
            self._pin_notice_height(text)
            self._notice_label.show()
        else:
            self._notice_label.clear()
            self._notice_label.setFixedHeight(0)
            self._notice_label.hide()

        marker = selection_marker_text(entry)
        if marker:
            self._marker_label.setText(marker)
            self._marker_label.show()
        else:
            self._marker_label.hide()

        self._refresh_actions()

    def _pin_notice_height(self, text: str) -> None:
        """Lock banner to wrapped text height; never accumulate across selections."""
        label = self._notice_label
        # Stable wrap width from the notes pane / dialog — not the label's
        # transient contentsRect (that shrinks as the plate grows → Jenga loop).
        width = max(int(self._notes.width()) - 8, int(self.width()) - 48, 280)
        # Stylesheet padding 8+8 + 1px borders ≈ 18; keep a small floor.
        pad = 20
        fm = label.fontMetrics()
        bounds = fm.boundingRect(
            0,
            0,
            max(width - pad, 40),
            10_000,
            int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft),
            text,
        )
        needed = max(int(bounds.height()) + pad, fm.height() + pad)
        needed = min(needed, 120)  # allow 2-3 lines for platform / policy notices
        if label.height() != needed:
            label.setFixedHeight(needed)

    def _refresh_actions(self):
        entry = self._selected
        self._btn_github.setEnabled(entry is not None)

        if not entry:
            self._btn_install.setText("Update")
            self._btn_install.setStyleSheet(_btn_primary_style())
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
            else:
                # Locked CTA: Update (version is clear from the selected rail row).
                self._btn_install.setText("Update")
        elif entry.install_tier == InstallTier.MANUAL:
            self._btn_install.setText("Cannot install")
        elif entry.install_tier == InstallTier.NO_ZIP:
            if not entry.available_platforms:
                self._btn_install.setText("Not ready yet")
            elif entry.block_reason:
                short = entry.block_reason.split(" (", 1)[0].rstrip(".")
                self._btn_install.setText(short)
            else:
                self._btn_install.setText("Cannot install here")
        else:
            self._btn_install.setText("Cannot install")

        if is_current:
            self._btn_install.setStyleSheet(_btn_current_style())
        else:
            self._btn_install.setStyleSheet(_btn_primary_style())
        self._btn_install.setEnabled(can_install)

    def _load_keep_prefs(self) -> dict[str, bool]:
        from steempeg.ui.settings_prefs import (
            DEFAULT_UPDATE_KEEP_WHEN,
            load_update_keep_when,
            normalize_update_keep_when,
        )

        if isinstance(self._initial_keep_prefs, dict):
            return normalize_update_keep_when(self._initial_keep_prefs)
        host = self._settings_host
        try:
            if host is not None and hasattr(host, "load_user_settings"):
                return load_update_keep_when(host.load_user_settings() or {})
        except Exception:
            logging.exception("UPDATE_CENTER: failed loading keep prefs")
        return dict(DEFAULT_UPDATE_KEEP_WHEN)

    def keep_when_updating(self) -> dict[str, bool]:
        """Current Keep when updating checkbox state."""
        from steempeg.ui.settings_prefs import DEFAULT_UPDATE_KEEP_WHEN

        out = dict(DEFAULT_UPDATE_KEEP_WHEN)
        for key, check in getattr(self, "_keep_checks", {}).items():
            out[key] = bool(check.isChecked())
        return out

    def _on_keep_prefs_changed(self, *_args) -> None:
        from steempeg.ui.settings_prefs import save_update_keep_when

        prefs = self.keep_when_updating()
        host = self._settings_host
        if host is None or not hasattr(host, "save_user_settings"):
            return
        try:
            save_update_keep_when(host, prefs)
        except Exception:
            logging.exception("UPDATE_CENTER: failed saving keep prefs")

    def _refresh_restore_button(self) -> None:
        backup = self._selected_backup()
        if backup is None:
            self._btn_restore.setText("Restore")
            self._btn_restore.setEnabled(False)
            return
        self._btn_restore.setText(f"Restore v{backup.version_str}")
        self._btn_restore.setEnabled(True)

    def _on_install_clicked(self):
        entry = self._selected
        if not entry:
            return
        if not entry.installable:
            webbrowser.open(entry.html_url)
            return
        # Persist keep prefs once more before handoff.
        self._on_keep_prefs_changed()
        self.install_requested.emit(entry)
        # Do NOT accept() here — the confirm dialog runs inside the install slot.
        # Closing Update Center before/after a cancelled confirm left a stuck
        # hand cursor on the title-bar Updates control.

    def _on_github_clicked(self):
        if self._selected:
            webbrowser.open(self._selected.html_url)

    def _on_restore_clicked(self):
        if not self._local_backups:
            return
        backup = self._selected_backup()
        if not backup:
            return
        if not steempeg_question(
            self,
            "Restore local backup",
            f"Restore v{backup.version_str} from {backup.folder_name}?",
        ):
            return
        self.restore_requested.emit(backup)
        self.accept()

    def _selected_backup(self) -> LocalBackup | None:
        if self._backup_combo is not None:
            return self._backup_combo.currentData()
        return self._local_backups[0] if self._local_backups else None

    def _apply_dialog_extras_styles(self) -> None:
        """Scroll + notes QSS layered on SteempegDialog card chrome."""
        from steempeg.ui.library.library_styles import LIBRARY_SCROLLBAR_VERTICAL

        extras = _scroll_style() + _notes_style()
        self.setStyleSheet(self.styleSheet() + extras)
        scroll = getattr(self, "_release_scroll", None)
        if scroll is not None:
            scroll.setStyleSheet(_scroll_style() + LIBRARY_SCROLLBAR_VERTICAL)

    def _refresh_theme_surfaces(self) -> None:
        """Re-tint lists, backup, buttons, and version rows from active tokens."""
        global _SCROLL_STYLE, _NOTES_STYLE, _BTN_PRIMARY, _BTN_SECONDARY, _ICON_BTN, _ACK_FRAME_STYLE
        _SCROLL_STYLE = _scroll_style()
        _NOTES_STYLE = _notes_style()
        _BTN_PRIMARY = _btn_primary_style()
        _BTN_SECONDARY = _btn_secondary_style()
        _ICON_BTN = _icon_btn_style()
        _ACK_FRAME_STYLE = _ack_frame_style()

        self._apply_dialog_extras_styles()
        if hasattr(self, "_list_host") and self._list_host is not None:
            self._list_host.setStyleSheet(f"background-color: {tok.BG_SHELL};")
        backup_frame = getattr(self, "_backup_frame", None)
        if backup_frame is not None:
            backup_frame.setStyleSheet(_backup_frame_style())
        if hasattr(self, "_ack_frame"):
            self._ack_frame.setStyleSheet(_ACK_FRAME_STYLE)
        if hasattr(self, "_btn_github"):
            self._btn_github.setStyleSheet(_BTN_SECONDARY)
        if hasattr(self, "_btn_restore"):
            self._btn_restore.setStyleSheet(_BTN_SECONDARY)
        if hasattr(self, "_refresh_actions"):
            self._refresh_actions()
        selected = self._selected
        for widget in getattr(self, "_row_widgets", []):
            if isinstance(widget, _VersionRow):
                is_sel = (
                    selected is not None
                    and widget._entry.version_float == selected.version_float
                )
                widget.set_selected(is_sel)
            elif hasattr(widget, "set_selected_entry"):
                widget.set_selected_entry(selected)
        for btn in self.findChildren(QPushButton):
            ss = btn.styleSheet() or ""
            if "min-width: 20px" in ss and "transparent" in ss:
                btn.setStyleSheet(_ICON_BTN)

    def apply_ui_theme_chrome(self) -> None:
        """Live-retint when Settings switches UI theme while Update Center is open."""
        super().apply_ui_theme_chrome()
        self._refresh_theme_surfaces()

    def closeEvent(self, event):
        if self._notes_image_loader is not None:
            self._notes_image_loader.cancel()
            self._notes_image_loader = None
        super().closeEvent(event)
