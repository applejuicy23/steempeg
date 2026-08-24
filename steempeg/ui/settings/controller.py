"""User-settings and JSON-cache access, mixed into the main application.

These small helpers read and write the on-disk JSON files that back the game-name
cache and the user's saved preferences. They run on the application instance and
reach its paths and in-memory caches through self.
"""
import json
import logging
import os

from steempeg.infra import cache

_log = logging.getLogger(__name__)


class SettingsMixin:
    def load_json_cache(self):
        return cache.read_json(self.json_cache_path)

    def save_json_cache(self):
        cache.write_json(self.json_cache_path, self.game_names_cache)

    def load_user_settings(self):
        memo = getattr(self, "_user_settings_memo", None)
        if isinstance(memo, dict):
            return memo
        path = os.path.join(self.cache_dir, "settings.json")
        loaded = cache.read_json(path)
        memo = loaded if isinstance(loaded, dict) else {}
        self._user_settings_memo = memo
        return memo

    def save_user_settings(self, key, value):
        """Merge one key into settings.json without clobbering on read failure."""
        path = os.path.join(self.cache_dir, "settings.json")
        settings: dict = {}
        memo = getattr(self, "_user_settings_memo", None)
        if isinstance(memo, dict):
            settings = memo
        elif os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
            except json.JSONDecodeError:
                _log.error(
                    "Refusing to save %r: settings.json is invalid JSON (%s)",
                    key,
                    path,
                )
                return
            except OSError as exc:
                _log.error(
                    "Refusing to save %r: could not read settings.json (%s): %s",
                    key,
                    path,
                    exc,
                )
                return
            if not isinstance(loaded, dict):
                _log.error(
                    "Refusing to save %r: settings.json root is not an object (%s)",
                    key,
                    path,
                )
                return
            settings = loaded
        settings[key] = value
        self._user_settings_memo = settings
        cache.write_json(path, settings)

    def save_user_settings_batch(self, updates: dict) -> None:
        """Merge many keys into settings.json with a single read/write."""
        if not updates:
            return
        path = os.path.join(self.cache_dir, "settings.json")
        settings: dict = {}
        memo = getattr(self, "_user_settings_memo", None)
        if isinstance(memo, dict):
            settings = memo
        elif os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
            except json.JSONDecodeError:
                _log.error(
                    "Refusing batch save: settings.json is invalid JSON (%s)",
                    path,
                )
                return
            except OSError as exc:
                _log.error(
                    "Refusing batch save: could not read settings.json (%s): %s",
                    path,
                    exc,
                )
                return
            if not isinstance(loaded, dict):
                _log.error(
                    "Refusing batch save: settings.json root is not an object (%s)",
                    path,
                )
                return
            settings = loaded
        settings.update(updates)
        self._user_settings_memo = settings
        cache.write_json(path, settings)

    def _layout_remember_enabled(self) -> bool:
        from steempeg.ui.layout_defaults import REMEMBER_LAYOUT_BETWEEN_SESSIONS
        return REMEMBER_LAYOUT_BETWEEN_SESSIONS

    # Always persist these even when REMEMBER_LAYOUT_BETWEEN_SESSIONS is False.
    # (Queue width/open + Desktop player↔settings vertical dock.)
    _ALWAYS_REMEMBER_LAYOUT_KEYS = frozenset(
        {"queue_panel_width", "queue_panel_open", "main_v_splitter_sizes"}
    )

    def get_layout_setting(self, key: str, default):
        # Queue / Desktop v-dock are always remembered — full layout recall stays
        # behind the REMEMBER_LAYOUT_BETWEEN_SESSIONS flag.
        if key in self._ALWAYS_REMEMBER_LAYOUT_KEYS or self._layout_remember_enabled():
            return self.load_user_settings().get(key, default)
        return default

    def save_layout_setting(self, key: str, value) -> None:
        if key in self._ALWAYS_REMEMBER_LAYOUT_KEYS or self._layout_remember_enabled():
            self.save_user_settings(key, value)