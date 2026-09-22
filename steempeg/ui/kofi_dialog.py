"""Ko-fi support dialog — cozy tip-jar card (beige / white, not dark chrome)."""
from __future__ import annotations

import logging
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

KOFI_URL = "https://ko-fi.com/milloriin"  # fallback; prefer resolve_kofi_url()
KOFI_MARK = "kofi.png"

# Ko-fi dashboard vibe — warm cream plate, soft charcoal type.
_CREAM = "#F9F5F0"
_CARD = "#FFFFFF"
_INK = "#3A342E"
_MUTED = "#8A8178"
_LINE = "#E8DFD4"
_BTN = "#FFF9F3"
_BTN_HOVER = "#F3EBE2"
_BTN_BORDER = "#E0D5C8"
_COZY_FALLBACK = '"Candara", "Calibri", "Segoe UI Variable", "Segoe UI", sans-serif'

_fredoka_family: str | None = None
_fredoka_loaded = False

# Static weights under assets/fonts/fredoka/ (SIL OFL — see OFL.txt).
_FREDOKA_FILES = (
    "fonts/fredoka/Fredoka-Regular.ttf",
    "fonts/fredoka/Fredoka-Medium.ttf",
    "fonts/fredoka/Fredoka-SemiBold.ttf",
    "fonts/fredoka/Fredoka-Bold.ttf",
)


def register_bundled_fredoka() -> str:
    """Load bundled Fredoka into QFontDatabase; return family name (or '')."""
    global _fredoka_family, _fredoka_loaded
    if _fredoka_loaded:
        return _fredoka_family or ""
    _fredoka_loaded = True
    try:
        from steempeg.infra.paths import get_resource_path
    except Exception:
        return ""

    families: list[str] = []
    seen: set[str] = set()
    for rel in _FREDOKA_FILES:
        path = get_resource_path(rel)
        try:
            import os

            if not os.path.isfile(path):
                continue
            fid = QFontDatabase.addApplicationFont(path)
        except Exception:
            logging.debug("Fredoka load failed: %s", rel, exc_info=True)
            continue
        if fid < 0:
            continue
        try:
            names = QFontDatabase.applicationFontFamilies(fid)
        except Exception:
            names = []
        for name in names:
            if name and name not in seen:
                seen.add(name)
                families.append(name)

    if families:
        preferred = next((n for n in families if n.lower() == "fredoka"), families[0])
        _fredoka_family = preferred
        return preferred
    return ""


def _cozy_stylesheet(*, support_font: str) -> str:
    support_css = f'"{support_font}", {_COZY_FALLBACK}' if support_font else _COZY_FALLBACK
    return f"""
    QWidget#KofiPlate {{
        background-color: {_CREAM};
        border: 1px solid {_LINE};
        border-radius: 22px;
    }}
    QWidget#KofiCard {{
        background-color: {_CARD};
        border: 1px solid {_LINE};
        border-radius: 18px;
    }}
    QWidget#KofiMarkBadge {{
        background-color: {_LINE};
        border: none;
        border-radius: 64px;
    }}
    QLabel {{
        background: transparent;
        color: {_INK};
        font-family: {_COZY_FALLBACK};
    }}
    QLabel#KofiTitle {{
        color: {_INK};
        font-size: 30px;
        font-weight: 700;
        letter-spacing: 0.3px;
    }}
    QLabel#KofiPitch {{
        color: {_INK};
        font-size: 15px;
        font-weight: 500;
    }}
    QLabel#KofiDim {{
        color: {_MUTED};
        font-size: 12px;
        font-weight: 500;
    }}
    QPushButton#KofiSupportBtn {{
        background-color: {_BTN};
        color: {_INK};
        border: 1px solid {_BTN_BORDER};
        border-radius: 22px;
        padding: 10px 20px 10px 14px;
        font-family: {support_css};
        font-size: 18px;
        font-weight: 700;
        min-height: 46px;
        outline: none;
    }}
    QPushButton#KofiSupportBtn:hover {{
        background-color: {_BTN_HOVER};
        border: 1px solid #D4C8B8;
    }}
    QPushButton#KofiSupportBtn:pressed {{
        background-color: #EDE4D8;
    }}
    QPushButton#KofiCloseBtn {{
        background-color: transparent;
        color: {_MUTED};
        border: 1px solid {_LINE};
        border-radius: 16px;
        padding: 6px 16px;
        font-family: {_COZY_FALLBACK};
        font-size: 13px;
        font-weight: 600;
        min-height: 30px;
        outline: none;
    }}
    QPushButton#KofiCloseBtn:hover {{
        background-color: {_CREAM};
        color: {_INK};
        border: 1px solid {_BTN_BORDER};
    }}
    QPushButton#KofiCloseBtn:pressed {{
        background-color: {_BTN_HOVER};
    }}
"""


