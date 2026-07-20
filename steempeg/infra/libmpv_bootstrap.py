"""Locate / preload bundled libmpv before ``import mpv`` (python-mpv).

On Linux, ctypes.util.find_library('mpv') only looks at the system cache and
often misses Fedora's ``libmpv.so.2`` (no unversioned ``.so``) or our
``bin/`` copy next to the frozen app. End users should not install system
mpv or run ldconfig hacks — we ship the library with the release zip.

Critical (NVIDIA / Bazzite): never RTLD_GLOBAL-preload Homebrew Mesa
(``libgallium``, ``libLLVM``, ``libEGL``, …). That hijacks Qt's GL stack and
hard-freezes the UI on XWayland. ``./run-linux.sh`` works because it does not
do that — only ``LD_LIBRARY_PATH`` for mpv, after Qt is free to use NVIDIA.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import glob
import os
import sys

# Shared objects that must NEVER be force-loaded into the Qt process.
_GL_POISON_PREFIXES = (
    "libgallium",
    "libLLVM",
    "libGL.so",
    "libGLX",
    "libGLdispatch",
    "libEGL.so",
    "libGLESv",
    "libOpenGL.so",
    "libglapi",
    "libvulkan",
    "libdrm_amdgpu",
    "libdrm_intel",
    "libdrm_radeon",
    "libdrm_nouveau",
    "libxcb-glx",
    "libX11",  # let Qt/system resolve display libs
    "libwayland",
)


def _is_gl_poison(path_or_name: str) -> bool:
    base = os.path.basename(path_or_name)
    return any(base.startswith(p) for p in _GL_POISON_PREFIXES)


def _candidate_dirs() -> list[str]:
    dirs: list[str] = []
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        # Wrapper renames ELF to *.bin — still same directory.
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
            os.path.join(repo, "bin", "mpv"),
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


def _preload_mpv_deps(directory: str) -> None:
    """Load non-GL deps of bundled mpv with RTLD_GLOBAL (libmpv last).

    Skips Mesa/LLVM/EGL — those belong to the GPU driver stack Qt already uses.
    """
    if not os.path.isdir(directory):
        return
    mode = getattr(ctypes, "RTLD_GLOBAL", 0) or 0
    paths: list[str] = []
    for pattern in ("*.so", "*.so.*"):
        paths.extend(glob.glob(os.path.join(directory, pattern)))

    unique: list[str] = []
    seen: set[str] = set()
    for p in paths:
        rp = os.path.realpath(p)
        if rp in seen or not os.path.isfile(rp):
            continue
        if _is_gl_poison(rp):
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
        _preload_mpv_deps(d)

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
