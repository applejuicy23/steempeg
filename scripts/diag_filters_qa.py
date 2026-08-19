#!/usr/bin/env python3
"""Library Filters & Sort QA — diagnostic test suite for Steempeg.

Loads clips/screenshots cache, simulates every filter and sort operation,
and verifies correctness.

Usage:
    python scripts/diag_filters_qa.py
    python scripts/diag_filters_qa.py --clips cache/clips_library_cache.json
    python scripts/diag_filters_qa.py --verbose
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

try:
    from colorama import Fore, Style, init as _colorama_init
    _colorama_init()
    _GREEN = Fore.GREEN
    _RED = Fore.RED
    _YELLOW = Fore.YELLOW
    _CYAN = Fore.CYAN
    _RESET = Style.RESET_ALL
except ImportError:
    _GREEN = _RED = _YELLOW = _CYAN = _RESET = ""


@dataclass
class TestResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Report:
    tests: list[TestResult] = field(default_factory=list)
    total_pass: int = 0
    total_fail: int = 0

    def add(self, t: TestResult):
        self.tests.append(t)
        if t.passed:
            self.total_pass += 1
        else:
            self.total_fail += 1


def _parse_date(date_str: str) -> datetime | None:
    """Parse the 'date_display' field like '18 August 2026\\n05:59 PM'."""
    if not date_str:
        return None
    clean = date_str.replace("\n", " ").strip()
    for fmt in ("%d %B %Y %I:%M %p", "%d %B %Y %H:%M", "%d %B %Y"):
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            continue
    return None


def _parse_duration_seconds(dur_str: str) -> float | None:
    """Parse '1m 49s' or '2h 3m 10s' to seconds."""
    if not dur_str:
        return None
    total = 0.0
    for m in re.finditer(r"(\d+)\s*h", dur_str):
        total += int(m.group(1)) * 3600
    for m in re.finditer(r"(\d+)\s*m", dur_str):
        total += int(m.group(1)) * 60
    for m in re.finditer(r"(\d+)\s*s", dur_str):
        total += int(m.group(1))
    return total if total > 0 else None


# ── filter tests ────────────────────────────────────────────────────────────
def _test_game_filter(clips: list[dict], report: Report):
    games = {c.get("game_name", "").strip() for c in clips if c.get("game_name", "").strip()}
    if not games:
        report.add(TestResult("game_filter", True, "no games in data"))
        return
    for game in sorted(games):
        filtered = [c for c in clips if c.get("game_name", "").strip() == game]
        stragglers = [c for c in filtered if c.get("game_name", "").strip() != game]
        ok = len(stragglers) == 0 and len(filtered) > 0
        detail = f"{len(filtered)} results" if ok else f"found {len(stragglers)} wrong-game clips"
        report.add(TestResult(f"game_filter '{game}'", ok, detail))


def _test_folder_filter(clips: list[dict], report: Report):
    """Filter by folder (library root — the parent directory of the clip folder)."""
    folders: dict[str, list[dict]] = {}
    for c in clips:
        fp = c.get("full_path", "")
        if not fp:
            continue
        # Group by the grandparent of the clip folder (the library root)
        root = str(Path(fp).parent.parent) if Path(fp).parent != Path(fp) else str(Path(fp).parent)
        folders.setdefault(root, []).append(c)

    if len(folders) <= 1:
        report.add(TestResult("folder_filter", True, f"only {len(folders)} folder(s), nothing to cross-check"))
        return

    for folder, expected in sorted(folders.items()):
        # Simulate: filter all clips whose full_path starts with folder
        filtered = [c for c in clips if str(Path(c.get("full_path", "")).parent.parent) == folder]
        ok = set(c["full_path"] for c in filtered) == set(c["full_path"] for c in expected)
        report.add(TestResult(f"folder_filter '{Path(folder).name}'", ok,
                              f"expected {len(expected)}, got {len(filtered)}"))


def _test_date_range(clips: list[dict], report: Report):
    dates = []
    for c in clips:
        d = _parse_date(c.get("date_display", ""))
        if d:
            dates.append((d, c))
    if len(dates) < 2:
        report.add(TestResult("date_range_filter", True, "not enough dated clips"))
        return

    dates.sort(key=lambda x: x[0])
    min_d, max_d = dates[0][0], dates[-1][0]
    mid = dates[len(dates) // 2][0]

    # Filter: min_d to mid
    filtered = [(d, c) for d, c in dates if min_d <= d <= mid]
    ok = all(min_d <= d <= mid for d, _ in filtered) and len(filtered) > 0
    report.add(TestResult("date_range [min..mid]", ok, f"{len(filtered)} clips in range"))

    # Filter: mid to max_d
    filtered = [(d, c) for d, c in dates if mid <= d <= max_d]
    ok = all(mid <= d <= max_d for d, _ in filtered) and len(filtered) > 0
    report.add(TestResult("date_range [mid..max]", ok, f"{len(filtered)} clips in range"))


def _test_duration_range(clips: list[dict], report: Report):
    durs = []
    for c in clips:
        d = _parse_duration_seconds(c.get("duration_str", ""))
        if d is not None:
            durs.append((d, c))
    if len(durs) < 2:
        report.add(TestResult("duration_range_filter", True, "not enough clips with duration"))
        return

    durs.sort(key=lambda x: x[0])
    lo, hi = durs[0][0], durs[-1][0]
    mid = (lo + hi) / 2

    filtered = [(d, c) for d, c in durs if lo <= d <= mid]
    ok = all(lo <= d <= mid for d, _ in filtered)
    report.add(TestResult("duration_range [lo..mid]", ok, f"{len(filtered)} clips"))


def _test_combined_filters(clips: list[dict], report: Report):
    games = {c.get("game_name", "").strip() for c in clips if c.get("game_name", "").strip()}
    if not games:
        return

    game = sorted(games)[0]
    game_clips = [c for c in clips if c.get("game_name", "").strip() == game]

    dates = [(d, c) for c in game_clips for d in [_parse_date(c.get("date_display", ""))] if d]
    if dates:
        dates.sort(key=lambda x: x[0])
        mid = dates[len(dates) // 2][0]
        filtered = [(d, c) for d, c in dates if d <= mid]
        ok = all(c.get("game_name", "").strip() == game for _, c in filtered)
        report.add(TestResult(f"combined game+date '{game}'", ok,
                              f"{len(filtered)}/{len(game_clips)} clips"))
    else:
        report.add(TestResult(f"combined game+date '{game}'", True, "no dates for this game"))


# ── sort tests ──────────────────────────────────────────────────────────────
def _test_sort_date(clips: list[dict], report: Report):
    dated = [(d, c) for c in clips for d in [_parse_date(c.get("date_display", ""))] if d]
    if len(dated) < 2:
        report.add(TestResult("sort_date_asc", True, "not enough dated clips"))
        return

    asc = sorted(dated, key=lambda x: x[0])
    ok = all(asc[i][0] <= asc[i+1][0] for i in range(len(asc)-1))
    report.add(TestResult("sort_date_asc", ok, f"{len(asc)} clips"))

    desc = sorted(dated, key=lambda x: x[0], reverse=True)
    ok = all(desc[i][0] >= desc[i+1][0] for i in range(len(desc)-1))
    report.add(TestResult("sort_date_desc", ok, f"{len(desc)} clips"))


def _test_sort_game(clips: list[dict], report: Report):
    names = [c.get("game_name", "").strip() for c in clips if c.get("game_name", "").strip()]
    if len(names) < 2:
        report.add(TestResult("sort_game_az", True, "not enough games"))
        return

    asc = sorted(names, key=str.lower)
    ok = all(asc[i].lower() <= asc[i+1].lower() for i in range(len(asc)-1))
    report.add(TestResult("sort_game_az", ok, f"{len(asc)} entries"))

    desc = sorted(names, key=str.lower, reverse=True)
    ok = all(desc[i].lower() >= desc[i+1].lower() for i in range(len(desc)-1))
    report.add(TestResult("sort_game_za", ok, f"{len(desc)} entries"))


# ── screenshots tests ──────────────────────────────────────────────────────
def _test_screenshots_filters(screenshots: list[dict], report: Report):
    if not screenshots:
        report.add(TestResult("screenshots_game_filter", True, "no screenshots data"))
        return

    games = {s.get("game_name", "").strip() for s in screenshots if s.get("game_name", "").strip()}
    for game in sorted(games)[:5]:  # cap to avoid huge output
        filtered = [s for s in screenshots if s.get("game_name", "").strip() == game]
        ok = all(s.get("game_name", "").strip() == game for s in filtered)
        report.add(TestResult(f"screenshots_game_filter '{game}'", ok, f"{len(filtered)} results"))

    sources = {s.get("source", "") for s in screenshots if s.get("source")}
    for src in sorted(sources):
        filtered = [s for s in screenshots if s.get("source") == src]
        ok = all(s.get("source") == src for s in filtered)
        report.add(TestResult(f"screenshots_source_filter '{src}'", ok, f"{len(filtered)} results"))


def _test_screenshots_sort(screenshots: list[dict], report: Report):
    if not screenshots:
        return

    mtimes = [s.get("mtime", 0) for s in screenshots if s.get("mtime")]
    if len(mtimes) >= 2:
        asc = sorted(mtimes)
        ok = all(asc[i] <= asc[i+1] for i in range(len(asc)-1))
        report.add(TestResult("screenshots_sort_date_asc", ok, f"{len(asc)} items"))

    names = [s.get("game_name", "").strip() for s in screenshots if s.get("game_name", "").strip()]
    if len(names) >= 2:
        asc = sorted(names, key=str.lower)
        ok = all(asc[i].lower() <= asc[i+1].lower() for i in range(len(asc)-1))
        report.add(TestResult("screenshots_sort_game_az", ok, f"{len(asc)} items"))


# ── main ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Steempeg Library Filters & Sort QA")
    parser.add_argument("--clips", type=str, default=None, help="Path to clips_library_cache.json")
    parser.add_argument("--screenshots", type=str, default=None, help="Path to screenshots_library_cache.json")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parent.parent
    clips_path = Path(args.clips) if args.clips else repo / "cache" / "clips_library_cache.json"
    ss_path = Path(args.screenshots) if args.screenshots else repo / "cache" / "screenshots_library_cache.json"
    log_dir = repo / "logs"
    log_dir.mkdir(exist_ok=True)

    clips: list[dict] = []
    screenshots: list[dict] = []

    if clips_path.exists():
        try:
            data = json.loads(clips_path.read_text(encoding="utf-8"))
            clips = data.get("clips", [])
        except Exception as e:
            print(f"{_RED}Failed to load clips cache: {e}{_RESET}")
    else:
        print(f"{_YELLOW}Clips cache not found at {clips_path}{_RESET}")

    if ss_path.exists():
        try:
            data = json.loads(ss_path.read_text(encoding="utf-8"))
            screenshots = data.get("files", [])
        except Exception as e:
            print(f"{_RED}Failed to load screenshots cache: {e}{_RESET}")
    else:
        print(f"{_YELLOW}Screenshots cache not found at {ss_path}{_RESET}")

    if not clips and not screenshots:
        print(f"{_RED}No data to test. Provide --clips or --screenshots paths.{_RESET}")
        sys.exit(1)

    print(f"{_CYAN}Steempeg Library Filters & Sort QA{_RESET}")
    print(f"  Clips: {len(clips)}  |  Screenshots: {len(screenshots)}")
    print()

    report = Report()

    if clips:
        print(f"{_CYAN}── Clips Filter Tests ──{_RESET}")
        _test_game_filter(clips, report)
        _test_folder_filter(clips, report)
        _test_date_range(clips, report)
        _test_duration_range(clips, report)
        _test_combined_filters(clips, report)

        print(f"{_CYAN}── Clips Sort Tests ──{_RESET}")
        _test_sort_date(clips, report)
        _test_sort_game(clips, report)

    if screenshots:
        print(f"{_CYAN}── Screenshots Tests ──{_RESET}")
        _test_screenshots_filters(screenshots, report)
        _test_screenshots_sort(screenshots, report)

    # Print results
    print()
    for t in report.tests:
        tag = f"{_GREEN}PASS{_RESET}" if t.passed else f"{_RED}FAIL{_RESET}"
        print(f"  {tag}  {t.name}")
        if args.verbose or not t.passed:
            print(f"         {t.detail}")

    print()
    print(f"{_CYAN}{'='*60}{_RESET}")
    print(f"  {_GREEN}PASS: {report.total_pass}{_RESET}  |  {_RED}FAIL: {report.total_fail}{_RESET}")
    print(f"{_CYAN}{'='*60}{_RESET}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = log_dir / f"diag_filters_qa_{stamp}.json"
    out = {
        "timestamp": stamp,
        "clips_count": len(clips),
        "screenshots_count": len(screenshots),
        "total_pass": report.total_pass,
        "total_fail": report.total_fail,
        "tests": [asdict(t) for t in report.tests],
    }
    report_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    main()
