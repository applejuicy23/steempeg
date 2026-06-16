"""Find and measure Steam clip folders on disk.

Pure filesystem helpers - no Qt.
"""
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