"""Filesystem path helpers and small OS actions.

No Qt in here.
"""
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Repo root, resolved from this file: steempeg/infra/paths.py -> steempeg/infra -> steempeg -> root.
# We anchor on the package layout instead of __file__ directly so asset lookups keep
# pointing at the project root, not at the steempeg/infra folder.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Bundled images/icons live under <root>/assets in source, and under <bundle>/assets when frozen.
_ASSETS_DIRNAME = "assets"


def get_install_root() -> str:
    """Folder that owns the Steempeg install (launchers, bin/, logs/, cache/).

    * Frozen (PyInstaller): directory of the executable.
    * Portable Linux pack: directory with ``Steempeg-linux`` + ``venv/`` + ``steempeg/``.
    * Dev checkout: repository root.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))

    # Portable pack often runs as ``venv/bin/python -m steempeg`` — climb out of venv.
    exe = os.path.abspath(sys.executable)
    parts = exe.replace("\\", "/").split("/")
    if "venv" in parts:
        idx = parts.index("venv")
        candidate = os.sep.join(parts[:idx]) if idx > 0 else str(_PROJECT_ROOT)
        if os.path.isfile(os.path.join(candidate, "Steempeg-linux")) or os.path.isdir(
            os.path.join(candidate, "steempeg")
        ):
            return candidate
    if os.path.isfile(os.path.join(str(_PROJECT_ROOT), "Steempeg-linux")):
        return str(_PROJECT_ROOT)
    return str(_PROJECT_ROOT)


def get_resource_path(relative_path):
    """Resolve a bundled asset (lives under assets/) for both the frozen build and a plain source run."""
    if getattr(sys, "frozen", False):
        base_dir = get_install_root()
        direct_path = os.path.join(base_dir, _ASSETS_DIRNAME, relative_path)
        if os.path.exists(direct_path):
            return direct_path
        # Fall back to the PyInstaller temp extraction dir if present.
        if hasattr(sys, "_MEIPASS"):
            return os.path.join(sys._MEIPASS, _ASSETS_DIRNAME, relative_path)
        return direct_path
    # Portable pack + dev: assets next to install root.
    pack = os.path.join(get_install_root(), _ASSETS_DIRNAME, relative_path)
    if os.path.exists(pack):
        return pack
    return os.path.join(str(_PROJECT_ROOT), _ASSETS_DIRNAME, relative_path)


def get_save_directory():
    """Return the default folder where the program saves videos, caches and logs."""
    return get_install_root()


def display_path(path: str) -> str:
    """Return a path string suitable for UI display (native casing when possible)."""
    if not path:
        return path
    if os.name == "nt":
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(32768)
            if ctypes.windll.kernel32.GetLongPathNameW(path, buf, 32768):
                resolved = buf.value
                if resolved:
                    return resolved
        except Exception:
            pass
    return path


def _linux_desktop_env() -> dict[str, str]:
    """Best-effort session env for ``xdg-open`` / ``kde-open`` on Linux.

    Steempeg is sometimes launched without ``DBUS_SESSION_BUS_ADDRESS`` or
    ``XDG_RUNTIME_DIR`` (Steam shortcut, terminal, distrobox). KDE helpers need
    those even when Qt itself already connected to the display.
    """
    env = os.environ.copy()
    try:
        uid = os.getuid()
    except AttributeError:
        return env

    runtime = (env.get("XDG_RUNTIME_DIR") or "").strip()
    if not runtime or not os.path.isdir(runtime):
        candidate = f"/run/user/{uid}"
        if os.path.isdir(candidate):
            env["XDG_RUNTIME_DIR"] = candidate
            runtime = candidate

    if runtime and not (env.get("DBUS_SESSION_BUS_ADDRESS") or "").strip():
        bus = os.path.join(runtime, "bus")
        if os.path.exists(bus):
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"

    return env


def _linux_open_commands(path: str) -> list[list[str]]:
    """Ordered desktop open helpers for ``path`` (Linux only)."""
    norm = path
    desktop = (
        os.environ.get("XDG_CURRENT_DESKTOP")
        or os.environ.get("XDG_SESSION_DESKTOP")
        or os.environ.get("DESKTOP_SESSION")
        or ""
    ).lower()
    kde = "kde" in desktop or "plasma" in desktop

    ordered: list[str] = []
    if kde:
        ordered.extend(["kde-open5", "kde-open"])
    ordered.append("xdg-open")
    if not kde:
        ordered.extend(["kde-open5", "kde-open"])
    ordered.append("gio")

    cmds: list[list[str]] = []
    seen: set[str] = set()
    for name in ordered:
        if name in seen:
            continue
        seen.add(name)
        if name == "gio":
            if shutil.which("gio") is not None:
                cmds.append(["gio", "open", norm])
        elif shutil.which(name) is not None:
            cmds.append([name, norm])
    return cmds


def _spawn_detached(
    cmd: list[str],
    *,
    new_session: bool | None = None,
    env: dict[str, str] | None = None,
) -> None:
    """Start ``cmd`` without blocking the Qt UI thread.

    Linux ``xdg-open`` / some file managers wait until the helper exits if launched
    via ``subprocess.run``, which freezes Steempeg after «Open file» / Play video.

    For desktop open/reveal helpers, keep ``new_session=False`` so the child stays
    on the user's DBus/display session (KDE's ``kde-open`` aborts when detached).
    """
    kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }
    if env is not None:
        kwargs["env"] = env
    if sys.platform == "win32":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP — don't wait on the child.
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
        )
    elif new_session if new_session is not None else False:
        # Opt-in only (updates / long-lived helpers). Default False on Linux so
        # xdg-open keeps session bus + DISPLAY.
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)


def open_path_with_default_app(path: str) -> None:
    """Open a file or folder with the OS default handler."""
    if not path:
        return
    norm = os.path.abspath(os.path.normpath(path))
    if not os.path.exists(norm):
        logging.warning("Cannot open — path does not exist: %s", norm)
        return
    if sys.platform == "win32":
        os.startfile(norm)  # noqa: S606
    elif sys.platform == "darwin":
        _spawn_detached(["open", norm])
    else:
        env = _linux_desktop_env()
        last_exc: Exception | None = None
        for cmd in _linux_open_commands(norm):
            try:
                _spawn_detached(cmd, new_session=False, env=env)
                logging.debug("Opened %s via %s", norm, cmd[0])
                return
            except OSError as exc:
                last_exc = exc
                logging.debug("Open helper %s failed for %s: %s", cmd[0], norm, exc)
                continue
        logging.warning(
            "Could not open %s — no desktop helper succeeded (%s)",
            norm,
            last_exc or "no helpers installed",
        )
        if last_exc is not None:
            raise last_exc


def open_text_file(path: str) -> None:
    """Open a text/log file in a sensible editor for the current OS."""
    if not path or not os.path.isfile(path):
        return
    norm = os.path.abspath(path)
    if sys.platform == "win32":
        subprocess.Popen(["notepad.exe", norm])
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-t", norm])
        return
    open_path_with_default_app(norm)


def open_in_file_manager(path, *, reveal: bool = False):
    """Open a file or folder in the OS file manager.

    With ``reveal=True``, highlight ``path`` in its parent window when supported.
    """
    if not path:
        return
    norm = os.path.normpath(path)
    if reveal:
        reveal_in_file_manager(norm)
        return
    open_path_with_default_app(norm)


def _reveal_windows(path: str) -> bool:
    """Select ``path`` in Explorer, even when that folder is already open.

    ``explorer /select,`` often does nothing if a window for the parent folder is
    already up. Shell32's SHOpenFolderAndSelectItems brings that window forward
    and highlights the item instead of silently no-oping.
    """
    import ctypes

    abs_path = os.path.abspath(path)
    try:
        ole32 = ctypes.windll.ole32
        shell32 = ctypes.windll.shell32
        ole32.CoInitialize(None)
        pidl = shell32.ILCreateFromPathW(abs_path)
        if not pidl:
            return False
        try:
            # cidl=0: treat pidl as the fully-qualified item to open+select.
            hr = shell32.SHOpenFolderAndSelectItems(pidl, 0, None, 0)
            return int(hr) >= 0
        finally:
            shell32.ILFree(pidl)
    except Exception:
        return False


def reveal_in_file_manager(path: str) -> None:
    """Open the file manager with ``path`` selected/highlighted.

    If ``path`` is already visible in an open Explorer/Finder window, that window
    is brought forward and the item is re-selected — not silently ignored.
    """
    if not path:
        return
    norm = os.path.abspath(os.path.normpath(path))
    if os.path.exists(norm):
        if sys.platform == "win32":
            if _reveal_windows(norm):
                return
            # Fallback: attach path to /select, — split argv form is unreliable.
            subprocess.run(
                ["explorer", f"/select,{norm}"],
                check=False,
            )
        elif sys.platform == "darwin":
            _spawn_detached(["open", "-R", norm])
        else:
            env = _linux_desktop_env()
            # Only spawn helpers that exist — Popen "success" on a missing binary
            # raises, but a present binary that can't talk to the session used to
            # look like success after start_new_session detached from DBus.
            candidates = (
                ["dolphin", "--select", norm],
                ["nautilus", "--select", norm],
                ["nemo", "--select", norm],
                ["thunar", "--select", norm],
                ["pcmanfm", "--select", norm],
            )
            for cmd in candidates:
                if shutil.which(cmd[0]) is None:
                    continue
                try:
                    _spawn_detached(cmd, new_session=False, env=env)
                    return
                except OSError:
                    continue
            open_in_file_manager(os.path.dirname(norm) if os.path.isfile(norm) else norm)
        return

    parent = os.path.dirname(norm)
    if parent and os.path.isdir(parent):
        open_in_file_manager(parent)


def default_rendered_videos_dir() -> str:
    """Default library folder for finished exports (Rendered videos tab)."""
    return os.path.join(get_save_directory(), "rendered_videos")


def is_in_default_rendered_videos(file_path: str) -> bool:
    """True when ``file_path`` lives under the default ``rendered_videos`` folder."""
    if not file_path or not os.path.isfile(file_path):
        return False
    root = os.path.normcase(os.path.normpath(default_rendered_videos_dir()))
    path = os.path.normcase(os.path.normpath(file_path))
    try:
        return os.path.commonpath([root, path]) == root
    except ValueError:
        return False