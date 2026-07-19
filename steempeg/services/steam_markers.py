"""Steam Game Recording timeline marker icons.

Steam stores one ``markers.svg`` sprite per game: an SVG whose ``<defs>`` holds
``<g id="cs2_death">`` style icons. Sources (in priority order):

1. ``<Steam>/appcache/librarycache/<app_id>/*/markers.svg`` (Steam client cache)
2. ``<save>/cache/markers/<app_id>/markers.svg`` (Steempeg cache)
3. Steam CDN — ``shared.fastly.steamstatic.com/app_config/timeline/<app_id>/<hash>/markers.svg``
   where ``<hash>`` comes from ``timeline_marker_svg`` in app metadata (steamcmd API).

Inside the Steam client the same file is served via ``steamloopback.host/assets/...``.

Renders icons with one QSvgRenderer per game, then ``render(painter, icon_id)`` per marker.
"""
import glob
import json
import logging
import os
import re
import threading

import requests

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from steempeg.core.steam_paths import get_steam_path
from steempeg.infra.paths import get_save_directory

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
}
_STEAMCMD_INFO_URL = "https://api.steamcmd.net/v1/info/{app_id}"
_MARKERS_CDN_BASE = "https://shared.fastly.steamstatic.com/app_config/timeline"
_APP_ID_FROM_PATH_RE = re.compile(r"(?:timeline|clip|fg|bg)_(\d+)_", re.IGNORECASE)


def app_id_from_clip_paths(json_path=None, clip_path=None):
    """Extract Steam app id from standard Game Recording path/name tokens."""
    for raw in (json_path, clip_path):
        if not raw:
            continue
        m = _APP_ID_FROM_PATH_RE.search(str(raw).replace("\\", "/"))
        if m:
            return m.group(1)
    return None


def find_markers_svg(app_id, steam_path=None):
    """Path to the markers.svg Steam cached for a game, or None.

    The hash subfolder is unknown ahead of time, so we wildcard it:
    ``appcache/librarycache/<app_id>/*/markers.svg``.
    """
    base = os.path.join(steam_path or get_steam_path(), "appcache", "librarycache", str(app_id))
    hits = glob.glob(os.path.join(base, "*", "markers.svg"))
    return hits[0] if hits else None


def _markers_cache_dir(cache_dir, app_id):
    return os.path.join(cache_dir, "markers", str(app_id))


def steempeg_markers_path(cache_dir, app_id):
    """Cached markers.svg path under the Steempeg cache directory."""
    return os.path.join(_markers_cache_dir(cache_dir, app_id), "markers.svg")


def _markers_meta_path(cache_dir, app_id):
    return os.path.join(_markers_cache_dir(cache_dir, app_id), "meta.json")


def fetch_markers_cdn_info(app_id, timeout=20):
    """Resolve CDN URL and version stamp for a game's timeline marker sprite.

    Returns ``{"url": str, "urls": list[str], "timeline_marker_updated": ...}`` or None.
    """
    app_id = str(app_id)
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.get(
                _STEAMCMD_INFO_URL.format(app_id=app_id),
                headers=_BROWSER_HEADERS,
                timeout=timeout,
            )
            if not resp.ok:
                last_err = f"HTTP {resp.status_code}"
                continue
            payload = resp.json()
            common = payload.get("data", {}).get(app_id, {}).get("common", {})
            rel = common.get("timeline_marker_svg")
            if not rel:
                logging.info(
                    "No timeline_marker_svg in steamcmd metadata for app %s", app_id
                )
                return None
            rel = str(rel).lstrip("/")
            if not rel.endswith("markers.svg"):
                rel = f"{rel.rstrip('/')}/markers.svg"
            urls = [
                f"https://cdn.cloudflare.steamstatic.com/app_config/timeline/{app_id}/{rel}",
                f"{_MARKERS_CDN_BASE}/{app_id}/{rel}",
                f"https://shared.akamai.steamstatic.com/app_config/timeline/{app_id}/{rel}",
            ]
            return {
                "url": urls[0],
                "urls": urls,
                "timeline_marker_updated": common.get("timeline_marker_updated"),
            }
        except (requests.RequestException, ValueError, TypeError) as exc:
            last_err = exc
            logging.warning(
                "steamcmd markers meta attempt %s failed for app %s: %s",
                attempt + 1,
                app_id,
                exc,
            )
    logging.warning("Could not resolve markers CDN info for app %s (%s)", app_id, last_err)
    return None


