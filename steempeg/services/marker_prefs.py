"""Persisted marker appearance prefs: icon packs, classes, per-marker overrides.

Stored in ``<save>/cache/marker_prefs.json``. Timeline / editors read this to
decide Steam SVG vs Steempeg CS2 PNGs, class tint/name, and custom icons.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from copy import deepcopy

from steempeg.infra import cache
from steempeg.infra.paths import get_resource_path, get_save_directory

_log = logging.getLogger(__name__)

CS2_APP_ID = "730"

# Emily's drawn pack (legacy timeline PNGs) vs Steam markers.svg sprites.
PACK_STEAM = "steam"
PACK_STEEMPEG = "steempeg"

# Built-in CS2 / generic keys that map to assets/*.png (smpeg20 era).
LEGACY_ICON_KEYS: tuple[str, ...] = (
    "kill",
    "knife",
    "tazer",
    "grenade",
    "firemolotov",
    "flashbang",
    "smoke",
    "bomb",
    "explosion",
    "defuse",
    "death",
    "screenshot",
    "restrict",
    "point",
    "usermarker",
)

LEGACY_KEY_TO_ASSET: dict[str, str] = {
    "kill": "kill.png",
    "knife": "knife.png",
    "tazer": "tazer.png",
    "grenade": "grenade.png",
    "firemolotov": "firemolotov.png",
    "flashbang": "flashbang.png",
    "smoke": "smoke.png",
    "bomb": "bomb.png",
    "explosion": "explosion.png",
    "defuse": "defuse.png",
    "death": "death.png",
    "screenshot": "screenshot.png",
    "restrict": "restrict.png",
    "point": "point.png",
    "usermarker": "pointuser.png",
}

# Auto colors when a class has no custom icon (white glyphs get tinted).
CLASS_PALETTE: tuple[str, ...] = (
    "#b29ae7",
    "#7ec8e3",
    "#f0a878",
    "#e88a9a",
    "#8fd4a0",
    "#e8d27a",
    "#9aa7e8",
    "#e89ad4",
    "#a8c4ff",
    "#ffb3a8",
)

_DEFAULTS: dict = {
    "cs2_icon_pack": PACK_STEAM,
    "classes": [],
    # marker_key → {class_id, custom_icon, label}
    # marker_key is Steam icon id (cs2_death) or legacy key (kill / usermarker).
    "markers": {},
    # Icon ids discovered from clips / SVG (for the settings list).
    "known_marker_ids": [],
}


def _prefs_path() -> str:
    return os.path.join(get_save_directory(), "cache", "marker_prefs.json")


def _empty() -> dict:
    return deepcopy(_DEFAULTS)


def load_marker_prefs() -> dict:
    data = cache.read_json(_prefs_path())
    if not isinstance(data, dict):
        return _empty()
    out = _empty()
    pack = data.get("cs2_icon_pack", PACK_STEAM)
    out["cs2_icon_pack"] = pack if pack in (PACK_STEAM, PACK_STEEMPEG) else PACK_STEAM
    classes = data.get("classes")
    if isinstance(classes, list):
        out["classes"] = [c for c in classes if isinstance(c, dict) and c.get("id")]
    markers = data.get("markers")
    if isinstance(markers, dict):
        out["markers"] = {
            str(k): v for k, v in markers.items() if isinstance(v, dict)
        }
    known = data.get("known_marker_ids")
    if isinstance(known, list):
        out["known_marker_ids"] = sorted(
            {str(x) for x in known if str(x).strip()}
        )
    return out


def save_marker_prefs(data: dict) -> None:
    path = _prefs_path()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    except OSError as exc:
        _log.debug("marker prefs dir: %s", exc)
    payload = _empty()
    if isinstance(data, dict):
        pack = data.get("cs2_icon_pack", PACK_STEAM)
        payload["cs2_icon_pack"] = (
            pack if pack in (PACK_STEAM, PACK_STEEMPEG) else PACK_STEAM
        )
        if isinstance(data.get("classes"), list):
            payload["classes"] = data["classes"]
        if isinstance(data.get("markers"), dict):
            payload["markers"] = data["markers"]
        if isinstance(data.get("known_marker_ids"), list):
            payload["known_marker_ids"] = sorted(
                {str(x) for x in data["known_marker_ids"] if str(x).strip()}
            )
    cache.write_json(path, payload)


def cs2_icon_pack(prefs: dict | None = None) -> str:
    data = prefs if prefs is not None else load_marker_prefs()
    pack = data.get("cs2_icon_pack", PACK_STEAM)
    return pack if pack in (PACK_STEAM, PACK_STEEMPEG) else PACK_STEAM


def set_cs2_icon_pack(pack: str) -> dict:
    data = load_marker_prefs()
    data["cs2_icon_pack"] = (
        pack if pack in (PACK_STEAM, PACK_STEEMPEG) else PACK_STEAM
    )
    save_marker_prefs(data)
    return data


def prefer_steempeg_pack(app_id: str | None, prefs: dict | None = None) -> bool:
    """True → use Emily's PNG pack instead of Steam SVG (CS2 only)."""
    if str(app_id or "") != CS2_APP_ID:
        return False
    return cs2_icon_pack(prefs) == PACK_STEEMPEG


