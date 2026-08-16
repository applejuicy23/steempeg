"""Named user export presets — full RenderJobSettings recipes (not Share/Edit/Web).

Stored in ``settings.json`` under ``export_presets``:

```json
{
  "export_presets": {
    "Discord 720p": { "quality_text": "...", "container_format": "MP4", ... }
  },
  "export_preset_favourites": ["Discord 720p", "1440p Ultra"]
}
```

Clip-specific fields (trim, basename, source probe) are stripped on save and
preserved when applying a preset onto an existing queue job.
"""
from __future__ import annotations

import re
from dataclasses import asdict, replace
from typing import Any, Callable

from steempeg.render.queue import RenderJob, RenderJobSettings, settings_from_dict

SETTINGS_KEY = "export_presets"
FAVOURITES_KEY = "export_preset_favourites"
MAX_FAVOURITES = 5

# Not part of a reusable recipe — stay with the clip / job.
_CLIP_SPECIFIC_KEYS = frozenset(
    {
        "trim_start_ms",
        "trim_end_ms",
        "is_trim_mode",
        "output_basename",
        "orig_fps",
        "orig_video_mbps",
        "orig_audio_kbps",
    }
)


def _normalize_name(name: str) -> str:
    return " ".join((name or "").strip().split())


def settings_to_preset_dict(settings: RenderJobSettings) -> dict[str, Any]:
    data = asdict(settings)
    for key in _CLIP_SPECIFIC_KEYS:
        data.pop(key, None)
    return data


def preset_dict_to_settings(data: dict[str, Any] | None) -> RenderJobSettings:
    cleaned = {
        k: v
        for k, v in (data or {}).items()
        if k not in _CLIP_SPECIFIC_KEYS
    }
    return settings_from_dict(cleaned)


def load_presets_map(load_settings: Callable[[], dict]) -> dict[str, dict[str, Any]]:
    raw = (load_settings() or {}).get(SETTINGS_KEY) or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, payload in raw.items():
        key = _normalize_name(str(name))
        if not key or not isinstance(payload, dict):
            continue
        out[key] = dict(payload)
    return out


def load_favourite_names(load_settings: Callable[[], dict]) -> list[str]:
    """Pinned names in pin order; unknown / empty entries dropped."""
    presets = load_presets_map(load_settings)
    raw = (load_settings() or {}).get(FAVOURITES_KEY) or []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        key = _normalize_name(str(item))
        if not key or key in seen or key not in presets:
            continue
        seen.add(key)
        out.append(key)
        if len(out) >= MAX_FAVOURITES:
            break
    return out


def save_favourite_names(
    names: list[str],
    *,
    load_settings: Callable[[], dict],
    save_settings: Callable[[str, Any], None],
) -> list[str]:
    presets = load_presets_map(load_settings)
    cleaned: list[str] = []
    seen: set[str] = set()
    for name in names:
        key = _normalize_name(name)
        if not key or key in seen or key not in presets:
            continue
        seen.add(key)
        cleaned.append(key)
        if len(cleaned) >= MAX_FAVOURITES:
            break
    save_settings(FAVOURITES_KEY, cleaned)
    return cleaned


def is_favourite(name: str, load_settings: Callable[[], dict]) -> bool:
    key = _normalize_name(name)
    return bool(key) and key in load_favourite_names(load_settings)


def toggle_favourite(
    name: str,
    *,
    load_settings: Callable[[], dict],
    save_settings: Callable[[str, Any], None],
) -> bool:
    """Pin / unpin. Returns True if the preset is favourited after the toggle."""
    key = _normalize_name(name)
    if not key:
        raise ValueError("Preset name is empty")
    presets = load_presets_map(load_settings)
    if key not in presets:
        raise KeyError(key)
    favs = load_favourite_names(load_settings)
    if key in favs:
        favs = [n for n in favs if n != key]
        save_favourite_names(favs, load_settings=load_settings, save_settings=save_settings)
        return False
    if len(favs) >= MAX_FAVOURITES:
        # Drop the oldest pin so the new one can land at the front.
        favs = favs[1:]
    favs = [key] + [n for n in favs if n != key]
    save_favourite_names(favs, load_settings=load_settings, save_settings=save_settings)
    return True


