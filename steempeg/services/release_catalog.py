"""GitHub release catalog and version policy for the Update Center."""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from enum import Enum

import requests

REPO = "applejuicy23/steempeg"
API_BASE = f"https://api.github.com/repos/{REPO}/releases"
HEADERS = {"User-Agent": "Steempeg-Updater"}

# Install policy (see Steempegold smpeg8/9/12.1/16 for era references).
MIN_INSTALL_VERSION = 12.1
RECOMMENDED_INSTALL_VERSION = 16.0
BLOCKED_INSTALL_VERSIONS: frozenset[float] = frozenset({12.0})

_VERSION_RE = re.compile(r"v?(\d+(?:\.\d+)*)", re.IGNORECASE)
_BACKUP_DIR_RE = re.compile(r"^old_version_v[\d.]+$", re.IGNORECASE)

REFACTOR_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (29.0, "v29 introduced major UI refactors."),
    (30.0, "v30 changed the render queue format."),
    (35.0, "v35 changed rendered output sidecars."),
    (36.0, "v36 changed window chrome and title bar."),
)

UPDATE_CENTER_POLICY_NOTE = ""

GENERIC_DOWNGRADE_NOTICE = (
    "Older release than your current build. You may hit bugs that were fixed in later patches."
)


_SECTION_HEADER_RE = re.compile(
    r"^(?:🚀\s*NEW FEATURES|✨\s*PLAYER\s*&\s*UI|✨\s*PLAYER)",
    re.IGNORECASE,
)
_BULLET_LINE_RE = re.compile(r"^[-*•]\s+(.+)$")
_MARKDOWN_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


class VersionEra(str, Enum):
    ALPHA = "alpha"
    BROWSER = "browser"
    EARLY = "early"
    RELIABLE = "reliable"


class InstallTier(str, Enum):
    MANUAL = "manual"
    BROKEN = "broken"
    NO_ZIP = "no_zip"
    RISKY = "risky"
    STABLE = "stable"


