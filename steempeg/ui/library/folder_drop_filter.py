"""Accept Explorer folder drops onto the Clips Manager grid/list."""
from __future__ import annotations

import os
from typing import Callable, Iterable, Optional, Sequence

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QAbstractItemView, QWidget


def local_folder_paths_from_mime(mime) -> list[str]:
    """Local directory paths from a drag mime payload (files ignored)."""
    if mime is None or not mime.hasUrls():
        return []
    out: list[str] = []
    seen: set[str] = set()
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = os.path.normpath(url.toLocalFile())
        if not path or path in seen:
            continue
        if not os.path.isdir(path):
            continue
        seen.add(path)
        out.append(path)
    return out


class LibraryFolderDropFilter(QObject):
    """Intercept external folder drops; QAbstractItemView NoDragDrop ignores them."""

    def __init__(
        self,
        on_folders: Callable[[Sequence[str]], None],
        highlight_widgets: Optional[Iterable[QWidget]] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._on_folders = on_folders
        self._highlight_widgets = [w for w in (highlight_widgets or ()) if w is not None]
        self._saved_styles: dict[int, str] = {}
        self._highlight_on = False

    def eventFilter(self, obj, event):  # noqa: N802 — Qt API
        et = event.type()
        if et == QEvent.Type.DragEnter and isinstance(event, QDragEnterEvent):
            if local_folder_paths_from_mime(event.mimeData()):
                event.acceptProposedAction()
                self._set_highlight(True)
                return True
            return False
        if et == QEvent.Type.DragMove and isinstance(event, QDragMoveEvent):
            if local_folder_paths_from_mime(event.mimeData()):
                event.acceptProposedAction()
                return True
            return False
        if et == QEvent.Type.DragLeave:
            self._set_highlight(False)
            return False
        if et == QEvent.Type.Drop and isinstance(event, QDropEvent):
            self._set_highlight(False)
            folders = local_folder_paths_from_mime(event.mimeData())
            if not folders:
                return False
            event.acceptProposedAction()
            self._on_folders(folders)
            return True
        return False

    def _set_highlight(self, on: bool) -> None:
        if on == self._highlight_on:
            return
        self._highlight_on = on
        for w in self._highlight_widgets:
            key = id(w)
            if on:
                if key not in self._saved_styles:
                    self._saved_styles[key] = w.styleSheet() or ""
                base = self._saved_styles[key]
                w.setStyleSheet(
                    base
                    + "\n/* folder-drop */\nborder: 2px dashed #9f8dba;\nborder-radius: 8px;"
                )
            else:
                if key in self._saved_styles:
                    w.setStyleSheet(self._saved_styles.pop(key))


def install_clips_folder_drop(
    *views: QWidget,
    on_folders: Callable[[Sequence[str]], None],
    highlight: Optional[QWidget] = None,
) -> LibraryFolderDropFilter:
    """Enable AcceptDrops on clips views and install the folder-drop filter."""
    targets: list[QWidget] = []
    for view in views:
        if view is None:
            continue
        view.setAcceptDrops(True)
        if isinstance(view, QAbstractItemView):
            # Keep items non-draggable; DropOnly still routes into the model —
            # we consume Drop in the filter instead.
            view.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
            vp = view.viewport()
            if vp is not None:
                vp.setAcceptDrops(True)
                targets.append(vp)
        targets.append(view)

    highlight_widgets = [highlight] if highlight is not None else []
    filt = LibraryFolderDropFilter(on_folders, highlight_widgets=highlight_widgets)
    for t in targets:
        t.installEventFilter(filt)
        # Keep filter alive for the view lifetime.
        t._library_folder_drop_filter = filt  # type: ignore[attr-defined]
    if highlight is not None and highlight not in targets:
        highlight._library_folder_drop_filter = filt  # type: ignore[attr-defined]
    return filt
