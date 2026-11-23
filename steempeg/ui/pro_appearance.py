"""The optional PRO accents and icon variants shared by the desktop UI."""
from __future__ import annotations

import os
import re
from functools import lru_cache
from weakref import WeakKeyDictionary, WeakSet

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QWidget

from steempeg.infra.paths import get_resource_path

KEY_PRO_RED_ACCENTS = "pro_red_accents"
KEY_PRO_RED_LOGO = "pro_red_logo"
KEY_PRO_ACCENT_COLOR = "pro_accent_color"
DEFAULT_PRO_ACCENT = "#d64545"
ACTIVE_RENDER_COLOR = "#d64545"
ERROR_RENDER_COLOR = "#a0364c"

# Map the existing brand colors, leaving semantic colors (trim, errors,
# success, warnings) out of the palette.
_ACCENT_TONES = {
    "#b29ae7": "#f3919a",
    "#6b5a8e": "#a04b53",
    "#8e7cc3": "#cc6672",
    "#5a4b7a": "#833943",
    "#5c4d7a": "#873a45",
    "#6e5c91": "#a44e59",
    "#7a6aa8": "#ad5663",
    "#4a3d66": "#632f39",
    "#5a4d76": "#773c47",
    "#3a324a": "#49252e",
    "#2a2438": "#371b22",
    "#a871ff": "#ef7887",
    "#c4b5e8": "#ffc0c6",
    "#d4c8f5": "#ffd1d6",
    "#d4c4ff": "#ffccd2",
    "#d4c4f5": "#ffced4",
    "#f0ecff": "#fff0f2",
    "#bda4f0": "#faa3ac",
    "#9f8dba": "#c47c87",
    "#a493bd": "#c1848b",
    "#8b74c4": "#c35c6a",
    "#4a4560": "#613841",
    "#3a3350": "#4c2630",
    "#322a45": "#45232d",
    "#292236": "#351c24",
    "#5138e6": "#bd424f",
    "#6b5cff": "#de5565",
    "#1a1228": "#2b1317",
    "#322b45": "#42232c",
    "#262229": "#2d2124",
    "#3d2a68": "#632736",
    "#a08abb": "#c27d88",
    "#d3c2fc": "#ffd0d7",
    "#bfa5f4": "#ffa5af",
    "#cdbfe6": "#eec1ca",
    "#c4b6e4": "#eab0bb",
    "#c8b8e8": "#f4b6c1",
    "#d8d4ff": "#ffdadf",
    "#e4dcf3": "#f8e0e5",
    "#2a2240": "#3c1b24",
    "#3a2e54": "#4e2631",
    "#8b3db8": "#ab3f53",
    "#2c2836": "#35262c",
    "#2e2a38": "#38272e",
    "#1b1821": "#25191d",
}
_CSS_ACCENT = re.compile(
    rf"(?P<hex>(?<![\w/])(?:{'|'.join(_ACCENT_TONES)})(?![\w.]))"
    r"|(?P<rgba>rgba?\(\s*(?:178,\s*154,\s*231|142,\s*124,\s*195|81,\s*56,\s*230)(?=\s*[,)]))",
    re.IGNORECASE,
)
_LOGOS = {"logo.png": "logo_pro.png", "logo.ico": "logo_pro.ico"}
_PLAYER_ICONS = {
    "icon_play.png": "icon_play_pro.png",
    "icon_pause.png": "icon_pause_pro.png",
    "less15.png": "less15_pro.png",
    "more15.png": "more15_pro.png",
}
_interface_color: str | None = None
_logo_color: str | None = None


def normalize_pro_accent(value: object) -> str:
    text = str(value or "").lower()
    return text if re.fullmatch(r"#[0-9a-f]{6}", text) else DEFAULT_PRO_ACCENT


@lru_cache(maxsize=1)
def _palette_for_color(color: str) -> dict[str, str]:
    # Use the established relative light/dark tones around the chosen swatch.
    # Deliberately keep the primary accent itself equal to the chosen color.
    anchor = QColor(_ACCENT_TONES["#b29ae7"]).lightnessF()
    base = QColor(color)
    rgb = (base.red(), base.green(), base.blue())
    palette = {}
    for original, sample in _ACCENT_TONES.items():
        lightness = QColor(sample).lightnessF()
        if lightness < anchor:
            target = tuple(round(channel * lightness / anchor) for channel in rgb)
        else:
            mix = (lightness - anchor) / (1.0 - anchor)
            target = tuple(round(channel + (255 - channel) * mix) for channel in rgb)
        palette[original] = QColor(*target).name()
    return palette


def pro_accents_enabled() -> bool:
    return _interface_color is not None


def accent_color(color: str) -> str:
    """Resolve an existing accent for a custom-painted widget."""
    if _interface_color is None:
        return color
    return _palette_for_color(_interface_color).get(color.lower(), color)


def accent_qcolor(color: QColor) -> QColor:
    if _interface_color is None:
        return color
    source = color.name()
    target = accent_color(source)
    if target == source:
        return color
    result = QColor(target)
    result.setAlpha(color.alpha())
    return result


