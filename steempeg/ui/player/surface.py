"""The video surface that libmpv renders into, plus a 16:9 aspect helper.

MPVWrapper owns the native child window the mpv player attaches to, draws an
optional highlight border and keeps the video centered at 16:9. VideoAspectKeeper
caps a widget's height to a 16:9 ratio so black bars do not appear above and below.
"""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QWidget

from steempeg.ui.player.loading_overlay import PlaybackLoadingOverlay


class MPVWrapper(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.aspect_frame = self 
        
        # Frame Status Flag
        self._is_border_active = False

        #  1. VIDEO (Native, Hardcore)
        self.mpv_screen = QWidget(self)
        self.mpv_screen.setAttribute(Qt.WA_NativeWindow)
        self.mpv_screen.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self.mpv_screen.setAttribute(Qt.WA_OpaquePaintEvent)
        self.mpv_screen.setAttribute(Qt.WA_NoSystemBackground)

        # 2. 4 LINES (Also native, to avoid lag with video)
        self.lines = []
        for _ in range(4):
            line = QWidget(self)
            line.setAttribute(Qt.WA_NativeWindow) 
            line.setAttribute(Qt.WA_DontCreateNativeAncestors)
            line.setStyleSheet("background-color: #ffcc00;")
            line.hide()
            self.lines.append(line)
            
        self.top_line, self.bottom_line, self.left_line, self.right_line = self.lines

        self.loading_overlay = PlaybackLoadingOverlay(self)
        self.loading_overlay.hide()

        self.setStyleSheet("background-color: transparent;")

    def setStyleSheet(self, style):
        if "#ffcc00" in style:
            self.set_border_active(True)
        elif "transparent" in style or "none" in style:
            self.set_border_active(False)
        super().setStyleSheet("background-color: transparent;")

    def update_geometry(self):
        w = self.width()
        h = self.height()
        
        # Closed Splitter Fix
        if w < 5 or h < 5:
            # The native window won't hide itself! Let's collapse it—and hide it with a sledgehammer!
            self.mpv_screen.setGeometry(0, 0, 0, 0)
            self.mpv_screen.hide()
            for line in self.lines: 
                line.hide()
            if getattr(self, 'hud_reference', None) and self.hud_reference.parent() == self:
                self.hud_reference.hide()
            if hasattr(self, 'loading_overlay'):
                self.loading_overlay.hide()
            return
            
        # If the splitter is reopened, we bring everything back to life.
        if self.mpv_screen.isHidden():
            self.mpv_screen.show()
            if getattr(self, '_is_border_active', False):
                for line in self.lines: line.show()
            if getattr(self, 'hud_reference', None) and self.hud_reference.parent() == self:
                self.hud_reference.show()


        b = 3 if getattr(self, '_is_border_active', False) else 0
        
        avail_w = w - (b * 2)
        avail_h = h - (b * 2)
        
        if avail_w * 9 > avail_h * 16:
            video_h = avail_h
            video_w = int(avail_h * 16 / 9)
        else:
            video_w = avail_w
            video_h = int(avail_w * 9 / 16)
            
        total_w = video_w + (b * 2)
        total_h = video_h + (b * 2)
        
        x = (w - total_w) // 2
        y = (h - total_h) // 2
        
        # 1. Embed the video
        self.mpv_screen.setGeometry(x + b, y + b, video_w, video_h)
        if hasattr(self, 'loading_overlay'):
            self.loading_overlay.setGeometry(x + b, y + b, video_w, video_h)
            self.loading_overlay.raise_()

        # 2. Place the frame (only if enabled)
        if getattr(self, '_is_border_active', False):
            self.top_line.setGeometry(x, y, total_w, b)
            self.bottom_line.setGeometry(x, y + total_h - b, total_w, b)
            self.left_line.setGeometry(x, y + b, b, video_h)
            self.right_line.setGeometry(x + total_w - b, y + b, b, video_h)
            # Bring the lines to the front so they don't get hidden.
            for line in self.lines:
                line.raise_()

        #3. Our HUD (Button Panel)
        if getattr(self, 'hud_reference', None) and self.hud_reference.parent() == self:
            hud = self.hud_reference
            hud_h = max(55, hud.sizeHint().height())
            hud_w = min(800, w - 40)
            hud.setGeometry((w - hud_w) // 2, h - hud_h - 30, hud_w, hud_h)
            hud.raise_()

    def resizeEvent(self, event):
        self.update_geometry()
        super().resizeEvent(event)

    def set_border_active(self, active):
        if not hasattr(self, 'lines'):
            return
            
        #Save the state and toggle visibility.
        self._is_border_active = active
        for line in self.lines:
            if active:
                line.show()
                line.raise_()
            else:
                line.hide()
                

        self.update_geometry()


class VideoAspectKeeper(QObject):
    """ Keeps the widget strictly within the 16:9 aspect ratio, preventing black bars from appearing at the top and bottom. """
    def __init__(self, video_widget):
        super().__init__(video_widget)
        self.video_widget = video_widget
        self.video_widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            # Find out the current width of the video widget
            w = event.size().width()
            # Calculate the ideal height for the 16:9 format
            ideal_height = int(w * 9 / 16)
            
            # If the height exceeds the ideal, we block its further growth
            if self.video_widget.maximumHeight() != ideal_height:
                self.video_widget.setMaximumHeight(ideal_height)
                
        return super().eventFilter(obj, event)