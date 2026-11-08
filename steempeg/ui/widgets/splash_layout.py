"""Shared sizing for floating Settings help and choice previews."""
from PySide6.QtWidgets import QWidget


def fit_splash_layout(widget: QWidget, width: int) -> None:
    """Includes every visible row, layout gap, and outer margin in the height."""
    layout = widget.layout()
    layout.invalidate()
    height = layout.totalHeightForWidth(width)
    if height < 0:
        height = layout.totalSizeHint().height()
    widget.setFixedSize(width, height)
    layout.activate()