def _qss_accent(match: re.Match) -> str:
    if match["hex"]:
        return accent_color(match["hex"])
    prefix, rgb = match["rgba"].split("(", 1)
    color = accent_qcolor(QColor(*(int(channel) for channel in rgb.split(","))))
    return f"{prefix}({color.red()}, {color.green()}, {color.blue()}"


def render_status_color(status, fallback: str = "#ffcc00") -> str:
    from steempeg.render.queue import JobStatus, STATUS_COLORS

    if pro_accents_enabled():
        if status == JobStatus.RENDERING:
            return ACTIVE_RENDER_COLOR
        if status == JobStatus.ERROR:
            return ERROR_RENDER_COLOR
    return STATUS_COLORS.get(status, fallback)


def themed_asset_path(name: str) -> str:
    base_name = "icon_play_aligned.png" if name == "icon_play.png" else name
    source = get_resource_path(base_name)
    if not os.path.isfile(source):
        source = get_resource_path(name)
    variant = _LOGOS.get(name) or _PLAYER_ICONS.get(name)
    color = _logo_color if name in _LOGOS else _interface_color
    if variant and color and color != DEFAULT_PRO_ACCENT:
        from steempeg.ui.pro_artwork import tinted_asset_path

        try:
            return tinted_asset_path(source, color)
        except OSError:
            return source
    if variant and color:
        path = get_resource_path(variant)
        if os.path.isfile(path):
            return path
    return source


class _AccentStyles(QObject):
    """Recolor local QSS, including styles set later by lazily opened windows."""

    def __init__(self, app: QApplication):
        super().__init__(app)
        self._app = app
        self._originals = WeakKeyDictionary()
        self._pending = WeakSet()
        self._timer = QTimer(self, singleShot=True, interval=0)
        self._timer.timeout.connect(self._flush)

    def enable(self) -> None:
        self._app.installEventFilter(self)
        for widget in self._app.allWidgets():
            self._apply(widget)

    def disable(self) -> None:
        self._app.removeEventFilter(self)
        self._timer.stop()
        self._pending.clear()
        for widget, (original, painted) in list(self._originals.items()):
            try:
                style = widget.styleSheet()
                if painted in style:
                    widget.setStyleSheet(style.replace(painted, original, 1))
            except RuntimeError:
                continue
        self._originals.clear()

    def refresh(self) -> None:
        for widget, (original, _) in list(self._originals.items()):
            self._apply(widget, original, force=True)

    def eventFilter(self, widget, event):  # noqa: N802
        if event.type() == QEvent.Type.StyleChange and isinstance(widget, QWidget):
            style = widget.styleSheet()
            previous = self._originals.get(widget)
            if previous and style == previous[1]:
                return False
            if previous or _CSS_ACCENT.search(style):
                self._pending.add(widget)
                if not self._timer.isActive():
                    self._timer.start()
        return False

    def _flush(self) -> None:
        widgets = list(self._pending)
        self._pending.clear()
        for widget in widgets:
            self._apply(widget)

    def _apply(self, widget: QWidget, source: str | None = None, *, force: bool = False) -> None:
        try:
            current = widget.styleSheet()
            style = current if source is None else source
            previous = self._originals.get(widget)
            if previous:
                original, painted = previous
                if not force and current == painted and style in (original, painted):
                    return
                # Some widgets extend their current stylesheet in place.
                style = style.replace(painted, original, 1)
            painted = _CSS_ACCENT.sub(_qss_accent, style)
            if painted == style and not _CSS_ACCENT.search(style):
                self._originals.pop(widget, None)
            else:
                self._originals[widget] = style, painted
            if current != painted:
                widget.setStyleSheet(painted)
        except RuntimeError:
            pass


def set_accent_stylesheet(widget: QWidget, stylesheet: str) -> None:
    """Apply a theme stylesheet in one polish pass, including the PRO accent."""
    styler = (
        getattr(QApplication.instance(), "_steempeg_accent_styles", None)
        if pro_accents_enabled() else None
    )
    if styler is not None:
        styler._apply(widget, stylesheet)
    elif widget.styleSheet() != stylesheet:
        widget.setStyleSheet(stylesheet)


def apply_pro_appearance(enabled: bool, settings: dict) -> tuple[bool, bool]:
    """Apply the two independent PRO appearance preferences."""
    global _interface_color, _logo_color
    color = normalize_pro_accent(settings.get(KEY_PRO_ACCENT_COLOR))
    accents = color if enabled and settings.get(KEY_PRO_RED_ACCENTS, True) else None
    logo = color if enabled and settings.get(KEY_PRO_RED_LOGO, True) else None
    old_accents = _interface_color
    changed = (accents != old_accents, logo != _logo_color)
    app = QApplication.instance()
    styler = getattr(app, "_steempeg_accent_styles", None)
    if changed[0] and old_accents and styler is not None:
        styler._flush()
    _interface_color, _logo_color = accents, logo
    if app is not None and changed[0]:
        if styler is None:
            styler = app._steempeg_accent_styles = _AccentStyles(app)
        if accents and old_accents:
            styler.refresh()
        elif accents:
            styler.enable()
        else:
            styler.disable()
        for window in app.topLevelWidgets():
            window.update()
            for child in window.findChildren(QWidget):
                if child.isVisible():
                    child.update()
    return changed
