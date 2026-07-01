"""Locate Steam clip preview images on disk (no ffmpeg)."""
import os

_THUMB_NAMES = ("thumbnail.jpg", "thumbnail.jpeg", "thumbnail.png")
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def find_clip_thumbnail(clip_path: str) -> str:
    """Return a preview image path for a clip folder, or '' if none found.

    Checks canonical Steam names in the clip root, then any image in the root,
    then one level of subfolders (some libraries nest thumbs).
    """
    if not clip_path or not os.path.isdir(clip_path):
        return ""

    clip_path = os.path.normpath(clip_path)

    for name in _THUMB_NAMES:
        candidate = os.path.join(clip_path, name)
        if os.path.isfile(candidate):
            return candidate

    try:
        for entry in os.listdir(clip_path):
            lower = entry.lower()
            if lower.endswith(_IMAGE_EXTS):
                return os.path.join(clip_path, entry)
    except OSError:
        return ""

    try:
        for entry in os.listdir(clip_path):
            sub = os.path.join(clip_path, entry)
            if not os.path.isdir(sub):
                continue
            for name in _THUMB_NAMES:
                candidate = os.path.join(sub, name)
                if os.path.isfile(candidate):
                    return candidate
            for sub_entry in os.listdir(sub):
                if sub_entry.lower().endswith(_IMAGE_EXTS):
                    return os.path.join(sub, sub_entry)
    except OSError:
        pass

    return ""
