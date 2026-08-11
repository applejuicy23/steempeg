#!/usr/bin/env python3
"""Dump all GitHub Releases (+ orphan tags) into a local .txt file.

Usage (repo root, needs `gh` auth):
  python scripts/dump_github_changelogs.py
  python scripts/dump_github_changelogs.py --out docs/github_changelogs_dump.txt

Requires: GitHub CLI (`gh`) logged in (`gh auth status`).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "docs" / "github_changelogs_dump.txt"
DEFAULT_REPO = "applejuicy23/steempeg"


def run_gh_json(args: list[str]) -> object:
    """Run `gh … --jq`/`gh api` and parse JSON stdout."""
    cmd = ["gh", *args]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        print("error: `gh` not found on PATH. Install GitHub CLI and retry.", file=sys.stderr)
        sys.exit(1)

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        print(f"error: {' '.join(cmd)}\n{err}", file=sys.stderr)
        sys.exit(proc.returncode or 1)

    text = (proc.stdout or "").strip()
    if not text:
        return []
    return json.loads(text)


def fetch_releases(repo: str) -> list[dict]:
    # --paginate merges JSON arrays; do NOT combine with --jq (breaks merging).
    data = run_gh_json(["api", "--paginate", f"repos/{repo}/releases"])
    if not isinstance(data, list):
        print("error: unexpected releases payload (expected JSON array)", file=sys.stderr)
        sys.exit(1)
    slim: list[dict] = []
    for r in data:
        if not isinstance(r, dict):
            continue
        slim.append(
            {
                "tag_name": r.get("tag_name"),
                "name": r.get("name"),
                "published_at": r.get("published_at"),
                "created_at": r.get("created_at"),
                "draft": r.get("draft"),
                "prerelease": r.get("prerelease"),
                "html_url": r.get("html_url"),
                "body": r.get("body"),
            }
        )
    return slim


def fetch_tags(repo: str) -> list[str]:
    data = run_gh_json(["api", "--paginate", f"repos/{repo}/tags"])
    if not isinstance(data, list):
        print("error: unexpected tags payload (expected JSON array)", file=sys.stderr)
        sys.exit(1)
    names: list[str] = []
    for t in data:
        if isinstance(t, dict) and t.get("name"):
            names.append(str(t["name"]))
        elif isinstance(t, str):
            names.append(t)
    return names


def format_date(iso: str | None) -> str:
    if not iso:
        return "(no date)"
    try:
        # GitHub returns e.g. 2024-01-15T12:34:56Z
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return iso


def write_dump(repo: str, releases: list[dict], tags: list[str], out_path: Path) -> None:
    release_tags = {str(r.get("tag_name") or "") for r in releases}
    orphan_tags = [t for t in tags if t not in release_tags]

    # Newest first (API already returns newest-first for releases)
    lines: list[str] = []
    lines.append(f"GitHub changelogs dump — {repo}")
    lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"Releases: {len(releases)}")
    lines.append(f"Tags (all): {len(tags)}")
    lines.append(f"Tags without a GitHub Release: {len(orphan_tags)}")
    lines.append("=" * 72)
    lines.append("")

    for i, rel in enumerate(releases, 1):
        tag = rel.get("tag_name") or "(no tag)"
        name = rel.get("name") or ""
        published = format_date(rel.get("published_at") or rel.get("created_at"))
        flags: list[str] = []
        if rel.get("draft"):
            flags.append("draft")
        if rel.get("prerelease"):
            flags.append("prerelease")
        flag_s = f" [{', '.join(flags)}]" if flags else ""
        url = rel.get("html_url") or ""
        body = (rel.get("body") or "").strip() or "(empty release body)"

        lines.append("-" * 72)
        lines.append(f"#{i}  {tag}{flag_s}")
        if name and name != tag:
            lines.append(f"Title: {name}")
        lines.append(f"Published: {published}")
        if url:
            lines.append(f"URL: {url}")
        lines.append("")
        lines.append(body)
        lines.append("")

    lines.append("=" * 72)
    lines.append("TAGS WITHOUT A GITHUB RELEASE")
    lines.append("=" * 72)
    if orphan_tags:
        lines.append(
            "These tags exist on the repo but have no matching GitHub Release "
            "(no release notes body via Releases API):"
        )
        lines.append("")
        for t in orphan_tags:
            lines.append(f"  - {t}")
    else:
        lines.append("(none — every tag has a Release)")
    lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump GitHub release changelogs to a .txt file.")
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help=f"owner/name (default: {DEFAULT_REPO})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"output path (default: {DEFAULT_OUT})",
    )
    args = parser.parse_args()
    out_path = args.out if args.out.is_absolute() else (REPO_ROOT / args.out)

    print(f"Fetching releases from {args.repo} …")
    releases = fetch_releases(args.repo)
    print(f"  {len(releases)} release(s)")

    print(f"Fetching tags from {args.repo} …")
    tags = fetch_tags(args.repo)
    print(f"  {len(tags)} tag(s)")

    write_dump(args.repo, releases, tags, out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
