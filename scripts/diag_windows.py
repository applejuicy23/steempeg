#!/usr/bin/env python3
"""Open every Steempeg window with sample content filled in.

Empty dialogs hide the rows that only appear once a clip, export, or release
is known. This gallery builds those objects and shows the windows together.
Nothing here writes settings, installs an update, or touches the real library.

Usage (from the repo)::

    python scripts/diag_windows.py
    python scripts/diag_windows.py --check

Close the "Steempeg windows" list to close the rest. Click a name to bring
that window forward. The main shell, Portable sheets, and the Render Settings
window that borrows the live export panel are the running app, not this list.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import traceback
from contextlib import contextmanager
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.paths import get_resource_path
from steempeg.render.queue import JobStatus, RenderJob, RenderJobSettings, job_to_dict
from steempeg.render.queue_history import RenderBatchRecord
from steempeg.services.new_clip_watcher import NewClipInfo
from steempeg.services.release_catalog import (
    InstallTier,
    LocalBackup,
    ReleaseEntry,
    VersionEra,
    VersionMilestone,
)
from steempeg.ui.settings_prefs import KEY_STEEMPEG_PRO
from steempeg.version import APP_VERSION_FLOAT, APP_VERSION_STR


class _Samples:
    """Files and jobs the windows display. Kept out of the real library."""

    def __init__(self) -> None:
        self.folder = tempfile.mkdtemp(prefix="steempeg-window-gallery-")
        self.clip_dir = os.path.join(self.folder, "clip_3513350_20261028_184554")
        os.makedirs(self.clip_dir, exist_ok=True)
        self.thumb = os.path.join(self.folder, "thumbnail.jpg")
        self.output = os.path.join(
            self.folder, "Wuthering Waves_2026-10-31_21-10-00.mp4"
        )
        self.icon = get_resource_path("logo.png")
        if not os.path.isfile(self.icon):
            self.icon = get_resource_path("unknown_icon.png")
        self._paint_thumb()
        with open(self.output, "wb") as handle:
            handle.write(b"")

    def _paint_thumb(self) -> None:
        """A still the New clip card can show instead of an empty plate."""
        image = QImage(640, 360, QImage.Format.Format_RGB32)
        image.fill(QColor("#241c33"))
        painter = QPainter(image)
        painter.setPen(QColor("#f0ecff"))
        painter.drawText(
            image.rect(),
            int(Qt.AlignmentFlag.AlignCenter),
            "Wuthering Waves\nHazard Tower — Floor 3",
        )
        painter.end()
        image.save(self.thumb, "JPEG")

    def settings(self, *, trim: bool) -> RenderJobSettings:
        """Export line the complete / history cards print under the game name."""
        return RenderJobSettings(
            quality_text="1080p",
            fps_text="60 FPS",
            bitrate_text="8 Mbps",
            codec_text="H.265",
            encoder_display="NVENC (NVIDIA GPU)",
            output_basename="Wuthering Waves_2026-10-31_21-10-00",
            save_dir=self.folder,
            trim_start_ms=12_000 if trim else 0,
            trim_end_ms=(7 * 60 + 48) * 1000 if trim else 0,
            is_trim_mode=trim,
            orig_fps=60,
            orig_video_mbps=22.0,
            output_preset="YouTube",
            container_format="MP4",
        )

    def job(
        self,
        *,
        name: str,
        status: JobStatus,
        output: str,
        error: str = "",
        trim: bool = True,
    ) -> RenderJob:
        """One export card: icon, title, preset, trim, and a path."""
        return RenderJob(
            clip_path=self.clip_dir,
            game_name=name,
            clip_date="31 October 2026",
            clip_time="9:10 PM",
            game_icon_path=self.icon,
            settings=self.settings(trim=trim),
            status=status,
            output_file=output,
            error_message=error,
            duration_label="8m 2s",
        )


class _Host:
    """Stand-in for the app object dialogs read while they are built.

    Saves are dropped on the floor so a click in Settings cannot rewrite
    settings.json.
    """

    def __init__(self, samples: _Samples) -> None:
        self.ui = None
        self._portable_shell = False
        self._about_is_open = False
        self._report_dialog_open = False
        self._preview_clip_path = samples.clip_dir
        self.cache_dir = samples.folder
        self.logs_dir = samples.folder
        self.clips_folders = [samples.folder]

    def load_user_settings(self) -> dict:
        """PRO on, so About and Settings show that badge and page."""
        return {KEY_STEEMPEG_PRO: True}

    def save_user_settings(self, key, value=None) -> bool:
        """Ignore writes from a gallery click."""
        return True

    def save_user_settings_batch(self, updates: dict) -> bool:
        """Ignore writes from a gallery click."""
        return True

    def start_express_render(self, *args, **kwargs):
        """The Express window stays a picture. No export starts."""
        return None


_SAMPLES: _Samples | None = None
_HOST: _Host | None = None


def _samples() -> _Samples:
    """The shared stub set. Created once Qt can paint the thumbnail."""
    global _SAMPLES, _HOST
    if _SAMPLES is None:
        _SAMPLES = _Samples()
        _HOST = _Host(_SAMPLES)
    return _SAMPLES


def _host() -> _Host:
    """The shared app stand-in."""
    _samples()
    assert _HOST is not None
    return _HOST


@contextmanager
def _modeless_exec():
    """Turn dialog.exec() into show() for the builders that only know exec.

    The real method is put back before the gallery's event loop starts, so a
    later Yes/No inside a window is still modal.
    """
    original = QDialog.exec
    shown: list[QDialog] = []

    def _show(dialog, *args, **kwargs):
        dialog.setModal(False)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.show()
        dialog.raise_()
        shown.append(dialog)
        return QDialog.DialogCode.Rejected

    QDialog.exec = _show  # type: ignore[method-assign]
    try:
        yield shown
    finally:
        QDialog.exec = original  # type: ignore[method-assign]


def _release(version: str, *, newer: bool) -> ReleaseEntry:
    """One Update Center row with notes, so the right pane is not blank."""
    number = float(version)
    parts = tuple(int(piece) for piece in version.split("."))
    milestone = (
        VersionMilestone(
            number,
            "🔧",
            "Repair",
            "Sample notes for the window gallery. This is not a real release.",
        ),
    )
    body = (
        "## Installer Repair\n\n"
        "- Repair removes program files and puts this setup back.\n"
        "- cache, logs, rendered videos, and screenshots stay.\n\n"
        "## Player\n\n"
        "Clips Manager keeps the share from Settings after the window grows.\n"
    )
    return ReleaseEntry(
        tag_name=f"v{version}",
        name=f"Steempeg {version}",
        version=parts,
        version_str=version,
        version_float=number,
        html_url=f"https://github.com/applejuicy23/steempeg/releases/tag/v{version}",
        body=body if newer else "You are on this build. Notes below are a sample.",
        zip_url=f"https://example.invalid/Steempeg_v{version}_setup.exe",
        zip_name=f"Steempeg_v{version}_setup.exe",
        era=VersionEra.RELIABLE,
        install_tier=InstallTier.STABLE,
        installable=True,
        milestones=milestone if newer else (),
        block_reason=None,
        published_at="2026-10-31T18:00:00Z",
        zip_size=48_000_000,
        available_platforms=frozenset({"windows"}),
    )


def _clip_info() -> NewClipInfo:
    """The New clip card and the Express window share this clip."""
    samples = _samples()
    return NewClipInfo(
        path=samples.clip_dir,
        app_id="3513350",
        game_name="Wuthering Waves",
        icon_path=samples.icon,
        thumbnail_path=samples.thumb,
        duration_sec=8 * 60 + 2,
    )


def _success_job() -> RenderJob:
    """Finished export whose file is on disk, so the action buttons appear."""
    samples = _samples()
    return samples.job(
        name="Wuthering Waves",
        status=JobStatus.COMPLETED,
        output=samples.output,
        trim=True,
    )


def _failed_job() -> RenderJob:
    """Failed export so the batch card shows the error line."""
    samples = _samples()
    missing = os.path.join(samples.folder, "missing_export.mp4")
    return samples.job(
        name="Counter-Strike 2",
        status=JobStatus.ERROR,
        output=missing,
        error="No space left on device",
        trim=False,
    )


def _detach(dialog: QDialog) -> QDialog:
    """Show with show(), not exec(), and keep the window independent."""
    dialog.setModal(False)
    dialog.setWindowModality(Qt.WindowModality.NonModal)
    return dialog


_SAMPLE_TIP = "Sample window. This gallery does not install, open a browser, or save."


def _park_button(button: QPushButton) -> None:
    """Leave the button visible and stop the real action."""
    try:
        button.clicked.disconnect()
    except (TypeError, RuntimeError):
        pass
    button.clicked.connect(lambda: None)
    if not button.toolTip():
        button.setToolTip(_SAMPLE_TIP)


def _park_named(widget: QWidget, *needles: str) -> None:
    """Park buttons whose label contains one of the needles."""
    folded = tuple(needle.casefold() for needle in needles)
    for button in widget.findChildren(QPushButton):
        if any(needle in button.text().casefold() for needle in folded):
            _park_button(button)


def _as_top_window(window: QWidget) -> None:
    """A dialog parented to a hidden stand-in would stay off screen."""
    if isinstance(window, QDialog) and window.parentWidget() is not None:
        window.setParent(None)
        window.setWindowFlag(Qt.WindowType.Window, True)
        window.setModal(False)
        window.setWindowModality(Qt.WindowModality.NonModal)


def _freeze_side_effects() -> None:
    """A click must not rewrite settings, marker prefs, or the chosen shell."""
    import steempeg.services.marker_prefs as marker_prefs
    import steempeg.ui.shell_chooser as shell_chooser

    def _drop_marker_save(data: dict) -> None:
        """Marker edits in the gallery stay on screen only."""
        return None

    def _drop_shell_save(*args, **kwargs) -> bool:
        """Desktop / Portable in the gallery does not become the next launch."""
        return True

    marker_prefs.save_marker_prefs = _drop_marker_save
    shell_chooser.save_ui_shell = _drop_shell_save
    shell_chooser.save_ask_ui_shell = _drop_shell_save


def _widget_blob(window: QWidget) -> str:
    """Visible strings, so a check can tell a stub actually landed."""
    parts: list[str] = []
    for child in (window, *window.findChildren(QWidget)):
        for method in ("text", "toPlainText"):
            reader = getattr(child, method, None)
            if not callable(reader):
                continue
            try:
                value = reader()
            except Exception:
                continue
            if isinstance(value, str) and value:
                parts.append(value)
    return "\n".join(parts)


def build_render_complete() -> QDialog:
    """Render complete with the game row, preset, trim, and path filled in."""
    from steempeg.ui.render_complete_dialog import RenderCompleteDialog

    return _detach(
        RenderCompleteDialog(
            _success_job(),
            _samples().output,
            show_clear_queue=True,
            always_clear_queue=True,
        )
    )


def build_batch_complete() -> QDialog:
    """Batch summary: one exported clip with buttons, one failed clip."""
    from steempeg.ui.batch_complete_dialog import BatchCompleteDialog

    return _detach(BatchCompleteDialog([_success_job(), _failed_job()]))


def build_render_history() -> QDialog:
    """History list with a finished batch and a cancelled one."""
    from steempeg.ui.render_queue_history import RenderQueueHistoryDialog

    done = job_to_dict(_success_job())
    failed = job_to_dict(_failed_job())
    skipped = job_to_dict(_success_job())
    skipped["status"] = "cancelled"
    batches = [
        RenderBatchRecord(
            id="gallery-done",
            started_at="2026-10-31T18:02:00+00:00",
            finished_at="2026-10-31T18:14:00+00:00",
            cancelled=False,
            jobs=[done, failed],
        ),
        RenderBatchRecord(
            id="gallery-cancelled",
            started_at="2026-10-30T12:00:00+00:00",
            finished_at="2026-10-30T12:04:00+00:00",
            cancelled=True,
            jobs=[skipped],
        ),
    ]
    return _detach(RenderQueueHistoryDialog(batches))


def build_render_details() -> QDialog:
    """One history job opened, with preset, trim, and both paths."""
    from steempeg.ui.render_history_detail_dialog import RenderHistoryDetailDialog

    return _detach(RenderHistoryDetailDialog(job_to_dict(_success_job())))


def build_render_failed() -> QDialog:
    """The Chupi error card with a sample FFmpeg log in the box."""
    from steempeg.render.ffmpeg_error_hints import next_simulate_sample
    from steempeg.ui.render_controller import RenderMixin

    _index, _kind, sample = next_simulate_sample(0)
    host = _host()
    with _modeless_exec() as shown:
        RenderMixin._show_steempeg_render_error_dialog(host, sample)
    if not shown:
        raise RuntimeError("Render Failed did not open")
    return shown[-1]


def build_update_center() -> QDialog:
    """Update Center with sample releases. Install cannot start a download."""
    from steempeg.ui.update_center import UpdateCenterDialog

    original = UpdateCenterDialog._start_fetch

    def _sample_fetch(self) -> None:
        """Fill the list from the gallery instead of calling GitHub."""
        self._hold_hidden_until_catalog = False
        current = str(APP_VERSION_STR).split("-", 1)[0]
        newer = str(int(APP_VERSION_FLOAT) + 1)
        self._on_releases_loaded(
            [_release(newer, newer=True), _release(current, newer=False)],
            from_cache=False,
        )
        try:
            self._btn_install.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self._btn_install.clicked.connect(lambda: None)
        self._btn_install.setToolTip("Sample catalog. This gallery does not install.")
        for button in (self._btn_github, getattr(self, "_btn_restore", None)):
            if button is None:
                continue
            try:
                button.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            button.clicked.connect(lambda: None)
            button.setToolTip("Sample catalog. This gallery does not install or open GitHub.")

    UpdateCenterDialog._start_fetch = _sample_fetch  # type: ignore[method-assign]
    try:
        backup = LocalBackup(
            folder_name="backup-v55",
            path=_samples().folder,
            version_str="55",
            version_float=55.0,
        )
        dialog = UpdateCenterDialog(local_backups=[backup])
    finally:
        UpdateCenterDialog._start_fetch = original  # type: ignore[method-assign]
    return _detach(dialog)


def build_update_confirm() -> QDialog:
    """The question shown before an install starts."""
    from steempeg.ui.update_confirm_dialog import UpdateConfirmDialog

    newer = str(int(APP_VERSION_FLOAT) + 1)
    return _detach(UpdateConfirmDialog(newer))


def build_update_progress() -> QDialog:
    """Updater window paused mid-download."""
    from steempeg.ui.update_progress_dialog import UpdateProgressDialog

    newer = str(int(APP_VERSION_FLOAT) + 1)
    dialog = UpdateProgressDialog(f"v{newer}")
    dialog.set_download_progress(42, "Steempeg_v%s_setup.exe  ·  18 MB / 46 MB" % newer)
    return _detach(dialog)


def build_rate_limit() -> QDialog:
    """GitHub limit card with a long wait so it does not close itself."""
    import time

    from steempeg.services.release_catalog import RateLimitInfo
    from steempeg.ui.github_rate_limit_dialog import GitHubRateLimitDialog

    info = RateLimitInfo(reset_at=int(time.time()) + 3600, limit=60, remaining=0)
    return _detach(GitHubRateLimitDialog(info, has_cached_releases=True))


def build_already_running() -> QDialog:
    """The dialog a second launch shows."""
    from steempeg.ui.already_running_dialog import AlreadyRunningDialog

    return _detach(AlreadyRunningDialog())


def build_shell_chooser() -> QDialog:
    """Desktop or Portable, the first-launch choice."""
    from steempeg.ui.shell_chooser import ShellChooserDialog

    return _detach(ShellChooserDialog())


def build_dead_offer() -> QDialog:
    """Dead clip offer with the issue lines filled in."""
    from steempeg.ui.dead_clip_dialogs import DeadClipOfferDialog

    return _detach(
        DeadClipOfferDialog(
            [
                "Manifest does not open",
                "Init segment is missing",
            ]
        )
    )


def build_dead_salvage() -> QDialog:
    """Force-play confirmation."""
    from steempeg.ui.dead_clip_dialogs import DeadClipSalvageDialog

    return _detach(DeadClipSalvageDialog())


def build_dead_failed() -> QDialog:
    """Salvage could not build a manifest."""
    from steempeg.ui.dead_clip_dialogs import DeadClipSalvageFailedDialog

    return _detach(DeadClipSalvageFailedDialog())


def build_dead_verify() -> QDialog:
    """Playback started — keep the salvage, and the auto-play checkbox."""
    from steempeg.ui.dead_clip_dialogs import DeadClipSalvageVerifyDialog

    return _detach(DeadClipSalvageVerifyDialog())


def build_clip_cured() -> QDialog:
    """Cured acknowledgement with the health icon lead line."""
    from steempeg.ui.dead_clip_dialogs import show_clip_cured_dialog

    with _modeless_exec() as shown:
        show_clip_cured_dialog(None)
    if not shown:
        raise RuntimeError("Clip Cured did not open")
    return shown[-1]


def build_message_info() -> QDialog:
    """Plain notice with a detail line under the message."""
    from steempeg.ui.message_dialog import DialogButton, SteempegMessageDialog

    return _detach(
        SteempegMessageDialog(
            "Export folder",
            "Finished videos go to the rendered_videos folder.",
            detail=_samples().folder,
            buttons=(DialogButton("OK", "primary", accept=True),),
        )
    )


def build_message_question() -> QDialog:
    """Yes / No."""
    from steempeg.ui.message_dialog import DialogButton, SteempegMessageDialog

    return _detach(
        SteempegMessageDialog(
            "Remove from library",
            "Take Wuthering Waves out of this list? The files stay on disk.",
            buttons=(
                DialogButton("No", "secondary"),
                DialogButton("Yes", "primary", accept=True),
            ),
        )
    )


def build_message_delete() -> QDialog:
    """Delete confirmation."""
    from steempeg.ui.message_dialog import DialogButton, SteempegMessageDialog

    return _detach(
        SteempegMessageDialog(
            "Delete clip",
            "Move this clip to the recycle bin?",
            detail=_samples().clip_dir,
            buttons=(
                DialogButton("Cancel", "secondary"),
                DialogButton("Delete", "danger", accept=True),
            ),
        )
    )


def build_dont_ask() -> QDialog:
    """Notice with the Don't ask again checkbox."""
    from steempeg.ui.message_dialog import steempeg_information_dont_ask

    with _modeless_exec() as shown:
        steempeg_information_dont_ask(
            None,
            "Clear cache",
            "This removes thumbnails and the game-name cache. Clips stay on disk.",
            checkbox_label="Don't ask again",
        )
    if not shown:
        raise RuntimeError("Don't ask again did not open")
    return shown[-1]


