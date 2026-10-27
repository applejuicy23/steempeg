"""Build the public changelog JSON from GitHub releases plus a local overlay.

GitHub stays the source of the release text. ``website/changelog/vNN/`` can add
bullets and screenshots (``notes.md`` and image files). The script writes a
light ``index.json`` and one ``vNN.json`` per version. Generated files are not
committed; Pages runs this on each deploy.

The three filter buckets are New, Improvements and Fixes. Anything else
(known issues, compare links) is kept on the version as ``other`` so it is
not thrown away.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = "applejuicy23/steempeg"
API_URL = f"https://api.github.com/repos/{REPO}/releases"
BUCKETS = ("new", "improvements", "fixes")

# Emoji may sit outside the bold markers: ``📝 **BUGFIXES:**``.
_HEADING_BOLD_RE = re.compile(r"^(?:[^\w*]+\s*)?\*\*(.+?)\*\*:?\s*$")
_HEADING_HASH_RE = re.compile(r"^#{1,3}\s+(.+?)\s*$")
_BULLET_RE = re.compile(r"^[-*•]\s+(.+)$")
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_HTML_IMAGE_RE = re.compile(
    r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"'][^>]*>",
    re.IGNORECASE,
)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def classify_section(heading: str) -> str:
    """Map a release heading onto new, improvements, fixes, or other."""
    text = heading.lower()
    if "new feature" in text or text.startswith("new") or "🚀" in heading:
        return "new"
    if any(word in text for word in ("fix", "bug")) or "📝" in heading:
        return "fixes"
    if "improv" in text or "✨" in heading:
        return "improvements"
    return "other"


def _heading_of(line: str) -> str | None:
    """Return the heading text when ``line`` is a section title."""
    bold = _HEADING_BOLD_RE.match(line)
    if bold:
        return bold.group(1).strip().rstrip(":").strip()
    hashed = _HEADING_HASH_RE.match(line)
    if hashed:
        return hashed.group(1).strip().rstrip(":").strip()
    return None


def _images_in(line: str) -> list[str]:
    """Pull markdown and HTML image URLs out of one line."""
    found = [match.group(2).strip() for match in _MD_IMAGE_RE.finditer(line)]
    found.extend(match.group(1).strip() for match in _HTML_IMAGE_RE.finditer(line))
    return found


def _plain_text(line: str) -> str:
    """Drop images and bold markers, keep link labels."""
    without_images = _HTML_IMAGE_RE.sub("", _MD_IMAGE_RE.sub("", line))
    without_links = _MD_LINK_RE.sub(r"\1", without_images)
    return _BOLD_RE.sub(r"\1", without_links).strip()


def parse_release_notes(body: str) -> dict[str, list[dict]]:
    """Split a GitHub release body into filter buckets.

    Each item is ``{"text": str, "images": [urls]}``. A picture that sits on
    its own line belongs to the bullet above it.
    """
    sections: dict[str, list[dict]] = {name: [] for name in (*BUCKETS, "other")}
    current = "other"
    item: dict | None = None

    def flush() -> None:
        nonlocal item
        if item is None:
            return
        text = str(item.get("text") or "").strip()
        images = [url for url in item.get("images") or [] if url]
        if text or images:
            sections[current].append({"text": text, "images": images})
        item = None

    for raw in (body or "").splitlines():
        line = raw.strip()
        if not line or set(line) <= {"-", "*"}:
            continue
        lowered = line.lower()
        if lowered.startswith("**full changelog") or lowered.startswith("full changelog"):
            continue
        heading = _heading_of(line)
        if heading is not None:
            flush()
            current = classify_section(heading)
            continue
        images = _images_in(line)
        text = _plain_text(line)
        bullet = _BULLET_RE.match(text)
        if bullet:
            flush()
            item = {"text": bullet.group(1).strip(), "images": images}
            continue
        if images and not text:
            if item is None:
                item = {"text": "", "images": []}
            item["images"].extend(images)
            continue
        if item is not None and text:
            item["text"] = f"{item['text']} {text}".strip()
            item["images"].extend(images)
    flush()
    return sections


def _empty_sections() -> dict[str, list[dict]]:
    return {name: [] for name in (*BUCKETS, "other")}


def _merge_sections(base: dict[str, list[dict]], extra: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Append overlay bullets after the GitHub ones."""
    merged = _empty_sections()
    for name in merged:
        merged[name] = list(base.get(name) or []) + list(extra.get(name) or [])
    return merged


