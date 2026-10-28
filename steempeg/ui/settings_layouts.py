"""Frames for the Settings window.

* Rail (stock): Render Settings-style section rail on the left, one page of
  section cards on the right.
* Scroll (Dev): every page stacked into one long scroll of cards, the rail
  jumps to a page and follows the scroll position.
* Tabs (Dev): the classic top tab bar with flat pages.

Pages are built once by ``SettingsDialog``; these frames only arrange them.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QByteArray, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.paths import get_resource_path
from steempeg.ui import design_tokens as tok
from steempeg.ui import ui_theme as ut

SETTINGS_LAYOUT_RAIL = "rail"
SETTINGS_LAYOUT_SCROLL = "scroll"
SETTINGS_LAYOUT_TABS = "tabs"
DEFAULT_SETTINGS_LAYOUT = SETTINGS_LAYOUT_RAIL

SETTINGS_LAYOUT_LABELS: tuple[tuple[str, str], ...] = (
    (SETTINGS_LAYOUT_RAIL, "Rail + cards (stock)"),
    (SETTINGS_LAYOUT_SCROLL, "One scroll"),
    (SETTINGS_LAYOUT_TABS, "Classic tabs"),
)

SECTION_TITLE_PROPERTY = "settingsSectionTitle"
CARD_OBJECT_NAME = "settingsCard"
RAIL_BUTTON_OBJECT_NAME = "settingsRailButton"

_RAIL_WIDTH = 188
_RAIL_ICON_PX = 16
# Room between the glyph and the page name. Qt's own icon gap is 4px.
_RAIL_ICON_GAP = 12
# Lucide stroke icons, one per settings page. PRO is the star and stays red.
_RAIL_GLYPHS = {
    "General": "settings_tab_general.svg",
    "Visual": "settings_tab_visual.svg",
    "Notifications": "settings_tab_notifications.svg",
    "Performance": "settings_tab_performance.svg",
    "Support": "settings_tab_support.svg",
    "PRO": "settings_tab_pro.svg",
    "Advanced": "settings_tab_advanced.svg",
}
# Thin resting outline, and the pure red the pill uses once PRO is the open page.
_PRO_BORDER = "#d64545"
_PRO_BORDER_HOT = "#ff2d2d"
_PRO_STAR = "#ff2d2d"
_STROKE_ICON_CACHE: dict[tuple[str, str, int], QIcon] = {}
_CARD_RADIUS = 12
# Scroll position slack so a page counts as current a bit before its title hits the top.
_ANCHOR_SLACK_PX = 24


def normalize_settings_layout(value: object | None) -> str:
    """Maps any stored or passed layout name to one of the three known frames."""
    text = str(value or "").strip().lower()
    if text in (SETTINGS_LAYOUT_RAIL, SETTINGS_LAYOUT_SCROLL, SETTINGS_LAYOUT_TABS):
        return text
    return DEFAULT_SETTINGS_LAYOUT


def mark_section_title(label: QLabel) -> None:
    """Flags a section title so the card regrouping knows where a new card starts."""
    label.setProperty(SECTION_TITLE_PROPERTY, True)


def settings_card_stylesheet() -> str:
    """Rounded section card on the active theme's settings-panel face."""
    p = ut.active_palette()
    return (
        f"QFrame#{CARD_OBJECT_NAME} {{ background-color: {p.bg_settings_panel}; "
        f"border: 1px solid {p.border_card}; border-radius: {_CARD_RADIUS}px; }}"
    )


def settings_rail_button_stylesheet() -> str:
    """Rail pills — the same pill the Render Settings neo-nav uses."""
    return ut.neo_nav_pill_stylesheet()


def settings_rail_pro_stylesheet() -> str:
    """PRO pill: a thin red outline at rest, pure red once that page is open.

    Other pills stay borderless until the purple selection ring. PRO is the
    exception on purpose. Padding gives back the pixel the thinner border
    would otherwise add, so the label stays in line with the other pills.
    """
    p = ut.active_palette()
    return f"""
        QPushButton {{
            background-color: transparent; color: {p.neo_nav_idle};
            border: 1px solid {_PRO_BORDER}; border-radius: 14px;
            padding: 11px 13px 11px 15px; text-align: left;
            font-size: 14px; font-weight: 700;
        }}
        QPushButton:hover {{
            background-color: {p.neo_nav_hover_bg};
            border: 1px solid {_PRO_BORDER};
            color: #e0e0e0;
        }}
        QPushButton:checked {{
            background-color: {p.neo_nav_checked_bg};
            border: 2px solid {_PRO_BORDER_HOT};
            color: #ffffff;
            padding: 10px 12px 10px 14px;
        }}
        QPushButton:checked:hover {{
            background-color: {p.neo_nav_checked_bg};
            border: 2px solid {_PRO_BORDER_HOT};
            color: #ffffff;
            padding: 10px 12px 10px 14px;
        }}
    """


