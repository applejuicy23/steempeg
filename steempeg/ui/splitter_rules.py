"""Desktop shell splitter rules — side pane | player column | side pane.

The shell is two nested splitters, not one flat three-pane splitter::

    main_splitter                <- LEFT handle
    +- outer pane                   Library (default) or Render Queue
    +- right_h_splitter          <- RIGHT handle
       +- right_panel               player column
       +- inner pane                Render Queue (default) or Library

Settings → Visual → Side panels can swap Library ↔ Render Queue. The player
stays in the middle. Geometry treats the panes as outer/inner; queue open,
close, and persist follow the Render Queue widget wherever it sits.

The RIGHT handle divides the player column against the inner pane, so the
outer pane is not a participant and cannot move — that side behaves correctly
on its own.
The LEFT handle divides the outer pane against the *whole* right block, so Qt
resizes that block as one unit and reshuffles its insides: the inner pane
changes width and the right handle slides along with it.

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

A collapsed pane is pinned by a one-pixel explicit minimum (see ``PANE_FREED``),
without which the outer splitter re-inflates the block and the kiss springs
back. Qt reads that minimum as licence to regrow the pane a pixel at a time, so
Any drag that *starts* from a collapse is driven here too — including the right
handle, which otherwise used to creep. Collapsed panes pop open at their
floor in one step; they never creep.

Stage B also drives the right handle when **both panes are already open**
(open→kiss). Native Qt alone fights live content minimums (player-header title
elide soft-min + queue card sizeHints) and twitches the player column; the left
handle never had that problem because its drag was always custom.

Either handle can undo a kiss — but only out of slack its own neighbour can
actually spare, and a neighbour already down to its own floor has none. Reopening
the player column there would mean shoving that neighbour under its floor, which
is what used to make a handle sitting at the verge of closing wander off instead
of closing. So the room becomes a two-position toggle at its own midpoint: the
neighbour holds all of it with the column kissed shut, or the neighbour shuts and
the joint travels, both handles moving together with the far pane taking up the
room. A handle already against its wall has nothing to shut and stays put.
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
# Least slack a neighbour must be able to spare before the player column is
# worth reopening at all. Under this the collapse simply holds.
PLAYER_COLUMN_MIN_SLACK = 120
# Explicit minimum that frees a collapsed pane. Zero is ignored: qSmartMinSize
# only lets an explicit minimum override the content-driven minimumSizeHint
# when it is greater than zero.
PANE_FREED = 1

LEFT = "left"
RIGHT = "right"

# Which pane the right handle starts its drag with collapsed.
FROM_KISS = "from-kiss"
REOPEN_QUEUE = "reopen-queue"


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
        self._frozen_inner_width = 0
        self._frozen_player_floor = 0
        self._right_drag_mode = ""
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
        # Kill a snap armed by a prior splitterMoved — it must not fire mid-hold.
        timer = getattr(self, "_right_h_snap_timer", None)
        if timer is not None:
            timer.stop()
        try:
            from steempeg.ui.splitter_telemetry import get_splitter_telemetry, splitter_reason

            with splitter_reason(f"drag_begin:{side}"):
                get_splitter_telemetry().note(
                    "drag_begin",
                    detail=f"side={side}",
                    splitter_name="main_splitter" if side == LEFT else "right_h_splitter",
                )
        except Exception:
            pass
        if not self._splitter_rules_active():
            return
        if side == RIGHT:
            # Latched once: mid-drag a pane stops being collapsed, and the rule
            # must not change while the button is still down.
            self._right_drag_mode = self._right_drag_mode_for_state()
            # Keep kiss hysteresis honest — otherwise reopen skips the snap floor
            # and the player column freeloads, then claps.
            if self._right_drag_mode == FROM_KISS:
                self._player_column_kissed = True
            # Freeze the content floor so header elide / queue cards cannot
            # renegotiate the kiss threshold every pixel (Stage B).
            self._frozen_player_floor = self._player_column_floor()
            return
        sizes = self.right_h_splitter.sizes()
        # Freeze the inner wall now. Reading it live lets that pane balloon while
        # the player column is collapsed, which drags the right handle along.
        inner_w = int(sizes[1]) if len(sizes) >= 2 else 0
        inner_floor = self._inner_pane_floor()
        # Sub-floor remnants are shut — freezing them as a wall lets the next
        # left drag unroll the inner pane instead of popping it.
        self._frozen_inner_width = inner_w if inner_w >= inner_floor else 0
        self.sync_queue_minimum()

    def _end_splitter_drag(self, side: str) -> None:
        if getattr(self, "_splitter_drag_side", None) == side:
            self._splitter_drag_side = None
        self._splitter_dragging = False
        self._frozen_inner_width = 0
        self._frozen_player_floor = 0
        self._right_drag_mode = ""
        self._sync_kiss_flag()
        self.sync_queue_minimum()
        try:
            from steempeg.ui.splitter_telemetry import get_splitter_telemetry, splitter_reason

            with splitter_reason(f"drag_end:{side}"):
                get_splitter_telemetry().note(
                    "drag_end",
                    detail=f"side={side}",
                    splitter_name="main_splitter" if side == LEFT else "right_h_splitter",
                )
        except Exception:
            pass
        # Header soft-min / elide was paused mid-drag — settle once geometry is final.
        try:
            from steempeg.ui.player_header_layout import (
                get_header_layout,
                HEADER_LAYOUT_STEAM_LIKE,
                sync_centered_title_width,
                sync_header_center_mirror,
            )

            if get_header_layout() == HEADER_LAYOUT_STEAM_LIKE:
                sync_header_center_mirror(self)
            else:
                sync_centered_title_width(self)
        except Exception:
            pass
        # Trim/marker overlays map from Cancel / theater — wait a tick after drag.
        try:
            from steempeg.ui.player.controls.adaptive_trim_tools import (
                schedule_sync_trim_tools_placement,
            )

            schedule_sync_trim_tools_placement(self)
        except Exception:
            pass
        # Custom handle drags can shut the queue without Qt's snap timer seeing
        # a "user collapse" — latch + persist so clip select cannot reopen.
        if self._splitter_rules_active():
            if hasattr(self, "_persist_queue_state_from_geometry"):
                self._persist_queue_state_from_geometry()
            if hasattr(self, "_on_right_h_splitter_moved"):
                self._on_right_h_splitter_moved()

    def _sync_kiss_flag(self) -> None:
        """Match the hysteresis flag to the sizes the drag actually left.

        Open→kiss is custom (Stage B), but still re-read sizes so a release that
        landed on scrap / freed never leaves the flag stale.
        """
        if not self._splitter_rules_active():
            return
        sizes = self.right_h_splitter.sizes()
        self._player_column_kissed = len(sizes) >= 2 and int(sizes[0]) <= PANE_FREED

    def sync_queue_minimum(self) -> None:
        """Match pane minimums to open vs shut — Clips-style floor when open.

        Closed queue must stay at ``PANE_FREED`` or content hint reserves ~480px.
        Open queue gets an explicit layout min so Qt cannot squash past it
        (labels/buttons alone will happily crush to nothing).
        """
        if not self._splitter_rules_active():
            return
        sizes = self.right_h_splitter.sizes()
        if len(sizes) < 2:
            return
        # Below the inner floor counts as shut. Scraps between PANE_FREED and
        # floor used to latch "open" here, keep the layout min, and unroll.
        inner_shut = int(sizes[1]) < self._inner_pane_floor()
        self._free_collapsed_minimums(
            int(sizes[0]) <= PANE_FREED,
            inner_shut,
        )

    def _splitter_drag_moved(self, side: str, global_x: int, grab_offset: int) -> bool:
        """Place both splitters for this pointer position. True = event consumed."""
        if getattr(self, "_splitter_drag_side", None) != side:
            return False
        if not self._splitter_rules_active():
            return False
        if side == RIGHT:
            mode = getattr(self, "_right_drag_mode", "")
            if mode == FROM_KISS:
                return self._drag_right_from_kiss(global_x, grab_offset)
            if mode == REOPEN_QUEUE:
                return self._reopen_queue_pane(global_x, grab_offset)
            # Stage B: both panes open — drive open→kiss ourselves. Native Qt
            # fights live content mins (header elide + queue cards) and twitches
            # the player column; left→kiss never had this because it is custom.
            return self._drag_right_both_open(global_x, grab_offset)
        inner_w = int(getattr(self, "_frozen_inner_width", 0))
        main = self.ui.main_splitter
        main_total = sum(main.sizes()) or main.width()
        # Everything the drag may divide: outer pane plus the player column.
        avail = main_total - inner_w - self._right_handle_width()
        if avail <= 0:
            return False

        requested_left = main.mapFromGlobal(QPoint(int(global_x), 0)).x() - int(grab_offset)
        left = max(0, min(int(requested_left), avail))
        floor = self._effective_player_floor(avail)
        if floor <= 0:
            return self._place_left_handle_at_verge(main_total, left, avail, inner_w)

        left = self._snap_outer_width(left, avail, floor)
        player_w = self._resolve_player_width(avail - left, floor)
        self._apply_left_drag_geometry(main_total, avail - player_w, player_w, inner_w)
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

    def _queue_on_left(self) -> bool:
        """True when Render Queue is the outer (left) pane."""
        queue = getattr(self, "render_queue_panel", None)
        main = getattr(getattr(self, "ui", None), "main_splitter", None)
        if queue is None or main is None:
            return False
        try:
            return main.indexOf(queue) == 0
        except RuntimeError:
            return False

    def _queue_splitter_and_index(self):
        """Splitter that currently owns Render Queue, and that child's index."""
        queue = getattr(self, "render_queue_panel", None)
        if queue is None:
            return None, -1
        rhs = getattr(self, "right_h_splitter", None)
        main = getattr(getattr(self, "ui", None), "main_splitter", None)
        for splitter in (rhs, main):
            if splitter is None:
                continue
            try:
                idx = splitter.indexOf(queue)
            except RuntimeError:
                continue
            if idx >= 0:
                return splitter, idx
        return None, -1

    def _queue_pane_width(self) -> int:
        splitter, idx = self._queue_splitter_and_index()
        if splitter is None or idx < 0:
            return 0
        sizes = splitter.sizes()
        if idx >= len(sizes):
            return 0
        return max(0, int(sizes[idx]))

    def _queue_width_from_saved_sizes(self, main_sizes, rhs_sizes) -> int:
        """Queue width encoded in a pair of splitter snapshots."""
        if self._queue_on_left():
            if isinstance(main_sizes, (list, tuple)) and main_sizes:
                return max(0, int(main_sizes[0]))
            return 0
        if isinstance(rhs_sizes, (list, tuple)) and len(rhs_sizes) >= 2:
            return max(0, int(rhs_sizes[1]))
        return 0

    def _library_min_width(self) -> int:
        ui = getattr(self, "ui", None)
        win_w = int(ui.width() or 0) if ui is not None else 0
        return left_panel_min_width(win_w, widget=ui) if win_w else 360

    def _outer_pane_floor(self) -> int:
        if self._queue_on_left():
            return self._queue_layout_floor()
        return self._library_min_width()

    def _inner_pane_floor(self) -> int:
        if self._queue_on_left():
            return self._library_min_width()
        return self._queue_layout_floor()

    def _persist_queue_state_from_geometry(self) -> None:
        """Latch user-collapse + persist open/width from the live queue slot."""
        queue_w = self._queue_pane_width()
        jobs = getattr(self, "render_queue", None)
        has_jobs = jobs is not None and len(jobs) > 0
        floor = self._queue_layout_floor() if hasattr(self, "_queue_layout_floor") else PANE_SCRAP_WIDTH
        if queue_w < floor:
            if has_jobs:
                self._queue_user_collapsed = True
            if hasattr(self, "_persist_queue_panel_open"):
                self._persist_queue_panel_open(False)
            return
        self._queue_user_collapsed = False
        if hasattr(self, "_persist_queue_panel_open"):
            self._persist_queue_panel_open(True)
        if hasattr(self, "save_layout_setting"):
            self.save_layout_setting("queue_panel_width", int(queue_w))

    def _right_handle_width(self) -> int:
        """How much room the right handle really takes.

        handleWidth() only reports the property; the stylesheet makes the handle
        widget wider than that, and the layout goes by the widget. Using the
        property alone leaves the kiss a few pixels off and squashes the handle.
        """
        rhs = self.right_h_splitter
        handle = rhs.handle(1)
        widget_w = 0
        if handle is not None:
            widget_w = max(int(handle.width()), int(handle.sizeHint().width()))
        return max(int(rhs.handleWidth()), widget_w)

    def _player_column_floor(self) -> int:
        """Narrowest the player column renders at — its own content minimum.

        Read from the size hint, which the explicit minimum never changes, so
        it stays honest while the column is collapsed. Mid-drag prefer the
        value frozen on press so Resize/elide cannot move the kiss threshold.
        """
        frozen = int(getattr(self, "_frozen_player_floor", 0) or 0)
        if frozen > 0 and getattr(self, "_splitter_dragging", False):
            return frozen
        return max(int(self.ui.right_panel.minimumSizeHint().width()), 1)

    def _scaled_player_floor(self, room: int, neighbour_floor: int) -> int:
        """How wide the player column may reopen here. Zero means it may not.

        Below roughly 1760px the three content floors do not fit side by side, so
        the full floor is out of reach and the column reopens at whatever the
        neighbour can spare. Once that is nothing — the neighbour is down to its
        own floor — the answer is zero. Forcing a floor there is what made a
        handle sitting at the verge of closing wander off instead of closing.
        """
        affordable = int(room) - int(neighbour_floor)
        if affordable < PLAYER_COLUMN_MIN_SLACK:
            return 0
        return min(self._player_column_floor(), affordable)

    def _effective_player_floor(self, avail: int) -> int:
        """Player floor for a left drag, where the outer pane is the neighbour."""
        return self._scaled_player_floor(avail, self._outer_pane_floor())

    def _snap_outer_width(self, left: int, avail: int, floor: int) -> int:
        """States 1 and 2 — outer pane is either shut or at least minimally open."""
        outer_min = self._outer_pane_floor()
        if avail < outer_min + floor:
            # Shell too narrow to honour both floors; the player column wins.
            return left
        if left >= outer_min:
            return left
        return 0 if left < outer_min * CLIPS_SNAP_SHUT else outer_min

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

    def _place_left_handle_at_verge(
        self, main_total: int, left: int, avail: int, inner_w: int
    ) -> bool:
        """Left drag with the outer pane a stone's throw from its own floor.

        Neither pane can give the other anything here, so the room has just two
        placements: outer shut with the player column holding it, or outer holding
        it with the column kissed shut. Halfway across decides which.
        """
        if left >= avail * CLIPS_SNAP_SHUT:
            self._player_column_kissed = True
            self._apply_left_drag_geometry(main_total, avail, 0, inner_w)
            return True
        if self._outer_pane_width() <= PANE_FREED:
            # Already against the wall, so there is nothing left to shut. Pushing
            # on would just shove the right handle along.
            return True
        return self._shut_outer_and_travel()

    def _outer_pane_width(self) -> int:
        sizes = self.ui.main_splitter.sizes()
        return int(sizes[0]) if sizes else 0

    def _clips_width(self) -> int:
        return self._outer_pane_width()

    def _apply_left_drag_geometry(
        self, main_total: int, left: int, player_w: int, inner_w: int
    ) -> None:
        handle = self._right_handle_width()
        self._free_collapsed_minimums(
            player_w <= 0, inner_w <= 0, outer_shut=int(left) <= 0
        )
        block = player_w + inner_w + handle
        self.ui.main_splitter.setSizes([max(int(left), 0), max(block, handle)])
        self.right_h_splitter.setSizes([max(int(player_w), 0), max(int(inner_w), 0)])

    def _right_drag_mode_for_state(self) -> str:
        """Which pane, if any, this drag has to snap back open.

        A collapsed pane is held there by a one-pixel minimum, and Qt reads that
        as licence to regrow it a pixel at a time. Panes must pop open at their
        floor in one step, so any drag starting from a collapse is driven here.
        """
        sizes = self.right_h_splitter.sizes()
        if len(sizes) < 2:
            return ""
        if int(sizes[0]) <= PANE_FREED:
            return FROM_KISS
        # Below layout floor = shut: free-drag scrap (2px..floor-1) used to latch
        # mode "" and unroll, then snap to floor on release («свиток»).
        return REOPEN_QUEUE if int(sizes[1]) < self._inner_pane_floor() else ""

    def _drag_right_from_kiss(self, global_x: int, grab_offset: int) -> bool:
        """Player column collapsed: reopen it, or shut the inner pane and travel."""
        sizes = self.right_h_splitter.sizes()
        if len(sizes) >= 2 and int(sizes[1]) <= PANE_FREED:
            # Nothing but the handle is left, so the inner pane comes out of outer.
            return self._pull_inner_out_of_outer(global_x, grab_offset)
        return self._drag_right_player_vs_inner(global_x, grab_offset)

    def _drag_right_both_open(self, global_x: int, grab_offset: int) -> bool:
        """Both panes open: same hysteresis as from-kiss (Stage B open→kiss)."""
        return self._drag_right_player_vs_inner(global_x, grab_offset)

    def _drag_right_player_vs_inner(self, global_x: int, grab_offset: int) -> bool:
        """Divide player | inner with kiss hysteresis; swallow native moveSplitter."""
        room, pointer = self._right_column_room(global_x, grab_offset)
        if room <= 0:
            return False
        # Layout floor (not content hint) — cards must not inflate the neighbour.
        floor = self._scaled_player_floor(room, self._inner_pane_floor())
        if floor <= 0:
            # Mirror of the left handle at the verge: the inner pane is a stone's
            # throw from its own floor, so it either holds the room or shuts and
            # takes the kissed left handle along. Halfway across decides which.
            if pointer >= room * CLIPS_SNAP_SHUT:
                self.kiss_right_column_shut()
            else:
                self._apply_right_column(room, 0)
            return True
        return self._apply_right_column(room, self._resolve_player_width(pointer, floor))

    def _reopen_queue_pane(self, global_x: int, grab_offset: int) -> bool:
        """Inner pane collapsed: it pops back to its floor, the player column yields."""
        room, pointer = self._right_column_room(global_x, grab_offset)
        if room <= 0:
            return False
        inner_w = self._snap_inner_width(room - pointer, room)
        return self._apply_right_column(room, room - inner_w)

    def _right_column_room(self, global_x: int, grab_offset: int) -> tuple[int, int]:
        """Splittable width of the right column, and the player width asked for."""
        rhs = self.right_h_splitter
        sizes = rhs.sizes()
        if len(sizes) < 2:
            return 0, 0
        room = sum(int(s) for s in sizes)
        pointer = rhs.mapFromGlobal(QPoint(int(global_x), 0)).x() - int(grab_offset)
        return room, max(0, min(int(pointer), room))

    def _apply_right_column(self, room: int, player_w: int) -> bool:
        player_w = max(0, min(int(player_w), int(room)))
        inner_w = int(room) - player_w
        self._free_collapsed_minimums(player_w <= 0, inner_w <= 0)
        self.right_h_splitter.setSizes([player_w, inner_w])
        return True

    def _pull_inner_out_of_outer(self, global_x: int, grab_offset: int) -> bool:
        """Right handle in state 5 with the inner pane shut too — both at the wall.

        Everywhere else the right handle divides the player column against the
        inner pane and the outer pane is not involved. Here there is no inner
        pane left to divide against, so the room for it has to come out of the
        outer pane — otherwise the handle would be dead.
        """
        main = self.ui.main_splitter
        handle = self._right_handle_width()
        main_total = sum(main.sizes()) or main.width()
        room = main_total - handle
        if room <= 0:
            return False

        pointer = main.mapFromGlobal(QPoint(int(global_x), 0)).x() - int(grab_offset)
        inner_w = self._snap_inner_width(room - pointer, room)
        if inner_w <= 0:
            self.kiss_right_column_shut()
            return True
        self._free_collapsed_minimums(True, False)
        main.setSizes([max(room - inner_w, 0), handle + inner_w])
        self.right_h_splitter.setSizes([0, inner_w])
        return True

    def _shut_outer_and_travel(self) -> bool:
        """Shut the outer pane from the verge, taking the kissed right handle along.

        The meeting point is a rigid joint here, so both handles end up against
        the left wall and the inner pane takes up the room the outer pane gave
        back. Handing it to the player column instead would reopen a pane the
        drag never asked for.
        """
        main = self.ui.main_splitter
        handle = self._right_handle_width()
        main_total = sum(main.sizes()) or main.width()
        room = main_total - handle
        if room <= 0:
            return False
        self._player_column_kissed = True
        self._free_collapsed_minimums(True, False, outer_shut=True)
        main.setSizes([0, main_total])
        self.right_h_splitter.setSizes([0, room])
        return True

    def _shut_clips_and_travel(self) -> bool:
        return self._shut_outer_and_travel()

    def _queue_pane_floor(self) -> int:
        """Narrowest the queue renders at — its own content minimum."""
        return max(int(self.render_queue_panel.minimumSizeHint().width()), 1)

    def _queue_layout_floor(self) -> int:
        """Hard open floor from layout_defaults (same role as Clips left min)."""
        from steempeg.ui.layout_defaults import queue_panel_min_width

        win_w = int(self.ui.width() or 0) if getattr(self, "ui", None) else 0
        if win_w <= 0:
            return 380
        return max(80, int(queue_panel_min_width(win_w, widget=getattr(self, "ui", None))))

    def _snap_inner_width(self, wanted: int, room: int) -> int:
        """Shut, or at least the inner layout min — never creep via content hint."""
        floor = min(self._inner_pane_floor(), room)
        if wanted < floor * CLIPS_SNAP_SHUT:
            return 0
        return min(max(int(wanted), floor), room)

    def _snap_queue_width(self, wanted: int, room: int) -> int:
        """Shut, or at least the queue layout min — never creep via content hint."""
        floor = min(self._queue_layout_floor(), room)
        if wanted < floor * CLIPS_SNAP_SHUT:
            return 0
        return min(max(int(wanted), floor), room)

    def kiss_right_column_shut(self) -> None:
        """State 5 with the inner pane already closed.

        The player column collapses and the right column shrinks to its bare
        handle, so the two handles meet while the right one stays grabbable.
        """
        if not self._splitter_rules_active():
            return
        main = self.ui.main_splitter
        sizes = main.sizes()
        if len(sizes) < 2:
            return
        handle = self._right_handle_width()
        self._free_collapsed_minimums(True, True)
        self.right_h_splitter.setSizes([0, 0])
        main.setSizes([max(sum(sizes) - handle, 0), handle])

    def _free_collapsed_minimums(
        self, player_shut: bool, inner_shut: bool, *, outer_shut: bool | None = None
    ) -> None:
        """Collapsed → ``PANE_FREED``; open queue → layout floor (blocks squash)."""
        self.ui.right_panel.setMinimumWidth(PANE_FREED if player_shut else 0)
        queue = self.render_queue_panel
        lib = getattr(self.ui, "left_panel", None)
        if outer_shut is None:
            outer_shut = self._outer_pane_width() < self._outer_pane_floor()
        if self._queue_on_left():
            # Kiss with inner shut: outer (queue) holds the room.
            queue_shut = False if (player_shut and inner_shut) else bool(outer_shut)
        else:
            queue_shut = bool(inner_shut)
        if queue_shut:
            queue.setMinimumWidth(PANE_FREED)
        else:
            # Explicit min like Clips Manager — zero lets the list crush itself.
            queue.setMinimumWidth(self._queue_layout_floor())
        if lib is not None and self._queue_on_left():
            if inner_shut:
                lib.setMinimumWidth(PANE_FREED)
            else:
                lib.setMinimumWidth(self._library_min_width())
        # Both inner-column panes gone: the right column is nothing but its own
        # handle. Without this the outer splitter re-inflates it and the kiss
        # springs back open.
        shut_width = self._right_handle_width() if (player_shut and inner_shut) else 0
        self.right_h_splitter.setMinimumWidth(shut_width)
