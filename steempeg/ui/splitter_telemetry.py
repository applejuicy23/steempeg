"""Opt-in Dev Mode telemetry for QSplitter movement / blockers.

Enable from Developer Tools → Tools → «Splitter movement telemetry».
When off, hooks are idle (no wrap, no overlay, negligible cost).

Logs go to the session steempeg_*.log as ``[splitter-tel]`` lines and optionally
to a small on-screen overlay.
"""
from __future__ import annotations

import logging
import traceback
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QSplitter, QWidget

_log = logging.getLogger(__name__)

KEY_SPLITTER_TELEMETRY = "dev_splitter_telemetry"
KEY_SPLITTER_TELEMETRY_OVERLAY = "dev_splitter_telemetry_overlay"

# Named splitters we care about for layout debugging.
_TRACKED = (
    ("main_splitter", "ui"),
    ("right_h_splitter", "self"),
    ("main_v_splitter", "self"),
)

_reason: ContextVar[str | None] = ContextVar("splitter_tel_reason", default=None)

# Module singleton — one watcher per process.
_controller: SplitterTelemetryController | None = None


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


@contextmanager
def splitter_reason(tag: str):
    """Tag the next setSizes / move as coming from a known layout path."""
    token = _reason.set(str(tag or "").strip() or None)
    try:
        yield
    finally:
        _reason.reset(token)


def get_splitter_telemetry() -> SplitterTelemetryController:
    global _controller
    if _controller is None:
        _controller = SplitterTelemetryController()
    return _controller


def install_splitter_telemetry(host) -> SplitterTelemetryController:
    """Attach to the app host and restore the saved Dev Mode preference."""
    ctl = get_splitter_telemetry()
    ctl.attach_host(host)
    enabled = False
    overlay = False
    try:
        settings = host.load_user_settings() if hasattr(host, "load_user_settings") else {}
        if isinstance(settings, dict):
            enabled = _is_truthy(settings.get(KEY_SPLITTER_TELEMETRY, False))
            overlay = _is_truthy(settings.get(KEY_SPLITTER_TELEMETRY_OVERLAY, False))
            # Only auto-arm when Dev Mode itself is on.
            if not _is_truthy(settings.get("dev_mode", False)):
                enabled = False
    except Exception:
        enabled = False
        overlay = False
    ctl.set_enabled(enabled, overlay=overlay, persist=False)
    return ctl