def build_new_clip() -> QWidget:
    """Corner card with a thumbnail, duration, game, and Open / Express."""
    from steempeg.ui.new_clip_popup import NewClipPopupStack

    stack = NewClipPopupStack(lambda _path: None, lambda _path: None)
    stack.show_clip(_clip_info())
    popup = stack._popups[0]
    popup._dismiss_timer.stop()
    # The stack is the only owner of the slot list. Keep it on the card.
    popup._gallery_stack = stack  # type: ignore[attr-defined]
    return popup


def build_edit_marker() -> QDialog:
    """Marker editor with a title and description already typed."""
    from steempeg.ui.edit_marker_dialog import EditSteamMarkerDialog

    return _detach(
        EditSteamMarkerDialog(
            "Boss phase",
            "Hazard Tower — shield break at 0:12.",
            marker_key="gallery-sample-pin",
        )
    )


def build_marker_settings() -> QDialog:
    """Marker settings with two rows on the open clip."""
    from steempeg.ui.marker_settings_dialog import MarkerSettingsDialog

    markers = [
        {
            "id": "pin-1",
            "time_ms": 12_500,
            "title": "Boss phase",
            "description": "Shield break",
            "icon_key": "usermarker",
        },
        {
            "id": "shot-1",
            "time_ms": 84_000,
            "title": "Hazard Tower",
            "icon_key": "screenshot",
        },
    ]
    return _detach(
        MarkerSettingsDialog(
            _host(),
            app_id="3513350",
            clip_markers=markers,
        )
    )


