"""Live drag-reorder for Render Queue cards.

While a queued card is dragged, the other cards slide to open a gap where it
would land, and the dragged card waits there as a dim ghost. Drop commits the
order the user sees; cancel slides everything back.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QTimer,
    Qt,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QWidget

from steempeg.render.queue import JobStatus

_SLIDE_MS = 170
_SETTLE_MS = 200
_GHOST_OPACITY = 0.35
_GHOST_FADE_OUT_MS = 140
_GHOST_FADE_IN_MS = 220
_PRESS_MS = 90
_RELEASE_MS = 180
_PRESS_INSET_X = 3
_PRESS_INSET_Y = 2
_LIFT_SCALE = 0.85
_LIFT_MAX_W = 420


def render_lifted_card_pixmap(card: QWidget) -> tuple[QPixmap, float]:
    """Whole card painted as a floating rounded plate, scaled down a little; returns the pixmap and its scale."""
    w = max(1, card.width())
    h = max(1, card.height())
    scale = min(_LIFT_SCALE, _LIFT_MAX_W / w)
    out_w = max(1, int(round(w * scale)))
    out_h = max(1, int(round(h * scale)))
    dpr = card.devicePixelRatioF()

    pix = QPixmap(int(out_w * dpr), int(out_h * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    radius = 12 * scale + 2
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, out_w, out_h), radius, radius)
    painter.fillPath(path, QColor("#262229"))
    painter.save()
    painter.setClipPath(path)
    painter.setOpacity(0.97)
    painter.scale(scale, scale)
    card.render(painter, QPoint(0, 0))
    painter.restore()
    painter.setPen(QPen(QColor("#b29ae7"), 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(1, 1, out_w - 2, out_h - 2), radius - 1, radius - 1)
    painter.end()
    return pix, scale


def press_card_visual(card: QWidget) -> None:
    """Sinks the card a few pixels while the mouse button is held."""
    if getattr(card, "_press_base", None) is None:
        card._press_base = QRect(card.geometry())
    base = card._press_base
    _animate_card_geometry(
        card,
        base.adjusted(_PRESS_INSET_X, _PRESS_INSET_Y, -_PRESS_INSET_X, -_PRESS_INSET_Y),
        _PRESS_MS,
        QEasingCurve.Type.OutCubic,
    )


def release_card_visual(card: QWidget) -> None:
    """Pops the card back to full size after a press."""
    base = getattr(card, "_press_base", None)
    if base is None:
        return
    card._press_base = None
    _animate_card_geometry(card, base, _RELEASE_MS, QEasingCurve.Type.OutBack)


def settle_card_visual(card: QWidget) -> None:
    """Snaps a pressed card back to full size at once (before a drag measures it)."""
    base = getattr(card, "_press_base", None)
    anim = getattr(card, "_press_anim", None)
    if anim is not None:
        anim.stop()
    if base is None:
        return
    card._press_base = None
    card.setGeometry(base)


def _animate_card_geometry(card: QWidget, end: QRect, duration_ms: int, curve) -> None:
    """Runs one geometry animation on ``card``, replacing any running one."""
    anim = getattr(card, "_press_anim", None)
    if anim is not None:
        anim.stop()
    anim = QPropertyAnimation(card, b"geometry", card)
    anim.setDuration(duration_ms)
    anim.setEasingCurve(curve)
    anim.setStartValue(card.geometry())
    anim.setEndValue(end)
    card._press_anim = anim
    anim.start()


class QueueDragAnimator(QObject):
    """Slides Render Queue cards out of the way during a drag and reports the final order."""

    def __init__(
        self,
        get_cards: Callable[[], list],
        get_mode: Callable[[], str],
        list_spacing: int,
        mime_type: str,
        commit: Callable[[str, list[str]], None],
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._get_cards = get_cards
        self._get_mode = get_mode
        self._list_spacing = int(list_spacing)
        self._mime_type = mime_type
        self._commit = commit
        self._source_id: str | None = None
        self._cards: list[QWidget] = []
        self._slots: list[QRect] = []
        self._order: list[str] = []
        self._anims: dict[int, QPropertyAnimation] = {}
        self._dropped = False

    def is_active(self) -> bool:
        """True while a card drag is in progress."""
        return self._source_id is not None

    def begin(self, source_id: str) -> None:
        """Remembers where every card sits and turns the dragged card into a ghost."""
        cards = [c for c in self._get_cards() if _card_alive(c)]
        ids = [c._job_id for c in cards]
        if source_id not in ids:
            return
        self._source_id = source_id
        self._cards = cards
        self._slots = [QRect(c.geometry()) for c in cards]
        self._order = ids
        self._dropped = False
        source = cards[ids.index(source_id)]
        effect = QGraphicsOpacityEffect(source)
        effect.setOpacity(1.0)
        source.setGraphicsEffect(effect)
        self._fade_effect(effect, _GHOST_OPACITY, _GHOST_FADE_OUT_MS)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def end(self) -> None:
        """Called when the drag loop returns: slides back on cancel, clears the ghost either way."""
        if self._source_id is None:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        if not self._dropped:
            self._order = [c._job_id for c in self._cards]
            self._animate_to_order(_SETTLE_MS)
        for card in self._cards:
            if _card_alive(card) and card._job_id == self._source_id:
                self._restore_ghost(card)
        self._source_id = None
        if not self._dropped:
            QTimer.singleShot(_SETTLE_MS + 30, self._relayout_parents)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 — Qt override
        """Takes over drag enter / move / drop for queue cards while a drag is active."""
        etype = event.type()
        if etype not in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            return False
        if self._source_id is None or not isinstance(watched, QWidget):
            return False
        mime = event.mimeData()
        if mime is None or not mime.hasFormat(self._mime_type):
            return False
        if not self._owns_widget(watched):
            return False

        global_pos = watched.mapToGlobal(event.position().toPoint())
        if etype == QEvent.Type.Drop:
            self._track(global_pos)
            self._dropped = True
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            source_id = self._source_id
            order = list(self._order)
            QTimer.singleShot(0, lambda: self._commit(source_id, order))
            return True

        self._track(global_pos)
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        return True

    def _fade_effect(self, effect: QGraphicsOpacityEffect, end: float, duration_ms: int):
        """Animates the ghost opacity and returns the running animation."""
        anim = QPropertyAnimation(effect, b"opacity", effect)
        anim.setDuration(duration_ms)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(effect.opacity())
        anim.setEndValue(end)
        anim.start()
        return anim

    def _restore_ghost(self, card: QWidget) -> None:
        """Fades the dragged card back to full opacity, then drops the effect."""
        effect = card.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            return
        anim = self._fade_effect(effect, 1.0, _GHOST_FADE_IN_MS)

        def _clear() -> None:
            if _card_alive(card) and card.graphicsEffect() is effect:
                card.setGraphicsEffect(None)

        anim.finished.connect(_clear)

    def _owns_widget(self, widget: QWidget) -> bool:
        """True when ``widget`` is one of the cards' parents or sits inside one."""
        parents = {id(c.parentWidget()) for c in self._cards if _card_alive(c)}
        node = widget
        while node is not None:
            if id(node) in parents:
                return True
            node = node.parentWidget()
        for card in self._cards:
            parent = card.parentWidget() if _card_alive(card) else None
            if parent is None:
                continue
            node = parent
            while node is not None:
                if node is widget:
                    return True
                node = node.parentWidget()
        return False

    def _track(self, global_pos: QPoint) -> None:
        """Works out the slot under the cursor and slides cards to open a gap there."""
        if not self._cards:
            return
        parent = self._cards[0].parentWidget()
        if parent is None:
            return
        local = parent.mapFromGlobal(global_pos)
        target = self._slot_index_at(local)
        others = [c._job_id for c in self._cards if c._job_id != self._source_id]
        target = max(0, min(target, len(others)))
        order = others[:target] + [self._source_id] + others[target:]
        if order == self._order or not self._lands_next_to_queued(order):
            return
        self._order = order
        self._animate_to_order(_SLIDE_MS)

    def _lands_next_to_queued(self, order: list[str]) -> bool:
        """True when the dragged card would sit next to another queued job (or back at home)."""
        if order == [c._job_id for c in self._cards]:
            return True
        status = {c._job_id: c._job.status for c in self._cards if _card_alive(c)}
        index = order.index(self._source_id)
        for neighbor in (index - 1, index + 1):
            if 0 <= neighbor < len(order) and status.get(order[neighbor]) == JobStatus.QUEUED:
                return True
        return False

    def _slot_index_at(self, pos: QPoint) -> int:
        """Index of the original slot closest to ``pos``."""
        best = 0
        best_dist = None
        for index, rect in enumerate(self._slots):
            if rect.contains(pos):
                return index
            center = rect.center()
            if self._get_mode() == "grid":
                dist = (center.x() - pos.x()) ** 2 + (center.y() - pos.y()) ** 2
            else:
                dist = abs(center.y() - pos.y())
            if best_dist is None or dist < best_dist:
                best, best_dist = index, dist
        return best

    def _target_positions(self) -> dict[str, QPoint]:
        """Top-left point for every card in the current order."""
        by_id = {c._job_id: c for c in self._cards}
        out: dict[str, QPoint] = {}
        if self._get_mode() == "grid":
            for index, job_id in enumerate(self._order):
                out[job_id] = self._slots[index].topLeft()
            return out
        x = self._slots[0].x()
        y = self._slots[0].y()
        for job_id in self._order:
            out[job_id] = QPoint(x, y)
            card = by_id.get(job_id)
            height = card.height() if card is not None else 0
            y += height + self._list_spacing
        return out

    def _animate_to_order(self, duration_ms: int) -> None:
        """Slides every card toward its spot in ``self._order``."""
        targets = self._target_positions()
        for card in self._cards:
            if not _card_alive(card):
                continue
            end = targets.get(card._job_id)
            if end is None:
                continue
            anim = self._anims.get(id(card))
            if anim is not None:
                anim.stop()
            if card.pos() == end:
                continue
            anim = QPropertyAnimation(card, b"pos", self)
            anim.setDuration(duration_ms)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.setStartValue(card.pos())
            anim.setEndValue(end)
            anim.start()
            self._anims[id(card)] = anim

    def _relayout_parents(self) -> None:
        """Lets the layouts take the cards back after a cancelled drag."""
        seen = set()
        for card in self._cards:
            parent = card.parentWidget() if _card_alive(card) else None
            if parent is None or id(parent) in seen:
                continue
            seen.add(id(parent))
            layout = parent.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()
        self._cards = []
        self._slots = []
        self._anims.clear()


def build_reorder_request(
    source_id: str, order: list[str], jobs: list
) -> tuple[str, str] | None:
    """Turns a visual order into ``("before", target)`` or ``("after", anchor)`` for the queue."""
    if source_id not in order:
        return None
    status = {j.id: j.status for j in jobs}
    index = order.index(source_id)
    current = [j.id for j in jobs]
    if current.index(source_id) == index and len(current) == len(order):
        return None
    if index + 1 < len(order) and status.get(order[index + 1]) == JobStatus.QUEUED:
        return ("before", order[index + 1])
    if index > 0 and status.get(order[index - 1]) == JobStatus.QUEUED:
        return ("after", order[index - 1])
    return None


def _card_alive(card) -> bool:
    """True when the Qt object behind ``card`` still exists."""
    try:
        card.objectName()
    except RuntimeError:
        return False
    return True
