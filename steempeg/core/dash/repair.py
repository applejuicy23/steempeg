"""Repair and reconstruct Steam's DASH manifests so broken clips can still play.

Pure logic - no Qt. Two jobs:
  - fix_steam_manifest: patch a session.mpd whose early chunks Steam already trimmed.
  - recover_orphaned_clip: build a session.mpd from scratch when Steam lost it.
Both read and write files and return a path (or None on failure).
"""
import glob
import logging
import os
import re

# Steam's fixed DASH timing. Video runs at timescale 1000 with 3000-tick (3s) chunks,
# audio at 48000 with 144000-tick (3s) chunks.
_VIDEO_TIMESCALE = 1000
_VIDEO_CHUNK_DUR = 3000
_AUDIO_TIMESCALE = 48000
_AUDIO_CHUNK_DUR = 144000
_CHUNK_SECONDS = 3.0


def fix_steam_manifest(mpd_path):
    """Patch a Steam session.mpd whose early chunks were dropped by the rolling buffer.

    Numbering may start above 1, which leaves the offsets and duration wrong. We rewrite
    the per-track presentation offsets, the startNumber, and the total duration, then save
    it as session_fixed.mpd. Returns the fixed path, or the original if nothing to fix.
    """
    folder = os.path.dirname(mpd_path)
    chunks = glob.glob(os.path.join(folder, "chunk-stream0-*.m4s"))
    if not chunks:
        return mpd_path

    numbers = []
    for c in chunks:
        m = re.search(r'chunk-stream0-(\d+)\.m4s', os.path.basename(c))
        if m:
            numbers.append(int(m.group(1)))
    if not numbers:
        return mpd_path
    min_chunk = min(numbers)

    try:
        with open(mpd_path, "r", encoding="utf-8") as f:
            content = f.read()

        # video and audio have different timescales, so each SegmentTemplate gets its
        # own offset based on its own duration. compute it per tag.
        def inject_offset(match):
            tag = match.group(0)
            ts_m = re.search(r'timescale="(\d+)"', tag)
            dur_m = re.search(r'duration="(\d+)"', tag)
            if ts_m and dur_m:
                dur = int(dur_m.group(1))
                track_offset = (min_chunk - 1) * dur
                if 'presentationTimeOffset=' in tag:
                    return re.sub(r'presentationTimeOffset="\d+"',
                                  f'presentationTimeOffset="{track_offset}"', tag)
                return tag.replace('<SegmentTemplate ',
                                   f'<SegmentTemplate presentationTimeOffset="{track_offset}" ')
            return tag

        content = re.sub(r'<SegmentTemplate\s+[^>]+>', inject_offset, content)

        # tell the player which chunk to start from
        content = re.sub(r'startNumber="\d+"', f'startNumber="{min_chunk}"', content)

        # only shorten the total duration if Steam actually dropped chunks
        if min_chunk > 1:
            ts_match = re.search(r'timescale="(\d+)"', content)
            dur_match = re.search(r'duration="(\d+)"', content)
            mpd_dur_match = re.search(
                r'mediaPresentationDuration="PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?"', content)
            if ts_match and dur_match and mpd_dur_match:
                chunk_seconds = float(dur_match.group(1)) / float(ts_match.group(1))
                deleted_sec = (min_chunk - 1) * chunk_seconds

                h = float(mpd_dur_match.group(1)) if mpd_dur_match.group(1) else 0
                m = float(mpd_dur_match.group(2)) if mpd_dur_match.group(2) else 0
                s = float(mpd_dur_match.group(3)) if mpd_dur_match.group(3) else 0
                original_total = h * 3600 + m * 60 + s
                new_total = max(0.0, original_total - deleted_sec)

                new_h = int(new_total // 3600)
                new_m = int((new_total % 3600) // 60)
                new_s = new_total % 60
                new_pt = (f"PT{new_h}H{new_m}M{new_s:.3f}S" if new_h > 0
                          else f"PT{new_m}M{new_s:.3f}S")
                content = re.sub(r'mediaPresentationDuration="PT[^"]+"',
                                 f'mediaPresentationDuration="{new_pt}"', content)

        fixed_path = os.path.join(folder, "session_fixed.mpd")
        with open(fixed_path, "w", encoding="utf-8") as f:
            f.write(content)
        return fixed_path

    except Exception as e:
        # broad on purpose: if fixing fails for any reason, fall back to the original
        # manifest so the clip still gets a chance to play
        logging.error(f"Failed to fix manifest accurately: {e}")
        return mpd_path


def recover_orphaned_clip(folder_path):
    """Build a session.mpd from scratch for a folder of orphaned chunks.

    Reads the surviving chunks, assumes Steam's standard DASH timing, and writes a fresh
    session_recovered.mpd. Returns its path, or None if there is nothing usable.
    """
    # without a valid video init segment MPV reads empty space and crashes, so bail early
    init_v = os.path.join(folder_path, "init-stream0.m4s")
    if not os.path.exists(init_v) or os.path.getsize(init_v) < 100:
        logging.warning(f"Skipped, no valid init-stream0: {folder_path}")
        return None

    video_chunks = glob.glob(os.path.join(folder_path, "chunk-stream0-*.m4s"))
    if not video_chunks:
        return None

    v_nums = []
    for c in video_chunks:
        if os.path.getsize(c) > 0:   # skip empty chunks, they crash playback
            m = re.search(r'chunk-stream0-(\d+)\.m4s', os.path.basename(c))
            if m:
                v_nums.append(int(m.group(1)))
    if not v_nums:
        return None

    v_start = min(v_nums)
    duration_sec = len(v_nums) * _CHUNK_SECONDS

    # audio is optional, and only if its own init segment is valid too
    a_start = v_start
    has_audio = False
    init_a = os.path.join(folder_path, "init-stream1.m4s")
    audio_chunks = glob.glob(os.path.join(folder_path, "chunk-stream1-*.m4s"))
    if audio_chunks and os.path.exists(init_a) and os.path.getsize(init_a) > 100:
        a_nums = []
        for c in audio_chunks:
            if os.path.getsize(c) > 0:
                m = re.search(r'chunk-stream1-(\d+)\.m4s', os.path.basename(c))
                if m:
                    a_nums.append(int(m.group(1)))
        if a_nums:
            a_start = min(a_nums)
            has_audio = True

    v_offset = (v_start - 1) * _VIDEO_CHUNK_DUR

    audio_block = ""
    if has_audio:
        a_offset = (a_start - 1) * _AUDIO_CHUNK_DUR
        audio_block = f"""
            <AdaptationSet id="1" contentType="audio" segmentAlignment="true">
              <Representation id="1" bandwidth="192000" mimeType="audio/mp4">
                <SegmentTemplate presentationTimeOffset="{a_offset}" timescale="{_AUDIO_TIMESCALE}" duration="{_AUDIO_CHUNK_DUR}" startNumber="{a_start}" initialization="init-stream1.m4s" media="chunk-stream1-$Number%05d$.m4s" />
              </Representation>
            </AdaptationSet>"""

    mpd_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" profiles="urn:mpeg:dash:profile:isoff-live:2011" type="static" mediaPresentationDuration="PT{duration_sec}S">
  <Period id="0" start="PT0.000S">
    <AdaptationSet id="0" contentType="video" segmentAlignment="true">
      <Representation id="0" bandwidth="10000000" mimeType="video/mp4">
        <SegmentTemplate presentationTimeOffset="{v_offset}" timescale="{_VIDEO_TIMESCALE}" duration="{_VIDEO_CHUNK_DUR}" startNumber="{v_start}" initialization="init-stream0.m4s" media="chunk-stream0-$Number%05d$.m4s" />
      </Representation>
    </AdaptationSet>{audio_block}
  </Period>
</MPD>"""

    recovered_path = os.path.join(folder_path, "session_recovered.mpd")
    try:
        with open(recovered_path, "w", encoding="utf-8") as f:
            f.write(mpd_xml.strip())
        logging.info(f"Recovered orphaned clip at {recovered_path}")
        return recovered_path
    except OSError as e:
        logging.error(f"Failed to write recovered MPD: {e}")
        return None