def stroke_svg_icon(filename: str, color: str, size: int = _RAIL_ICON_PX) -> QIcon:
    """Render a Lucide stroke SVG (``currentColor``) into a tinted square icon."""
    key = (filename, color, int(size))
    cached = _STROKE_ICON_CACHE.get(key)
    if cached is not None:
        return cached
    icon = QIcon()
    try:
        with open(get_resource_path(filename), encoding="utf-8") as handle:
            svg = handle.read().replace("currentColor", color)
    except OSError:
        _STROKE_ICON_CACHE[key] = icon
        return icon
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        _STROKE_ICON_CACHE[key] = icon
        return icon
    # Paint into physical pixels, then mark the ratio. Setting the ratio
    # first makes the renderer draw past the logical box and clip the glyph.
    dpr = 2
    pix = QPixmap(size * dpr, size * dpr)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size * dpr, size * dpr))
    painter.end()
    pix.setDevicePixelRatio(dpr)
    for mode in (
        QIcon.Mode.Normal,
        QIcon.Mode.Disabled,
        QIcon.Mode.Active,
        QIcon.Mode.Selected,
    ):
        icon.addPixmap(pix, mode, QIcon.State.Off)
        icon.addPixmap(pix, mode, QIcon.State.On)
    _STROKE_ICON_CACHE[key] = icon
    return icon


class SettingsRailButton(QPushButton):
    """One settings-page pill: glyph, then the page name.

    The style's own icon sits on the line box, so it rides above the
    capitals. This button paints the glyph on the cap-height instead,
    with a wider gap before the name. The PRO star stays red. Every
    other glyph follows the label (idle, hover, selected).
    """

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(title, parent)
        self._pro_rail = title == "PRO"
        self._glyph_file = _RAIL_GLYPHS.get(title, "")
        self.setObjectName(RAIL_BUTTON_OBJECT_NAME)
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.toggled.connect(self.refresh_glyph)
        self.apply_chrome()

    def apply_chrome(self) -> None:
        """Re-apply the pill face and the glyph after a theme change."""
        if self._pro_rail:
            self.setStyleSheet(settings_rail_pro_stylesheet())
        else:
            self.setStyleSheet(settings_rail_button_stylesheet())
        self.refresh_glyph()

    def _label_color(self) -> str:
        """Text color for idle, hover, and the open page."""
        if self.isChecked():
            return "#ffffff"
        if self.underMouse():
            return "#e0e0e0"
        return ut.active_palette().neo_nav_idle

    def refresh_glyph(self, *_args) -> None:
        """Repaint so the glyph picks up the current label color."""
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        self.refresh_glyph()

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self.refresh_glyph()

    def paintEvent(self, event) -> None:  # noqa: N802
        """Draw the pill, then the glyph and the name on one line."""
        del event
        panel = QStyleOptionButton()
        self.initStyleOption(panel)
        panel.text = ""
        panel.icon = QIcon()
        painter = QPainter(self)
        self.style().drawControl(
            QStyle.ControlElement.CE_PushButton, panel, painter, self
        )
        self._paint_label(painter)
        painter.end()

    def _paint_label(self, painter: QPainter) -> None:
        """Place the glyph on the capital-letter line, then the page name."""
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        opt.icon = QIcon()
        opt.text = ""
        contents = self.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents, opt, self
        )
        font = self.font()
        metrics = QFontMetrics(font)
        icon = _RAIL_ICON_PX
        em = metrics.ascent() + metrics.descent()
        em_top = contents.top() + (contents.height() - em) / 2.0
        baseline = em_top + metrics.ascent()
        cap_mid = baseline - metrics.capHeight() / 2.0
        icon_y = int(round(cap_mid - icon / 2.0))
        icon_x = contents.left()
        color = self._label_color()
        glyph_color = _PRO_STAR if self._pro_rail else color
        if self._glyph_file:
            pix = stroke_svg_icon(self._glyph_file, glyph_color, icon).pixmap(
                QSize(icon, icon)
            )
            painter.drawPixmap(QRect(icon_x, icon_y, icon, icon), pix)
        text_rect = QRect(
            icon_x + icon + _RAIL_ICON_GAP,
            contents.top(),
            max(0, contents.width() - icon - _RAIL_ICON_GAP),
            contents.height(),
        )
        painter.setFont(font)
        painter.setPen(QColor(color))
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self.text(),
        )


def settings_page_title_stylesheet() -> str:
    """Big page title used between pages in the one-scroll frame."""
    return (
        f"color: {tok.TEXT_TITLE}; font-size: 16px; font-weight: bold; "
        f"background: transparent; font-family: {tok.FONT_APP};"
    )


def _start_card(page_layout: QVBoxLayout) -> QVBoxLayout:
    """Appends an empty section card to the page and returns its layout."""
    card = QFrame()
    card.setObjectName(CARD_OBJECT_NAME)
    card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    card.setStyleSheet(settings_card_stylesheet())
    card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(14, 12, 14, 14)
    card_layout.setSpacing(8)
    page_layout.addWidget(card)
    return card_layout


