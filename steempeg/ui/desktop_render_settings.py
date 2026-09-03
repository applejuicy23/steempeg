"""Desktop «Like a Portable» — floating Render Settings window (neo panel only)."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QSizePolicy

from steempeg.ui import design_tokens as tok
from steempeg.ui.message_dialog import dialog_theme
from steempeg.ui.portable.sheets import (
    _borrow_widget,
    _clear_borrow_dont_show,
    _return_widget,
)
from steempeg.ui.widgets.dialog_chrome import SteempegDialog

_log = logging.getLogger(__name__)

# v48 comfort size at 2K — neo sidebar + two Video Settings columns.
_FLOAT_W = 980
_FLOAT_H = 640
_FLOAT_MIN_W = 720
_FLOAT_MIN_H = 480


def _clear_stuck_cursor() -> None:
    from steempeg.ui.window_chrome import force_app_cursor_resync

    try:
        force_app_cursor_resync()
    except Exception:
        pass
    QTimer.singleShot(0, force_app_cursor_resync)
    QTimer.singleShot(50, force_app_cursor_resync)


def _raise_floating_dialog(dlg) -> None:
    """Keep modeless Render Settings above the shell (Windows TOPMOST demote race)."""
    try:
        from steempeg.infra.window_focus import prepare_shell_for_modeless_dialog

        shell = dlg.parentWidget()
        prepare_shell_for_modeless_dialog(shell, dlg)
        QTimer.singleShot(
            0, lambda: prepare_shell_for_modeless_dialog(shell, dlg)
        )
    except Exception:
        try:
            dlg.raise_()
            dlg.activateWindow()
        except RuntimeError:
            pass


class DesktopRenderSettingsDialog(SteempegDialog):
    """Non-modal window that borrows the docked neo export panel **once**.

    Like a Portable keeps neo inside this dialog for the whole session:
    close / toggle = hide (warm park). No garage round-trip — that reparent
    is what made the plate crawl outside the chrome on the second open.

    Full teardown (neo back to garage/dock) only via ``dismantle()`` when
    leaving Like a Portable or shutting down.
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
        self._warm = True

        # Opaque HWND — translucent dialog + child neo desyncs hit-tests on Win.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAutoFillBackground(True)

        # Neo borrow can touch winId before geometry is set — keep off-screen
        # until warm-map show() (no Aero flash at 0,0).
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.setWindowOpacity(0.0)

        app._desktop_render_settings_dlg = self

        self.setMinimumSize(_FLOAT_MIN_W, _FLOAT_MIN_H)
        self.resize(_FLOAT_W, _FLOAT_H)
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)

        if self._neo is None:
            empty = QLabel("Render settings panel is not available.")
            empty.setStyleSheet(f"color: {tok.TEXT_MUTED};")
            self.content_layout.addWidget(empty, 1)
        else:
            from steempeg.ui.render_panel import suspend_neo_wrapper_mask_for_float

            # Outer neo mask is for the docked card. Float chrome already rounds —
            # leave the mask off for the life of this warm dialog.
            suspend_neo_wrapper_mask_for_float(app)
            try:
                self._neo.hide()
            except RuntimeError:
                pass
            self._neo.setMaximumHeight(16777215)
            self._neo.setMinimumHeight(0)
            self._home = _borrow_widget(self._neo)
            self._neo.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            tabs = getattr(getattr(app, "ui", None), "settings_tabs", None)
            if tabs is not None:
                from steempeg.ui.settings_prefs import apply_default_render_tab

                apply_default_render_tab(app)
            from steempeg.ui.portable.sheets import expand_neo_for_floating_dialog

            expand_neo_for_floating_dialog(self._neo, self)
            self.content_layout.addWidget(self._neo, 1)

        try:
            self._title_bar.close_requested.disconnect(self.reject)
        except (TypeError, RuntimeError):
            pass
        self._title_bar.close_requested.connect(self.park_hidden)

        self._soft_minimized = False
        min_btn = getattr(self._title_bar, "btn_minimize", None)
        if min_btn is not None:
            try:
                min_btn.clicked.disconnect()
            except (TypeError, RuntimeError):
                pass
            min_btn.clicked.connect(self.soft_minimize)

        self._reclaim_neo_into_dialog(reveal=False)

    def _reveal_neo_chrome(self) -> None:
        """Show borrowed neo only after this dialog is on-screen."""
        neo = self._neo
        if neo is not None:
            _clear_borrow_dont_show(neo)
            neo.show()
        tabs = getattr(getattr(self._app, "ui", None), "settings_tabs", None)
        if tabs is not None:
            try:
                tabs.show()
            except RuntimeError:
                pass
        for name in ("_neo_sidebar", "right_scroll"):
            w = getattr(self._app, name, None)
            if w is not None:
                try:
                    _clear_borrow_dont_show(w)
                    w.show()
                except RuntimeError:
                    pass
        if hasattr(self._app, "fit_settings_tab_to_page"):
            try:
                self._app.fit_settings_tab_to_page()
            except Exception:
                pass

    def _prepare_geometry_before_map(self) -> None:
        if not getattr(self, "_floating_mapped", False):
            self.resize(_FLOAT_W, _FLOAT_H)
            self._floating_mapped = True
            self.ensurePolished()
            self._center_on_parent()
            return
        self.ensurePolished()

    def show(self):
        if self._map_suppressed:
            return super().show()
        return self._show_without_map_flash()

    def _sync_floating_neo_geometry(self) -> None:
        from steempeg.ui.portable.sheets import expand_neo_for_floating_dialog

        neo = self._neo or getattr(self._app, "neo_wrapper", None)
        if neo is None:
            return
        # Keep neo clipped to the content host — never a free-size plate.
        neo.setMinimumSize(0, 0)
        neo.setMaximumSize(16777215, 16777215)
        neo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        expand_neo_for_floating_dialog(neo, self)
        if hasattr(self._app, "fit_settings_tab_to_page"):
            try:
                self._app.fit_settings_tab_to_page()
            except Exception:
                pass

    def showEvent(self, event) -> None:
        super().showEvent(event)
        try:
            self.setWindowOpacity(1.0)
        except RuntimeError:
            pass
        self._reveal_neo_chrome()
        QTimer.singleShot(0, self._sync_floating_neo_geometry)
        QTimer.singleShot(0, lambda: _raise_floating_dialog(self))
        QTimer.singleShot(0, _clear_stuck_cursor)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_floating_neo_geometry()

    def is_parked_minimized(self) -> bool:
        if getattr(self, "_soft_minimized", False):
            return True
        try:
            return bool(self.isMinimized())
        except RuntimeError:
            return False

    def soft_minimize(self) -> None:
        self._soft_minimized = True
        self.hide()
        _clear_stuck_cursor()
        app = self._app
        if hasattr(app, "_sync_dash_render_settings_button"):
            try:
                app._sync_dash_render_settings_button()
            except Exception:
                pass

    def soft_restore(self) -> None:
        self._soft_minimized = False
        try:
            if self.isMinimized():
                self.showNormal()
            else:
                self.show()
        except RuntimeError:
            return
        _raise_floating_dialog(self)
        self._sync_floating_neo_geometry()
        app = self._app
        if hasattr(app, "_sync_dash_render_settings_button"):
            try:
                app._sync_dash_render_settings_button()
            except Exception:
                pass

    def park_hidden(self) -> None:
        """Toggle / title-bar close: hide only — neo stays inside this HWND."""
        self._soft_minimized = False
        self.hide()
        _clear_stuck_cursor()
        app = self._app
        if hasattr(app, "_sync_dash_render_settings_button"):
            try:
                app._sync_dash_render_settings_button()
            except Exception:
                pass
        # Dash glue only — do NOT park neo into the garage (that is the second-
        # open crawl-out / dual-geometry bug).
        try:
            if hasattr(app, "_glue_portable_like_dash_open"):
                app._glue_portable_like_dash_open()
            elif hasattr(app, "_reapply_portable_like_middle_gap"):
                app._reapply_portable_like_middle_gap()
        except Exception:
            pass

    def _reclaim_neo_into_dialog(self, *, reveal: bool = True) -> None:
        neo = self._neo or getattr(self._app, "neo_wrapper", None)
        if neo is None:
            return
        self._neo = neo
        try:
            if self.isAncestorOf(neo):
                if reveal and self.isVisible():
                    self._reveal_neo_chrome()
                self._sync_floating_neo_geometry()
                return
        except RuntimeError:
            return
        try:
            neo.hide()
        except RuntimeError:
            pass
        parent = neo.parentWidget()
        if parent is not None:
            lay = parent.layout()
            if lay is not None:
                lay.removeWidget(neo)
            else:
                _borrow_widget(neo)
        neo.setMaximumHeight(16777215)
        neo.setMinimumHeight(0)
        neo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.content_layout.addWidget(neo, 1)
        if getattr(self._app, "_neo_dock_home", None):
            self._app._neo_dock_home = None
        try:
            from steempeg.ui.render_panel import suspend_neo_wrapper_mask_for_float

            suspend_neo_wrapper_mask_for_float(self._app)
        except Exception:
            pass
        if reveal and self.isVisible():
            self._reveal_neo_chrome()
        self._sync_floating_neo_geometry()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        from PySide6.QtCore import QEvent

        if event.type() != QEvent.Type.WindowStateChange:
            return
        app = self._app
        if hasattr(app, "_sync_dash_render_settings_button"):
            try:
                app._sync_dash_render_settings_button()
            except Exception:
                pass

    def dismantle(self) -> None:
        """Real teardown — leave Like a Portable / app exit only."""
        if self._returned:
            self.hide()
            self.deleteLater()
            return
        self._warm = False
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
        _clear_stuck_cursor()
        self._light_portable_like_after_settings_close(app)

    # Back-compat alias used by older call sites / mode switch.
    def close_and_return(self) -> None:
        self.dismantle()

    def _return_neo(self) -> None:
        if self._returned or self._neo is None:
            return
        self._returned = True
        parent, layout, index, kind = self._home
        app = self._app
        garage = getattr(app, "_neo_chrome_garage", None)
        try:
            try:
                self._neo.hide()
            except RuntimeError:
                pass
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
                _clear_borrow_dont_show(self._neo)
                garage.layout().addWidget(self._neo)
                self._neo.hide()
            elif (
                not portable_like
                and hasattr(app, "_restore_neo_to_dock_layout")
            ):
                if self._neo.parentWidget() is not None:
                    prev = self._neo.parentWidget()
                    prev_lay = prev.layout() if prev is not None else None
                    if prev_lay is not None:
                        prev_lay.removeWidget(self._neo)
                app._restore_neo_to_dock_layout()
            else:
                _clear_borrow_dont_show(self._neo)
                _return_widget(self._neo, parent, layout, index, kind, visible=True)
        except Exception:
            _log.exception("Failed returning neo_wrapper after Render Settings close")
        try:
            from steempeg.ui.render_panel import restore_neo_dock_masks

            restore_neo_dock_masks(self._app)
        except Exception:
            pass
        if hasattr(self._app, "fit_settings_tab_to_page"):
            try:
                self._app.fit_settings_tab_to_page()
            except Exception:
                pass

    def reject(self) -> None:
        self.park_hidden()

    def closeEvent(self, event) -> None:
        # Title-bar / Alt-F4 while warm: park, do not tear neo out of the HWND.
        if self._warm and not self._returned:
            event.ignore()
            self.park_hidden()
            return
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
        _clear_stuck_cursor()
        self._light_portable_like_after_settings_close(app)

    @staticmethod
    def _light_portable_like_after_settings_close(app) -> None:
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
        super().apply_ui_theme_chrome()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        from steempeg.ui.render_panel import apply_render_panel_theme_chrome

        ui = getattr(self._app, "ui", None)
        if ui is not None:
            apply_render_panel_theme_chrome(ui)


