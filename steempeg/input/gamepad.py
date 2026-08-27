"""Steam Deck / Xbox-layout gamepad button ids + in-process event bus.

Real HID / Steam Input (later) and Dev Mode pad emulator both emit here so
Portable actions share one path.
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Callable

from PySide6.QtCore import QObject, Signal

_log = logging.getLogger(__name__)


class DeckButton(str, Enum):
    """Physical Deck controls we may bind (STEAM / QAM stay OS-only)."""

    # Face + chrome
    A = "a"  # south — confirm / play-pause
    B = "b"  # east — back / close sheet
    X = "x"  # west — add to queue
    Y = "y"  # north — (reserved / trim later)
    VIEW = "view"  # left Select-like — Choose a Clip
    MENU = "menu"  # right Options — Render settings
    # D-pad
    DPAD_UP = "dpad_up"
    DPAD_DOWN = "dpad_down"
    DPAD_LEFT = "dpad_left"
    DPAD_RIGHT = "dpad_right"
    # Shoulders / triggers
    L1 = "l1"
    R1 = "r1"
    L2 = "l2"
    R2 = "r2"
    # Stick clicks (optional later)
    L3 = "l3"
    R3 = "r3"
    # OS-only — exposed in Dev UI as disabled labels, never dispatched
    STEAM = "steam"
    QAM = "qam"


# Buttons the OS owns — emulator shows them locked.
OS_ONLY_BUTTONS = frozenset({DeckButton.STEAM, DeckButton.QAM})


class GamepadBus(QObject):
    """Singleton fan-out for DeckButton press/release."""

    button_pressed = Signal(object)  # DeckButton
    button_released = Signal(object)

    def press(self, button: DeckButton | str) -> None:
        btn = _coerce(button)
        if btn is None:
            return
        if btn in OS_ONLY_BUTTONS:
            _log.debug("Ignoring OS-only Deck button: %s", btn.value)
            return
        self.button_pressed.emit(btn)

    def release(self, button: DeckButton | str) -> None:
        btn = _coerce(button)
        if btn is None or btn in OS_ONLY_BUTTONS:
            return
        self.button_released.emit(btn)

    def tap(self, button: DeckButton | str) -> None:
        """Press then release (Dev Mode click)."""
        self.press(button)
        self.release(button)


_bus: GamepadBus | None = None


def gamepad_bus() -> GamepadBus:
    global _bus
    if _bus is None:
        _bus = GamepadBus()
    return _bus


def _coerce(button: DeckButton | str) -> DeckButton | None:
    if isinstance(button, DeckButton):
        return button
    try:
        return DeckButton(str(button).strip().lower())
    except ValueError:
        _log.debug("Unknown Deck button id: %r", button)
        return None


Handler = Callable[[DeckButton], None]
