"""Filesystem path helpers and small OS actions.

No Qt in here.
"""
import os
import subprocess
import sys
from pathlib import Path

# Repo root, resolved from this file: steempeg/infra/paths.py -> steempeg/infra -> steempeg -> root.
# We anchor on the package layout instead of __file__ directly so asset lookups keep
# pointing at the project root, not at the steempeg/infra folder.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Bundled images/icons live under <root>/assets in source, and under <bundle>/assets when frozen.
_ASSETS_DIRNAME = "assets"


def get_resource_path(relative_path):
    """Resolve a bundled asset (lives under assets/) for both the frozen build and a plain source run."""
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
        direct_path = os.path.join(base_dir, _ASSETS_DIRNAME, relative_path)
        if os.path.exists(direct_path):
            return direct_path
        # Fall back to the PyInstaller temp extraction dir if present.
        if hasattr(sys, "_MEIPASS"):
            return os.path.join(sys._MEIPASS, _ASSETS_DIRNAME, relative_path)
        return direct_path
    return os.path.join(str(_PROJECT_ROOT), _ASSETS_DIRNAME, relative_path)


def get_save_directory():
    """Return the default folder where the program saves videos, caches and logs."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return str(_PROJECT_ROOT)


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


def open_path_with_default_app(path: str) -> None:
    """Open a file or folder with the OS default handler."""
    if not path:
        return
    norm = os.path.normpath(path)
    if not os.path.exists(norm):
        return
    if sys.platform == "win32":
        os.startfile(norm)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.run(["open", norm], check=False)
    else:
        subprocess.run(["xdg-open", norm], check=False)


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


def reveal_in_file_manager(path: str) -> None:
    """Open the file manager with ``path`` selected/highlighted."""
    if not path:
        return
    norm = os.path.normpath(path)
    if os.path.exists(norm):
        if sys.platform == "win32":
            subprocess.run(["explorer", "/select,", norm], check=False)
        elif sys.platform == "darwin":
            subprocess.run(["open", "-R", norm], check=False)
        else:
            for cmd in (
                ["nautilus", "--select", norm],
                ["nemo", "--select", norm],
                ["dolphin", "--select", norm],
                ["thunar", "--select", norm],
                ["pcmanfm", "--select", norm],
            ):
                try:
                    subprocess.run(cmd, check=False)
                    return
                except FileNotFoundError:
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