"""MPV preview downscale presets — playback only, not export."""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

SETTINGS_KEY = "preview_quality"
DEFAULT_QUALITY = "source"
VF_LABEL = "steempeg_preview"

# True decoded height for the current file. video-params/h follows vf and must
# never drive the d3d11vpp factor (that was the flaky compounding bug).
_cached_source_h: int = 0


@dataclass(frozen=True)
class PreviewQualityPreset:
    id: str
    label: str
    max_height: int | None  # None = native source


PRESETS: tuple[PreviewQualityPreset, ...] = (
    PreviewQualityPreset("source", "Source", None),
    PreviewQualityPreset("1080p", "1080p", 1080),
    PreviewQualityPreset("720p", "720p", 720),
    PreviewQualityPreset("480p", "480p", 480),
    PreviewQualityPreset("360p", "360p", 360),
)


def normalize_quality_id(preset_id: str | None) -> str:
    if preset_id:
        for preset in PRESETS:
            if preset.id == preset_id:
                return preset.id
    return DEFAULT_QUALITY


def _preset(preset_id: str) -> PreviewQualityPreset:
    return next((p for p in PRESETS if p.id == preset_id), PRESETS[0])


def reset_source_height_cache() -> None:
    """Call when loading a new clip/file so a prior 1440p cache cannot leak."""
    global _cached_source_h
    _cached_source_h = 0


def _mpv_prop(player, name: str) -> int:
    try:
        if "/" in name:
            val = player[name]
        else:
            val = getattr(player, name, None)
            if val is None:
                try:
                    val = player[name]
                except Exception:
                    val = None
        return int(val or 0)
    except Exception:
        return 0


def _dict_height(params) -> int:
    if not isinstance(params, dict):
        return 0
    for key in ("h", "dh", "H", "height"):
        try:
            h = int(params.get(key) or 0)
        except Exception:
            h = 0
        if h > 0:
            return h
    return 0


def _decoded_height(player) -> int:
    """Height from the decoder — unaffected by vf. Prefer this always."""
    for attr in ("video-dec-params/h", "video-dec-params/dh"):
        h = _mpv_prop(player, attr)
        if h > 0:
            return h
    try:
        h = _dict_height(player["video-dec-params"])
        if h > 0:
            return h
    except Exception:
        pass
    return 0


def _output_height(player) -> int:
    """Post-vf / display height — only safe when our preview vf is absent."""
    for attr in ("video-params/h", "dheight", "height"):
        h = _mpv_prop(player, attr)
        if h > 0:
            return h
    try:
        h = _dict_height(player["video-params"])
        if h > 0:
            return h
    except Exception:
        pass
    return 0


def _has_preview_vf(player) -> bool:
    try:
        raw = player["vf"]
    except Exception:
        return False
    if not raw:
        return False
    if isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, dict) and item.get("label") == VF_LABEL:
                return True
            if VF_LABEL in str(item):
                return True
        return False
    return VF_LABEL in str(raw)


def _remember_source_h(h: int) -> int:
    """Keep the largest plausible decode height for this file."""
    global _cached_source_h
    if h <= 0:
        return _cached_source_h
    # Ignore tiny/stale post-filter reads once we know the real source.
    if _cached_source_h > 0 and h < _cached_source_h:
        return _cached_source_h
    _cached_source_h = h
    return _cached_source_h


def resolve_source_height(player) -> int:
    """Stable source height for factor math."""
    dec = _decoded_height(player)
    if dec > 0:
        return _remember_source_h(dec)
    # Only trust output size when our downscale filter is not in the chain.
    if player and not _has_preview_vf(player):
        out = _output_height(player)
        if out > 0:
            return _remember_source_h(out)
    return _cached_source_h


def source_height(player) -> int:
    return resolve_source_height(player)


