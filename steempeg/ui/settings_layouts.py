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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

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

_RAIL_WIDTH = 176
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
        btn = QPushButton(title)
        btn.setObjectName(RAIL_BUTTON_OBJECT_NAME)
        btn.setCheckable(True)
        btn.setAutoExclusive(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setStyleSheet(settings_rail_button_stylesheet())
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
        qss = settings_rail_button_stylesheet()
        for btn in self.buttons:
            btn.setStyleSheet(qss)


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
        qss = settings_rail_button_stylesheet()
        for btn in self.buttons:
            btn.setStyleSheet(qss)
        title_qss = settings_page_title_stylesheet()
        for title_label in self._titles:
            title_label.setStyleSheet(title_qss)
