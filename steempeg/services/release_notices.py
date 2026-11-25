"""Version-targeted notices served as plain text by the Steempeg website."""
from __future__ import annotations

from dataclasses import dataclass
import re

from steempeg.services.release_catalog import parse_version, version_key

NOTICES_URL = "https://applejuicy23.github.io/steempeg/notices.json"
_VERSION = re.compile(r"v?[0-9]{1,6}(?:\.[0-9]{1,6}){0,2}", re.IGNORECASE)


def release_key(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str) or not _VERSION.fullmatch(value):
        return None
    return version_key(parse_version(value) or ())


@dataclass(frozen=True)
class ReleaseNotice:
    id: str
    title: str
    message: str
    critical: bool
    offer_update: bool
    details: str = ""


def notices_for_version(payload: object, version: str) -> list[ReleaseNotice]:
    current = release_key(version)
    rows = payload.get("notices") if isinstance(payload, dict) else None
    if current is None or not isinstance(rows, list):
        return []
    notices = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        targets = row.get("versions")
        if not isinstance(targets, list) or not any(
            target == "*" or release_key(target) == current for target in targets
        ):
            continue
        notice_id, title, message = (row.get(key) for key in ("id", "title", "message"))
        if not all(isinstance(value, str) and value.strip() for value in (notice_id, title, message)):
            continue
        if len(notice_id) > 64 or len(title) > 120 or len(message) > 1400:
            continue
        details = row.get("details")
        if not isinstance(details, str) or len(details) > 2400:
            details = ""
        notices.setdefault(
            notice_id,
            ReleaseNotice(notice_id, title.strip(), message.strip(),
                          row.get("critical") is True, row.get("action") == "update",
                          details.strip()),
        )
    return sorted(notices.values(), key=lambda item: not item.critical)[:16]
