"""Library / queue card size ladder (Big · Medium · Small).

Replaces Grid/List as the primary density control. List tables remain behind
Settings → Restore classic List view.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSize

CARD_SIZE_BIG = "big"
CARD_SIZE_MEDIUM = "medium"
CARD_SIZE_SMALL = "small"
CARD_SIZES = (CARD_SIZE_BIG, CARD_SIZE_MEDIUM, CARD_SIZE_SMALL)

DEFAULT_LIBRARY_CARD_SIZE = CARD_SIZE_BIG
DEFAULT_QUEUE_CARD_SIZE = CARD_SIZE_MEDIUM

CARD_SIZE_LABELS = {
    CARD_SIZE_BIG: "Big",
    CARD_SIZE_MEDIUM: "Medium",
    CARD_SIZE_SMALL: "Small",
}


@dataclass(frozen=True)
class CardSizeSpec:
    key: str
    label: str
    card_w: int
    card_h: int
    thumb_w: int
    thumb_h: int
    cell_w: int
    cell_h: int
    spacing: int
    # full = title+date · compact = title (+ short meta) · info = ⓘ only
    footer_mode: str
    title_font: int
    meta_font: int
    icon_px: int
    badge_font: int
    queue_badge: int
    health_dot: int
    footer_pad_h: int


# Big = today's ClipCard. Medium ≈ ScreenshotPhoto. Small = dense thumb + ⓘ.
_SPECS: dict[str, CardSizeSpec] = {
    CARD_SIZE_BIG: CardSizeSpec(
        key=CARD_SIZE_BIG,
        label="Big",
        card_w=254,
        card_h=184,
        thumb_w=254,
        thumb_h=144,
        cell_w=260,
        cell_h=190,
        spacing=15,
        footer_mode="full",
        title_font=13,
        meta_font=11,
        icon_px=24,
        badge_font=11,
        queue_badge=26,
        health_dot=14,
        footer_pad_h=12,
    ),
    CARD_SIZE_MEDIUM: CardSizeSpec(
        key=CARD_SIZE_MEDIUM,
        label="Medium",
        card_w=168,
        card_h=142,
        thumb_w=168,
        thumb_h=94,
        cell_w=182,
        cell_h=156,
        spacing=14,
        footer_mode="compact",
        title_font=12,
        meta_font=10,
        icon_px=20,
        badge_font=10,
        queue_badge=22,
        health_dot=12,
        footer_pad_h=10,
    ),
    CARD_SIZE_SMALL: CardSizeSpec(
        key=CARD_SIZE_SMALL,
        label="Small",
        card_w=112,
        card_h=88,
        thumb_w=112,
        thumb_h=68,
        cell_w=124,
        cell_h=100,
        spacing=10,
        footer_mode="info",
        title_font=11,
        meta_font=9,
        icon_px=16,
        badge_font=9,
        queue_badge=18,
        health_dot=10,
        footer_pad_h=6,
    ),
}


def normalize_card_size(value, *, default: str = DEFAULT_LIBRARY_CARD_SIZE) -> str:
    key = str(value or "").strip().lower()
    if key in _SPECS:
        return key
    return default if default in _SPECS else CARD_SIZE_BIG


def card_size_spec(size: str | None, *, default: str = DEFAULT_LIBRARY_CARD_SIZE) -> CardSizeSpec:
    return _SPECS[normalize_card_size(size, default=default)]


def card_cell_size(size: str | None, *, default: str = DEFAULT_LIBRARY_CARD_SIZE) -> QSize:
    spec = card_size_spec(size, default=default)
    return QSize(spec.cell_w, spec.cell_h)


def card_grid_size(size: str | None, *, default: str = DEFAULT_LIBRARY_CARD_SIZE) -> QSize:
    """QListWidget.setGridSize — cell + spacing."""
    spec = card_size_spec(size, default=default)
    return QSize(spec.cell_w + spec.spacing, spec.cell_h + spec.spacing)


# --- Queue cards (separate ladder; big ≈ old grid card) ---------------------

@dataclass(frozen=True)
class QueueCardSizeSpec:
    key: str
    label: str
    card_w: int
    card_h: int
    thumb_w: int
    thumb_h: int
    text_h: int
    gap: int
    footer_mode: str  # full | compact | info


_QUEUE_SPECS: dict[str, QueueCardSizeSpec] = {
    CARD_SIZE_BIG: QueueCardSizeSpec(
        key=CARD_SIZE_BIG,
        label="Big",
        card_w=280,
        card_h=244,
        thumb_w=280,
        thumb_h=148,
        text_h=96,
        gap=10,
        footer_mode="full",
    ),
    CARD_SIZE_MEDIUM: QueueCardSizeSpec(
        key=CARD_SIZE_MEDIUM,
        label="Medium",
        card_w=200,
        card_h=168,
        thumb_w=200,
        thumb_h=108,
        text_h=60,
        gap=10,
        footer_mode="compact",
    ),
    CARD_SIZE_SMALL: QueueCardSizeSpec(
        key=CARD_SIZE_SMALL,
        label="Small",
        card_w=132,
        card_h=108,
        thumb_w=132,
        thumb_h=74,
        text_h=34,
        gap=8,
        footer_mode="info",
    ),
}


def queue_card_size_spec(
    size: str | None, *, default: str = DEFAULT_QUEUE_CARD_SIZE
) -> QueueCardSizeSpec:
    return _QUEUE_SPECS[normalize_card_size(size, default=default)]
