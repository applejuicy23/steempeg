#!/usr/bin/env python3
"""Refresh ``bin/linux/mpv`` from the host libmpv (Fedora/Bazzite preferred).

Used by pack builds via ``newver_compilator.harvest_libmpv_bundle``. Run this
manually when preparing a DASH-capable Linux engine tree for v50
(native live ``.mpd`` — remux bridge retired):

  python scripts/harvest_linux_libmpv.py
  python scripts/harvest_linux_libmpv.py --check-only

Requires: mpv-libs (rpm) or libmpv1 (apt), patchelf recommended.
Refuse Homebrew by default (mux-only DASH + Mesa poison).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from newver_compilator import (  # noqa: E402
    _bundle_avformat_path,
    _lavf_has_dash_demux_bytes,
    harvest_libmpv_bundle,
)


def _default_dest() -> str:
    return os.path.join(_REPO, "bin", "linux", "mpv")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        default=_default_dest(),
        help="Output directory (default: bin/linux/mpv)",
    )
    parser.add_argument(
        "--allow-brew",
        action="store_true",
        help="Allow Homebrew libmpv (not recommended; often E dash only)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only report whether dest lavf has DASH demux; do not rewrite",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Do not wipe dest before harvest (merge/overwrite)",
    )
    args = parser.parse_args()
    dest = os.path.abspath(args.dest)

    if args.check_only:
        av = _bundle_avformat_path(dest) if os.path.isdir(dest) else None
        if not av:
            print(f"NO lavf in {dest}")
            return 2
        ok = _lavf_has_dash_demux_bytes(av)
        print(f"{'YES' if ok else 'NO'} DASH demux in {av}")
        return 0 if ok else 1

    if os.path.isdir(dest) and not args.keep:
        print(f"Clearing {dest} …")
        shutil.rmtree(dest)
    os.makedirs(dest, exist_ok=True)

    n = harvest_libmpv_bundle(dest, allow_brew=bool(args.allow_brew))
    if n <= 0:
        return 1
    from newver_compilator import _slim_mpv_bundle

    freed = _slim_mpv_bundle(dest)
    if freed:
        print(f"   slimmed optional deps: {freed / (1024 * 1024):.1f} MiB")
    av = _bundle_avformat_path(dest)
    if not av or not _lavf_has_dash_demux_bytes(av):
        print("Harvest finished but DASH demux was not detected — refusing success.")
        return 1
    print(f"Ready: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
