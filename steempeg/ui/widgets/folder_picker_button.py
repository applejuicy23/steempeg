"""Composite Choose Folder button with a combobox-style side that opens a panel."""
from steempeg.ui import design_tokens as tok
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

from steempeg.ui.ui_density import COMFORT, UiDensity

_BUSY_TICK_MS = 40
_BUSY_DEG_PER_TICK = 18
_BUSY_ARC_COLOR = QColor("#b29ae7")
_BUSY_TRACK_COLOR = QColor(80, 80, 80, 160)


def _folder_style(dense: UiDensity) -> str:
    from steempeg.ui import ui_theme as ut

    if ut.get_ui_theme() != ut.UI_THEME_DEFAULT:
        return ut.split_footer_composite_stylesheet(dense, "folder")
    r = dense.footer_radius
    return f"""
    QPushButton#FolderPickerMain {{
        font-family: {tok.FONT_APP};
        font-size: {dense.footer_font}px;
        font-weight: bold;
        background-color: #383838;
        color: #ffffff;
        border: 2px solid #444444;
        border-right: none;
        border-top-left-radius: {r}px;
        border-bottom-left-radius: {r}px;
        border-top-right-radius: 0px;
        border-bottom-right-radius: 0px;
        padding: {dense.footer_pad};
        min-height: {dense.footer_min_h}px;
    }}
    QPushButton#FolderPickerMain:hover {{
        background-color: #404040;
        border: 2px solid #6b5a8e;
        border-right: none;
    }}
    QPushButton#FolderPickerMain:pressed {{
        background-color: #3a324a;
        border: 2px solid #b29ae7;
        border-right: none;
    }}
    QPushButton#FolderPickerAdd {{
        background-color: #383838;
        color: #ffffff;
        border: 2px solid #444444;
        border-left: 1px solid #555555;
        border-top-left-radius: 0px;
        border-bottom-left-radius: 0px;
        border-top-right-radius: {r}px;
        border-bottom-right-radius: {r}px;
        font-family: {tok.FONT_APP};
        font-size: {17 if not dense.compact else 14}px;
        font-weight: bold;
        min-width: {dense.footer_add_w}px;
        max-width: {dense.footer_add_w + 4}px;
        padding: 2px 0;
        min-height: {dense.footer_min_h}px;
    }}
    QPushButton#FolderPickerAdd:hover {{
        background-color: #404040;
        color: #d4c4ff;
        border: 2px solid #6b5a8e;
        border-left: 1px solid #6b5a8e;
    }}
    QPushButton#FolderPickerAdd:pressed {{
        background-color: #3a324a;
        border: 2px solid #b29ae7;
        border-left: 1px solid #b29ae7;
    }}
"""


class _FolderPickerAddButton(QPushButton):
    """``+`` chip that paints a busy arc while the library is scanning."""

    def __init__(self, parent=None):
        super().__init__("+", parent)
        self.setObjectName("FolderPickerAdd")
        self._busy = False
        self._angle = 0
        self._spin = QTimer(self)
        self._spin.setInterval(_BUSY_TICK_MS)
        self._spin.timeout.connect(self._on_tick)

    def set_busy(self, busy: bool) -> None:
        busy = bool(busy)
        if self._busy == busy:
            return
        self._busy = busy
        if busy:
            self.setText("")
            self.setToolTip("Loading library folders…")
            if not self._spin.isActive():
                self._spin.start()
        else:
            self._spin.stop()
            self._angle = 0
            self.setText("+")
            self.setToolTip("Manage clips folders")
        self.update()

    def is_busy(self) -> bool:
        return bool(self._busy)

    def _on_tick(self) -> None:
        if not self._busy:
            self._spin.stop()
            return
        self._angle = (self._angle + _BUSY_DEG_PER_TICK) % 360
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if not self._busy:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        side = min(self.width(), self.height())
        pad = max(4.0, side * 0.22)
        rect = QRectF(
            (self.width() - side) / 2.0 + pad,
            (self.height() - side) / 2.0 + pad,
            side - 2.0 * pad,
            side - 2.0 * pad,
        )
        track = QPen(_BUSY_TRACK_COLOR)
        track.setWidthF(2.2)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawEllipse(rect)

        arc = QPen(_BUSY_ARC_COLOR)
        arc.setWidthF(2.2)
        arc.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(arc)
        # Qt arcs: 16ths of a degree, 0 = 3 o'clock, counter-clockwise.
        painter.drawArc(rect, int((90 - self._angle) * 16), int(-110 * 16))
        painter.end()


class FolderPickerButton(QWidget):
    """Choose Folder… with a combobox-style + cell that opens the folders panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._density = COMFORT

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.main_btn = QPushButton("📂 Choose Folder…")
        self.main_btn.setObjectName("FolderPickerMain")
        self.main_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.main_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.add_btn = _FolderPickerAddButton()
        self.add_btn.setToolTip("Manage clips folders")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        layout.addWidget(self.main_btn, 1)
        layout.addWidget(self.add_btn)

        self._add_visible = True
        self.apply_density(COMFORT)
        self._update_main_radius()

    def apply_density(self, dense: UiDensity) -> None:
        self._density = dense
        self.setStyleSheet(_folder_style(dense))
        self._update_main_radius()

    def _update_main_radius(self):
        """When the + is hidden, the main button should be fully rounded on both sides."""
        r = self._density.footer_radius
        if self._add_visible:
            self.main_btn.setStyleSheet("")  # inherit composite stylesheet
        else:
            self.main_btn.setStyleSheet(
                f"QPushButton#FolderPickerMain {{"
                f" border: 2px solid #444444;"
                f" border-top-right-radius: {r}px;"
                f" border-bottom-right-radius: {r}px; }}"
                f"QPushButton#FolderPickerMain:hover {{ border: 2px solid #6b5a8e; }}"
                f"QPushButton#FolderPickerMain:pressed {{ border: 2px solid #b29ae7; }}"
            )

    def set_add_visible(self, visible):
        self._add_visible = bool(visible)
        self.add_btn.setVisible(self._add_visible)
        self._update_main_radius()

    def set_busy(self, busy: bool) -> None:
        """Spin the + chip while the clips library is loading."""
        if hasattr(self.add_btn, "set_busy"):
            self.add_btn.set_busy(bool(busy))

    def set_folder_label(self, text, tooltip=""):
        self.main_btn.setText(text)
        tip = tooltip or text
        self.main_btn.setToolTip(tip)
        self.setToolTip(tip)
