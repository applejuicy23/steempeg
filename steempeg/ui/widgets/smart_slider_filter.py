"""An event filter that lets a slider jump to the clicked position and then keep dragging.

Install it on a QSlider, e.g. slider.installEventFilter(SmartSliderFilter(slider)).
"""
from PySide6.QtCore import QEvent, QObject, Qt


class SmartSliderFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.LeftButton:
            x = event.position().toPoint().x()
            width = obj.width()
            if width > 0:
                # Map the click position to a slider value.
                val = obj.minimum() + ((obj.maximum() - obj.minimum()) * x) / width
                obj.setValue(int(val))

                # Push the value out so the player reacts right away.
                if hasattr(obj, "sliderMoved"):
                    obj.sliderMoved.emit(int(val))
                if hasattr(obj, "valueChanged"):
                    obj.valueChanged.emit(int(val))

                # Return False so the click still reaches the slider. The handle is now
                # under the cursor, so Qt grabs it and the user can keep dragging smoothly.
                return False
        return super().eventFilter(obj, event)