def _vf_candidates(src_h: int, max_height: int) -> tuple[str, ...]:
    """Build filter bodies. Windows hwdec needs d3d11vpp with factor from true src."""
    out: list[str] = []
    h = int(max_height)

    if src_h > max_height and os.name == "nt":
        factor = max_height / float(src_h)
        if 0.0 < factor < 1.0:
            out.append(f"d3d11vpp=scale={factor:.6f}")

    if os.name != "nt":
        out.extend(
            (
                f"scale=-2:{h}:flags=lanczos:force_original_aspect_ratio=decrease",
                f"lavfi=[scale=-2:{h}:flags=lanczos:force_original_aspect_ratio=decrease]",
                f"scale=-2:{h}:force_original_aspect_ratio=decrease",
            )
        )

    # Last-resort software path (often fails under d3d11va — verified below).
    out.extend(
        (
            f"lavfi=[hwdownload,format=nv12,scale=-2:{h}:force_original_aspect_ratio=decrease]",
            f"lavfi=[hwdownload,scale=-2:{h}:force_original_aspect_ratio=decrease]",
            f"scale=-2:{h}:flags=lanczos:force_original_aspect_ratio=decrease",
        )
    )

    seen: set[str] = set()
    unique: list[str] = []
    for body in out:
        if body not in seen:
            seen.add(body)
            unique.append(body)
    return tuple(unique)


def _labeled(body: str) -> str:
    return f"@{VF_LABEL}:{body}"


def remove_preview_vf(player) -> None:
    if not player:
        return
    for token in (f"@{VF_LABEL}", VF_LABEL):
        try:
            player.command("vf", "remove", token)
        except Exception:
            pass
        try:
            player.command("change-list", "vf", "remove", token)
        except Exception:
            pass
    # Nuclear clear — Steempeg only uses this one user vf for preview quality.
    try:
        if _has_preview_vf(player):
            player["vf"] = ""
    except Exception:
        try:
            player["vf"] = ""
        except Exception:
            pass


def _try_add_vf(player, tagged: str) -> bool:
    try:
        player.command("vf", "add", tagged)
        return True
    except Exception:
        pass
    try:
        player.command("change-list", "vf", "append", tagged)
        return True
    except Exception:
        pass
    try:
        player["vf"] = tagged
        return True
    except Exception:
        return False


def _preview_vf_alive(player) -> bool:
    try:
        raw = player["vf"]
    except Exception:
        return False
    if not raw:
        return False
    if isinstance(raw, (list, tuple)):
        for item in raw:
            if not isinstance(item, dict):
                if VF_LABEL in str(item):
                    return True
                continue
            if item.get("label") == VF_LABEL:
                return bool(item.get("enabled", True))
        return False
    return VF_LABEL in str(raw)


def _wait_source_height(player, *, rounds: int = 10) -> int:
    """After vf remove, params can lag one tick — poll before factor math."""
    src_h = 0
    for _ in range(max(1, rounds)):
        src_h = resolve_source_height(player)
        if src_h > 0:
            return src_h
        time.sleep(0.02)
    return src_h


def apply_mpv_preview_quality(player, preset_id: str) -> bool:
    """Swap preview vf live — no file reload, timeline position untouched."""
    if not player:
        return True

    preset = _preset(preset_id)
    remove_preview_vf(player)
    if preset.max_height is None:
        logging.info("Preview quality: Source")
        return True

    src_h = _wait_source_height(player)
    if not src_h:
        logging.info(
            "Preview quality %s: source height unknown — defer",
            preset_id,
        )
        return False

    if src_h <= preset.max_height:
        logging.info(
            "Preview quality %s: source is %sp (already <= %sp), no downscale",
            preset_id,
            src_h,
            preset.max_height,
        )
        return True

    last_error = ""
    for body in _vf_candidates(src_h, preset.max_height):
        tagged = _labeled(body)
        remove_preview_vf(player)
        try:
            if not _try_add_vf(player, tagged):
                continue
            # lavfi can "add" then disable under d3d11 — only accept live filters.
            alive = False
            for _ in range(5):
                time.sleep(0.02)
                if _preview_vf_alive(player):
                    alive = True
                    break
            if not alive:
                logging.debug("Preview quality candidate failed (disabled): %s", tagged)
                remove_preview_vf(player)
                continue
            logging.info(
                "Preview quality %s -> %s (source %sp)",
                preset_id,
                tagged,
                src_h,
            )
            try:
                logging.debug("MPV vf now: %r", player["vf"])
            except Exception:
                pass
            return True
        except Exception as exc:
            last_error = str(exc)
            remove_preview_vf(player)

    logging.warning(
        "Preview quality apply failed (%s): %s — using Source",
        preset_id,
        last_error or "unknown",
    )
    return False


def menu_stylesheet() -> str:
    from steempeg.ui import ui_theme as ut

    return ut.preview_quality_menu_stylesheet()
