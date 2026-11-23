"""Temporary graphical preview of the Settings pane percentages.

The existing Settings fields own fitting and integer rounding. Done retains
live geometry as a cancellable Settings preview; Apply commits the form.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                              QLabel, QPushButton, QSplitter, QVBoxLayout)

from steempeg.ui import design_tokens as tok
from steempeg.ui import ui_theme as ut
from steempeg.ui import portable_splitter_reveal as shell
from steempeg.ui.pro_appearance import accent_qcolor, set_accent_stylesheet, visible_accent


def _resize_button_style(*, pad: str = "4px 12px") -> str:
    return ut.dash_secondary_button_stylesheet(radius=16, pad=pad) + """
        QPushButton:focus:enabled { border-color: #b29ae7; }
    """


def capture_geometry(app):
    found = shell._shell_widgets(app)
    if found is None:
        raise RuntimeError("The desktop panel layout is unavailable")
    return {
        "splitters": [(splitter, splitter.sizes(), splitter.handleWidth(), splitter.styleSheet(),
                       [(i, splitter.handle(i).isHidden(), splitter.handle(i).isEnabled(),
                         splitter.handle(i).styleSheet()) for i in range(1, splitter.count())])
                      for splitter in found[:2]],
        "attrs": {key: (hasattr(app, key), getattr(app, key, None)) for key in
                  ("_shell_pane_ratio", "_shell_pane_refitting", "_player_column_kissed", "_shell_pane_user_drag")},
    }


def restore_geometry(app, snapshot):
    """Restore the Settings transaction's geometry without retaining an editor."""
    for splitter, sizes, handle_width, style, handles in snapshot["splitters"]:
        blocked = splitter.blockSignals(True)
        try:
            splitter.setStyleSheet(style)
            splitter.setHandleWidth(handle_width)
            for index, hidden, enabled, handle_style in handles:
                handle = splitter.handle(index)
                if handle is not None:
                    handle.setStyleSheet(handle_style)
                    handle.setEnabled(enabled)
                    handle.setVisible(not hidden)
            splitter.setSizes(sizes)
        finally:
            splitter.blockSignals(blocked)
    shell._cancel_shell_pane_snap(app)
    for key, (existed, value) in snapshot["attrs"].items():
        if existed:
            setattr(app, key, value)
        elif hasattr(app, key):
            delattr(app, key)
    if "hover" in snapshot:
        width, suspended, revealed = snapshot["hover"]
        ctrl = app._queue_hover
        shell._apply_hover_overlay_width(app, width)
        ctrl.set_suspended(suspended)
        if revealed and not suspended:
            ctrl.reveal(animated=False)


def pencil_icon() -> QIcon:
    """Small code-native pencil, with no platform-dependent emoji glyph."""
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#d3c2fc"), 2, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.drawPolygon([QPoint(5, 15), QPoint(15, 5), QPoint(19, 9), QPoint(9, 19), QPoint(4, 20)])
    painter.drawLine(13, 7, 17, 11)
    painter.end()
    return QIcon(pixmap)


class _BoundaryHandle(QPushButton):
    def __init__(self, editor, key):
        super().__init__(editor)
        self.editor, self.key = editor, key
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoDefault(False)
        set_accent_stylesheet(self, _resize_button_style())
        self.setIcon(editor.drag_icon)
        self.setIconSize(QSize(16, 16))
        self.setToolTip("Drag to resize. Left / Right: 1%; Shift: 5%.")

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.editor.begin_drag(self.key, event.globalPosition().toPoint())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.editor.move_drag(event.globalPosition().toPoint())
            event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.editor.end_drag(event.globalPosition().toPoint())
            event.accept()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            amount = 5 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            # Right grows left-side panes and shrinks right-side panes.
            grows_right = (self.key == "queue") == self.editor.queue_left
            direction = 1 if event.key() == Qt.Key.Key_Right else -1
            self.editor.step(self.key, direction * amount * (1 if grows_right else -1))
            event.accept()
        else:
            super().keyPressEvent(event)


class PaneLayoutEditor(QDialog):
    def __init__(self, settings):
        self.settings = settings
        self.app = settings._app
        self.host = self.app.ui
        super().__init__(settings, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Panel layout")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMouseTracking(True)
        self.hover = settings._pane_queue_is_hover()
        self.queue_left = bool(getattr(self.app, "_queue_on_left", lambda: False)())
        self.before_values = settings._shell_pane_percent_values()
        self.values = self.before_values
        self._snapshot = None
        self._drag = None
        self._pending_pointer = None
        self._finished = False
        self._hover_ctrl = getattr(self.app, "_queue_hover", None) if self.hover else None
        self._queue_preview = QFrame(self)
        self._queue_preview.setObjectName("paneQueuePreview")
        self._queue_preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._queue_preview.setStyleSheet("QFrame#paneQueuePreview {background: transparent; border: none;}")
        self._queue_preview_layout = QVBoxLayout(self._queue_preview)
        self._queue_preview_layout.setContentsMargins(0, 0, 0, 0)
        opacity = QGraphicsOpacityEffect(self._queue_preview)
        opacity.setOpacity(.4)
        self._queue_preview.setGraphicsEffect(opacity)
        self._queue_preview.hide()
        self._tick = QTimer(self)
        self._tick.setSingleShot(True)
        self._tick.setInterval(32)
        self._tick.timeout.connect(self._flush_drag)
        pixmap = QPixmap(32, 32)
        pixmap.setDevicePixelRatio(2)
        pixmap.fill(Qt.GlobalColor.transparent)
        with QPainter(pixmap) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor("#eeeeee"), 1.4, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawLine(2, 8, 14, 8)
            painter.drawPolyline([QPoint(5, 5), QPoint(2, 8), QPoint(5, 11)])
            painter.drawPolyline([QPoint(11, 5), QPoint(14, 8), QPoint(11, 11)])
        self.drag_icon = QIcon(pixmap)
        self.handles = {key: _BoundaryHandle(self, key) for key in ("clips", "queue")}
        self.bar = QFrame(self)
        self.bar.setStyleSheet(ut.footer_pill_stylesheet())
        row = QHBoxLayout(self.bar)
        row.setContentsMargins(14, 8, 8, 8)
        row.setSpacing(8)
        title = QLabel("Panel layout", self.bar)
        title.setFont(tok.ui_qfont(pixel_size=14, weight=QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff; background: transparent; border: none; padding-right: 6px;")
        row.addWidget(title)
        self.cancel_button = QPushButton("Cancel", self.bar)
        from steempeg.ui.widgets.apply_button import ApplyButton

        self.apply_button = ApplyButton(self.bar)
        self.done_button = QPushButton("Done", self.bar)
        for button in (self.cancel_button, self.apply_button, self.done_button):
            button.setAutoDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(32)
            button.setMinimumWidth(76)
            row.addWidget(button)
        secondary = _resize_button_style()
        set_accent_stylesheet(self.cancel_button, secondary)
        set_accent_stylesheet(self.apply_button, _resize_button_style(pad="4px 5px"))
        set_accent_stylesheet(self.done_button, secondary + """
            QPushButton { background-color: rgba(178, 154, 231, 58); border-color: #8e7cc3; }
            QPushButton:hover { background-color: rgba(178, 154, 231, 72); border-color: #b29ae7; }
            QPushButton:pressed { background-color: rgba(178, 154, 231, 37); }
        """)
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self.apply_settings)
        self.apply_button.setToolTip("Save current Settings and continue adjusting panel widths")
        self.done_button.clicked.connect(self.accept)
        self.host.installEventFilter(self)

    def start_preview(self):
        """Capture the layout once, before changing any geometry or hover state."""
        self._snapshot = capture_geometry(self.app)
        if self._hover_ctrl is not None:
            ctrl = self._hover_ctrl
            self._snapshot["hover"] = (ctrl.overlay_width(), ctrl._suspended, ctrl.is_revealed())
            ctrl.set_suspended(True)
            panel = getattr(self.app, "render_queue_panel", None)
            if panel is not None:
                parent = panel.parentWidget()
                layout = parent.layout() if parent is not None else None
                index = layout.indexOf(panel) if layout is not None else -1
                alignment = layout.itemAt(index).alignment() if index >= 0 else Qt.AlignmentFlag(0)
                stretch = layout.stretch(index) if index >= 0 and hasattr(layout, "stretch") else 0
                self._snapshot["queue_parent"] = (
                    panel, parent, layout, parent.indexOf(panel) if isinstance(parent, QSplitter) else index,
                    alignment, stretch, panel.isHidden(), panel.geometry(), panel.sizePolicy(),
                )
                # Use the actual queue widgets: resizing must run their layouts,
                # not scale a cached picture of their text and thumbnails.
                self._queue_preview_layout.addWidget(panel)
                panel.show()
                self._queue_preview.show()
        shell._set_side_handles_visible(self.app, False)
        self._follow_host()
        self._preview()

    def _follow_host(self):
        self.setGeometry(QRect(self.host.mapToGlobal(QPoint(0, 0)), self.host.size()))
        self._place_controls()

    def _shell_rect(self):
        splitter = self.host.main_splitter
        return QRect(splitter.mapTo(self.host, QPoint(0, 0)), splitter.size())

    def _queue_rect(self):
        if self._hover_ctrl is not None:
            rect = self._hover_span()
            width = self._hover_ctrl.overlay_width()
            return QRect(rect.left() if self.queue_left else rect.right() - width + 1,
                         rect.top(), width, rect.height()).intersected(self.rect())
        panel = self.app.render_queue_panel
        return QRect(panel.mapTo(self.host, QPoint(0, 0)), panel.size())

    def _hover_span(self):
        rect = self._hover_ctrl._span_rect()
        owner = self._hover_ctrl._host or self.host
        rect.moveTopLeft(owner.mapTo(self.host, rect.topLeft()))
        return rect

    def boundaries(self):
        rect = self._shell_rect()
        widths = shell.shell_pane_widths(self.app)
        clips_x = rect.right() - widths[0] + 1 if self.queue_left else rect.left() + widths[0]
        queue = self._queue_rect()
        queue_x = queue.right() + 1 if self.queue_left else queue.left()
        return {"clips": clips_x, "queue": queue_x}

    def _place_controls(self):
        if self._snapshot is None:
            return
        bar_size = self.bar.sizeHint()
        self.bar.setGeometry((self.width() - bar_size.width()) // 2,
                             self.height() - bar_size.height() - 12,
                             bar_size.width(), bar_size.height())
        dirty = getattr(self.settings, "_form_has_unsaved_changes", None)
        self.apply_button.setEnabled(bool(dirty and dirty()))
        positions = self.boundaries()
        if self.hover and "queue_parent" in self._snapshot:
            self._queue_preview.setGeometry(self._queue_rect())
            self._queue_preview_layout.activate()
        clips, player, queue = self.values
        queue_name = "Hover queue" if self.hover else "Queue"
        self.handles["clips"].setText(f"Clips {clips}%  ·  Player {player}%")
        self.handles["clips"].setAccessibleName(f"Clips {clips} percent, Player {player} percent")
        self.handles["queue"].setText(f"{queue_name} {queue}%")
        self.handles["queue"].setAccessibleName(f"{queue_name} width {queue} percent")
        top = self._shell_rect().top() + 4
        for key, handle in self.handles.items():
            width = handle.sizeHint().width()
            handle.setGeometry(max(8, min(self.width() - width - 8, positions[key] - width // 2)),
                               top, width, 32)
        clips_rect = self.handles["clips"].geometry()
        queue_handle = self.handles["queue"]
        # Stagger the controls only when the boundary labels would overlap.
        if clips_rect.adjusted(-8, 0, 8, 0).intersects(queue_handle.geometry()):
            queue_handle.move(queue_handle.x(), clips_rect.bottom() + 7)
        self.update()

    def _preview(self):
        self.values = self.settings._shell_pane_percent_values()
        shell._apply_percents_keeping_drag(self.app, self.values)
        self._place_controls()

    def begin_drag(self, key, global_pos):
        self._drag = (key, self.mapFromGlobal(global_pos).x() - self.boundaries()[key])
        self.update()

    def move_drag(self, global_pos):
        if self._drag is not None:
            self._pending_pointer = global_pos
            if not self._tick.isActive():
                self._tick.start()

    def end_drag(self, global_pos):
        if self._drag is not None:
            self._pending_pointer = global_pos
            self._tick.stop()
            self._flush_drag()
            self._drag = None
            self.update()

    def _flush_drag(self):
        if self._drag is None or self._pending_pointer is None:
            return
        key, offset = self._drag
        x = self.mapFromGlobal(self._pending_pointer).x() - offset
        rect = self._shell_rect()
        if key == "clips":
            width = rect.right() + 1 - x if self.queue_left else x - rect.left()
            base = rect.width()
        elif self.hover:
            span = self._hover_span()
            edge = span.left()
            width = x - edge if self.queue_left else edge + span.width() - x
            base = self.host.width()
        else:
            width = x - rect.left() if self.queue_left else rect.right() + 1 - x
            base = rect.width()
        self.set_percent(key, round(100 * width / max(1, base)))
        self._pending_pointer = None

    def set_percent(self, key, value):
        spin = self.settings._pane_spins[key]
        spin.setValue(int(value))
        self.settings._refit_pane_percent_spins(key)
        self._preview()

    def step(self, key, amount):
        self.set_percent(key, self.settings._pane_spins[key].value() + amount)

    def _boundary_at(self, pos):
        candidates = []
        for key, x in self.boundaries().items():
            if abs(pos.x() - x) <= 9:
                candidates.append((abs(pos.x() - x), key))
        if len(candidates) == 2 and candidates[0][0] == candidates[1][0]:
            return "clips" if pos.y() < self.height() / 2 else "queue"
        return min(candidates)[1] if candidates else None

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            key = self._boundary_at(event.position().toPoint())
            if key is not None:
                self.begin_drag(key, event.globalPosition().toPoint())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag is not None:
            self.move_drag(event.globalPosition().toPoint())
        else:
            self.setCursor(Qt.CursorShape.SizeHorCursor if self._boundary_at(event.position().toPoint())
                           else Qt.CursorShape.ArrowCursor)
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._drag is not None:
            self.end_drag(event.globalPosition().toPoint())
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def paintEvent(self, event):  # noqa: N802
        if self._snapshot is None:
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 42))
        accent = accent_qcolor(QColor("#b29ae7"))
        surface = QColor(ut.active_palette().bg_shell)
        guide_accent = visible_accent(accent, surface, minimum=3.0)
        if self.hover:
            rect = self._queue_rect()
            tint = QColor(accent)
            tint.setAlpha(52)
            painter.fillRect(rect, tint)
            edge = QColor(guide_accent)
            edge.setAlpha(140)
            painter.setPen(QPen(edge, 1))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
        span = self._shell_rect()
        for key, x in self.boundaries().items():
            is_hover_queue = key == "queue" and self.hover
            active = self._drag is not None and self._drag[0] == key
            color = guide_accent if is_hover_queue or active else QColor("#eeeeee")
            style = Qt.PenStyle.DashLine if is_hover_queue else Qt.PenStyle.SolidLine
            painter.setPen(QPen(QColor(0, 0, 0, 155), 3))
            painter.drawLine(x, span.top(), x, span.bottom())
            painter.setPen(QPen(color, 2 if active else 1, style))
            painter.drawLine(x, span.top(), x, span.bottom())

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.host and self._snapshot is not None and not self._finished:
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
                QTimer.singleShot(0, self._resize_preview)
            elif event.type() in (QEvent.Type.Hide, QEvent.Type.Close):
                self.reject()
        return super().eventFilter(obj, event)

    def _resize_preview(self):
        if not self._finished and self._snapshot is not None:
            self._follow_host()
            self.settings._refit_pane_percent_spins()
            self._preview()

    def apply_settings(self):
        if self.apply_button._busy:
            return
        self._tick.stop()
        self._flush_drag()
        self.apply_button.set_busy(True)
        self.apply_button.setEnabled(False)
        try:
            self.settings._apply()
        finally:
            self.apply_button.set_busy(False)
            self._place_controls()
        if self.settings._form_has_unsaved_changes():
            return  # A failed write keeps the previous Cancel baseline.
        snapshot = capture_geometry(self.app)
        if "hover" in self._snapshot:
            _width, suspended, revealed = self._snapshot["hover"]
            snapshot["hover"] = (self._hover_ctrl.overlay_width(), suspended, revealed)
        if "queue_parent" in self._snapshot:
            snapshot["queue_parent"] = self._snapshot["queue_parent"]
        self._snapshot = snapshot
        self.before_values = self.settings._shell_pane_percent_values()
        self._preview()

    def done(self, result):
        # Finish reparenting and rollback beneath the still-visible editor.
        # This prevents native windows painting each intermediate restore step.
        updating = self.host.updatesEnabled()
        self.host.setUpdatesEnabled(False)
        try:
            self._restore(result)
            super().done(result)
        finally:
            self.host.setUpdatesEnabled(updating)

    def _restore(self, result):
        if self._finished:
            return
        self._finished = True
        self._tick.stop()
        self.host.removeEventFilter(self)
        if result != QDialog.DialogCode.Accepted:
            self.settings._pane_percent_lock = True
            try:
                # Restore ranges before values: dragging may have narrowed them.
                for spin, value in zip(self.settings._pane_spins.values(), self.before_values):
                    spin.setRange(0, 100)
                    spin.setValue(value)
            finally:
                self.settings._pane_percent_lock = False
            self.settings._refit_pane_percent_spins()
        if self._snapshot is None:
            return
        accepted = result == QDialog.DialogCode.Accepted
        if accepted and getattr(self.settings, "_pane_layout_preview_snapshot", None) is None:
            self.settings._pane_layout_preview_snapshot = {
                key: value for key, value in self._snapshot.items() if key != "queue_parent"
            }
        if "queue_parent" in self._snapshot:
            panel, parent, layout, index, alignment, stretch, hidden, geometry, policy = self._snapshot["queue_parent"]
            self._queue_preview.hide()
            self._queue_preview_layout.removeWidget(panel)
            panel.setParent(parent)
            if isinstance(parent, QSplitter):
                parent.insertWidget(index, panel)
            elif layout is not None and index >= 0:
                layout.insertWidget(index, panel, stretch, alignment)
            else:
                panel.setGeometry(geometry)
            panel.setSizePolicy(policy)
            panel.setVisible(not hidden)
        if not accepted:
            restore_geometry(self.app, self._snapshot)
        elif "hover" in self._snapshot:
            _width, suspended, revealed = self._snapshot["hover"]
            desired_width = self._hover_ctrl.overlay_width()
            self._hover_ctrl.set_suspended(suspended)
            if revealed and not suspended:
                self._hover_ctrl.reveal(animated=False)
            shell._apply_hover_overlay_width(self.app, desired_width)


def edit_pane_layout(settings):
    """Return to the same Settings transaction; never save during a drag."""
    pending_sides = getattr(settings, "_shell_sides_preview_timer", None)
    if pending_sides is not None and pending_sides.isActive():
        pending_sides.stop()
        settings._apply_shell_sides_preview()
    settings._refit_pane_percent_spins()
    editor = PaneLayoutEditor(settings)
    opacity = settings.windowOpacity()
    try:
        # Hiding a QDialog inside exec() ends its outer modal loop. Keep it
        # mapped but invisible until its owned editor has actually finished.
        settings.setWindowOpacity(0.0)
        editor.start_preview()
        editor.exec()
    finally:
        editor._restore(editor.result())
        editor.hide()
        editor.setWindowModality(Qt.WindowModality.NonModal)
        editor.deleteLater()
        settings.setWindowOpacity(opacity)
        settings.raise_()
        settings.activateWindow()
