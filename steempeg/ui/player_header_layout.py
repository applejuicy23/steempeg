"""Player header title-cluster layout preference (Settings → Visual).

Two modes:

* ``steempeg_ui`` — classic left-aligned title + date/time (+ duration) meta
* ``steam_like`` — centered logo + game name; meta lives in the Clip info tip/popup only

Default is ``steam_like`` (matches Soft / Steam-like game icons).
"""
from __future__ import annotations

import os
import re

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget

from steempeg.ui import design_tokens as tok
from steempeg.ui.ui_density import COMFORT, UiDensity

KEY_PLAYER_HEADER_LAYOUT = "player_header_layout"

# Same stack Large / construction use — pin in QSS, QFont, and rich-text HTML.
# Qt rich text often ignores QLabel stylesheet ``font-family`` when spans set
# ``font-size``; omitting family made Medium/Small fall back to a different face.
# Keep rich-text family to a single preferred face (full stack lives on QFont/QSS) —
# comma-lists in QTextDocument CSS have been flaky across Qt builds.
def _header_title_font_css() -> str:
    """Live preferred family for rich-text / QSS header titles."""
    return f"font-family: '{tok.FONT_FAMILIES[0]}'; font-weight: 700;"


def _header_chip_font_css() -> str:
    return f"font-family: {tok.FONT_APP};"

HEADER_LAYOUT_STEEMPEG_UI = "steempeg_ui"
HEADER_LAYOUT_STEAM_LIKE = "steam_like"

HEADER_LAYOUT_DEFAULT = HEADER_LAYOUT_STEAM_LIKE

HEADER_LAYOUT_LABELS: tuple[tuple[str, str], ...] = (
    (HEADER_LAYOUT_STEAM_LIKE, "Steam-like"),
    (HEADER_LAYOUT_STEEMPEG_UI, "SteempegUI"),
)

# SteempegUI separators (v41.1 / v42.1 mix): large bullet after the game name,
# quieter middot between datetime and duration (and further meta parts).
# HTML nbsp so Qt rich text keeps padding around the fat bullet (plain spaces collapse).
_TITLE_SEP = "&nbsp;&nbsp;•&nbsp;&nbsp;"
_META_SEP = " · "

_current_layout: str = HEADER_LAYOUT_DEFAULT


def normalize_header_layout(value: object | None) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if text in (HEADER_LAYOUT_STEEMPEG_UI, "steempeg", "classic", "normal", "left"):
        return HEADER_LAYOUT_STEEMPEG_UI
    if text in (HEADER_LAYOUT_STEAM_LIKE, "steam", "centered", "center"):
        return HEADER_LAYOUT_STEAM_LIKE
    return HEADER_LAYOUT_DEFAULT


def get_header_layout() -> str:
    return _current_layout


def player_header_density(app) -> UiDensity:
    """Active density for the player header (falls back to comfort).

    Composes window density with Settings → Visual → Player header → Size
    (S/M/L). Callers that only need icon/font px should use the helpers below.
    """
    dense = getattr(app, "_ui_density_player", None) or getattr(app, "_ui_density", None)
    base = dense if dense is not None else COMFORT
    try:
        from steempeg.ui.player_header_size import apply_header_size_to_density

        return apply_header_size_to_density(base)
    except Exception:
        return base


def player_header_icon_px(app) -> int:
    """Game-icon box size for the title cluster."""
    return max(16, int(getattr(player_header_density(app), "header_icon", 24) or 24))


def player_header_font_px(app) -> int:
    return max(11, int(getattr(player_header_density(app), "header_font", 13) or 13))


def player_header_title_qfont(font_px: int | None = None) -> QFont:
    """Bold Segoe stack matching Large / construction — pixel size only varies."""
    px = max(11, int(font_px or COMFORT.header_font))
    return tok.ui_qfont(pixel_size=px, weight=QFont.Weight.Bold)


def player_header_chip_qfont(font_px: int | None = None) -> QFont:
    """Bold Segoe stack for header status / portable chips — size only varies."""
    px = max(11, int(font_px or COMFORT.header_font))
    return tok.ui_qfont(pixel_size=px, weight=QFont.Weight.Bold)


def set_header_layout(layout: object | None) -> str:
    global _current_layout
    _current_layout = normalize_header_layout(layout)
    return _current_layout


def load_header_layout_from_settings(settings: dict | None) -> str:
    raw = (settings or {}).get(KEY_PLAYER_HEADER_LAYOUT, HEADER_LAYOUT_DEFAULT)
    return set_header_layout(raw)


