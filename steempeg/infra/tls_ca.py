"""HTTPS CA bundle for frozen builds.

Nuitka reports ``<install>\\certifi\\cacert.pem`` even when that data file was
not packed beside the exe. ``requests`` then refuses every download, including
the updater, with "invalid path".
"""
from __future__ import annotations

import logging
import os
import sys

_log = logging.getLogger(__name__)
_ready = False


def ensure_tls_ca_bundle() -> str | None:
    """Point ``requests`` at a CA file that exists. Safe to call more than once."""
    global _ready
    if _ready:
        current = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
        if current and os.path.isfile(current):
            return current
    path = _first_existing(_candidate_paths())
    if not path:
        _log.warning("No TLS CA bundle found; HTTPS downloads will fail")
        return None
    os.environ["REQUESTS_CA_BUNDLE"] = path
    os.environ["SSL_CERT_FILE"] = path
    _ready = True
    return path


def _candidate_paths() -> list[str]:
    """Places a packed or source checkout might keep ``cacert.pem``."""
    found: list[str] = []

    def add(path: str | None) -> None:
        if path and path not in found:
            found.append(path)

    for key in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE"):
        add(os.environ.get(key))

    try:
        import certifi

        add(os.path.join(os.path.dirname(certifi.__file__), "cacert.pem"))
        try:
            reported = certifi.where()
        except Exception:
            reported = ""
        add(reported)
    except Exception:
        pass

    try:
        from steempeg.infra.paths import get_install_root, get_resource_path

        add(get_resource_path("cacert.pem"))
        root = get_install_root()
        add(os.path.join(root, "certifi", "cacert.pem"))
        add(os.path.join(root, "cacert.pem"))
    except Exception:
        pass

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        add(os.path.join(meipass, "certifi", "cacert.pem"))
        add(os.path.join(meipass, "assets", "cacert.pem"))
    return found


def _first_existing(paths: list[str]) -> str | None:
    """First candidate that is a real file."""
    for path in paths:
        try:
            if path and os.path.isfile(path) and os.path.getsize(path) > 1000:
                return os.path.abspath(path)
        except OSError:
            continue
    return None
