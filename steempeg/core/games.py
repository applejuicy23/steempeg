"""Look up Steam game metadata (names, icons) by app id.

Pure functions - no Qt, no caching. Network only; callers handle the cache.
"""
from __future__ import annotations

import glob
import os
import re
import shutil

import requests

from steempeg.core.steam_paths import get_steam_path

_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
_STEAMCMD_INFO_URL = "https://api.steamcmd.net/v1/info/{app_id}"
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
}
_ICON_HASH_RE = re.compile(r"^[a-fA-F0-9]{32,40}\.jpg$")
# Overrides where scraping is unreliable.
_ICON_OVERRIDES = {
    "730": "https://shared.fastly.steamstatic.com/community_assets/images/apps/730/8dbc71957312bbd3baea65848b545be9eae2a355.jpg",
}
_CDN_HOSTS = (
    "shared.fastly.steamstatic.com",
    "shared.akamai.steamstatic.com",
    "cdn.cloudflare.steamstatic.com",
)


def fetch_game_name(app_id, timeout=3):
    """Return the game's name from the Steam store API, or None if unavailable."""
    app_id = str(app_id)
    try:
        resp = requests.get(_APPDETAILS_URL, params={"appids": app_id}, timeout=timeout)
        data = resp.json()
        entry = data.get(app_id) if data else None
        if entry and entry.get("success"):
            return entry["data"]["name"]
    except (requests.RequestException, ValueError, KeyError):
        pass
    return None


def find_local_steam_icon(app_id, steam_path=None) -> str | None:
    """Return a square icon file from the local Steam client cache, if present."""
    app_id = str(app_id)
    base = os.path.join(steam_path or get_steam_path(), "appcache", "librarycache", app_id)
    if not os.path.isdir(base):
        return None

    for path in sorted(glob.glob(os.path.join(base, "*.jpg"))):
        if _ICON_HASH_RE.match(os.path.basename(path)) and os.path.getsize(path) > 100:
            return path

    for path in sorted(glob.glob(os.path.join(base, "*", "logo.png"))):
        if os.path.getsize(path) > 100:
            return path

    return None


def _cdn_icon_urls(app_id: str, icon_hash: str) -> list[str]:
    rel = f"community_assets/images/apps/{app_id}/{icon_hash}.jpg"
    return [f"https://{host}/{rel}" for host in _CDN_HOSTS]


def _is_valid_icon_response(resp: requests.Response) -> bool:
    if not resp.ok:
        return False
    content_type = (resp.headers.get("content-type") or "").lower()
    if "image" not in content_type and not resp.content.startswith(b"\xff\xd8\xff"):
        return False
    return len(resp.content) > 100


def find_icon_urls(app_id, timeout=7) -> list[str]:
    """Return candidate icon URLs, best first. Does not verify HTTP status."""
    app_id = str(app_id)
    urls: list[str] = []
    seen: set[str] = set()

    def add(url: str | None) -> None:
        if not url or url in seen:
            return
        seen.add(url)
        urls.append(url)

    if app_id in _ICON_OVERRIDES:
        add(_ICON_OVERRIDES[app_id])

    try:
        resp = requests.get(
            _STEAMCMD_INFO_URL.format(app_id=app_id),
            headers=_BROWSER_HEADERS,
            timeout=timeout,
        )
        if resp.ok:
            common = resp.json().get("data", {}).get(app_id, {}).get("common", {})
            icon_hash = common.get("clienticon") or common.get("icon")
            if icon_hash:
                for url in _cdn_icon_urls(app_id, icon_hash):
                    add(url)
    except (requests.RequestException, ValueError, TypeError):
        pass

    try:
        resp = requests.get(
            f"https://steamcommunity.com/app/{app_id}",
            headers=_BROWSER_HEADERS,
            timeout=5,
        )
        if resp.ok:
            pattern = (
                r"(https://[^\"'<>]*?images/apps/"
                + re.escape(app_id)
                + r"/[a-fA-F0-9]{32,40}\.jpg)"
            )
            for match in re.finditer(pattern, resp.text):
                add(match.group(1))
    except requests.RequestException:
        pass

    return urls


def find_icon_url(app_id, timeout=7):
    """Find a square game-icon URL for `app_id`, or None."""
    urls = find_icon_urls(app_id, timeout=timeout)
    return urls[0] if urls else None


def download_icon(app_id, dest_path, timeout=5):
    """Find and download the game icon for `app_id` to `dest_path`.

    Prefers the local Steam client cache, then tries CDN URLs until one returns
    a real image (community HTML can point at stale 404 hashes).
    Returns True on success. Pure - no Qt.
    """
    app_id = str(app_id)

    local = find_local_steam_icon(app_id)
    if local:
        try:
            shutil.copy2(local, dest_path)
            return True
        except OSError:
            pass

    for url in find_icon_urls(app_id, timeout=timeout):
        try:
            resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=timeout)
            if not _is_valid_icon_response(resp):
                continue
            with open(dest_path, "wb") as handle:
                handle.write(resp.content)
            return True
        except (requests.RequestException, OSError):
            continue
    return False
