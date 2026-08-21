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
    # Old builds wrote icon/class under shared usermarker/steam_marker — that
    # painted every custom pin the same. Drop those type keys; keep user_<id>.
    if _scrub_shared_user_type_overrides(out):
        save_marker_prefs(out)
    return out


# Type-level keys that must never hold per-pin custom icons (legacy mistake).
_SHARED_USER_TYPE_KEYS = frozenset({"usermarker", "steam_marker"})
_SHARED_SHOT_TYPE_KEYS = frozenset({"screenshot", "steam_screenshot"})
_SHARED_INSTANCE_TYPE_KEYS = _SHARED_USER_TYPE_KEYS | _SHARED_SHOT_TYPE_KEYS


def _scrub_shared_user_type_overrides(prefs: dict) -> bool:
    markers = dict(prefs.get("markers") or {})
    changed = False
    for key in _SHARED_INSTANCE_TYPE_KEYS:
        if key in markers:
            markers.pop(key, None)
            changed = True
    if changed:
        prefs["markers"] = markers
    return changed


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
        if "color" in fields:
            # Empty string = group-only class (no tint attribute).
            cls["color"] = str(fields["color"] or "").strip()
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


def class_has_color(cls: dict | None) -> bool:
    if not cls:
        return False
    return bool(str(cls.get("color") or "").strip())


def marker_override(marker_key: str, prefs: dict | None = None) -> dict:
    data = prefs if prefs is not None else load_marker_prefs()
    raw = (data.get("markers") or {}).get(str(marker_key)) or {}
    return {
        "class_id": str(raw.get("class_id") or ""),
        "custom_icon": str(raw.get("custom_icon") or ""),
        "label": str(raw.get("label") or ""),
        # Exception: stay in a colored class but keep the glyph / art untinted.
        "no_tint": bool(raw.get("no_tint")),
    }


