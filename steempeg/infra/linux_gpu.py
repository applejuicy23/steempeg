"""Linux GPU / session probes for preview hwdec policy (no hard deps)."""
from __future__ import annotations

import functools
import os
import sys


def _sysfs_module_loaded(name: str) -> bool:
    return os.path.isdir(f"/sys/module/{name}")


@functools.lru_cache(maxsize=1)
def linux_has_nvidia_proprietary() -> bool:
    """True when the proprietary NVIDIA kernel driver is present.

    Same signals as Qt startup in ``app.py`` (not Nouveau-only Mesa).
    """
    if sys.platform == "win32":
        return False
    return (
        os.path.exists("/proc/driver/nvidia/version")
        or os.path.exists("/dev/nvidia0")
        or _sysfs_module_loaded("nvidia")
    )


@functools.lru_cache(maxsize=1)
def linux_has_amdgpu() -> bool:
    if sys.platform == "win32":
        return False
    if _sysfs_module_loaded("amdgpu"):
        return True
    # Vendor PCI id 0x1002 under drm cards.
    return _dri_vendor_ids_include("0x1002")


@functools.lru_cache(maxsize=1)
def linux_has_intel_i915() -> bool:
    if sys.platform == "win32":
        return False
    if _sysfs_module_loaded("i915") or _sysfs_module_loaded("xe"):
        return True
    return _dri_vendor_ids_include("0x8086")


def _dri_vendor_ids_include(vendor_hex: str) -> bool:
    """Best-effort scan of ``/sys/class/drm/card*/device/vendor``."""
    root = "/sys/class/drm"
    if not os.path.isdir(root):
        return False
    want = vendor_hex.lower()
    try:
        for name in os.listdir(root):
            if not name.startswith("card") or "-" in name:
                continue
            path = os.path.join(root, name, "device", "vendor")
            try:
                raw = open(path, encoding="ascii").read().strip().lower()
            except OSError:
                continue
            if raw == want:
                return True
    except OSError:
        return False
    return False


@functools.lru_cache(maxsize=1)
def is_steamdeck_like() -> bool:
    """Steam Deck zip channel and/or SteamOS / SteamDeck board markers."""
    if sys.platform == "win32":
        return False
    try:
        from steempeg.ui.shell_chooser import is_steamdeck_build

        if is_steamdeck_build():
            return True
    except Exception:
        pass
    # Hardware / OS without relying on update channel.
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            text = fh.read()
        if "steamdeck" in text.lower() or 'ID=steamos' in text.replace(" ", "").lower():
            return True
        if "VARIANT_ID=steamdeck" in text or 'VARIANT_ID="steamdeck"' in text:
            return True
    except OSError:
        pass
    board = "/sys/devices/virtual/dmi/id/board_name"
    try:
        name = open(board, encoding="utf-8").read().strip().lower()
        if "jupiter" in name or "steamdeck" in name or "galileo" in name:
            return True
    except OSError:
        pass
    return False


def linux_mesa_friendly() -> bool:
    """AMD / Intel / Deck — Mesa VAAPI path; not proprietary NVIDIA."""
    if linux_has_nvidia_proprietary():
        return False
    return (
        is_steamdeck_like()
        or linux_has_amdgpu()
        or linux_has_intel_i915()
    )


def resolve_linux_embed_gpu_hwdec(requested: str) -> tuple[str, str]:
    """Map Settings hwdec for ``vo=gpu`` + ``wid=`` embeds.

    Returns ``(mpv_hwdec_value, reason_tag)``.

    * ``auto`` + NVIDIA proprietary → ``no`` (XWayland wid + NVDEC: black / mush)
    * ``auto`` + Deck / AMD / Intel / unknown → ``auto`` (mpv picks vaapi/…)
    * ``yes`` → ``auto-copy`` (copy-back safer for embed than zero-copy)
    * ``no`` → ``no``

    Overrides: ``STEEMPEG_HWDEC`` (raw), ``STEEMPEG_CUDA_ZEROCOPY=1`` (keep raw).
    """
    env = (os.environ.get("STEEMPEG_HWDEC") or "").strip()
    if env:
        return env, "env_STEEMPEG_HWDEC"

    raw = (requested or "auto").strip().lower()
    zc = (os.environ.get("STEEMPEG_CUDA_ZEROCOPY") or "").strip().lower()
    if zc in ("1", "true", "yes", "on"):
        return raw, "env_STEEMPEG_CUDA_ZEROCOPY"

    if raw in ("no", "off", "software", "sw"):
        return "no", "settings_off"

    if raw in ("yes", "on", "force", "hw"):
        return "auto-copy", "settings_force_auto_copy"

    # auto (default)
    if linux_has_nvidia_proprietary():
        return "no", "nvidia_xwayland_embed"
    if is_steamdeck_like():
        return "auto", "steamdeck_mesa"
    if linux_has_amdgpu():
        return "auto", "amd_mesa"
    if linux_has_intel_i915():
        return "auto", "intel_mesa"
    return "auto", "linux_default_auto"
