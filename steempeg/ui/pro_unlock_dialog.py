"""Steempeg PRO unlock ask — About-style card, exact Ko-fi Support CTA."""
from __future__ import annotations

import webbrowser
from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.paths import get_resource_path
from steempeg.ui.kofi_dialog import KOFI_MARK, register_bundled_fredoka
from steempeg.ui.widgets.pro_badge import ProBadge

ProUnlockChoice = Literal["donate", "cancel", "dismiss"]

# Exact Ko-fi Support CTA tokens (must stay in lockstep with kofi_dialog.py).
_KOFI_BTN = "#FFF9F3"
_KOFI_BTN_HOVER = "#F3EBE2"
_KOFI_BTN_BORDER = "#E0D5C8"
_KOFI_INK = "#3A342E"
_COZY_FALLBACK = '"Candara", "Calibri", "Segoe UI Variable", "Segoe UI", sans-serif'


def _unlock_extra_stylesheet(*, support_font: str) -> str:
    """Exact ``KofiSupportBtn`` rules + About Close for Cancel."""
    from steempeg.ui import design_tokens as tok
    from steempeg.ui import ui_theme as ut

    support_css = f'"{support_font}", {_COZY_FALLBACK}' if support_font else _COZY_FALLBACK
    # About Close is a bare QPushButton under about_secondary_button_stylesheet.
    return ut.about_secondary_button_stylesheet() + f"""
    QLabel#ProUnlockHeadline {{
        color: #ffffff;
        font-size: 16px;
        font-weight: bold;
        font-family: {tok.FONT_APP};
        background: transparent;
    }}
    QLabel#ProUnlockPitch {{
        color: #888888;
        font-size: 13px;
        font-family: {tok.FONT_APP};
        background: transparent;
    }}
    QPushButton#KofiSupportBtn {{
        background-color: {_KOFI_BTN};
        color: {_KOFI_INK};
        border: 1px solid {_KOFI_BTN_BORDER};
        border-radius: 22px;
        padding: 10px 20px 10px 14px;
        font-family: {support_css};
        font-size: 18px;
        font-weight: 700;
        min-height: 46px;
        outline: none;
    }}
    QPushButton#KofiSupportBtn:hover {{
        background-color: {_KOFI_BTN_HOVER};
        border: 1px solid #D4C8B8;
    }}
    QPushButton#KofiSupportBtn:pressed {{
        background-color: #EDE4D8;
    }}
"""