class SplitterTelemetryController:
    """Wraps tracked splitters' setSizes + splitterMoved when enabled."""

    def __init__(self) -> None:
        self._host: Any = None
        self._enabled = False
        self._overlay_on = False
        self._wrapped: dict[int, tuple[QSplitter, Any]] = {}
        self._moved_slots: list[tuple[QSplitter, Any]] = []
        self._ring: deque[str] = deque(maxlen=48)
        self._overlay: QLabel | None = None
        self._overlay_timer: QTimer | None = None
        self._depth = 0  # re-entrancy guard while we read sizes / paint overlay

    # ── public API ───────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def overlay_enabled(self) -> bool:
        return self._overlay_on

    def attach_host(self, host) -> None:
        self._host = host

    def set_enabled(
        self,
        on: bool,
        *,
        overlay: bool | None = None,
        persist: bool = True,
    ) -> None:
        want = bool(on)
        if overlay is not None:
            self._overlay_on = bool(overlay)
        if want == self._enabled:
            self._sync_overlay_widget()
            if persist:
                self._persist()
            return
        self._enabled = want
        if want:
            self._hook_all()
            self.emit(
                "telemetry_on",
                detail=f"overlay={'on' if self._overlay_on else 'off'}",
            )
        else:
            self.emit("telemetry_off")
            self._unhook_all()
        self._sync_overlay_widget()
        if persist:
            self._persist()

    def set_overlay(self, on: bool, *, persist: bool = True) -> None:
        self._overlay_on = bool(on)
        self._sync_overlay_widget()
        if persist:
            self._persist()
        if self._enabled:
            self.emit(
                "overlay",
                detail="on" if self._overlay_on else "off",
            )

    def dump_snapshot(self, reason: str = "manual_dump") -> str:
        """Log a one-shot snapshot of every tracked splitter; return the text."""
        lines = [self._format_line(reason, "snapshot", detail="all tracked")]
        for name, splitter in self._iter_tracked():
            snap = self._snapshot(splitter)
            blockers = self._collect_blockers(name, splitter, snap)
            lines.append(
                self._format_line(
                    reason,
                    name,
                    before=None,
                    after=snap,
                    blockers=blockers,
                    caller="(dump)",
                )
            )
        text = "\n".join(lines)
        for line in lines:
            _log.info("%s", line)
            self._ring.append(line)
        self._refresh_overlay()
        return text

    def note(self, event: str, *, detail: str = "", splitter_name: str = "") -> None:
        """Manual breadcrumb from layout code (cheap no-op when disabled)."""
        if not self._enabled:
            return
        self.emit(event, detail=detail, splitter_name=splitter_name or "shell")

    def emit(
        self,
        event: str,
        *,
        splitter_name: str = "",
        detail: str = "",
        before: dict | None = None,
        after: dict | None = None,
        blockers: list[str] | None = None,
        caller: str | None = None,
    ) -> None:
        if not self._enabled and event not in ("telemetry_on", "telemetry_off"):
            return
        reason = _reason.get() or event
        line = self._format_line(
            reason,
            splitter_name or event,
            detail=detail,
            before=before,
            after=after,
            blockers=blockers,
            caller=caller if caller is not None else self._caller_summary(),
        )
        _log.info("%s", line)
        self._ring.append(line)
        self._refresh_overlay()

    # ── hook / unhook ────────────────────────────────────────────────────────

    def _hook_all(self) -> None:
        self._unhook_all()
        for name, splitter in self._iter_tracked():
            self._wrap_splitter(name, splitter)

    def _unhook_all(self) -> None:
        for sid, (splitter, original) in list(self._wrapped.items()):
            try:
                splitter.setSizes = original  # type: ignore[method-assign]
            except Exception:
                pass
        self._wrapped.clear()
        for splitter, slot in self._moved_slots:
            try:
                splitter.splitterMoved.disconnect(slot)
            except Exception:
                pass
        self._moved_slots.clear()

    def _wrap_splitter(self, name: str, splitter: QSplitter) -> None:
        if splitter is None:
            return
        sid = id(splitter)
        if sid in self._wrapped:
            return
        original = splitter.setSizes

        def _set_sizes(sizes, *, _name=name, _orig=original, _spl=splitter):
            return self._on_set_sizes(_name, _spl, _orig, sizes)

        splitter.setSizes = _set_sizes  # type: ignore[method-assign]
        self._wrapped[sid] = (splitter, original)

        def _moved(pos: int, index: int, *, _name=name, _spl=splitter):
            self._on_moved(_name, _spl, pos, index)

        try:
            splitter.splitterMoved.connect(_moved)
            self._moved_slots.append((splitter, _moved))
        except Exception:
            pass

        # Name the widget for logs / Qt Designer hunting.
        try:
            if not splitter.objectName():
                splitter.setObjectName(name)
        except Exception:
            pass

    def _iter_tracked(self) -> list[tuple[str, QSplitter]]:
        host = self._host
        if host is None:
            return []
        out: list[tuple[str, QSplitter]] = []
        for name, where in _TRACKED:
            if where == "ui":
                ui = getattr(host, "ui", None)
                spl = getattr(ui, name, None) if ui is not None else None
            else:
                spl = getattr(host, name, None)
            if isinstance(spl, QSplitter):
                out.append((name, spl))
        return out

    # ── event handlers ───────────────────────────────────────────────────────

    def _on_set_sizes(self, name: str, splitter: QSplitter, original, sizes) -> None:
        if self._depth or not self._enabled:
            return original(sizes)
        self._depth += 1
        try:
            before = self._snapshot(splitter)
            result = original(sizes)
            after = self._snapshot(splitter)
            blockers = self._collect_blockers(name, splitter, after)
            if before.get("sizes") != after.get("sizes") or blockers:
                self.emit(
                    "setSizes",
                    splitter_name=name,
                    detail=f"requested={list(sizes)}",
                    before=before,
                    after=after,
                    blockers=blockers,
                )
            return result
        finally:
            self._depth -= 1

    def _on_moved(self, name: str, splitter: QSplitter, pos: int, index: int) -> None:
        if self._depth or not self._enabled:
            return
        self._depth += 1
        try:
            after = self._snapshot(splitter)
            blockers = self._collect_blockers(name, splitter, after)
            self.emit(
                "splitterMoved",
                splitter_name=name,
                detail=f"pos={pos} index={index}",
                after=after,
                blockers=blockers,
            )
        finally:
            self._depth -= 1

    # ── snapshot / blockers ──────────────────────────────────────────────────

    def _snapshot(self, splitter: QSplitter) -> dict:
        sizes: list[int] = []
        try:
            sizes = [int(s) for s in splitter.sizes()]
        except Exception:
            sizes = []
        panes: list[dict] = []
        try:
            count = int(splitter.count())
        except Exception:
            count = 0
        for i in range(count):
            w = splitter.widget(i)
            if w is None:
                panes.append({"i": i, "missing": True})
                continue
            panes.append(
                {
                    "i": i,
                    "name": w.objectName() or type(w).__name__,
                    "vis": bool(w.isVisible()),
                    "hidden": bool(w.isHidden()),
                    "min_w": int(w.minimumWidth()),
                    "min_h": int(w.minimumHeight()),
                    "hint_w": int(w.minimumSizeHint().width()),
                    "hint_h": int(w.minimumSizeHint().height()),
                    "w": int(w.width()),
                    "h": int(w.height()),
                }
            )
        handle_w = 0
        try:
            handle_w = int(splitter.handleWidth() or 0)
        except Exception:
            pass
        return {
            "sizes": sizes,
            "total": sum(sizes) if sizes else 0,
            "handle_w": handle_w,
            "panes": panes,
            "orient": (
                "H"
                if splitter.orientation() == Qt.Orientation.Horizontal
                else "V"
            ),
        }

    def _collect_blockers(
        self, name: str, splitter: QSplitter, snap: dict
    ) -> list[str]:
        host = self._host
        blockers: list[str] = []
        sizes = snap.get("sizes") or []

        # Per-pane floors / hidden widgets.
        for pane in snap.get("panes") or []:
            if pane.get("missing"):
                blockers.append(f"pane{pane.get('i')}:missing")
                continue
            idx = pane.get("i", "?")
            if pane.get("hidden") or not pane.get("vis"):
                blockers.append(f"pane{idx}:hidden({pane.get('name')})")
            min_w = int(pane.get("min_w") or 0)
            hint_w = int(pane.get("hint_w") or 0)
            if min_w > 1:
                blockers.append(f"pane{idx}:minW={min_w}")
            try:
                pane_size = int(sizes[int(idx)]) if sizes and str(idx).isdigit() else -1
            except (IndexError, TypeError, ValueError):
                pane_size = -1
            # Content hint can act as an invisible floor when the pane is scrap/collapsed.
            if hint_w > 48 and 0 <= pane_size <= 1:
                blockers.append(f"pane{idx}:hintW={hint_w}")

        if host is not None:
            if bool(getattr(host, "is_theater", False)):
                blockers.append("theater")
            if bool(getattr(host, "is_fullscreen", False)) or bool(
                getattr(host, "_is_fullscreen", False)
            ):
                blockers.append("fullscreen")
            if bool(getattr(host, "_splitter_dragging", False)):
                side = getattr(host, "_splitter_drag_side", "")
                blockers.append(f"drag:{side or '?'}")
            if bool(getattr(host, "_player_column_kissed", False)):
                blockers.append("kiss")
            frozen_q = int(getattr(host, "_frozen_queue_width", 0) or 0)
            if frozen_q:
                blockers.append(f"frozen_queue={frozen_q}")
            mode = str(getattr(host, "_right_drag_mode", "") or "")
            if mode:
                blockers.append(f"right_mode={mode}")
            if bool(getattr(host, "_portable_like_dash_closed", False)):
                blockers.append("portable_dash_closed")
            # Like-a-Portable gap path (no middle handle) often re-glues sizes.
            try:
                if hasattr(host, "_desktop_render_layout_is_portable_like") and (
                    host._desktop_render_layout_is_portable_like()
                ):
                    middle = False
                    if hasattr(host, "_portable_like_middle_splitter_enabled"):
                        middle = bool(host._portable_like_middle_splitter_enabled())
                    blockers.append(
                        "portable_like_gap" if not middle else "portable_like_middle"
                    )
            except Exception:
                pass
            if bool(getattr(host, "_queue_user_collapsed", False)):
                blockers.append("queue_user_collapsed")

        # Collapsed scrap detection.
        for i, sz in enumerate(sizes):
            if int(sz) <= 1:
                blockers.append(f"size[{i}]=collapsed({sz})")
            elif int(sz) < 48:
                blockers.append(f"size[{i}]=scrap({sz})")

        # Deduplicate while preserving order.
        seen: set[str] = set()
        uniq: list[str] = []
        for b in blockers:
            if b not in seen:
                seen.add(b)
                uniq.append(b)
        return uniq

    # ── formatting ───────────────────────────────────────────────────────────

    def _format_line(
        self,
        reason: str,
        name: str,
        *,
        detail: str = "",
        before: dict | None = None,
        after: dict | None = None,
        blockers: list[str] | None = None,
        caller: str | None = None,
    ) -> str:
        parts = [f"[splitter-tel] {reason} · {name}"]
        if detail:
            parts.append(detail)
        if before is not None:
            parts.append(f"before={before.get('sizes')}")
        if after is not None:
            parts.append(f"after={after.get('sizes')} total={after.get('total')}")
            orient = after.get("orient")
            if orient:
                parts.append(orient)
        if blockers:
            parts.append("blockers=[" + ", ".join(blockers) + "]")
        if caller:
            parts.append(f"via {caller}")
        return " | ".join(parts)

    def _caller_summary(self, depth: int = 6) -> str:
        frames = traceback.extract_stack()
        skip_names = {
            "_caller_summary",
            "_format_line",
            "emit",
            "_on_set_sizes",
            "_on_moved",
            "_set_sizes",
            "note",
            "dump_snapshot",
        }
        picked: list[str] = []
        for fr in reversed(frames[:-1]):
            func = fr.name
            if func in skip_names:
                continue
            file = fr.filename.replace("\\", "/")
            if "splitter_telemetry.py" in file:
                continue
            short = file.rsplit("/", 1)[-1]
            picked.append(f"{short}:{fr.lineno}:{func}")
            if len(picked) >= depth:
                break
        tagged = _reason.get()
        if tagged:
            return f"tag={tagged}; " + " ← ".join(picked)
        return " ← ".join(picked) if picked else "?"

    # ── overlay / persist ────────────────────────────────────────────────────

    def _persist(self) -> None:
        host = self._host
        if host is None or not hasattr(host, "save_user_settings"):
            return
        try:
            if hasattr(host, "save_user_settings_batch"):
                host.save_user_settings_batch(
                    {
                        KEY_SPLITTER_TELEMETRY: bool(self._enabled),
                        KEY_SPLITTER_TELEMETRY_OVERLAY: bool(self._overlay_on),
                    }
                )
            else:
                host.save_user_settings(KEY_SPLITTER_TELEMETRY, bool(self._enabled))
                host.save_user_settings(
                    KEY_SPLITTER_TELEMETRY_OVERLAY, bool(self._overlay_on)
                )
        except Exception:
            _log.debug("splitter telemetry persist failed", exc_info=True)

    def _sync_overlay_widget(self) -> None:
        want = self._enabled and self._overlay_on
        if not want:
            if self._overlay is not None:
                self._overlay.hide()
                self._overlay.deleteLater()
                self._overlay = None
            if self._overlay_timer is not None:
                self._overlay_timer.stop()
                self._overlay_timer = None
            return
        host = self._host
        parent: QWidget | None = None
        if host is not None:
            parent = getattr(host, "ui", None)
        if parent is None:
            return
        if self._overlay is None:
            lab = QLabel(parent)
            lab.setObjectName("splitterTelemetryOverlay")
            lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            lab.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )
            font = QFont("Consolas")
            if not font.exactMatch():
                font = QFont("Courier New")
            font.setPointSize(9)
            lab.setFont(font)
            lab.setStyleSheet(
                "QLabel#splitterTelemetryOverlay {"
                " background: rgba(12, 12, 16, 190);"
                " color: #d8d4ff;"
                " border: 1px solid #6b5cff;"
                " border-radius: 6px;"
                " padding: 6px 8px;"
                "}"
            )
            lab.setWordWrap(True)
            self._overlay = lab
            timer = QTimer(parent)
            timer.setInterval(400)
            timer.timeout.connect(self._place_overlay)
            timer.start()
            self._overlay_timer = timer
        self._refresh_overlay()
        self._place_overlay()
        self._overlay.show()
        self._overlay.raise_()

    def _refresh_overlay(self) -> None:
        lab = self._overlay
        if lab is None or not self._overlay_on:
            return
        recent = list(self._ring)[-10:]
        if not recent:
            lab.setText("splitter-tel · waiting for events…")
        else:
            # Strip the common prefix so the overlay stays readable.
            lines = [
                ln.replace("[splitter-tel] ", "", 1) if ln.startswith("[splitter-tel] ") else ln
                for ln in recent
            ]
            lab.setText("splitter-tel\n" + "\n".join(lines))
        self._place_overlay()

    def _place_overlay(self) -> None:
        lab = self._overlay
        if lab is None:
            return
        parent = lab.parentWidget()
        if parent is None:
            return
        margin = 10
        lab.adjustSize()
        w = min(max(lab.sizeHint().width(), 320), max(parent.width() - 2 * margin, 200))
        h = min(max(lab.sizeHint().height(), 80), max(parent.height() // 3, 80))
        lab.setGeometry(margin, margin, w, h)
        lab.raise_()