def list_preset_names(
    load_settings: Callable[[], dict],
    *,
    search: str = "",
    favourites_first: bool = True,
) -> list[str]:
    """Names for UI lists. Favourites (pin order) first, then A–Z."""
    presets = load_presets_map(load_settings)
    names = list(presets.keys())
    needle = _normalize_name(search).casefold()
    if needle:
        names = [n for n in names if needle in n.casefold()]
    if not favourites_first:
        return sorted(names, key=str.casefold)
    favs = [n for n in load_favourite_names(load_settings) if n in names]
    fav_set = set(favs)
    rest = sorted((n for n in names if n not in fav_set), key=str.casefold)
    return favs + rest


def get_preset_settings(
    name: str, load_settings: Callable[[], dict]
) -> RenderJobSettings | None:
    key = _normalize_name(name)
    payload = load_presets_map(load_settings).get(key)
    if payload is None:
        return None
    return preset_dict_to_settings(payload)


def _short_codec(codec_text: str) -> str:
    codec = (codec_text or "").strip()
    if not codec:
        return ""
    if "H.265" in codec or "HEVC" in codec.upper():
        return "H.265"
    if "H.264" in codec or "AVC" in codec.upper():
        return "H.264"
    if codec.startswith("AV1"):
        return "AV1"
    if codec.startswith("VP9"):
        return "VP9"
    return codec.split()[0]


def _short_res(settings: RenderJobSettings) -> str:
    quality = (settings.quality_text or "").strip()
    if "Target File Size" in quality:
        return "Target size"
    if "Original" in quality and "Target" not in quality:
        return "Original"
    match = re.match(r"^(\d+p)", quality)
    if match:
        return match.group(1)
    if settings.custom_target_height and settings.custom_target_height > 0:
        return f"{settings.custom_target_height}p"
    if quality:
        return quality.split("(")[0].strip()
    return ""


def _format_video_bitrate_mbps(mbps: float) -> str:
    """Preset-summary bitrate: Mbps at ≥1, else whole kbps (matches audio labels).

    Ultra-low ladder rows are stored as Mbps in the combo (e.g. ``0.01 Mbps``)
    but read better as ``10 kbps`` in the expandable recipe strip.
    """
    value = float(mbps)
    if value < 1:
        kbps = max(1, int(round(value * 1000)))
        return f"{kbps} kbps"
    s = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{s} Mbps"


def _format_video_bitrate_kbps(kbps: float | int) -> str:
    """Same as ``_format_video_bitrate_mbps`` when the stored unit is already kbps."""
    return _format_video_bitrate_mbps(float(kbps) / 1000.0)


def _short_video_bitrate(settings: RenderJobSettings) -> str:
    quality = (settings.quality_text or "").strip()
    bitrate = (settings.bitrate_text or "").strip()
    if "Original" in quality and "Target" not in quality:
        return "source"
    if "Custom" in bitrate and settings.custom_vbitrate is not None:
        return _format_video_bitrate_mbps(settings.custom_vbitrate)
    match = re.search(r"([\d.]+)\s*Mbps", bitrate)
    if match:
        return _format_video_bitrate_mbps(float(match.group(1)))
    if "Target File Size" in quality and settings.custom_target_bitrate:
        return _format_video_bitrate_kbps(settings.custom_target_bitrate)
    return ""


def _short_audio(settings: RenderJobSettings) -> str:
    if settings.mute_audio:
        return "Muted"
    fmt = (settings.audio_format or "").strip() or "AAC"
    if settings.audio_only:
        br = (settings.audio_bitrate_text or "").strip()
        if br and fmt not in ("FLAC", "WAV", "Copy"):
            match = re.search(r"(\d+)", br)
            return f"{fmt} only · {match.group(1)}k" if match else f"{fmt} only"
        return f"{fmt} only"
    if fmt in ("FLAC", "WAV", "Copy"):
        return fmt
    br = (settings.audio_bitrate_text or "").strip()
    match = re.search(r"(\d+)", br)
    if match:
        return f"{fmt} {match.group(1)}k"
    return fmt


