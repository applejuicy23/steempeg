"""Locate / preload bundled libmpv before ``import mpv`` (python-mpv).

On Linux, ctypes.util.find_library('mpv') only looks at the system cache and
often misses Fedora's ``libmpv.so.2`` (no unversioned ``.so``) or our
``bin/`` copy next to the frozen app. End users should not install system
mpv or run ldconfig hacks — we ship the library with the release zip.

Critical (NVIDIA / Bazzite): never RTLD_GLOBAL-preload Homebrew Mesa
(``libgallium``, ``libLLVM``, ``libEGL``, …). That hijacks Qt's GL stack and
hard-freezes the UI on XWayland. ``./run-linux.sh`` works because it does not
do that — only ``LD_LIBRARY_PATH`` for mpv, after Qt is free to use NVIDIA.

Also prefer a system ``libmpv`` that links to host EGL (NVIDIA) over a bundled
copy that RPATHs Homebrew Mesa → llvmpipe (black / artifacty ``vo=xv`` preview).
"""
from __future__ import annotations

import ctypes
import ctypes.util
import glob
import logging
import os
import subprocess
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


def find_system_libmpv() -> str | None:
    """Host libmpv (Fedora/Bazzite often ship ``libmpv.so.2`` without unversioned ``.so``)."""
    for path in (
        "/usr/lib64/libmpv.so.2",
        "/usr/lib/libmpv.so.2",
        "/usr/lib/x86_64-linux-gnu/libmpv.so.2",
        "/usr/local/lib64/libmpv.so.2",
        "/usr/local/lib/libmpv.so.2",
    ):
        if os.path.isfile(path):
            return os.path.realpath(path)
    try:
        found = ctypes.util.find_library("mpv")
    except Exception:
        found = None
    if found and os.path.isfile(found):
        return os.path.realpath(found)
    return None


def libmpv_links_brew_mesa(path: str | None) -> bool:
    """True when *path* pulls Homebrew EGL/gallium (llvmpipe on NVIDIA desktops)."""
    if not path or not os.path.isfile(path):
        return False
    try:
        out = subprocess.check_output(
            ["ldd", path], text=True, stderr=subprocess.DEVNULL
        )
    except (OSError, subprocess.CalledProcessError):
        return "linuxbrew" in path
    return "linuxbrew" in out and (
        "libEGL" in out or "libgallium" in out or "mesa" in out.lower()
    )


def choose_libmpv() -> str | None:
    """Pick the best libmpv: non-brew bundled → system → brew-bundled last resort."""
    bundled = find_bundled_libmpv()
    system = find_system_libmpv()

    if bundled and not libmpv_links_brew_mesa(bundled):
        return bundled
    if system and not libmpv_links_brew_mesa(system):
        if bundled and libmpv_links_brew_mesa(bundled):
            logging.info(
                "libmpv: preferring system %s over brew-linked bundled %s",
                system,
                bundled,
            )
        return system
    if bundled:
        return bundled
    return system


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

    Returns the path that will be used, or None if nothing is available.
    """
    if sys.platform == "win32":
        # Windows build already ships mpv-2.dll on PATH via app.py bin/ prepend.
        return None

    chosen = choose_libmpv()
    if not chosen:
        return None

    # Only preload sibling .so's for bundled copies — system libmpv uses host deps.
    bundled = find_bundled_libmpv()
    if bundled and os.path.realpath(chosen) == os.path.realpath(bundled):
        lib_dirs = [d for d in _candidate_dirs() if os.path.isdir(d)]
        for d in lib_dirs:
            _preload_mpv_deps(d)

    os.environ["MPV_LIBRARY_PATH"] = chosen

    _orig = ctypes.util.find_library

    def _find(name: str):
        if name in ("mpv", "libmpv"):
            return chosen
        return _orig(name)

    ctypes.util.find_library = _find  # type: ignore[assignment]

    mode = getattr(ctypes, "RTLD_GLOBAL", 0) or 0
    try:
        ctypes.CDLL(chosen, mode=mode)
    except OSError:
        pass

    return chosen