def next_class_color(existing_count: int) -> str:
    return CLASS_PALETTE[existing_count % len(CLASS_PALETTE)]


def create_class(
    name: str | None = None,
    *,
    color: str | None = None,
    icon: str | None = None,
) -> dict:
    data = load_marker_prefs()
    classes = list(data.get("classes") or [])
    idx = len(classes) + 1
    cls = {
        "id": f"cls_{uuid.uuid4().hex[:8]}",
        "name": (name or f"Class {idx}").strip() or f"Class {idx}",
        "color": color or next_class_color(len(classes)),
        "icon": icon or "",
    }
    classes.append(cls)
    data["classes"] = classes
    save_marker_prefs(data)
    return cls


def delete_class(class_id: str) -> None:
    data = load_marker_prefs()
    cid = str(class_id)
    data["classes"] = [
        c for c in (data.get("classes") or []) if str(c.get("id")) != cid
    ]
    markers = dict(data.get("markers") or {})
    for key, ov in list(markers.items()):
        if str(ov.get("class_id") or "") == cid:
            ov = dict(ov)
            ov["class_id"] = ""
            markers[key] = ov
    data["markers"] = markers
    save_marker_prefs(data)


def update_class(class_id: str, **fields) -> dict | None:
    data = load_marker_prefs()
    cid = str(class_id)
    for cls in data.get("classes") or []:
        if str(cls.get("id")) != cid:
            continue
        if "name" in fields and fields["name"] is not None:
            cls["name"] = str(fields["name"]).strip() or cls.get("name") or "Class"
        if "color" in fields and fields["color"]:
            cls["color"] = str(fields["color"])
        if "icon" in fields:
            cls["icon"] = str(fields["icon"] or "")
        save_marker_prefs(data)
        return cls
    return None


def get_class(class_id: str | None, prefs: dict | None = None) -> dict | None:
    if not class_id:
        return None
    data = prefs if prefs is not None else load_marker_prefs()
    cid = str(class_id)
    for cls in data.get("classes") or []:
        if str(cls.get("id")) == cid:
            return cls
    return None


def marker_override(marker_key: str, prefs: dict | None = None) -> dict:
    data = prefs if prefs is not None else load_marker_prefs()
    raw = (data.get("markers") or {}).get(str(marker_key)) or {}
    return {
        "class_id": str(raw.get("class_id") or ""),
        "custom_icon": str(raw.get("custom_icon") or ""),
        "label": str(raw.get("label") or ""),
    }


def set_marker_override(
    marker_key: str,
    *,
    class_id: str | None = None,
    custom_icon: str | None = None,
    label: str | None = None,
    clear_missing: bool = False,
) -> dict:
    data = load_marker_prefs()
    key = str(marker_key)
    ov = dict((data.get("markers") or {}).get(key) or {})
    if class_id is not None:
        ov["class_id"] = str(class_id)
    elif clear_missing:
        ov.pop("class_id", None)
    if custom_icon is not None:
        ov["custom_icon"] = str(custom_icon)
    elif clear_missing:
        ov.pop("custom_icon", None)
    if label is not None:
        ov["label"] = str(label)
    elif clear_missing:
        ov.pop("label", None)
    # Drop empty override entries.
    cleaned = {
        k: v
        for k, v in ov.items()
        if v not in ("", None)
    }
    markers = dict(data.get("markers") or {})
    if cleaned:
        markers[key] = cleaned
    else:
        markers.pop(key, None)
    data["markers"] = markers
    remember_marker_ids([key], data=data, save=False)
    save_marker_prefs(data)
    return cleaned


