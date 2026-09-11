"""Size · Big/Medium/Small (+ optional List) chrome.

Toolbar: one ghost icon chip. Popup: three size tiles; when
``library_allow_list_view`` is on, a fourth **List** tile (``defaultsort.png``)
opens the classic table — not a separate toolbar button.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from steempeg.ui import design_tokens as tok
from steempeg.ui import ui_theme as ut
from steempeg.ui.icon_assets import (
    CARD_SIZE_GRID_TINT,
    card_size_grid_icon,
    card_size_grid_pixmap,
    view_mode_list_icon,
    view_mode_list_pixmap,
)
from steempeg.ui.library.card_sizes import (
    CARD_SIZE_BIG,
    CARD_SIZE_LABELS,
    CARD_SIZES,
    normalize_card_size,
)
from steempeg.ui.ui_density import (
    COMFORT,
    VIEW_TOGGLE_SEG_NAME,
    UiDensity,
    toggle_segment_min_height,
    view_toggle_button_styles,
)

_TOOLBAR_GLYPH = CARD_SIZE_GRID_TINT
_POPUP_GLYPH_PX = 40
_SIZE_BTN_NAME = "CardSizeGhostBtn"
_LIST_KEY = "list"


def _font_css() -> str:
    return "font-family: " + tok.FONT_APP + ";"


def _size_ghost_button_style(*, radius: int = 6) -> str:
    """Minimal transparent chip — no purple plate, soft hover only."""
    return f"""
        QPushButton#{_SIZE_BTN_NAME} {{
            background-color: transparent;
            border: 1px solid transparent;
            border-radius: {radius}px;
            padding: 2px;
        }}
        QPushButton#{_SIZE_BTN_NAME}:hover {{
            background-color: rgba(178, 154, 231, 0.12);
            border: 1px solid #6b5a8e;
        }}
        QPushButton#{_SIZE_BTN_NAME}:pressed {{
            background-color: rgba(178, 154, 231, 0.22);
            border: 1px solid #b29ae7;
        }}
    """


class _SizePreviewTile(QPushButton):
    """Popup tile — size glyph or List (defaultsort)."""

    def __init__(self, size_key: str, parent=None):
        super().__init__(parent)
        self._size_key = size_key
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        self.setFlat(True)
        self.setFixedSize(92, 88)
        if size_key == _LIST_KEY:
            self.setToolTip("List")
        else:
            self.setToolTip(CARD_SIZE_LABELS.get(size_key, size_key))

    def paintEvent(self, event) -> None:  # noqa: N802
        chrome = ut.card_size_popup_chrome()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        selected = self.isChecked()
        hovered = self.underMouse()
        if selected:
            bg = QColor(chrome.tile_selected_bg)
            border = QColor(chrome.tile_selected_border)
        elif hovered:
            bg = QColor(chrome.tile_hover_bg)
            border = QColor(chrome.tile_hover_border)
        else:
            bg = QColor(chrome.tile_bg)
            border = QColor(chrome.tile_border)
        p.setPen(border)
        p.setBrush(bg)
        p.drawRoundedRect(1, 1, self.width() - 2, self.height() - 2, 8, 8)

        tint = chrome.glyph_selected if selected else chrome.glyph
        if self._size_key == _LIST_KEY:
            glyph = view_mode_list_pixmap(_POPUP_GLYPH_PX, color=tint)
            label = "List"
        else:
            glyph = card_size_grid_pixmap(self._size_key, _POPUP_GLYPH_PX, color=tint)
            label = CARD_SIZE_LABELS.get(self._size_key, self._size_key)
        if not glyph.isNull():
            gx = (self.width() - glyph.width()) // 2
            gy = 10
            p.drawPixmap(gx, gy, glyph)

        p.setPen(QColor(chrome.label_selected if selected else chrome.label))
        font = QFont(tok.FONT_APP)
        font.setBold(True)
        font.setPixelSize(11)
        p.setFont(font)
        p.drawText(
            QRectF(0, self.height() - 22, self.width(), 18),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            label,
        )
        p.end()


class _CardSizePopup(QFrame):
    """Emits ``size`` keys or ``list`` when the List tile is picked."""

    choice_picked = Signal(str)

    def __init__(self, current: str, *, allow_list: bool, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("CardSizePopup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        chrome = ut.card_size_popup_chrome()
        self.setStyleSheet(
            f"""
            QFrame#CardSizePopup {{
                background-color: {chrome.panel_bg};
                border: 1px solid {chrome.panel_border};
                border-radius: 10px;
            }}
            """
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        keys = list(CARD_SIZES)
        if allow_list:
            keys.append(_LIST_KEY)
        # ``current`` is ``list`` or a size key.
        for key in keys:
            tile = _SizePreviewTile(key, self)
            tile.setChecked(key == current)
            tile.clicked.connect(lambda _=False, k=key: self._pick(k))
            lay.addWidget(tile)

    def _pick(self, key: str) -> None:
        self.choice_picked.emit(key)
        self.hide()


class CardSizeChrome(QObject):
    """Owns Size label + one ghost chip + count. List is a popup tile when allowed."""

    size_changed = Signal(str)
    mode_changed = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        initial_size: str = CARD_SIZE_BIG,
        initial_mode: str = "grid",
        allow_list: bool = False,
        size_only: bool = False,
        dense: UiDensity | None = None,
        initial_count: str | None = None,
    ):
        super().__init__(parent)
        self._density = dense if dense is not None else COMFORT
        self._size = normalize_card_size(initial_size)
        self._mode = "list" if initial_mode == "list" and allow_list else "grid"
        self._allow_list = bool(allow_list)
        self._size_only = bool(size_only)
        self._popup: _CardSizePopup | None = None

        self.lbl_view = QLabel("Size", parent)
        self._apply_label_style(self.lbl_view)

        self.toggle_pill = QFrame(parent)
        self.toggle_pill.setObjectName("CardSizeChromeHost")
        self.toggle_pill.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.toggle_pill.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
        )
        self.toggle_pill.setStyleSheet(
            "QFrame#CardSizeChromeHost { background: transparent; border: none; }"
        )
        toggle_layout = QHBoxLayout(self.toggle_pill)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.setSpacing(0)

        self.btn_size = QPushButton(self.toggle_pill)
        self.btn_size.setObjectName(_SIZE_BTN_NAME)
        self.btn_size.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_size.setFlat(True)
        self.btn_size.setText("")
        self.btn_size.clicked.connect(self._open_size_popup)

        # Compat aliases — callers still look for Grid/List button attrs.
        self.btn_view_grid = self.btn_size
        self.btn_view_list = QPushButton(self.toggle_pill)
        self.btn_view_list.setObjectName(VIEW_TOGGLE_SEG_NAME)
        self.btn_view_list.hide()  # List lives in the Size popup, not the toolbar.

        self.toggle_style_active, self.toggle_style_inactive = view_toggle_button_styles(
            self._density
        )
        toggle_layout.addWidget(self.btn_size)

        self.lbl_count = QLabel(
            initial_count if initial_count is not None else "(0)", parent
        )
        self._apply_count_style(self.lbl_count)

        self._apply_segment_metrics(self._density)
        self._sync_buttons()
        self.set_allow_list(self._allow_list and not self._size_only)

    def add_to_layout(self, layout, *, include_count: bool = True) -> None:
        layout.addWidget(self.lbl_view)
        layout.addWidget(self.toggle_pill)
        if include_count:
            layout.addWidget(self.lbl_count)

    @property
    def size(self) -> str:
        return self._size

    @property
    def mode(self) -> str:
        return self._mode

    def set_size(self, size: str, *, emit: bool = True) -> None:
        key = normalize_card_size(size)
        size_changed = key != self._size
        mode_was_list = self._mode == "list"
        self._size = key
        if mode_was_list:
            self._mode = "grid"
        self._sync_buttons()
        if size_changed and emit:
            self.size_changed.emit(key)
        if mode_was_list and emit:
            self.mode_changed.emit("grid")

    def set_mode(self, mode: str, *, emit: bool = True) -> None:
        if mode not in ("list", "grid"):
            return
        if mode == "list" and (self._size_only or not self._allow_list):
            mode = "grid"
        changed = mode != self._mode
        self._mode = mode
        self._sync_buttons()
        if changed and emit:
            self.mode_changed.emit(mode)

    def set_allow_list(self, allow: bool) -> None:
        self._allow_list = bool(allow) and not self._size_only
        self.btn_view_list.hide()
        if not self._allow_list and self._mode == "list":
            self._mode = "grid"
        self._sync_buttons()

    def set_grid_only(self, grid_only: bool) -> None:
        """Screenshots: size chrome still works; List never shown.

        Must clear ``_size_only`` when leaving Screenshots — sticky True
        used to hide List forever after one Screenshots visit.
        """
        self._size_only = bool(grid_only)
        if grid_only:
            self.set_allow_list(False)
            self.set_mode("grid", emit=False)

    def set_size_only(self, size_only: bool) -> None:
        self._size_only = bool(size_only)
        if size_only:
            self.set_allow_list(False)

    def set_count(self, value) -> None:
        from steempeg.ui.widgets.view_mode_toggle import format_view_count

        if isinstance(value, str):
            self.lbl_count.setText(value)
        else:
            self.lbl_count.setText(format_view_count(value))

    def apply_density(self, dense: UiDensity) -> None:
        self._density = dense
        self.lbl_view.setVisible(not dense.compact)
        self._apply_label_style(self.lbl_view)
        self._apply_count_style(self.lbl_count)
        self.toggle_style_active, self.toggle_style_inactive = view_toggle_button_styles(
            dense
        )
        self.toggle_pill.setStyleSheet(
            "QFrame#CardSizeChromeHost { background: transparent; border: none; }"
        )
        self._apply_segment_metrics(dense)
        self._sync_buttons()

    def sync_styles_from_mode(self) -> None:
        self._sync_buttons()

    def _popup_current_key(self) -> str:
        if self._mode == "list" and self._allow_list:
            return _LIST_KEY
        return self._size

    def _on_popup_choice(self, key: str) -> None:
        if key == _LIST_KEY:
            self.set_mode("list")
            return
        # Size tile: leave List if needed, then apply size.
        self.set_size(key)

    def _open_size_popup(self) -> None:
        if self._popup is not None:
            try:
                self._popup.hide()
                self._popup.deleteLater()
            except RuntimeError:
                pass
        popup = _CardSizePopup(
            self._popup_current_key(),
            allow_list=self._allow_list and not self._size_only,
        )
        popup.choice_picked.connect(self._on_popup_choice)
        self._popup = popup
        popup.adjustSize()
        origin = self.btn_size.mapToGlobal(QPoint(0, self.btn_size.height() + 4))
        popup.move(origin)
        popup.show()

    def _glyph_px(self) -> int:
        h = toggle_segment_min_height(self._density)
        return max(16, min(22, h - 4))

    def _apply_segment_metrics(self, dense: UiDensity) -> None:
        h = toggle_segment_min_height(dense)
        glyph = self._glyph_px()
        side = max(h, glyph + 6)
        self.btn_size.setFixedSize(side, side)
        self.btn_size.setIconSize(QSize(glyph, glyph))
        self.btn_size.setStyleSheet(_size_ghost_button_style(radius=max(4, side // 4)))

    def _sync_buttons(self) -> None:
        glyph_px = self._glyph_px()
        side = max(toggle_segment_min_height(self._density), glyph_px + 6)
        self.btn_size.setFixedSize(side, side)
        self.btn_size.setStyleSheet(_size_ghost_button_style(radius=max(4, side // 4)))
        self.btn_size.setText("")
        list_on = self._mode == "list" and self._allow_list
        if list_on:
            self.btn_size.setIcon(view_mode_list_icon(glyph_px, color=_TOOLBAR_GLYPH))
            self.btn_size.setToolTip("View — List")
        else:
            self.btn_size.setIcon(
                card_size_grid_icon(self._size, glyph_px, color=_TOOLBAR_GLYPH)
            )
            self.btn_size.setToolTip(
                f"Card size — {CARD_SIZE_LABELS.get(self._size, 'Big')}"
            )
        self.btn_size.setIconSize(QSize(glyph_px, glyph_px))
        self.btn_view_list.hide()

    def _apply_label_style(self, lbl: QLabel) -> None:
        d = self._density
        lbl.setStyleSheet(
            f"color: #777777; font-weight: bold; font-size: {d.toolbar_label_font}px;"
            f" border: none; background: transparent; {_font_css()}"
        )

    def _apply_count_style(self, lbl: QLabel) -> None:
        d = self._density
        lbl.setStyleSheet(
            f"color: #888888; font-weight: bold; font-size: {d.toolbar_label_font}px;"
            f" border: none; background: transparent; {_font_css()}"
        )
