"""A clip card for the library grid: thumbnail, title, date and a type badge."""
import os

import PySide6.QtCore as qtc
import PySide6.QtGui as qtg
import PySide6.QtWidgets as qtw


class ClipCard(qtw.QWidget):
    def __init__(self, title, date_str, badge_text, thumb_path, icon_path, row_idx, parent=None):
        super().__init__(parent)
        self.row_idx = row_idx
        
        # Cell 260, border 3px. That means the inside is exactly 254 by 184!
        self.setFixedSize(254, 184) 
        self.setStyleSheet("QWidget { background: transparent; }")

        layout = qtw.QVBoxLayout(self)
        # Remove the fucking joystick, the picture will stick to the frame itself!
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. --- THUMBNAIL AREA ---
        self.thumb_label = qtw.QLabel(self)
        self.thumb_label.setFixedSize(254, 144) 
        self.thumb_label.setStyleSheet("background-color: #1a1a1a; border-radius: 0px;")
        
        # Remove the old setScaledContents(True) and implement a nice, smooth downscale:
        if thumb_path and os.path.exists(thumb_path):
            pixmap = qtg.QPixmap(thumb_path)
            if not pixmap.isNull():
                # Scaling an image while preserving aspect ratio and applying smoothing
                scaled_thumb = pixmap.scaled(
                    254, 144, 
                    qtc.Qt.KeepAspectRatioByExpanding, 
                    qtc.Qt.SmoothTransformation
                )
                self.thumb_label.setPixmap(scaled_thumb)

        # 2. --- GAME LOGO (OVERLAY) ---
        self.icon_label = qtw.QLabel(self.thumb_label)
        self.icon_label.setFixedSize(24, 24)
        self.icon_label.move(8, 8)
        if icon_path and os.path.exists(icon_path):
            self.icon_label.setPixmap(qtg.QPixmap(icon_path).scaled(24, 24, qtc.Qt.KeepAspectRatio, qtc.Qt.SmoothTransformation))

        # 3. --- BADGE (OVERLAY) ---
        self.badge_label = qtw.QLabel(badge_text, self.thumb_label)
        self.badge_label.setStyleSheet("background-color: #b29ae7; color: black; font-weight: bold; font-size: 11px; border-radius: 4px; padding: 2px 6px;")
        self.badge_label.adjustSize()
        badge_w = self.badge_label.width()
        # Move the badge to the new size
        self.badge_label.move(254 - badge_w - 6, 144 - 24)

        # 4. --- TEXT AREA (BOTTOM OF CARD) ---
        text_widget = qtw.QWidget()
        # Outer border radius of 12px, minus our padding of 3px = Perfect inner radius of 9px!
        text_widget.setStyleSheet("""
            QWidget { 
                background-color: #383838; 
                border: none; 
                border-top-left-radius: 0px; 
                border-top-right-radius: 0px; 
                border-bottom-left-radius: 9px; 
                border-bottom-right-radius: 9px; 
            }
        """)

        text_layout = qtw.QHBoxLayout(text_widget)
        text_layout.setContentsMargins(12, 0, 12, 0)

        title_lbl = qtw.QLabel(title)
        title_lbl.setStyleSheet("QLabel { color: #e0e0e0; font-weight: bold; font-size: 13px; background: transparent; border: none; }")

        date_lbl = qtw.QLabel(date_str)
        date_lbl.setStyleSheet("QLabel { color: #888888; font-size: 11px; background: transparent; border: none; }")

        text_layout.addWidget(title_lbl)
        text_layout.addStretch()
        text_layout.addWidget(date_lbl)

        layout.addWidget(self.thumb_label)
        layout.addWidget(text_widget)