def format_preset_summary(settings: RenderJobSettings | dict[str, Any] | None) -> str:
    """Readable recipe line: container · codec · res · bitrate · audio."""
    if isinstance(settings, dict):
        settings = preset_dict_to_settings(settings)
    if settings is None:
        return "—"

    if settings.audio_only:
        container = (settings.container_format or "").strip() or "Audio"
        return " · ".join(p for p in (container, _short_audio(settings)) if p)

    parts: list[str] = []
    container = (settings.container_format or "").strip()
    if container:
        parts.append(container)

    codec = _short_codec(settings.codec_text) or _short_codec(settings.encoder_display)
    if codec:
        parts.append(codec)

    res = _short_res(settings)
    if res:
        parts.append(res)

    br = _short_video_bitrate(settings)
    if br:
        parts.append(br)

    audio = _short_audio(settings)
    if audio:
        parts.append(audio)

    return " · ".join(parts) if parts else "—"


def save_preset(
    name: str,
    settings: RenderJobSettings,
    *,
    load_settings: Callable[[], dict],
    save_settings: Callable[[str, Any], None],
) -> str:
    key = _normalize_name(name)
    if not key:
        raise ValueError("Preset name is empty")
    presets = load_presets_map(load_settings)
    presets[key] = settings_to_preset_dict(settings)
    save_settings(SETTINGS_KEY, presets)
    return key


def delete_preset(
    name: str,
    *,
    load_settings: Callable[[], dict],
    save_settings: Callable[[str, Any], None],
) -> bool:
    key = _normalize_name(name)
    presets = load_presets_map(load_settings)
    if key not in presets:
        return False
    del presets[key]
    save_settings(SETTINGS_KEY, presets)
    favs = [n for n in load_favourite_names(load_settings) if n != key]
    save_favourite_names(favs, load_settings=load_settings, save_settings=save_settings)
    return True


def rename_preset(
    old_name: str,
    new_name: str,
    *,
    load_settings: Callable[[], dict],
    save_settings: Callable[[str, Any], None],
) -> str:
    old_key = _normalize_name(old_name)
    new_key = _normalize_name(new_name)
    if not old_key or not new_key:
        raise ValueError("Preset name is empty")
    presets = load_presets_map(load_settings)
    if old_key not in presets:
        raise KeyError(old_key)
    if new_key != old_key and new_key in presets:
        raise FileExistsError(new_key)
    payload = presets.pop(old_key)
    presets[new_key] = payload
    save_settings(SETTINGS_KEY, presets)
    raw_favs = (load_settings() or {}).get(FAVOURITES_KEY) or []
    if isinstance(raw_favs, list) and any(
        _normalize_name(str(item)) == old_key for item in raw_favs
    ):
        remapped = [
            new_key if _normalize_name(str(item)) == old_key else str(item)
            for item in raw_favs
        ]
        save_favourite_names(
            remapped, load_settings=load_settings, save_settings=save_settings
        )
    return new_key


def duplicate_preset(
    name: str,
    *,
    load_settings: Callable[[], dict],
    save_settings: Callable[[str, Any], None],
    new_name: str | None = None,
) -> str:
    """Copy a preset under a free name (``Name (copy)``, ``Name (copy 2)``, …)."""
    key = _normalize_name(name)
    presets = load_presets_map(load_settings)
    if key not in presets:
        raise KeyError(key)
    payload = dict(presets[key])
    if new_name:
        candidate = _normalize_name(new_name)
        if not candidate:
            raise ValueError("Preset name is empty")
        if candidate in presets:
            raise FileExistsError(candidate)
    else:
        base = f"{key} (copy)"
        candidate = base
        n = 2
        while candidate in presets:
            candidate = f"{key} (copy {n})"
            n += 1
    presets[candidate] = payload
    save_settings(SETTINGS_KEY, presets)
    return candidate


def apply_preset_to_job(job: RenderJob, preset: RenderJobSettings, *, preset_name: str = "") -> None:
    """Overwrite export recipe on a job; keep trim / basename / source probe."""
    keep = job.settings
    merged = replace(
        preset_dict_to_settings(asdict(preset)),
        trim_start_ms=keep.trim_start_ms,
        trim_end_ms=keep.trim_end_ms,
        is_trim_mode=keep.is_trim_mode,
        output_basename=keep.output_basename,
        orig_fps=keep.orig_fps,
        orig_video_mbps=keep.orig_video_mbps,
        orig_audio_kbps=keep.orig_audio_kbps,
    )
    # Remember which named recipe was applied (display / future rules).
    if preset_name:
        merged.output_preset = f"User: {_normalize_name(preset_name)}"
    job.settings = merged
    job.refresh_output_path()
