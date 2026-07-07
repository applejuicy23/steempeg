"""Repair and reconstruct Steam's DASH manifests so broken clips can still play.

Pure logic - no Qt. Two jobs:
  - fix_steam_manifest: patch a session.mpd whose early chunks Steam already trimmed.
  - recover_orphaned_clip: build a session.mpd from scratch when Steam lost it.
Both read and write files and return a path (or None on failure).
"""
import glob
import json
import logging
import os
import re
import subprocess

# Steam's fixed DASH timing. Video runs at timescale 1000 with 3000-tick (3s) chunks,
# audio at 48000 with 144000-tick (3s) chunks.
_VIDEO_TIMESCALE = 1000
_VIDEO_CHUNK_DUR = 3000
_AUDIO_TIMESCALE = 48000
_AUDIO_CHUNK_DUR = 144000
_CHUNK_SECONDS = 3.0


def _stream_chunk_numbers(folder, stream_idx):
    """Sorted list of non-empty chunk numbers for chunk-stream{idx}-NNNNN.m4s on disk."""
    nums = []
    for c in glob.glob(os.path.join(folder, f"chunk-stream{stream_idx}-*.m4s")):
        try:
            if os.path.getsize(c) <= 0:
                continue
        except OSError:
            continue
        m = re.search(rf'chunk-stream{stream_idx}-(\d+)\.m4s', os.path.basename(c))
        if m:
            nums.append(int(m.group(1)))
    return sorted(nums)


def _u32(b, o):
    return int.from_bytes(b[o:o + 4], "big")


