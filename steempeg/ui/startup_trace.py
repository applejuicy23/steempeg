"""Lightweight post-splash UI-thread tracer for cold-start hitch hunts.

Always logs critical delayed bombs at INFO. Extra enter/leave spans need
``STEEMPEG_STARTUP_TRACE=1``.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

_log = logging.getLogger("steempeg.startup_trace")
_t0: Optional[float] = None
_enabled: Optional[bool] = None


def startup_trace_enabled() -> bool:
    global _enabled
    if _enabled is None:
        raw = (os.environ.get("STEEMPEG_STARTUP_TRACE") or "").strip().lower()
        _enabled = raw in ("1", "true", "yes", "on")
    return bool(_enabled)


def startup_trace_reset() -> None:
    global _t0
    _t0 = time.perf_counter()
    _log.info("startup_trace: reset (t=0)")


def startup_trace(event: str, **fields) -> None:
    """Log ``+XXXms event key=val…`` — always for hydrate bombs; spans if TRACE=1."""
    global _t0
    if _t0 is None:
        _t0 = time.perf_counter()
    ms = int((time.perf_counter() - _t0) * 1000)
    extra = ""
    if fields:
        parts = [f"{k}={v}" for k, v in fields.items()]
        extra = " " + " ".join(parts)
    # Always surface the delayed bombs that freeze Clips marquees.
    critical = (
        "hydrate" in event
        or "shown" in event
        or "finished" in event
        or "chunk" in event
        or "bomb" in event
        or event.startswith("main_")
        or event.startswith("progressive_")
    )
    if critical or startup_trace_enabled():
        _log.info("startup_trace: +%dms %s%s", ms, event, extra)


class startup_span:
    """Context manager — logs enter/leave duration for a named UI burst."""

    def __init__(self, event: str, **fields):
        self.event = event
        self.fields = fields
        self._t = 0.0

    def __enter__(self):
        self._t = time.perf_counter()
        if startup_trace_enabled():
            startup_trace(f"{self.event}:begin", **self.fields)
        return self

    def __exit__(self, exc_type, exc, tb):
        if startup_trace_enabled():
            dt = int((time.perf_counter() - self._t) * 1000)
            startup_trace(f"{self.event}:end", ms=dt, **self.fields)
        return False
