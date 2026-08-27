"""Package: Deck / gamepad input bus + Portable action mapping."""
from __future__ import annotations

from steempeg.input.deck_actions import install_deck_actions
from steempeg.input.gamepad import (
    OS_ONLY_BUTTONS,
    DeckButton,
    GamepadBus,
    gamepad_bus,
)

__all__ = [
    "DeckButton",
    "GamepadBus",
    "OS_ONLY_BUTTONS",
    "gamepad_bus",
    "install_deck_actions",
]