def _mdhd_timescale(init_path):
    """Read the media timescale from an init segment's mdhd box (None on failure)."""
    try:
        with open(init_path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    i = data.find(b"mdhd")
    if i < 0:
        return None
    p = i + 4  # payload starts right after the box type
    version = data[p]
    ts_off = p + 20 if version == 1 else p + 12  # skip ver/flags + creation + modified
    if ts_off + 4 > len(data):
        return None
    return _u32(data, ts_off)


def _tfdt_base_time(chunk_path):
    """Read baseMediaDecodeTime from a fragment's tfdt box (None on failure)."""
    try:
        with open(chunk_path, "rb") as f:
            data = f.read(8192)  # tfdt lives in the leading moof, no need to read it all
    except OSError:
        return None
    i = data.find(b"tfdt")
    if i < 0:
        return None
    p = i + 4
    version = data[p]
    if version == 1:
        if p + 12 > len(data):
            return None
        return int.from_bytes(data[p + 4:p + 12], "big")
    if p + 8 > len(data):
        return None
    return _u32(data, p + 4)


def _segment_start_ticks(folder, stream_idx, first_num, template_timescale):
    """Real media-time start of a track's first fragment, in the template's timescale.

    Steam fragments carry a non-zero baseMediaDecodeTime (e.g. ~6.01s). If the manifest
    pretends segments start at 0, mpv's playback timeline drifts by that amount after a
    seek (the "+6s" bug). We read the actual start so the SegmentTimeline can declare it.
    Returns an int tick count, or None if the boxes can't be read.
    """
    init_path = os.path.join(folder, f"init-stream{stream_idx}.m4s")
    chunk_path = os.path.join(folder, f"chunk-stream{stream_idx}-{first_num:05d}.m4s")
    media_ts = _mdhd_timescale(init_path)
    base = _tfdt_base_time(chunk_path)
    if not media_ts or base is None:
        return None
    start_seconds = base / media_ts
    return int(round(start_seconds * template_timescale))


def fix_steam_manifest(mpd_path):
    """Rewrite a Steam session.mpd so ffmpeg's DASH demuxer plays the whole clip.

    Steam ships a live-profile SegmentTemplate with a bare ``duration``/``startNumber``
    and a non-zero ``<Period start>``. ffmpeg can't derive the segment count from that:
    it reads only the FIRST chunk, hits a premature EOF, and any seek back then fails
    with "Error when loading first fragment" (which used to wedge playback entirely).

    The fix is to enumerate the chunks actually on disk as an explicit ``<SegmentTimeline>``
    and pin the period to ``start="PT0S"``. We keep each track's own timescale/duration and
    the original ``mediaPresentationDuration`` (used elsewhere for the clip length). Saved as
    session_fixed.mpd; returns that path, or the original on any failure.
    """
    folder = os.path.dirname(mpd_path)
    v_nums = _stream_chunk_numbers(folder, 0)
    if not v_nums:
        return mpd_path
    a_nums = _stream_chunk_numbers(folder, 1)

    try:
        with open(mpd_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 1) Pin the period to time 0. Steam's "start=PT8.119S" desyncs the demuxer's
        #    timeline against the fragments' own timestamps.
        content = re.sub(r'(<Period\b[^>]*?\bstart=")PT[^"]*(")', r'\g<1>PT0S\g<2>', content)

        # 2) Give each track an explicit SegmentTimeline covering every chunk it has.
        #    contentType (or the mimeType) tells us video (stream0) from audio (stream1).
        def patch_adaptation_set(as_match):
            block = as_match.group(0)
            is_audio = 'contentType="audio"' in block or 'audio/mp4' in block
            stream_idx = 1 if is_audio else 0
            nums = (a_nums or v_nums) if is_audio else v_nums
            if not nums:
                return block
            start_num = nums[0]
            count = len(nums)

            def patch_template(t_match):
                tag = t_match.group(0)
                dur_m = re.search(r'duration="(\d+)"', tag)
                ts_m = re.search(r'timescale="(\d+)"', tag)
                if not dur_m:
                    return tag
                seg_dur = dur_m.group(1)
                template_ts = int(ts_m.group(1)) if ts_m else 1000000

                if 'startNumber=' in tag:
                    tag = re.sub(r'startNumber="\d+"', f'startNumber="{start_num}"', tag)
                else:
                    tag = tag.replace('<SegmentTemplate ',
                                      f'<SegmentTemplate startNumber="{start_num}" ', 1)

                # Anchor the timeline to the fragments' real start time so displayed
                # time is 0-based AND stays consistent across seeks. Falls back to 0
                # if the boxes can't be read (clip still plays; seek may drift).
                anchor = _segment_start_ticks(folder, stream_idx, start_num, template_ts) or 0
                tag = re.sub(r'\s*presentationTimeOffset="\d+"', '', tag)
                if anchor:
                    tag = tag.replace('<SegmentTemplate ',
                                      f'<SegmentTemplate presentationTimeOffset="{anchor}" ', 1)

                timeline = (f"<SegmentTimeline><S t=\"{anchor}\" d=\"{seg_dur}\" "
                            f"r=\"{count - 1}\"/></SegmentTimeline>")

                stripped = tag.rstrip()
                if stripped.endswith('/>'):
                    open_tag = stripped[:-2].rstrip() + '>'
                    return f"{open_tag}{timeline}</SegmentTemplate>"
                # already a container tag: drop any existing timeline, inject ours
                body = re.sub(r'<SegmentTimeline>.*?</SegmentTimeline>', '', tag, flags=re.DOTALL)
                return re.sub(r'>', '>' + timeline, body, count=1)

            return re.sub(r'<SegmentTemplate\b[^>]*?/>|<SegmentTemplate\b[^>]*?>',
                          patch_template, block, count=1)

        content = re.sub(r'<AdaptationSet\b.*?</AdaptationSet>', patch_adaptation_set,
                         content, flags=re.DOTALL)

        fixed_path = os.path.join(folder, "session_fixed.mpd")
        with open(fixed_path, "w", encoding="utf-8") as f:
            f.write(content)
        return fixed_path

    except Exception as e:
        # broad on purpose: if fixing fails for any reason, fall back to the original
        # manifest so the clip still gets a chance to play
        logging.error(f"Failed to fix manifest accurately: {e}")
        return mpd_path


def _probe_video_dimensions(mpd_path):
    """(width, height, fps) for a manifest's video track via ffprobe (0s on failure)."""
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,avg_frame_rate",
                "-of", "json", mpd_path,
            ],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        data = json.loads(proc.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        rate = str(stream.get("avg_frame_rate") or "0/0")
        num, _, den = rate.partition("/")
        den = den or "1"
        fps = int(round(float(num) / float(den))) if float(den) != 0 else 0
        return width, height, fps
    except Exception as exc:
        logging.debug("ffprobe dimensions failed for %s: %s", mpd_path, exc)
        return 0, 0, 0


def _annotate_video_resolution(mpd_path):
    """Bake real width/height/frameRate into a freshly built video Representation.

    Recovered/salvage manifests are assembled from raw chunks and start with no
    resolution, so the render UI shows 'Unknown' and caps its quality/bitrate ladder.
    Probing the actual stream lets the pipeline see the true resolution."""
    width, height, fps = _probe_video_dimensions(mpd_path)
    if not (width and height):
        return
    attrs = f' width="{width}" height="{height}"'
    if fps:
        attrs += f' frameRate="{fps}"'
    try:
        with open(mpd_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace(
            '<Representation id="0" bandwidth',
            f'<Representation id="0"{attrs} bandwidth',
            1,
        )
        with open(mpd_path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as exc:
        logging.debug("Failed to annotate resolution for %s: %s", mpd_path, exc)


def recover_orphaned_clip(
    folder_path,
    out_name="session_recovered.mpd",
    video_init_name="init-stream0.m4s",
    audio_init_name="init-stream1.m4s",
    require_valid_init=True,
    probe_resolution=False,
):
    """Build a manifest from scratch for a folder of orphaned chunks.

    Reads the surviving chunks, assumes Steam's standard DASH timing, and writes a
    fresh manifest named ``out_name``. Returns its path, or None if there is nothing
    usable. Use a non-standard ``out_name`` (e.g. session_salvage.mpd) to keep the
    health/discovery scanners from treating the clip as recovered.

    ``video_init_name`` / ``audio_init_name`` let the manifest point at a *borrowed*
    init segment (from a healthy clip of the same game) when the clip's own init is
    missing/corrupt. Set ``require_valid_init=False`` when supplying such a donor init.
    """
    # without a valid video init segment MPV reads empty space and crashes, so bail early
    init_v = os.path.join(folder_path, video_init_name)
    if require_valid_init and (not os.path.exists(init_v) or os.path.getsize(init_v) < 100):
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

    # Derive a real video bandwidth from the surviving bytes instead of a hardcoded
    # placeholder, so the render UI's "Original" bitrate reflects the actual clip.
    v_bytes = 0
    for c in video_chunks:
        try:
            sz = os.path.getsize(c)
            if sz > 0:
                v_bytes += sz
        except OSError:
            pass
    try:
        v_bytes += os.path.getsize(init_v)
    except OSError:
        pass
    video_bandwidth = int(v_bytes * 8 / duration_sec) if duration_sec > 0 else 10000000
    video_bandwidth = max(video_bandwidth, 100000)

    # audio is optional, and only if its own init segment is valid too
    a_start = v_start
    has_audio = False
    init_a = os.path.join(folder_path, audio_init_name)
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

    # Explicit per-track timelines so ffmpeg reads every chunk (a bare duration makes
    # it stop after the first segment — the same bug fix_steam_manifest works around).
    v_count = len(v_nums)
    v_timeline = f'<SegmentTimeline><S t="0" d="{_VIDEO_CHUNK_DUR}" r="{v_count - 1}"/></SegmentTimeline>'

    audio_block = ""
    if has_audio:
        a_count = len(a_nums)
        a_timeline = f'<SegmentTimeline><S t="0" d="{_AUDIO_CHUNK_DUR}" r="{a_count - 1}"/></SegmentTimeline>'
        audio_block = f"""
            <AdaptationSet id="1" contentType="audio" segmentAlignment="true">
              <Representation id="1" bandwidth="192000" mimeType="audio/mp4">
                <SegmentTemplate timescale="{_AUDIO_TIMESCALE}" startNumber="{a_start}" initialization="{audio_init_name}" media="chunk-stream1-$Number%05d$.m4s">{a_timeline}</SegmentTemplate>
              </Representation>
            </AdaptationSet>"""

    mpd_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" profiles="urn:mpeg:dash:profile:isoff-live:2011" type="static" mediaPresentationDuration="PT{duration_sec}S">
  <Period id="0" start="PT0.000S">
    <AdaptationSet id="0" contentType="video" segmentAlignment="true">
      <Representation id="0" bandwidth="{video_bandwidth}" mimeType="video/mp4">
        <SegmentTemplate timescale="{_VIDEO_TIMESCALE}" startNumber="{v_start}" initialization="{video_init_name}" media="chunk-stream0-$Number%05d$.m4s">{v_timeline}</SegmentTemplate>
      </Representation>
    </AdaptationSet>{audio_block}
  </Period>
</MPD>"""

    recovered_path = os.path.join(folder_path, out_name)
    try:
        with open(recovered_path, "w", encoding="utf-8") as f:
            f.write(mpd_xml.strip())
        logging.info(f"Recovered orphaned clip at {recovered_path}")
        if probe_resolution:
            _annotate_video_resolution(recovered_path)
        return recovered_path
    except OSError as e:
        logging.error(f"Failed to write recovered MPD: {e}")
        return None