def regroup_page_into_cards(page_layout: QVBoxLayout) -> None:
    """Moves a flat settings page into cards, one card per section title.

    Stretches from the flat page are dropped; one stretch goes back at the end
    so short pages keep their cards at the top.
    """
    items = []
    while page_layout.count():
        items.append(page_layout.takeAt(0))

    card_layout: QVBoxLayout | None = None
    for item in items:
        widget = item.widget()
        child_layout = item.layout()
        if widget is None and child_layout is None:
            continue
        if widget is not None and widget.property(SECTION_TITLE_PROPERTY):
            card_layout = _start_card(page_layout)
            card_layout.addWidget(widget)
            continue
        if card_layout is None:
            card_layout = _start_card(page_layout)
        if widget is not None:
            card_layout.addWidget(widget)
        else:
            card_layout.addLayout(child_layout)
    page_layout.addStretch(1)


def _build_rail(titles: list[str]) -> tuple[QFrame, list[QPushButton]]:
    """Builds the left section rail with one checkable pill per page."""
    rail = QFrame()
    rail.setObjectName("settingsRail")
    rail.setFixedWidth(_RAIL_WIDTH)
    rail.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
    rail.setStyleSheet("QFrame#settingsRail { background: transparent; border: none; }")
    rail_layout = QVBoxLayout(rail)
    rail_layout.setContentsMargins(0, 4, 10, 4)
    rail_layout.setSpacing(6)
    rail_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    buttons: list[QPushButton] = []
    for title in titles:
        btn = SettingsRailButton(title, rail)
        rail_layout.addWidget(btn)
        buttons.append(btn)
    rail_layout.addStretch(1)
    return rail, buttons


class SettingsRailFrame(QWidget):
    """Stock frame: section rail on the left, the picked page of cards on the right.

    ``stack`` keeps the QTabWidget-like API (count / currentIndex / currentWidget)
    that Console mode pad navigation walks.
    """

    def __init__(
        self,
        pages: list[tuple[str, QWidget]],
        wrap_in_scroll: Callable[[QWidget], QScrollArea],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.rail, self.buttons = _build_rail([title for title, _page in pages])
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        for index, (_title, page) in enumerate(pages):
            self.stack.addWidget(wrap_in_scroll(page))
            self.buttons[index].clicked.connect(
                lambda _checked=False, i=index: self.stack.setCurrentIndex(i)
            )
        self.stack.currentChanged.connect(self._check_rail_button)
        if self.buttons:
            self.buttons[0].setChecked(True)

        layout.addWidget(self.rail)
        layout.addWidget(self.stack, 1)

    def _check_rail_button(self, index: int) -> None:
        """Keeps the rail pill in sync when the page changes from the pad or code."""
        if 0 <= index < len(self.buttons):
            self.buttons[index].setChecked(True)

    def apply_ui_theme_chrome(self) -> None:
        """Re-tints the rail pills after a theme change."""
        for btn in self.buttons:
            if isinstance(btn, SettingsRailButton):
                btn.apply_chrome()


class SettingsScrollFrame(QWidget):
    """Dev frame: all pages in one long scroll, the rail jumps and follows along."""

    def __init__(
        self,
        pages: list[tuple[str, QWidget]],
        wrap_in_scroll: Callable[[QWidget], QScrollArea],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.rail, self.buttons = _build_rail([title for title, _page in pages])

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        self._titles: list[QLabel] = []
        for title, page in pages:
            title_label = QLabel(title)
            title_label.setObjectName("settingsPageTitle")
            title_label.setStyleSheet(settings_page_title_stylesheet())
            title_label.setContentsMargins(12, 14, 12, 0)
            body_layout.addWidget(title_label)
            body_layout.addWidget(page)
            self._titles.append(title_label)
        body_layout.addStretch(1)

        self._scroll = wrap_in_scroll(body)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._scroll)

        for index, btn in enumerate(self.buttons):
            btn.clicked.connect(lambda _checked=False, i=index: self.scroll_to_page(i))
        self._scroll.verticalScrollBar().valueChanged.connect(self._follow_scroll)
        if self.buttons:
            self.buttons[0].setChecked(True)

        layout.addWidget(self.rail)
        layout.addWidget(self.stack, 1)

    def scroll_to_page(self, index: int) -> None:
        """Scrolls so the page title sits at the top, then lights its rail pill."""
        if not 0 <= index < len(self._titles):
            return
        bar = self._scroll.verticalScrollBar()
        bar.setValue(min(bar.maximum(), self._titles[index].y()))
        self.buttons[index].setChecked(True)

    def _follow_scroll(self, value: int) -> None:
        """Lights the rail pill of the page currently at the top of the scroll."""
        if not self._titles:
            return
        current = 0
        for index, title_label in enumerate(self._titles):
            if title_label.y() - _ANCHOR_SLACK_PX <= value:
                current = index
        bar = self._scroll.verticalScrollBar()
        if bar.maximum() > 0 and value >= bar.maximum():
            current = len(self._titles) - 1
        self.buttons[current].setChecked(True)

    def apply_ui_theme_chrome(self) -> None:
        """Re-tints the rail pills and page titles after a theme change."""
        for btn in self.buttons:
            if isinstance(btn, SettingsRailButton):
                btn.apply_chrome()
        title_qss = settings_page_title_stylesheet()
        for title_label in self._titles:
            title_label.setStyleSheet(title_qss)