def reset_marker_override(marker_key: str) -> None:
    data = load_marker_prefs()
    markers = dict(data.get("markers") or {})
    markers.pop(str(marker_key), None)
    data["markers"] = markers
    save_marker_prefs(data)


def reset_all_marker_overrides(*, keep_classes: bool = True) -> None:
    data = load_marker_prefs()
    data["markers"] = {}
    if not keep_classes:
        data["classes"] = []
    save_marker_prefs(data)


def reset_steam_marker_overrides() -> None:
    """Clear overrides for non-usermarker keys (in-game / Steam ids)."""
    data = load_marker_prefs()
    markers = dict(data.get("markers") or {})
    data["markers"] = {
        k: v for k, v in markers.items() if k in ("usermarker",) or k.startswith("user_")
    }
    save_marker_prefs(data)


def remember_marker_ids(
    ids,
    *,
    data: dict | None = None,
    save: bool = True,
) -> list[str]:
    prefs = data if data is not None else load_marker_prefs()
    known = set(prefs.get("known_marker_ids") or [])
    for raw in ids or ():
        s = str(raw or "").strip()
        if s:
            known.add(s)
    prefs["known_marker_ids"] = sorted(known)
    if save and data is None:
        save_marker_prefs(prefs)
    elif save and data is not None:
        save_marker_prefs(prefs)
    return prefs["known_marker_ids"]