def _read_markers_meta(cache_dir, app_id):
    path = _markers_meta_path(cache_dir, app_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_markers_meta(cache_dir, app_id, info):
    folder = _markers_cache_dir(cache_dir, app_id)
    os.makedirs(folder, exist_ok=True)
    path = _markers_meta_path(cache_dir, app_id)
    payload = {
        "url": info.get("url", ""),
        "timeline_marker_updated": info.get("timeline_marker_updated"),
    }
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    except OSError as exc:
        logging.debug("Could not write markers meta for app %s: %s", app_id, exc)


def download_markers_svg(app_id, dest_path, info=None, cache_dir=None, timeout=20):
    """Download markers.svg from the Steam CDN. Returns True on success."""
    app_id = str(app_id)
    info = info or fetch_markers_cdn_info(app_id, timeout=timeout)
    if not info or not info.get("url"):
        return False
    if cache_dir is None:
        cache_dir = os.path.dirname(os.path.dirname(os.path.dirname(dest_path)))
    urls = list(info.get("urls") or [info["url"]])
    last_err = None
    for url in urls:
        try:
            resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=timeout)
            if not resp.ok or not resp.content:
                last_err = f"{url} -> HTTP {getattr(resp, 'status_code', '?')}"
                continue
            head = resp.content[:800].lower()
            if b"<svg" not in head and b"<svg" not in resp.content.lower():
                last_err = f"{url} -> not svg ({len(resp.content)} bytes)"
                continue
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, "wb") as handle:
                handle.write(resp.content)
            _write_markers_meta(cache_dir, app_id, {**info, "url": url})
            logging.info("Downloaded timeline markers for app %s from %s", app_id, url)
            return True
        except (requests.RequestException, OSError) as exc:
            last_err = exc
            logging.warning("Markers CDN download failed for app %s: %s", app_id, exc)
    logging.warning("All markers CDN mirrors failed for app %s (%s)", app_id, last_err)
    return False


def _steempeg_cache_is_fresh(cache_dir, app_id, info):
    path = steempeg_markers_path(cache_dir, app_id)
    if not os.path.isfile(path):
        return False
    if not info:
        return True
    meta = _read_markers_meta(cache_dir, app_id)
    if not meta:
        return True
    remote_ver = info.get("timeline_marker_updated")
    if remote_ver is None:
        return True
    return str(meta.get("timeline_marker_updated")) == str(remote_ver)


def resolve_markers_svg_path_local(app_id, cache_dir=None, steam_path=None):
    """Disk-only lookup: Steam librarycache, then Steempeg cache. No network."""
    app_id = str(app_id)
    steam_hit = find_markers_svg(app_id, steam_path=steam_path)
    if steam_hit:
        return steam_hit
    if cache_dir is None:
        cache_dir = os.path.join(get_save_directory(), "cache")
    cached = steempeg_markers_path(cache_dir, app_id)
    if os.path.isfile(cached):
        return cached
    return None


def resolve_markers_svg_path(app_id, cache_dir=None, steam_path=None):
    """Best available markers.svg path for ``app_id``, or None.

    Order: Steam install cache → Steempeg cache (if fresh) → CDN download.
    """
    app_id = str(app_id)
    steam_hit = find_markers_svg(app_id, steam_path=steam_path)
    if steam_hit:
        return steam_hit

    if cache_dir is None:
        cache_dir = os.path.join(get_save_directory(), "cache")

    cdn_info = fetch_markers_cdn_info(app_id)
    cached = steempeg_markers_path(cache_dir, app_id)
    if _steempeg_cache_is_fresh(cache_dir, app_id, cdn_info) and os.path.isfile(cached):
        return cached

    if cdn_info and download_markers_svg(app_id, cached, info=cdn_info, cache_dir=cache_dir):
        return cached

    if os.path.isfile(cached):
        logging.debug("Using stale Steempeg markers cache for app %s (CDN unavailable)", app_id)
        return cached

    return None


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
    """Renders Steam timeline marker icons (by id) from each game's markers.svg.

    One QSvgRenderer per app_id (the whole sprite); pixmaps cached per
    (app_id, icon_id, size). Unknown games / missing icons return None so the caller
    can fall back to a placeholder.
    """

    def __init__(self, whiten=True, cache_dir=None):
        self._whiten = whiten
        self._cache_dir = cache_dir
        self._renderers = {}   # app_id -> QSvgRenderer | None  (None = looked, not found)
        self._pixmaps = {}     # (app_id, icon_id, size) -> QPixmap | None
        self._pending_fetch = set()

    def set_cache_dir(self, cache_dir):
        self._cache_dir = cache_dir
        self.clear()

    def _cache_dir_resolved(self):
        return self._cache_dir or os.path.join(get_save_directory(), "cache")

    def prefetch(self, app_id, on_ready=None):
        """Download markers.svg off the UI thread when not already on disk."""
        app_id = str(app_id)
        if app_id in self._pending_fetch:
            return
        if resolve_markers_svg_path_local(app_id, cache_dir=self._cache_dir):
            self._renderers.pop(app_id, None)
            if on_ready:
                on_ready()
            return

        self._pending_fetch.add(app_id)
        cache_dir = self._cache_dir_resolved()

        def work():
            try:
                path = resolve_markers_svg_path(app_id, cache_dir=cache_dir)
                if path:
                    self._renderers.pop(app_id, None)
                    self._pixmaps = {
                        key: val for key, val in self._pixmaps.items() if key[0] != app_id
                    }
            finally:
                self._pending_fetch.discard(app_id)
                if on_ready:
                    QTimer.singleShot(0, on_ready)

        threading.Thread(target=work, daemon=True, name=f"markers-{app_id}").start()

    def _renderer_for(self, app_id):
        app_id = str(app_id)
        if app_id in self._renderers:
            return self._renderers[app_id]

        renderer = None
        path = resolve_markers_svg_path_local(app_id, cache_dir=self._cache_dir)
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
        self._pending_fetch.clear()
