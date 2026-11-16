#!/usr/bin/env python3
r"""Focused fork of diag_windows for the v59 render-dialog redesign.

Run from the repository root in the VS Code terminal:
    .\.venv\Scripts\python.exe .\scripts\diag_render_windows.py

Four dialog families, five windows (single and batch completion are separate).
Uses the real application builders with temporary sample files. No render,
deletion of library files, preference write, or external file opening occurs.
Restart the command after editing application code to see the latest design.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QPushButton

import diag_windows as gallery
from steempeg.ui import design_tokens as tok, ui_theme as ut


def _captured(build):
    """Run an existing modal app entry point without blocking this gallery."""
    with gallery._modeless_exec() as shown:
        build()
    if len(shown) != 1:
        raise RuntimeError(f"Expected one render dialog, got {len(shown)}")
    return gallery._detach(shown[0])


def build_duplicate():
    from steempeg.ui.render_controller import RenderMixin

    return _captured(lambda: RenderMixin._maybe_notify_queue_duplicate(
        gallery._host(), [gallery._samples().clip_dir],
    ))


def build_cancelled():
    from steempeg.ui.render_controller import RenderMixin

    host = gallery._host()
    host.update_playback_badge = lambda: None
    return _captured(lambda: RenderMixin._show_canceled_information(
        host, "Cancelled", "Render was cancelled.",
    ))


def build_delete():
    from steempeg.ui.library.rendered_library import RenderedLibraryMixin

    samples = gallery._samples()
    paths = []
    for i in range(1, 5):
        path = Path(samples.folder) / f"Wuthering_Waves_rendered_{i}.mp4"
        path.touch(exist_ok=True)
        paths.append(str(path))
    host = gallery._host()
    host._rendered_delete_confirm_copy = lambda selected: RenderedLibraryMixin._rendered_delete_confirm_copy(host, selected)
    dialog = _captured(lambda: RenderedLibraryMixin.delete_rendered_files(host, paths))
    # The intercepted exec returns Rejected: no delete handler continues later
    # when someone presses the confirmation button in this standalone window.
    if not all(Path(path).is_file() for path in paths):
        raise RuntimeError("Sample delete confirmation unexpectedly removed a file")
    return dialog


def _safe_completion(builder):
    import shutil

    samples = gallery._samples()
    shutil.copyfile(samples.thumb, Path(samples.clip_dir) / "thumbnail.jpg")
    window = builder()
    gallery._park_named(window, "open folder", "open file", "play video",
                        "rendered videos", "details", "source clip", "open render history")
    return window


def build_single_result():
    from steempeg.ui.render_complete_dialog import RenderCompleteDialog

    return _safe_completion(lambda: RenderCompleteDialog(
        gallery._success_job(), gallery._samples().output, elapsed_seconds=84.6,
    ))


def build_batch_result():
    from steempeg.ui.batch_complete_dialog import BatchCompleteDialog

    return _safe_completion(lambda: BatchCompleteDialog(
        [gallery._success_job(), gallery._failed_job()], elapsed_seconds=193.2,
    ))


_WINDOWS = [
    ("Duplicate in Render Queue", build_duplicate, True),
    ("Render cancelled", build_cancelled, True),
    ("Delete rendered files", build_delete, True),
    ("Render complete", build_single_result, True),
    ("Batch render complete", build_batch_result, True),
]


class RenderGallery(gallery.Gallery):
    def __init__(self, theme):
        super().__init__()
        self.setWindowTitle("Steempeg render windows")
        self.resize(340, 570)
        layout = self.layout()
        labels = self.findChildren(QLabel, options=Qt.FindChildOption.FindDirectChildrenOnly)
        if labels:
            labels[0].setText("Render dialog redesign · v59")
        for label in labels:
            if label.objectName() == "hint":
                label.setText(
                    "Four dialog families, five real application windows. "
                    "Temporary samples; actions do not render, delete your files or save settings. "
                    "Choose a window below to bring it forward. Close this list to quit. "
                    "Restart this command after changing the code."
                )
        self.theme = QComboBox(self)
        for key, name in ((ut.UI_THEME_DEFAULT, "Default"),
                          (ut.UI_THEME_TRUE_DARK, "TrueDark"),
                          (ut.UI_THEME_TRUE_DARK_OLED, "TrueDark OLED")):
            self.theme.addItem(name, key)
        self.theme.setCurrentIndex(self.theme.findData(theme))
        layout.insertWidget(2, self.theme)
        self.theme.currentIndexChanged.connect(self._theme_changed)
        reopen = QPushButton("Reopen all windows", self)
        reopen.clicked.connect(self.reopen)
        layout.addWidget(reopen)

    def _theme_changed(self):
        ut.apply_palette(str(self.theme.currentData()))
        tok.apply_app_tooltip_style()
        self.reopen()

    def reopen(self):
        for window in list(self._open.values()):
            window.close()
            window.deleteLater()
        self._open.clear()
        self._list.clear()
        return self.open_all()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--theme", choices=ut.UI_THEMES, default=ut.UI_THEME_TRUE_DARK)
    parser.add_argument("--check", action="store_true", help="Build and validate the five windows, then exit")
    args = parser.parse_args(argv)
    app = QApplication([sys.argv[0]])
    app.setApplicationName("Steempeg render windows")
    ut.apply_palette(args.theme)
    tok.apply_app_tooltip_style()
    gallery._freeze_side_effects()
    gallery._WINDOWS = _WINDOWS
    panel = RenderGallery(args.theme)
    panel.show()
    errors = panel.open_all()
    if args.check:
        panel.close()
        return int(bool(errors))
    print("Close the render windows list to quit. Restart the command after code changes.", flush=True)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
