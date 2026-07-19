"""An editable combo box that validates its text against the allowed items.

Used for the date and time pickers in the filter panel.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QCompleter

from steempeg.ui.widgets.combo_chrome import COMBO_POPUP_ITEM_RULES


class BlockCombo(QComboBox):
    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.addItems(items)
        self.setInsertPolicy(QComboBox.NoInsert)

        completer = QCompleter(items, self)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.setCompleter(completer)
        self.setCursor(Qt.PointingHandCursor)

        self.lineEdit().setAlignment(Qt.AlignCenter)
        self.lineEdit().setTextMargins(0, 0, 0, 0)

        # Pad a single typed digit to two digits when editing finishes.
        self.lineEdit().editingFinished.connect(self.auto_pad_zero)

        self.style_normal = """
            QComboBox { background: #1e1e1e; color: white; border: 1px solid #333; border-radius: 6px; padding: 0px; font-weight: bold; font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji'; }
            QLineEdit { background: transparent; color: white; border: none; selection-background-color: #b29ae7; selection-color: black; padding: 0px; margin: 0px; }
            QComboBox::drop-down { border: none; width: 0px; }
        """ + COMBO_POPUP_ITEM_RULES
        self.style_error = self.style_normal.replace(
            "border: 1px solid #333;", "border: 2px solid #ff4444;"
        )
        self.setStyleSheet(self.style_normal)
        self.currentTextChanged.connect(self.validate_text)

    def auto_pad_zero(self):
        """Convert a single digit like '1' into '01' once input is finished."""
        txt = self.lineEdit().text()
        if txt.isdigit() and len(txt) == 1:
            self.setCurrentText(f"0{txt}")

    def validate_text(self, text):
        valid_items = [self.itemText(i).lower() for i in range(self.count())]
        if text.lower() in valid_items:
            self.setStyleSheet(self.style_normal)
        else:
            self.setStyleSheet(self.style_error)

    def is_valid(self):
        return self.currentText().lower() in [
            self.itemText(i).lower() for i in range(self.count())
        ]
