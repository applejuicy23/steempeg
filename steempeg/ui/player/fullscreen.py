"""A global event filter for immersive player mode and player hotkeys.

Created with the application instance, it watches every event: Space toggles
play/pause unless a text field has focus, Escape leaves immersive mode, mouse movement
wakes the floating controls, and minimizing the window hides the timeline preview.
"""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QLineEdit, QTextEdit


class FullscreenEventFilter(QObject):
    """ Global radar for hotkeys and fullscreen control. """
    def __init__(self, app_instance):
        super().__init__()
        self.app_instance = app_instance

    def eventFilter(self, obj, event):
        if getattr(self.app_instance, '_is_closing', False):
            return False

        # Hide preview when minimizing the window
        if event.type() == QEvent.Type.ApplicationStateChange:
            if QApplication.instance().applicationState() != Qt.ApplicationState.ApplicationActive:
                if hasattr(self.app_instance, 'custom_timeline') and hasattr(self.app_instance.custom_timeline, 'preview_widget'):
                    self.app_instance.custom_timeline.preview_widget.hide()

        # GLOBAL KEYBOARD INTERCEPTION (WORKS EVERYWHERE)
        if event.type() == QEvent.Type.KeyPress:
            # 1. SPACE: Play / Pause
            if event.key() == Qt.Key_Space:
                focus_w = QApplication.focusWidget()
                # Protection: If the user is typing text (file name, marker), pass the space character to the text!
                if not isinstance(focus_w, (QLineEdit, QTextEdit)):
                    self.app_instance.toggle_play()
                    return True  # Consume the event to prevent accidental activation of the highlighted button

            # 2. ESC: leave fullscreen, but NEVER let it close the main window
            elif event.key() == Qt.Key_Escape:
                # A stuck immersive transition cover (top-level Tool) can outlive
                # is_fullscreen and eat the screen — always drop it on Esc first.
                cover = getattr(self.app_instance, '_immersive_transition_cover', None)
                cover_was_up = cover is not None and cover.isVisible()
                if cover_was_up and hasattr(self.app_instance, '_hide_immersive_transition_cover'):
                    self.app_instance._hide_immersive_transition_cover()
                if getattr(self.app_instance, 'is_fullscreen', False):
                    self.app_instance.toggle_fullscreen()
                    return True
                if cover_was_up:
                    # Exit path died with is_fullscreen already False — Esc recovers.
                    return True
                # Let child popups / modal dialogs (About, file picker, marker input,
                # combo dropdowns) keep their own Esc-to-close behavior.
                if QApplication.activePopupWidget() is not None:
                    return False
                modal = QApplication.activeModalWidget()
                main_ui = getattr(self.app_instance, 'ui', None)
                if modal is not None and modal is not main_ui:
                    return False
                # Swallow Esc aimed at the main window so QDialog.reject() can't fire.
                return True

        # MOUSE LOGIC (FULLSCREEN ONLY)
        if getattr(self.app_instance, 'is_fullscreen', False):
            if event.type() == QEvent.Type.MouseMove:
                self.app_instance.wake_up_fullscreen_controls()

        return False
