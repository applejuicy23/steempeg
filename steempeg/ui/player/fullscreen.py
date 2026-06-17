"""A global event filter for fullscreen control and player hotkeys.

Created with the application instance, it watches every event: Space toggles
play/pause unless a text field has focus, Escape leaves fullscreen, mouse movement
wakes the fullscreen controls, and minimizing the window hides the timeline preview.
"""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QLineEdit, QTextEdit


class FullscreenEventFilter(QObject):
    """ Global radar for hotkeys and fullscreen control. """
    def __init__(self, app_instance):
        super().__init__()
        self.app_instance = app_instance

    def eventFilter(self, obj, event):
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
                    return True # Consume the event to prevent accidental activation of the highlighted button
                    
            # 2. ESC: Exit full-screen mode
            elif event.key() == Qt.Key_Escape and getattr(self.app_instance, 'is_fullscreen', False):
                self.app_instance.toggle_fullscreen()
                return True

        # MOUSE LOGIC (FULLSCREEN ONLY)
        if getattr(self.app_instance, 'is_fullscreen', False):
            if event.type() == QEvent.Type.MouseMove:
                self.app_instance.wake_up_fullscreen_controls()

        return False
