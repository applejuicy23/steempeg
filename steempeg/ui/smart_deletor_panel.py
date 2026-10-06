"""Smart Deletor tab — pick rules, review matches, delete through a queue."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTime, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.paths import get_resource_path
from steempeg.library.smart_delete import (
    KIND_CLIP,
    DeleteCandidate,
    DeleteRules,
    format_size,
)
from steempeg.ui import design_tokens as tok
from steempeg.ui import ui_theme as ut
from steempeg.ui.queue_card_shared import (
    QUEUE_CARD_BORDER_PX,
    STATUS_BORDER_DONE,
    STATUS_BORDER_ERROR,
    STATUS_BORDER_RENDER,
    _FONT,
    _LIST_THUMB_H,
    _LIST_THUMB_W,
    _QUEUE_CHROME_INSET,
    queue_card_idle_border,
    queue_menu_stylesheet,
)
from steempeg.ui.ui_density import COMFORT, toolbar_mega_pill_style
from steempeg.ui.widgets.elided_label import ElidedLabel
from steempeg.ui.widgets.steempeg_check import SteempegCheckBox
from steempeg.ui.widgets.view_mode_toggle import ViewModeChrome

_TITLE_ICON = 28
_GRID_ICON = 24
_BADGE = 26
_GRID_CARD_W = 200
_GRID_THUMB_H = 112
_GRID_TEXT_H = 66
_GRID_GAP = 10
# Rows beyond this still get deleted, they just skip the thumbnail decode.
_THUMB_ROW_CAP = 200

def _btn_style(height: int = 32) -> str:
    return ut.toolbar_text_button_stylesheet(radius=6, font_px=13, height=height)


def _danger_btn_style() -> str:
    return (
        _btn_style()
        .replace("color: #e0e0e0;", "color: #ff7777;", 1)
        .replace("#6b5a8e", "#e05555")
        .replace("#b29ae7", "#ff7777")
    )


def _field_btn_style() -> str:
    return ut.filter_action_button_stylesheet(
        font=13, pad_v=4, pad_h=10, min_h=24, radius=8, border=2
    ).replace("min-height: 24px;", "min-height: 24px; text-align: left;", 1)


def _chip_style() -> str:
    return ut.filter_chip_button_stylesheet(
        font=13, pad_v=4, pad_h=12, min_h=24, radius=14, border=2
    )


def _capsule_style() -> str:
    return ut.filter_menu_capsule_stylesheet(radius=14, title_font=13)


class _RuleCheck(SteempegCheckBox):
    """Bold 13px label — width measured with the painted font so it never clips."""

    def __init__(self, label: str):
        super().__init__(label, font_size=13, label_bold=True)
        self._paint_font = tok.ui_qfont(pixel_size=13, weight=QFont.Weight.Bold)

    def sizeHint(self):  # noqa: N802
        fm = QFontMetrics(self._paint_font)
        w = self._text_left() + fm.horizontalAdvance(self.text()) + self._PAD + 4
        h = max(self._IND + 2 * self._PAD, fm.height() + 4)
        return QSize(w, h)

    def minimumSizeHint(self):  # noqa: N802
        return self.sizeHint()


def _check(label: str) -> SteempegCheckBox:
    return _RuleCheck(label)


_CARD_LABEL_CSS = f"background: transparent; border: none; {_FONT}"

_STATUS_LINE = {
    "deleting": ("Deleting…", STATUS_BORDER_RENDER),
    "done": ("Deleted", STATUS_BORDER_DONE),
    "error": ("Failed", STATUS_BORDER_ERROR),
}


def _arrow_paths() -> tuple[str, str]:
    """Same white spinner arrows the Clips filter popup uses."""
    temp_dir = tempfile.gettempdir()
    up = os.path.join(temp_dir, "smpeg_up.png").replace("\\", "/")
    down = os.path.join(temp_dir, "smpeg_down.png").replace("\\", "/")
    for path, pts in (
        (up, (QPoint(3, 11), QPoint(8, 5), QPoint(13, 11))),
        (down, (QPoint(3, 5), QPoint(8, 11), QPoint(13, 5))),
    ):
        if os.path.isfile(path):
            continue
        pix = QPixmap(16, 16)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon(list(pts))
        p.end()
        pix.save(path, "PNG")
    return up, down


def _field_style() -> str:
    """Filter-popup date/time field chrome, widened to every spin box."""
    up, down = _arrow_paths()
    css = ut.filter_date_time_input_stylesheet(
        font=13, pad_v=4, pad_h=10, min_h=24, radius=8, border=2,
        drop_w=24, spin_w=20, arrow_up=up, arrow_down=down, arrow_sz=10,
    ).replace("QTimeEdit", "QAbstractSpinBox")
    return css + """
        QAbstractSpinBox:disabled { color: #666666; border-color: #333333; }
    """


def _capsule(title: str, content: QWidget) -> QFrame:
    cap = QFrame()
    cap.setObjectName("CategoryCapsule")
    cap.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    cap.setStyleSheet(_capsule_style())
    lay = QVBoxLayout(cap)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(8)
    lbl = QLabel(title)
    lbl.setObjectName("CategoryTitle")
    lay.addWidget(lbl)
    lay.addWidget(content)
    return cap


def _rounded_thumb(path: str, w: int, h: int, radius: float, *, top_only: bool = False) -> QPixmap:
    src = QPixmap(path) if path and os.path.isfile(path) else QPixmap()
    out = QPixmap(w, h)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    clip = QPainterPath()
    if top_only:
        clip.addRect(QRectF(0, 0, w, h))
    else:
        clip.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    p.setClipPath(clip)
    p.fillRect(0, 0, w, h, QColor("#1a1a1a"))
    if not src.isNull():
        scaled = src.scaled(
            w, h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        p.drawPixmap((w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled)
    p.end()
    return out


def _game_icon(label: QLabel, icon_path: str, size: int) -> None:
    from steempeg.ui.icon_shape import shaped_game_icon_pixmap
    from steempeg.ui.icon_utils import apply_square_icon

    unknown = get_resource_path("unknown_icon.png")
    path = icon_path if icon_path and os.path.isfile(icon_path) else unknown
    shaped = None
    if path and os.path.isfile(path):
        src = QPixmap(path)
        if not src.isNull():
            shaped = shaped_game_icon_pixmap(src, size)
    apply_square_icon(label, shaped, size)


def _date_text(c: DeleteCandidate) -> str:
    if not c.recorded_at:
        return ""
    return datetime.fromtimestamp(c.recorded_at).strftime("%d %b %Y · %I:%M %p")


def _size_text(c: DeleteCandidate) -> str:
    kind = c.type_label or ("🎬 Clip" if c.kind == KIND_CLIP else "🎥 Rendered")
    parts = [kind, format_size(c.size_bytes)]
    if c.duration_sec:
        total = int(c.duration_sec)
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        parts.append(f"{h}h {m}m" if h else (f"{m}m {s:02d}s" if m else f"{s}s"))
    return " · ".join(parts)


_HEALTH_LABELS = {"dead": "Dead", "degraded": "Issues", "cured": "Cured"}


def _health_text(c: DeleteCandidate) -> str:
    return _HEALTH_LABELS.get(c.health, "")


def _health_pixmap(c: DeleteCandidate, size: int = 14) -> QPixmap:
    from steempeg.core.dash.health import HEALTH_ICON_FILES, ClipHealth
    from steempeg.ui.icon_assets import load_pixmap

    if c.health not in _HEALTH_LABELS:
        return QPixmap()
    try:
        name = HEALTH_ICON_FILES[ClipHealth(c.health)]
    except (ValueError, KeyError):
        return QPixmap()
    return load_pixmap(name, size)


def _health_color(c: DeleteCandidate) -> str:
    from steempeg.core.dash.health import HEALTH_COLORS, ClipHealth

    try:
        return HEALTH_COLORS[ClipHealth(c.health)]
    except (ValueError, KeyError):
        return "#e07a86"


def _badge_style(checked: bool, status: str) -> tuple[str, str]:
    r = _BADGE // 2
    base = (
        f"font-weight: bold; font-size: 13px; {_FONT} border-radius: {r}px;"
        f"min-width: {_BADGE}px; max-width: {_BADGE}px; min-height: {_BADGE}px;"
        f"max-height: {_BADGE}px; padding: 0; margin: 0;"
    )
    if status == "deleting":
        return "…", f"color: #1a1a1a; background-color: {STATUS_BORDER_RENDER}; {base}"
    if status == "done":
        return "✓", f"color: #1a1a1a; background-color: {STATUS_BORDER_DONE}; {base}"
    if status == "error":
        return "!", f"color: #ffffff; background-color: {STATUS_BORDER_ERROR}; {base}"
    if checked:
        return "✓", f"color: #1a1a1a; background-color: #b29ae7; {base}"
    return "", f"background-color: rgba(0, 0, 0, 0.55); border: 2px solid #888888; {base}"


class _CardBase:
    """Shared check / status / hover behaviour for list + grid cards."""

    def _init_state(self, cand: DeleteCandidate, panel: "SmartDeletorPanel") -> None:
        self.cand = cand
        self._panel = panel
        self._hovered = False
        self._faded = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @property
    def checked(self) -> bool:
        return self._panel._checked.get(self.cand.key, True)

    @property
    def status(self) -> str:
        return self._panel._status.get(self.cand.key, ("", ""))[0]

    def refresh(self) -> None:
        text, style = _badge_style(self.checked, self.status)
        self._badge.setText(text)
        self._badge.setStyleSheet(style)
        status, error = self._panel._status.get(self.cand.key, ("", ""))
        line = _STATUS_LINE.get(status)
        health_pix = QPixmap() if line is not None else _health_pixmap(self.cand)
        self._health_icon.setPixmap(health_pix)
        self._health_icon.setVisible(not health_pix.isNull())
        if line is not None:
            self._status_label.setText(line[0])
            self._status_label.setStyleSheet(
                f"color: {line[1]}; font-size: 11px; font-weight: bold; {_CARD_LABEL_CSS}"
            )
            self._status_label.setToolTip(error)
            self._status_label.show()
        else:
            health = _health_text(self.cand)
            self._status_label.setText(health)
            self._status_label.setStyleSheet(
                f"color: {_health_color(self.cand)}; font-size: 11px; font-weight: bold;"
                f" {_CARD_LABEL_CSS}"
            )
            self._status_label.setToolTip("")
            self._status_label.setVisible(bool(health))
        faded = not (self.checked or status)
        if faded != self._faded:
            self._faded = faded
            if faded:
                effect = QGraphicsOpacityEffect(self)
                effect.setOpacity(0.45)
                self.setGraphicsEffect(effect)
            else:
                self.setGraphicsEffect(None)
        self._apply_border()

    def _border_color(self) -> str:
        status = self.status
        if status == "deleting":
            return STATUS_BORDER_RENDER
        if status == "done":
            return STATUS_BORDER_DONE
        if status == "error":
            return STATUS_BORDER_ERROR
        if self._hovered:
            return "#7a6aa8"
        return queue_card_idle_border()

    def enterEvent(self, event):  # noqa: N802
        self._hovered = True
        self._apply_border()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hovered = False
        self._apply_border()
        super().leaveEvent(event)

    def contextMenuEvent(self, event):  # noqa: N802
        self._panel._show_card_menu(self.cand, event.globalPos())
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self._panel._toggle_card(self.cand.key)
        super().mouseReleaseEvent(event)


class _ListCard(_CardBase, QFrame):
    def __init__(self, cand: DeleteCandidate, panel: "SmartDeletorPanel", *, load_thumb: bool):
        QFrame.__init__(self)
        self.setObjectName("SmartDeleteCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._init_state(cand, panel)
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(8)

        thumb_wrap = QWidget()
        thumb_wrap.setFixedSize(_LIST_THUMB_W, _LIST_THUMB_H)
        thumb = QLabel(thumb_wrap)
        thumb.setGeometry(0, 0, _LIST_THUMB_W, _LIST_THUMB_H)
        thumb.setStyleSheet("background: transparent; border: none;")
        thumb.setPixmap(
            panel._thumb(cand.thumb_path if load_thumb else "", _LIST_THUMB_W, _LIST_THUMB_H, 8.0)
        )
        self._badge = QLabel(thumb_wrap)
        self._badge.setFixedSize(_BADGE, _BADGE)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.move(6, 6)
        root.addWidget(thumb_wrap, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(3)
        title_host = QWidget()
        title_host.setFixedHeight(_TITLE_ICON)
        title_row = QHBoxLayout(title_host)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        icon = QLabel()
        _game_icon(icon, cand.icon_path, _TITLE_ICON)
        title_row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        title = ElidedLabel(cand.title or os.path.basename(cand.path))
        title.setStyleSheet(f"color: #f0f0f0; font-weight: bold; font-size: 13px; {_FONT}")
        title.setMinimumWidth(0)
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        title_row.addWidget(title, 1, Qt.AlignmentFlag.AlignVCenter)
        text_col.addWidget(title_host)

        meta = ElidedLabel(_date_text(cand))
        meta.setStyleSheet(f"color: #888888; font-size: 11px; {_FONT}")
        size = ElidedLabel(_size_text(cand))
        size.setStyleSheet(f"color: #c4b5e8; font-size: 11px; {_FONT}")
        self._status_label = QLabel()
        self._health_icon = QLabel()
        self._health_icon.setFixedSize(14, 14)
        for lbl in (meta, size):
            lbl.setMinimumWidth(0)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            text_col.addWidget(lbl)
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(4)
        status_row.addWidget(self._health_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self._status_label, 0, Qt.AlignmentFlag.AlignVCenter)
        status_row.addStretch()
        text_col.addLayout(status_row)
        text_col.addStretch()
        text_host = QWidget()
        text_host.setLayout(text_col)
        text_host.setMinimumWidth(0)
        text_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        root.addWidget(text_host, 1)

        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setToolTip(cand.path)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.refresh()

    def _apply_border(self) -> None:
        self.setStyleSheet(f"""
            QFrame#SmartDeleteCard {{
                background-color: {ut.queue_job_card_face()};
                border: {QUEUE_CARD_BORDER_PX}px solid {self._border_color()};
                border-radius: 12px;
            }}
            QLabel {{ background: transparent; border: none; {_FONT} }}
        """)


class _GridCard(_CardBase, QWidget):
    def __init__(self, cand: DeleteCandidate, panel: "SmartDeletorPanel", *, load_thumb: bool):
        QWidget.__init__(self)
        self.setObjectName("SmartDeleteGridCard")
        self._init_state(cand, panel)
        self.setFixedSize(_GRID_CARD_W, _GRID_THUMB_H + _GRID_TEXT_H)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        thumb_wrap = QWidget()
        thumb_wrap.setFixedSize(_GRID_CARD_W, _GRID_THUMB_H)
        thumb = QLabel(thumb_wrap)
        thumb.setGeometry(0, 0, _GRID_CARD_W, _GRID_THUMB_H)
        thumb.setStyleSheet("background: transparent; border: none;")
        thumb.setPixmap(
            panel._thumb(
                cand.thumb_path if load_thumb else "", _GRID_CARD_W, _GRID_THUMB_H, 0.0, top_only=True
            )
        )
        self._badge = QLabel(thumb_wrap)
        self._badge.setFixedSize(_BADGE, _BADGE)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.move(8, 8)
        icon = QLabel(thumb_wrap)
        icon.move(8, _GRID_THUMB_H - _GRID_ICON - 8)
        _game_icon(icon, cand.icon_path, _GRID_ICON)
        lay.addWidget(thumb_wrap)

        footer = QWidget()
        footer.setFixedHeight(_GRID_TEXT_H)
        footer.setStyleSheet(ut.queue_grid_footer_stylesheet(radius=9))
        fl = QVBoxLayout(footer)
        fl.setContentsMargins(8, 6, 8, 6)
        fl.setSpacing(2)
        title = ElidedLabel(cand.title or os.path.basename(cand.path))
        title.setStyleSheet(
            f"QLabel {{ color: #e0e0e0; font-weight: bold; font-size: 13px; {_CARD_LABEL_CSS} }}"
        )
        meta = ElidedLabel(_date_text(cand))
        meta.setStyleSheet(f"QLabel {{ color: #888888; font-size: 11px; {_CARD_LABEL_CSS} }}")
        size = ElidedLabel(_size_text(cand))
        size.setStyleSheet(f"QLabel {{ color: #c4b5e8; font-size: 11px; {_CARD_LABEL_CSS} }}")
        self._status_label = QLabel()
        self._health_icon = QLabel()
        self._health_icon.setFixedSize(14, 14)
        self._health_icon.setStyleSheet("background: transparent; border: none;")
        fl.addWidget(title)
        fl.addWidget(meta)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(size, 1)
        row.addWidget(self._health_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._status_label, 0)
        fl.addLayout(row)
        lay.addWidget(footer)

        self._overlay = QFrame(self)
        self._overlay.setGeometry(0, 0, self.width(), self.height())
        self._overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._overlay.raise_()
        self._badge.raise_()
        self.setToolTip(cand.path)
        self.refresh()

    def _apply_border(self) -> None:
        self._overlay.setStyleSheet(f"""
            QFrame {{
                background: transparent;
                border: {QUEUE_CARD_BORDER_PX}px solid {self._border_color()};
                border-top-left-radius: 0px; border-top-right-radius: 0px;
                border-bottom-left-radius: 12px; border-bottom-right-radius: 12px;
            }}
        """)


class _RuleRow(QWidget):
    """Checkbox that enables an optional value editor next to it."""

    def __init__(self, label: str, editor: QWidget | None = None, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.check = _check(label)
        lay.addWidget(self.check)
        lay.addStretch()
        self.editor = editor
        if editor is not None:
            editor.setEnabled(False)
            editor.setFixedWidth(128)
            editor.setCursor(Qt.CursorShape.PointingHandCursor)
            self.check.toggled.connect(editor.setEnabled)
            lay.addWidget(editor)

    @property
    def on(self) -> bool:
        return self.check.isChecked()


def _secs(edit: QTimeEdit) -> int:
    return QTime(0, 0).secsTo(edit.time())


class SmartDeletorPanel(QWidget):
    find_requested = Signal(object)  # DeleteRules
    start_requested = Signal(object, bool)  # list[(path, kind)], permanent
    cancel_requested = Signal()
    games_requested = Signal()
    view_mode_changed = Signal(str)
    preview_requested = Signal(str, str)  # path, kind
    reveal_requested = Signal(str, str)  # path, kind

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self._candidates: list[DeleteCandidate] = []
        self._cards: list[_CardBase] = []
        self._card_by_key: dict[str, _CardBase] = {}
        self._checked: dict[str, bool] = {}
        self._status: dict[str, tuple[str, str]] = {}
        self._pix_cache: dict[tuple, QPixmap] = {}
        self._games: list[str] = []
        self._picked_games: set[str] = set()
        self._running = False
        self._scanning = False
        self._view_mode = "list"
        self._grid_cols = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        toolbar_row = QHBoxLayout()
        toolbar_row.setContentsMargins(_QUEUE_CHROME_INSET, 0, _QUEUE_CHROME_INSET, 0)
        toolbar = QFrame()
        toolbar.setObjectName("deletorToolbar")
        toolbar.setStyleSheet(toolbar_mega_pill_style(COMFORT, object_name="deletorToolbar"))
        self._toolbar = toolbar
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(16, 6, 16, 6)
        tl.setSpacing(8)
        tl.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._view_chrome = ViewModeChrome(toolbar, initial_mode="list", dense=COMFORT, initial_count="")
        self._view_chrome.mode_changed.connect(self._on_view_mode)
        self._view_chrome.add_to_layout(tl)
        self._summary = ElidedLabel("Pick rules, then Find")
        self._view_chrome._apply_count_style(self._summary)
        self._summary.setMinimumWidth(0)
        self._summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        tl.addWidget(self._summary, 1)
        self._btn_find = QPushButton("🔍  Find")
        self._btn_find.setFixedHeight(32)
        self._btn_find.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_find.clicked.connect(self._emit_find)
        tl.addWidget(self._btn_find)
        toolbar_row.addWidget(toolbar)
        outer.addLayout(toolbar_row)

        container = QFrame()
        self._container = container
        container.setObjectName("queueListContainer")
        container.setStyleSheet(ut.queue_list_panel_stylesheet())
        cl = QVBoxLayout(container)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.setSpacing(8)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        try:
            from steempeg.ui.widgets.vertical_scrollbar import (
                ensure_steempg_vertical_scrollbar,
                queue_scrollbar_chrome,
            )

            ensure_steempg_vertical_scrollbar(self._scroll, chrome=queue_scrollbar_chrome())
        except Exception:
            pass
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(0, 0, 4, 0)
        self._content_layout.setSpacing(8)
        for cap in self._build_rules():
            self._content_layout.addWidget(cap)

        head = QHBoxLayout()
        head.setContentsMargins(4, 4, 0, 0)
        self._results_label = QLabel("")
        self._results_label.setStyleSheet(
            f"color: #c4b5e8; font-size: 13px; font-weight: bold; {_CARD_LABEL_CSS}"
        )
        head.addWidget(self._results_label)
        head.addStretch()
        self._btn_all = QPushButton("All")
        self._btn_none = QPushButton("None")
        for b in (self._btn_all, self._btn_none):
            b.setFixedHeight(28)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            head.addWidget(b)
        self._btn_all.clicked.connect(lambda: self._check_all(True))
        self._btn_none.clicked.connect(lambda: self._check_all(False))
        self._results_head = QWidget()
        self._results_head.setStyleSheet("background: transparent;")
        self._results_head.setLayout(head)
        self._results_head.hide()
        self._content_layout.addWidget(self._results_head)

        self._list_host = QWidget()
        self._list_host.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(10)
        self._grid_host = QWidget()
        self._grid_host.setStyleSheet("background: transparent;")
        self._grid_layout = QGridLayout(self._grid_host)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setHorizontalSpacing(_GRID_GAP)
        self._grid_layout.setVerticalSpacing(_GRID_GAP)
        self._grid_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._grid_host.hide()
        self._content_layout.addWidget(self._list_host)
        self._content_layout.addWidget(self._grid_host)
        self._content_layout.addStretch()
        self._scroll.setWidget(content)
        cl.addWidget(self._scroll, 1)

        self._chk_permanent = _check("Delete permanently")
        self._chk_permanent.setToolTip("Skip the Recycle Bin — cannot be undone")
        self._chk_permanent.toggled.connect(self._sync_start_button)
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.addWidget(self._chk_permanent, 0, Qt.AlignmentFlag.AlignVCenter)
        bottom.addStretch()
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.setFixedHeight(32)
        self._btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_cancel.clicked.connect(self.cancel_requested.emit)
        self._btn_cancel.hide()
        bottom.addWidget(self._btn_cancel)
        self._btn_start = QPushButton("")
        self._btn_start.setFixedHeight(32)
        self._btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_start.clicked.connect(self._emit_start)
        bottom.addWidget(self._btn_start)
        cl.addLayout(bottom)

        outer.addWidget(container, 1)
        self.apply_ui_theme_chrome()
        self._sync_start_button()

    def apply_ui_theme_chrome(self) -> None:
        """Re-tint every control for the active theme (Default / TrueDark / OLED)."""
        self._toolbar.setStyleSheet(toolbar_mega_pill_style(COMFORT, object_name="deletorToolbar"))
        self._container.setStyleSheet(ut.queue_list_panel_stylesheet())
        for btn in (self._btn_find, self._btn_cancel):
            btn.setStyleSheet(_btn_style(32))
        for btn in (self._btn_all, self._btn_none):
            btn.setStyleSheet(_btn_style(28))
        self._btn_start.setStyleSheet(_danger_btn_style())
        self._btn_games.setStyleSheet(_field_btn_style())
        chip = _chip_style()
        for btn in (self._chk_clips, self._chk_rendered):
            btn.setStyleSheet(chip)
        field_css = _field_style()
        for w in self._fields:
            w.setStyleSheet(field_css)
        capsule_css = _capsule_style()
        for cap in self.findChildren(QFrame, "CategoryCapsule"):
            cap.setStyleSheet(capsule_css)
        for card in self._cards:
            card.refresh()

    # --- rules -------------------------------------------------------------

    def _build_rules(self) -> list[QFrame]:
        src = QWidget()
        src.setStyleSheet("background: transparent;")
        sl = QHBoxLayout(src)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)
        self._chk_clips = QPushButton("📁  Clips")
        self._chk_rendered = QPushButton("🎬  Rendered videos")
        for btn in (self._chk_clips, self._chk_rendered):
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            sl.addWidget(btn)
        self._chk_clips.setChecked(True)
        sl.addStretch()

        self._size_spin = QDoubleSpinBox()
        self._size_spin.setRange(1, 100000)
        self._size_spin.setDecimals(0)
        self._size_spin.setValue(500)
        self._size_spin.setSuffix(" MB")
        short_edit = QTimeEdit(QTime(0, 0, 10))
        long_edit = QTimeEdit(QTime(0, 5, 0))
        for te in (short_edit, long_edit):
            te.setDisplayFormat("HH:mm:ss")
        age_spin = QSpinBox()
        age_spin.setRange(1, 3650)
        age_spin.setValue(90)
        age_spin.setSuffix(" days")
        self._fields = [self._size_spin, short_edit, long_edit, age_spin]

        self._r_size = _RuleRow("Larger than", self._size_spin)
        self._r_short = _RuleRow("Shorter than", short_edit)
        self._r_long = _RuleRow("Longer than", long_edit)
        self._r_age = _RuleRow("Older than", age_spin)
        self._btn_games = QPushButton("Any game")
        self._btn_games.clicked.connect(self._open_games_menu)
        self._r_games = _RuleRow("Game", self._btn_games)
        self._r_dead = _RuleRow("Dead")
        self._r_issues = _RuleRow("Has issues")
        self._r_rendered = _RuleRow("Clips already rendered")
        self._r_selection = _RuleRow("Only selected in library")
        self._r_filter = _RuleRow("Only visible with current filter")

        def _stack(rows: list[QWidget]) -> QWidget:
            host = QWidget()
            host.setStyleSheet("background: transparent;")
            lay = QVBoxLayout(host)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(6)
            for r in rows:
                lay.addWidget(r)
            return host

        return [
            _capsule("📂 Look in:", src),
            _capsule("📏 Size & length:", _stack([self._r_size, self._r_short, self._r_long])),
            _capsule("📅 Age & game:", _stack([self._r_age, self._r_games])),
            _capsule(
                "🩺 Health & scope:",
                _stack([
                    self._r_dead, self._r_issues, self._r_rendered,
                    self._r_selection, self._r_filter,
                ]),
            ),
        ]

    def set_games(self, games: list[str]) -> None:
        self._games = sorted({g for g in games if g}, key=str.lower)
        self._picked_games &= set(self._games)
        self._sync_games_button()

    def _open_games_menu(self) -> None:
        self.games_requested.emit()
        menu = QMenu(self._btn_games)
        menu.setStyleSheet(queue_menu_stylesheet())
        if self._games:
            every = menu.addAction("Every game")
            every.setCheckable(True)
            every.setChecked(self._picked_games >= set(self._games))
            every.toggled.connect(self._toggle_every_game)
            menu.addSeparator()
        for game in self._games:
            act = menu.addAction(game)
            act.setCheckable(True)
            act.setChecked(game in self._picked_games)
            act.toggled.connect(lambda on, g=game: self._toggle_game(g, on))
        if not self._games:
            menu.addAction("No games yet").setEnabled(False)
        menu.exec(self._btn_games.mapToGlobal(self._btn_games.rect().bottomLeft()))

    def _toggle_game(self, game: str, on: bool) -> None:
        if on:
            self._picked_games.add(game)
            self._r_games.check.setChecked(True)
        else:
            self._picked_games.discard(game)
        self._sync_games_button()

    def _toggle_every_game(self, on: bool) -> None:
        self._picked_games = set(self._games) if on else set()
        if on:
            self._r_games.check.setChecked(True)
        self._sync_games_button()

    def _sync_games_button(self) -> None:
        n = len(self._picked_games)
        if n == 0:
            self._btn_games.setText("Any game")
        elif self._games and self._picked_games >= set(self._games) and n > 1:
            self._btn_games.setText("Every game")
        elif n == 1:
            self._btn_games.setText(next(iter(self._picked_games)))
        else:
            self._btn_games.setText(f"{n} games")

    def current_rules(self) -> DeleteRules:
        return DeleteRules(
            include_clips=self._chk_clips.isChecked(),
            include_rendered=self._chk_rendered.isChecked(),
            min_size_mb=self._size_spin.value() if self._r_size.on else None,
            max_duration_sec=float(_secs(self._r_short.editor)) if self._r_short.on else None,
            min_duration_sec=float(_secs(self._r_long.editor)) if self._r_long.on else None,
            health_dead=self._r_dead.on,
            health_degraded=self._r_issues.on,
            older_than_days=int(self._r_age.editor.value()) if self._r_age.on else None,
            games=set(self._picked_games) if self._r_games.on else set(),
            only_rendered=self._r_rendered.on,
            only_selection=self._r_selection.on,
            only_filter=self._r_filter.on,
        )

    def _emit_find(self) -> None:
        rules = self.current_rules()
        if not rules.include_clips and not rules.include_rendered:
            self._summary.setText("Pick Clips and/or Rendered videos")
            return
        if self._r_games.on and not self._picked_games:
            self._summary.setText("Pick at least one game")
            self._open_games_menu()
            return
        if not rules.has_any_filter():
            self._summary.setText("Turn on at least one rule")
            return
        self.find_requested.emit(rules)

    # --- view mode ---------------------------------------------------------

    def set_view_mode(self, mode: str) -> None:
        mode = mode if mode in ("list", "grid") else "list"
        self._view_chrome.set_mode(mode, emit=False)
        self._apply_view_mode(mode)

    def _on_view_mode(self, mode: str) -> None:
        self._apply_view_mode(mode)
        self.view_mode_changed.emit(mode)

    def _apply_view_mode(self, mode: str) -> None:
        if mode == self._view_mode and self._cards:
            return
        self._view_mode = mode
        self._list_host.setVisible(mode == "list")
        self._grid_host.setVisible(mode == "grid")
        self._rebuild_cards()

    # --- results -----------------------------------------------------------

    def _thumb(self, path: str, w: int, h: int, radius: float, *, top_only: bool = False) -> QPixmap:
        key = (path, w, h, radius, top_only)
        pix = self._pix_cache.get(key)
        if pix is None:
            pix = _rounded_thumb(path, w, h, radius, top_only=top_only)
            self._pix_cache[key] = pix
        return pix

    def set_scanning(self, scanning: bool, done: int = 0, total: int = 0) -> None:
        self._scanning = scanning
        self._btn_find.setEnabled(not scanning and not self._running)
        if scanning:
            self._summary.setText(f"Searching… {done}/{total}" if total else "Searching…")
        self._sync_start_button()

    def set_results(self, candidates: list[DeleteCandidate]) -> None:
        self._candidates = list(candidates)
        self._checked = {c.key: True for c in candidates}
        self._status = {}
        self._pix_cache = {}
        self._rebuild_cards()
        self._results_head.setVisible(bool(candidates))
        self._view_chrome.set_count(len(candidates))
        self._summary.setText("found" if candidates else "Nothing matches these rules")

    def candidate_sizes(self) -> dict[str, int]:
        return {c.key: c.size_bytes for c in self._candidates}

    def _clear_cards(self) -> None:
        for card in self._cards:
            card.hide()
            card.deleteLater()
        self._cards = []
        self._card_by_key = {}
        self._grid_cols = 0

    def _rebuild_cards(self) -> None:
        self._clear_cards()
        cls = _GridCard if self._view_mode == "grid" else _ListCard
        for i, cand in enumerate(self._candidates):
            card = cls(cand, self, load_thumb=i < _THUMB_ROW_CAP)
            self._cards.append(card)
            self._card_by_key[cand.key] = card
            if cls is _ListCard:
                self._list_layout.addWidget(card)
        if cls is _GridCard:
            self._relayout_grid(force=True)
        self._sync_start_button()

    def _relayout_grid(self, *, force: bool = False) -> None:
        if self._view_mode != "grid" or not self._cards:
            return
        avail = max(1, self._scroll.viewport().width() - 4)
        cols = max(1, (avail + _GRID_GAP) // (_GRID_CARD_W + _GRID_GAP))
        if cols == self._grid_cols and not force:
            return
        self._grid_cols = cols
        for card in self._cards:
            self._grid_layout.removeWidget(card)
        for i, card in enumerate(self._cards):
            self._grid_layout.addWidget(card, i // cols, i % cols)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._relayout_grid()

    def _show_card_menu(self, cand: DeleteCandidate, global_pos) -> None:
        if not os.path.exists(cand.path):
            return
        menu = QMenu(self)
        menu.setStyleSheet(ut.library_menu_stylesheet())
        act_preview = menu.addAction("▶  Preview in player")
        act_reveal = menu.addAction("📂  Open in folder")
        chosen = menu.exec(global_pos)
        if chosen is act_preview:
            self.preview_requested.emit(cand.path, cand.kind)
        elif chosen is act_reveal:
            self.reveal_requested.emit(cand.path, cand.kind)

    def _toggle_card(self, key: str) -> None:
        if self._running or self._status.get(key, ("", ""))[0] in ("deleting", "done"):
            return
        self._checked[key] = not self._checked.get(key, True)
        card = self._card_by_key.get(key)
        if card is not None:
            card.refresh()
        self._sync_start_button()

    def _check_all(self, on: bool) -> None:
        for key in self._checked:
            if self._status.get(key, ("", ""))[0] not in ("deleting", "done"):
                self._checked[key] = on
        for card in self._cards:
            card.refresh()
        self._sync_start_button()

    def _pending_candidates(self) -> list[DeleteCandidate]:
        return [
            c for c in self._candidates
            if self._checked.get(c.key, True)
            and self._status.get(c.key, ("", ""))[0] not in ("deleting", "done")
        ]

    def _sync_start_button(self, *_args) -> None:
        picked = self._pending_candidates()
        total = sum(c.size_bytes for c in picked)
        if self._candidates:
            self._results_label.setText(
                f"{len(picked)} of {len(self._candidates)} selected · {format_size(total)}"
            )
        verb = "Delete forever" if self._chk_permanent.isChecked() else "Recycle"
        self._btn_start.setText(f"🗑  {verb} ({len(picked)})" if picked else f"🗑  {verb}")
        self._btn_start.setEnabled(bool(picked) and not self._running and not self._scanning)

    def _emit_start(self) -> None:
        picked = self._pending_candidates()
        if picked:
            self.start_requested.emit(
                [(c.path, c.kind) for c in picked], self._chk_permanent.isChecked()
            )

    # --- run ---------------------------------------------------------------

    def set_running(self, running: bool) -> None:
        self._running = running
        self._btn_cancel.setVisible(running)
        self._btn_find.setEnabled(not running and not self._scanning)
        self._chk_permanent.setEnabled(not running)
        self._btn_all.setEnabled(not running)
        self._btn_none.setEnabled(not running)
        self._sync_start_button()

    def _set_status(self, path: str, status: str, error: str = "") -> None:
        key = os.path.normcase(os.path.normpath(path))
        self._status[key] = (status, error)
        card = self._card_by_key.get(key)
        if card is not None:
            card.refresh()

    def mark_started(self, path: str) -> None:
        self._set_status(path, "deleting")

    def mark_finished(self, path: str, ok: bool, error: str = "") -> None:
        self._set_status(path, "done" if ok else "error", error)
        self._sync_start_button()

    def set_run_summary(self, text: str) -> None:
        self._summary.setText(text)