class FetchError(Exception):
    """Raised when the GitHub releases API cannot be read."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        rate_limit: RateLimitInfo | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.rate_limit = rate_limit


@dataclass(frozen=True)
class RateLimitInfo:
    reset_at: int
    limit: int = 60
    remaining: int = 0

    @property
    def seconds_remaining(self) -> int:
        return max(0, self.reset_at - int(time.time()))


@dataclass(frozen=True)
class VersionMilestone:
    version: float
    icon: str
    short_label: str
    detail: str


# Landmarks — manual anchors; release notes fill gaps for unlisted versions.
VERSION_MILESTONES: tuple[VersionMilestone, ...] = (
    VersionMilestone(36.0, "🎨", "New chrome", "Frameless title bar and chrome theme experiments."),
    VersionMilestone(35.0, "📼", "Rendered library", "Rendered output sidecars and filter panel."),
    VersionMilestone(30.0, "📋", "Render queue", "Batch render queue and export history."),
    VersionMilestone(29.0, "🔧", "UI refactor", "Major player and shell layout refactor."),
    VersionMilestone(27.0, "🔍", "Sort & filter", "Sorting and filtering."),
    VersionMilestone(22.0, "🎬", "Clips manager", "Clips manager UI update."),
    VersionMilestone(20.0, "📍", "Timeline markers", "Timeline marker support."),
    VersionMilestone(16.0, "▶", "MPV player", "VLC replaced with mpv playback engine."),
    VersionMilestone(16.0, "⚡", "Stable updater", "Download, unzip and updater.bat. Same model as today."),
    VersionMilestone(12.1, "📦", "Zip installer", "First working in-app zip download and install."),
    VersionMilestone(12.0, "💀", "Broken release", "Do not install. Shipped dead. Use v12.1."),
    VersionMilestone(11.0, "📺", "VLC player", "VLC-based video playback."),
    VersionMilestone(10.0, "▶", "Early player", "Early player update."),
    VersionMilestone(9.0, "🎨", "UI update", "UI refresh."),
    VersionMilestone(8.0, "🧪", "Early dev · last", "Select Clip + Render only."),
)

_KEYED_EARLY_INFO_VERSIONS: frozenset[float] = frozenset({8.0, 9.0, 10.0, 11.0})

COLOR_VERSION_NEW = "#7ec8a3"
COLOR_VERSION_CURRENT = "#b29ae7"
COLOR_VERSION_STABLE = "#e8e8e8"
COLOR_VERSION_RISKY = "#e8b86d"
COLOR_VERSION_LEGACY = "#ff8a80"

# How many major versions behind latest stay white before fading to yellow.
WHITE_HOLD_GAP = 3
YELLOW_FADE_SPAN = 18


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
    install_tier: InstallTier
    installable: bool
    milestones: tuple[VersionMilestone, ...]
    block_reason: str | None
    published_at: str = ""
    zip_size: int | None = None
    zip_sha256: str | None = None

    def badge(self, current_version: float) -> str:
        if abs(self.version_float - current_version) < 0.001:
            return "current"
        if self.version_float > current_version:
            if self.install_tier == InstallTier.STABLE:
                return "newer"
            if self.install_tier == InstallTier.RISKY:
                return "newer · risky"
            if self.install_tier == InstallTier.BROKEN:
                return "broken"
            return "newer"
        if not self.installable:
            if self.install_tier == InstallTier.BROKEN:
                return "broken"
            if self.install_tier == InstallTier.MANUAL:
                return "manual only"
            if self.era in (VersionEra.BROWSER, VersionEra.EARLY):
                return "browser-era"
            return "unavailable"
        if self.install_tier == InstallTier.RISKY:
            return "older · risky"
        if abs(self.version_float - RECOMMENDED_INSTALL_VERSION) < 0.001:
            return "older · stable floor"
        return "older"

    def milestone_labels(self) -> str:
        if not self.milestones:
            return ""
        parts = [f"{m.icon} {m.short_label}" for m in self.milestones]
        return " · ".join(parts)

    def row_highlight(self) -> str | None:
        if self.milestones:
            return self.milestone_labels()
        return extract_release_highlight(self.body)


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


def versions_equal(a: float, b: float) -> bool:
    return abs(a - b) < 0.001


def classify_era(version_float: float) -> VersionEra:
    if version_float <= 8:
        return VersionEra.ALPHA
    if version_float <= 11:
        return VersionEra.BROWSER
    if version_float <= 15:
        return VersionEra.EARLY
    return VersionEra.RELIABLE


def is_early_development(version_float: float) -> bool:
    return version_float <= 8.0


def extract_release_highlight(body: str) -> str | None:
    """First bullet under NEW FEATURES or PLAYER & UI in GitHub release notes."""
    if not body:
        return None
    lines = body.splitlines()
    in_section = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _SECTION_HEADER_RE.search(stripped):
            in_section = True
            continue
        if in_section:
            if stripped.startswith("#") or stripped.startswith("---"):
                break
            if len(stripped) < 80 and _SECTION_HEADER_RE.search(stripped):
                break
            match = _BULLET_LINE_RE.match(stripped)
            if match:
                text = _MARKDOWN_BOLD_RE.sub(r"\1", match.group(1)).strip()
                if text:
                    return text[:72] + ("…" if len(text) > 72 else "")
            if stripped[0].isdigit() and "." in stripped[:4]:
                break
    return None


def group_releases_by_major(releases: list[ReleaseEntry]) -> list[list[ReleaseEntry]]:
    """Group v36 / v36.1 / v36.2 together; preserve newest-major-first order."""
    groups: dict[int, list[ReleaseEntry]] = {}
    major_order: list[int] = []
    for entry in releases:
        major = entry.version[0]
        if major not in groups:
            groups[major] = []
            major_order.append(major)
        groups[major].append(entry)
    return [
        sorted(groups[major], key=lambda item: item.version_float, reverse=True)
        for major in major_order
    ]


def patch_warning(entry: ReleaseEntry, group: list[ReleaseEntry]) -> str | None:
    if len(group) <= 1:
        return None
    newest = group[0]
    if entry.version_float < newest.version_float - 0.001:
        return f"Newer patch v{newest.version_str} exists. This build may have unfixed bugs."
    return None


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _lerp_color(color_a: str, color_b: str, progress: float) -> str:
    progress = max(0.0, min(1.0, progress))
    ar, ag, ab = _hex_to_rgb(color_a)
    br, bg, bb = _hex_to_rgb(color_b)
    return (
        f"#{int(ar + (br - ar) * progress):02x}"
        f"{int(ag + (bg - ag) * progress):02x}"
        f"{int(ab + (bb - ab) * progress):02x}"
    )


def version_major(version_float: float) -> int:
    return int(version_float)


def latest_release_version(releases: list[ReleaseEntry]) -> float:
    if not releases:
        return 0.0
    return releases[0].version_float


def default_selected_release(releases: list[ReleaseEntry], installed: float) -> ReleaseEntry:
    """Prefer the newest GitHub release when it is newer than the running build."""
    latest = releases[0]
    if latest.version_float > installed + 0.001:
        return latest
    for entry in releases:
        if versions_equal(entry.version_float, installed):
            return entry
    return latest


def version_label_color(
    version_float: float,
    *,
    installed: float,
    latest: float,
) -> str:
    if versions_equal(version_float, installed):
        return COLOR_VERSION_CURRENT
    if version_float > installed + 0.001:
        return COLOR_VERSION_NEW
    if version_float < 12.0 - 0.001:
        return COLOR_VERSION_LEGACY

    gap = version_major(latest) - version_major(version_float)
    if gap <= WHITE_HOLD_GAP:
        return COLOR_VERSION_STABLE
    fade = min(1.0, (gap - WHITE_HOLD_GAP) / YELLOW_FADE_SPAN)
    return _lerp_color(COLOR_VERSION_STABLE, COLOR_VERSION_RISKY, fade)


def shows_info_icon(entry: ReleaseEntry) -> bool:
    """(i) only on keyed Early builds v8–v11, and on v12+ milestone releases."""
    if entry.version_float < 12.0 - 0.001:
        return any(versions_equal(entry.version_float, v) for v in _KEYED_EARLY_INFO_VERSIONS)
    return bool(entry.milestones)


def selection_marker_text(entry: ReleaseEntry) -> str | None:
    """Purple label above the ack checkbox for keyed releases."""
    if not entry.milestones:
        return None
    parts: list[str] = []
    for milestone in entry.milestones:
        if versions_equal(milestone.version, 8.0):
            parts.append(f"{milestone.icon} {milestone.short_label} · {milestone.detail}")
        else:
            parts.append(f"{milestone.icon} {milestone.short_label}")
    return " · ".join(parts)


def info_tooltip_text(entry: ReleaseEntry) -> str | None:
    """Tooltip for the (i) button on a version row."""
    if not shows_info_icon(entry):
        return None
    lines: list[str] = []
    for milestone in entry.milestones:
        lines.append(f"{milestone.icon} {milestone.short_label}: {milestone.detail}")
    return "\n".join(lines) if lines else None


def selection_notice(entry: ReleaseEntry, current_version: float) -> str | None:
    """Single short line under release notes when a version is selected."""
    if entry.version_float <= 11.0:
        return "Early Development. Bare .exe only. Cannot install in-app."
    if entry.version_float >= current_version - 0.001:
        return None
    if versions_equal(entry.version_float, RECOMMENDED_INSTALL_VERSION):
        return "Last safe version for in-app install."
    if versions_equal(entry.version_float, 12.1):
        return "Last early zip build. No longer supported. Not recommended to download."
    if MIN_INSTALL_VERSION < entry.version_float < RECOMMENDED_INSTALL_VERSION:
        return "Early zip updater era. Install may be unstable."
    if entry.version_float >= RECOMMENDED_INSTALL_VERSION:
        return GENERIC_DOWNGRADE_NOTICE
    if entry.version_float < MIN_INSTALL_VERSION:
        return "Bare .exe era. Manual download only."
    return GENERIC_DOWNGRADE_NOTICE


def old_version_warning(entry: ReleaseEntry, current_version: float) -> str | None:
    return selection_notice(entry, current_version)


def milestones_for_version(version_float: float) -> tuple[VersionMilestone, ...]:
    return tuple(m for m in VERSION_MILESTONES if versions_equal(m.version, version_float))


def classify_install_tier(version_float: float, zip_url: str | None) -> InstallTier:
    if any(versions_equal(version_float, blocked) for blocked in BLOCKED_INSTALL_VERSIONS):
        return InstallTier.BROKEN
    if not zip_url:
        return InstallTier.NO_ZIP if version_float >= MIN_INSTALL_VERSION else InstallTier.MANUAL
    if version_float < MIN_INSTALL_VERSION:
        return InstallTier.MANUAL
    if version_float < RECOMMENDED_INSTALL_VERSION:
        return InstallTier.RISKY
    return InstallTier.STABLE


def is_installable(version_float: float, zip_url: str | None) -> bool:
    tier = classify_install_tier(version_float, zip_url)
    return tier in (InstallTier.RISKY, InstallTier.STABLE)


def install_policy_message(entry: ReleaseEntry) -> str | None:
    if entry.block_reason:
        return entry.block_reason.replace("—", ",")
    if versions_equal(entry.version_float, RECOMMENDED_INSTALL_VERSION):
        return "Last safe version for in-app install."
    if versions_equal(entry.version_float, 12.1):
        return "Last early zip build. No longer supported. Not recommended."
    if MIN_INSTALL_VERSION < entry.version_float < RECOMMENDED_INSTALL_VERSION:
        return "Early zip updater. Settings and formats may break."
    if is_early_development(entry.version_float) and versions_equal(entry.version_float, 8.0):
        return "Last Early Development build. Select Clip + Render only."
    if is_early_development(entry.version_float):
        return "Early Development. Bare .exe only."
    return None


def jump_warnings(from_version: float, to_version: float) -> list[str]:
    if versions_equal(from_version, to_version):
        return []
    low = min(from_version, to_version)
    high = max(from_version, to_version)
    warnings: list[str] = []
    for threshold, message in REFACTOR_THRESHOLDS:
        if low < threshold <= high:
            warnings.append(message)
    if high < RECOMMENDED_INSTALL_VERSION and low >= MIN_INSTALL_VERSION:
        warnings.append("Target is before v16 — early updater era; higher crash/incompatibility risk.")
    if low < MIN_INSTALL_VERSION:
        warnings.append("Crossing into pre-v12.1 territory — manual .exe era, not in-app install.")
    return warnings


def find_zip_asset(assets: list[dict]) -> tuple[str | None, str | None, int | None, str | None]:
    for asset in assets:
        name = (asset.get("name") or "").lower()
        if name.endswith(".zip"):
            size = asset.get("size")
            try:
                size_i = int(size) if size is not None else None
            except (TypeError, ValueError):
                size_i = None
            digest = (asset.get("digest") or "").strip() or None
            return asset.get("browser_download_url"), asset.get("name"), size_i, digest
    return None, None, None, None


def _block_reason_for(tier: InstallTier, version_float: float) -> str | None:
    if tier == InstallTier.BROKEN and versions_equal(version_float, 12.0):
        return "v12.0 cannot be installed. Broken release. Use v12.1."
    return None


def parse_release(data: dict) -> ReleaseEntry | None:
    tag_name = data.get("tag_name") or ""
    name = data.get("name") or tag_name
    version = parse_version(f"{tag_name} {name}")
    if not version:
        return None

    version_str = format_version(version)
    version_float = version_to_float(version)
    zip_url, zip_name, zip_size, zip_sha256 = find_zip_asset(data.get("assets") or [])
    era = classify_era(version_float)
    install_tier = classify_install_tier(version_float, zip_url)
    milestones = milestones_for_version(version_float)
    block_reason = _block_reason_for(install_tier, version_float)

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
        install_tier=install_tier,
        installable=is_installable(version_float, zip_url),
        milestones=milestones,
        block_reason=block_reason,
        published_at=data.get("published_at") or "",
        zip_size=zip_size,
        zip_sha256=zip_sha256,
    )


def _rate_limit_from_response(response: requests.Response) -> RateLimitInfo | None:
    """Parse GitHub rate-limit headers / body from an API response."""
    reset_raw = response.headers.get("X-RateLimit-Reset")
    limit_raw = response.headers.get("X-RateLimit-Limit", "60")
    remaining_raw = response.headers.get("X-RateLimit-Remaining")

    is_rate_limit = False
    try:
        if remaining_raw is not None and int(remaining_raw) == 0:
            is_rate_limit = True
    except (TypeError, ValueError):
        pass

    body_text = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            body_text = str(body.get("message", "")).lower()
            if "rate limit" in body_text or "secondary rate" in body_text:
                is_rate_limit = True
    except ValueError:
        body_text = (response.text or "").lower()
        if "rate limit" in body_text:
            is_rate_limit = True

    # Bare 403 from api.github.com with reset header — treat as rate limit.
    if (
        not is_rate_limit
        and response.status_code == 403
        and reset_raw
        and "github" in (response.url or "")
    ):
        is_rate_limit = True

    if not is_rate_limit:
        return None

    try:
        reset_at = int(reset_raw) if reset_raw else int(time.time()) + 3600
        limit = int(limit_raw)
    except (TypeError, ValueError):
        reset_at = int(time.time()) + 3600
        limit = 60

    try:
        remaining = int(remaining_raw) if remaining_raw is not None else 0
    except (TypeError, ValueError):
        remaining = 0

    # Never schedule a reset in the past — bump at least 30s so the dialog can tick.
    now = int(time.time())
    if reset_at <= now:
        reset_at = now + 30

    return RateLimitInfo(reset_at=reset_at, limit=limit, remaining=remaining)


def probe_github_rate_limit(*, timeout: float = 8.0) -> RateLimitInfo | None:
    """Ask /rate_limit (does not consume quota). Returns info when core remaining is 0."""
    try:
        response = requests.get(
            "https://api.github.com/rate_limit",
            headers=HEADERS,
            timeout=timeout,
        )
    except requests.RequestException:
        return None

    if response.status_code == 403:
        return _rate_limit_from_response(response)

    if response.status_code != 200:
        return None

    try:
        payload = response.json()
        core = (payload.get("resources") or {}).get("core") or {}
        remaining = int(core.get("remaining", 1))
        limit = int(core.get("limit", 60))
        reset_at = int(core.get("reset") or (time.time() + 3600))
    except (TypeError, ValueError, AttributeError):
        return None

    if remaining > 0:
        return None

    now = int(time.time())
    if reset_at <= now:
        reset_at = now + 30
    return RateLimitInfo(reset_at=reset_at, limit=limit, remaining=0)


def _looks_like_transport_block(exc: BaseException) -> bool:
    text = str(exc).lower()
    needles = (
        "max retries exceeded",
        "connection aborted",
        "connection reset",
        "remotely closed",
        "timed out",
        "temporary failure",
        "name resolution",
        "failed to establish",
    )
    return any(n in text for n in needles)


def fetch_releases(*, timeout: float = 10.0) -> list[ReleaseEntry]:
    """Fetch all public releases, newest first."""
    releases: list[ReleaseEntry] = []
    page = 1

    try:
        while True:
            response = requests.get(
                API_BASE,
                headers=HEADERS,
                params={"per_page": 100, "page": page},
                timeout=timeout,
            )
            if response.status_code == 403:
                rate_limit = _rate_limit_from_response(response) or probe_github_rate_limit(
                    timeout=timeout
                )
                if rate_limit:
                    raise FetchError(
                        "GitHub API rate limit exceeded.",
                        status_code=403,
                        rate_limit=rate_limit,
                    )
                raise FetchError("GitHub API access denied.", status_code=403)
            if response.status_code == 404:
                raise FetchError("No public releases found for this repository.", status_code=404)
            if response.status_code == 429:
                rate_limit = _rate_limit_from_response(response) or probe_github_rate_limit(
                    timeout=timeout
                )
                if rate_limit is None:
                    now = int(time.time())
                    rate_limit = RateLimitInfo(reset_at=now + 60, limit=60, remaining=0)
                raise FetchError(
                    "GitHub API rate limit exceeded.",
                    status_code=429,
                    rate_limit=rate_limit,
                )
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
    except FetchError:
        raise
    except requests.RequestException as exc:
        # VPN / drop / "Max retries exceeded" often masks a spent hourly quota.
        rate_limit = probe_github_rate_limit(timeout=min(timeout, 8.0))
        if rate_limit is None and _looks_like_transport_block(exc):
            # Soft wait: show countdown dialog instead of a dead red error string.
            now = int(time.time())
            rate_limit = RateLimitInfo(reset_at=now + 60, limit=60, remaining=0)
            logging.warning(
                "RELEASE_CATALOG: transport error talking to GitHub (%s) — "
                "opening rate-limit wait dialog",
                exc,
            )
        if rate_limit is not None:
            raise FetchError(
                "GitHub API rate limit exceeded.",
                status_code=403,
                rate_limit=rate_limit,
            ) from exc
        raise FetchError(f"Could not reach GitHub:\n{exc}") from exc

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