def show_kofi_dialog(parent=None) -> None:
    """Frameless cozy Donate Me card — cream plate, cup mark, soft Support CTA."""
    from steempeg.services.kofi_remote import display_kofi_host, resolve_kofi_url
    from steempeg.ui.icon_assets import load_pixmap
    from steempeg.ui.icon_utils import apply_square_icon
    from steempeg.ui.ui_density import scaled_dialog_size

    # Prefer live Pages meta so a renamed Ko-fi slug updates without a release.
    kofi_url = resolve_kofi_url(refresh=True, timeout=2.5)
    kofi_host = display_kofi_host(kofi_url)

    fredoka = register_bundled_fredoka()

    dialog = QDialog(parent)
    dialog.setObjectName("SteempegKofiDialog")
    dialog.setWindowFlag(Qt.WindowType.FramelessWindowHint)
    # Rounded cream plate paints itself; dialog stays clear so corners aren't square.
    dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.setFixedSize(*scaled_dialog_size(420, 430, parent=parent))
    dialog.setStyleSheet(_cozy_stylesheet(support_font=fredoka))

    shell = QVBoxLayout(dialog)
    shell.setContentsMargins(0, 0, 0, 0)
    shell.setSpacing(0)

    # Opaque cream shell — fixes the “stuck” dark/purple void behind the card.
    plate = QWidget(dialog)
    plate.setObjectName("KofiPlate")
    plate.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    shell.addWidget(plate)

    plate_lay = QVBoxLayout(plate)
    plate_lay.setContentsMargins(14, 14, 14, 8)
    plate_lay.setSpacing(0)

    card = QWidget(plate)
    card.setObjectName("KofiCard")
    card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    plate_lay.addWidget(card)

    content = QVBoxLayout(card)
    content.setContentsMargins(32, 36, 32, 24)
    content.setSpacing(12)

    logo_row = QHBoxLayout()
    logo_row.addStretch(1)
    # Soft plate-border disc behind the cup mark (roomy — handle breaks roundness).
    mark_badge = QWidget()
    mark_badge.setObjectName("KofiMarkBadge")
    mark_badge.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    mark_badge.setFixedSize(128, 128)
    badge_lay = QVBoxLayout(mark_badge)
    badge_lay.setContentsMargins(16, 16, 16, 16)
    badge_lay.setSpacing(0)
    logo = QLabel()
    logo.setFixedSize(96, 96)
    logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    apply_square_icon(logo, load_pixmap(KOFI_MARK, 96), 96)
    badge_lay.addWidget(logo, 0, Qt.AlignmentFlag.AlignCenter)
    logo_row.addWidget(mark_badge)
    logo_row.addStretch(1)
    content.addLayout(logo_row)
    content.addSpacing(4)

    title = QLabel("Donate Me!")
    title.setObjectName("KofiTitle")
    title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    title_font = QFont()
    if fredoka:
        title_font.setFamily(fredoka)
    else:
        title_font.setFamilies(["Candara", "Calibri", "Segoe UI Variable", "Segoe UI"])
    title_font.setPointSize(28)
    title_font.setWeight(QFont.Weight.Bold)
    title.setFont(title_font)
    content.addWidget(title)

    pitch = QLabel(
        "If Steempeg saves you time, a small tip keeps the lights on — "
        "and the developer in caffeine. No pressure, just coffee."
    )
    pitch.setObjectName("KofiPitch")
    pitch.setWordWrap(True)
    pitch.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    pitch_font = QFont()
    pitch_font.setFamilies(["Candara", "Calibri", "Segoe UI Variable", "Segoe UI"])
    pitch_font.setPointSize(13)
    pitch_font.setWeight(QFont.Weight.Medium)
    pitch.setFont(pitch_font)
    content.addWidget(pitch)

    dim = QLabel(kofi_host)
    dim.setObjectName("KofiDim")
    dim.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    content.addWidget(dim)

    content.addStretch(1)
    content.addSpacing(8)

    btn_open = QPushButton("  Support on Ko-fi")
    btn_open.setObjectName("KofiSupportBtn")
    btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_open.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    # Fredoka Bold, a notch larger / heavier than Close (14px / DemiBold).
    support_font = QFont()
    if fredoka:
        support_font.setFamily(fredoka)
    else:
        support_font.setFamilies(["Candara", "Calibri", "Segoe UI"])
    support_font.setPointSize(17)
    support_font.setWeight(QFont.Weight.Bold)
    btn_open.setFont(support_font)
    cup = load_pixmap(KOFI_MARK, 28)
    if not cup.isNull():
        btn_open.setIcon(QIcon(cup))
        btn_open.setIconSize(cup.size())
    btn_open.clicked.connect(lambda: webbrowser.open(kofi_url))
    support_row = QHBoxLayout()
    support_row.addStretch(1)
    support_row.addWidget(btn_open)
    support_row.addStretch(1)
    content.addLayout(support_row)

    # Close sits on the cream plate — bottom-right, tight to the edge.
    btn_close = QPushButton("Close")
    btn_close.setObjectName("KofiCloseBtn")
    btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_close.clicked.connect(dialog.accept)
    close_row = QHBoxLayout()
    close_row.setContentsMargins(4, 6, 2, 2)
    close_row.setSpacing(0)
    close_row.addStretch(1)
    close_row.addWidget(btn_close, 0, Qt.AlignmentFlag.AlignRight)
    plate_lay.addLayout(close_row)

    dialog.exec()
