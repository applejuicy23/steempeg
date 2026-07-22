"""Render-queue sidebar for the portable Render sheet — desktop-style cards with thumbs."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.paths import get_resource_path, get_save_directory, reveal_in_file_manager
from steempeg.render.queue import JobStatus, RenderJob
from steempeg.render.queue_display import (
    format_job_datetime_line,
    format_job_output,
    format_job_preset,
    format_job_trim,
)
from steempeg.ui.queue_card_shared import (
    _FONT,
    _QUEUE_MENU_STYLE,
    build_queue_thumb_strip,
    job_can_remove,
    set_game_icon_label,
)
from steempeg.ui.ui_density import COMFORT
from steempeg.ui.widgets.elided_label import ElidedLabel

# Compact rail on Deck-class shells; roomy rail when the host is wide.
_SIDEBAR_W_COMPACT = 376
_SIDEBAR_W_SPACIOUS = 400
_THUMB_W = 120
_THUMB_H = 72
_TITLE_ICON = 22
_QUEUE_ICON = 18
_REMOVE_SIZE = 26
_REMOVE_INSET = 8  # breathing room from the card corner
# Gutter so title/meta clear the overlaid ✕.
_REMOVE_TEXT_PAD = _REMOVE_SIZE + _REMOVE_INSET
# Same typeface as desktop Refresh / Choose Folder (Segoe UI bold + footer_font).
_HEADER_FONT = int(COMFORT.footer_font)
_HEADER_RADIUS = int(COMFORT.footer_radius)
_HEADER_PAD = COMFORT.footer_pad
_HEADER_MIN_H = int(COMFORT.footer_min_h)

_TOGGLE_SELECT_MODIFIERS = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
_MULTI_SELECT_MODIFIERS = (
    Qt.KeyboardModifier.ControlModifier
    | Qt.KeyboardModifier.ShiftModifier
    | Qt.KeyboardModifier.AltModifier
)

_PANEL = """
QFrame#portableQueueHeader, QFrame#portableQueueList {
    background-color: #2d2d2d;
    border: 1px solid #383838;
    border-radius: 10px;
}
"""

_ROW_IDLE = f"""
QFrame#portableQueueRow {{
    background-color: #2a2a2a;
    border: 1px solid #444444;
    border-radius: 10px;
}}
QFrame#portableQueueRow:hover {{
    border-color: #7a6aa8;
}}
QFrame#portableQueueRow QLabel {{
    background: transparent;
    border: none;
    {_FONT}
}}
"""

_ROW_SELECTED = f"""
QFrame#portableQueueRow {{
    background-color: #322a45;
    border: 2px solid #8e7cc3;
    border-radius: 10px;
}}
QFrame#portableQueueRow QLabel {{
    background: transparent;
    border: none;
    {_FONT}
}}
"""

_REMOVE_BTN_STYLE = """
QPushButton#portableQueueRemoveBtn {
    background-color: rgba(120, 45, 45, 0.92);
    border: 1px solid #aa4444;
    color: #ffcccc;
    font-size: 13px;
    font-weight: bold;
    border-radius: 13px;
    padding: 0;
}
QPushButton#portableQueueRemoveBtn:hover {
    background-color: #cc3333;
    color: #ffffff;
    border: 1px solid #ff6666;
}
"""

_BTN_ADD = f"""
QPushButton#portableQueueAdd {{
    font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
    font-size: {_HEADER_FONT}px;
    font-weight: bold;
    background-color: #383838;
    color: #ffffff;
    border: 2px solid #444444;
    border-radius: {_HEADER_RADIUS}px;
    padding: {_HEADER_PAD};
    min-height: {_HEADER_MIN_H}px;
}}
QPushButton#portableQueueAdd:hover {{
    background-color: #404040;
    border: 2px solid #6b5a8e;
}}
QPushButton#portableQueueAdd:pressed {{
    background-color: #3a324a;
    border: 2px solid #b29ae7;
}}
QPushButton#portableQueueAdd:disabled {{
    background-color: #262626;
    color: #555555;
    border: 2px solid #333333;
}}
"""


def _queue_cache_dir(app) -> str:
    return getattr(app, "cache_dir", None) or os.path.join(get_save_directory(), "cache")


class _PortableQueueRow(QFrame):
    """Queue card: activate on LMB, Alt/Ctrl toggle, Shift range, ✕ + context menu."""

    clicked = Signal(str, object)  # job_id, keyboard modifiers
    remove_requested = Signal(str)

    def __init__(
        self,
        job: RenderJob,
        index: int,
        selected: bool,
        *,
        cache_dir: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("portableQueueRow")
        self._job = job
        self._job_id = job.id
        self._selected = selected
        self._press_on_remove = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_selected(selected)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(8)

        thumb_wrap, badge, _ = build_queue_thumb_strip(
            job,
            width=_THUMB_W,
            height=_THUMB_H,
            show_game_icon=False,
            cache_dir=cache_dir,
        )
        badge.setText(str(index))
        thumb_wrap.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(thumb_wrap, 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(3)
        # Leave a slim gutter so lines don't sit under the overlaid ✕.
        text.setContentsMargins(0, 0, _REMOVE_TEXT_PAD if job_can_remove(job) else 0, 0)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)

        icon = QLabel()
        set_game_icon_label(icon, job, size=_TITLE_ICON)
        title_row.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)

        title = ElidedLabel(job.game_name.strip() or os.path.basename(job.clip_path))
        title.setStyleSheet(f"color: #f0f0f0; font-size: 13px; font-weight: bold; {_FONT}")
        title.setMinimumWidth(0)
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        title_row.addWidget(title, 1)
        text.addLayout(title_row)

        meta = ElidedLabel(format_job_datetime_line(job))
        meta.setStyleSheet(f"color: #888888; font-size: 11px; {_FONT}")
        meta.setMinimumWidth(0)
        text.addWidget(meta)

        preset = ElidedLabel(format_job_preset(job.settings))
        preset.setStyleSheet(f"color: #c4b5e8; font-size: 11px; {_FONT}")
        preset.setMinimumWidth(0)
        text.addWidget(preset)

        trim_text = format_job_trim(job.settings)
        has_trim = (
            job.settings.is_trim_mode
            and job.settings.trim_end_ms > job.settings.trim_start_ms
        )
        if has_trim and trim_text:
            trim_lbl = ElidedLabel(trim_text)
            trim_lbl.setStyleSheet(f"color: #b29ae7; font-size: 11px; {_FONT}")
            trim_lbl.setMinimumWidth(0)
            text.addWidget(trim_lbl)

        out_line = ElidedLabel(format_job_output(job))
        out_line.setStyleSheet(f"color: #999999; font-size: 11px; {_FONT}")
        out_line.setMinimumWidth(0)
        text.addWidget(out_line)

        lay.addLayout(text, 1)

        # Overlay ✕ on the card corner — no layout column, closer to content.
        self._btn_remove = None
        if job_can_remove(job):
            self._btn_remove = QPushButton("✕", self)
            self._btn_remove.setObjectName("portableQueueRemoveBtn")
            self._btn_remove.setFixedSize(_REMOVE_SIZE, _REMOVE_SIZE)
            self._btn_remove.setToolTip("Remove from queue")
            self._btn_remove.setCursor(Qt.CursorShape.PointingHandCursor)
            self._btn_remove.setStyleSheet(_REMOVE_BTN_STYLE)
            self._btn_remove.clicked.connect(
                lambda: self.remove_requested.emit(self._job_id)
            )
            self._btn_remove.raise_()

        for label in self.findChildren(QLabel):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumHeight(max(_THUMB_H + 12, 96))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_remove_btn()

    def showEvent(self, event):
        super().showEvent(event)
        self._place_remove_btn()

    def _place_remove_btn(self) -> None:
        btn = self._btn_remove
        if btn is None:
            return
        btn.move(
            max(0, self.width() - btn.width() - _REMOVE_INSET),
            _REMOVE_INSET,
        )
        btn.raise_()

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self.setStyleSheet(_ROW_SELECTED if self._selected else _ROW_IDLE)

    def _hit_remove_button(self, event) -> bool:
        if self._btn_remove is None or not self._btn_remove.isVisible():
            return False
        gp = event.globalPosition().toPoint()
        return self._btn_remove.rect().contains(self._btn_remove.mapFromGlobal(gp))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._hit_remove_button(event):
            self._press_on_remove = True
            event.accept()
            return
        self._press_on_remove = False
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._job_id, event.modifiers())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._press_on_remove:
            self._press_on_remove = False
            if (
                event.button() == Qt.MouseButton.LeftButton
                and self._hit_remove_button(event)
            ):
                self.remove_requested.emit(self._job_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(_QUEUE_MENU_STYLE)
        job = self._job

        act_select = menu.addAction("▶️  Select in editor")
        act_select.triggered.connect(
            lambda: self.clicked.emit(self._job_id, Qt.KeyboardModifier.NoModifier)
        )

        act_open_clip = menu.addAction("📂  Open clip folder")
        clip_exists = bool(job.clip_path) and os.path.isdir(job.clip_path)
        act_open_clip.setEnabled(clip_exists)
        if clip_exists:
            act_open_clip.triggered.connect(
                lambda: reveal_in_file_manager(job.clip_path)
            )

        if job_can_remove(job):
            menu.addSeparator()
            act_remove = menu.addAction("🗑️  Remove from queue")
            act_remove.triggered.connect(
                lambda: self.remove_requested.emit(self._job_id)
            )

        menu.exec(event.globalPos())


class PortableQueueSidebar(QWidget):
    """Left queue rail: rounded header (title + Add) above a separate clips list panel."""

    job_selected = Signal(str)

    def __init__(self, app, parent: QWidget | None = None, *, compact: bool = True):
        super().__init__(parent)
        self._app = app
        self._selected_ids: set[str] = set()
        self._anchor_id: str | None = None
        self._row_ids: list[str] = []
        self._rows: dict[str, _PortableQueueRow] = {}
        rail_w = _SIDEBAR_W_COMPACT if compact else _SIDEBAR_W_SPACIOUS
        self.setFixedWidth(rail_w)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(_PANEL)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # --- Header panel: icon + Queue title + Add + ---
        header = QFrame()
        header.setObjectName("portableQueueHeader")
        header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        head_lay = QHBoxLayout(header)
        head_lay.setContentsMargins(12, 10, 12, 10)
        head_lay.setSpacing(8)

        self._title_icon = QLabel()
        self._title_icon.setFixedSize(_QUEUE_ICON, _QUEUE_ICON)
        self._title_icon.setStyleSheet("background: transparent; border: none;")
        queue_icon_path = get_resource_path("queue.png")
        if queue_icon_path and os.path.isfile(queue_icon_path):
            self._title_icon.setPixmap(
                QPixmap(queue_icon_path).scaled(
                    _QUEUE_ICON,
                    _QUEUE_ICON,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        head_lay.addWidget(self._title_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        self._title = QLabel("Queue")
        self._title.setStyleSheet(
            f"color: #ffffff; font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', "
            f"'Noto Emoji', Arial, sans-serif; font-size: {_HEADER_FONT}px; "
            f"font-weight: bold; background: transparent;"
        )
        head_lay.addWidget(self._title, 1, Qt.AlignmentFlag.AlignVCenter)

        # Heavy plus (U+FF0B fullwidth) reads bolder than ASCII "+" at the same px size.
        self._btn_add = QPushButton("Add ＋")
        self._btn_add.setObjectName("portableQueueAdd")
        self._btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_add.setStyleSheet(_BTN_ADD)
        self._btn_add.setToolTip("Add the current clip to the queue")
        self._btn_add.clicked.connect(self._on_add_current)
        head_lay.addWidget(self._btn_add, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(header, 0)

        # --- List panel: clip cards only ---
        list_panel = QFrame()
        list_panel.setObjectName("portableQueueList")
        list_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        list_lay = QVBoxLayout(list_panel)
        list_lay.setContentsMargins(8, 8, 8, 8)
        list_lay.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { border: none; background: transparent; width: 10px; margin: 2px; }"
            "QScrollBar::handle:vertical { background: #4e4e4e; min-height: 30px; border-radius: 4px; }"
            "QScrollBar::handle:vertical:hover { background: #b29ae7; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
        )

        self._host = QWidget()
        self._host.setStyleSheet("background: transparent;")
        self._list = QVBoxLayout(self._host)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(8)
        self._list.addStretch(1)

        self._empty = QLabel("Empty — Add current\nclip, or queue from\nClips Manager.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._empty.setStyleSheet(f"color: #777777; font-size: 11px; {_FONT}")
        self._list.insertWidget(0, self._empty)

        scroll.setWidget(self._host)
        list_lay.addWidget(scroll, 1)
        root.addWidget(list_panel, 1)
        self.refresh()

    def refresh(self) -> None:
        # Clear rows (keep stretch at end).
        while self._list.count() > 1:
            item = self._list.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        jobs = [
            j
            for j in list(getattr(getattr(self._app, "render_queue", None), "jobs", []) or [])
            if getattr(j, "status", None) != JobStatus.COMPLETED
        ]
        live_ids = {j.id for j in jobs}
        self._selected_ids = {jid for jid in self._selected_ids if jid in live_ids}
        active = getattr(self._app, "_selected_queue_job_id", None)
        if active and active in live_ids:
            self._selected_ids.add(active)
        if self._anchor_id not in live_ids:
            self._anchor_id = active if active in live_ids else (
                next(iter(self._selected_ids), None)
            )

        self._title.setText(f"Queue ({len(jobs)})")
        self._row_ids = []
        self._rows = {}

        if not jobs:
            self._empty = QLabel("Empty — Add current\nclip, or queue from\nClips Manager.")
            self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._empty.setWordWrap(True)
            self._empty.setStyleSheet(f"color: #777777; font-size: 11px; {_FONT}")
            self._list.insertWidget(0, self._empty)
            self._sync_add_enabled()
            return

        cache_dir = _queue_cache_dir(self._app)
        for pending_i, job in enumerate(jobs, start=1):
            row = _PortableQueueRow(
                job,
                pending_i,
                job.id in self._selected_ids,
                cache_dir=cache_dir,
                parent=self._host,
            )
            row.clicked.connect(self._on_row_clicked)
            row.remove_requested.connect(self._on_remove_requested)
            self._list.insertWidget(self._list.count() - 1, row)
            self._row_ids.append(job.id)
            self._rows[job.id] = row

        self._sync_add_enabled()

    def _apply_selection_styles(self) -> None:
        for job_id, row in self._rows.items():
            row.set_selected(job_id in self._selected_ids)

    def _on_row_clicked(self, job_id: str, mods) -> None:
        mods = mods or Qt.KeyboardModifier.NoModifier
        if mods & _TOGGLE_SELECT_MODIFIERS:
            if job_id in self._selected_ids:
                self._selected_ids.discard(job_id)
            else:
                self._selected_ids.add(job_id)
            self._anchor_id = job_id
            self._apply_selection_styles()
            return

        if mods & Qt.KeyboardModifier.ShiftModifier:
            if self._anchor_id and self._anchor_id in self._row_ids and job_id in self._row_ids:
                a = self._row_ids.index(self._anchor_id)
                b = self._row_ids.index(job_id)
                lo, hi = sorted((a, b))
                self._selected_ids = set(self._row_ids[lo : hi + 1])
            else:
                self._selected_ids = {job_id}
                self._anchor_id = job_id
            self._apply_selection_styles()
            return

        self._selected_ids = {job_id}
        self._anchor_id = job_id
        self._apply_selection_styles()
        self.job_selected.emit(job_id)

    def _on_remove_requested(self, job_id: str) -> None:
        if job_id in self._selected_ids and len(self._selected_ids) > 1:
            ids = list(self._selected_ids)
        else:
            ids = [job_id]
        if hasattr(self._app, "remove_queue_jobs"):
            self._app.remove_queue_jobs(ids)
        elif hasattr(self._app, "remove_queue_job"):
            for jid in ids:
                self._app.remove_queue_job(jid)
        self._selected_ids -= set(ids)
        self.refresh()

    def _sync_add_enabled(self) -> None:
        resolve = getattr(self._app, "_resolve_export_clip_path", None)
        ok = False
        if callable(resolve):
            try:
                ok = bool(resolve())
            except Exception:
                ok = False
        self._btn_add.setEnabled(ok and not getattr(self._app, "_is_rendering", False))

    def _on_add_current(self) -> None:
        resolve = getattr(self._app, "_resolve_export_clip_path", None)
        path = resolve() if callable(resolve) else None
        if not path:
            return
        if hasattr(self._app, "add_clip_to_render_queue"):
            self._app.add_clip_to_render_queue(path)
        self.refresh()