def build_preset_editor() -> QDialog:
    """Create-preset form filled as a 1080p export."""
    from steempeg.ui.preset_mini_editor import PresetMiniEditor

    return _detach(
        PresetMiniEditor(
            _host(),
            edit_name="YouTube 1080p",
            seed=_samples().settings(trim=False),
        )
    )


def build_settings() -> QDialog:
    """Settings. Save does not write the real settings file."""
    from steempeg.ui.settings_dialog import SettingsDialog

    return _detach(SettingsDialog(_host()))


def build_about() -> QDialog:
    """About, including the PRO chip."""
    from steempeg.ui.lifecycle import LifecycleMixin

    host = LifecycleMixin()
    host.ui = QWidget()
    host.ui.hide()
    host._portable_shell = False
    host._about_is_open = False
    host.load_user_settings = _host().load_user_settings
    with _modeless_exec() as shown:
        host.show_about_dialog()
    if not shown:
        raise RuntimeError("About did not open")
    dialog = shown[-1]
    # The dialog is parented to host.ui. Dropping host would delete it.
    dialog._gallery_owner = host  # type: ignore[attr-defined]
    return dialog


def build_report() -> QDialog:
    """Bug report with a description already in the box."""
    from steempeg.ui.report_dialog import show_report_dialog

    host = _host()
    host.ui = QWidget()
    host.ui.hide()
    host._report_dialog_open = False
    with _modeless_exec() as shown:
        show_report_dialog(host)
    if not shown:
        raise RuntimeError("Report did not open")
    dialog = shown[-1]
    editor = dialog.findChild(QTextEdit)
    if editor is not None:
        editor.setPlainText(
            "Render complete showed Chupi and the buttons only. "
            "The game icon, the game name, and the preset line were missing."
        )
    _park_named(dialog, "github", "save bundle")
    return dialog


