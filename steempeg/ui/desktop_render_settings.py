"""Desktop «Like a Portable» — floating Render Settings window (neo panel only)."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QSizePolicy

from steempeg.ui import design_tokens as tok
from steempeg.ui.message_dialog import dialog_theme
from steempeg.ui.portable.sheets import _borrow_widget, _return_widget
from steempeg.ui.widgets.dialog_chrome import SteempegDialog

_log = logging.getLogger(__name__)


class DesktopRenderSettingsDialog(SteempegDialog):
    """Non-modal window that borrows the docked neo export panel.

    Minimize / maximize in the title bar; closing (or toggling the dash button)
    returns neo to the main shell (hidden again while Like a Portable).
    """

    def __init__(self, app, parent=None):
        theme = dialog_theme(parent or getattr(app, "ui", None))
        super().__init__(
            "Render Settings",
            parent or getattr(app, "ui", None),
            show_minimize=True,
            show_maximize=True,
            content_margins=(12, 10, 12, 12),
            **theme,
        )
        self._app = app
        self._neo = getattr(app, "neo_wrapper", None)
        self._home = (None, None, -1, "orphan")
        self._returned = False

        # Register before borrow/sync — otherwise portable-like dock chrome parks
        # neo back into the garage and this window stays empty black.
        app._desktop_render_settings_dlg = self

        self.setMinimumSize(720, 480)
        self.resize(980, 640)
        # Modeless — user can keep Start / Pause / Cancel on the dash.
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)

        if self._neo is None:
            empty = QLabel("Render settings panel is not available.")
            empty.setStyleSheet(f"color: {tok.TEXT_MUTED};")
            self.content_layout.addWidget(empty, 1)
        else:
            # Undo dock collapse so neo can fill this window.
            self._neo.setMaximumHeight(16777215)
            self._neo.setMinimumHeight(0)
            self._home = _borrow_widget(self._neo)
            self._neo.show()
            self._neo.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            tabs = getattr(getattr(app, "ui", None), "settings_tabs", None)
            if tabs is not None:
                tabs.show()
                from steempeg.ui.settings_prefs import apply_default_render_tab

                apply_default_render_tab(app)
            for name in ("_neo_sidebar", "right_scroll"):
                w = getattr(app, name, None)
                if w is not None:
                    w.show()
            if hasattr(app, "fit_settings_tab_to_page"):
                QTimer.singleShot(0, app.fit_settings_tab_to_page)
            self.content_layout.addWidget(self._neo, 1)

        try:
            self._title_bar.close_requested.disconnect(self.reject)
        except (TypeError, RuntimeError):
            pass
        self._title_bar.close_requested.connect(self.close_and_return)

        if hasattr(app, "_sync_portable_like_dock_chrome"):
            try:
                app._sync_portable_like_dock_chrome()
            except Exception:
                pass

    def close_and_return(self) -> None:
        self._return_neo()
        self.hide()
        self.deleteLater()
        app = self._app
        if getattr(app, "_desktop_render_settings_dlg", None) is self:
            app._desktop_render_settings_dlg = None
        if hasattr(app, "_sync_dash_render_settings_button"):
            try:
                app._sync_dash_render_settings_button()
            except Exception:
                pass
        if hasattr(app, "_sync_portable_like_dock_chrome"):
            try:
                app._sync_portable_like_dock_chrome()
            except Exception:
                pass

    def _return_neo(self) -> None:
        if self._returned or self._neo is None:
            return
        self._returned = True
        parent, layout, index, kind = self._home
        # Prefer the chrome garage while Like a Portable — never leave a dock hole.
        # When switching to It's a Desktop, hand off to dock restore (not garage).
        app = self._app
        garage = getattr(app, "_neo_chrome_garage", None)
        try:
            portable_like = (
                hasattr(app, "_desktop_render_layout_is_portable_like")
                and app._desktop_render_layout_is_portable_like()
            )
            if portable_like and garage is not None:
                if self._neo.parentWidget() is not None:
                    prev = self._neo.parentWidget()
                    prev_lay = prev.layout() if prev is not None else None
                    if prev_lay is not None:
                        prev_lay.removeWidget(self._neo)
                garage.layout().addWidget(self._neo)
                self._neo.hide()
            elif (
                not portable_like
                and hasattr(app, "_restore_neo_to_dock_layout")
            ):
                # Detach from this dialog; dock chrome will place neo above dash.
                if self._neo.parentWidget() is not None:
                    prev = self._neo.parentWidget()
                    prev_lay = prev.layout() if prev is not None else None
                    if prev_lay is not None:
                        prev_lay.removeWidget(self._neo)
                self._neo.setParent(None)
            else:
                _return_widget(self._neo, parent, layout, index, kind, visible=True)
        except Exception:
            _log.exception("Failed returning neo_wrapper after Render Settings close")
        if hasattr(self._app, "fit_settings_tab_to_page"):
            try:
                self._app.fit_settings_tab_to_page()
            except Exception:
                pass

    def reject(self) -> None:
        self.close_and_return()

    def closeEvent(self, event) -> None:
        self._return_neo()
        app = self._app
        if getattr(app, "_desktop_render_settings_dlg", None) is self:
            app._desktop_render_settings_dlg = None
        super().closeEvent(event)
        if hasattr(app, "_sync_dash_render_settings_button"):
            try:
                app._sync_dash_render_settings_button()
            except Exception:
                pass
        if hasattr(app, "_sync_portable_like_dock_chrome"):
            try:
                app._sync_portable_like_dock_chrome()
            except Exception:
                pass


def toggle_desktop_render_settings(app) -> None:
    """Open / raise / lower the desktop Render Settings window."""
    if getattr(app, "_portable_shell", False):
        from steempeg.ui.portable.chrome import open_portable_render_settings

        open_portable_render_settings(app)
        return

    dlg = getattr(app, "_desktop_render_settings_dlg", None)
    try:
        if dlg is not None:
            dlg.objectName()
    except RuntimeError:
        dlg = None
        app._desktop_render_settings_dlg = None

    if dlg is not None:
        # Second click: if minimized → restore; if visible → close (lower).
        if dlg.isMinimized():
            dlg.showNormal()
            dlg.raise_()
            dlg.activateWindow()
            return
        if dlg.isVisible():
            dlg.close_and_return()
            return

    dlg = DesktopRenderSettingsDialog(app, parent=getattr(app, "ui", None))
    # __init__ already assigned _desktop_render_settings_dlg
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    if hasattr(app, "_sync_dash_render_settings_button"):
        try:
            app._sync_dash_render_settings_button()
        except Exception:
            pass
    if hasattr(app, "_sync_portable_like_dock_chrome"):
        try:
            app._sync_portable_like_dock_chrome()
        except Exception:
            pass


def close_desktop_render_settings(app) -> None:
    dlg = getattr(app, "_desktop_render_settings_dlg", None)
    if dlg is None:
        return
    try:
        dlg.close_and_return()
    except RuntimeError:
        app._desktop_render_settings_dlg = None
