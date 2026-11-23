"""Recolor purple pixels in the original Steempeg artwork."""
from __future__ import annotations

from colorsys import hsv_to_rgb, rgb_to_hsv
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageFilter


@lru_cache(maxsize=1)
def _tint_lut(color: str) -> ImageFilter.Color3DLUT:
    target = tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    target_hue, target_saturation, target_value = rgb_to_hsv(*target)

    def tint(r: float, g: float, b: float) -> tuple[float, float, float]:
        hue, saturation, value = rgb_to_hsv(r, g, b)
        if not 0.64 <= hue <= 0.86 or saturation < 0.08:
            return r, g, b
        # Blend the low-saturation antialiasing at the edge of the ring.
        strength = min(1.0, (saturation - 0.08) / 0.16)
        shade = min(1.0, max(0.0, target_value + (value - 0.906) * 0.55))
        colored = hsv_to_rgb(
            target_hue, min(1.0, saturation * target_saturation / 0.33), shade
        )
        return tuple(src + (dst - src) * strength for src, dst in zip((r, g, b), colored))

    return ImageFilter.Color3DLUT.generate(33, tint)


def save_tinted_artwork(source: str | Path, destination: str | Path, color: str) -> None:
    with Image.open(source) as original:
        rgba = original.convert("RGBA")
        result = rgba.convert("RGB").filter(_tint_lut(color))
        result.putalpha(rgba.getchannel("A"))
        if original.format == "ICO":
            result.save(destination, sizes=sorted(original.ico.sizes()))
        else:
            result.save(destination)


@lru_cache(maxsize=1)
def _artwork_directory() -> TemporaryDirectory:
    # QIcon and the Win32 icon loader can open these paths after the picker closes.
    return TemporaryDirectory(prefix="steempeg-pro-")


def tinted_asset_path(source: str, color: str) -> str:
    path = Path(source)
    destination = Path(_artwork_directory().name) / f"{path.stem}_{color[1:]}{path.suffix}"
    if not destination.is_file():
        save_tinted_artwork(path, destination, color)
    return str(destination)
