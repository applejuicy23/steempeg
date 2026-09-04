"""GitHub release catalog and version policy for the Update Center."""
from __future__ import annotations

import logging
import os
import re
import sys
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


# Landmarks — manual anchors from docs/github_changelogs_dump.txt (and kitchen
# majors). Release notes still fill row highlights for unlisted versions.
# (i) badge = keyed Early v8–v11, or any v12+ version listed here.
VERSION_MILESTONES: tuple[VersionMilestone, ...] = (
    VersionMilestone(
        49.0,
        "📚",
        "Progressive library",
        "Viewport-lazy Clips on launch; Create… presets; Console mode; Marker Settings by game.",
    ),
    VersionMilestone(
        43.0,
        "⚡",
        "Skip library startup",
        "Session snapshot paints Clips / Rendered / Screenshots instantly; expanded Main Settings.",
    ),
    VersionMilestone(
        42.0,
        "🎨",
        "Visual settings",
        "Game-icon shapes and player-header layout; Clip info chip & popup; permanent export folder.",
    ),
    VersionMilestone(
        41.0,
        "💾",
        "Export presets",
        "Named Video/Audio/Export presets; custom marker classes UI; title-bar Check for Updates.",
    ),
    VersionMilestone(
        40.0,
        "🐧",
        "Linux · Deck · channels",
        "First desktop Linux build, Steam Deck channel, and per-platform Update Center zips.",
    ),
    VersionMilestone(
        38.0,
        "🔄",
        "Fast library refresh",
        "Background scan, clip posters, live preview quality ladder, and encode-speed presets.",
    ),
    VersionMilestone(
        37.0,
        "🆙",
        "Update Center",
        "Browse/install any GitHub release (upgrade or downgrade), backup & restore, detached updater.",
    ),
    VersionMilestone(
        36.0,
        "🖼",
        "Frameless chrome",
        "Custom title bar with traffic lights; chrome color themes; dead-clip salvage.",
    ),
    VersionMilestone(
        35.0,
        "🎞",
        "Export codecs & presets",
        "MP4/MKV/MOV/WebM + codecs; Share/Edit/Web named presets; honest source bitrate.",
    ),
    VersionMilestone(
        34.0,
        "📼",
        "Rendered library",
        "Rendered videos tab with filters and .steempeg.json companion meta sidecars.",
    ),
    VersionMilestone(
        33.0,
        "🗂",
        "Queue grid & history",
        "Render queue thumbnail grid and batch export history archive.",
    ),
    VersionMilestone(
        32.0,
        "📁",
        "Multi-folder library",
        "Scan multiple Steam recording folders; clip health indicators; bug reports.",
    ),
    VersionMilestone(
        30.0,
        "📋",
        "Render queue",
        "Batch render queue with drag-reorder; Steam marker icons auto-loaded.",
    ),
    VersionMilestone(
        29.0,
        "🔧",
        "UI redesign kickoff",
        "Global UI overhaul start; in-player screenshots and markers.",
    ),
    VersionMilestone(
        27.0,
        "🔍",
        "Sort & filter",
        "Clips Manager filter by game/type and deep sort; marker-to-trim snapping.",
    ),
    VersionMilestone(
        26.0,
        "📍",
        "Custom markers",
        "Drop custom timeline markers; advanced trim snap tools.",
    ),
    VersionMilestone(
        22.0,
        "🎬",
        "Clips grid",
        "Netflix-style clips library grid view with grid/list toggle.",
    ),
    VersionMilestone(
        20.0,
        "🎯",
        "Timeline markers",
        "CS2/JSON timeline markers, PyAV hover preview, and zoomable ruler.",
    ),
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
    # Which install zips shipped on this GitHub release (may be empty = announced only).
    available_platforms: frozenset[str] = frozenset()

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
            if self.install_tier == InstallTier.NO_ZIP:
                return "not ready" if not self.available_platforms else "no build"
            return "newer"
        if not self.installable:
            if self.install_tier == InstallTier.BROKEN:
                return "broken"
            if self.install_tier == InstallTier.MANUAL:
                return "manual only"
            if self.install_tier == InstallTier.NO_ZIP:
                return "not ready" if not self.available_platforms else "no build"
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
    if entry.install_tier == InstallTier.NO_ZIP and entry.block_reason:
        return entry.block_reason
    if entry.install_tier == InstallTier.BROKEN and entry.block_reason:
        return entry.block_reason
    if entry.version_float <= 11.0:
        return (
            "Early Development. Bare .exe only. Cannot install in-app. "
            "Minimum for in-app update is v12.1 (still risky)."
        )
    if entry.version_float < MIN_INSTALL_VERSION - 0.001:
        return "Too old for in-app install. Minimum is v12.1, and even that era is risky."
    if entry.version_float >= current_version - 0.001:
        return None
    if versions_equal(entry.version_float, RECOMMENDED_INSTALL_VERSION):
        return "Last safe version for in-app install."
    if versions_equal(entry.version_float, 12.1):
        return "Last early zip build. No longer supported. Not recommended to download."
    if MIN_INSTALL_VERSION < entry.version_float < RECOMMENDED_INSTALL_VERSION:
        return "Risky VLC-era build (v12.1 to v16). Install may be unstable."
    if entry.version_float >= RECOMMENDED_INSTALL_VERSION:
        return GENERIC_DOWNGRADE_NOTICE
    if entry.version_float < MIN_INSTALL_VERSION:
        return "Bare .exe era. Manual download only."
    return GENERIC_DOWNGRADE_NOTICE


def platform_display_name(platform: str) -> str:
    return {
        "windows": "Windows",
        "linux": "Linux",
        "steamdeck": "Steam Deck",
        "macos": "macOS",
    }.get(platform, platform)


def _missing_channel_block_reason(
    *,
    channel: str,
    available: frozenset[str],
    version_float: float,
) -> str | None:
    """Explain why this release cannot be installed on the running channel."""
    if version_float < MIN_INSTALL_VERSION:
        return None
    if channel in available:
        return None
    pretty = platform_display_name(channel)
    if not available:
        return "Version announced, but no install zip is ready yet."
    others = ", ".join(platform_display_name(p) for p in ("windows", "linux", "steamdeck") if p in available)
    return f"No {pretty} build for this version (available: {others})."


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


def is_installable(version_float: float, zip_url: str | None, *, available_platforms: frozenset[str] | None = None) -> bool:
    tier = classify_install_tier(version_float, zip_url)
    if tier not in (InstallTier.RISKY, InstallTier.STABLE):
        return False
    if available_platforms is not None:
        channel = release_platform_tag()
        if channel not in available_platforms:
            return False
    return True


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
        warnings.append("Target is before v16: early updater era; higher crash/incompatibility risk.")
    if low < MIN_INSTALL_VERSION:
        warnings.append("Crossing into pre-v12.1 territory: manual .exe era, not in-app install.")
    return warnings


def release_platform_tag() -> str:
    """Update channel for this build: ``windows`` | ``linux`` | ``steamdeck`` | ``macos``.

    From **40T** onward the channel is ``APP_UPDATE_CHANNEL`` (display version
    stays short, e.g. ``40T``):

    * ``""`` / ``windows`` → Windows (legacy untagged zips still accepted)
    * ``linux`` → Linux desktop zips
    * ``steamdeck`` → Steam Deck zips

    Legacy ``40T-linux`` / ``40T-steamdeck`` version strings still resolve.
    Pre-40T builds fall back to the host OS.
    Override anytime with ``STEEMPEG_UPDATE_CHANNEL=windows|linux|steamdeck``.
    """
    return update_channel()


def update_channel(*, version_str: str | None = None) -> str:
    """Resolve the update stream for *version_str* (default: running app)."""
    env = (os.environ.get("STEEMPEG_UPDATE_CHANNEL") or "").strip().lower()
    if env in ("windows", "linux", "steamdeck", "macos"):
        return env

    from steempeg.version import APP_UPDATE_CHANNEL, APP_VERSION_FLOAT, APP_VERSION_STR

    if version_str is None:
        baked = (APP_UPDATE_CHANNEL or "").strip().lower()
        if baked in ("windows", "linux", "steamdeck", "macos"):
            return baked
        if baked in ("", "win", "win32") and APP_VERSION_FLOAT >= 40.0 - 0.001:
            # Packaged Windows builds bake "" on purpose. On Linux/macOS the same
            # empty value means source/dev or a mis-baked portable — never treat
            # those as Windows (would offer untagged zips that cannot run here).
            if sys.platform == "win32":
                return "windows"
            return _host_platform_tag()

    text = (version_str if version_str is not None else APP_VERSION_STR) or ""
    text = text.strip().lower()
    match = re.search(r"[-_](linux|steamdeck|windows|macos)\s*$", text)
    if match:
        return match.group(1)

    # Bare version (no suffix): from 40T onward → Windows stream for release tags.
    # Running app with no bake on a non-Windows host → host platform (see above).
    major_match = re.match(r"v?(\d+(?:\.\d+)?)", text)
    if major_match:
        try:
            if float(major_match.group(1)) >= 40.0 - 0.001:
                if version_str is None and sys.platform != "win32":
                    return _host_platform_tag()
                return "windows"
        except ValueError:
            pass
    if version_str is None and APP_VERSION_FLOAT >= 40.0 - 0.001:
        if sys.platform == "win32":
            return "windows"
        return _host_platform_tag()

    return _host_platform_tag()


def _host_platform_tag() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _asset_matches_platform(name: str, platform: str) -> bool:
    """True if this zip is clearly meant for ``platform``."""
    n = name.lower()
    markers = (f"_{platform}.", f"-{platform}.", f"_{platform}_", f"-{platform}-")
    return any(m in n for m in markers)


def _asset_is_other_platform(name: str, platform: str) -> bool:
    """True if zip is tagged for a different OS/channel than ``platform``."""
    n = name.lower()
    for other in ("windows", "linux", "macos", "darwin", "steamdeck"):
        if other == platform:
            continue
        if other == "darwin" and platform == "macos":
            continue
        if other == "macos" and platform == "darwin":
            continue
        if _asset_matches_platform(n, other):
            return True
        if other == "darwin" and _asset_matches_platform(n, "macos"):
            return True
    return False


def classify_release_platforms(assets: list[dict] | None) -> frozenset[str]:
    """Which install channels shipped zips on this GitHub release.

    * ``*_linux.zip`` / ``*-linux.zip`` → linux
    * ``*_steamdeck.zip`` → steamdeck
    * ``*_windows.zip`` → windows
    * untagged ``Steempeg_vX.zip`` (legacy) → windows (keeps old releases working)
    """
    found: set[str] = set()
    for asset in assets or []:
        name = str(asset.get("name") or "")
        if not name.lower().endswith(".zip"):
            continue
        if _asset_matches_platform(name, "linux"):
            found.add("linux")
        elif _asset_matches_platform(name, "steamdeck"):
            found.add("steamdeck")
        elif _asset_matches_platform(name, "windows"):
            found.add("windows")
        elif _asset_matches_platform(name, "macos") or _asset_matches_platform(name, "darwin"):
            found.add("macos")
        elif not _asset_is_other_platform(name, "windows"):
            # Untagged zip = Windows stream (pre-_windows naming).
            found.add("windows")
    return frozenset(found)


def find_zip_asset(assets: list[dict]) -> tuple[str | None, str | None, int | None, str | None]:
    """Pick the install zip for this build's update channel.

    Prefers ``*_windows.zip`` / ``*_linux.zip`` / ``*_steamdeck.zip``.
    On the Windows channel, untagged legacy ``Steempeg_vX.Y.zip`` is still accepted.
    Cross-channel zips are never chosen.
    """
    platform = release_platform_tag()
    zips = [a for a in (assets or []) if str(a.get("name") or "").lower().endswith(".zip")]

    def _unpack(asset: dict) -> tuple[str | None, str | None, int | None, str | None]:
        size = asset.get("size")
        try:
            size_i = int(size) if size is not None else None
        except (TypeError, ValueError):
            size_i = None
        digest = (asset.get("digest") or "").strip() or None
        return asset.get("browser_download_url"), asset.get("name"), size_i, digest

    for asset in zips:
        name = str(asset.get("name") or "")
        if _asset_matches_platform(name, platform):
            return _unpack(asset)
        if platform == "macos" and _asset_matches_platform(name, "darwin"):
            return _unpack(asset)

    # Windows channel only: untagged zip from the .exe / early-zip era.
    if platform == "windows":
        for asset in zips:
            name = str(asset.get("name") or "")
            if _asset_is_other_platform(name, platform):
                continue
            return _unpack(asset)

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
    assets = data.get("assets") or []
    available = classify_release_platforms(assets)
    zip_url, zip_name, zip_size, zip_sha256 = find_zip_asset(assets)
    era = classify_era(version_float)
    install_tier = classify_install_tier(version_float, zip_url)
    milestones = milestones_for_version(version_float)
    block_reason = _block_reason_for(install_tier, version_float)
    if block_reason is None and install_tier == InstallTier.NO_ZIP:
        block_reason = _missing_channel_block_reason(
            channel=release_platform_tag(),
            available=available,
            version_float=version_float,
        )

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
        installable=is_installable(version_float, zip_url, available_platforms=available),
        milestones=milestones,
        block_reason=block_reason,
        published_at=data.get("published_at") or "",
        zip_size=zip_size,
        zip_sha256=zip_sha256,
        available_platforms=available,
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


def fetch_releases(*, timeout: float = 10.0, save_cache: bool = True) -> list[ReleaseEntry]:
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
                if not entry:
                    continue
                # List every public release. Install is gated by zip for this channel
                # (icons show which platforms shipped; missing channel → no download).
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
    if save_cache:
        save_releases_cache(releases)
    return releases


_RELEASES_CACHE_FILENAME = "release_catalog.json"
# Silent title-bar probe can skip GitHub when the on-disk catalog is still fresh.
RELEASES_CACHE_MAX_AGE_SEC = 6 * 3600


def _releases_cache_path() -> str:
    from steempeg.infra.paths import get_save_directory

    return os.path.join(get_save_directory(), "cache", _RELEASES_CACHE_FILENAME)


def _milestone_to_dict(milestone: VersionMilestone) -> dict:
    return {
        "version": milestone.version,
        "icon": milestone.icon,
        "short_label": milestone.short_label,
        "detail": milestone.detail,
    }


def _entry_to_dict(entry: ReleaseEntry) -> dict:
    return {
        "tag_name": entry.tag_name,
        "name": entry.name,
        "version": list(entry.version),
        "version_str": entry.version_str,
        "version_float": entry.version_float,
        "html_url": entry.html_url,
        "body": entry.body,
        "zip_url": entry.zip_url,
        "zip_name": entry.zip_name,
        "era": entry.era.value,
        "install_tier": entry.install_tier.value,
        "installable": entry.installable,
        "milestones": [_milestone_to_dict(m) for m in entry.milestones],
        "block_reason": entry.block_reason,
        "published_at": entry.published_at,
        "zip_size": entry.zip_size,
        "zip_sha256": entry.zip_sha256,
        "available_platforms": sorted(entry.available_platforms),
    }


def _entry_from_dict(data: dict) -> ReleaseEntry | None:
    try:
        version = tuple(int(part) for part in (data.get("version") or []))
        if not version:
            return None
        era = VersionEra(str(data.get("era", VersionEra.RELIABLE.value)))
        install_tier = InstallTier(str(data.get("install_tier", InstallTier.NO_ZIP.value)))
        version_float = float(data.get("version_float", version_to_float(version)))
        # Always prefer live VERSION_MILESTONES so (i) badges update without a GitHub refetch.
        milestones = milestones_for_version(version_float)
        platforms = frozenset(str(p) for p in (data.get("available_platforms") or []))
        return ReleaseEntry(
            tag_name=str(data.get("tag_name") or ""),
            name=str(data.get("name") or ""),
            version=version,
            version_str=str(data.get("version_str") or format_version(version)),
            version_float=version_float,
            html_url=str(data.get("html_url") or ""),
            body=str(data.get("body") or ""),
            zip_url=data.get("zip_url"),
            zip_name=data.get("zip_name"),
            era=era,
            install_tier=install_tier,
            installable=bool(data.get("installable")),
            milestones=milestones,
            block_reason=data.get("block_reason"),
            published_at=str(data.get("published_at") or ""),
            zip_size=data.get("zip_size"),
            zip_sha256=data.get("zip_sha256"),
            available_platforms=platforms,
        )
    except (TypeError, ValueError):
        return None


def releases_cache_age_sec() -> float | None:
    """Seconds since the on-disk catalog was written, or None if missing."""
    path = _releases_cache_path()
    if not os.path.isfile(path):
        return None
    try:
        from steempeg.infra import cache as json_cache

        payload = json_cache.read_json(path, default={})
        fetched_at = float(payload.get("fetched_at", 0) or 0)
        if fetched_at <= 0:
            return None
        return max(0.0, time.time() - fetched_at)
    except (TypeError, ValueError, OSError):
        return None


def releases_cache_is_fresh(*, max_age_sec: float = RELEASES_CACHE_MAX_AGE_SEC) -> bool:
    age = releases_cache_age_sec()
    return age is not None and age <= max_age_sec


def load_releases_cache() -> list[ReleaseEntry] | None:
    """Return the last saved release catalog, or None if unreadable."""
    path = _releases_cache_path()
    if not os.path.isfile(path):
        return None
    try:
        from steempeg.infra import cache as json_cache

        payload = json_cache.read_json(path, default={})
        raw = payload.get("releases")
        if not isinstance(raw, list) or not raw:
            return None
        releases: list[ReleaseEntry] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            entry = _entry_from_dict(item)
            if entry is not None:
                releases.append(entry)
        if not releases:
            return None
        releases.sort(key=lambda entry: entry.version_float, reverse=True)
        return releases
    except Exception:
        logging.exception("RELEASE_CATALOG: failed reading cache")
        return None


def save_releases_cache(releases: list[ReleaseEntry]) -> None:
    if not releases:
        return
    try:
        from steempeg.infra import cache as json_cache

        payload = {
            "fetched_at": time.time(),
            "releases": [_entry_to_dict(entry) for entry in releases],
        }
        json_cache.write_json(_releases_cache_path(), payload)
    except Exception:
        logging.exception("RELEASE_CATALOG: failed writing cache")


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
