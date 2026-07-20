"""MPV preview downscale presets — playback only, not export."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

SETTINGS_KEY = "preview_quality"
DEFAULT_QUALITY = "source"
VF_LABEL = "steempeg_preview"

_PREVIEW_MENU_STYLE = """
    QMenu {
        background-color: #2d2d2d;
        color: #ffffff;
        border: 2px solid #444444;
        border-radius: 8px;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
        font-size: 13px;
        font-weight: bold;
        padding: 4px 0px;
    }
    QMenu::item {
        padding: 6px 28px 6px 16px;
        border-radius: 4px;
        margin: 2px 6px;
    }
    QMenu::item:selected {
        background-color: #6b5a8e;
    }
    QMenu::item:disabled {
        color: #888888;
        background: transparent;
        font-weight: normal;
        font-size: 11px;
        padding-top: 2px;
        padding-bottom: 8px;
    }
    QMenu::separator {
        height: 1px;
        background-color: #444444;
        margin: 4px 10px;
    }
"""


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


def _source_height(player) -> int:
    """Best-effort decoded video height (Linux often has height=0 until params settle)."""
    for attr in ("video-params/h", "dheight", "height"):
        try:
            # python-mpv exposes nested props via mapping / getattr.
            if "/" in attr:
                val = player[attr]
            else:
                val = getattr(player, attr, None)
                if val is None:
                    try:
                        val = player[attr]
                    except Exception:
                        val = None
            h = int(val or 0)
            if h > 0:
                return h
        except Exception:
            continue
    return 0


def _vf_candidates(player, max_height: int) -> tuple[str, ...]:
    """Build filter bodies; Windows can use D3D11 VPP, Linux prefers software scale."""
    out: list[str] = []
    src_h = _source_height(player)
    h = max_height

    if src_h > max_height and os.name == "nt":
        factor = max_height / src_h
        if 0.0 < factor < 1.0:
            out.append(f"d3d11vpp=scale={factor:.6f}")

    # Linux (xv/x11 embed): software scale first — lavfi+hwdownload fails without HW frames.
    if os.name != "nt":
        out.extend(
            (
                f"scale=-2:{h}:flags=lanczos:force_original_aspect_ratio=decrease",
                f"lavfi=[scale=-2:{h}:flags=lanczos:force_original_aspect_ratio=decrease]",
                f"scale=-2:{h}:force_original_aspect_ratio=decrease",
            )
        )

    out.extend(
        (
            f"lavfi=[hwdownload,scale=-2:{h}:force_original_aspect_ratio=decrease]",
            f"lavfi-scale=-2:{h}:force_original_aspect_ratio=decrease",
            f"scale=-2:{h}:force_original_aspect_ratio=decrease",
        )
    )
    # Dedupe while preserving order.
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
    for token in (VF_LABEL, f"@{VF_LABEL}"):
        try:
            player.command("vf", "remove", token)
        except Exception:
            pass
        try:
            player.command("change-list", "vf", "remove", token)
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


def source_height(player) -> int:
    return _source_height(player)


def apply_mpv_preview_quality(player, preset_id: str) -> bool:
    """Swap preview vf live — no file reload, timeline position untouched."""
    if not player:
        return True

    preset = _preset(preset_id)
    remove_preview_vf(player)
    if preset.max_height is None:
        logging.info("Preview quality: Source")
        return True

    src_h = _source_height(player)
    if src_h and src_h <= preset.max_height:
        logging.info(
            "Preview quality %s: source is %sp (already <= %sp), no downscale",
            preset_id,
            src_h,
            preset.max_height,
        )
        return True

    last_error = ""
    for body in _vf_candidates(player, preset.max_height):
        tagged = _labeled(body)
        remove_preview_vf(player)
        try:
            if not _try_add_vf(player, tagged):
                continue
            logging.info("Preview quality %s -> %s (source %sp)", preset_id, tagged, src_h or "?")
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
    return _PREVIEW_MENU_STYLE
