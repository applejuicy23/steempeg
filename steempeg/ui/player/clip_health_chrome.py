"""Health badge and anchored popup shared by the desktop and Express players."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QWidget, QWidgetAction

from steempeg.ui import design_tokens as tok, ui_theme as ut
from steempeg.ui.icon_assets import health_icon
from steempeg.ui.player_header_layout import player_header_chip_qfont


def apply_clip_health_button(
    button, report, *, pad="4px 12px 4px 10px", font_px=13, icon_px=18, min_h=30
) -> None:
    color = report.color
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    button.setToolTip(report.summary())
    button.setIcon(health_icon(report.level, icon_px))
    button.setIconSize(QSize(icon_px, icon_px))
    button.setText(f" {report.label}")
    button.setMinimumHeight(min_h)
    button.setMinimumWidth(0)
    button.setMaximumWidth(16777215)
    button.setFont(player_header_chip_qfont(font_px))
    button.setStyleSheet(
        f"QPushButton {{"
        f"background-color: rgba({r}, {g}, {b}, 0.22);"
        f"color: {color};"
        f"border: 2px solid {color};"
        f"border-radius: 8px;"
        f"font-weight: bold;"
        f"font-size: {font_px}px;"
        f"padding: {pad};"
        f"font-family: {tok.FONT_APP};"
        f"}}"
        f"QPushButton:hover {{ background-color: rgba({r}, {g}, {b}, 0.35); }}"
    )
    button.show()
def build_clip_health_menu(parent, display) -> QMenu:
    menu = QMenu(parent)
    menu.setStyleSheet(ut.health_menu_stylesheet())

    # Title row as a widget: icon sits next to the label (not a reserved muted
    # left column), and keeps full color even though the row is non-clickable.
    title_host = QWidget(menu)
    title_row = QHBoxLayout(title_host)
    title_row.setContentsMargins(12, 8, 16, 8)
    title_row.setSpacing(8)
    title_icon = QLabel()
    title_icon.setPixmap(health_icon(display.level, 16).pixmap(16, 16))
    title_icon.setFixedSize(16, 16)
    title_lbl = QLabel(display.label)
    title_lbl.setStyleSheet(
        f"color: {display.color}; font-weight: bold; font-size: 13px;"
        f" font-family: {tok.FONT_APP}; background: transparent;"
    )
    title_row.addWidget(title_icon, 0, Qt.AlignVCenter)
    title_row.addWidget(title_lbl, 0, Qt.AlignVCenter)
    title_row.addStretch(1)
    title_act = QWidgetAction(menu)
    title_act.setDefaultWidget(title_host)
    # Keep enabled so Qt doesn't desaturate the row into greyscale.
    # No trigger is connected, so it still behaves like a visual header.
    title_act.setEnabled(True)
    menu.addAction(title_act)
    menu.addSeparator()

    if display.issues:
        for issue in display.issues:
            act = menu.addAction(f"• {issue}")
            act.setEnabled(False)
    else:
        act = menu.addAction("No issues detected.")
        act.setEnabled(False)

    return menu
