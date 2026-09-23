"""Remote Ko-fi tip URL — fetched from the Steempeg Pages meta JSON.

Single source of truth on the website:

  https://applejuicy23.github.io/steempeg/steempeg-meta.json

  { "kofi_url": "https://ko-fi.com/applejuicy23" }

The app caches the last good URL so Donate Me / PRO still work offline.
Display strips ``https://``; buttons always open the full URL.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any

DEFAULT_KOFI_URL = "https://ko-fi.com/applejuicy23"
META_URL = "https://applejuicy23.github.io/steempeg/steempeg-meta.json"
_CACHE_NAME = "kofi_remote.json"

_lock = threading.Lock()
_memory_url: str | None = None
_refresh_started = False


def normalize_kofi_url(raw: object | None) -> str:
    """Return a full ``https://…`` Ko-fi URL, or ``DEFAULT_KOFI_URL``."""
    text = str(raw or "").strip()
    if not text:
        return DEFAULT_KOFI_URL
    if not re.match(r"^https?://", text, flags=re.IGNORECASE):
        text = "https://" + text.lstrip("/")
    # Drop trailing slash noise for stable display / open.
    text = text.rstrip("/")
    if "ko-fi.com" not in text.lower() and "kofi.com" not in text.lower():
        # Still accept — user may move tip jar off Ko-fi later.
        pass
    return text or DEFAULT_KOFI_URL


def display_kofi_host(url: object | None = None) -> str:
    """``https://ko-fi.com/x`` → ``ko-fi.com/x`` for labels."""
    full = normalize_kofi_url(url if url is not None else resolve_kofi_url())
    return re.sub(r"^https?://", "", full, flags=re.IGNORECASE)


def _cache_path() -> str:
    try:
        from steempeg.infra.paths import get_save_directory

        return os.path.join(get_save_directory(), "cache", _CACHE_NAME)
    except Exception:
        return ""


def _read_disk_cache() -> str | None:
    path = _cache_path()
    if not path or not os.path.isfile(path):
        return None
    try:
        from steempeg.infra import cache as json_cache

        data = json_cache.read_json(path, default={})
        if isinstance(data, dict) and data.get("kofi_url"):
            return normalize_kofi_url(data.get("kofi_url"))
    except Exception:
        logging.debug("Ko-fi cache read failed", exc_info=True)
    return None


def _write_disk_cache(url: str) -> None:
    path = _cache_path()
    if not path:
        return
    try:
        from steempeg.infra import cache as json_cache

        os.makedirs(os.path.dirname(path), exist_ok=True)
        json_cache.write_json(path, {"kofi_url": normalize_kofi_url(url)})
    except Exception:
        logging.debug("Ko-fi cache write failed", exc_info=True)


def resolve_kofi_url(*, refresh: bool = False, timeout: float = 2.5) -> str:
    """Best tip URL: memory → disk cache → default; optionally hit Pages first."""
    global _memory_url
    if refresh:
        fetched = fetch_kofi_url(timeout=timeout)
        if fetched:
            return fetched
    with _lock:
        if _memory_url:
            return _memory_url
    cached = _read_disk_cache()
    if cached:
        with _lock:
            _memory_url = cached
        return cached
    return DEFAULT_KOFI_URL


def fetch_kofi_url(*, timeout: float = 2.5) -> str | None:
    """GET ``steempeg-meta.json``; update memory + disk on success."""
    global _memory_url
    try:
        import requests

        resp = requests.get(META_URL, timeout=max(0.5, float(timeout)))
        resp.raise_for_status()
        data: Any = resp.json()
        if not isinstance(data, dict):
            return None
        raw = data.get("kofi_url") or data.get("kofi") or data.get("url")
        if not raw:
            return None
        url = normalize_kofi_url(raw)
        with _lock:
            _memory_url = url
        _write_disk_cache(url)
        logging.info("Ko-fi tip URL from Pages: %s", url)
        return url
    except Exception:
        logging.debug("Ko-fi meta fetch failed", exc_info=True)
        return None


def refresh_kofi_url_async() -> None:
    """Quiet background refresh (startup / idle) — never blocks UI."""
    global _refresh_started
    with _lock:
        if _refresh_started:
            return
        _refresh_started = True

    def _worker() -> None:
        try:
            fetch_kofi_url(timeout=4.0)
        finally:
            global _refresh_started
            with _lock:
                _refresh_started = False

    threading.Thread(target=_worker, name="steempeg-kofi-meta", daemon=True).start()