def set_marker_override(
    marker_key: str,
    *,
    class_id: str | None = None,
    custom_icon: str | None = None,
    label: str | None = None,
    no_tint: bool | None = None,
    clear_missing: bool = False,
) -> dict:
    key = str(marker_key)
    # Never store appearance on shared type keys — would apply to every custom pin.
    if key in _SHARED_INSTANCE_TYPE_KEYS:
        _log.warning("refusing marker override on shared key %r", key)
        return {}
    data = load_marker_prefs()
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
    if no_tint is not None:
        if no_tint:
            ov["no_tint"] = True
        else:
            ov.pop("no_tint", None)
    elif clear_missing:
        ov.pop("no_tint", None)
    # Drop empty override entries.
    cleaned = {
        k: v
        for k, v in ov.items()
        if v not in ("", None, False)
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


def is_user_marker(marker: dict | None) -> bool:
    """True for Steempeg / Steam custom pins (not kill/death/etc.)."""
    if not marker:
        return False
    icon_key = str(marker.get("icon_key") or "").strip()
    steam_icon = str(marker.get("icon") or "").strip()
    return icon_key == "usermarker" or steam_icon in ("steam_marker", "usermarker")


def is_screenshot_marker(marker: dict | None) -> bool:
    if not marker:
        return False
    icon_key = str(marker.get("icon_key") or "").strip()
    steam_icon = str(marker.get("icon") or "").strip()
    return icon_key == "screenshot" or steam_icon in (
        "steam_screenshot",
        "screenshot",
    )


def is_tintable_marker(marker: dict | None) -> bool:
    """White glyphs that take a class color tint (custom pins + screenshots)."""
    return is_user_marker(marker) or is_screenshot_marker(marker)


def user_instance_prefs_key(marker_id: str | None, *, time_ms: int | None = None) -> str:
    """Per-instance prefs key so each custom pin can have its own class/icon."""
    mid = str(marker_id or "").strip()
    if mid:
        return f"user_{mid}"
    if time_ms is not None:
        return f"user_t{int(time_ms)}"
    return "usermarker"


def screenshot_instance_prefs_key(
    marker_id: str | None, *, time_ms: int | None = None
) -> str:
    mid = str(marker_id or "").strip()
    if mid:
        return f"shot_{mid}"
    if time_ms is not None:
        return f"shot_t{int(time_ms)}"
    return "screenshot"


def marker_resolve_keys(marker: dict) -> list[str]:
    """Preference lookup order for a timeline marker.

    Custom pins and screenshots use only their instance key — never fall back to
    shared type overrides (that leaked one icon onto every pin).
    """
    if is_user_marker(marker):
        return [
            user_instance_prefs_key(
                marker.get("id"),
                time_ms=marker.get("time_ms"),
            )
        ]
    if is_screenshot_marker(marker):
        return [
            screenshot_instance_prefs_key(
                marker.get("id"),
                time_ms=marker.get("time_ms"),
            )
        ]
    keys: list[str] = []
    steam_icon = str(marker.get("icon") or "").strip()
    icon_key = str(marker.get("icon_key") or "").strip()
    for k in (steam_icon, icon_key):
        if k and k not in keys:
            keys.append(k)
    return keys


def format_marker_timecode(time_ms: int | None) -> str:
    """Compact clip-relative timecode for On clip list rows (m:ss or h:mm:ss)."""
    ms = max(0, int(time_ms or 0))
    total_s = ms // 1000
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def clip_marker_setting_rows(clip_markers: list | None) -> list[dict]:
    """Configurable rows from the open clip — one row per marker instance.

    Custom pins and screenshots keep per-instance prefs keys. Game markers
    (kill, death, …) are listed individually but still share one prefs key per
    Steam/legacy type (``shared_type`` + ``type_count`` for the settings UI).
    Round-number markers are skipped (not configurable).
    """
    user_rows: list[dict] = []
    shot_rows: list[dict] = []
    game_rows: list[dict] = []
    unnamed_n = 0
    shot_n = 0
    type_counts: dict[str, int] = {}

    ordered = sorted(
        list(clip_markers or ()),
        key=lambda m: (int(m.get("time_ms") or 0), str(m.get("id") or "")),
    )
    for i, m in enumerate(ordered):
        if m.get("is_round"):
            continue
        steam_icon = str(m.get("icon") or "").strip()
        icon_key = str(m.get("icon_key") or "").strip()
        marker_id = str(m.get("id") or "")
        time_ms = int(m.get("time_ms") or 0)

        if is_user_marker(m):
            key = user_instance_prefs_key(m.get("id"), time_ms=m.get("time_ms"))
            title = str(m.get("title") or "").strip()
            if title:
                label = title
            else:
                unnamed_n += 1
                label = f"Custom Marker {unnamed_n}"
            user_rows.append(
                {
                    "row_id": key,
                    "key": key,
                    "kind": "user",
                    "title": title,
                    "label": label,
                    "marker_id": marker_id,
                    "time_ms": time_ms,
                    "raw_time_ms": m.get("raw_time_ms"),
                    "icon": steam_icon,
                    "icon_key": icon_key or "usermarker",
                    "shared_type": False,
                    "type_count": 1,
                }
            )
            continue

        if is_screenshot_marker(m):
            shot_n += 1
            key = screenshot_instance_prefs_key(
                m.get("id"), time_ms=m.get("time_ms")
            )
            title = str(m.get("title") or "").strip()
            if title and title.lower() not in ("a screenshot", "screenshot"):
                label = title
            else:
                label = f"Screenshot {shot_n}"
            shot_rows.append(
                {
                    "row_id": key,
                    "key": key,
                    "kind": "screenshot",
                    "title": title,
                    "label": label,
                    "marker_id": marker_id,
                    "time_ms": time_ms,
                    "raw_time_ms": m.get("raw_time_ms"),
                    "icon": steam_icon,
                    "icon_key": icon_key or "screenshot",
                    "shared_type": False,
                    "type_count": 1,
                }
            )
            continue

        key = steam_icon or icon_key
        if not key or is_round_number_key(key):
            continue
        title = str(m.get("title") or "")
        type_counts[key] = type_counts.get(key, 0) + 1
        if marker_id:
            row_id = f"game_{marker_id}"
        else:
            row_id = f"game_{key}_t{time_ms}_{i}"
        game_rows.append(
            {
                "row_id": row_id,
                "key": key,
                "kind": "steam" if steam_icon else "legacy",
                "title": title,
                "label": friendly_marker_label(key, title=title),
                "marker_id": marker_id,
                "time_ms": time_ms,
                "raw_time_ms": m.get("raw_time_ms"),
                "icon": steam_icon,
                "icon_key": icon_key,
                "shared_type": True,
                "type_count": 1,  # filled below
            }
        )

    for row in game_rows:
        row["type_count"] = type_counts.get(row["key"], 1)

    # Chronological within each kind block (users → screenshots → game events).
    return user_rows + shot_rows + game_rows


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
    """Class color for tinting white glyphs; None = leave as-is.

    Rules:
    - Marker ``no_tint`` → never tint (in class for grouping only).
    - Marker custom icon → never tint (full-color art stays as-is).
    - Class custom icon → class supplies the picture instead of a tint.
    - Class with empty color → group-only class.
    """
    ov = marker_override(marker_key, prefs)
    if ov.get("no_tint"):
        return None
    custom = ov.get("custom_icon") or ""
    if custom and os.path.isfile(custom):
        return None
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


def resolve_custom_icon_path_for_marker(
    marker: dict,
    *,
    prefs: dict | None = None,
) -> str | None:
    for key in marker_resolve_keys(marker):
        path = resolve_custom_icon_path(key, prefs=prefs)
        if path:
            return path
    return None


def resolve_tint_color_for_marker(
    marker: dict,
    *,
    prefs: dict | None = None,
) -> str | None:
    for key in marker_resolve_keys(marker):
        tint = resolve_tint_color(key, prefs=prefs)
        if tint:
            return tint
    return None