def list_svg_element_ids(svg_path: str) -> list[str]:
    """Parse ``id="..."`` attributes from a markers.svg (best-effort)."""
    if not svg_path or not os.path.isfile(svg_path):
        return []
    try:
        with open(svg_path, "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read()
    except OSError:
        return []
    ids = re.findall(r'\bid="([^"]+)"', raw)
    # Skip structural junk.
    skip = {"svg", "defs", "g", "path", "clipPath", "mask", "linearGradient"}
    return sorted({i for i in ids if i and i not in skip and not i.startswith("SVGID")})


FRIENDLY_LABEL_EN: dict[str, str] = {
    "kill": "Kill",
    "death": "Death",
    "knife": "Knife",
    "tazer": "Zeus",
    "grenade": "Grenade",
    "firemolotov": "Molotov",
    "flashbang": "Flashbang",
    "smoke": "Smoke",
    "bomb": "Bomb",
    "explosion": "Explosion",
    "defuse": "Defuse",
    "screenshot": "Screenshot",
    "restrict": "Restrict",
    "point": "Event",
    "usermarker": "Custom marker",
}

# Reserved for future localization (Spanish, Russian, …).
FRIENDLY_LABEL_RU: dict[str, str] = {
    "kill": "Убийство",
    "death": "Смерть",
    "knife": "Нож",
    "tazer": "Zeus",
    "grenade": "Граната",
    "firemolotov": "Молотов",
    "flashbang": "Флешка",
    "smoke": "Смок",
    "bomb": "Бомба",
    "explosion": "Взрыв",
    "defuse": "Разминирование",
    "screenshot": "Скриншот",
    "restrict": "Ограничение",
    "point": "Событие",
    "usermarker": "Своя метка",
}


def is_round_number_key(key: str) -> bool:
    """Round markers use icon_key '1'..'30' — not configurable IDs."""
    return bool(re.fullmatch(r"\d+", str(key or "").strip()))


def friendly_marker_label(key: str, *, title: str = "") -> str:
    """Human label for settings UI."""
    if title and str(title).strip():
        return str(title).strip()
    k = str(key or "")
    if is_round_number_key(k):
        return f"Round {k}"
    if k in FRIENDLY_LABEL_EN:
        return FRIENDLY_LABEL_EN[k]
    if k.startswith("cs2_"):
        return k.replace("cs2_", "").replace("_", " ").title()
    return k


def catalog_marker_keys(
    *,
    app_id: str | None = None,
    clip_marker_icons: list[str] | None = None,
    clip_icon_keys: list[str] | None = None,
    prefs: dict | None = None,
) -> list[dict]:
    """Unified list for the settings UI: key, kind, label hint."""
    data = prefs if prefs is not None else load_marker_prefs()
    rows: dict[str, dict] = {}

    def _add(key: str, kind: str, hint: str = "") -> None:
        key = str(key)
        if not key or key in rows:
            return
        if is_round_number_key(key):
            return
        rows[key] = {"key": key, "kind": kind, "hint": hint}

    for k in LEGACY_ICON_KEYS:
        _add(k, "legacy", LEGACY_KEY_TO_ASSET.get(k, ""))

    for k in data.get("known_marker_ids") or []:
        kind = "steam" if ("_" in k or k.startswith("cs")) else "legacy"
        if k in LEGACY_ICON_KEYS:
            kind = "legacy"
        if k == "usermarker":
            kind = "user"
        _add(k, kind)

    for k in clip_marker_icons or ():
        _add(str(k), "steam")
    for k in clip_icon_keys or ():
        _add(str(k), "legacy" if str(k) in LEGACY_ICON_KEYS else "steam")

    if app_id:
        try:
            from steempeg.services.steam_markers import resolve_markers_svg_path_local

            svg = resolve_markers_svg_path_local(app_id)
            for eid in list_svg_element_ids(svg or ""):
                _add(eid, "steam")
        except Exception:
            pass

    # Prefer stable order: user, legacy, then steam alpha.
    def _sort_key(row: dict):
        k = row["key"]
        kind = row["kind"]
        pri = {"user": 0, "legacy": 1, "steam": 2}.get(kind, 3)
        return (pri, k.lower())

    return sorted(rows.values(), key=_sort_key)


def clip_marker_setting_rows(clip_markers: list | None) -> list[dict]:
    """Unique configurable keys from the open clip — what users actually care about."""
    rows: dict[str, dict] = {}
    for m in clip_markers or ():
        steam_icon = str(m.get("icon") or "").strip()
        icon_key = str(m.get("icon_key") or "").strip()
        if m.get("is_round"):
            continue
        key = steam_icon or icon_key
        if not key or is_round_number_key(key):
            continue
        title = str(m.get("title") or "")
        rows[key] = {
            "key": key,
            "kind": "user" if icon_key == "usermarker" else "steam" if steam_icon else "legacy",
            "title": title,
            "label": friendly_marker_label(key, title=title),
        }
    return sorted(rows.values(), key=lambda r: r["label"].lower())


def legacy_asset_path(icon_key: str) -> str | None:
    name = LEGACY_KEY_TO_ASSET.get(str(icon_key))
    if not name:
        return None
    path = get_resource_path(name)
    return path if path and os.path.isfile(path) else None


def resolve_display_label(
    marker_key: str,
    *,
    fallback: str = "",
    prefs: dict | None = None,
) -> str:
    ov = marker_override(marker_key, prefs)
    if ov.get("label"):
        return ov["label"]
    cls = get_class(ov.get("class_id"), prefs)
    if cls and cls.get("name"):
        return str(cls["name"])
    return fallback or marker_key


def resolve_tint_color(
    marker_key: str,
    *,
    prefs: dict | None = None,
) -> str | None:
    """Class color for tinting white glyphs; None = leave as-is."""
    ov = marker_override(marker_key, prefs)
    cls = get_class(ov.get("class_id"), prefs)
    if not cls:
        return None
    # Class custom icon replaces tint.
    if cls.get("icon") and os.path.isfile(str(cls["icon"])):
        return None
    color = str(cls.get("color") or "").strip()
    return color or None


def resolve_custom_icon_path(
    marker_key: str,
    *,
    prefs: dict | None = None,
) -> str | None:
    ov = marker_override(marker_key, prefs)
    custom = ov.get("custom_icon") or ""
    if custom and os.path.isfile(custom):
        return custom
    cls = get_class(ov.get("class_id"), prefs)
    if cls:
        icon = str(cls.get("icon") or "")
        if icon and os.path.isfile(icon):
            return icon
    return None
