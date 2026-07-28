"""Desktop shell splitter rules — Clips Manager | player column | Render Queue.

The shell is two nested splitters, not one flat three-pane splitter::

    main_splitter                <- LEFT handle
    +- left_panel                   Clips Manager
    +- right_h_splitter          <- RIGHT handle
       +- right_panel               player column
       +- render_queue_panel        Render Queue

The RIGHT handle divides the player column against the queue, so Clips Manager
is not a participant and cannot move — that side behaves correctly on its own.
The LEFT handle divides Clips against the *whole* right block, so Qt resizes
that block as one unit and reshuffles its insides: the queue changes width and
the right handle slides along with it.

There is no arrangement of minimums that makes Qt treat the outer handle as a
three-pane divider, so the left drag is driven here instead. On press the queue
width is frozen, and every mouse move is converted straight into geometry for
both splitters — Qt's own ``moveSplitter`` is skipped entirely (the move event
is swallowed). The queue then behaves exactly like Clips Manager does for the
right handle: a wall that does not move, with only the player column absorbing
the drag.

Handle states, from open to closed:

1. closed          Clips collapsed to 0, only its handle shows.
2. minimally open  Clips at ``left_panel_min_width``.
3. open            free travel; the player column absorbs the drag.
4. pre-kiss        player column held at its content floor.
5. kiss            player column collapsed; the handles meet, each keeping its
                   own width so they touch without overlapping.

States 4 and 5 use hysteresis so the collapse cannot flicker, and both are
derived from the live pointer position rather than a latched size — dragging
back out always reopens the player column at its floor.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, Qt

from steempeg.ui.layout_defaults import left_panel_min_width

# Fractions of the player column's content floor. Collapse once the drag asks
# for less than KISS_IN; reopen once it offers back at least KISS_OUT.
KISS_IN = 0.45
KISS_OUT = 0.75
# Clips snaps shut below this fraction of its own minimum (states 1 <-> 2).
CLIPS_SNAP_SHUT = 0.5
# A pane thinner than this is a leftover scrap, not an open pane.
PANE_SCRAP_WIDTH = 48
# Smallest the player column's floor may be scaled to on a cramped shell.
PLAYER_COLUMN_CRAMPED = 120
# Explicit minimum that frees the player column for the kiss. Zero is ignored:
# qSmartMinSize only lets an explicit minimum override the content-driven
# minimumSizeHint when it is greater than zero.
PLAYER_COLUMN_FREED = 1

LEFT = "left"
RIGHT = "right"


class _HandleDragWatcher(QObject):
    """Reports press / move / release on one splitter handle to the shell."""

    def __init__(self, splitter, host, side: str):
        super().__init__(splitter)
        self._host = host
        self._side = side
        self._grab_offset = 0

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.MouseMove:
            # True here keeps QSplitterHandle from running its own moveSplitter.
            return self._host._splitter_drag_moved(
                self._side, int(event.globalPosition().x()), self._grab_offset
            )
        if kind == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self._grab_offset = int(event.position().x())
                self._host._begin_splitter_drag(self._side)
        elif kind == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                self._host._end_splitter_drag(self._side)
        return False


class SplitterRulesMixin:
    """Drives the LEFT handle so it matches the RIGHT one (see module docstring)."""

    def install_splitter_rules(self) -> None:
        """Watch both horizontal handles once the nested splitters exist."""
        ui = getattr(self, "ui", None)
        self._splitter_drag_side = None
        self._splitter_dragging = False
        self._splitter_handle_watchers = []
        self._frozen_queue_width = 0
        self._watch_splitter_handle(getattr(ui, "main_splitter", None), LEFT)
        self._watch_splitter_handle(getattr(self, "right_h_splitter", None), RIGHT)

    def _watch_splitter_handle(self, splitter, side: str) -> None:
        if splitter is None or splitter.count() < 2:
            return
        handle = splitter.handle(1)
        if handle is None or handle.property("steempeg_drag_side"):
            return
        handle.setProperty("steempeg_drag_side", side)
        watcher = _HandleDragWatcher(splitter, self, side)
        handle.installEventFilter(watcher)
        self._splitter_handle_watchers.append(watcher)

    # --- drag lifecycle ---------------------------------------------------

    def _begin_splitter_drag(self, side: str) -> None:
        self._splitter_drag_side = side
        self._splitter_dragging = True
        if side != LEFT or not self._splitter_rules_active():
            return
        sizes = self.right_h_splitter.sizes()
        # Freeze the wall now. Reading it live lets the queue balloon while the
        # player column is collapsed, which drags the right handle along.
        self._frozen_queue_width = int(sizes[1]) if len(sizes) >= 2 else 0

    def _end_splitter_drag(self, side: str) -> None:
        if getattr(self, "_splitter_drag_side", None) == side:
            self._splitter_drag_side = None
        self._splitter_dragging = False
        self._frozen_queue_width = 0

    def _splitter_drag_moved(self, side: str, global_x: int, grab_offset: int) -> bool:
        """Place both splitters for this pointer position. True = event consumed."""
        if side != LEFT or getattr(self, "_splitter_drag_side", None) != LEFT:
            return False
        if not self._splitter_rules_active():
            return False
        queue_w = int(getattr(self, "_frozen_queue_width", 0))
        if queue_w <= PANE_SCRAP_WIDTH:
            # Queue closed — no wall to work against, let Qt drag normally.
            return False

        main = self.ui.main_splitter
        rhs = self.right_h_splitter
        main_total = sum(main.sizes()) or main.width()
        # Everything the drag may divide: Clips plus the player column.
        avail = main_total - queue_w - rhs.handleWidth()
        if avail <= 0:
            return False

        requested_left = main.mapFromGlobal(QPoint(int(global_x), 0)).x() - int(grab_offset)
        left = max(0, min(int(requested_left), avail))
        floor = self._effective_player_floor(avail)

        left = self._snap_clips_width(left, avail, floor)
        player_w = self._resolve_player_width(avail - left, floor)
        self._apply_left_drag_geometry(main_total, avail - player_w, player_w, queue_w)
        return True

    # --- geometry ---------------------------------------------------------

    def _splitter_rules_active(self) -> bool:
        if getattr(self, "_portable_shell", False):
            return False
        if getattr(self, "is_theater", False) or getattr(self, "is_fullscreen", False):
            return False
        ui = getattr(self, "ui", None)
        if ui is None or getattr(ui, "main_splitter", None) is None:
            return False
        return (
            getattr(self, "right_h_splitter", None) is not None
            and getattr(self, "render_queue_panel", None) is not None
            and getattr(ui, "right_panel", None) is not None
        )

    def _player_column_floor(self) -> int:
        """Narrowest the player column renders at — its own content minimum.

        Read from the size hint, which the explicit minimum never changes, so
        it stays honest while the column is collapsed.
        """
        return max(int(self.ui.right_panel.minimumSizeHint().width()), 1)

    def _effective_player_floor(self, avail: int) -> int:
        """The content floor, scaled down when the shell cannot afford it.

        Below roughly 1760px the three content floors do not fit side by side.
        Holding the full floor there puts the reopen threshold out of reach and
        the player column stays collapsed for good, so it is scaled to whatever
        the drag can actually hand back.
        """
        ui = self.ui
        clips_min = left_panel_min_width(int(ui.width() or 0), widget=ui)
        affordable = int(avail) - clips_min
        return min(self._player_column_floor(), max(PLAYER_COLUMN_CRAMPED, affordable))

    def _snap_clips_width(self, left: int, avail: int, floor: int) -> int:
        """States 1 and 2 — Clips is either shut or at least minimally open."""
        ui = self.ui
        clips_min = left_panel_min_width(int(ui.width() or 0), widget=ui)
        if avail < clips_min + floor:
            # Shell too narrow to honour both floors; the player column wins.
            return left
        if left >= clips_min:
            return left
        return 0 if left < clips_min * CLIPS_SNAP_SHUT else clips_min

    def _resolve_player_width(self, wanted: int, floor: int) -> int:
        """States 3 to 5 — free travel, held at the floor, or collapsed."""
        kissed = bool(getattr(self, "_player_column_kissed", False))
        if wanted < floor * KISS_IN:
            kissed = True
        elif wanted >= floor * KISS_OUT:
            kissed = False
        self._player_column_kissed = kissed
        if kissed:
            return 0
        return max(int(wanted), floor)

    def _apply_left_drag_geometry(
        self, main_total: int, left: int, player_w: int, queue_w: int
    ) -> None:
        main = self.ui.main_splitter
        rhs = self.right_h_splitter
        # Only an explicit minimum above zero can undercut the content floor.
        self.ui.right_panel.setMinimumWidth(PLAYER_COLUMN_FREED if player_w <= 0 else 0)
        block = player_w + queue_w + rhs.handleWidth()
        main.setSizes([max(int(left), 0), max(block, 1)])
        rhs.setSizes([max(int(player_w), 0), max(int(queue_w), 1)])