def build_kofi() -> QDialog:
    """Donate card."""
    from steempeg.ui.kofi_dialog import show_kofi_dialog

    with _modeless_exec() as shown:
        show_kofi_dialog(None)
    if not shown:
        raise RuntimeError("Ko-fi did not open")
    dialog = shown[-1]
    _park_named(dialog, "ko-fi")
    return dialog


def build_pro_unlock() -> QDialog:
    """PRO unlock card."""
    from steempeg.ui.pro_unlock_dialog import ask_steempeg_pro_unlock

    with _modeless_exec() as shown:
        ask_steempeg_pro_unlock(None)
    if not shown:
        raise RuntimeError("PRO unlock did not open")
    dialog = shown[-1]
    _park_named(dialog, "ko-fi")
    return dialog


def build_dev_tools() -> QDialog:
    """Developer tools. The tabs are the window; the workers stay idle."""
    from steempeg.ui.dev_mode_dialog import DevModeDialog

    return _detach(DevModeDialog(_samples().folder))


def build_splash() -> QWidget:
    """Launch splash part-way through, with the PRO mark."""
    from steempeg.ui.launch_splash import show_launch_splash

    splash = show_launch_splash(force=True, pro=True)
    if splash is None:
        raise RuntimeError("Launch splash is disabled")
    splash.set_progress(64, "Indexing clips…")
    return splash


