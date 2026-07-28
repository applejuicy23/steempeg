"""Named user export presets — full RenderJobSettings recipes (not Share/Edit/Web).

Stored in ``settings.json`` under ``export_presets``:

```json
{
  "export_presets": {
    "Discord 720p": { "quality_text": "...", "container_format": "MP4", ... }
  }
}
```

Clip-specific fields (trim, basename, source probe) are stripped on save and
preserved when applying a preset onto an existing queue job.
"""
from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any, Callable

from steempeg.render.queue import RenderJob, RenderJobSettings, settings_from_dict

SETTINGS_KEY = "export_presets"

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


def list_preset_names(load_settings: Callable[[], dict]) -> list[str]:
    return sorted(load_presets_map(load_settings).keys(), key=str.casefold)


def get_preset_settings(
    name: str, load_settings: Callable[[], dict]
) -> RenderJobSettings | None:
    key = _normalize_name(name)
    payload = load_presets_map(load_settings).get(key)
    if payload is None:
        return None
    return preset_dict_to_settings(payload)


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
    return new_key


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
