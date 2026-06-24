"""User-settings and JSON-cache access, mixed into the main application.

These small helpers read and write the on-disk JSON files that back the game-name
cache and the user's saved preferences. They run on the application instance and
reach its paths and in-memory caches through self.
"""
import os

from steempeg.infra import cache


class SettingsMixin:
    def load_json_cache(self):
        return cache.read_json(self.json_cache_path)

    def save_json_cache(self):
        cache.write_json(self.json_cache_path, self.game_names_cache)

    def load_user_settings(self):
        return cache.read_json(os.path.join(self.cache_dir, "settings.json"))

    def save_user_settings(self, key, value):
        """ Saves a specific preference to the settings file permanently """
        path = os.path.join(self.cache_dir, "settings.json")
        settings = cache.read_json(path)
        settings[key] = value
        cache.write_json(path, settings)

    def _layout_remember_enabled(self) -> bool:
        from steempeg.ui.layout_defaults import REMEMBER_LAYOUT_BETWEEN_SESSIONS
        return REMEMBER_LAYOUT_BETWEEN_SESSIONS

    def get_layout_setting(self, key: str, default):
        if not self._layout_remember_enabled():
            return default
        return self.load_user_settings().get(key, default)

    def save_layout_setting(self, key: str, value) -> None:
        if self._layout_remember_enabled():
            self.save_user_settings(key, value)