def toggle_desktop_render_settings(app) -> None:
    """Open / raise / park the desktop Render Settings window."""
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
        # Hidden warm dialog (toggle close / soft minimize) → show again.
        try:
            if not dlg.isVisible() or dlg.isMinimized() or (
                hasattr(dlg, "is_parked_minimized") and dlg.is_parked_minimized()
            ):
                if hasattr(dlg, "soft_restore"):
                    dlg.soft_restore()
                else:
                    dlg.showNormal()
                    _raise_floating_dialog(dlg)
                if hasattr(app, "_sync_dash_render_settings_button"):
                    try:
                        app._sync_dash_render_settings_button()
                    except Exception:
                        pass
                return
        except RuntimeError:
            dlg = None
            app._desktop_render_settings_dlg = None
        else:
            # Visible → park (no garage reparent).
            dlg.park_hidden()
            return

    dlg = DesktopRenderSettingsDialog(app, parent=getattr(app, "ui", None))
    dlg.show()
    _raise_floating_dialog(dlg)
    if hasattr(dlg, "_reclaim_neo_into_dialog"):
        dlg._reclaim_neo_into_dialog(reveal=True)
    if hasattr(app, "_sync_dash_render_settings_button"):
        try:
            app._sync_dash_render_settings_button()
        except Exception:
            pass


def close_desktop_render_settings(app) -> None:
    """Full teardown — used when leaving Like a Portable."""
    dlg = getattr(app, "_desktop_render_settings_dlg", None)
    if dlg is None:
        return
    try:
        if hasattr(dlg, "dismantle"):
            dlg.dismantle()
        else:
            dlg.close_and_return()
    except RuntimeError:
        app._desktop_render_settings_dlg = None
