"""Right-side render queue panel — list or grid job cards with status colours."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal, QMimeData, QPoint, QRectF, QEvent, QSize
from PySide6.QtGui import QDrag, QPixmap, QPainter, QColor, QPen, QPainterPath
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.paths import get_save_directory
from steempeg.ui.icon_assets import load_icon
from steempeg.render.queue import STATUS_COLORS, JobStatus, RenderJob
from steempeg.render.queue_display import (
    format_job_datetime_line,
    format_job_output,
    format_job_preset,
    format_job_trim,
)
from steempeg.ui.layout_defaults import (
    LIBRARY_TAB_TO_TOOLBAR_SPACING,
    RENDER_QUEUE_BOTTOM_INSET,
)
from steempeg.ui.library.library_tab import LibraryTabWidget
from steempeg.ui.widgets.elided_label import ElidedLabel
from steempeg.ui.queue_card_shared import (
    _FONT,
    _LIST_THUMB_H,
    _LIST_THUMB_W,
    _MIME_JOB_ID,
    _QUEUE_CHROME_INSET,
    _QUEUE_MENU_STYLE,
    build_queue_thumb_strip,
    job_accepts_drop as _job_accepts_drop,
    job_can_remove as _job_can_remove,
    set_game_icon_label,
    status_dot_style as _status_dot_style,
)

_LIST_TITLE_ICON = 28

from steempeg.ui.render_queue_grid import (
    QueueGridJobCard,
    _CARD_W as _GRID_CARD_W,
    _REMOVE_BTN_STYLE,
)
_DRAG_PIXMAP_MAX_W = 300
_DRAG_PIXMAP_MAX_H = 88
_SPLITTER_GUTTER = 10
_GRID_GAP = 10
_ROUNDED_LIST_BOX = (
    "QFrame { background-color: #2d2d2d; border: 1px solid #353535; border-radius: 12px; }"
)
_QUEUE_TOOLBAR_BOX = (
    "QFrame#queueToolbar { background-color: #2d2d2d; border: 1px solid #353535;"
    " border-radius: 20px; }"
)
_QUEUE_TOGGLE_ACTIVE = (
    "background-color: #5138e6; color: #ffffff; border-radius: 12px;"
    " font-weight: bold; font-size: 12px; padding: 6px 16px; border: none;"
)
_QUEUE_TOGGLE_INACTIVE = (
    "background-color: transparent; color: #888888; border-radius: 12px;"
    " font-weight: bold; font-size: 12px; padding: 6px 16px; border: none;"
)
_SCROLL_STYLE = """
    QScrollArea { background: transparent; border: none; }
    QWidget#queueListHost { background: transparent; }
    QScrollBar:vertical { border: none; background: transparent; width: 10px; margin: 2px; }
    QScrollBar::handle:vertical { background: #4e4e4e; min-height: 30px; border-radius: 4px; }
    QScrollBar::handle:vertical:hover { background: #b29ae7; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
"""


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


class QueueJobCard(QFrame):
    clicked = Signal(str)
    remove_requested = Signal(str)
    dropped_on = Signal(str, str)

    def __init__(
        self,
        job: RenderJob,
        selected: bool = False,
        cache_dir: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._cache_dir = cache_dir
        self.setObjectName("QueueJobCard")
        self._job = job
        self._job_id = job.id
        self._drag_start = QPoint()
        self._selected = selected
        self._drop_highlight = False
        self._hovered = False
        self._press_on_remove = False
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(_job_accepts_drop(job))
        self.setMinimumWidth(0)
        self._apply_card_style()

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        thumb_wrap, self._num_label, _ = build_queue_thumb_strip(
            job, show_game_icon=False, cache_dir=self._cache_dir
        )
        thumb_wrap.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        root.addWidget(thumb_wrap, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        text_col.setContentsMargins(0, 0, 0, 0)

        title_row_host = QWidget()
        title_row_host.setFixedHeight(_LIST_TITLE_ICON)
        title_row_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        title_row = QHBoxLayout(title_row_host)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)

        self._game_icon = QLabel()
        set_game_icon_label(self._game_icon, job, size=_LIST_TITLE_ICON)
        title_row.addWidget(self._game_icon, 0, Qt.AlignmentFlag.AlignTop)

        title_text = job.game_name.strip() or os.path.basename(job.clip_path)
        title_wrap = QWidget()
        title_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        title_wrap.setMinimumWidth(0)
        title_wrap_lay = QHBoxLayout(title_wrap)
        title_wrap_lay.setContentsMargins(0, 0, 0, 0)
        title = ElidedLabel(title_text)
        title.setStyleSheet(f"color: #f0f0f0; font-weight: bold; font-size: 13px; {_FONT}")
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        title.setMinimumWidth(0)
        self._title_label = title
        title_wrap_lay.addWidget(title, 1)
        title_row.addWidget(title_wrap, 1, Qt.AlignmentFlag.AlignVCenter)
        text_col.addWidget(title_row_host)

        meta = QLabel(format_job_datetime_line(job))
        meta.setStyleSheet(f"color: #888888; font-size: 11px; {_FONT}")
        meta.setWordWrap(False)
        meta.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        meta.setMinimumWidth(0)
        self._meta_label = meta

        preset = QLabel(format_job_preset(job.settings))
        preset.setStyleSheet(f"color: #c4b5e8; font-size: 11px; {_FONT}")
        preset.setWordWrap(False)
        preset.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        preset.setMinimumWidth(0)
        self._preset_label = preset

        trim_text = format_job_trim(job.settings)
        has_trim = job.settings.is_trim_mode and job.settings.trim_end_ms > job.settings.trim_start_ms
        trim_lbl = QLabel(trim_text)
        trim_lbl.setStyleSheet(f"color: #b29ae7; font-size: 11px; {_FONT}")
        trim_lbl.setVisible(has_trim)
        trim_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        trim_lbl.setMinimumWidth(0)
        self._trim_label = trim_lbl

        out_text = format_job_output(job)
        out_line = ElidedLabel(out_text)
        out_line.setStyleSheet(f"color: #999999; font-size: 11px; {_FONT}")
        out_line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        out_line.setMinimumWidth(0)
        self._out_label = out_line

        text_col.addWidget(meta)
        text_col.addWidget(preset)
        text_col.addWidget(trim_lbl)
        text_col.addWidget(out_line)

        text_host = QWidget()
        text_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        text_host.setMinimumWidth(0)
        text_host.setLayout(text_col)
        root.addWidget(text_host, 1, Qt.AlignmentFlag.AlignTop)

        self._btn_remove = None
        if _job_can_remove(job):
            self._btn_remove = QPushButton("✕")
            self._btn_remove.setObjectName("queueRemoveBtn")
            self._btn_remove.setFixedSize(26, 26)
            self._btn_remove.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._btn_remove.setToolTip("Remove from queue")
            self._btn_remove.setCursor(Qt.PointingHandCursor)
            self._btn_remove.setStyleSheet(_REMOVE_BTN_STYLE)
            self._btn_remove.clicked.connect(lambda: self.remove_requested.emit(self._job_id))
            root.addWidget(self._btn_remove, 0, Qt.AlignTop)

        for label in self.findChildren(QLabel):
            if label is self._btn_remove:
                continue
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumHeight(_LIST_THUMB_H + 20)

        self._refresh_num_style()

    def apply_job(self, job: RenderJob, *, selected: bool) -> None:
        """Update card visuals without rebuilding the widget."""
        self._job = job
        self._selected = selected
        self._drop_highlight = False
        self._num_label.setText(str(job.queue_index))
        if hasattr(self, "_game_icon"):
            set_game_icon_label(self._game_icon, job, size=_LIST_TITLE_ICON)
        if hasattr(self, "_title_label"):
            title_text = job.game_name.strip() or os.path.basename(job.clip_path)
            self._title_label.setText(title_text)
        if hasattr(self, "_meta_label"):
            self._meta_label.setText(format_job_datetime_line(job))
        if hasattr(self, "_preset_label"):
            self._preset_label.setText(format_job_preset(job.settings))
        if hasattr(self, "_trim_label"):
            trim_text = format_job_trim(job.settings)
            has_trim = job.settings.is_trim_mode and job.settings.trim_end_ms > job.settings.trim_start_ms
            self._trim_label.setText(trim_text)
            self._trim_label.setVisible(has_trim)
        if hasattr(self, "_out_label"):
            self._out_label.setText(format_job_output(job))
        self.setAcceptDrops(_job_accepts_drop(job))
        self._refresh_num_style()
        self._apply_card_style()

    def set_selected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self._apply_card_style()

    def _drag_preview_pixmap(self) -> QPixmap:
        """A clean, opaque rounded snapshot of the card for the drag cursor.

        A plain self.grab() captured the card's translucent background with hard
        square corners, so the floating preview looked muddy and broken. Here we
        paint a solid rounded panel, clip the live card contents to it, and add the
        purple accent border — giving a crisp "lifted card" while dragging.
        """
        w = max(1, min(self.width(), _DRAG_PIXMAP_MAX_W))
        h = max(1, min(self.height(), _DRAG_PIXMAP_MAX_H))
        dpr = self.devicePixelRatioF()

        pix = QPixmap(int(w * dpr), int(h * dpr))
        pix.setDevicePixelRatio(dpr)
        pix.fill(Qt.transparent)

        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), 12, 12)
        painter.fillPath(path, QColor("#262229"))

        painter.save()
        painter.setClipPath(path)
        painter.setOpacity(0.97)
        self.render(painter, QPoint(0, 0))
        painter.restore()

        painter.setPen(QPen(QColor("#b29ae7"), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 11, 11)
        painter.end()
        return pix

    def _refresh_num_style(self) -> None:
        color = STATUS_COLORS.get(self._job.status, "#ffcc00")
        self._num_label.setStyleSheet(_status_dot_style(color))

    def _apply_card_style(self) -> None:
        color = STATUS_COLORS.get(self._job.status, "#ffcc00")
        r, g, b = _hex_to_rgb(color)
        if self._drop_highlight:
            border = "2px dashed #b29ae7"
        elif self._selected:
            border = "3px solid #b29ae7"
        elif self._hovered:
            border = "2px solid #7a6aa8"
        else:
            border = "2px solid #444444"
        self.setStyleSheet(f"""
            QueueJobCard {{
                background-color: rgba({r}, {g}, {b}, 0.10);
                border: {border};
                border-radius: 12px;
            }}
            QLabel {{ background: transparent; border: none; {_FONT} }}
            QPushButton#queueRemoveBtn {{
                background-color: rgba(120, 45, 45, 0.55);
                border: 1px solid #aa4444;
                color: #ffcccc;
                font-size: 13px;
                font-weight: bold;
                border-radius: 12px;
                padding: 0;
            }}
            QPushButton#queueRemoveBtn:hover {{
                background-color: #cc3333;
                color: #ffffff;
                border: 1px solid #ff6666;
            }}
        """)

    def set_drop_highlight(self, active: bool) -> None:
        if self._drop_highlight == active:
            return
        self._drop_highlight = active
        self._apply_card_style()

    def enterEvent(self, event):
        self._hovered = True
        self._apply_card_style()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._apply_card_style()
        super().leaveEvent(event)

    def _hit_remove_button(self, event) -> bool:
        if self._btn_remove is None or not self._btn_remove.isVisible():
            return False
        gp = event.globalPosition().toPoint()
        return self._btn_remove.rect().contains(self._btn_remove.mapFromGlobal(gp))

    def mousePressEvent(self, event):
        if self._hit_remove_button(event):
            self._press_on_remove = True
            return
        self._press_on_remove = False
        if event.button() == Qt.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if getattr(self, "_press_on_remove", False):
            self._press_on_remove = False
            if self._hit_remove_button(event):
                self.remove_requested.emit(self._job_id)
            return
        if event.button() == Qt.LeftButton:
            if (event.position().toPoint() - self._drag_start).manhattanLength() < 8:
                self.clicked.emit(self._job_id)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, "_press_on_remove", False):
            return
        if not (event.buttons() & Qt.LeftButton):
            return
        if self._job.status != JobStatus.QUEUED:
            return
        if (event.position().toPoint() - self._drag_start).manhattanLength() < QApplication.startDragDistance():
            return

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_MIME_JOB_ID, self._job_id.encode("utf-8"))
        drag.setMimeData(mime)
        drag.setPixmap(self._drag_preview_pixmap())
        drag.setHotSpot(QPoint(min(event.position().toPoint().x(), _DRAG_PIXMAP_MAX_W // 2), 16))

        drag.exec(Qt.DropAction.MoveAction)
        self.update()

    def dragEnterEvent(self, event):
        if not _job_accepts_drop(self._job):
            return
        if event.mimeData().hasFormat(_MIME_JOB_ID):
            raw = event.mimeData().data(_MIME_JOB_ID)
            source_id = bytes(raw).decode("utf-8") if raw else ""
            if source_id and source_id != self._job_id:
                self.set_drop_highlight(True)
                event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.set_drop_highlight(False)
        super().dragLeaveEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(_MIME_JOB_ID):
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.set_drop_highlight(False)
        raw = event.mimeData().data(_MIME_JOB_ID)
        if not raw:
            return
        source_id = bytes(raw).decode("utf-8")
        if source_id and source_id != self._job_id:
            self.dropped_on.emit(source_id, self._job_id)
        event.acceptProposedAction()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(_QUEUE_MENU_STYLE)

        job = self._job
        is_done = job.status == JobStatus.COMPLETED
        output_dir = os.path.dirname(job.output_file) if job.output_file else ""

        act_select = menu.addAction("▶️  Select in editor")
        act_select.triggered.connect(lambda: self.clicked.emit(self._job_id))

        act_open_clip = menu.addAction("📂  Open clip folder")
        clip_exists = bool(job.clip_path) and os.path.isdir(job.clip_path)
        act_open_clip.setEnabled(clip_exists)
        act_open_clip.triggered.connect(lambda: paths.reveal_in_file_manager(job.clip_path))

        if is_done:
            act_open_out = menu.addAction("🎬  Open output folder")
            out_exists = bool(job.output_file and os.path.isfile(job.output_file)) or (
                bool(output_dir) and os.path.isdir(output_dir)
            )
            act_open_out.setEnabled(out_exists)
            act_open_out.triggered.connect(
                lambda: paths.reveal_in_file_manager(job.output_file or output_dir)
            )

        if _job_can_remove(job):
            menu.addSeparator()
            act_remove = menu.addAction("🗑️  Remove from queue")
            act_remove.triggered.connect(lambda: self.remove_requested.emit(self._job_id))

        menu.exec(event.globalPos())


class QueueListHost(QWidget):
    """Drop target for inserting at the end of the queue list."""

    dropped_at_end = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("queueListHost")
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(_MIME_JOB_ID):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(_MIME_JOB_ID):
            event.acceptProposedAction()

    def dropEvent(self, event):
        raw = event.mimeData().data(_MIME_JOB_ID)
        if not raw:
            return
        source_id = bytes(raw).decode("utf-8")
        if source_id:
            self.dropped_at_end.emit(source_id)
        event.acceptProposedAction()


class RenderQueuePanel(QWidget):
    """Render queue column — header pill + list or grid of job cards."""

    job_selected = Signal(str)
    job_remove_requested = Signal(str)
    job_reorder_requested = Signal(str, str)
    job_reorder_after_requested = Signal(str, str)
    clear_queue_requested = Signal()
    history_requested = Signal()
    view_mode_changed = Signal(str)

    def __init__(self, initial_view_mode: str = "grid", parent=None):
        super().__init__(parent)
        self.setObjectName("render_queue_panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent;")
        self._view_mode = initial_view_mode if initial_view_mode in ("list", "grid") else "grid"
        self._selected_id: str | None = None
        self._card_widgets: list = []
        self._jobs: list[RenderJob] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(_SPLITTER_GUTTER, 0, 0, RENDER_QUEUE_BOTTOM_INSET)
        outer.setSpacing(LIBRARY_TAB_TO_TOOLBAR_SPACING)

        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(0, 0, 0, 4)
        tab_row.setSpacing(8)

        self._tab = LibraryTabWidget("🎬 Render Queue", "queue", closable=False)
        self._tab.set_active(True)
        tab_row.addStretch()
        tab_row.addWidget(self._tab)
        tab_row.addStretch()
        outer.addLayout(tab_row)

        toolbar_row = QHBoxLayout()
        toolbar_row.setContentsMargins(_QUEUE_CHROME_INSET, 0, _QUEUE_CHROME_INSET, 0)
        toolbar_row.setSpacing(0)

        toolbar = QFrame()
        toolbar.setObjectName("queueToolbar")
        toolbar.setStyleSheet(_QUEUE_TOOLBAR_BOX)
        tool_layout = QHBoxLayout(toolbar)
        tool_layout.setContentsMargins(16, 6, 16, 6)
        tool_layout.setSpacing(8)

        self._count_label = QLabel("(0)")
        self._count_label.setStyleSheet(
            f"color: #888888; font-weight: bold; font-size: 13px; border: none;"
            f" background: transparent; {_FONT}"
        )

        # Clear — styled like the Clips Manager sort combo (rounded #383838 field).
        self._btn_clear = QPushButton("  Clear")
        self._btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_clear.setToolTip("Clear the render queue")
        self._btn_clear.setIcon(load_icon("clear.png", 16))
        self._btn_clear.setIconSize(QSize(16, 16))
        self._btn_clear.setFixedHeight(32)
        self._btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #383838; color: #e0e0e0; border: 2px solid #4a4a4a;
                border-radius: 8px; padding: 4px 12px; font-size: 13px; font-weight: bold;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QPushButton:hover { background-color: #404040; color: #ffffff; border: 2px solid #6b5a8e; }
            QPushButton:pressed { background-color: #3a324a; border: 2px solid #b29ae7; }
            QPushButton:disabled { background-color: #262626; color: #5a5a5a; border: 2px solid #333333; }
        """)
        _clear_font = self._btn_clear.font()
        _clear_font.setFamily("Segoe UI")
        _clear_font.setBold(True)
        _clear_font.setPixelSize(13)
        self._btn_clear.setFont(_clear_font)
        self._btn_clear.clicked.connect(self.clear_queue_requested.emit)

        # History — styled like the Clips Manager Filter pill (square icon button).
        self._btn_history = QPushButton()
        self._btn_history.setIcon(load_icon("history.png", 16))
        self._btn_history.setIconSize(QSize(16, 16))
        self._btn_history.setFixedSize(32, 32)
        self._btn_history.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_history.setToolTip("Render History — past batches and exports")
        self._btn_history.setStyleSheet("""
            QPushButton {
                background-color: #383838; border: 2px solid #444444;
                border-radius: 8px; padding: 4px;
            }
            QPushButton:hover { background-color: #404040; border: 2px solid #6b5a8e; }
            QPushButton:pressed { background-color: #3a324a; border: 2px solid #b29ae7; }
        """)
        self._btn_history.clicked.connect(self.history_requested.emit)

        actions_group = QWidget()
        actions_group.setStyleSheet("background: transparent; border: none;")
        actions_layout = QHBoxLayout(actions_group)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(4)
        actions_layout.addWidget(self._btn_history)
        actions_layout.addWidget(self._btn_clear)

        lbl_view = QLabel("View")
        lbl_view.setStyleSheet(
            f"color: #777777; font-weight: bold; font-size: 13px; border: none;"
            f" background: transparent; {_FONT}"
        )

        self._view_toggle_pill = QFrame()
        self._view_toggle_pill.setStyleSheet(
            "QFrame { background-color: #141414; border-radius: 14px; border: none; }"
        )
        toggle_layout = QHBoxLayout(self._view_toggle_pill)
        toggle_layout.setContentsMargins(2, 2, 2, 2)
        toggle_layout.setSpacing(0)

        self._btn_view_grid = QPushButton("Grid")
        self._btn_view_list = QPushButton("List")
        for btn in (self._btn_view_grid, self._btn_view_list):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFlat(True)
        self._btn_view_list.clicked.connect(lambda: self._set_view_mode("list"))
        self._btn_view_grid.clicked.connect(lambda: self._set_view_mode("grid"))

        toggle_layout.addWidget(self._btn_view_grid)
        toggle_layout.addWidget(self._btn_view_list)

        tool_layout.addWidget(lbl_view)
        tool_layout.addWidget(self._view_toggle_pill)
        tool_layout.addWidget(self._count_label)
        tool_layout.addStretch()
        tool_layout.addWidget(actions_group)
        toolbar_row.addWidget(toolbar)
        outer.addLayout(toolbar_row)

        self._sync_view_toggle_buttons()

        self._list_container = QFrame()
        self._list_container.setObjectName("queueListContainer")
        self._list_container.setStyleSheet(_ROUNDED_LIST_BOX)
        list_outer = QVBoxLayout(self._list_container)
        list_outer.setContentsMargins(8, 8, 8, 8)
        list_outer.setSpacing(10)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(_SCROLL_STYLE)

        self._list_host = QueueListHost()
        self._list_host.dropped_at_end.connect(self._on_drop_at_end)
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(10)

        self._grid_host = QWidget()
        self._grid_host.setObjectName("queueGridHost")
        self._grid_outer = QHBoxLayout(self._grid_host)
        self._grid_outer.setContentsMargins(0, 0, 0, 0)
        self._grid_outer.setSpacing(0)
        self._grid_outer.addStretch(1)

        self._grid_inner = QWidget()
        self._grid_inner.setObjectName("queueGridInner")
        self._grid_layout = QGridLayout(self._grid_inner)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setHorizontalSpacing(_GRID_GAP)
        self._grid_layout.setVerticalSpacing(_GRID_GAP)
        self._grid_layout.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self._grid_outer.addWidget(self._grid_inner, 0, Qt.AlignTop)

        self._content_stack = QWidget()
        self._content_stack_layout = QVBoxLayout(self._content_stack)
        self._content_stack_layout.setContentsMargins(0, 0, 0, 0)
        self._content_stack_layout.addWidget(self._list_host)
        self._content_stack_layout.addWidget(self._grid_host)
        self._grid_host.hide()

        self._empty_label = QLabel("Queue is empty")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint = QLabel(
            "Right-click a clip in the library and choose\n"
            "<b>Add to queue</b> to build a batch render."
        )
        self._empty_hint.setTextFormat(Qt.TextFormat.RichText)
        self._empty_hint.setWordWrap(True)
        for lbl in (self._empty_label, self._empty_hint):
            lbl.setStyleSheet(
                f"color: #8a8a8a; font-size: 12px; border: none; background: transparent; {_FONT}"
            )
        self._empty_label.setStyleSheet(
            f"color: #c4b5e8; font-size: 14px; font-weight: bold; border: none;"
            f" background: transparent; {_FONT}"
        )

        self._scroll.setWidget(self._content_stack)
        list_outer.addWidget(self._scroll, 1)

        outer.addWidget(self._list_container, 1)

        self._scroll.viewport().installEventFilter(self)

        self.setMinimumWidth(420)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

    def eventFilter(self, obj, event):
        if (
            obj == self._scroll.viewport()
            and event.type() == QEvent.Type.Resize
            and self._view_mode == "grid"
            and self._jobs
        ):
            self._relayout_grid_cards()
        return super().eventFilter(obj, event)

    def _set_view_mode(self, mode: str) -> None:
        if mode not in ("list", "grid") or mode == self._view_mode:
            return
        self._view_mode = mode
        self._sync_view_toggle_buttons()
        self.view_mode_changed.emit(mode)
        self._rebuild_cards()

    def _sync_view_toggle_buttons(self) -> None:
        if self._view_mode == "list":
            self._btn_view_list.setStyleSheet(_QUEUE_TOGGLE_ACTIVE)
            self._btn_view_grid.setStyleSheet(_QUEUE_TOGGLE_INACTIVE)
        else:
            self._btn_view_list.setStyleSheet(_QUEUE_TOGGLE_INACTIVE)
            self._btn_view_grid.setStyleSheet(_QUEUE_TOGGLE_ACTIVE)

    def _active_host_layout(self):
        if self._view_mode == "grid":
            return self._grid_layout
        return self._list_layout

    def _show_active_host(self) -> None:
        is_grid = self._view_mode == "grid"
        self._list_host.setVisible(not is_grid)
        self._grid_host.setVisible(is_grid)

    def _grid_column_count(self) -> int:
        viewport_w = max(1, self._scroll.viewport().width())
        return max(1, viewport_w // (_GRID_CARD_W + _GRID_GAP))

    def _relayout_grid_cards(self) -> None:
        if self._view_mode != "grid" or not self._card_widgets:
            return
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(self._grid_inner)
        cols = self._grid_column_count()
        for index, card in enumerate(self._card_widgets):
            row, col = divmod(index, cols)
            self._grid_layout.addWidget(card, row, col)
        rows_used = (len(self._card_widgets) + cols - 1) // cols
        self._grid_layout.setRowStretch(rows_used, 1)

    def _queue_cache_dir(self) -> str:
        return getattr(self, "cache_dir", None) or os.path.join(get_save_directory(), "cache")

    def _make_card(self, job: RenderJob, selected: bool):
        cache_dir = self._queue_cache_dir()
        if self._view_mode == "grid":
            return QueueGridJobCard(job, selected=selected, cache_dir=cache_dir)
        return QueueJobCard(job, selected=selected, cache_dir=cache_dir)

    def _wire_card(self, card) -> None:
        card.clicked.connect(self._on_card_clicked)
        card.remove_requested.connect(self.job_remove_requested.emit)
        card.dropped_on.connect(self._on_card_drop)

    def _clear_cards(self) -> None:
        for empty_widget in (self._empty_label, self._empty_hint):
            if empty_widget.parent() is not None:
                self._list_layout.removeWidget(empty_widget)

        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w is not None and w not in (self._empty_label, self._empty_hint):
                w.setParent(None)
                w.deleteLater()

        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        self._card_widgets.clear()

    def _rebuild_cards(self) -> None:
        jobs = list(self._jobs)
        selected = self._selected_id
        self._clear_cards()
        self._show_active_host()

        if not jobs:
            self._list_layout.addStretch(1)
            self._list_layout.addWidget(self._empty_label)
            self._list_layout.addWidget(self._empty_hint)
            self._list_layout.addStretch(2)
            self._empty_label.show()
            self._empty_hint.show()
            return

        self._empty_label.hide()
        self._empty_hint.hide()
        for job in jobs:
            card = self._make_card(job, selected=(job.id == selected))
            self._wire_card(card)
            self._card_widgets.append(card)

        if self._view_mode == "grid":
            self._relayout_grid_cards()
        else:
            for card in self._card_widgets:
                self._list_layout.addWidget(card)
            self._list_layout.addStretch()

        self._scroll_to_selected()

    def _clear_drop_highlights(self) -> None:
        for card in self._card_widgets:
            card.set_drop_highlight(False)

    def _on_drop_at_end(self, source_id: str) -> None:
        last_queued = None
        for job in self._jobs:
            if job.status == JobStatus.QUEUED:
                last_queued = job
        if last_queued is None or last_queued.id == source_id:
            return
        self.job_reorder_after_requested.emit(source_id, last_queued.id)

    def refresh(self, jobs: list[RenderJob], selected_id: str | None = None) -> None:
        self._selected_id = selected_id
        self._count_label.setText(f"({len(jobs)})")
        self._btn_clear.setEnabled(len(jobs) > 0)
        self._jobs = list(jobs)

        job_ids = [j.id for j in jobs]
        same_cards = (
            job_ids
            and job_ids == [c._job_id for c in self._card_widgets]
            and len(self._card_widgets) == len(jobs)
            and (
                (self._view_mode == "grid" and isinstance(self._card_widgets[0], QueueGridJobCard))
                or (self._view_mode == "list" and isinstance(self._card_widgets[0], QueueJobCard))
            )
        )
        if same_cards:
            for card, job in zip(self._card_widgets, jobs):
                card.apply_job(job, selected=(job.id == selected_id))
            self._scroll_to_selected()
            return

        self._rebuild_cards()

    def clear_selection(self) -> None:
        """Drop the purple selection ring without rebuilding cards."""
        self._selected_id = None
        for card in self._card_widgets:
            card.set_selected(False)

    def patch_job_trim(self, job: RenderJob) -> None:
        """Lightweight trim-line update for one queue card (no full rebuild)."""
        for card in self._card_widgets:
            if card._job_id != job.id:
                continue
            if hasattr(card, "_trim_label"):
                trim_text = format_job_trim(job.settings)
                has_trim = (
                    job.settings.is_trim_mode
                    and job.settings.trim_end_ms > job.settings.trim_start_ms
                )
                card._trim_label.setText(trim_text)
                card._trim_label.setVisible(has_trim)
            break

    def _scroll_to_selected(self) -> None:
        if not self._selected_id:
            return
        for card in self._card_widgets:
            if card._job_id == self._selected_id:
                self._scroll.ensureWidgetVisible(card)
                break

    def _on_card_drop(self, source_id: str, target_id: str) -> None:
        self._clear_drop_highlights()
        self.job_reorder_requested.emit(source_id, target_id)

    def _on_card_clicked(self, job_id: str) -> None:
        self._selected_id = job_id
        for card in self._card_widgets:
            card.set_selected(card._job_id == job_id)
        self.job_selected.emit(job_id)
