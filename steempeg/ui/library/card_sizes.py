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
# Screenshots stock = today's photo card (was the only size).
DEFAULT_SCREENSHOTS_CARD_SIZE = CARD_SIZE_MEDIUM

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
    # full = title+date · compact = title + meta · info = title marquee + info glyph
    footer_mode: str
    title_font: int
    meta_font: int
    icon_px: int
    badge_font: int
    queue_badge: int
    health_dot: int
    footer_pad_h: int


# Big = today's ClipCard. Medium ≈ ScreenshotPhoto. Small = dense thumb + title/info.
_SPECS: dict[str, CardSizeSpec] = {
    CARD_SIZE_BIG: CardSizeSpec(
        key=CARD_SIZE_BIG,
        label="Big",
        card_w=254,
        card_h=184,
        thumb_w=254,
        thumb_h=144,
        # Cell == card; spacing alone owns the gutter (no phantom item plate).
        cell_w=254,
        cell_h=184,
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
        # Room for title+meta pads without killing 3-col at a slim splitter.
        card_h=136,
        thumb_w=168,
        thumb_h=94,
        cell_w=168,
        cell_h=136,
        spacing=10,
        footer_mode="compact",
        title_font=13,  # same face size as Big
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
        # Between old micro (112) and Medium (168): title + info strip fits.
        card_w=128,
        card_h=108,
        thumb_w=128,
        thumb_h=78,
        cell_w=128,
        cell_h=108,
        spacing=8,
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


# --- Screenshots (Grid-only for now; List → v51) -----------------------------

@dataclass(frozen=True)
class ScreenshotCardSizeSpec:
    key: str
    label: str
    card_w: int
    card_h: int
    thumb_h: int
    footer_h: int
    spacing: int
    # full = title + date/time/size · compact = title + source·date · info = title + ⓘ
    footer_mode: str
    title_font: int
    meta_font: int
    icon_px: int
    pad_h: int
    pad_v: int


_SCREENSHOT_SPECS: dict[str, ScreenshotCardSizeSpec] = {
    CARD_SIZE_BIG: ScreenshotCardSizeSpec(
        key=CARD_SIZE_BIG,
        label="Big",
        # Same outer footprint as Clips Big; taller footer so game logo +
        # title stay above source icon / date (40px + 24px icon overlapped).
        card_w=254,
        card_h=184,
        thumb_h=134,
        footer_h=50,
        spacing=15,
        footer_mode="full",
        title_font=13,
        meta_font=11,
        icon_px=18,
        pad_h=12,
        pad_v=6,
    ),
    CARD_SIZE_MEDIUM: ScreenshotCardSizeSpec(
        key=CARD_SIZE_MEDIUM,
        label="Medium",
        # Stock Screenshots photo card (pre-Size ladder).
        card_w=168,
        card_h=142,
        thumb_h=94,
        footer_h=48,
        spacing=14,
        footer_mode="compact",
        title_font=13,
        meta_font=11,
        icon_px=16,
        pad_h=12,
        pad_v=8,
    ),
    CARD_SIZE_SMALL: ScreenshotCardSizeSpec(
        key=CARD_SIZE_SMALL,
        label="Small",
        # Match Clips Small — game logo on thumb + marquee title + info glyph.
        card_w=128,
        card_h=108,
        thumb_h=78,
        footer_h=30,
        spacing=8,
        footer_mode="info",
        title_font=11,
        meta_font=9,
        icon_px=16,
        pad_h=6,
        pad_v=4,
    ),
}


def screenshot_card_size_spec(
    size: str | None, *, default: str = DEFAULT_SCREENSHOTS_CARD_SIZE
) -> ScreenshotCardSizeSpec:
    return _SCREENSHOT_SPECS[normalize_card_size(size, default=default)]


def screenshot_cell_size(
    size: str | None, *, default: str = DEFAULT_SCREENSHOTS_CARD_SIZE
) -> QSize:
    spec = screenshot_card_size_spec(size, default=default)
    return QSize(spec.card_w, spec.card_h)


def screenshot_grid_size(
    size: str | None, *, default: str = DEFAULT_SCREENSHOTS_CARD_SIZE
) -> QSize:
    spec = screenshot_card_size_spec(size, default=default)
    return QSize(spec.card_w + spec.spacing, spec.card_h + spec.spacing)