def ask_steempeg_pro_unlock(parent=None) -> ProUnlockChoice:
    """Show the free-PRO tip dialog (About plate + Ko-fi Support button).

    Returns:
      ``donate`` — opened Ko-fi (caller should still unlock PRO)
      ``cancel`` — skip donation, unlock PRO anyway (it is free)
      ``dismiss`` — Escape / closed without a choice; do not unlock
    """
    from steempeg.services.kofi_remote import display_kofi_host, resolve_kofi_url
    from steempeg.ui import ui_theme as ut
    from steempeg.ui.icon_assets import load_pixmap
    from steempeg.ui.icon_utils import apply_square_icon, app_logo_pixmap
    from steempeg.ui.ui_density import scaled_dialog_size

    kofi_url = resolve_kofi_url(refresh=True, timeout=2.5)
    kofi_host = display_kofi_host(kofi_url)

    fredoka = register_bundled_fredoka()
    choice: dict[str, ProUnlockChoice] = {"value": "dismiss"}

    dialog = QDialog(parent)
    dialog.setObjectName("SteempegProUnlockDialog")
    dialog.setWindowFlag(Qt.WindowType.FramelessWindowHint)
    dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.setFixedSize(*scaled_dialog_size(440, 480, parent=parent))
    dialog.setStyleSheet(
        ut.about_dialog_stylesheet(pro=True) + _unlock_extra_stylesheet(support_font=fredoka)
    )

    shell = QVBoxLayout(dialog)
    shell.setContentsMargins(0, 0, 0, 0)
    shell.setSpacing(0)

    card = QWidget(dialog)
    card.setObjectName("AboutCard")
    card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    shell.addWidget(card)

    content = QVBoxLayout(card)
    content.setContentsMargins(32, 32, 32, 24)
    content.setSpacing(10)

    logo_row = QHBoxLayout()
    logo_row.addStretch(1)
    logo = QLabel()
    logo.setFixedSize(110, 110)
    logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    # Circular crop — logo.png is a disc on an opaque square (black corners).
    from steempeg.ui.icon_shape import ICON_SHAPE_CIRCLE, shaped_game_icon_pixmap

    pix = app_logo_pixmap(110, dpr=1.0)
    if pix is None or pix.isNull():
        pix = QPixmap(get_resource_path("logo.png"))
    if pix is not None and not pix.isNull():
        pix = shaped_game_icon_pixmap(pix, 110, ICON_SHAPE_CIRCLE)
    apply_square_icon(logo, pix, 110)
    logo_row.addWidget(logo)
    logo_row.addStretch(1)
    content.addLayout(logo_row)
    content.addSpacing(4)

    brand_row = QHBoxLayout()
    brand_row.setSpacing(8)
    brand_row.addStretch(1)
    brand = QLabel("Steempeg")
    brand.setObjectName("AboutTitle")
    brand.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    brand_row.addWidget(brand, 0, Qt.AlignmentFlag.AlignVCenter)
    brand_row.addWidget(ProBadge(size="splash", parent=card), 0, Qt.AlignmentFlag.AlignVCenter)
    brand_row.addStretch(1)
    content.addLayout(brand_row)

    headline = QLabel("Steempeg PRO is Free")
    headline.setObjectName("ProUnlockHeadline")
    headline.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    content.addWidget(headline)

    pitch = QLabel(
        "If you can, a small tip on Ko-fi helps keep this project going — "
        "thank you in advance."
    )
    pitch.setObjectName("ProUnlockPitch")
    pitch.setWordWrap(True)
    pitch.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    content.addWidget(pitch)

    dim = QLabel(kofi_host)
    dim.setObjectName("ProUnlockPitch")
    dim.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    content.addWidget(dim)

    content.addStretch(1)
    content.addSpacing(8)

    # Exact Ko-fi dialog Support CTA (object name + metrics + Fredoka).
    btn_donate = QPushButton("  Support on Ko-fi")
    btn_donate.setObjectName("KofiSupportBtn")
    btn_donate.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_donate.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    support_font = QFont()
    if fredoka:
        support_font.setFamily(fredoka)
    else:
        support_font.setFamilies(["Candara", "Calibri", "Segoe UI"])
    support_font.setPointSize(17)
    support_font.setWeight(QFont.Weight.Bold)
    btn_donate.setFont(support_font)
    cup = load_pixmap(KOFI_MARK, 28)
    if not cup.isNull():
        btn_donate.setIcon(QIcon(cup))
        btn_donate.setIconSize(cup.size())

    def _donate() -> None:
        choice["value"] = "donate"
        try:
            webbrowser.open(kofi_url)
        except Exception:
            pass
        dialog.accept()

    btn_donate.clicked.connect(_donate)
    donate_row = QHBoxLayout()
    donate_row.addStretch(1)
    donate_row.addWidget(btn_donate)
    donate_row.addStretch(1)
    content.addLayout(donate_row)

    # About Close — bare QPushButton under about_secondary_button_stylesheet.
    btn_cancel = QPushButton("Cancel")
    btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_cancel.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def _cancel() -> None:
        choice["value"] = "cancel"
        dialog.reject()

    btn_cancel.clicked.connect(_cancel)
    cancel_row = QHBoxLayout()
    cancel_row.setContentsMargins(0, 6, 0, 0)
    cancel_row.addStretch(1)
    cancel_row.addWidget(btn_cancel)
    cancel_row.addStretch(1)
    content.addLayout(cancel_row)

    dialog.exec()
    return choice["value"]