def split_clip_date_cell(text: str | None) -> tuple[str, str]:
    """Split library date cell ``12 July 2026\\n12:11 PM`` into (date, clock time)."""
    raw = (text or "").replace("\r\n", "\n").strip()
    if not raw:
        return "", ""
    if "\n" in raw:
        date_part, _, time_part = raw.partition("\n")
        return date_part.strip(), time_part.strip()
    # Already joined with ``at`` / comma / bare space — peel clock time off.
    m = re.search(
        r"^(.*?)\s+(?:at\s+|,\s*)?(\d{1,2}:\d{2}(?:\s*[AaPp][Mm])?)\s*$",
        raw,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return raw, ""


def _looks_like_duration(text: str) -> bool:
    """True for clip lengths like ``1m 29s`` / ``45s`` / ``1h 2m`` (not clock times)."""
    t = (text or "").strip()
    if not t or re.search(r"[AaPp][Mm]\b", t):
        return False
    return bool(
        re.fullmatch(
            r"(?:\d+h(?:\s*\d+m)?(?:\s*\d+s)?|\d+m(?:\s*\d+s)?|\d+s|--:--|—|-)",
            t,
            flags=re.IGNORECASE,
        )
    )


def join_clip_date_time(date_text: str | None, time_text: str | None) -> str:
    """Combine date + clock time with ``at``: ``12 July 2026 at 12:11 PM``.

    Never joins a duration into this string — callers pass duration separately.
    """
    date_part, embedded_time = split_clip_date_cell(date_text)
    time_part = (time_text or "").strip()
    if time_part and _looks_like_duration(time_part):
        # Table col 3 is duration; ignore if mis-passed as ``time``.
        time_part = ""
    if not time_part:
        time_part = embedded_time
    elif embedded_time and time_part in date_part:
        time_part = embedded_time

    if date_part and time_part:
        # Strip a prior comma / ``at`` if a caller already joined them.
        if time_part in date_part:
            cleaned = re.sub(
                r",\s*" + re.escape(time_part) + r"$",
                "",
                date_part,
            )
            cleaned = re.sub(
                r"\s+at\s+" + re.escape(time_part) + r"$",
                "",
                cleaned,
                flags=re.IGNORECASE,
            ).strip()
            if cleaned and cleaned != date_part:
                date_part = cleaned
            elif date_part.endswith(time_part):
                # Prefer canonical ``date at time`` even when already bare-spaced.
                date_only = date_part[: -len(time_part)].rstrip(" ,")
                date_only = re.sub(
                    r"\s+at\s*$", "", date_only, flags=re.IGNORECASE
                ).strip()
                if date_only:
                    return f"{date_only} at {time_part}"
                return date_part
        date_part = re.sub(r",\s*$", "", date_part).strip()
        date_part = re.sub(r"\s+at\s*$", "", date_part, flags=re.IGNORECASE).strip()
        return f"{date_part} at {time_part}"
    return date_part or time_part


def _esc(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def format_player_header_html(
    title: str,
    *,
    date: str = "",
    time: str = "",
    duration: str = "",
    extra_parts: list[str] | tuple[str, ...] | None = None,
    layout: str | None = None,
    font_px: int | None = None,
) -> str:
    """Build rich text for ``custom_text_label`` based on the active layout mode."""
    mode = normalize_header_layout(layout if layout is not None else _current_layout)
    title_plain = (title or "").strip() or "—"
    fs = max(11, int(font_px or COMFORT.header_font))
    # Inline size + family: Qt rich text often ignores QLabel stylesheet fonts.
    # Family must be in the span or Medium/Small can resolve a different face.
    # Single Segoe token in HTML; full stack stays on QFont / QSS.
    _title_style = (
        f"color:#ffffff; font-size:{fs}px; {_header_title_font_css()} "
        "vertical-align:middle;"
    )
    title_html = f'<span style="{_title_style}">{_esc(title_plain)}</span>'

    if mode == HEADER_LAYOUT_STEAM_LIKE:
        return title_html

    date_part, embedded_time = split_clip_date_cell(date)
    clock = (time or "").strip()
    dur = (duration or "").strip()
    # Library table: col 2 = date[+time], col 3 = duration (often mis-passed as time).
    if clock and _looks_like_duration(clock):
        if not dur:
            dur = clock
        clock = ""
    if not clock:
        clock = embedded_time

    meta: list[str] = []
    datetime_line = join_clip_date_time(date_part, clock)
    if datetime_line:
        meta.append(datetime_line)
    if dur and dur not in ("-", "—", "Time: -", "Time:-"):
        # Source Info uses ``Time: 3m 12s`` — strip the label for the header line.
        if dur.lower().startswith("time:"):
            dur = dur.split(":", 1)[1].strip()
        if dur and dur not in meta:
            meta.append(dur)
    for part in extra_parts or ():
        p = (part or "").strip()
        if p and p not in meta:
            meta.append(p)

    if not meta:
        return title_html

    # Classic SteempegUI: bold gray meta (same face/weight as the game title).
    # ``Game • 11 May 2026 at 02:28 PM · 3m 36s``
    meta_style = (
        f"color:#888888; font-size:{fs}px; {_header_title_font_css()} "
        "vertical-align:middle;"
    )
    title_sep = f'<span style="{meta_style}">{_TITLE_SEP}</span>'
    meta_sep = f'<span style="{meta_style}">{_META_SEP}</span>'
    meta_bits = [f'<span style="{meta_style}">{_esc(m)}</span>' for m in meta]
    return title_html + title_sep + meta_sep.join(meta_bits)


def plain_header_title(html_or_text: str) -> str:
    """Extract the game/title portion from header HTML or plain text."""
    plain = re.sub(r"<[^>]+>", "", html_or_text or "")
    plain = plain.replace("\xa0", " ").strip()
    if not plain:
        return ""
    # Prefer the earliest separator so ``Game • date · dur`` yields ``Game``.
    cut: int | None = None
    for sep in (" • ", " · ", "•", "·"):
        idx = plain.find(sep)
        if idx >= 0 and (cut is None or idx < cut):
            cut = idx
    if cut is not None:
        return plain[:cut].strip()
    return plain


def ensure_header_spacers(app) -> tuple[QWidget | None, QWidget | None]:
    """Create expanding spacer widgets used to center or left-align the title cluster."""
    left = getattr(app, "player_header_left_spacer", None)
    right = getattr(app, "player_header_right_spacer", None)
    if left is not None and right is not None:
        try:
            left.objectName()
            right.objectName()
            return left, right
        except RuntimeError:
            pass

    def _spacer(name: str) -> QWidget:
        w = QWidget()
        w.setObjectName(name)
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        w.setMinimumWidth(0)
        return w

    left = _spacer("playerHeaderLeftSpacer")
    right = _spacer("playerHeaderRightSpacer")
    app.player_header_left_spacer = left
    app.player_header_right_spacer = right
    return left, right


def ensure_header_center_wings(app) -> tuple[QWidget | None, QWidget | None]:
    """Equal-stretch wings so Steam-like portable can optically center on ``|``."""
    left = getattr(app, "player_header_left_wing", None)
    right = getattr(app, "player_header_right_wing", None)
    if left is not None and right is not None:
        try:
            left.objectName()
            right.objectName()
            return left, right
        except RuntimeError:
            pass

    def _wing(name: str) -> QWidget:
        w = QWidget()
        w.setObjectName(name)
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        w.setMinimumWidth(0)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        return w

    left = _wing("playerHeaderLeftWing")
    right = _wing("playerHeaderRightWing")
    app.player_header_left_wing = left
    app.player_header_right_wing = right
    return left, right


def ensure_header_right_dock_mirror(app) -> QWidget | None:
    """Fixed-width left pad mirroring the right status/actions dock.

    Keeps the Steam-like optical center (``|`` or title cluster) at the
    geometric midpoint of the header bar when Healthy / gear / close chips
    appear or change width.
    """
    mirror = getattr(app, "player_header_dock_mirror", None)
    if mirror is not None:
        try:
            mirror.objectName()
            return mirror
        except RuntimeError:
            pass
    mirror = QWidget()
    mirror.setObjectName("playerHeaderDockMirror")
    mirror.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
    mirror.setFixedWidth(0)
    mirror.setMinimumWidth(0)
    app.player_header_dock_mirror = mirror
    return mirror


def _widget_alive(w) -> bool:
    if w is None:
        return False
    try:
        w.objectName()
        return True
    except RuntimeError:
        return False


def _right_dock_widgets(app) -> list[QWidget]:
    out: list[QWidget] = []
    for name in (
        "player_header_status",
        "player_header_divider",
        "player_header_actions",
    ):
        w = getattr(app, name, None)
        if _widget_alive(w):
            out.append(w)
    return out


def _effective_widget_width(w: QWidget) -> int:
    """Width a visible dock widget currently consumes (0 if empty/hidden)."""
    if not w.isVisible():
        return 0
    # Prefer the laid-out width; fall back to sizeHint before first show.
    laid = int(w.width()) if w.width() > 0 else 0
    hint = max(0, int(w.sizeHint().width()))
    return max(laid, hint)


def measure_right_dock_span(app, spacing: int = 10) -> int:
    """Total width of visible right-dock widgets including inter-item spacing."""
    widths = [
        ww
        for w in _right_dock_widgets(app)
        if (ww := _effective_widget_width(w)) > 0
    ]
    if not widths:
        return 0
    return sum(widths) + max(0, spacing) * (len(widths) - 1)


# Breathing room so glyphs never sit flush under Healthy / Completed plaques.
_TITLE_DOCK_GAP_PX = 10


def _header_content_width(header: QWidget) -> int:
    """Inner width of the header bar (minus layout margins)."""
    hw = int(header.width()) if header.width() > 0 else 0
    if hw <= 0:
        return 0
    lay = header.layout()
    if lay is None:
        return hw
    m = lay.contentsMargins()
    return max(0, hw - int(m.left()) - int(m.right()))


def title_cluster_max_width(app, header: QWidget) -> int:
    """Largest width the icon+name(+info) cluster may occupy without underlapping dock.

    Steam-like keeps a left dock-mirror matching the right plaques, so the title
    lives in the middle band ``content - 2*dock``. Also keep the historic half-bar
    cap so long names cannot shove portable ``|``. SteempegUI is left-aligned and
    may use everything except the right dock.
    """
    content = _header_content_width(header)
    if content <= 0:
        return 0
    lay = header.layout()
    spacing = int(lay.spacing()) if lay is not None else 10
    dock = measure_right_dock_span(app, spacing)
    gap = _TITLE_DOCK_GAP_PX

    if get_header_layout() == HEADER_LAYOUT_STEAM_LIKE:
        # mirror | title band | dock  → middle ≈ content - 2*dock - gaps
        middle = content - 2 * dock - gap - 2 * max(0, spacing)
        half_cap = content // 2 - 40
        return max(80, min(middle, half_cap))

    # Left-aligned: title grows from the left until the dock.
    return max(80, content - dock - gap - max(0, spacing))


def _title_text_budget(app, title: QWidget, cluster_max: int) -> int:
    """Pixels left for ``custom_text_label`` inside the title cluster."""
    if cluster_max <= 0:
        return 0
    row = title.layout()
    spacing = int(row.spacing()) if row is not None else 8
    used = 0
    parts = 0
    for name in ("custom_icon_label", "btn_player_header_info"):
        child = getattr(app, name, None)
        if not _widget_alive(child):
            continue
        if name == "btn_player_header_info" and child.isHidden():
            continue
        ww = _effective_widget_width(child)
        if ww <= 0:
            continue
        used += ww
        parts += 1
    if parts:
        used += spacing * parts  # icon↔text and/or text↔info
    return max(40, cluster_max - used)


def _header_line_plain_width(font: QFont, title: str, meta_plain: str = "") -> int:
    fm = QFontMetrics(font)
    if not meta_plain:
        return int(fm.horizontalAdvance(title or ""))
    # Approximate SteempegUI ``Title  •  meta`` (nbsp bullets → spaces for metrics).
    sep = "  •  "
    return int(fm.horizontalAdvance(f"{title}{sep}{meta_plain}"))


def _meta_plain_for_elide(meta: dict) -> str:
    """Plain meta tail used only for width checks (SteempegUI)."""
    if get_header_layout() == HEADER_LAYOUT_STEAM_LIKE:
        return ""
    date = str(meta.get("date") or "")
    time = str(meta.get("time") or "")
    duration = str(meta.get("duration") or "")
    parts: list[str] = []
    datetime_line = join_clip_date_time(date, time)
    if datetime_line:
        parts.append(datetime_line)
    dur = (duration or "").strip()
    if dur.lower().startswith("time:"):
        dur = dur.split(":", 1)[1].strip()
    if dur and dur not in ("-", "—", "Time: -", "Time:-"):
        parts.append(dur)
    for part in meta.get("extra") or ():
        p = str(part or "").strip()
        if p:
            parts.append(p)
    return _META_SEP.join(parts)


def apply_header_title_elide(app, cluster_max: int) -> None:
    """Elide the game name so icon+text+info never paint under Healthy / Completed.

    Full title stays in ``_player_header_meta`` (Clip info / tooltips). Rich text is
    rebuilt from an elided name; QLabel RichText does not auto-elide.
    """
    label = getattr(app, "custom_text_label", None)
    meta = getattr(app, "_player_header_meta", None)
    title = getattr(app, "player_header_title", None)
    if not _widget_alive(label) or not isinstance(meta, dict) or not _widget_alive(title):
        return
    if cluster_max <= 0:
        return

    budget = _title_text_budget(app, title, cluster_max)
    label.setMinimumWidth(0)
    label.setMaximumWidth(max(40, budget))
    label.setWordWrap(False)

    font_px = player_header_font_px(app)
    font = player_header_title_qfont(font_px)
    label.setFont(font)
    fm = QFontMetrics(font)

    full_title = str(meta.get("title") or "").strip() or "—"
    if meta.get("placeholder"):
        elided = fm.elidedText(full_title, Qt.TextElideMode.ElideRight, budget)
        html = format_player_header_html(elided, font_px=font_px)
        tip = full_title if elided != full_title else ""
    else:
        meta_plain = _meta_plain_for_elide(meta)
        # Binary-search a title width so title (+ optional meta) fits ``budget``.
        lo, hi = 24, max(24, budget)
        best = fm.elidedText(full_title, Qt.TextElideMode.ElideRight, lo)
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = fm.elidedText(full_title, Qt.TextElideMode.ElideRight, mid)
            width = _header_line_plain_width(font, candidate, meta_plain)
            if width <= budget:
                best = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        # If meta alone overflows, drop meta from the painted line (Steam-like
        # never has meta; SteempegUI still keeps facts in Clip info).
        if (
            meta_plain
            and _header_line_plain_width(font, best, meta_plain) > budget
        ):
            best = fm.elidedText(full_title, Qt.TextElideMode.ElideRight, budget)
            html = format_player_header_html(best, font_px=font_px)
        else:
            html = format_player_header_html(
                best,
                date=str(meta.get("date") or ""),
                time=str(meta.get("time") or ""),
                duration=str(meta.get("duration") or ""),
                extra_parts=list(meta.get("extra") or ()),
                font_px=font_px,
            )
        tip = full_title if best != full_title else ""

    key = (html, budget, tip)
    if getattr(app, "_player_header_elide_key", None) != key:
        app._player_header_elide_key = key
        label.setText(html)
        label.setToolTip(tip)


def sync_centered_title_width(app) -> None:
    """Keep the title cluster within the dock-safe band; elide long game names.

    Expanding wing/header spacers previously competed with ``Ignored`` policy and
    ate the title cluster at startup. Prefer ``Preferred`` + a dock-aware cap so
    Healthy / Completed / gear never sit on top of the name or play-info glyph.
    """
    title = getattr(app, "player_header_title", None)
    header = getattr(app, "player_header_frame", None)
    if not _widget_alive(title) or not _widget_alive(header):
        return

    title.setSizePolicy(
        QSizePolicy.Policy.Preferred,
        QSizePolicy.Policy.Preferred,
    )
    title.show()
    for name in ("custom_icon_label", "custom_text_label"):
        child = getattr(app, name, None)
        if _widget_alive(child):
            child.show()
            if name == "custom_text_label":
                child.setMinimumWidth(0)
    # Leave ``btn_player_header_info`` alone — ``refresh_player_header_info``
    # owns show/hide (hidden when no clip is selected).

    hw = int(header.width()) if header.width() > 0 else 0
    if hw <= 0:
        # Pre-show / pre-layout: do not force a zero min — sizeHint must win.
        title.setMaximumWidth(16777215)
        title.setMinimumWidth(0)
        label = getattr(app, "custom_text_label", None)
        if _widget_alive(label):
            label.setMaximumWidth(16777215)
        return

    cap = title_cluster_max_width(app, header)
    title.setMaximumWidth(cap)
    title.setMinimumWidth(0)
    # Soft min so short/placeholder titles are not crushed by Expanding spacers,
    # but never demand more than the dock-safe cap (that caused underlap).
    apply_header_title_elide(app, cap)
    hint = max(0, int(title.sizeHint().width()))
    if hint > 0:
        title.setMinimumWidth(min(hint, cap))


def sync_header_center_mirror(app) -> None:
    """Match dock-mirror width to the right dock so Steam-like center stays put."""
    mirror = getattr(app, "player_header_dock_mirror", None)
    if not _widget_alive(mirror):
        return
    header = getattr(app, "player_header_frame", None)
    if not _widget_alive(header):
        return
    lay = header.layout()
    spacing = int(lay.spacing()) if lay is not None else 10

    if get_header_layout() != HEADER_LAYOUT_STEAM_LIKE:
        if mirror.width() != 0:
            mirror.setFixedWidth(0)
        mirror.hide()
        sync_centered_title_width(app)
        return

    target = measure_right_dock_span(app, spacing)
    mirror.show()
    if mirror.width() != target:
        mirror.setFixedWidth(target)
    sync_centered_title_width(app)


class _HeaderCenterSyncFilter(QObject):
    """Re-sync dock mirror / title elide when status/actions show, hide, or resize."""

    def eventFilter(self, obj, event):  # noqa: N802 — Qt API
        et = event.type()
        if et in (
            QEvent.Type.Show,
            QEvent.Type.Hide,
            QEvent.Type.Resize,
            QEvent.Type.LayoutRequest,
        ):
            app = self.parent()
            if app is None:
                return False
            # Mid-splitter-drag: elide + soft minWidth feedback fights the right
            # handle open→kiss path and twitches the player column (Stage B).
            if bool(getattr(app, "_splitter_dragging", False)):
                return False
            try:
                if get_header_layout() == HEADER_LAYOUT_STEAM_LIKE:
                    sync_header_center_mirror(app)
                else:
                    sync_centered_title_width(app)
            except Exception:
                pass
        return False


def ensure_header_center_sync(app) -> None:
    """Install event filters so dock width changes re-center ``|`` / title."""
    filt = getattr(app, "_player_header_center_sync", None)
    if filt is None:
        filt = _HeaderCenterSyncFilter(app)
        app._player_header_center_sync = filt
    seen: set[int] = getattr(app, "_player_header_center_sync_ids", None) or set()
    app._player_header_center_sync_ids = seen
    targets: list[QWidget] = list(_right_dock_widgets(app))
    for name in (
        "btn_clip_health",
        "label_playback_badge",
        "btn_portable_add_to_queue",
        "btn_portable_in_queue",
        "btn_portable_queue_gear",
        "player_header_frame",
    ):
        child = getattr(app, name, None)
        if _widget_alive(child):
            targets.append(child)
    for w in targets:
        wid = id(w)
        if wid in seen:
            continue
        w.installEventFilter(filt)
        seen.add(wid)


def _portable_pipe_cluster(app) -> tuple[QWidget | None, QWidget | None, QWidget | None]:
    """Return (divider, choose_btn, scan_badge) when the portable ``|`` is in play.

    Use ``isHidden()`` (not ``isVisible()``) so a pre-show startup apply still
    sees Choose a Clip — ``isVisible()`` is false until ancestors are mapped.
    """
    divider = getattr(app, "portable_add_clip_divider", None)
    btn = getattr(app, "btn_portable_add_clip", None)
    badge = getattr(app, "portable_library_scan_badge", None)
    if not _widget_alive(divider) or not _widget_alive(btn):
        return None, None, None
    if divider.isHidden() or btn.isHidden():
        return None, None, None
    if not _widget_alive(badge) or badge.isHidden():
        badge = None
    return divider, btn, badge


def _reparent_into(layout: QHBoxLayout, widget: QWidget, stretch: int = 0) -> None:
    """Move ``widget`` into ``layout`` (safe if already parented elsewhere)."""
    parent_lay = widget.parentWidget().layout() if widget.parentWidget() else None
    if parent_lay is layout:
        # Already here — detach so callers can re-add in the desired order.
        layout.removeWidget(widget)
    elif parent_lay is not None:
        parent_lay.removeWidget(widget)
    layout.addWidget(widget, stretch)


def _clear_box_layout(layout: QHBoxLayout) -> None:
    """Detach all widgets from ``layout`` without deleting them."""
    while layout.count():
        layout.takeAt(0)


def _flatten_wings_to_header(app, header_lay: QHBoxLayout) -> None:
    """If wings were used, pull children back onto the header row."""
    left_wing, right_wing = (
        getattr(app, "player_header_left_wing", None),
        getattr(app, "player_header_right_wing", None),
    )
    for wing in (left_wing, right_wing):
        if not _widget_alive(wing):
            continue
        wing_lay = wing.layout()
        if wing_lay is None:
            continue
        # Collect first — mutating while iterating QLayout is unsafe.
        kids: list[QWidget] = []
        for i in range(wing_lay.count()):
            item = wing_lay.itemAt(i)
            w = item.widget() if item is not None else None
            if w is not None:
                kids.append(w)
        insert_at = header_lay.indexOf(wing)
        if insert_at < 0:
            insert_at = header_lay.count()
        for w in kids:
            wing_lay.removeWidget(w)
            header_lay.insertWidget(insert_at, w)
            insert_at += 1
        header_lay.removeWidget(wing)
        wing.hide()


def apply_player_header_layout(app, layout: object | None = None) -> str:
    """Show/hide header spacers so the title cluster is left or centered.

    Steam-like keeps the optical center fixed at the geometric midpoint of the
    header bar:

    * Portable ``| Choose a Clip``: equal-width wings around the pipe, plus a
      left dock-mirror matching status/actions width so Healthy / gear never
      shove ``|``.
    * Desktop (no Choose a Clip): same mirror + equal stretches around title+i.

    SteempegUI stays left-aligned; the mirror is collapsed.
    """
    mode = set_header_layout(layout if layout is not None else get_header_layout())
    header = getattr(app, "player_header_frame", None)
    title = getattr(app, "player_header_title", None)
    if header is None or title is None:
        return mode
    lay = header.layout()
    if lay is None:
        return mode

    left, right = ensure_header_spacers(app)
    if left is None or right is None:
        return mode
    mirror = ensure_header_right_dock_mirror(app)
    ensure_header_center_sync(app)

    status = getattr(app, "player_header_status", None)
    divider, choose_btn, scan_badge = _portable_pipe_cluster(app)
    centered = mode == HEADER_LAYOUT_STEAM_LIKE
    pipe_center = bool(centered and divider is not None and choose_btn is not None)

    # Right dock always stays at the trailing edge (outside the center group).
    dock_anchor = None
    for w in _right_dock_widgets(app):
        if lay.indexOf(w) >= 0:
            dock_anchor = w
            break
    dock_idx = lay.indexOf(dock_anchor) if dock_anchor is not None else -1

    if pipe_center:
        left_wing, right_wing = ensure_header_center_wings(app)
        if left_wing is None or right_wing is None or mirror is None:
            return mode
        left_wing_lay = left_wing.layout()
        right_wing_lay = right_wing.layout()
        assert isinstance(left_wing_lay, QHBoxLayout)
        assert isinstance(right_wing_lay, QHBoxLayout)

        # Pull prior flat / wing children off the header before rebuilding.
        for w in (
            mirror,
            left,
            title,
            divider,
            choose_btn,
            scan_badge,
            right,
            left_wing,
            right_wing,
        ):
            if w is None or not _widget_alive(w):
                continue
            if lay.indexOf(w) >= 0:
                lay.removeWidget(w)

        _clear_box_layout(left_wing_lay)
        _clear_box_layout(right_wing_lay)

        # Left wing: expanding pad + title hugging the pipe from the left.
        _reparent_into(left_wing_lay, left, stretch=1)
        _reparent_into(left_wing_lay, title, stretch=0)
        # Right wing: Choose a Clip (+ scan badge) hugging pipe, then pad.
        _reparent_into(right_wing_lay, choose_btn, stretch=0)
        if scan_badge is not None:
            _reparent_into(right_wing_lay, scan_badge, stretch=0)
        _reparent_into(right_wing_lay, right, stretch=1)

        left.setVisible(True)
        left.setMaximumWidth(16777215)
        right.setVisible(True)
        right.setMaximumWidth(16777215)
        left_wing.show()
        right_wing.show()
        mirror.show()

        insert_at = dock_idx if dock_idx >= 0 else lay.count()
        # Recompute after removals — dock may have shifted.
        if dock_anchor is not None:
            dock_idx = lay.indexOf(dock_anchor)
            insert_at = dock_idx if dock_idx >= 0 else lay.count()
        lay.insertWidget(insert_at, mirror, 0)
        lay.insertWidget(insert_at + 1, left_wing, 1)
        lay.insertWidget(insert_at + 2, divider, 0)
        lay.insertWidget(insert_at + 3, right_wing, 1)
        divider.show()
        choose_btn.show()
        title.show()
        sync_header_center_mirror(app)
    else:
        # Flat header row — unwrap wings if a prior Steam-like portable pass used them.
        _flatten_wings_to_header(app, lay)

        title_idx = lay.indexOf(title)
        if title_idx < 0:
            # Title was orphaned off the header row — park it before the dock.
            insert_at = dock_idx if dock_idx >= 0 else lay.count()
            lay.insertWidget(insert_at, title)
            title_idx = lay.indexOf(title)
            if title_idx < 0:
                return mode

        # Ensure mirror sits at the far left of the center group when Steam-like.
        if mirror is not None:
            mir_idx = lay.indexOf(mirror)
            if centered:
                if mir_idx < 0:
                    lay.insertWidget(0, mirror, 0)
                elif mir_idx != 0:
                    lay.removeWidget(mirror)
                    lay.insertWidget(0, mirror, 0)
                mirror.show()
            else:
                if mir_idx >= 0:
                    lay.removeWidget(mirror)
                mirror.hide()
                mirror.setFixedWidth(0)

        left_idx = lay.indexOf(left)
        title_idx = lay.indexOf(title)
        if left_idx < 0:
            lay.insertWidget(title_idx, left)
        elif left_idx != title_idx - 1:
            lay.removeWidget(left)
            title_idx = lay.indexOf(title)
            lay.insertWidget(max(0, title_idx), left)

        # Keep portable ``| Choose a Clip`` immediately after the title cluster.
        if divider is not None and choose_btn is not None:
            title_idx = lay.indexOf(title)
            for w in (divider, choose_btn, scan_badge):
                if w is None or not _widget_alive(w):
                    continue
                cur = lay.indexOf(w)
                if cur >= 0:
                    lay.removeWidget(w)
            title_idx = lay.indexOf(title)
            at = title_idx + 1
            lay.insertWidget(at, divider)
            lay.insertWidget(at + 1, choose_btn)
            divider.show()
            choose_btn.show()
            if scan_badge is not None:
                lay.insertWidget(at + 2, scan_badge)

        # Right expanding spacer sits just before the status dock.
        status_idx = lay.indexOf(status) if status is not None else -1
        right_idx = lay.indexOf(right)
        if status_idx >= 0:
            if right_idx < 0:
                lay.insertWidget(status_idx, right)
            elif right_idx != status_idx - 1:
                lay.removeWidget(right)
                status_idx = lay.indexOf(status)
                lay.insertWidget(max(0, status_idx), right)
        elif right_idx < 0:
            lay.insertWidget(lay.indexOf(title) + 1, right)

        left.setVisible(centered)
        left.setMaximumWidth(16777215 if centered else 0)
        right.setVisible(True)
        right.setMaximumWidth(16777215)
        if centered:
            sync_header_center_mirror(app)

    label = getattr(app, "custom_text_label", None)
    if label is not None:
        if pipe_center:
            # Title hugs ``|`` from the left — right-align glyphs in the wing.
            align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        elif centered:
            align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
        else:
            align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        label.setAlignment(align)

    # Never use Ignored: Expanding spacers would collapse icon+name to width 0.
    sync_centered_title_width(app)
    return mode


def refresh_player_header_text(app) -> None:
    """Re-render ``custom_text_label`` from the last stored meta (layout switch)."""
    meta = getattr(app, "_player_header_meta", None)
    label = getattr(app, "custom_text_label", None)
    if not meta or label is None:
        return
    font_px = player_header_font_px(app)
    label.setFont(player_header_title_qfont(font_px))
    # Clear elide cache so dock-safe pass rewrites for the new layout/font.
    app._player_header_elide_key = None
    if meta.get("placeholder"):
        # Same rich-text + family pin as a filled title (plain text diverged).
        label.setText(
            format_player_header_html(
                str(meta.get("title") or "Select a clip to preview..."),
                font_px=font_px,
            )
        )
    else:
        label.setText(
            format_player_header_html(
                str(meta.get("title") or ""),
                date=str(meta.get("date") or ""),
                time=str(meta.get("time") or ""),
                duration=str(meta.get("duration") or ""),
                extra_parts=list(meta.get("extra") or ()),
                font_px=font_px,
            )
        )
    sync_centered_title_width(app)


def store_player_header_meta(
    app,
    *,
    title: str,
    date: str = "",
    time: str = "",
    duration: str = "",
    extra: list[str] | tuple[str, ...] | None = None,
    placeholder: bool = False,
) -> None:
    app._player_header_meta = {
        "title": title,
        "date": date or "",
        "time": time or "",
        "duration": duration or "",
        "extra": list(extra or ()),
        "placeholder": bool(placeholder),
    }


def set_player_header_game_text(
    app,
    title: str,
    *,
    date: str = "",
    time: str = "",
    duration: str = "",
    extra: list[str] | tuple[str, ...] | None = None,
    placeholder: bool = False,
) -> None:
    """Store meta, paint the label, and refresh the Clip info chip."""
    store_player_header_meta(
        app,
        title=title,
        date=date,
        time=time,
        duration=duration,
        extra=extra,
        placeholder=placeholder,
    )
    label = getattr(app, "custom_text_label", None)
    if label is None:
        return
    font_px = player_header_font_px(app)
    label.setFont(player_header_title_qfont(font_px))
    app._player_header_elide_key = None
    if placeholder:
        label.setText(format_player_header_html(title, font_px=font_px))
    else:
        label.setText(
            format_player_header_html(
                title,
                date=date,
                time=time,
                duration=duration,
                extra_parts=extra,
                font_px=font_px,
            )
        )
    # Show/hide Clip info before measuring — it steals width from the name.
    if hasattr(app, "refresh_player_header_info"):
        try:
            app.refresh_player_header_info()
        except Exception:
            pass
    sync_centered_title_width(app)


def apply_player_header_density(app, dense: UiDensity | None = None) -> None:
    """Scale player-header chrome (icon, title, chips, pad) with UI density.

    Comfort Large matches the classic fixed strip (icon 24 / font 13 / pads
    10×8 / chip 30). Settings → Visual Size (S/M/L) scales those metrics on
    top of window density. Empty placeholder uses the same ``setFixedHeight``
    as a filled clip so the bar does not jump thinner when no clip is selected.
    """
    if dense is None:
        dense = player_header_density(app)
    else:
        # Callers pass raw window density — still apply the S/M/L size pref.
        try:
            from steempeg.ui.player_header_size import apply_header_size_to_density

            dense = apply_header_size_to_density(dense)
        except Exception:
            pass
    header = getattr(app, "player_header_frame", None)
    if not _widget_alive(header):
        return

    pad_h = max(6, int(dense.header_pad_h))
    pad_v = max(4, int(dense.header_pad_v))
    icon_px = max(16, int(dense.header_icon))
    font_px = max(11, int(dense.header_font))
    chip = max(24, int(dense.header_chip))
    chip_icon = max(12, int(dense.header_chip_icon))
    # Always the filled-state height (icon/chips + pads). Empty placeholder must
    # not shrink when status/actions/info are hidden — Fixed sizeHint otherwise
    # collapses to icon+label only and looks thinner than a selected clip.
    from steempeg.ui.layout_defaults import (
        PLAYER_HEADER_CANVAS_GAP,
        PLAYER_HEADER_FRAME_BORDER_V,
    )

    min_h = max(chip + 2 * pad_v, int(dense.header_min_h), icon_px + 2 * pad_v)
    content_h = max(icon_px, chip)

    lay = header.layout()
    if lay is not None:
        lay.setContentsMargins(pad_h, pad_v, pad_h, pad_v + PLAYER_HEADER_CANVAS_GAP)
        lay.setSpacing(max(6, pad_h))

    header.setFixedHeight(
        min_h + PLAYER_HEADER_CANVAS_GAP + int(PLAYER_HEADER_FRAME_BORDER_V)
    )
    header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    title = getattr(app, "player_header_title", None)
    if _widget_alive(title):
        title.setMinimumHeight(content_h)

    label = getattr(app, "custom_text_label", None)
    if _widget_alive(label):
        # QFont pins the document default; stylesheet backs non-rich fallbacks.
        label.setFont(player_header_title_qfont(font_px))
        label.setStyleSheet(
            f"color: white; font-size: {font_px}px; {_header_title_font_css()}"
            "background: transparent; border: none;"
        )

    # Reshape the live game / unknown icon to the density box.
    icon_lbl = getattr(app, "custom_icon_label", None)
    if _widget_alive(icon_lbl):
        try:
            from PySide6.QtGui import QPixmap

            from steempeg.infra.paths import get_resource_path
            from steempeg.ui.icon_shape import ICON_SHAPE_CIRCLE, shaped_game_icon_pixmap
            from steempeg.ui.icon_utils import apply_square_icon

            path = ""
            if hasattr(app, "_resolve_header_game_icon_path"):
                try:
                    path = app._resolve_header_game_icon_path() or ""
                except Exception:
                    path = ""
            if not path:
                path = getattr(app, "current_game_icon", "") or ""
            unknown = get_resource_path("unknown_icon.png")
            if not path or not os.path.isfile(path):
                path = unknown
            is_unknown = (
                os.path.basename(path).lower() == "unknown_icon.png" if path else True
            )
            src = QPixmap(path) if path else QPixmap()
            shape = ICON_SHAPE_CIRCLE if is_unknown else None
            shaped = (
                shaped_game_icon_pixmap(src, icon_px, shape)
                if not src.isNull()
                else None
            )
            icon_lbl.setStyleSheet("background: transparent; border: none;")
            apply_square_icon(icon_lbl, shaped, icon_px)
        except Exception:
            pass

    # Clip-info hitbox — classic comfort was 22×22 with a 16px glyph.
    info = getattr(app, "btn_player_header_info", None)
    if _widget_alive(info):
        from steempeg.ui.design_tokens import with_tooltip_style
        from steempeg.ui.icon_assets import playinfo_icons

        hit = max(18, chip - 8)
        glyph = max(12, min(chip_icon, hit - 4))
        idle, hot = playinfo_icons(glyph)
        app._player_header_info_icon_idle = idle
        app._player_header_info_icon_hot = hot
        info.setFixedSize(hit, hit)
        info.setIcon(idle if not info.underMouse() else hot)
        info.setIconSize(QSize(glyph, glyph))
        r = hit // 2
        info.setStyleSheet(
            with_tooltip_style(
                "QPushButton#playerHeaderInfo {"
                "background: transparent; border: none; padding: 0px; margin: 0px;"
                "text-align: center;}"
                "QPushButton#playerHeaderInfo:hover {"
                f"background-color: rgba(255, 255, 255, 0.08); border-radius: {r}px;}}"
                "QPushButton#playerHeaderInfo:pressed {"
                f"background-color: rgba(255, 255, 255, 0.12); border-radius: {r}px;}}"
                "QPushButton#playerHeaderInfo:disabled { background-color: transparent; }"
            )
        )

    from steempeg.ui.icon_assets import close_clip_icon, preview_settings_icon

    chip_qss_tail = (
        f"border-radius: 8px; padding: 0px; {_header_chip_font_css()}"
    )
    preview = getattr(app, "btn_preview_settings", None)
    if _widget_alive(preview):
        preview.setFixedSize(chip, chip)
        preview.setIcon(preview_settings_icon(chip_icon))
        preview.setIconSize(QSize(chip_icon, chip_icon))
        preview.setStyleSheet(
            "QPushButton {"
            "background-color: rgba(74, 159, 216, 0.18); color: #4a9fd8;"
            "border: 2px solid #4a9fd8;"
            + chip_qss_tail
            + "}"
            "QPushButton:hover { background-color: rgba(74, 159, 216, 0.32); }"
            "QPushButton:pressed { background-color: rgba(74, 159, 216, 0.45); }"
        )
    close_btn = getattr(app, "btn_close_clip", None)
    if _widget_alive(close_btn):
        close_btn.setFixedSize(chip, chip)
        close_btn.setIcon(close_clip_icon(chip_icon))
        close_btn.setIconSize(QSize(chip_icon, chip_icon))
        close_btn.setStyleSheet(
            "QPushButton {"
            "background-color: rgba(224, 85, 85, 0.18); color: #e05555;"
            "border: 2px solid #e05555;"
            + chip_qss_tail
            + "}"
            "QPushButton:hover { background-color: rgba(224, 85, 85, 0.32); }"
            "QPushButton:pressed { background-color: rgba(224, 85, 85, 0.45); }"
        )

    divider = getattr(app, "player_header_divider", None)
    if _widget_alive(divider):
        divider.setFixedHeight(max(18, chip - 8))

    # Portable "| Choose a Clip" cluster — keep chip height with the header.
    choose = getattr(app, "btn_portable_add_clip", None)
    if _widget_alive(choose) and hasattr(choose, "setFixedHeight"):
        choose.setFixedHeight(chip)
        choose.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    pipe = getattr(app, "portable_add_clip_divider", None)
    if _widget_alive(pipe) and hasattr(pipe, "setFixedHeight"):
        pipe.setFixedHeight(max(18, chip - 8))

    # + Queue / In queue — Fixed height only (content width; no reserved slot).
    for name in ("btn_portable_add_to_queue", "btn_portable_in_queue"):
        qbtn = getattr(app, name, None)
        if _widget_alive(qbtn):
            qbtn.setFixedHeight(chip)
            qbtn.setMinimumWidth(0)
            qbtn.setMaximumWidth(16777215)
            qbtn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    status_host = getattr(app, "player_header_status", None)
    if _widget_alive(status_host):
        status_host.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )

    # Status chips (Healthy / Preview) pick up pad + min height on next refresh;
    # store so callers can read without importing density.
    app._player_header_status_pad = str(dense.header_status_pad)
    app._player_header_status_min_h = chip
    app._player_header_status_font = font_px
    app._player_header_status_icon = max(14, chip_icon)

    refresh_player_header_text(app)
    if hasattr(app, "update_clip_health_button"):
        try:
            app.update_clip_health_button()
        except Exception:
            pass
    if hasattr(app, "update_playback_badge"):
        try:
            app.update_playback_badge()
        except Exception:
            pass
    sync_centered_title_width(app)
