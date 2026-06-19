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


def open_in_file_manager(path):
    """Open a file or folder in the OS file manager. Does nothing if it is missing."""
    if not os.path.exists(path):
        return
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.run(["open", path])
    else:
        subprocess.run(["xdg-open", path])