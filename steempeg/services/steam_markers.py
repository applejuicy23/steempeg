"""Steam Game Recording timeline marker icons.

Steam stores one ``markers.svg`` sprite per game: an SVG whose ``<defs>`` holds
``<g id="cs2_death">`` style icons. It lives under
``<Steam>/appcache/librarycache/<app_id>/<hash>/markers.svg`` (downloaded from the
Steam CDN, then served locally via steamloopback.host inside the client).

This module locates that cached sprite by app_id and renders any icon by its id to
a QPixmap, caching both the per-game renderer and the per-icon pixmaps. Mirrors the
approach proven in the standalone svgunl.py extractor: load the whole sprite into one
QSvgRenderer, then ``render(painter, icon_id)`` to slice a single icon out.
"""
import glob
import os
import re

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


from steempeg.core.steam_paths import get_steam_path


def find_markers_svg(app_id, steam_path=None):
    """Path to the markers.svg Steam cached for a game, or None.

    The hash subfolder is unknown ahead of time, so we wildcard it:
    ``appcache/librarycache/<app_id>/*/markers.svg``.
    """
    base = os.path.join(steam_path or get_steam_path(), "appcache", "librarycache", str(app_id))
    hits = glob.glob(os.path.join(base, "*", "markers.svg"))
    return hits[0] if hits else None


def _whiten(raw_svg):
    """Recolor fills/strokes to white (keeps fill='none' holes), like the Steam mono style.

    Note: only touches attribute-form colors (fill="..."/stroke="...") and currentColor,
    matching svgunl.py. Colors written inside style="fill:..." are left as-is.
    """
    svg = raw_svg.replace("currentColor", "#ffffff")
    svg = re.sub(r'fill="(?!none)[^"]+"', 'fill="#ffffff"', svg)
    svg = re.sub(r'stroke="(?!none)[^"]+"', 'stroke="#ffffff"', svg)
    return svg


class MarkerIconStore:
    """Renders Steam timeline marker icons (by id) from each game's cached markers.svg.

    One QSvgRenderer per app_id (the whole sprite); pixmaps cached per
    (app_id, icon_id, size). Unknown games / missing icons return None so the caller
    can fall back to a placeholder.
    """

    def __init__(self, whiten=True):
        self._whiten = whiten
        self._renderers = {}   # app_id -> QSvgRenderer | None  (None = looked, not found)
        self._pixmaps = {}     # (app_id, icon_id, size) -> QPixmap | None

    def _renderer_for(self, app_id):
        if app_id in self._renderers:
            return self._renderers[app_id]

        renderer = None
        path = find_markers_svg(app_id)
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = f.read()
                if self._whiten:
                    raw = _whiten(raw)
                candidate = QSvgRenderer()
                if candidate.load(QByteArray(raw.encode("utf-8"))):
                    renderer = candidate
            except Exception:
                renderer = None

        self._renderers[app_id] = renderer
        return renderer

    def has_icon(self, app_id, icon_id):
        renderer = self._renderer_for(app_id)
        return renderer is not None and renderer.elementExists(icon_id)

    def get_icon(self, app_id, icon_id, size=36):
        """QPixmap for icon_id from app_id's sprite, or None if unavailable."""
        key = (app_id, icon_id, size)
        if key in self._pixmaps:
            return self._pixmaps[key]

        renderer = self._renderer_for(app_id)
        pixmap = None
        if renderer is not None and renderer.elementExists(icon_id):
            pm = QPixmap(size, size)
            pm.fill(Qt.transparent)
            painter = QPainter(pm)
            painter.setRenderHint(QPainter.Antialiasing)
            renderer.render(painter, icon_id)
            painter.end()
            pixmap = pm

        self._pixmaps[key] = pixmap
        return pixmap

    def clear(self):
        self._renderers.clear()
        self._pixmaps.clear()