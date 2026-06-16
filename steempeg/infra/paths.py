"""Filesystem path helpers and small OS actions.

No Qt in here.
"""
import os
import subprocess
import sys


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