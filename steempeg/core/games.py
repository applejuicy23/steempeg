"""Look up Steam game metadata (names, icons) by app id.

Pure functions - no Qt, no caching. Network only; callers handle the cache.
"""
import requests

_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"


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