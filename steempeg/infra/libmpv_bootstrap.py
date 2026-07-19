"""Locate / preload bundled libmpv before ``import mpv`` (python-mpv).

On Linux, ctypes.util.find_library('mpv') only looks at the system cache and
often misses Fedora's ``libmpv.so.2`` (no unversioned ``.so``) or our
``bin/`` copy next to the frozen app. End users should not install system
mpv or run ldconfig hacks — we ship the library with the release zip.

Note: changing LD_LIBRARY_PATH after process start does not affect dlopen on
glibc, so we CDLL every bundled .so with RTLD_GLOBAL before import mpv.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import glob
import os
import sys


def _candidate_dirs() -> list[str]:
    dirs: list[str] = []
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        meipass = getattr(sys, "_MEIPASS", None)
        for root in (
            exe_dir,
            os.path.join(exe_dir, "bin"),
            os.path.join(exe_dir, "bin", "mpv"),
            os.path.join(exe_dir, "_internal"),
            os.path.join(exe_dir, "_internal", "bin"),
            meipass,
            os.path.join(meipass, "bin") if meipass else None,
        ):
            if root and root not in dirs:
                dirs.append(root)
    else:
        # steempeg/infra/this.py → repo root
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for root in (
            os.path.join(repo, "bin", "linux"),
            os.path.join(repo, "bin", "linux", "mpv"),
            os.path.join(repo, "bin"),
        ):
            if os.path.isdir(root) and root not in dirs:
                dirs.append(root)
    return dirs


def _lib_names() -> tuple[str, ...]:
    return (
        "libmpv.so.2",
        "libmpv.so.1",
        "libmpv.so",
    )


def find_bundled_libmpv() -> str | None:
    for directory in _candidate_dirs():
        for name in _lib_names():
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                return os.path.realpath(path)
    return None


def _preload_bundle_dir(directory: str) -> None:
    """Load every shared object in directory with RTLD_GLOBAL (deps before use)."""
    if not os.path.isdir(directory):
        return
    mode = getattr(ctypes, "RTLD_GLOBAL", 0) or 0
    # Several passes: missing deps may succeed once siblings are loaded.
    paths = []
    for pattern in ("*.so", "*.so.*"):
        paths.extend(glob.glob(os.path.join(directory, pattern)))
    # Prefer real files; skip dangling names
    unique: list[str] = []
    seen: set[str] = set()
    for p in paths:
        rp = os.path.realpath(p)
        if rp in seen or not os.path.isfile(rp):
            continue
        seen.add(rp)
        unique.append(rp)

    # libmpv last so its deps are already global
    unique.sort(key=lambda p: (1 if "libmpv" in os.path.basename(p) else 0, p))

    pending = list(unique)
    for _ in range(8):
        if not pending:
            break
        still: list[str] = []
        for path in pending:
            try:
                ctypes.CDLL(path, mode=mode)
            except OSError:
                still.append(path)
        if len(still) == len(pending):
            break
        pending = still


def bootstrap_libmpv() -> str | None:
    """Patch find_library so ``import mpv`` resolves our copy.

    Returns the path that will be used, or None if nothing bundled (falls back
    to system libmpv).
    """
    if sys.platform == "win32":
        # Windows build already ships mpv-2.dll on PATH via app.py bin/ prepend.
        return None

    lib_dirs = [d for d in _candidate_dirs() if os.path.isdir(d)]
    for d in lib_dirs:
        _preload_bundle_dir(d)

    bundled = find_bundled_libmpv()
    if not bundled:
        return None

    os.environ["MPV_LIBRARY_PATH"] = bundled

    _orig = ctypes.util.find_library

    def _find(name: str):
        if name in ("mpv", "libmpv"):
            return bundled
        return _orig(name)

    ctypes.util.find_library = _find  # type: ignore[assignment]

    mode = getattr(ctypes, "RTLD_GLOBAL", 0) or 0
    try:
        ctypes.CDLL(bundled, mode=mode)
    except OSError:
        pass

    return bundled
