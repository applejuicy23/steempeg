"""Apply saved recipes safely when PRO encoding controls are unavailable."""
from __future__ import annotations

import logging
from dataclasses import fields, replace

from steempeg.render.queue import RenderJobSettings
from steempeg.render.pro_encoding import normalize_rate_control
from steempeg.ui.render_pro_controls import pro_enabled

KEY_SKIP_PRO_PRESET_WARNING = "skip_pro_preset_warning"
_DEFAULTS = RenderJobSettings()
_PRO_DEFAULTS = {f.name: getattr(_DEFAULTS, f.name)
                 for f in fields(RenderJobSettings) if f.name.startswith("pro_")}


def preset_uses_pro(settings: RenderJobSettings) -> bool:
    """Ignore a remembered CQ number while ordinary bitrate mode is selected."""
    quality = settings.quality_text or ""
    if settings.audio_only or ("Original" in quality and "Target File" not in quality):
        return False
    return bool(normalize_rate_control(settings.pro_rate_control) == "quality" or settings.pro_two_pass
                or settings.pro_ten_bit or settings.pro_preset or settings.pro_tune
                or settings.pro_keyint_sec > 0)


def preset_settings_for_plan(app, settings: RenderJobSettings, name: str) -> RenderJobSettings:
    """Warn once if requested, then use a copy with ordinary encoding defaults.

    Never rewrite the saved preset: enabling PRO later restores its full recipe.
    """
    if pro_enabled(app):
        return settings
    if preset_uses_pro(settings):
        from steempeg.ui.message_dialog import steempeg_information_dont_ask

        prefs = app.load_user_settings() or {}
        if not prefs.get(KEY_SKIP_PRO_PRESET_WARNING, False):
            skip = steempeg_information_dont_ask(
                getattr(app, "ui", None), "PRO preset",
                f'Preset “{name}” includes PRO encoding settings, but PRO is turned off.\n\n'
                "The preset will use standard encoding settings. Its PRO options "
                "will not be applied. Your saved preset will stay unchanged.",
            )
            if skip:
                try:
                    app.save_user_settings(KEY_SKIP_PRO_PRESET_WARNING, True)
                except Exception:
                    logging.exception("Could not save the PRO preset warning preference")
    return replace(settings, **_PRO_DEFAULTS)
