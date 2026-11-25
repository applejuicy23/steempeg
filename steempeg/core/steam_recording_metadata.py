"""Read the timeline and recording offsets stored in Steam's recording files."""

import os
import re


_TIMELINE_ID = re.compile(r"timeline_\d+(?:_\d{8})?_\d{6}")


def _varint(data, pos):
    value = 0
    for shift in range(0, 70, 7):
        byte = data[pos]
        pos += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
    raise ValueError("Invalid varint")


def _fields(data):
    """Read the protobuf wire types used by Steam without generated classes."""
    pos = 0
    while pos < len(data):
        tag, pos = _varint(data, pos)
        number, wire = tag >> 3, tag & 7
        if not number:
            raise ValueError("Invalid field number")
        if wire == 0:
            value, pos = _varint(data, pos)
        else:
            if wire == 2:
                size, pos = _varint(data, pos)
            elif wire in (1, 5):
                size = 8 if wire == 1 else 4
            else:
                raise ValueError("Unsupported wire type")
            end = pos + size
            if end > len(data):
                raise ValueError("Truncated recording metadata")
            value, pos = data[pos:end], end
        yield number, wire, value


def recording_timelines(path):
    """Return (timeline JSON basename, recording ID, zero offset) tuples.

    clip.pb and gamerecording.pb both store CGameRecordingTimelineMetadata
    as repeated field 1. Each recording contains its own timeline offset.
    """
    try:
        with open(os.fspath(path), "rb") as handle:
            data = handle.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            return []
        rows = []
        for number, wire, timeline in _fields(data):
            if (number, wire) != (1, 2):
                continue
            fields = list(_fields(timeline))
            name = next((v.decode("ascii") for n, w, v in fields if (n, w) == (1, 2)), "")
            if not _TIMELINE_ID.fullmatch(name):
                continue
            for n, w, value in fields:
                if (n, w) != (5, 2):
                    continue
                recording = {(n, w): v for n, w, v in _fields(value)}
                recording_id = recording.get((1, 2), b"").decode("ascii")
                if recording_id:
                    rows.append((name + ".json", recording_id, recording.get((10, 0))))
        return rows
    except (OSError, ValueError, IndexError):
        return []
