"""Rendering controls and the export pipeline, mixed into the main application.

These methods drive the render tab: probing clip media, building quality and
bitrate options, validating custom input, running the export thread and reporting
results. They run on the application instance and reach its widgets and state
through self.
"""
from steempeg.core.dash import discovery, mpd, repair


class RenderMixin:
    def get_all_mpd_paths(self, clip_path):
        return discovery.find_mpd_paths(clip_path)

    def fix_steam_manifest(self, mpd_path):
        return repair.fix_steam_manifest(mpd_path)

    def recover_orphaned_clip(self, folder_path):
        return repair.recover_orphaned_clip(folder_path)

    def get_fps_from_mpd(self, mpd_path):
        return mpd.get_fps(mpd_path)

    def get_audio_bitrate_from_mpd(self, mpd_path):
        return mpd.get_audio_bitrate_kbps(mpd_path)