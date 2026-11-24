"""Dialog showing past render-queue batch runs."""
from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import Qt, QSize, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.paths import reveal_in_file_manager
from steempeg.render.queue import JobStatus
from steempeg.render.queue_history import RenderBatchRecord, parse_history_job
from steempeg.ui.icon_assets import load_icon
from steempeg.ui import design_tokens as tok
from steempeg.ui.queue_card_shared import _FONT
from steempeg.ui.render_result_widgets import ExportResultCard
from steempeg.ui.widgets import ElidedLabel
from steempeg.ui.widgets.dialog_chrome import SteempegDialog
from steempeg.ui.widgets.flow_layout import FlowLayout
from steempeg.ui.message_dialog import steempeg_question

_DIALOG_STYLE = """
    QLabel { background: transparent; border: none; }
"""


def _surface_styles() -> str:
    from steempeg.ui import ui_theme as ut

    return ut.render_history_surface_stylesheet()


def _pill_btn_style() -> str:
    from steempeg.ui import ui_theme as ut

    return ut.render_history_pill_button_stylesheet(bold=True)


def _action_btn_style() -> str:
    from steempeg.ui import ui_theme as ut

    return ut.settings_dialog_secondary_button_stylesheet()


def _close_btn_style() -> str:
    from steempeg.ui import ui_theme as ut

    return ut.render_history_close_button_stylesheet()


def _format_batch_when(iso: str) -> str:
    if not iso:
        return "Unknown time"
    try:
        from steempeg.infra.locale_time import format_clip_datetime

        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return format_clip_datetime(dt)
    except ValueError:
        return iso[:16].replace("T", " ")


def _batch_summary(batch: RenderBatchRecord) -> str:
    parts = []
    if batch.completed_count:
        parts.append(f"{batch.completed_count} done")
    if batch.error_count:
        parts.append(f"{batch.error_count} failed")
    if batch.cancelled_count:
        parts.append(f"{batch.cancelled_count} skipped")
    if batch.cancelled and not parts:
        return "Cancelled"
    return ", ".join(parts) if parts else "No renders"


