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

    Minimize in the title bar (no maximize — keep a fixed usable size). Closing
    (or toggling the dash button) returns neo to the main shell (hidden again
    while Like a Portable).
    """

    def __init__(self, app, parent=None):
        theme = dialog_theme(parent or getattr(app, "ui", None))
        super().__init__(
            "Render Settings",
            parent or getattr(app, "ui", None),
            show_minimize=True,
            show_maximize=False,
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

        # Do NOT call _sync_portable_like_dock_chrome here — with this dialog
        # registered as floating it used to still re-glue the main splitter
        # (1–2s lag). Neo is already borrowed into this window.
        self._reclaim_neo_into_dialog()

    def _reclaim_neo_into_dialog(self) -> None:
        neo = self._neo or getattr(self._app, "neo_wrapper", None)
        if neo is None:
            return
        self._neo = neo
        try:
            if self.isAncestorOf(neo):
                neo.show()
                return
        except RuntimeError:
            return
        parent = neo.parentWidget()
        if parent is not None:
            lay = parent.layout()
            if lay is not None:
                lay.removeWidget(neo)
            else:
                neo.setParent(None)
        neo.setMaximumHeight(16777215)
        neo.setMinimumHeight(0)
        neo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.content_layout.addWidget(neo, 1)
        neo.show()
        if getattr(self._app, "_neo_dock_home", None):
            self._app._neo_dock_home = None
        for name in ("_neo_sidebar", "right_scroll"):
            w = getattr(self._app, name, None)
            if w is not None:
                try:
                    w.show()
                except RuntimeError:
                    pass
        tabs = getattr(getattr(self._app, "ui", None), "settings_tabs", None)
        if tabs is not None:
            try:
                tabs.show()
            except RuntimeError:
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
        # Light close: neo already in garage — only re-glue dash. Full dock sync
        # (setSizes + middle-gap + spacer walk) was the 1–2s close lag.
        self._light_portable_like_after_settings_close(app)

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
        self._light_portable_like_after_settings_close(app)

    @staticmethod
    def _light_portable_like_after_settings_close(app) -> None:
        """Park neo + glue dash without a full portable-like dock rebuild."""
        try:
            if hasattr(app, "_desktop_render_layout_is_portable_like"):
                if not app._desktop_render_layout_is_portable_like():
                    if hasattr(app, "_sync_portable_like_dock_chrome"):
                        app._sync_portable_like_dock_chrome()
                    return
            if hasattr(app, "_park_neo_away_from_dock"):
                app._park_neo_away_from_dock()
            if hasattr(app, "_glue_portable_like_dash_open"):
                app._glue_portable_like_dash_open()
            elif hasattr(app, "_reapply_portable_like_middle_gap"):
                app._reapply_portable_like_middle_gap()
        except Exception:
            _log.exception("Light portable-like restore after Render Settings failed")
            if hasattr(app, "_sync_portable_like_dock_chrome"):
                try:
                    app._sync_portable_like_dock_chrome()
                except Exception:
                    pass

    def apply_ui_theme_chrome(self) -> None:
        """Re-tint dialog shell when UI theme changes while window is open."""
        super().apply_ui_theme_chrome()
        from steempeg.ui.render_panel import apply_render_panel_theme_chrome

        ui = getattr(self._app, "ui", None)
        if ui is not None:
            apply_render_panel_theme_chrome(ui)


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
    # One reclaim only — no post-show dock sync (that re-glued the shell).
    if hasattr(dlg, "_reclaim_neo_into_dialog"):
        dlg._reclaim_neo_into_dialog()
    if hasattr(app, "_sync_dash_render_settings_button"):
        try:
            app._sync_dash_render_settings_button()
        except Exception:
            pass
    # Do not touch update_status_indicator here — forcing "Ready" zeroed the
    # encode progress strip on every open (rapid toggle made it obvious).


def close_desktop_render_settings(app) -> None:
    dlg = getattr(app, "_desktop_render_settings_dlg", None)
    if dlg is None:
        return
    try:
        dlg.close_and_return()
    except RuntimeError:
        app._desktop_render_settings_dlg = None
