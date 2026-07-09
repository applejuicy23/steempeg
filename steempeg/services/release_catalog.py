"""GitHub release catalog and version policy for the Update Center."""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from enum import Enum

import requests

REPO = "applejuicy23/steempeg"
API_BASE = f"https://api.github.com/repos/{REPO}/releases"
HEADERS = {"User-Agent": "Steempeg-Updater"}
MIN_INSTALL_VERSION = 16.0

_VERSION_RE = re.compile(r"v?(\d+(?:\.\d+)*)", re.IGNORECASE)
_BACKUP_DIR_RE = re.compile(r"^old_version_v[\d.]+$", re.IGNORECASE)

REFACTOR_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (29.0, "v29 introduced major UI refactors."),
    (30.0, "v30 changed the render queue format."),
    (35.0, "v35 changed rendered output sidecars."),
    (36.0, "v36 changed window chrome and title bar."),
)


class VersionEra(str, Enum):
    ALPHA = "alpha"
    BROWSER = "browser"
    EARLY = "early"
    RELIABLE = "reliable"


class FetchError(Exception):
    """Raised when the GitHub releases API cannot be read."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ReleaseEntry:
    tag_name: str
    name: str
    version: tuple[int, ...]
    version_str: str
    version_float: float
    html_url: str
    body: str
    zip_url: str | None
    zip_name: str | None
    era: VersionEra
    installable: bool
    published_at: str = ""

    def badge(self, current_version: float) -> str:
        if abs(self.version_float - current_version) < 0.001:
            return "current"
        if self.version_float > current_version:
            return "newer"
        if not self.installable:
            if self.era == VersionEra.ALPHA:
                return "manual only"
            if self.era in (VersionEra.BROWSER, VersionEra.EARLY):
                return "browser-era"
            return "unavailable"
        return "older"


@dataclass(frozen=True)
class LocalBackup:
    folder_name: str
    path: str
    version_str: str
    version_float: float


def parse_version(text: str) -> tuple[int, ...] | None:
    match = _VERSION_RE.search(text or "")
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def version_to_float(parts: tuple[int, ...]) -> float:
    if not parts:
        return 0.0
    if len(parts) == 1:
        return float(parts[0])
    return parts[0] + parts[1] / (10 ** len(str(parts[1])))


def format_version(parts: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in parts)


def classify_era(version_float: float) -> VersionEra:
    if version_float <= 8:
        return VersionEra.ALPHA
    if version_float <= 11:
        return VersionEra.BROWSER
    if version_float <= 15:
        return VersionEra.EARLY
    return VersionEra.RELIABLE


def is_installable(version_float: float, zip_url: str | None) -> bool:
    return bool(zip_url) and version_float >= MIN_INSTALL_VERSION


def jump_warnings(from_version: float, to_version: float) -> list[str]:
    if abs(from_version - to_version) < 0.001:
        return []
    low = min(from_version, to_version)
    high = max(from_version, to_version)
    warnings: list[str] = []
    for threshold, message in REFACTOR_THRESHOLDS:
        if low < threshold <= high:
            warnings.append(message)
    return warnings


def find_zip_asset(assets: list[dict]) -> tuple[str | None, str | None]:
    for asset in assets:
        name = (asset.get("name") or "").lower()
        if name.endswith(".zip"):
            return asset.get("browser_download_url"), asset.get("name")
    return None, None


def parse_release(data: dict) -> ReleaseEntry | None:
    tag_name = data.get("tag_name") or ""
    name = data.get("name") or tag_name
    version = parse_version(f"{tag_name} {name}")
    if not version:
        return None

    version_str = format_version(version)
    version_float = version_to_float(version)
    zip_url, zip_name = find_zip_asset(data.get("assets") or [])
    era = classify_era(version_float)

    return ReleaseEntry(
        tag_name=tag_name,
        name=name,
        version=version,
        version_str=version_str,
        version_float=version_float,
        html_url=data.get("html_url") or f"https://github.com/{REPO}/releases",
        body=(data.get("body") or "").strip(),
        zip_url=zip_url,
        zip_name=zip_name,
        era=era,
        installable=is_installable(version_float, zip_url),
        published_at=data.get("published_at") or "",
    )


def fetch_releases(*, timeout: float = 10.0) -> list[ReleaseEntry]:
    """Fetch all public releases, newest first."""
    releases: list[ReleaseEntry] = []
    page = 1

    while True:
        response = requests.get(
            API_BASE,
            headers=HEADERS,
            params={"per_page": 100, "page": page},
            timeout=timeout,
        )
        if response.status_code == 403:
            raise FetchError("GitHub API rate limit exceeded. Try again later.", status_code=403)
        if response.status_code == 404:
            raise FetchError("No public releases found for this repository.", status_code=404)
        if response.status_code != 200:
            raise FetchError(
                f"GitHub API returned status {response.status_code}.",
                status_code=response.status_code,
            )

        batch = response.json()
        if not batch:
            break

        for item in batch:
            if item.get("draft"):
                continue
            entry = parse_release(item)
            if entry:
                releases.append(entry)

        if len(batch) < 100:
            break
        page += 1

    releases.sort(key=lambda entry: entry.version_float, reverse=True)
    logging.info("RELEASE_CATALOG: fetched %s releases", len(releases))
    return releases


def find_local_backups(exe_dir: str) -> list[LocalBackup]:
    backups: list[LocalBackup] = []
    if not exe_dir or not os.path.isdir(exe_dir):
        return backups

    for name in os.listdir(exe_dir):
        path = os.path.join(exe_dir, name)
        if not os.path.isdir(path) or not _BACKUP_DIR_RE.match(name):
            continue
        version = parse_version(name)
        if not version:
            continue
        backups.append(
            LocalBackup(
                folder_name=name,
                path=path,
                version_str=format_version(version),
                version_float=version_to_float(version),
            )
        )

    backups.sort(key=lambda item: item.version_float, reverse=True)
    return backups