class RenderQueueHistoryDialog(SteempegDialog):
    open_output_requested = Signal(str)
    open_in_rendered_requested = Signal(str)
    open_source_clip_requested = Signal(str)

    def __init__(
        self,
        batches: list[RenderBatchRecord],
        parent=None,
        *,
        cache_dir: str | None = None,
        bar_color: str | None = None,
        bg_color: str | None = None,
    ):
        super().__init__("Render History", parent, bar_color=bar_color, bg_color=bg_color)
        from steempeg.ui.ui_density import scaled_dialog_size

        mw, mh = scaled_dialog_size(520, 510, parent=parent)
        rw, rh = scaled_dialog_size(560, 590, parent=parent)
        self.setMinimumSize(mw, mh)
        self.resize(rw, rh)
        self._batches = batches
        self._cache_dir = cache_dir
        self._apply_history_styles()

        root = self.content_layout

        header = QHBoxLayout()
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_icon = QLabel()
        title_icon.setFixedSize(24, 24)
        title_icon.setPixmap(load_icon("history.png", 22).pixmap(22, 22))
        title_icon.setStyleSheet("background: transparent; border: none;")
        title = QLabel("Render History")
        title.setStyleSheet(tok.STYLE_PANEL_TITLE)
        title_row.addWidget(title_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addLayout(title_row)
        header.addStretch()
        btn_clear = QPushButton("  Clear all")
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.setIcon(load_icon("clear.png", 16))
        btn_clear.setIconSize(QSize(16, 16))
        btn_clear.setStyleSheet(_pill_btn_style())
        from PySide6.QtGui import QFont as _QF
        clear_font = tok.ui_qfont(pixel_size=13, weight=_QF.Weight.Bold)
        btn_clear.setFont(clear_font)
        btn_clear.clicked.connect(self._confirm_clear)
        self._btn_clear = btn_clear
        header.addWidget(btn_clear)
        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._history_scroll = scroll
        tok.apply_dialog_scroll_bg(scroll, self._bg_color)
        from steempeg.ui.library.library_styles import (
            LIBRARY_SCROLLBAR_VERTICAL,
            install_library_vertical_scrollbar,
        )

        scroll.setStyleSheet(
            tok.dialog_scroll_stylesheet(self._bg_color) + LIBRARY_SCROLLBAR_VERTICAL
        )
        install_library_vertical_scrollbar(scroll)

        host = QWidget()
        host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        host.setStyleSheet(f"background-color: {self._bg_color};")
        self._history_scroll_host = host
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(12)

        if not batches:
            empty = QLabel("No batch renders yet")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: #c4b5e8; font-size: 14px; font-weight: bold; padding-top: 32px; {_FONT}"
            )
            hint = QLabel("Run a render queue batch to see exports here.")
            hint.setAlignment(Qt.AlignCenter)
            hint.setWordWrap(True)
            hint.setStyleSheet(f"color: #8a8a8a; font-size: 12px; padding-bottom: 32px; {_FONT}")
            host_layout.addWidget(empty)
            host_layout.addWidget(hint)
            host_layout.addStretch()
        else:
            # Build cards in chunks so the dialog paints immediately (portable open lag).
            # Do NOT addStretch until the pump finishes — stretch steals height and
            # turns early cards into flat bars while batches are still pending.
            self._pending_batches = list(batches)
            self._history_host_layout = host_layout
            loading = QLabel("Loading history…")
            loading.setAlignment(Qt.AlignCenter)
            loading.setObjectName("historyLoadingLabel")
            loading.setStyleSheet(
                f"color: #8a8a8a; font-size: 13px; padding: 24px; {_FONT}"
            )
            host_layout.addWidget(loading)
            QTimer.singleShot(0, self._pump_history_batches)

        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        close_row = QHBoxLayout()
        close_row.addStretch()
        btn_close = QPushButton("Close")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setFixedWidth(100)
        btn_close.setStyleSheet(_close_btn_style())
        self._btn_close = btn_close
        btn_close.clicked.connect(self.accept)
        close_row.addWidget(btn_close)
        root.addLayout(close_row)

    def _apply_history_styles(self) -> None:
        """Layer card faces + label rules on SteempegDialog chrome."""
        self.setStyleSheet(self.styleSheet() + _DIALOG_STYLE + _surface_styles())

    def _refresh_theme_surfaces(self) -> None:
        """Re-tint cards and action buttons from active tokens."""
        self._apply_history_styles()
        host = getattr(self, "_history_scroll_host", None)
        if host is not None:
            host.setStyleSheet(f"background-color: {self._bg_color};")
        scroll = getattr(self, "_history_scroll", None)
        if scroll is not None:
            from steempeg.ui.library.library_styles import LIBRARY_SCROLLBAR_VERTICAL

            scroll.setStyleSheet(
                tok.dialog_scroll_stylesheet(self._bg_color) + LIBRARY_SCROLLBAR_VERTICAL
            )
        btn_clear = getattr(self, "_btn_clear", None)
        if btn_clear is not None:
            btn_clear.setStyleSheet(_pill_btn_style())
        btn_close = getattr(self, "_btn_close", None)
        if btn_close is not None:
            btn_close.setStyleSheet(_close_btn_style())
        action_style = _action_btn_style()
        for card in self.findChildren(ExportResultCard):
            card.apply_theme()
            for btn in card.findChildren(QPushButton):
                btn.setStyleSheet(action_style)

    def apply_ui_theme_chrome(self) -> None:
        """Live-retint when Settings switches UI theme while Render History is open."""
        super().apply_ui_theme_chrome()
        self._refresh_theme_surfaces()

    def _pump_history_batches(self) -> None:
        layout = getattr(self, "_history_host_layout", None)
        pending = getattr(self, "_pending_batches", None)
        if layout is None or pending is None:
            return
        # Drop the loading label on first pump.
        if layout.count() >= 1:
            item = layout.itemAt(0)
            w = item.widget() if item is not None else None
            if w is not None and w.objectName() == "historyLoadingLabel":
                layout.takeAt(0)
                w.setParent(None)
                w.deleteLater()
        chunk = 2
        for _ in range(chunk):
            if not pending:
                break
            batch = pending.pop(0)
            layout.addWidget(self._build_batch_card(batch))
        if pending:
            QTimer.singleShot(0, self._pump_history_batches)
        else:
            layout.addStretch(1)
            self._pending_batches = None
            self._history_host_layout = None

    def _confirm_clear(self) -> None:
        if not self._batches:
            return
        if not steempeg_question(
            self,
            "Clear history",
            "Remove all saved render batches?",
        ):
            return
        self._batches.clear()
        self.done(2)

    def _build_batch_card(self, batch: RenderBatchRecord) -> QFrame:
        frame = QFrame()
        frame.setObjectName("batchFrame")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        when = _format_batch_when(batch.finished_at or batch.started_at)
        summary = _batch_summary(batch)
        head_row = QHBoxLayout()
        head_row.setSpacing(6)
        cal = QLabel("📅")
        cal.setStyleSheet(f"font-size: 12px; background: transparent; border: none; {_FONT}")
        head = ElidedLabel(f"{when}  •  {summary}")
        head.setStyleSheet(
            f"color: #c4b5e8; font-size: 12px; font-weight: bold; {_FONT}"
        )
        head_row.addWidget(cal, 0, Qt.AlignmentFlag.AlignVCenter)
        head_row.addWidget(head, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(head_row)

        for job_data in batch.jobs:
            layout.addWidget(self._build_job_row(job_data))

        return frame

    def _build_job_row(self, job_data: dict) -> QFrame:
        job, status_key = parse_history_job(job_data)
        if job is None:
            frame = QFrame()
            frame.setObjectName("jobFrame")
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.addWidget(QLabel("Unknown job"))
            return frame

        frame = ExportResultCard(
            job, cache_dir=self._cache_dir,
            status_text="Skipped" if status_key == "cancelled" else None,
        )
        out_path = frame.output_path
        actions = []
        if frame.file_exists and job.status == JobStatus.COMPLETED:
            actions = [
                ("📂  Open folder", lambda: reveal_in_file_manager(out_path)),
                ("▶️  Open file", lambda: self.open_output_requested.emit(out_path)),
                ("🎬  Rendered videos", lambda: self._request_open_in_rendered(out_path)),
            ]
        elif job.status in (JobStatus.COMPLETED, JobStatus.ERROR):
            actions.append(("Details", lambda: self._show_job_details(job_data)))
            clip_path = (job.clip_path or "").strip()
            if clip_path and os.path.isdir(clip_path):
                actions.append(("Source clip", lambda: self._request_open_source_clip(clip_path)))

        if actions:
            buttons = FlowLayout()
            style = _action_btn_style()
            for text, action in actions:
                button = QPushButton(text)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setStyleSheet(style)
                button.clicked.connect(action)
                buttons.addWidget(button)
            frame.body.addLayout(buttons)

        return frame

    def _show_job_details(self, job_data: dict) -> None:
        from steempeg.ui.render_history_detail_dialog import RenderHistoryDetailDialog

        dlg = RenderHistoryDetailDialog(job_data, parent=self)
        dlg.open_source_clip_requested.connect(self._request_open_source_clip)
        dlg.open_in_rendered_requested.connect(self._request_open_in_rendered)
        dlg.open_folder_requested.connect(lambda p: reveal_in_file_manager(p))
        dlg.exec()

    def _request_open_in_rendered(self, path: str) -> None:
        # Keep history open — same as the completed-queue plaque when jumping
        # to Rendered videos (Emily: only Source clip / leave should dismiss).
        self.open_in_rendered_requested.emit(path)

    def _request_open_source_clip(self, path: str) -> None:
        self.open_source_clip_requested.emit(path)
        self.accept()