def _version_label(tag: str, name: str) -> str:
    """Folder and file stem: ``v55.1``."""
    raw = (tag or name or "").strip()
    match = re.search(r"(\d+(?:\.\d+)*)", raw)
    if not match:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-") or "unknown"
        return safe if safe.startswith("v") else f"v{safe}"
    return f"v{match.group(1)}"


def _date_only(published: str) -> str:
    """``2026-10-21T12:00:00Z`` → ``2026-10-21``."""
    text = (published or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return ""


def _rewrite_overlay_images(
    sections: dict[str, list[dict]],
    version_dir: Path,
    public_prefix: str,
) -> dict[str, list[dict]]:
    """Point relative overlay pictures at the path Pages will serve."""
    rewritten: dict[str, list[dict]] = {}
    for name, items in sections.items():
        rewritten[name] = []
        for item in items:
            images: list[str] = []
            for url in item.get("images") or []:
                if url.startswith(("http://", "https://", "/")):
                    images.append(url)
                    continue
                local = (version_dir / url).resolve()
                if local.is_file():
                    images.append(f"{public_prefix}/{local.name}")
            rewritten[name].append({"text": item.get("text") or "", "images": images})
    return rewritten


def _copy_overlay_images(version_dir: Path, dest_dir: Path) -> None:
    """Copy screenshot files next to that version's JSON."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for path in version_dir.iterdir():
        if not path.is_file() or path.name.lower() == "notes.md":
            continue
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            continue
        shutil.copy2(path, dest_dir / path.name)


def _counts(sections: dict[str, list[dict]]) -> dict[str, int]:
    return {name: len(sections.get(name) or []) for name in BUCKETS}


def load_majors(overlay_root: Path) -> dict[str, tuple[str, str]]:
    """Read ``majors.json``. Each version has a short label and a hover detail.

    A plain string is just the label. An object is ``{"label", "detail"}``.
    """
    path = overlay_root / "majors.json"
    if not path.is_file():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(loaded, dict):
        return {}
    majors: dict[str, tuple[str, str]] = {}
    for key, value in loaded.items():
        if isinstance(value, str):
            label, detail = value.strip(), ""
        elif isinstance(value, dict):
            label = str(value.get("label") or "").strip()
            detail = str(value.get("detail") or "").strip()
        else:
            continue
        if label:
            majors[str(key).strip()] = (label, detail)
    return majors


def _major_lookup_key(version: str) -> str:
    """``50.0`` and ``50`` are the same major. ``50.1`` stays a patch."""
    parts = version.split(".")
    while len(parts) > 1 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


def major_for(version: str, majors: dict[str, tuple[str, str]]) -> tuple[str, str]:
    """Return ``(label, detail)`` for this version, or two empty strings."""
    return majors.get(_major_lookup_key(version), ("", ""))


def build_version(
    release: dict,
    overlay_root: Path,
    out_dir: Path,
    majors: dict[str, tuple[str, str]] | None = None,
) -> dict | None:
    """Write one ``vNN.json`` and return its index row, or None when it has no version."""
    tag = str(release.get("tag_name") or "")
    name = str(release.get("name") or tag)
    label = _version_label(tag, name)
    if label == "vunknown":
        return None
    sections = parse_release_notes(str(release.get("body") or ""))
    overlay_dir = overlay_root / label
    if overlay_dir.is_dir():
        notes_path = overlay_dir / "notes.md"
        if notes_path.is_file():
            extra = parse_release_notes(notes_path.read_text(encoding="utf-8"))
            sections = _merge_sections(sections, extra)
        sections = _rewrite_overlay_images(sections, overlay_dir, label)
        _copy_overlay_images(overlay_dir, out_dir / label)
    payload = {
        "version": label[1:] if label.startswith("v") else label,
        "tag": tag,
        "title": name,
        "date": _date_only(str(release.get("published_at") or "")),
        "html_url": str(release.get("html_url") or ""),
        "sections": sections,
    }
    major, major_detail = major_for(payload["version"], majors or {})
    if major:
        payload["major"] = major
        if major_detail:
            payload["major_detail"] = major_detail
    (out_dir / f"{label}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    counts = _counts(sections)
    return {
        "version": payload["version"],
        "tag": tag,
        "title": name,
        "date": payload["date"],
        "counts": counts,
        "major": major,
        "major_detail": major_detail,
        "file": f"{label}.json",
    }


def build_changelog(releases: list[dict], overlay_root: Path, out_dir: Path) -> dict:
    """Write ``index.json`` and every version file. Returns the index payload."""
    out_dir.mkdir(parents=True, exist_ok=True)
    majors = load_majors(overlay_root)
    rows: list[dict] = []
    for release in releases:
        if release.get("draft"):
            continue
        row = build_version(release, overlay_root, out_dir, majors)
        if row is not None:
            rows.append(row)
    index = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "versions": rows,
    }
    (out_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "releases.json").write_text(
        json.dumps(
            {"releases": [_catalog_release(item, overlay_root) for item in releases if not item.get("draft")]},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return index


def _catalog_release(release: dict, overlay_root: Path) -> dict:
    """One release in the shape Update Center already parses, without the GitHub API.

    Only zip assets are kept: the app installs from those. The installer exe
    is not an update download.
    """
    assets = []
    for asset in release.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        if not name.lower().endswith(".zip"):
            continue
        assets.append(
            {
                "name": name,
                "browser_download_url": asset.get("browser_download_url") or "",
                "size": asset.get("size"),
                "digest": asset.get("digest") or "",
            }
        )
    tag = str(release.get("tag_name") or "")
    name = str(release.get("name") or tag)
    body = str(release.get("body") or "")
    notes = overlay_root / _version_label(tag, name) / "notes.md"
    if notes.is_file():
        extra = notes.read_text(encoding="utf-8").strip()
        if extra:
            body = body.rstrip() + "\n\n" + extra
    return {
        "tag_name": tag,
        "name": name,
        "body": body,
        "html_url": release.get("html_url") or "",
        "published_at": release.get("published_at") or "",
        "draft": False,
        "assets": assets,
    }


def fetch_releases(token: str | None = None) -> list[dict]:
    """Download every public GitHub release, newest first, skipping drafts."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Steempeg-Changelog",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    releases: list[dict] = []
    page = 1
    while True:
        request = urllib.request.Request(
            f"{API_URL}?per_page=100&page={page}",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                batch = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"GitHub releases returned {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise SystemExit(f"Could not reach GitHub: {exc.reason}") from exc
        if not isinstance(batch, list) or not batch:
            break
        releases.extend(item for item in batch if isinstance(item, dict) and not item.get("draft"))
        if len(batch) < 100:
            break
        page += 1
    return releases


def main(argv: list[str] | None = None) -> None:
    """Build the changelog JSON into ``--out`` (default ``public/changelog``)."""
    parser = argparse.ArgumentParser(description="Build the Steempeg changelog JSON.")
    parser.add_argument(
        "--out",
        default="public/changelog",
        help="Directory for index.json, vNN.json and overlay images.",
    )
    parser.add_argument(
        "--overlay",
        default="website/changelog",
        help="Folder of vNN/notes.md and screenshots.",
    )
    parser.add_argument(
        "--from-json",
        default="",
        help="Read a saved GitHub releases array instead of calling the API.",
    )
    args = parser.parse_args(argv)
    if args.from_json:
        loaded = json.loads(Path(args.from_json).read_text(encoding="utf-8-sig"))
        if not isinstance(loaded, list):
            raise SystemExit("--from-json must be a list of GitHub release objects")
        releases = [item for item in loaded if isinstance(item, dict)]
    else:
        releases = fetch_releases(os.environ.get("GITHUB_TOKEN") or None)
    index = build_changelog(releases, Path(args.overlay), Path(args.out))
    print(f"changelog: {len(index['versions'])} versions → {args.out}")


if __name__ == "__main__":
    main(sys.argv[1:])
