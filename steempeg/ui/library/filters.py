"""Filter popup for the library: a date/time range picker plus game and type filters.

DateGroup and TimeGroup are small composite pickers built from BlockCombo; FilterMenu
is the popup itself. It receives the owning application via gather_statistics(app_window)
rather than importing it, so this module stays free of any back-reference to the app.
"""
import os
import re
import tempfile
from datetime import datetime

from PySide6.QtCore import QEvent, Qt, QDate, QDateTime, QPoint, QTime, QSize
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.locale_time import parse_clip_datetime_text, qt_time_display_format
from steempeg.core.dash.health import ClipHealth
from steempeg.ui.icon_assets import health_icon
from steempeg.ui.widgets import BlockCombo, FlowLayout

_CLIP_HEALTH_ROLE = Qt.UserRole + 2
_CLIP_CURED_ROLE = Qt.UserRole + 4


def _row_display_health_level(item) -> str:
    if item and item.data(_CLIP_CURED_ROLE):
        return ClipHealth.CURED.value
    return item.data(_CLIP_HEALTH_ROLE) or ClipHealth.HEALTHY.value


class DateGroup(QWidget):
    def __init__(self):
        super().__init__()
        l = QHBoxLayout(self)
        l.setContentsMargins(0,0,0,0); l.setSpacing(4)
        self.d = BlockCombo([f"{i:02d}" for i in range(1,32)])
        self.m = BlockCombo(["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"])
        self.y = BlockCombo([str(y) for y in range(2000, 2030)])
        l.addWidget(self.d); l.addWidget(self.m); l.addWidget(self.y)
        
        self.d.setFixedWidth(36)  # Narrow day
        self.m.setFixedWidth(46)  # Month
        self.y.setFixedWidth(56)
        self.m.currentTextChanged.connect(self.upd)
        self.y.currentTextChanged.connect(self.upd)
        
    def upd(self):
        if not self.y.is_valid() or not self.m.is_valid(): return 
        
        month_idx = ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"].index(self.m.currentText().lower()) + 1
        days = QDate(int(self.y.currentText()), month_idx, 1).daysInMonth()
        
        cur = self.d.currentText()
        self.d.blockSignals(True)
        self.d.clear()
        self.d.addItems([f"{i:02d}" for i in range(1, days+1)])
        
        if cur.isdigit() and 1 <= int(cur) <= days:
            self.d.setCurrentText(f"{int(cur):02d}")
        elif cur.isdigit() and int(cur) > days:
            self.d.setCurrentText(f"{days:02d}")
        else:
            self.d.setCurrentText(cur)
            
        self.d.validate_text(self.d.currentText())
        self.d.blockSignals(False)
        
    def set_dt(self, qd):
        self.y.setCurrentText(str(qd.year()))
        self.m.setCurrentText(["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][qd.month()-1])
        self.d.setCurrentText(f"{qd.day():02d}")

class TimeGroup(QWidget):
    def __init__(self, mode="time"): 
        super().__init__()
        l = QHBoxLayout(self)
        l.setContentsMargins(0,0,0,0); l.setSpacing(4)
        self.mode = mode
        if mode == "time":
            self.h = BlockCombo([f"{i:02d}" for i in range(1,13)])
            self.m = BlockCombo([f"{i:02d}" for i in range(60)])
            self.ap = BlockCombo(["AM", "PM"])
            l.addWidget(self.h); l.addWidget(QLabel(":")); l.addWidget(self.m); l.addWidget(self.ap)
            self.h.setFixedWidth(36)
            self.m.setFixedWidth(36)
            self.ap.setFixedWidth(40)
        else:
            self.h = BlockCombo([f"{i:02d}" for i in range(100)]) 
            self.m = BlockCombo([f"{i:02d}" for i in range(60)])
            self.s = BlockCombo([f"{i:02d}" for i in range(60)])
            l.addWidget(self.h); l.addWidget(QLabel(":")); l.addWidget(self.m); l.addWidget(QLabel(":")); l.addWidget(self.s)
            self.h.setFixedWidth(36)
            self.m.setFixedWidth(36)
            self.s.setFixedWidth(36)
            

    def set_t(self, qt):
        h = qt.hour()
        self.ap.setCurrentText("PM" if h >= 12 else "AM")
        h = h % 12
        self.h.setCurrentText(f"{12 if h==0 else h:02d}")
        self.m.setCurrentText(f"{qt.minute():02d}")

    def set_sec(self, sec):
        self.h.setCurrentText(f"{sec//3600:02d}")
        self.m.setCurrentText(f"{(sec%3600)//60:02d}")
        self.s.setCurrentText(f"{sec%60:02d}")



class FilterMenu(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # --- UI TWEAK: Slightly widened the menu to give the capsules a more spacious look ---
        self.setFixedWidth(460) 

        self.container = QFrame(self)
        self.container.setObjectName("MainFilterContainer")
        self.container.setStyleSheet("""
            QFrame#MainFilterContainer { background-color: #252525; border: 1px solid #3d3d3d; border-radius: 16px; }
        """)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10) 
        main_layout.addWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Sections are stacked directly; only the Games list scrolls (see below).
        scroll_layout = layout

        self._drag_active = False
        self._drag_layout = None
        self._drag_btn = None
        # Remembers each type's checked state across rebuilds, so a type that
        # disappears (its game was deselected) returns with the SAME state it had,
        # instead of being force-checked or force-cleared.
        self._type_checked_memory = {}

        # --- 1. SUPER HELPER: CREATE CATEGORY MEGA-CAPSULES ---
        def create_category_capsule(title_text, content_widget):
            capsule = QFrame()
            capsule.setObjectName("CategoryCapsule")
            capsule.setStyleSheet("""
                QFrame#CategoryCapsule {
                    background-color: #2d2d2d;
                    border: 1px solid #383838;
                    border-radius: 14px;
                }
                QLabel#CategoryTitle {
                    color: #cccccc;
                    border: none;
                    background: transparent;
                    font-size: 13px;
                    font-weight: bold;
                    font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji';
                }
            """)
            cap_layout = QVBoxLayout(capsule)
            cap_layout.setContentsMargins(12, 12, 12, 12)
            cap_layout.setSpacing(8)

            title_lbl = QLabel(title_text)
            title_lbl.setObjectName("CategoryTitle")

            cap_layout.addWidget(title_lbl)
            cap_layout.addWidget(content_widget)
            return capsule

        # --- GAMES CAPSULE (the ONLY scrollable section) ---
        self.games_container = QWidget()
        self.games_container.setStyleSheet("background: transparent;")
        self.games_layout = FlowLayout()
        self.games_container.setLayout(self.games_layout)
        self.games_container.setMouseTracking(True)
        self.games_container.installEventFilter(self)

        self._games_scroll = QScrollArea()
        self._games_scroll.setWidgetResizable(True)
        self._games_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._games_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._games_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._games_scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { border: none; background: transparent; width: 8px; margin: 2px; }
            QScrollBar::handle:vertical { background: #4e4e4e; min-height: 24px; border-radius: 4px; }
            QScrollBar::handle:vertical:hover { background: #b29ae7; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)
        self._games_scroll.setWidget(self.games_container)
        scroll_layout.addWidget(create_category_capsule("🎮 Games:", self._games_scroll))

        # --- TYPE CAPSULE ---
        self.types_container = QWidget()
        self.types_layout = FlowLayout()
        self.types_container.setLayout(self.types_layout)
        scroll_layout.addWidget(create_category_capsule("📂 Type:", self.types_container))
        self.types_container.setMouseTracking(True)
        self.types_container.installEventFilter(self)

        # --- HEALTH CAPSULE (static three-tier classification) ---
        self.health_container = QWidget()
        self.health_layout = FlowLayout()
        self.health_container.setLayout(self.health_layout)
        scroll_layout.addWidget(create_category_capsule("💚 Health:", self.health_container))
        self.health_container.setMouseTracking(True)
        self.health_container.installEventFilter(self)

        _HEALTH_PILL_TEXT = {
            ClipHealth.HEALTHY: "Healthy",
            ClipHealth.DEGRADED: "Issues",
            ClipHealth.DEAD: "Dead",
            ClipHealth.CURED: "Cured",
        }
        for level in (ClipHealth.HEALTHY, ClipHealth.DEGRADED, ClipHealth.DEAD, ClipHealth.CURED):
            btn = QPushButton(f" {_HEALTH_PILL_TEXT[level]}")
            btn.setIcon(health_icon(level, 14))
            btn.setIconSize(QSize(14, 14))
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._PILL_BTN_STYLE)
            btn.setProperty("health_level", level.value)
            btn.clicked.connect(self.update_live_count)
            self.health_layout.addWidget(btn)

        # --- 3. SMART INPUTS STYLE (Clean, small pills + Rounded Spinners) ---
        
        # 1. Generate paths in the system's temporary folder.
        temp_dir = tempfile.gettempdir()
        up_path = os.path.join(temp_dir, "smpeg_up.png").replace('\\', '/')
        down_path = os.path.join(temp_dir, "smpeg_down.png").replace('\\', '/')

        # 2. Making the program draw the icons itself!
        pix = QPixmap(16, 16)
        
        # Drawing the perfect upward-flicked eyeliner
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon([QPoint(3, 11), QPoint(8, 5), QPoint(13, 11)])
        p.end()
        pix.save(up_path, "PNG")

        # Drawing the perfect downward-sloping winged liner
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon([QPoint(3, 5), QPoint(8, 11), QPoint(13, 5)])
        p.end()
        pix.save(down_path, "PNG")

        # 3. SEWING THEM INTO STYLES
        raw_style = """
            QDateEdit, QTimeEdit {
                background-color: #383838;
                color: #ffffff;
                border: 2px solid #444444;
                border-radius: 8px;
                font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
                font-weight: bold;
                font-size: 13px;
                padding: 4px 10px;
                min-height: 24px;
            }
            QDateEdit:hover, QTimeEdit:hover { background-color: #404040; border: 2px solid #6b5a8e; }
            QDateEdit:focus, QTimeEdit:focus { background-color: #3a324a; border: 2px solid #b29ae7; }
            
            
            QDateEdit::drop-down {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 24px;
                border-left: 1px solid #444444;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                background-color: #333333;
            }
            QTimeEdit::up-button {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 20px;
                border-left: 1px solid #444444;
                border-bottom: 1px solid #444444;
                border-top-right-radius: 6px;
                background-color: #333333;
            }
            QTimeEdit::down-button {
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 20px;
                border-left: 1px solid #444444;
                border-bottom-right-radius: 6px;
                background-color: #333333;
            }
            QDateEdit::drop-down:hover, QTimeEdit::up-button:hover, QTimeEdit::down-button:hover { background-color: #6b5a8e; }
            QDateEdit::drop-down:pressed, QTimeEdit::up-button:pressed, QTimeEdit::down-button:pressed { background-color: #b29ae7; }
            

            QTimeEdit::up-arrow {
                image: url("UP_ARROW_PATH");
                width: 10px; height: 10px;
            }
            QTimeEdit::down-arrow, QDateEdit::down-arrow {
                image: url("DOWN_ARROW_PATH");
                width: 10px; height: 10px;
            }
            

            QCalendarWidget QWidget { alternate-background-color: #2d2d2d; background-color: #252525; color: white; }
            QCalendarWidget QToolButton { color: white; background-color: #383838; border-radius: 4px; padding: 2px; }
            QCalendarWidget QToolButton:hover { background-color: #6b5a8e; }
            QCalendarWidget QAbstractItemView:enabled { color: white; background-color: #252525; selection-background-color: #6b5a8e; selection-color: white; border-radius: 4px; }
        """
        
        smart_input_style = raw_style.replace("UP_ARROW_PATH", up_path).replace("DOWN_ARROW_PATH", down_path)
        self._filter_date_arrow_up = up_path
        self._filter_date_arrow_down = down_path
        self._date_time_input_style = smart_input_style

        # --- DATE CAPSULE (WITH CALENDAR POPUP & ICONS) ---
        date_container = QWidget()
        date_layout = QHBoxLayout(date_container)
        date_layout.setContentsMargins(0, 0, 0, 0)
        date_layout.setSpacing(8)
        
        self.input_min_date = QDateEdit()
        self.input_max_date = QDateEdit()
        
        for de in (self.input_min_date, self.input_max_date):
            de.setCalendarPopup(True)
            de.setStyleSheet(smart_input_style)
            de.setCursor(Qt.PointingHandCursor)
            de.setDateRange(QDate(2020, 1, 1), QDate(2050, 12, 31))
        
        # Aesthetic icons right in the text
        lbl_from_d = QLabel("📅 From:"); lbl_from_d.setStyleSheet("color: #888888; font-weight: bold;")
        lbl_to_d = QLabel("📅 To:"); lbl_to_d.setStyleSheet("color: #888888; font-weight: bold;")
        
        date_layout.addWidget(lbl_from_d)
        date_layout.addWidget(self.input_min_date)
        date_layout.addSpacing(15) 
        date_layout.addWidget(lbl_to_d)
        date_layout.addWidget(self.input_max_date)
        date_layout.addStretch() 
        scroll_layout.addWidget(create_category_capsule("📅 Date:", date_container))

        # --- TIME CAPSULE (WITH AM/PM & ICONS) ---
        time_c_container = QWidget()
        time_c_layout = QHBoxLayout(time_c_container)
        time_c_layout.setContentsMargins(0, 0, 0, 0)
        time_c_layout.setSpacing(8)
        
        self.input_min_time = QTimeEdit()
        self.input_max_time = QTimeEdit()
        
        for te in (self.input_min_time, self.input_max_time):
            te.setDisplayFormat(qt_time_display_format())
            te.setStyleSheet(smart_input_style)
            te.setCursor(Qt.PointingHandCursor)
        
        lbl_from_t = QLabel("🕒 From:"); lbl_from_t.setStyleSheet("color: #888888; font-weight: bold;")
        lbl_to_t = QLabel("🕒 To:"); lbl_to_t.setStyleSheet("color: #888888; font-weight: bold;")
        
        time_c_layout.addWidget(lbl_from_t)
        time_c_layout.addWidget(self.input_min_time)
        time_c_layout.addSpacing(15)
        time_c_layout.addWidget(lbl_to_t)
        time_c_layout.addWidget(self.input_max_time)
        time_c_layout.addStretch()
        scroll_layout.addWidget(create_category_capsule("⏰ Time of creation:", time_c_container))

        # --- DURATION CAPSULE (HH:MM:SS) ---
        dur_container = QWidget()
        dur_layout = QHBoxLayout(dur_container)
        dur_layout.setContentsMargins(0, 0, 0, 0)
        dur_layout.setSpacing(8)
        
        self.input_min_dur = QTimeEdit()
        self.input_max_dur = QTimeEdit()
        
        for de in (self.input_min_dur, self.input_max_dur):
            de.setDisplayFormat("HH:mm:ss")
            de.setStyleSheet(smart_input_style)
            de.setCursor(Qt.PointingHandCursor)
        
        lbl_min_dur = QLabel("⏱ Min:"); lbl_min_dur.setStyleSheet("color: #888888; font-weight: bold;")
        lbl_max_dur = QLabel("⏱ Max:"); lbl_max_dur.setStyleSheet("color: #888888; font-weight: bold;")
        
        dur_layout.addWidget(lbl_min_dur)
        dur_layout.addWidget(self.input_min_dur)
        dur_layout.addSpacing(15)
        dur_layout.addWidget(lbl_max_dur)
        dur_layout.addWidget(self.input_max_dur)
        dur_layout.addStretch()
        scroll_layout.addWidget(create_category_capsule("⏱ Duration:", dur_container))


        scroll_layout.addStretch()

        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 10, 0, 0)
        
        unified_table_style = """
            QPushButton { 
                background-color: #383838; 
                color: #ffffff; 
                border: 2px solid #444444; 
                border-radius: 14px; 
                font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
                font-weight: bold; 
                font-size: 13px; 
                padding: 4px 12px; 
                min-height: 24px; 
            }
            QPushButton:hover { background-color: #404040; border: 2px solid #6b5a8e; }
            QPushButton:pressed { background-color: #3a324a; border: 2px solid #b29ae7; }
            QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }
            QPushButton::menu-indicator { image: none; }
        """
        
        # Style for Clear
        clear_style = unified_table_style.replace("color: #ffffff;", "color: #ff7777;").replace("#6b5a8e", "#e05555").replace("#b29ae7", "#ff7777")

        self.btn_clear = QPushButton("🗑 Clear")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.setStyleSheet(clear_style)
        self.btn_clear.clicked.connect(self.clear_filters)

        self.btn_apply = QPushButton("Apply Filters (0)")
        self.btn_apply.setCursor(Qt.PointingHandCursor)
        self.btn_apply.setStyleSheet(unified_table_style)
        self.btn_apply.clicked.connect(self.apply_filters)

        bottom_layout.addWidget(self.btn_clear)
        bottom_layout.addWidget(self.btn_apply)
        layout.addLayout(bottom_layout)

        self._outer_layout = main_layout
        self._inner_layout = layout
        self._bottom_layout = bottom_layout
        self._density = None

    def _date_time_input_style_for(self, dense) -> str:
        """QDateEdit / QTimeEdit chrome — comfort uses init style; compact shrinks."""
        if not bool(getattr(dense, "compact", False)):
            return getattr(self, "_date_time_input_style", "")

        font = 10
        pad_v, pad_h = 1, 5
        min_h = 18
        radius = 6
        border = 1
        drop_w = 18
        spin_w = 16
        arrow_sz = 8
        up = getattr(self, "_filter_date_arrow_up", "")
        down = getattr(self, "_filter_date_arrow_down", "")
        return f"""
            QDateEdit, QTimeEdit {{
                background-color: #383838;
                color: #ffffff;
                border: {border}px solid #444444;
                border-radius: {radius}px;
                font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
                font-weight: bold;
                font-size: {font}px;
                padding: {pad_v}px {pad_h}px;
                min-height: {min_h}px;
                max-height: {min_h + 2}px;
            }}
            QDateEdit:hover, QTimeEdit:hover {{ background-color: #404040; border: {border}px solid #6b5a8e; }}
            QDateEdit:focus, QTimeEdit:focus {{ background-color: #3a324a; border: {border}px solid #b29ae7; }}
            QDateEdit::drop-down {{
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: {drop_w}px;
                border-left: 1px solid #444444;
                border-top-right-radius: {radius - 1}px;
                border-bottom-right-radius: {radius - 1}px;
                background-color: #333333;
            }}
            QTimeEdit::up-button {{
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: {spin_w}px;
                border-left: 1px solid #444444;
                border-bottom: 1px solid #444444;
                border-top-right-radius: {radius - 1}px;
                background-color: #333333;
            }}
            QTimeEdit::down-button {{
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: {spin_w}px;
                border-left: 1px solid #444444;
                border-bottom-right-radius: {radius - 1}px;
                background-color: #333333;
            }}
            QDateEdit::drop-down:hover, QTimeEdit::up-button:hover, QTimeEdit::down-button:hover {{
                background-color: #6b5a8e;
            }}
            QDateEdit::drop-down:pressed, QTimeEdit::up-button:pressed, QTimeEdit::down-button:pressed {{
                background-color: #b29ae7;
            }}
            QTimeEdit::up-arrow {{
                image: url("{up}");
                width: {arrow_sz}px; height: {arrow_sz}px;
            }}
            QTimeEdit::down-arrow, QDateEdit::down-arrow {{
                image: url("{down}");
                width: {arrow_sz}px; height: {arrow_sz}px;
            }}
            QCalendarWidget QWidget {{ alternate-background-color: #2d2d2d; background-color: #252525; color: white; }}
            QCalendarWidget QToolButton {{ color: white; background-color: #383838; border-radius: 4px; padding: 2px; }}
            QCalendarWidget QToolButton:hover {{ background-color: #6b5a8e; }}
            QCalendarWidget QAbstractItemView:enabled {{
                color: white; background-color: #252525;
                selection-background-color: #6b5a8e; selection-color: white; border-radius: 4px;
            }}
        """

    def apply_density(self, dense) -> None:
        """Shrink popup chrome for Deck / ultra-narrow windows."""
        self._density = dense
        compact = bool(getattr(dense, "compact", False))
        width = 340 if compact else 460
        self.setFixedWidth(width)

        font = 11 if compact else 13
        pad_v = 2 if compact else 4
        pad_h = 8 if compact else 12
        min_h = 18 if compact else 24
        radius = 8 if compact else 10
        border = 1 if compact else 2
        outer_m = 6 if compact else 10
        inner_m = 8 if compact else 16
        gap = 6 if compact else 12
        cap_m = 8 if compact else 12
        title_font = 11 if compact else 13
        pill_r = 10 if compact else 14

        if getattr(self, "_outer_layout", None) is not None:
            self._outer_layout.setContentsMargins(outer_m, outer_m, outer_m, outer_m)
        if getattr(self, "_inner_layout", None) is not None:
            self._inner_layout.setContentsMargins(inner_m, inner_m, inner_m, inner_m)
            self._inner_layout.setSpacing(gap)
        if getattr(self, "_bottom_layout", None) is not None:
            self._bottom_layout.setContentsMargins(0, 6 if compact else 10, 0, 0)

        self.container.setStyleSheet(
            f"QFrame#MainFilterContainer {{ background-color: #252525; "
            f"border: 1px solid #3d3d3d; border-radius: {pill_r + 2}px; }}"
        )

        for capsule in self.findChildren(QFrame, "CategoryCapsule"):
            capsule.setStyleSheet(f"""
                QFrame#CategoryCapsule {{
                    background-color: #2d2d2d;
                    border: 1px solid #383838;
                    border-radius: {pill_r}px;
                }}
                QLabel#CategoryTitle {{
                    color: #cccccc;
                    border: none;
                    background: transparent;
                    font-size: {title_font}px;
                    font-weight: bold;
                    font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji';
                }}
            """)
            lay = capsule.layout()
            if lay is not None:
                lay.setContentsMargins(cap_m, cap_m, cap_m, cap_m)
                lay.setSpacing(4 if compact else 8)

        self._PILL_BTN_STYLE = f"""
            QPushButton {{
                background-color: #383838;
                color: #aaaaaa;
                border: {border}px solid #444444;
                border-radius: {radius}px;
                font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
                font-weight: bold;
                font-size: {font}px;
                padding: {pad_v}px {pad_h}px;
                min-height: {min_h}px;
            }}
            QPushButton:hover {{
                background-color: #404040;
                color: #ffffff;
                border: {border}px solid #555555;
            }}
            QPushButton:checked {{
                background-color: #404040;
                color: #ffffff;
                border: {border}px solid #6b5a8e;
            }}
            QPushButton:checked:hover {{
                background-color: #3a324a;
                border: {border}px solid #b29ae7;
            }}
        """
        for btn in self.findChildren(QPushButton):
            if btn in (self.btn_clear, self.btn_apply):
                continue
            # Game / type / health chips
            if btn.isCheckable() or btn.parent() in (
                getattr(self, "games_container", None),
                getattr(self, "types_container", None),
                getattr(self, "health_container", None),
            ):
                btn.setStyleSheet(self._PILL_BTN_STYLE)

        unified = f"""
            QPushButton {{
                background-color: #383838;
                color: #ffffff;
                border: {border}px solid #444444;
                border-radius: {radius + 2}px;
                font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
                font-weight: bold;
                font-size: {font}px;
                padding: {pad_v}px {pad_h}px;
                min-height: {min_h}px;
            }}
            QPushButton:hover {{ background-color: #404040; border: {border}px solid #6b5a8e; }}
            QPushButton:pressed {{ background-color: #3a324a; border: {border}px solid #b29ae7; }}
            QPushButton:disabled {{ background-color: #222222; color: #555555; border: {border}px solid #2d2d2d; }}
            QPushButton::menu-indicator {{ image: none; }}
        """
        clear_style = (
            unified.replace("color: #ffffff;", "color: #ff7777;")
            .replace("#6b5a8e", "#e05555")
            .replace("#b29ae7", "#ff7777")
        )
        self.btn_clear.setStyleSheet(clear_style)
        self.btn_apply.setStyleSheet(unified)

        # Date/time BlockCombo fields
        from steempeg.ui.widgets.block_combo import BlockCombo
        from steempeg.ui.widgets.combo_chrome import combo_popup_item_rules

        bc_pad = "0px" if compact else "0px"
        bc_font = 11 if compact else 13
        for combo in self.findChildren(BlockCombo):
            normal = f"""
                QComboBox {{ background: #1e1e1e; color: white; border: 1px solid #333;
                    border-radius: 6px; padding: {bc_pad}; font-weight: bold; font-size: {bc_font}px;
                    font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji';
                    min-height: {min_h}px; max-height: {min_h + 4}px; }}
                QLineEdit {{ background: transparent; color: white; border: none;
                    selection-background-color: #b29ae7; selection-color: black; padding: 0px; margin: 0px; }}
                QComboBox::drop-down {{ border: none; width: 0px; }}
            """ + combo_popup_item_rules(dense)
            combo.style_normal = normal
            combo.style_error = normal.replace(
                "border: 1px solid #333;", "border: 2px solid #ff4444;"
            )
            combo.setStyleSheet(combo.style_normal if combo.is_valid() else combo.style_error)

        dt_style = self._date_time_input_style_for(dense)
        if dt_style:
            cap_lbl = f"color: #888888; font-weight: bold; font-size: {10 if compact else 12}px;"
            for w in self.findChildren(QDateEdit):
                w.setStyleSheet(dt_style)
                if compact:
                    w.setMaximumWidth(112)
                else:
                    w.setMaximumWidth(16777215)
            for w in self.findChildren(QTimeEdit):
                w.setStyleSheet(dt_style)
                if compact:
                    w.setMaximumWidth(88)
                else:
                    w.setMaximumWidth(16777215)
            for lbl in self.findChildren(QLabel):
                ss = lbl.styleSheet() or ""
                if "#888888" in ss and "font-weight: bold" in ss:
                    lbl.setStyleSheet(cap_lbl)

    _PILL_BTN_STYLE = """
        QPushButton {
            background-color: #383838;
            color: #aaaaaa;
            border: 2px solid #444444;
            border-radius: 10px;
            font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
            font-weight: bold;
            font-size: 13px;
            padding: 4px 12px;
            min-height: 24px;
        }
        QPushButton:hover {
            background-color: #404040;
            color: #ffffff;
            border: 2px solid #555555;
        }
        QPushButton:checked {
            background-color: #404040;
            color: #ffffff;
            border: 2px solid #6b5a8e;
        }
        QPushButton:checked:hover {
            background-color: #3a324a;
            border: 2px solid #b29ae7;
        }
    """

    def set_content_max_height(self, max_px: int) -> None:
        """Size the Games list to its content, capped so the popup never overruns
        the footer buttons. The list grows row by row as games are added and the
        scrollbar only appears once it hits that cap.
        """
        # Collapse Games to measure everything else, so the cap is independent of
        # the scroll area's own expanding policy.
        self._games_scroll.setFixedHeight(0)
        self.adjustSize()
        non_games = self.height()
        cap = max(70, max_px - non_games)

        # Fixed popup width minus main/container/capsule margins + scrollbar.
        inset = 64 if getattr(self, "_density", None) and getattr(self._density, "compact", False) else 84
        width = max(120, self.width() - inset)
        content = self.games_layout.heightForWidth(width) + 4
        height = max(40, min(content, cap))

        self._games_scroll.setFixedHeight(height)
        self.adjustSize()

    _MOUSE_EVENTS = (
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseMove,
        QEvent.Type.MouseButtonRelease,
    )

    def eventFilter(self, source, event):
        et = event.type()
        games_c = getattr(self, 'games_container', None)
        types_c = getattr(self, 'types_container', None)
        health_c = getattr(self, 'health_container', None)
        if source in (games_c, types_c, health_c) and source is not None and et in self._MOUSE_EVENTS:
            if source is games_c:
                layout = self.games_layout
            elif source is types_c:
                layout = self.types_layout
            else:
                layout = self.health_layout
            pos = event.position().toPoint()
            if et == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                btn = self._pill_at(layout, pos)
                if btn and not btn.isChecked():
                    self._is_gathering = True
                    btn.setChecked(True)
                    self._is_gathering = False
                    self._drag_active = True
                    self._drag_layout = layout
                    self._drag_btn = btn
                    if layout is self.games_layout:
                        self._refresh_cascade_after_games()
                    elif layout is self.types_layout:
                        self._refresh_cascade_after_types()
                    self.update_live_count()
                    return True
            elif et == QEvent.Type.MouseMove and self._drag_active and event.buttons() & Qt.MouseButton.LeftButton:
                btn = self._pill_at(self._drag_layout, pos)
                if btn and not btn.isChecked():
                    self._is_gathering = True
                    btn.setChecked(True)
                    self._is_gathering = False
                    if self._drag_layout is self.games_layout:
                        self._refresh_cascade_after_games()
                    elif self._drag_layout is self.types_layout:
                        self._refresh_cascade_after_types()
                    self.update_live_count()
            elif et == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                handled = self._drag_btn is not None
                self._drag_active = False
                self._drag_layout = None
                self._drag_btn = None
                if handled:
                    return True
        return super().eventFilter(source, event)

    @staticmethod
    def _pill_at(layout, pos):
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if w and w.geometry().contains(pos):
                return w
        return None

    @staticmethod
    def _sec_to_qtime(seconds):
        h = min(23, seconds // 3600)
        m = (seconds % 3600) // 60
        s = seconds % 60
        return QTime(h, m, s)

    @staticmethod
    def _qtime_to_sec(qt):
        return qt.hour() * 3600 + qt.minute() * 60 + qt.second()

    @staticmethod
    def _parse_row_datetime(text):
        return parse_clip_datetime_text(text)

    @staticmethod
    def _parse_row_duration(text):
        txt = text or ""
        h = int(re.search(r'(\d+)h', txt).group(1)) if 'h' in txt else 0
        m = int(re.search(r'(\d+)m', txt).group(1)) if 'm' in txt else 0
        s = int(re.search(r'(\d+)s', txt).group(1)) if 's' in txt else 0
        return h * 3600 + m * 60 + s

    def _get_checked_health_levels(self):
        levels = []
        for i in range(self.health_layout.count()):
            w = self.health_layout.itemAt(i).widget()
            if w and w.isChecked():
                levels.append(w.property("health_level"))
        return levels

    def _get_checked_names(self, layout):
        names = []
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if w and w.isChecked():
                names.append(w.property("raw_name"))
        return names

    def _compute_stats(self, games=None, types=None):
        table = self.app.ui.table_clips
        unique_types = set()
        min_sec = 999999
        max_sec = 0
        min_dt = None
        max_dt = None

        for row in range(table.rowCount()):
            g_item = table.item(row, 0)
            t_item = table.item(row, 1)
            game = g_item.text().strip() if g_item else ""
            typ = t_item.text().strip() if t_item else ""

            if games is not None and game not in games:
                continue
            if types is not None:
                if not types:
                    continue
                if typ and typ not in types:
                    continue

            if typ:
                unique_types.add(typ)

            dt_item = table.item(row, 2)
            if dt_item:
                q_dt = self._parse_row_datetime(dt_item.text())
                if q_dt:
                    if min_dt is None or q_dt < min_dt:
                        min_dt = q_dt
                    if max_dt is None or q_dt > max_dt:
                        max_dt = q_dt

            d_item = table.item(row, 3)
            if d_item:
                total_sec = self._parse_row_duration(d_item.text())
                if total_sec < min_sec:
                    min_sec = total_sec
                if total_sec > max_sec:
                    max_sec = total_sec

        if min_sec == 999999:
            min_sec = 0

        return {
            'types': unique_types,
            'min_dt': min_dt,
            'max_dt': max_dt,
            'min_sec': min_sec,
            'max_sec': max_sec,
        }

    def _sync_type_memory(self):
        for i in range(self.types_layout.count()):
            w = self.types_layout.itemAt(i).widget()
            if w:
                self._type_checked_memory[w.property("raw_name")] = w.isChecked()

    def _rebuild_type_buttons(self, available_types):
        # Capture the live pill states first, then rebuild from remembered states.
        self._sync_type_memory()

        while self.types_layout.count():
            item = self.types_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for t_name in sorted(available_types):
            short_name = t_name[:12] + '...' if len(t_name) > 12 else t_name
            btn = QPushButton(f" {short_name}")
            btn.setCheckable(True)
            checked = self._type_checked_memory.get(t_name, True)
            btn.setChecked(checked)
            self._type_checked_memory[t_name] = checked
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._PILL_BTN_STYLE)
            btn.setProperty("raw_name", t_name)
            btn.clicked.connect(self._on_type_toggled)
            self.types_layout.addWidget(btn)

    def _default_datetime_bounds(self, stats):
        min_dt = stats['min_dt']
        max_dt = stats['max_dt']
        if not min_dt:
            min_dt = QDateTime.currentDateTime().addMonths(-1)
            max_dt = QDateTime.currentDateTime()
        return min_dt, max_dt

    def _reset_bounds_to_stats(self, stats):
        """Snap date/time/duration pickers to a stats dict (full library or cascade)."""
        min_dt, max_dt = self._default_datetime_bounds(stats)
        self.actual_min_dt = min_dt
        self.actual_max_dt = max_dt
        self.actual_min_sec = stats['min_sec']
        self.actual_max_sec = stats['max_sec']
        self._is_gathering = True
        self.input_min_date.setDate(min_dt.date())
        self.input_max_date.setDate(max_dt.date())
        self.input_min_time.setTime(QTime(0, 0))
        self.input_max_time.setTime(QTime(23, 59))
        self.input_min_dur.setTime(self._sec_to_qtime(stats['min_sec']))
        self.input_max_dur.setTime(self._sec_to_qtime(stats['max_sec']))
        self._is_gathering = False

    def _ensure_types_checked_if_none(self):
        """Re-selecting a game after hide-all must not leave every type off."""
        if self._get_checked_names(self.types_layout):
            return
        for i in range(self.types_layout.count()):
            w = self.types_layout.itemAt(i).widget()
            if not w:
                continue
            w.setChecked(True)
            self._type_checked_memory[w.property("raw_name")] = True

    def _apply_bounds(self, stats, *, clamp=False):
        min_dt = stats['min_dt']
        max_dt = stats['max_dt']
        min_sec = stats['min_sec']
        max_sec = stats['max_sec']

        if min_dt is None:
            min_dt = QDateTime.currentDateTime().addMonths(-1)
        if max_dt is None:
            max_dt = QDateTime.currentDateTime()

        # Decide auto-vs-manual BEFORE overwriting the stored extent: a bound is
        # "auto" while it still sits exactly on the previous actual extent (the user
        # never dragged it). An auto bound keeps following the data extent; a manual
        # bound is preserved and only reset when it becomes impossible.
        prev_min_dt = getattr(self, 'actual_min_dt', None)
        prev_max_dt = getattr(self, 'actual_max_dt', None)
        prev_min_sec = getattr(self, 'actual_min_sec', None)
        prev_max_sec = getattr(self, 'actual_max_sec', None)

        auto_min_date = prev_min_dt is not None and self.input_min_date.date() == prev_min_dt.date()
        auto_max_date = prev_max_dt is not None and self.input_max_date.date() == prev_max_dt.date()
        cur_min_dur = self._qtime_to_sec(self.input_min_dur.time())
        cur_max_dur = self._qtime_to_sec(self.input_max_dur.time())
        auto_min_dur = prev_min_sec is not None and cur_min_dur == prev_min_sec
        auto_max_dur = prev_max_sec is not None and cur_max_dur == prev_max_sec

        self.actual_min_dt = min_dt
        self.actual_max_dt = max_dt
        self.actual_min_sec = min_sec
        self.actual_max_sec = max_sec

        if not clamp or stats['min_dt'] is None:
            return

        self._is_gathering = True

        # Date: snap if untouched, or if the manual value is now impossible.
        if auto_min_date or self.input_min_date.date() > max_dt.date():
            self.input_min_date.setDate(min_dt.date())
        if auto_max_date or self.input_max_date.date() < min_dt.date():
            self.input_max_date.setDate(max_dt.date())

        # Duration: same rule.
        if auto_min_dur or cur_min_dur > max_sec:
            self.input_min_dur.setTime(self._sec_to_qtime(min_sec))
        if auto_max_dur or cur_max_dur < min_sec:
            self.input_max_dur.setTime(self._sec_to_qtime(max_sec))

        self._is_gathering = False

    def _on_game_toggled(self):
        self._refresh_cascade_after_games()
        self.update_live_count()

    def _on_type_toggled(self):
        self._refresh_cascade_after_types()
        self.update_live_count()

    def _refresh_cascade_after_games(self):
        if getattr(self, '_is_gathering', False):
            return
        games = self._get_checked_names(self.games_layout)
        if not games:
            self._rebuild_type_buttons(set())
            self._reset_bounds_to_stats(self._compute_stats())
            return

        stats = self._compute_stats(games=games)
        self._rebuild_type_buttons(stats['types'])
        self._ensure_types_checked_if_none()

        active_types = self._get_checked_names(self.types_layout)
        if active_types:
            bounds_stats = self._compute_stats(games=games, types=active_types)
        else:
            bounds_stats = stats
        self._apply_bounds(bounds_stats, clamp=True)

    def _refresh_cascade_after_types(self):
        if getattr(self, '_is_gathering', False):
            return
        games = self._get_checked_names(self.games_layout)
        if not games:
            return
        types = self._get_checked_names(self.types_layout)
        if not types:
            return
        stats = self._compute_stats(games=games, types=types)
        self._apply_bounds(stats, clamp=True)

    def gather_statistics(self, app_window):
        self.app = app_window
        table = self.app.ui.table_clips

        unique_games = {}
        for row in range(table.rowCount()):
            g_item = table.item(row, 0)
            if g_item:
                name = g_item.text().strip()
                if name not in unique_games:
                    unique_games[name] = g_item.icon()

        full_stats = self._compute_stats()

        while self.games_layout.count():
            item = self.games_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        saved_state = getattr(self.app, 'saved_filter_state', None)
        hide_all = bool(saved_state and saved_state.get('active') is False)
        for name, icon in unique_games.items():
            short_name = name[:14] + '...' if len(name) > 14 else name
            btn = QPushButton(icon, f" {short_name}")
            btn.setCheckable(True)
            if hide_all:
                btn.setChecked(False)
            elif saved_state and saved_state.get('games'):
                btn.setChecked(name in saved_state['games'])
            else:
                btn.setChecked(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._PILL_BTN_STYLE)
            btn.setProperty("raw_name", name)
            btn.clicked.connect(self._on_game_toggled)
            self.games_layout.addWidget(btn)

        # Seed the type memory: only honor a non-empty saved list on an active filter.
        if (
            saved_state
            and saved_state.get('active')
            and saved_state.get('types')
        ):
            saved_types = set(saved_state['types'])
            self._type_checked_memory = {t: (t in saved_types) for t in full_stats['types']}
        else:
            self._type_checked_memory = {t: True for t in full_stats['types']}

        min_dt = full_stats['min_dt']
        max_dt = full_stats['max_dt']
        min_sec = full_stats['min_sec']
        max_sec = full_stats['max_sec']
        if not min_dt:
            min_dt = QDateTime.currentDateTime().addMonths(-1)
            max_dt = QDateTime.currentDateTime()

        self.actual_min_dt = min_dt
        self.actual_max_dt = max_dt
        self.actual_min_sec = min_sec
        self.actual_max_sec = max_sec

        self._is_gathering = True
        if hide_all or not saved_state:
            self._reset_bounds_to_stats(full_stats)
        elif saved_state.get('active'):
            self.input_min_date.setDate(saved_state['min_date'])
            self.input_max_date.setDate(saved_state['max_date'])
            self.input_min_time.setTime(saved_state['min_time'])
            self.input_max_time.setTime(saved_state['max_time'])
            saved_min_dur = saved_state['min_dur']
            saved_max_dur = saved_state['max_dur']
            if (
                self._qtime_to_sec(saved_min_dur) == 0
                and self._qtime_to_sec(saved_max_dur) == 0
            ):
                self.input_min_dur.setTime(self._sec_to_qtime(min_sec))
                self.input_max_dur.setTime(self._sec_to_qtime(max_sec))
            else:
                self.input_min_dur.setTime(saved_min_dur)
                self.input_max_dur.setTime(saved_max_dur)
        else:
            self._reset_bounds_to_stats(full_stats)
        self._is_gathering = False

        for i in range(self.health_layout.count()):
            w = self.health_layout.itemAt(i).widget()
            if not w:
                continue
            level = w.property("health_level")
            if hide_all:
                w.setChecked(True)
            elif saved_state and saved_state.get('active') and saved_state.get('health'):
                w.setChecked(level in saved_state['health'])
            else:
                w.setChecked(True)

        self.input_min_date.dateChanged.connect(self.update_live_count)
        self.input_max_date.dateChanged.connect(self.update_live_count)
        self.input_min_time.timeChanged.connect(self.update_live_count)
        self.input_max_time.timeChanged.connect(self.update_live_count)
        self.input_min_dur.timeChanged.connect(self.update_live_count)
        self.input_max_dur.timeChanged.connect(self.update_live_count)

        self._refresh_cascade_after_games()
        self.update_live_count()

    def clear_filters(self):
        """ Resets all buttons and calendars to ACTUAL minimums. """
        self._is_gathering = True

        for i in range(self.games_layout.count()):
            w = self.games_layout.itemAt(i).widget()
            if w:
                w.setChecked(True)

        full_stats = self._compute_stats()
        # Clear = everything on: reset the type memory to all-checked, then rebuild.
        self._type_checked_memory = {t: True for t in full_stats['types']}
        self._rebuild_type_buttons(full_stats['types'])

        for i in range(self.health_layout.count()):
            w = self.health_layout.itemAt(i).widget()
            if not w:
                continue
            w.setChecked(True)

        min_dt = full_stats['min_dt'] or QDateTime.currentDateTime().addMonths(-1)
        max_dt = full_stats['max_dt'] or QDateTime.currentDateTime()
        self.actual_min_dt = min_dt
        self.actual_max_dt = max_dt
        self.actual_min_sec = full_stats['min_sec']
        self.actual_max_sec = full_stats['max_sec']

        self.input_min_date.setDate(min_dt.date())
        self.input_max_date.setDate(max_dt.date())
        self.input_min_time.setTime(QTime(0, 0))
        self.input_max_time.setTime(QTime(23, 59))
        self.input_min_dur.setTime(self._sec_to_qtime(full_stats['min_sec']))
        self.input_max_dur.setTime(self._sec_to_qtime(full_stats['max_sec']))

        self._is_gathering = False
        self.update_live_count()

    def _resolved_duration_bounds(self):
        """Return min/max duration seconds, recovering from stale 0:00–0:00."""
        min_dur = self._qtime_to_sec(self.input_min_dur.time())
        max_dur = self._qtime_to_sec(self.input_max_dur.time())
        if max_dur == 0 and min_dur == 0:
            full = self._compute_stats()
            return full['min_sec'], full['max_sec']
        if max_dur < min_dur:
            return min_dur, min_dur
        return min_dur, max_dur

    def update_live_count(self, *args):
        """ Safely counts suitable clips in real time. """
        if getattr(self, '_is_gathering', False) or not hasattr(self, 'app'): return
        table = self.app.ui.table_clips

        sel_games = self._get_checked_names(self.games_layout)
        sel_types = self._get_checked_names(self.types_layout)
        sel_health = self._get_checked_health_levels()

        if not sel_games or not sel_types or not sel_health:
            self.btn_apply.setText("Apply Filters (0)")
            return

        min_date, max_date = self.input_min_date.date(), self.input_max_date.date()
        min_time = self._qtime_to_sec(self.input_min_time.time())
        max_time = self._qtime_to_sec(self.input_max_time.time())
        min_dur, max_dur = self._resolved_duration_bounds()

        count = 0
        for row in range(table.rowCount()):
            show = True
            r_g = table.item(row, 0)
            r_t = table.item(row, 1)
            r_d = table.item(row, 2)
            r_dur = table.item(row, 3)

            if show and r_g and r_g.text().strip() not in sel_games: show = False
            if show and r_t and r_t.text().strip() not in sel_types: show = False
            if show and r_g:
                row_health = _row_display_health_level(r_g)
                if row_health not in sel_health:
                    show = False

            if show and r_d:
                q_dt = self._parse_row_datetime(r_d.text())
                if q_dt:
                    q_d = q_dt.date()
                    if min_date.isValid() and q_d < min_date: show = False
                    if max_date.isValid() and q_d > max_date: show = False
                    t_sec = q_dt.time().hour() * 3600 + q_dt.time().minute() * 60 + q_dt.time().second()
                    if t_sec < min_time: show = False
                    if t_sec > max_time: show = False

            if show and r_dur:
                sec = self._parse_row_duration(r_dur.text())
                if sec < min_dur: show = False
                if sec > max_dur: show = False

            if show: count += 1

        self.btn_apply.setText(f"Apply Filters ({count})")

    def apply_filters(self):
        """ LIGHTNING FAST FILTERING (NO SORTING, NO LAGS) """
        if not hasattr(self, 'app'): return
        table = self.app.ui.table_clips

        table.setUpdatesEnabled(False)

        selected_games = self._get_checked_names(self.games_layout)
        selected_types = self._get_checked_names(self.types_layout)
        selected_health = self._get_checked_health_levels()

        filter_active = bool(selected_games and selected_types and selected_health)

        if not filter_active:
            full_stats = self._compute_stats()
            self._reset_bounds_to_stats(full_stats)
            min_dur_sec = full_stats['min_sec']
            max_dur_sec = full_stats['max_sec']
            min_date = self.input_min_date.date()
            max_date = self.input_max_date.date()
            min_time = self.input_min_time.time()
            max_time = self.input_max_time.time()
        else:
            min_dur_sec, max_dur_sec = self._resolved_duration_bounds()
            if (
                self._qtime_to_sec(self.input_min_dur.time()) == 0
                and self._qtime_to_sec(self.input_max_dur.time()) == 0
                and max_dur_sec > 0
            ):
                self._is_gathering = True
                self.input_min_dur.setTime(self._sec_to_qtime(min_dur_sec))
                self.input_max_dur.setTime(self._sec_to_qtime(max_dur_sec))
                self._is_gathering = False
            min_date = self.input_min_date.date()
            max_date = self.input_max_date.date()
            min_time = self.input_min_time.time()
            max_time = self.input_max_time.time()

        saved = {
            'active': filter_active,
            'min_date': min_date,
            'max_date': max_date,
            'min_time': min_time,
            'max_time': max_time,
            'min_dur': self._sec_to_qtime(min_dur_sec),
            'max_dur': self._sec_to_qtime(max_dur_sec),
        }
        if filter_active:
            saved['games'] = selected_games
            saved['types'] = selected_types
            saved['health'] = selected_health
        else:
            saved['games'] = []
        self.app.saved_filter_state = saved

        visible_count = 0
        if not filter_active:
            for row in range(table.rowCount()):
                table.setRowHidden(row, True)
        else:
            min_date = self.input_min_date.date()
            max_date = self.input_max_date.date()
            min_time = self._qtime_to_sec(self.input_min_time.time())
            max_time = self._qtime_to_sec(self.input_max_time.time())
            min_dur = min_dur_sec
            max_dur = max_dur_sec

            for row in range(table.rowCount()):
                show = True
                item_game = table.item(row, 0)
                item_type = table.item(row, 1)
                item_date = table.item(row, 2)
                item_dur = table.item(row, 3)

                if show and item_game and item_game.text().strip() not in selected_games: show = False
                if show and item_type and item_type.text().strip() not in selected_types: show = False
                if show and item_game:
                    row_health = _row_display_health_level(item_game)
                    if row_health not in selected_health:
                        show = False

                if show and item_date:
                    q_dt = self._parse_row_datetime(item_date.text())
                    if q_dt:
                        r_date = q_dt.date()
                        if min_date.isValid() and r_date < min_date: show = False
                        if max_date.isValid() and r_date > max_date: show = False
                        r_time = q_dt.time().hour() * 3600 + q_dt.time().minute() * 60 + q_dt.time().second()
                        if r_time < min_time: show = False
                        if r_time > max_time: show = False

                if show and item_dur:
                    r_dur = self._parse_row_duration(item_dur.text())
                    if r_dur < min_dur: show = False
                    if r_dur > max_dur: show = False

                table.setRowHidden(row, not show)
                if show: visible_count += 1

        self.btn_apply.setText(f"Apply Filters ({visible_count})")
        
        # Re-enabling graphics
        table.setUpdatesEnabled(True)
        self.hide()
        
        # 5. THE MOST IMPORTANT PART: REBUILD THE GRID FROM SCRATCH TO KEEP CUSTOM WIDGETS!
        if hasattr(self.app, 'fast_sync_grid'):
            self.app.fast_sync_grid()