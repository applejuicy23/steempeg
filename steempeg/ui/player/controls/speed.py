"""A YouTube-style expandable speed control with a dynamic icon engine.

Collapsed it is a round button showing the current speed (for example ``1.5x``),
rendered by compositing per-digit PNG glyphs into a single icon. On hover it animates
open to reveal a slider; the owning player connects to ``self.slider`` for speed changes.
"""
import os

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer
from PySide6.QtGui import QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from steempeg.infra.paths import get_resource_path
from steempeg.ui import design_tokens as tok
from steempeg.ui.player_boost import (
    SPEED_CEILING_DEFAULT,
    SPEED_UNITY_VALUE,
    get_speed_boost_ceiling,
)
from steempeg.ui.widgets import SmartSliderFilter
from steempeg.ui.widgets.gradient_slider import (
    LEVEL_LABEL_GAP,
    LEVEL_LABEL_W,
    LEVEL_SLIDER_WIDTH,
    LevelGradientSlider,
    level_expand_width,
    level_slider_x,
)

def _round_btn_style(size: int = 40) -> str:
    from steempeg.ui import ui_theme as ut

    radius = max(1, size // 2)
    return tok.with_tooltip_style(ut.player_chrome_round_button_stylesheet(radius=radius))


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
        self.btn_icon.setStyleSheet(_round_btn_style(40))
        self.btn_icon.setIconSize(QSize(36, 16))
        self.btn_icon.clicked.connect(self.toggle_speed)

        self.slider = LevelGradientSlider(Qt.Horizontal, self)
        self.slider.setRange(1, SPEED_CEILING_DEFAULT)
        self.slider.setValue(10)
        self.slider.setFixedSize(LEVEL_SLIDER_WIDTH, 30)
        self.slider.setCursor(Qt.PointingHandCursor)

        self.smart_filter = SmartSliderFilter(self.slider)
        self.slider.installEventFilter(self.smart_filter)

        self.lbl_percent = QLabel("x1.0", self)
        self.lbl_percent.setFixedSize(LEVEL_LABEL_W, 20)
        self.lbl_percent.setFont(_drag_value_font())
        self.lbl_percent.setStyleSheet(
            f"color: white; font-family: {tok.FONT_APP}; font-weight: bold; background: transparent;"
        )
        self.lbl_percent.setAlignment(Qt.AlignCenter)

        self._layout_strip(40)

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

        self.apply_speed_ceiling(get_speed_boost_ceiling())
        self.update_text(self.slider.value())

    def apply_speed_ceiling(self, ceiling: int | None = None) -> int:
        """Resize the slider max (5.0x / 8.0x / 10.0x in tenths). Clamps value."""
        try:
            ceiling = int(ceiling) if ceiling is not None else get_speed_boost_ceiling()
        except (TypeError, ValueError):
            ceiling = SPEED_CEILING_DEFAULT
        ceiling = max(SPEED_CEILING_DEFAULT, ceiling)
        cur = int(self.slider.value())
        self.slider.setMaximum(ceiling)
        # Tick at today's 5.0x hinge when the ceiling is boosted past it.
        self.slider.set_unity_value(
            SPEED_UNITY_VALUE if ceiling > SPEED_UNITY_VALUE else None
        )
        if cur > ceiling:
            self.slider.setValue(ceiling)
        if self.previous_speed > ceiling:
            self.previous_speed = ceiling
        self.update_text(self.slider.value())
        return ceiling

    def toggle_speed(self):
        if self.slider.value() == 10:
            restore_val = self.previous_speed if self.previous_speed != 10 else 20
            if restore_val > self.slider.maximum():
                restore_val = self.slider.maximum()
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
        expand = getattr(self, "_expand_w", level_expand_width(40))
        self.anim.setStartValue(self.width())
        self.anim.setEndValue(expand)
        self.anim_max.setStartValue(self.width())
        self.anim_max.setEndValue(expand)
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
        collapsed = getattr(self, "_collapsed_w", 44)
        self.anim.setEndValue(collapsed)
        self.anim_max.setStartValue(self.width())
        self.anim_max.setEndValue(collapsed)
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

    def _layout_strip(self, btn_size: int) -> None:
        """Place strip + label so the groove hugs the speed circle like old builds."""
        sx = level_slider_x(btn_size)
        sy = max(0, (btn_size - 30) // 2)
        self.slider.move(sx, sy)
        self.lbl_percent.move(sx + LEVEL_SLIDER_WIDTH + LEVEL_LABEL_GAP, max(0, (btn_size - 20) // 2))
        self._expand_w = level_expand_width(btn_size)

    def apply_density(self, dense) -> None:
        """Scale round speed button with chrome density (keep circular radius)."""
        sz = int(getattr(dense, "chrome_chip", 40) or 40)
        self.setFixedHeight(sz)
        collapsed = sz + 4
        self.setFixedWidth(collapsed)
        self.btn_icon.setFixedSize(sz, sz)
        self.btn_icon.setStyleSheet(_round_btn_style(sz))
        self.btn_icon.setIconSize(QSize(max(28, sz - 4), max(12, sz // 2 - 4)))
        self._collapsed_w = collapsed
        self._layout_strip(sz)
