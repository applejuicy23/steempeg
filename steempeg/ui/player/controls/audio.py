"""A YouTube-style expandable volume control with mute memory.

Collapsed it is a round mute button; on hover it animates open to reveal a volume
slider and a percentage label. The icon swaps with the level and the last non-zero
volume is remembered across mutes. The owning player connects to ``self.slider``.
"""
import os

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QLabel, QPushButton, QSlider, QWidget

from steempeg.infra.paths import get_resource_path
from steempeg.ui import design_tokens as tok
from steempeg.ui.widgets import SmartSliderFilter

_ROUND_BTN_STYLE = """
    QPushButton {{ background-color: #4e4e4e; border-radius: {radius}px; }}
    QPushButton:hover {{ background-color: #5a5a5a; }}
"""


def _round_btn_style(size: int = 40) -> str:
    return _ROUND_BTN_STYLE.format(radius=max(1, size // 2))


def _drag_value_font() -> QFont:
    font = QFont("Segoe UI", 9)
    font.setBold(True)
    return font


class VolumeControlWidget(QWidget):
    """ Smart YouTube-style expandable volume control with Mute Memory """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setFixedWidth(44) 
        self.setStyleSheet("background: transparent;")

        self.previous_volume = 100
        self.is_muted = False

        
        self.icon_vol1 = QIcon()
        self.icon_vol2 = QIcon()
        self.icon_vol3 = QIcon()
        self.icon_off = QIcon()
        
        path_1 = get_resource_path("buttonvolume1.png")
        path_2 = get_resource_path("buttonvolume2.png")
        path_3 = get_resource_path("buttonvolume3.png")
        path_off = get_resource_path("volumeoff.png")
        
        if os.path.exists(path_1): self.icon_vol1 = QIcon(path_1)
        if os.path.exists(path_2): self.icon_vol2 = QIcon(path_2)
        if os.path.exists(path_3): self.icon_vol3 = QIcon(path_3)
        if os.path.exists(path_off): self.icon_off = QIcon(path_off)

        # 1. Round button
        self.btn_icon = QPushButton(self)
        self.btn_icon.setFixedSize(40, 40)
        self.btn_icon.move(0, 0)
        self.btn_icon.setCursor(Qt.PointingHandCursor)
        self.btn_icon.setToolTip("Mute / Unmute Volume")
        self.btn_icon.setStyleSheet(_round_btn_style(40))
        
        # Set maximum volume (3) by default
        if not self.icon_vol3.isNull():
            self.btn_icon.setIcon(self.icon_vol3)
            self.btn_icon.setIconSize(QSize(24, 24))
        else:
            self.btn_icon.setText("🔊") 

        self.btn_icon.clicked.connect(self.toggle_mute)

        # 2. The Volume Slider - Starts at X=48
        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setRange(0, 100)
        self.slider.setValue(100)
        
        # INCREASE HITBOX (Height 30 instead of 20)
        self.slider.setFixedSize(80, 30)
        # RAISE SLIGHTLY (Y=5 instead of 10)
        self.slider.move(48, 5) 
        self.slider.setCursor(Qt.PointingHandCursor) 
        
        # Enabling Smart Click
        self.smart_filter = SmartSliderFilter(self.slider)
        self.slider.installEventFilter(self.smart_filter)
        
        line_path = get_resource_path("linevolume.png").replace("\\", "/")
        self.slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{ height: 4px; border-image: url("{line_path}"); background: rgba(255, 255, 255, 50); border-radius: 2px; }}
            QSlider::sub-page:horizontal {{ background: #b498e3; border-radius: 2px; }}
            QSlider::handle:horizontal {{ background: #b498e3; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }}
            QSlider::handle:horizontal:hover {{ transform: scale(1.2); background: #cbb5f2; }}
        """)

        # 3. Percentage Text 
        self.lbl_percent = QLabel("100%", self)
        self.lbl_percent.setFixedSize(45, 20)
        self.lbl_percent.move(136, 10)
        self.lbl_percent.setFont(_drag_value_font())
        self.lbl_percent.setStyleSheet(
            f"color: white; font-family: {tok.FONT_APP}; font-weight: bold; background: transparent;"
        )
        self.lbl_percent.setAlignment(Qt.AlignCenter)

        self.slider.hide()
        self.lbl_percent.hide()

        # 4. Smooth Expansion Animations
        self.anim = QPropertyAnimation(self, b"minimumWidth")
        self.anim.setDuration(200)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)

        self.anim_max = QPropertyAnimation(self, b"maximumWidth")
        self.anim_max.setDuration(200)
        self.anim_max.setEasingCurve(QEasingCurve.OutCubic)

        self.slider.valueChanged.connect(self.update_text)

        self.slider.sliderReleased.connect(self.on_slider_released)

    def toggle_mute(self):
        """ Handles the button click to mute or restore volume """
        if self.is_muted or self.slider.value() == 0:
            # Unmute: Restore to previous volume (default to 100 if it was 0)
            restore_val = self.previous_volume if self.previous_volume > 0 else 100
            self.slider.setValue(restore_val)
        else:
            # Mute: Save current volume and drop to 0
            self.previous_volume = self.slider.value()
            self.slider.setValue(0)

    def update_text(self, val):
        """ Updates the text AND dynamically swaps the icon based on the slider value """
        self.lbl_percent.setText(f"{val}%")
        
        if val == 0:
            # Mute
            if not self.icon_off.isNull(): self.btn_icon.setIcon(self.icon_off)
            else: self.btn_icon.setText("🔇")
            self.is_muted = True
        else:
            if val < 33:
                target_icon = self.icon_vol1
                fallback_txt = "🔈"
            elif val <= 66:
                target_icon = self.icon_vol2
                fallback_txt = "🔉"
            else:
                target_icon = self.icon_vol3
                fallback_txt = "🔊"

            if not target_icon.isNull(): 
                self.btn_icon.setIcon(target_icon)
            else: 
                self.btn_icon.setText(fallback_txt)
                
            self.is_muted = False
            self.previous_volume = val


    def enterEvent(self, event):
        """ Expands the volume widget and shows the slider """
        self.anim.stop()
        self.anim_max.stop()
        
        self.slider.show()
        self.lbl_percent.show()
        
        self.anim.setStartValue(self.width())
        self.anim.setEndValue(185) 
        self.anim_max.setStartValue(self.width())
        self.anim_max.setEndValue(185)
        
        self.anim.start()
        self.anim_max.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """ Collapses the volume widget back to a button """
        # SAFETY CHECK: If the user is actively dragging the slider, DO NOT hide it!
        if self.slider.isSliderDown():
            super().leaveEvent(event)
            return
            
        self.anim.stop()
        self.anim_max.stop()
        
        # MAGIC RESTORED: We removed the instant .hide() calls here!
        # Now it will smoothly animate its width down to 44px first.
        
        self.anim.setStartValue(self.width())
        collapsed = getattr(self, "_collapsed_w", 44)
        self.anim.setEndValue(collapsed)
        self.anim_max.setStartValue(self.width())
        self.anim_max.setEndValue(collapsed)
        
        self.anim.start()
        self.anim_max.start()
        
        # Hide the slider and text safely AFTER the 200ms animation finishes
        QTimer.singleShot(200, self.hide_items)
        
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        """ Ensures the widget collapses if the user released the mouse outside the widget area """
        super().mouseReleaseEvent(event)
        
        # If the mouse was released outside our hitbox, force collapse
        if not self.rect().contains(event.position().toPoint()):
            self.leaveEvent(event)
    def on_slider_released(self):
        """ Triggered when the user lets go of the slider. """
        # If the mouse is already outside the widget when released, collapse it smoothly!
        if not self.underMouse():
            self.anim.stop()
            self.anim_max.stop()
            
            self.anim.setStartValue(self.width())
            collapsed = getattr(self, "_collapsed_w", 44)
            self.anim.setEndValue(collapsed)
            self.anim_max.setStartValue(self.width())
            self.anim_max.setEndValue(collapsed)

            self.anim.start()
            self.anim_max.start()

            QTimer.singleShot(200, self.hide_items)

    def hide_items(self):
        if self.width() <= getattr(self, "_collapsed_w", 44) + 4:
            self.slider.hide()
            self.lbl_percent.hide()

    def apply_density(self, dense) -> None:
        """Scale round mute button with chrome density (keep circular radius)."""
        sz = int(getattr(dense, "chrome_chip", 40) or 40)
        self.setFixedHeight(sz)
        collapsed = sz + 4
        self.setFixedWidth(collapsed)
        self.btn_icon.setFixedSize(sz, sz)
        self.btn_icon.setStyleSheet(_round_btn_style(sz))
        icon = max(16, sz - 16)
        self.btn_icon.setIconSize(QSize(icon, icon))
        self._collapsed_w = collapsed
