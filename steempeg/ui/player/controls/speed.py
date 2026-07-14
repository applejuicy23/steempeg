"""A YouTube-style expandable speed control with a dynamic icon engine.

Collapsed it is a round button showing the current speed (for example ``1.5x``),
rendered by compositing per-digit PNG glyphs into a single icon. On hover it animates
open to reveal a slider; the owning player connects to ``self.slider`` for speed changes.
"""
import os

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer
from PySide6.QtGui import QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QSlider, QWidget

from steempeg.infra.paths import get_resource_path
from steempeg.ui import design_tokens as tok
from steempeg.ui.widgets import SmartSliderFilter

_ROUND_BTN_STYLE = """
    QPushButton { background-color: #4e4e4e; border-radius: 20px; }
    QPushButton:hover { background-color: #5a5a5a; }
"""


def _drag_value_font() -> QFont:
    font = QFont("Segoe UI", 9)
    font.setBold(True)
    return font


class SpeedControlWidget(QWidget):
    """Smart YouTube-style expandable speed control (dynamic PNG icon engine)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setFixedWidth(44)
        self.setStyleSheet("background: transparent;")

        self.previous_speed = 10  # 10 means 1.0x

        self.base_pixmaps = {}
        self.generated_icons = {}

        char_map = {
            "x": "multiplier.png",
            ".": "dot.png",
            "0": "zero.png",
            "1": "one.png",
            "2": "two.png",
            "3": "three.png",
            "4": "four.png",
            "5": "five.png",
            "6": "six.png",
            "7": "seven.png",
            "8": "eight.png",
            "9": "nine.png",
        }

        for char, filename in char_map.items():
            path = get_resource_path(filename)
            if os.path.exists(path):
                if char == "x":
                    self.base_pixmaps[char] = QPixmap(path).scaledToHeight(
                        10, Qt.SmoothTransformation
                    )
                elif char == ".":
                    self.base_pixmaps[char] = QPixmap(path).scaledToHeight(
                        4, Qt.SmoothTransformation
                    )
                else:
                    self.base_pixmaps[char] = QPixmap(path).scaledToHeight(
                        14, Qt.SmoothTransformation
                    )

        self.btn_icon = QPushButton(self)
        self.btn_icon.setFixedSize(40, 40)
        self.btn_icon.move(0, 0)
        self.btn_icon.setCursor(Qt.PointingHandCursor)
        self.btn_icon.setToolTip("Playback Speed")
        self.btn_icon.setStyleSheet(_ROUND_BTN_STYLE)
        self.btn_icon.setIconSize(QSize(36, 16))
        self.btn_icon.clicked.connect(self.toggle_speed)

        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setRange(1, 50)
        self.slider.setValue(10)
        self.slider.setFixedSize(80, 30)
        self.slider.move(48, 5)
        self.slider.setCursor(Qt.PointingHandCursor)

        self.smart_filter = SmartSliderFilter(self.slider)
        self.slider.installEventFilter(self.smart_filter)

        line_path = get_resource_path("linevolume.png").replace("\\", "/")
        self.slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{ height: 4px; border-image: url("{line_path}"); background: rgba(255, 255, 255, 50); border-radius: 2px; }}
            QSlider::sub-page:horizontal {{ background: #b498e3; border-radius: 2px; }}
            QSlider::handle:horizontal {{ background: #b498e3; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }}
            QSlider::handle:horizontal:hover {{ transform: scale(1.2); background: #cbb5f2; }}
        """)

        self.lbl_percent = QLabel("x1.0", self)
        self.lbl_percent.setFixedSize(45, 20)
        self.lbl_percent.move(136, 10)
        self.lbl_percent.setFont(_drag_value_font())
        self.lbl_percent.setStyleSheet(
            f"color: white; font-family: {tok.FONT_APP}; font-weight: bold; background: transparent;"
        )
        self.lbl_percent.setAlignment(Qt.AlignCenter)

        self.slider.hide()
        self.lbl_percent.hide()

        self.anim = QPropertyAnimation(self, b"minimumWidth")
        self.anim.setDuration(200)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)

        self.anim_max = QPropertyAnimation(self, b"maximumWidth")
        self.anim_max.setDuration(200)
        self.anim_max.setEasingCurve(QEasingCurve.OutCubic)

        self.slider.valueChanged.connect(self.update_text)
        self.slider.sliderReleased.connect(self.on_slider_released)

        self.update_text(10)

    def toggle_speed(self):
        if self.slider.value() == 10:
            restore_val = self.previous_speed if self.previous_speed != 10 else 20
            self.slider.setValue(restore_val)
        else:
            self.previous_speed = self.slider.value()
            self.slider.setValue(10)

    def update_text(self, val):
        speed_str = f"{val / 10:.1f}"
        if speed_str.endswith(".0"):
            speed_str = speed_str[:-2]

        full_str = f"{speed_str}x"
        self.lbl_percent.setText(f"x{speed_str}")

        if full_str in self.generated_icons:
            self.btn_icon.setIcon(self.generated_icons[full_str])
            self.btn_icon.setText("")
            return

        total_width = 0
        max_h = 16
        valid_pixmaps = []
        for char in full_str:
            if char in self.base_pixmaps:
                pm = self.base_pixmaps[char]
                valid_pixmaps.append((char, pm))
                total_width += pm.width() + 1

        if not valid_pixmaps:
            self.btn_icon.setIcon(QIcon())
            self.btn_icon.setText(full_str)
            return

        canvas_width = 40
        combined = QPixmap(canvas_width, max_h)
        combined.fill(Qt.transparent)

        start_x = (canvas_width - total_width) // 2
        painter = QPainter(combined)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        current_x = start_x
        for char, pm in valid_pixmaps:
            y_offset = 15 - pm.height()
            if char == "x":
                y_offset -= 1
            painter.drawPixmap(current_x, y_offset, pm)
            spacing = 0 if char == "." else 1
            current_x += pm.width() + spacing

        painter.end()

        final_icon = QIcon(combined)
        self.generated_icons[full_str] = final_icon
        self.btn_icon.setText("")
        self.btn_icon.setIcon(final_icon)

    def enterEvent(self, event):
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
        if self.slider.isSliderDown():
            super().leaveEvent(event)
            return
        self.anim.stop()
        self.anim_max.stop()
        self.anim.setStartValue(self.width())
        self.anim.setEndValue(44)
        self.anim_max.setStartValue(self.width())
        self.anim_max.setEndValue(44)
        self.anim.start()
        self.anim_max.start()
        QTimer.singleShot(200, self.hide_items)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if not self.rect().contains(event.position().toPoint()):
            self.leaveEvent(event)

    def on_slider_released(self):
        if not self.underMouse():
            self.anim.stop()
            self.anim_max.stop()
            self.anim.setStartValue(self.width())
            self.anim.setEndValue(44)
            self.anim_max.setStartValue(self.width())
            self.anim_max.setEndValue(44)
            self.anim.start()
            self.anim_max.start()
            QTimer.singleShot(200, self.hide_items)

    def hide_items(self):
        if self.width() <= 48:
            self.slider.hide()
            self.lbl_percent.hide()
