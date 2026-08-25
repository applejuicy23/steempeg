"""Steempeg-styled editor for custom timeline markers (title / desc / class / icon)."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
)

from steempeg.services import marker_prefs as mprefs
from steempeg.ui import design_tokens as tok
from steempeg.ui.icon_utils import apply_square_icon
from steempeg.ui.marker_icons import load_scaled_pixmap, tint_pixmap
from steempeg.ui.message_dialog import _BTN_PRIMARY, _BTN_SECONDARY, dialog_theme
from steempeg.ui.widgets.combo_chrome import COMBO_POPUP_ITEM_RULES
from steempeg.ui.widgets.dialog_chrome import SteempegDialog
from steempeg.ui.widgets.steempeg_check import SteempegCheckBox

_PREVIEW_EDGE = 36

_FIELD_STYLE = """
    QLineEdit, QTextEdit, QComboBox {
        background-color: #2d2d2d; color: #f0f0f0; border: 1px solid #555;
        border-radius: 6px; padding: 6px 8px; font-size: 12px;
        font-family: <<FONT>>;
    }
    QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border-color: #6b5a8e; }
    QComboBox::drop-down { border: none; width: 22px; }
""".replace("<<FONT>>", tok.FONT_APP) + COMBO_POPUP_ITEM_RULES

_LABEL_STYLE = (
    f"color: {tok.TEXT_MUTED}; font-size: 11px; font-weight: 600; "
    f"background: transparent; font-family: {tok.FONT_APP};"
)


class EditSteamMarkerDialog(SteempegDialog):
    def __init__(
        self,
        title_text: str,
        description: str,
        parent=None,
        *,
        marker_key: str = "usermarker",
        **theme_kwargs,
    ):
        if not theme_kwargs.get("bar_color"):
            theme_kwargs = {**dialog_theme(parent), **theme_kwargs}
        super().__init__("Edit Marker", parent, **theme_kwargs)
        self.setMinimumWidth(400)
        self.resize(440, 360)
        self._marker_key = marker_key or "usermarker"
        self._custom_icon = ""

        prefs = mprefs.load_marker_prefs()
        ov = mprefs.marker_override(self._marker_key, prefs)
        self._custom_icon = ov.get("custom_icon") or ""

        # Icon preview + pick
        icon_row = QHBoxLayout()
        icon_row.setSpacing(10)
        self._preview = QLabel()
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet(
            "background: #1a1a1a; border-radius: 10px; border: 1px solid #444;"
        )
        apply_square_icon(self._preview, None, 44)
        icon_row.addWidget(self._preview)
        icon_btns = QHBoxLayout()
        btn_icon = QPushButton("Set icon…")
        btn_icon.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_icon.setStyleSheet(_BTN_SECONDARY)
        btn_icon.clicked.connect(self._pick_icon)
        btn_clear = QPushButton("Clear")
        btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear.setStyleSheet(_BTN_SECONDARY)
        btn_clear.clicked.connect(self._clear_icon)
        icon_btns.addWidget(btn_icon)
        icon_btns.addWidget(btn_clear)
        icon_btns.addStretch(1)
        icon_col = QHBoxLayout()
        # stack vertically beside preview via nested layout
        from PySide6.QtWidgets import QVBoxLayout

        side = QVBoxLayout()
        side.addWidget(QLabel("Icon"))
        side.itemAt(0).widget().setStyleSheet(_LABEL_STYLE)
        side.addLayout(icon_btns)
        side.addStretch(1)
        icon_row.addLayout(side, 1)
        self.content_layout.addLayout(icon_row)
        self._refresh_preview(prefs)

        # Class
        cls_lbl = QLabel("Class")
        cls_lbl.setStyleSheet(_LABEL_STYLE)
        self.content_layout.addWidget(cls_lbl)
        self._class_combo = QComboBox()
        self._class_combo.setStyleSheet(_FIELD_STYLE)
        self._class_combo.addItem("(no class)", "")
        for cls in prefs.get("classes") or []:
            color = str(cls.get("color") or "").strip()
            suffix = f" ({color})" if color else " (no color)"
            self._class_combo.addItem(
                f"{cls.get('name')}{suffix}", cls.get("id")
            )
        idx = self._class_combo.findData(ov.get("class_id") or "")
        self._class_combo.setCurrentIndex(max(0, idx))
        self._class_combo.currentIndexChanged.connect(
            lambda _i: self._refresh_preview()
        )
        self.content_layout.addWidget(self._class_combo)

        self._no_tint = SteempegCheckBox("Don't apply class color (keep original look)")
        self._no_tint.setToolTip(
            "Stay in the class for grouping, but skip the class tint. "
            "Custom icons already keep their own colors."
        )
        self._no_tint.setChecked(bool(ov.get("no_tint")))
        self._no_tint.toggled.connect(lambda _c: self._refresh_preview())
        self.content_layout.addWidget(self._no_tint)
        self._sync_no_tint_enabled()
        self._class_combo.currentIndexChanged.connect(
            lambda _i: self._sync_no_tint_enabled()
        )

        title_lbl = QLabel("Title")
        title_lbl.setStyleSheet(_LABEL_STYLE)
        self.content_layout.addWidget(title_lbl)

        self._title_edit = QLineEdit(title_text)
        self._title_edit.setStyleSheet(_FIELD_STYLE)
        self.content_layout.addWidget(self._title_edit)

        desc_lbl = QLabel("Description")
        desc_lbl.setStyleSheet(_LABEL_STYLE)
        self.content_layout.addWidget(desc_lbl)

        self._desc_edit = QTextEdit(description)
        self._desc_edit.setStyleSheet(_FIELD_STYLE)
        self.content_layout.addWidget(self._desc_edit, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet(_BTN_SECONDARY)
        btn_cancel.clicked.connect(self.reject)
        actions.addWidget(btn_cancel)

        btn_save = QPushButton("Save")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setStyleSheet(_BTN_PRIMARY)
        btn_save.clicked.connect(self._on_save)
        actions.addWidget(btn_save)

        self.content_layout.addLayout(actions)

    def _sync_no_tint_enabled(self) -> None:
        if not hasattr(self, "_no_tint"):
            return
        self._no_tint.setEnabled(bool(self._class_combo.currentData()))

    def _refresh_preview(self, prefs: dict | None = None) -> None:
        prefs = prefs or mprefs.load_marker_prefs()
        # Temporary combo class for live preview.
        class_id = self._class_combo.currentData() if hasattr(self, "_class_combo") else ""
        path = self._custom_icon
        has_custom = bool(path and os.path.isfile(path))
        if not path and class_id:
            cls = mprefs.get_class(class_id, prefs)
            if cls and cls.get("icon") and os.path.isfile(str(cls["icon"])):
                path = str(cls["icon"])
        if not path:
            path = mprefs.legacy_asset_path("usermarker")
        pix = load_scaled_pixmap(path, _PREVIEW_EDGE) if path else None
        tint = None
        no_tint = bool(getattr(self, "_no_tint", None) and self._no_tint.isChecked())
        if class_id and not has_custom and not no_tint:
            cls = mprefs.get_class(class_id, prefs)
            if cls and not (cls.get("icon") and os.path.isfile(str(cls.get("icon") or ""))):
                tint = str(cls.get("color") or "").strip() or None
        if pix is not None and tint:
            pix = tint_pixmap(pix, str(tint), height=_PREVIEW_EDGE)
        apply_square_icon(self._preview, pix, 44)
        if pix is None:
            self._preview.setText("?")
        else:
            self._preview.setText("")

    def _pick_icon(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Marker icon",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.svg)",
        )
        if not path:
            return
        self._custom_icon = path
        self._refresh_preview()

    def _clear_icon(self) -> None:
        self._custom_icon = ""
        self._refresh_preview()

    def _on_save(self) -> None:
        mprefs.set_marker_override(
            self._marker_key,
            class_id=self._class_combo.currentData() or "",
            custom_icon=self._custom_icon,
            no_tint=bool(self._no_tint.isChecked()) if hasattr(self, "_no_tint") else False,
        )
        self.accept()

    @property
    def title_text(self) -> str:
        return self._title_edit.text().strip()

    @property
    def description_text(self) -> str:
        return self._desc_edit.toPlainText().strip()

    @property
    def class_id(self) -> str:
        return str(self._class_combo.currentData() or "")

    @property
    def custom_icon(self) -> str:
        return self._custom_icon
