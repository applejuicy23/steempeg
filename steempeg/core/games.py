"""Look up Steam game metadata (names, icons) by app id.

Pure functions - no Qt, no caching. Network only; callers handle the cache.
"""
import requests
import re

_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
}
# Overrides where scraping is unreliable.
_ICON_OVERRIDES = {
    "730": "https://shared.fastly.steamstatic.com/community_assets/images/apps/730/8dbc71957312bbd3baea65848b545be9eae2a355.jpg",
}


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

def find_icon_url(app_id, timeout=7):
    """Find a square game-icon URL for `app_id`, or None. Tries overrides,
    the community page, then the steamcmd API. Pure - network/regex, no Qt."""
    app_id = str(app_id)
    if app_id in _ICON_OVERRIDES:
        return _ICON_OVERRIDES[app_id]

    # community hub page: look for a hashed icon link
    try:
        resp = requests.get(f"https://steamcommunity.com/app/{app_id}",
                            headers=_BROWSER_HEADERS, timeout=5)
        if resp.ok:
            pattern = r'(https://[^"\'<>]*?images/apps/' + re.escape(app_id) + r'/[a-fA-F0-9]{32,40}\.jpg)'
            match = re.search(pattern, resp.text)
            if match:
                return match.group(1)
    except requests.RequestException:
        pass

    # fallback: steamcmd API
    try:
        resp = requests.get(f"https://api.steamcmd.net/v1/info/{app_id}",
                            headers=_BROWSER_HEADERS, timeout=timeout)
        if resp.ok:
            common = resp.json().get("data", {}).get(app_id, {}).get("common", {})
            icon_hash = common.get("clienticon") or common.get("icon")
            if icon_hash:
                return f"https://shared.fastly.steamstatic.com/community_assets/images/apps/{app_id}/{icon_hash}.jpg"
    except (requests.RequestException, ValueError):
        pass

    return None


def download_icon(app_id, dest_path, timeout=5):
    """Find and download the game icon for `app_id` to `dest_path`.
    Returns True on success. Pure - no Qt."""
    url = find_icon_url(app_id)
    if not url:
        return False
    try:
        resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=timeout)
        if resp.ok:
            with open(dest_path, "wb") as f:
                f.write(resp.content)
            return True
    except (requests.RequestException, OSError):
        pass
    return False