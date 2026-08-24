"""Find and measure Steam clip folders on disk.

Pure filesystem helpers - no Qt.
"""
from steempeg.core.dash import repair
import os
import re


def folder_size_bytes(path):
    """Add up the size of every file in the clip folder.
    Skips symlinks so nothing gets counted twice."""
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for name in filenames:
            fp = os.path.join(dirpath, name)
            if not os.path.islink(fp):
                total += os.path.getsize(fp)
    return total

def parse_duration_seconds(mpd_content):
    """Read the clip length in seconds from the mpd's mediaPresentationDuration.
    Returns None if it is not present."""
    m = re.search(
        r'mediaPresentationDuration="PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?"',
        mpd_content,
    )
    if not m:
        return None
    # raw values, they can be odd like 80 minutes and 0 hours
    hours = int(m.group(1)) if m.group(1) else 0
    minutes = int(m.group(2)) if m.group(2) else 0
    seconds = float(m.group(3)) if m.group(3) else 0.0
    return hours * 3600 + minutes * 60 + seconds


def _append_mpd_for_folder(folder: str, mpd_paths: list) -> bool:
    """Resolve playable manifest(s) in *folder* without listing chunk files.

    Reuses ``session_fixed.mpd`` when it is still as new as ``session.mpd`` —
    rewriting the fixed copy on every select/open used to glob every chunk and
    block the UI thread.
    """
    fixed_path = os.path.join(folder, "session_fixed.mpd")
    raw_path = os.path.join(folder, "session.mpd")
    recovered_path = os.path.join(folder, "session_recovered.mpd")

    if os.path.isfile(fixed_path):
        if os.path.isfile(raw_path):
            try:
                if os.path.getmtime(raw_path) > os.path.getmtime(fixed_path):
                    mpd_paths.append(repair.fix_steam_manifest(raw_path))
                    return True
            except OSError:
                pass
        mpd_paths.append(fixed_path)
        return True
    if os.path.isfile(raw_path):
        mpd_paths.append(repair.fix_steam_manifest(raw_path))
        return True
    if os.path.isfile(recovered_path):
        mpd_paths.append(recovered_path)
        return True
    return False


def find_mpd_paths(clip_path):
    """Find every playable manifest under clip_path, fixing Steam's originals on the way.
    Returns a sorted list of paths.

    Walks directories only and probes known manifest names with ``isfile`` — never
    ``listdir``/``walk`` the thousands of ``.m4s`` chunks in a long recording
    (that alone was enough to freeze the UI on open).
    """
    mpd_paths = []
    if not clip_path or not os.path.isdir(clip_path):
        return mpd_paths

    # Typical Steam layout: manifests sit in the clip root.
    if _append_mpd_for_folder(clip_path, mpd_paths):
        return sorted(mpd_paths)

    # Rare nested layouts: descend into subdirs without enumerating chunk files.
    stack = [clip_path]
    seen = {os.path.normcase(os.path.abspath(clip_path))}
    while stack:
        folder = stack.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    try:
                        key = os.path.normcase(os.path.abspath(entry.path))
                    except OSError:
                        continue
                    if key in seen:
                        continue
                    seen.add(key)
                    if _append_mpd_for_folder(entry.path, mpd_paths):
                        # Keep scanning siblings for multi-period clips, but do
                        # not descend further under a folder that already has a
                        # manifest (chunk trees live beside the MPD).
                        continue
                    stack.append(entry.path)
        except OSError:
            continue
    return sorted(mpd_paths)