def build_express() -> QWidget:
    """Express player chrome with the game title. Playback is not started."""
    from steempeg.ui.express_player import ExpressPlayerWindow

    return ExpressPlayerWindow(_host(), _clip_info())


# Order is the list order. place=False keeps a window where it put itself
# (the corner card, the centered splash).
_WINDOWS: tuple[tuple[str, object, bool], ...] = (
    ("Render complete", build_render_complete, True),
    ("Batch render complete", build_batch_complete, True),
    ("Render History", build_render_history, True),
    ("Render details", build_render_details, True),
    ("Render Failed", build_render_failed, True),
    ("Update Center", build_update_center, True),
    ("Before updating", build_update_confirm, True),
    ("Updater", build_update_progress, True),
    ("GitHub API limit", build_rate_limit, True),
    ("Already running", build_already_running, True),
    ("Choose your Steempeg", build_shell_chooser, True),
    ("Dead clip", build_dead_offer, True),
    ("Force play", build_dead_salvage, True),
    ("Nothing to salvage", build_dead_failed, True),
    ("Salvage verified", build_dead_verify, True),
    ("Clip Cured", build_clip_cured, True),
    ("Notice", build_message_info, True),
    ("Question", build_message_question, True),
    ("Delete confirm", build_message_delete, True),
    ("Don't ask again", build_dont_ask, True),
    ("New clip", build_new_clip, False),
    ("Edit marker", build_edit_marker, True),
    ("Marker settings", build_marker_settings, True),
    ("Preset editor", build_preset_editor, True),
    ("Settings", build_settings, True),
    ("About", build_about, True),
    ("Report a bug", build_report, True),
    ("Ko-fi", build_kofi, True),
    ("PRO unlock", build_pro_unlock, True),
    ("Developer tools", build_dev_tools, True),
    ("Launch splash", build_splash, False),
    ("Express player", build_express, True),
)


class Gallery(QWidget):
    """The list that opens the windows and brings one back to the front."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Steempeg windows")
        self.setMinimumSize(280, 520)
        self.resize(320, 720)
        self._open: dict[str, QWidget] = {}
        self._errors: list[tuple[str, str]] = []
        self._names = [name for name, _build, _place in _WINDOWS]

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        title = QLabel("Steempeg windows")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        root.addWidget(title)
        hint = QLabel(
            "Sample clips and releases, not your library. "
            "The main window, Portable sheets, and docked Render Settings "
            "stay in the running app. "
            "Buttons that would install, open a browser, or save do nothing here. "
            "Click a name to bring that window forward. "
            "Close this list to close the rest."
        )
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        root.addWidget(hint)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._raise_row)
        root.addWidget(self._list, 1)
        self.setStyleSheet(
            "QWidget { background: #1a1a1a; color: #f0f0f0; }"
            "QListWidget { background: #242424; border: 1px solid #333; }"
            "QListWidget::item { padding: 4px 6px; }"
            "QListWidget::item:selected { background: #4a3d66; }"
            "QLabel#hint { color: #999999; }"
        )

    def open_all(self) -> list[tuple[str, str]]:
        """Build and show every window. Returns (name, error) for the failures."""
        self._errors.clear()
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else None
        origin_x = 340
        origin_y = 24
        if avail is not None:
            self.move(avail.x() + 12, avail.y() + 24)
            origin_x = avail.x() + 348
            origin_y = avail.y() + 16
        placed = 0
        self._list.blockSignals(True)
        try:
            for name, build, place in _WINDOWS:
                item = QListWidgetItem(name)
                try:
                    window = build()
                except Exception:
                    detail = traceback.format_exc().strip().splitlines()[-1]
                    self._errors.append((name, traceback.format_exc()))
                    item.setText(f"{name}  —  failed")
                    item.setToolTip(detail)
                    self._list.addItem(item)
                    print(f"FAIL  {name}: {detail}", flush=True)
                    continue
                self._open[name] = window
                _as_top_window(window)
                if place:
                    column = placed % 3
                    row = placed // 3
                    window.move(origin_x + column * 36, origin_y + row * 32)
                    placed += 1
                if isinstance(window, QDialog):
                    window.setModal(False)
                window.show()
                window.raise_()
                self._list.addItem(item)
                print(f"OK    {name}", flush=True)
        finally:
            self._list.blockSignals(False)
        self._pump()
        self._check_samples()
        return list(self._errors)

    def _check_samples(self) -> None:
        """The rows that stay empty without a job must contain the sample."""
        expected = {
            "Render complete": ("Wuthering Waves", "1080p"),
            "Batch render complete": ("Wuthering Waves", "Counter-Strike 2"),
            "Render History": ("Wuthering Waves",),
            "Render details": ("Wuthering Waves", "1080p"),
            "New clip": ("Wuthering Waves",),
            "Express player": ("Wuthering Waves",),
            "Update Center": ("Repair",),
        }
        for name, needles in expected.items():
            window = self._open.get(name)
            if window is None:
                continue
            blob = _widget_blob(window)
            missing = [needle for needle in needles if needle not in blob]
            if not missing:
                continue
            detail = "missing " + ", ".join(missing)
            self._errors.append((name, detail))
            print(f"FAIL  {name}: {detail}", flush=True)

    def _pump(self) -> None:
        """Let one-shot timers fill lists that build after show."""
        app = QApplication.instance()
        if app is None:
            return
        for _ in range(12):
            app.processEvents()

    def _raise_row(self, row: int) -> None:
        """Bring the picked window forward, or rebuild it if it was closed."""
        if row < 0 or row >= len(self._names):
            return
        name = self._names[row]
        window = self._open.get(name)
        alive = False
        if window is not None:
            try:
                alive = True
                window.isVisible()
            except RuntimeError:
                alive = False
        if not alive:
            build = next(item[1] for item in _WINDOWS if item[0] == name)
            try:
                window = build()
            except Exception:
                print(f"FAIL  {name}", flush=True)
                return
            self._open[name] = window
            window.show()
        try:
            window.show()
            window.raise_()
            window.activateWindow()
        except RuntimeError:
            return

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt override
        """Close every gallery window with this list."""
        for window in list(self._open.values()):
            try:
                window.close()
            except RuntimeError:
                pass
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    """Open the gallery. ``--check`` builds every window and exits."""
    parser = argparse.ArgumentParser(description="Open Steempeg windows with sample content.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Build every window, print OK or FAIL, then exit.",
    )
    args = parser.parse_args(argv)

    app = QApplication(sys.argv)
    app.setApplicationName("Steempeg windows")
    _freeze_side_effects()
    _samples()
    gallery = Gallery()
    gallery.show()
    errors = gallery.open_all()
    gallery._pump()
    if args.check:
        gallery.close()
        return 1 if errors else 0
    print("Close the Steempeg windows list to quit.", flush=True)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
