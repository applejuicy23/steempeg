from steempeg.render import bitrate
from steempeg.infra import cache 
from steempeg.core.dash import mpd 
from steempeg.core import games
from steempeg.core.dash import discovery
from steempeg.core import capabilities
from steempeg.infra import paths
from steempeg.core.dash import repair
from steempeg.ui.player.surface import MPVWrapper
from steempeg.ui.player.fullscreen import FullscreenEventFilter
from steempeg.ui.player.controls.audio import VolumeControlWidget
from steempeg.ui.player.controls.speed import SpeedControlWidget

import sys
import os
import subprocess
import re
import psutil
import requests
import json
import time
import logging
from datetime import datetime
# --- GLOBAL APP VERSION ---
APP_VERSION_STR = "30"
APP_VERSION_FLOAT = 30

if getattr(sys, 'frozen', False):
    _base_dir = os.path.dirname(sys.executable)
else:
    _base_dir = os.path.dirname(os.path.abspath(__file__))

_bin_dir = os.path.join(_base_dir, "bin")
os.environ["PATH"] = _bin_dir + os.pathsep + _base_dir + os.pathsep + os.environ["PATH"]

import mpv

from PySide6.QtCore import Qt, QFile, QThread, Signal, QTimer, QSize, QObject
from PySide6.QtCore import QUrl, QEvent
from PySide6.QtWidgets import QVBoxLayout, QApplication, QFileDialog, QMessageBox
from PySide6.QtWidgets import QTableWidgetItem, QHeaderView, QAbstractItemView
from PySide6.QtUiTools import QUiLoader
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QPen, QBrush

from steempeg.ui.widgets import FlowLayout, BlockCombo, ElidedLabel, SmartSliderFilter, FilterPillButton

def get_resource_path(relative_path):
    return paths.get_resource_path(relative_path)


def get_save_directory():
    return paths.get_save_directory()

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt


from PySide6.QtWidgets import QPushButton
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt


    

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget, QCompleter
from PySide6.QtCore import Qt, QDate



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


from PySide6.QtCore import Qt, QPoint, QTime, QDateTime, QTimer
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QPushButton, QWidget, 
                               QFrame, QLabel, QListWidget, QListWidgetItem, QComboBox)
from datetime import datetime
import re

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
                    font-family: 'Segoe UI';
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

        # --- GAMES CAPSULE ---
        self.games_container = QWidget()
        self.games_layout = FlowLayout()
        self.games_container.setLayout(self.games_layout)
        layout.addWidget(create_category_capsule("🎮 Games:", self.games_container))

        # --- TYPE CAPSULE ---
        self.types_container = QWidget()
        self.types_layout = FlowLayout()
        self.types_container.setLayout(self.types_layout)
        layout.addWidget(create_category_capsule("📂 Type:", self.types_container))

        # --- 3. SMART INPUTS STYLE (Clean, small pills + Rounded Spinners) ---
        from PySide6.QtWidgets import QDateEdit, QTimeEdit
        from PySide6.QtGui import QPixmap, QPainter, QColor
        from PySide6.QtCore import QPoint
        import tempfile
        import os
        
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
                font-family: 'Segoe UI', Arial, sans-serif;
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
        layout.addWidget(create_category_capsule("📅 Date:", date_container))

        # --- TIME CAPSULE (WITH AM/PM & ICONS) ---
        time_c_container = QWidget()
        time_c_layout = QHBoxLayout(time_c_container)
        time_c_layout.setContentsMargins(0, 0, 0, 0)
        time_c_layout.setSpacing(8)
        
        self.input_min_time = QTimeEdit()
        self.input_max_time = QTimeEdit()
        
        for te in (self.input_min_time, self.input_max_time):
            te.setDisplayFormat("hh:mm AP")
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
        layout.addWidget(create_category_capsule("⏰ Time of creation:", time_c_container))

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
        layout.addWidget(create_category_capsule("⏱ Duration:", dur_container))


        layout.addStretch()

        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 10, 0, 0)
        
        unified_table_style = """
            QPushButton { 
                background-color: #383838; 
                color: #ffffff; 
                border: 2px solid #444444; 
                border-radius: 14px; 
                font-family: 'Segoe UI', Arial, sans-serif;
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

    def gather_statistics(self, app_window):
        self.app = app_window 
        table = self.app.ui.table_clips

        unique_games = {}
        unique_types = set()
        min_sec = 999999
        max_sec = 0
        min_dt = None
        max_dt = None

        for row in range(table.rowCount()):
            g_item = table.item(row, 0)
            if g_item:
                name = g_item.text().strip()
                if name not in unique_games: unique_games[name] = g_item.icon()

            # Smart Type Collection
            t_item = table.item(row, 1)
            if t_item and t_item.text().strip():
                unique_types.add(t_item.text().strip())

            dt_item = table.item(row, 2)
            if dt_item:
                raw_dt_str = re.sub(r'\s+', ' ', dt_item.text().strip())
                dt_obj = None
                try: dt_obj = datetime.strptime(raw_dt_str, "%d %B %Y %I:%M %p")
                except:
                    try: dt_obj = datetime.strptime(raw_dt_str, "%d %B %Y")
                    except: pass
                
                if dt_obj:
                    q_dt = QDateTime(dt_obj.year, dt_obj.month, dt_obj.day, dt_obj.hour, dt_obj.minute, dt_obj.second)
                    if min_dt is None or q_dt < min_dt: min_dt = q_dt
                    if max_dt is None or q_dt > max_dt: max_dt = q_dt

            d_item = table.item(row, 3)
            if d_item:
                txt = d_item.text()
                h = int(re.search(r'(\d+)h', txt).group(1)) if 'h' in txt else 0
                m = int(re.search(r'(\d+)m', txt).group(1)) if 'm' in txt else 0
                s = int(re.search(r'(\d+)s', txt).group(1)) if 's' in txt else 0
                total_sec = h * 3600 + m * 60 + s
                if total_sec < min_sec: min_sec = total_sec
                if total_sec > max_sec: max_sec = total_sec

        # 1. Clean the old discs.
        while self.games_layout.count():
            item = self.games_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            
        while self.types_layout.count():
            item = self.types_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            
        # --- 2. NEW SMART BUTTON STYLES (Based on Refresh Button) ---
        new_btn_style = """
            QPushButton {
                background-color: #383838;
                color: #aaaaaa;
                border: 2px solid #444444;
                border-radius: 10px;
                font-family: 'Segoe UI', Arial, sans-serif;
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
        
        # 2. Generating IG circles
        for name, icon in unique_games.items():
            short_name = name[:14] + '...' if len(name) > 14 else name
            btn = QPushButton(icon, f" {short_name}")
            btn.setCheckable(True)
            saved_state = getattr(self.app, 'saved_filter_state', None)
            if saved_state and 'games' in saved_state:
                btn.setChecked(name in saved_state['games'])
            else:
                btn.setChecked(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(new_btn_style)
            btn.setProperty("raw_name", name)
            btn.clicked.connect(self.update_live_count)
            self.games_layout.addWidget(btn)

        # 3. Generating TYPE circles
        for t_name in sorted(list(unique_types)):
            short_name = t_name[:12] + '...' if len(t_name) > 12 else t_name
            btn = QPushButton(f" {short_name}")
            btn.setCheckable(True)
            saved_state = getattr(self.app, 'saved_filter_state', None)
            if saved_state and 'types' in saved_state:
                btn.setChecked(t_name in saved_state['types'])
            else:
                btn.setChecked(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(new_btn_style)
            btn.setProperty("raw_name", t_name)
            btn.clicked.connect(self.update_live_count)
            self.types_layout.addWidget(btn)


        
        # --- 3. SETTING NATIVE QT VALUES ---
        
        from PySide6.QtCore import QTime
        
        if not min_dt:
            min_dt = QDateTime.currentDateTime().addMonths(-1)
            max_dt = QDateTime.currentDateTime()
            
        # Filling out calendars
        self.input_min_date.setDate(min_dt.date())
        self.input_max_date.setDate(max_dt.date())
        
        # Filling in the time (AM/PM)
        self.input_min_time.setTime(QTime(0, 0))
        self.input_max_time.setTime(QTime(23, 59))
        
        # Fill in the duration 
        if min_sec == 999999: min_sec = 0
        
        # --- CLEAR BUTTON FIX: Store the actual clip boundarie
        self.actual_min_dt = min_dt
        self.actual_max_dt = max_dt
        self.actual_min_sec = min_sec
        self.actual_max_sec = max_sec
        
        def sec_to_qtime(seconds):
            h = seconds // 3600
            m = (seconds % 3600) // 60
            s = seconds % 60
            if h > 23: h = 23; m = 59; s = 59 # Lockout due to exceeding 24 hours
            return QTime(h, m, s)

        saved_state = getattr(self.app, 'saved_filter_state', None)
        if saved_state:
            self.input_min_date.setDate(saved_state['min_date'])
            self.input_max_date.setDate(saved_state['max_date'])
            self.input_min_time.setTime(saved_state['min_time'])
            self.input_max_time.setTime(saved_state['max_time'])
            self.input_min_dur.setTime(saved_state['min_dur'])
            self.input_max_dur.setTime(saved_state['max_dur'])
        else:
            # Otherwise, set default limits.
            self.input_min_date.setDate(min_dt.date())
            self.input_max_date.setDate(max_dt.date())
            from PySide6.QtCore import QTime
            self.input_min_time.setTime(QTime(0, 0))
            self.input_max_time.setTime(QTime(23, 59))
            
            if min_sec == 999999: min_sec = 0
            def sec_to_qtime(seconds):
                h = min(23, seconds // 3600); m = (seconds % 3600) // 60; s = seconds % 60
                return QTime(h, m, s)

            self.input_min_dur.setTime(sec_to_qtime(min_sec))
            self.input_max_dur.setTime(sec_to_qtime(max_sec))


        # Move this out of the else block so it works on the second opening too!

        self.input_min_date.dateChanged.connect(self.update_live_count)
        self.input_max_date.dateChanged.connect(self.update_live_count)
        self.input_min_time.timeChanged.connect(self.update_live_count)
        self.input_max_time.timeChanged.connect(self.update_live_count)
        self.input_min_dur.timeChanged.connect(self.update_live_count)
        self.input_max_dur.timeChanged.connect(self.update_live_count)

        self._is_gathering = False
        self.update_live_count()

    def clear_filters(self):
        """ Resets all buttons and calendars to ACTUAL minimums. """
        self._is_gathering = True
        
        for i in range(self.games_layout.count()):
            w = self.games_layout.itemAt(i).widget()
            if w: w.setChecked(True)
            
        for i in range(self.types_layout.count()):
            w = self.types_layout.itemAt(i).widget()
            if w: w.setChecked(True)
            
        # Bringing back the REAL dates and times for the clips!
        if hasattr(self, 'actual_min_dt') and self.actual_min_dt:
            self.input_min_date.setDate(self.actual_min_dt.date())
            self.input_max_date.setDate(self.actual_max_dt.date())
        else:
            self.input_min_date.setDate(self.input_min_date.minimumDate())
            self.input_max_date.setDate(self.input_max_date.maximumDate())
        
        from PySide6.QtCore import QTime
        self.input_min_time.setTime(QTime(0, 0))
        self.input_max_time.setTime(QTime(23, 59))
        
        if hasattr(self, 'actual_min_sec'):
            def sec_to_qtime(seconds):
                h = min(23, seconds // 3600); m = (seconds % 3600) // 60; s = seconds % 60
                return QTime(h, m, s)
            self.input_min_dur.setTime(sec_to_qtime(self.actual_min_sec))
            self.input_max_dur.setTime(sec_to_qtime(self.actual_max_sec))
        else:
            self.input_min_dur.setTime(QTime(0, 0))
            self.input_max_dur.setTime(QTime(23, 59, 59))
        
        self._is_gathering = False
        self.update_live_count()

    def update_live_count(self, *args):
        """ Safely counts suitable clips in real time. """
        if getattr(self, '_is_gathering', False) or not hasattr(self, 'app'): return
        table = self.app.ui.table_clips
        
        import re
        from datetime import datetime
        from PySide6.QtCore import QDate

        sel_games = [self.games_layout.itemAt(i).widget().property("raw_name") for i in range(self.games_layout.count()) if self.games_layout.itemAt(i).widget().isChecked()]
        if not sel_games: sel_games = [self.games_layout.itemAt(i).widget().property("raw_name") for i in range(self.games_layout.count())]

        sel_types = [self.types_layout.itemAt(i).widget().property("raw_name") for i in range(self.types_layout.count()) if self.types_layout.itemAt(i).widget().isChecked()]
        if not sel_types: sel_types = [self.types_layout.itemAt(i).widget().property("raw_name") for i in range(self.types_layout.count())]

        min_date, max_date = self.input_min_date.date(), self.input_max_date.date()
        def qt_sec(qt): return qt.hour() * 3600 + qt.minute() * 60 + qt.second()
        min_time, max_time = qt_sec(self.input_min_time.time()), qt_sec(self.input_max_time.time())
        min_dur, max_dur = qt_sec(self.input_min_dur.time()), qt_sec(self.input_max_dur.time())

        count = 0
        for row in range(table.rowCount()):
            show = True
            r_g = table.item(row, 0)
            r_t = table.item(row, 1)
            r_d = table.item(row, 2)
            r_dur = table.item(row, 3)

            if show and r_g and r_g.text().strip() not in sel_games: show = False
            if show and r_t and r_t.text().strip() not in sel_types: show = False

            if show and r_d:
                raw_dt = re.sub(r'\s+', ' ', r_d.text().strip())
                dt_obj = None
                try: dt_obj = datetime.strptime(raw_dt, "%d %B %Y %I:%M %p")
                except: 
                    try: dt_obj = datetime.strptime(raw_dt, "%d %B %Y")
                    except: pass
                if dt_obj:
                    q_d = QDate(dt_obj.year, dt_obj.month, dt_obj.day)
                    if min_date.isValid() and q_d < min_date: show = False
                    if max_date.isValid() and q_d > max_date: show = False
                    t_sec = dt_obj.hour * 3600 + dt_obj.minute * 60
                    if min_time is not None and t_sec < min_time: show = False
                    if max_time is not None and t_sec > max_time: show = False

            if show and r_dur:
                txt = r_dur.text()
                h = int(re.search(r'(\d+)h', txt).group(1)) if 'h' in txt else 0
                m = int(re.search(r'(\d+)m', txt).group(1)) if 'm' in txt else 0
                s = int(re.search(r'(\d+)s', txt).group(1)) if 's' in txt else 0
                sec = h * 3600 + m * 60 + s
                if min_dur is not None and sec < min_dur: show = False
                if max_dur is not None and sec > max_dur: show = False
            
            if show: count += 1

        self.btn_apply.setText(f"Apply Filters ({count})")

    def apply_filters(self):
        """ LIGHTNING FAST FILTERING (NO SORTING, NO LAGS) """
        if not hasattr(self, 'app'): return
        table = self.app.ui.table_clips
            
        import re
        from datetime import datetime
        from PySide6.QtCore import QDate, Qt
        
        table.setUpdatesEnabled(False)

        # 1. Read filters
        selected_games = []
        for i in range(self.games_layout.count()):
            btn = self.games_layout.itemAt(i).widget()
            if btn and btn.isChecked(): selected_games.append(btn.property("raw_name"))
        if not selected_games: selected_games = [self.games_layout.itemAt(i).widget().property("raw_name") for i in range(self.games_layout.count())]

        selected_types = []
        for i in range(self.types_layout.count()):
            btn = self.types_layout.itemAt(i).widget()
            if btn and btn.isChecked(): selected_types.append(btn.property("raw_name"))
        if not selected_types:
            for i in range(self.types_layout.count()):
                btn = self.types_layout.itemAt(i).widget()
                if btn: btn.setChecked(True); selected_types.append(btn.property("raw_name"))
        
        self.app.saved_filter_state = {
            'games': selected_games,
            'types': selected_types,
            'min_date': self.input_min_date.date(),
            'max_date': self.input_max_date.date(),
            'min_time': self.input_min_time.time(),
            'max_time': self.input_max_time.time(),
            'min_dur': self.input_min_dur.time(),
            'max_dur': self.input_max_dur.time()
        }

        min_date = self.input_min_date.date()
        max_date = self.input_max_date.date()

        def qtime_to_sec(qt):
            return qt.hour() * 3600 + qt.minute() * 60 + qt.second()

        min_time = qtime_to_sec(self.input_min_time.time())
        max_time = qtime_to_sec(self.input_max_time.time())
        
        min_dur = qtime_to_sec(self.input_min_dur.time())
        max_dur = qtime_to_sec(self.input_max_dur.time())

        # 2. SIMPLY HIDING AND SHOWING ROWS (Without retrieving anything from memory!)
        visible_count = 0
        for row in range(table.rowCount()):
            show = True
            item_game = table.item(row, 0)
            item_type = table.item(row, 1)
            item_date = table.item(row, 2)
            item_dur = table.item(row, 3)

            if show and item_game and item_game.text().strip() not in selected_games: show = False
            if show and item_type and item_type.text().strip() not in selected_types: show = False

            if show and item_date:
                raw_dt = re.sub(r'\s+', ' ', item_date.text().strip())
                dt_obj = None
                try: dt_obj = datetime.strptime(raw_dt, "%d %B %Y %I:%M %p")
                except: 
                    try: dt_obj = datetime.strptime(raw_dt, "%d %B %Y")
                    except: pass
                if dt_obj:
                    r_date = QDate(dt_obj.year, dt_obj.month, dt_obj.day)
                    if min_date and r_date < min_date: show = False
                    if max_date and r_date > max_date: show = False
                    r_time = dt_obj.hour * 3600 + dt_obj.minute * 60
                    if min_time is not None and r_time < min_time: show = False
                    if max_time is not None and r_time > max_time: show = False

            if show and item_dur:
                txt = item_dur.text()
                h = int(re.search(r'(\d+)h', txt).group(1)) if 'h' in txt else 0
                m = int(re.search(r'(\d+)m', txt).group(1)) if 'm' in txt else 0
                s = int(re.search(r'(\d+)s', txt).group(1)) if 's' in txt else 0
                r_dur = h * 3600 + m * 60 + s
                if min_dur is not None and r_dur < min_dur: show = False
                if max_dur is not None and r_dur > max_dur: show = False
            
            # Applying visibility
            table.setRowHidden(row, not show)
            if show: visible_count += 1

        self.btn_apply.setText(f"Apply Filters ({visible_count})")
        
        # Re-enabling graphics
        table.setUpdatesEnabled(True)
        self.hide()
        
        # 5. THE MOST IMPORTANT PART: REBUILD THE GRID FROM SCRATCH TO KEEP CUSTOM WIDGETS!
        if hasattr(self.app, 'fast_sync_grid'):
            self.app.fast_sync_grid()
        

class SteempegApp(QObject):
    def __init__(self):
        # 1. LOADING THE INTERFACE
        super().__init__()
        loader = QUiLoader()
        ui_file_path = get_resource_path("smpegui13.ui")
        ui_file = QFile(ui_file_path)
        
        if not ui_file.open(QFile.ReadOnly):
            return
            
        self.ui = loader.load(ui_file)
        ui_file.close()

        self.ui.setStyleSheet("""
            QDialog#Dialog { background-color: #1e1e1e; }
            

            QToolTip {
                background-color: #2d2d2d; 
                color: #ffffff; 
                border: 1px solid #444444; 
                border-radius: 4px; 
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 11px;
                font-weight: bold;
                padding: 4px 8px;
            }
        """)
        
        self.ui.setWindowTitle(f"Steempeg v{APP_VERSION_STR}")
        
        # Setting the application icon
        icon_path = get_resource_path("logo.png")
        if os.path.exists(icon_path):
            self.ui.setWindowIcon(QIcon(icon_path))

        # 2. DATABASE AND VARIABLES
        # Steam bitrate dictionary in megabits (Mbps) for different resolutions
        self.steam_bitrate_presets = {
            "Ultra": {"4320p": 120, "2160p": 50, "1440p": 32, "1080p": 24, "720p": 12, "480p": 6, "360p": 3, "260p": 1.5, "144p": 0.5},
            "High": {"4320p": 90, "2160p": 38, "1440p": 22, "1080p": 12, "720p": 7.5, "480p": 4, "360p": 2, "260p": 1.0, "144p": 0.3},
            "Medium": {"4320p": 60, "2160p": 28.5, "1440p": 16.5, "1080p": 9, "720p": 5.6, "480p": 2.5, "360p": 1.2, "260p": 0.6, "144p": 0.2},
            "Low": {"4320p": 40, "2160p": 19, "1440p": 11, "1080p": 6, "720p": 3.75, "480p": 1.5, "360p": 0.8, "260p": 0.4, "144p": 0.1}
        }

        self.game_names_cache = {} # Cache for game names to avoid spamming the Steam API
        self.game_icons_cache = {} # Cache for downloaded Steam images
        self.clips_folder = "" # Current clip folder
        
        # --- Set default rendered_videos ---
        default_export_dir = os.path.join(get_save_directory(), "rendered_videos").replace('\\', '/')
        if not os.path.exists(default_export_dir):
            os.makedirs(default_export_dir, exist_ok=True)
        self.custom_destination = default_export_dir 
        
        # Let's write this path directly on the button in the interface
        if hasattr(self.ui, 'destination_button'):
            self.ui.destination_button.setText(f"Destination: {self.custom_destination}")
            
        self.current_orig_bitrate = 0 # Bitrate of the selected original clip
        self.current_clip_duration_sec = 0
        
        # list of all supported resolutions for rendering
        self.all_qualities = [
            ("2160p (Best Quality)", 2160),
            ("1440p (Very good Quality)", 1440),
            ("1080p (Good Quality)", 1080),
            ("720p (Mid Quality)", 720),
            ("480p (Bad Quality)", 480),
            ("360p (Very bad Quality)", 360),
            ("260p (Worst Quality)", 260),
            ("144p (Old VHS tape)", 144)
        ]

        self.set_status("Ready")

        self.cache_dir = os.path.join(get_save_directory(), "cache")
        self.logs_dir = os.path.join(get_save_directory(), "logs")
        self.screenshots_dir = os.path.join(get_save_directory(), "Screenshots")

        if not os.path.exists(self.screenshots_dir):
            os.makedirs(self.screenshots_dir)

        if not os.path.exists(self.logs_dir):
            os.makedirs(self.logs_dir)
        

            
        # Create a log file with the date and time of launch
        log_filename = os.path.join(self.logs_dir, f"steempeg_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        self.current_log_file = log_filename
        logging.basicConfig(
            filename=log_filename,
            level=logging.DEBUG, # Everything here
            format='[%(asctime)s] [%(levelname)s] %(message)s',
            datefmt='%H:%M:%S',
            encoding='utf-8'
        )
        logging.info("="*40)
        logging.info(f"STEEMPEG {APP_VERSION_STR} RUNNING") 
        logging.info("="*40)

        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir) # Create a cache folder if it doesn't exist
            
        self.json_cache_path = os.path.join(self.cache_dir, "games.json")
        self.game_names_cache = self.load_json_cache() # JSON
        self.game_icons_cache = {} # This is where we store downloaded images in memory
        
        # 3. CONFIGURING THE INTERFACE (TABLE AND COMBOBOXES)
        if hasattr(self.ui, 'table_clips'):
            self.ui.table_clips.setColumnCount(4)
            # 1. CHANGE THE ORDER OF HEADINGS
            self.ui.table_clips.setHorizontalHeaderLabels(["Game Name", "Type", "Date", "Time"])
            self.ui.table_clips.setIconSize(QSize(16, 16))

            self.ui.table_clips.setFocusPolicy(Qt.NoFocus)
            self.ui.table_clips.viewport().setFocusPolicy(Qt.NoFocus)

            # GUI TABLE
            self.ui.table_clips.setStyleSheet("""
                QTableWidget { 
                    background: transparent; 
                    border: none; 
                    outline: none; 
                }
                QTableWidget::item { 
                    padding: 4px 12px; 
                    border-bottom: 1px solid #282828; 
                    color: #e0e0e0; 
                    font-family: 'Inter', 'Segoe UI', sans-serif;
                    font-size: 13px;
                    font-weight: 600; 
                }
                QTableWidget::item:hover { 
                    background-color: #303030; 
                }
                QTableWidget::item:selected { 
                    background-color: #3a2e54; 
                    color: #ffffff; 
                }
                
                
                QHeaderView {
                    background-color: transparent;
                    border: none;
                }
                QHeaderView::section {
                    background-color: #2a2a2a; 
                    color: #999999;
                    padding: 6px 14px;
                    border: 1px solid #353535; 
                    border-radius: 12px;
                    margin-right: 6px; 
                    margin-bottom: 6px; 
                    font-size: 12px;
                    font-weight: bold;
                }
                QHeaderView::section:hover {
                    background-color: #353535;
                    color: #ffffff;
                    border: 1px solid #555555;
                }
                QHeaderView::section:checked, QHeaderView::section:pressed {
                    background-color: #3a2e54; 
                    color: #b29ae7;
                    border: 1px solid #6b5a8e;
                }
                QHeaderView::up-arrow, QHeaderView::down-arrow {
                    width: 0px; height: 0px;
                }
            """)
            self.ui.table_clips.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.ui.table_clips.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.ui.table_clips.setShowGrid(False)
            self.ui.table_clips.verticalHeader().setVisible(False)
            self.ui.table_clips.setContextMenuPolicy(Qt.CustomContextMenu)
            self.ui.table_clips.customContextMenuRequested.connect(self.show_clip_context_menu)
            # 2. ADJUST THE WIDTH
            header = self.ui.table_clips.horizontalHeader()

            header.setStretchLastSection(False)
            header.setMinimumSectionSize(40) # Allow shrinking the 'Game Name' column to the size of a single icon!
            self.ui.table_clips.setMinimumWidth(80) # Allow the splitter to collapse the entire table to zero!

            # 1. KILLING UGLY LINE BREAKS
            self.ui.table_clips.setWordWrap(False) # Text will never jump to the second line again!
            self.ui.table_clips.setTextElideMode(Qt.ElideRight) # Replace the truncated segment with aesthetic "..."

            self.ui.table_clips.verticalHeader().setSectionResizeMode(QHeaderView.Fixed) 
            self.ui.table_clips.verticalHeader().setDefaultSectionSize(48)
            
            
            # 2. Enter Bold Text
            from PySide6.QtGui import QFont
            custom_font = QFont("Segoe UI", 10) 
            custom_font.setWeight(QFont.DemiBold)
            self.ui.table_clips.setFont(custom_font)
            
            header.setSectionResizeMode(0, QHeaderView.Stretch)         
            header.setSectionResizeMode(1, QHeaderView.Interactive) # Switch to Interactive so they don't jump around when compressed.
            header.setSectionResizeMode(2, QHeaderView.Interactive) 
            header.setSectionResizeMode(3, QHeaderView.Interactive) 
            
            # Set the ideal width for the right columns
            self.ui.table_clips.setColumnWidth(1, 80)  # Type
            self.ui.table_clips.setColumnWidth(2, 130) # Date
            self.ui.table_clips.setColumnWidth(3, 100) # Duration
            
            self.ui.table_clips.itemSelectionChanged.connect(self.update_quality_options)
            if hasattr(self.ui, 'table_clips'):
                from PySide6.QtCore import QTimer 
                self.ui.table_clips.horizontalHeader().sortIndicatorChanged.connect(
                    # Give the table 50 milliseconds to physically finish sorting the rows!
                    lambda *args: QTimer.singleShot(50, self.build_netflix_grid) if hasattr(self, 'build_netflix_grid') else None
                )

            # --- SMART RIGHT-CLICK (NO ROW SELECTION) ---
            self.ui.table_clips.viewport().installEventFilter(self)
            
            # Attaching an event listener to the main window
            self.ui.installEventFilter(self)
            
            QApplication.instance().aboutToQuit.connect(self.on_app_exit)

            import PySide6.QtWidgets as qtw
            import PySide6.QtCore as qtc

            #1: Hiding the old, ugly text from Qt Designer
            if hasattr(self.ui, 'label_13'):
                self.ui.label_13.hide()
                target_layout = self.ui.label_13.parentWidget().layout()
                insert_idx = target_layout.indexOf(self.ui.label_13)
            else:
                target_layout = self.ui.right_panel.layout()
                insert_idx = 0

            #2. CREATE A BEAUTIFUL TABLET (Without a counter)
            cm_row = qtw.QHBoxLayout()
            cm_row.setContentsMargins(0, 0, 0, 10) 
            
            self.mega_top_pill = qtw.QFrame()
            self.mega_top_pill.setStyleSheet("""
                QFrame {
                    background-color: #2d2d2d;
                    border: 1px solid #353535;
                    border-radius: 16px; 
                }
            """)
            
            # Layer inside our tablet
            pill_layout = qtw.QHBoxLayout(self.mega_top_pill)
            pill_layout.setContentsMargins(24, 8, 24, 8) 
            
            # Only Folder Icon + Text
            self.lbl_cm = qtw.QLabel("📁 Clips Manager")
            self.lbl_cm.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 14px; border: none; background: transparent;")
            
            # Put the text into the tablet
            pill_layout.addWidget(self.lbl_cm)

            # 3. PERFECT CENTERING IN THE PANEL
            cm_row.addStretch()
            cm_row.addWidget(self.mega_top_pill)
            cm_row.addStretch()

            # 4. INSERT IT INTO THE INTERFACE EXACTLY IN ITS PLACE
            target_layout.insertLayout(insert_idx, cm_row)

            # 1. MEGA-CAPSULE (All elements within a single floating island)
            # Container for external padding
            top_bar_layout = qtw.QHBoxLayout()
            top_bar_layout.setContentsMargins(12, 0, 12, 4) 
            
            mega_top_pill = qtw.QFrame()
            mega_top_pill.setStyleSheet("""
                QFrame {
                    background-color: #2d2d2d;
                    border: 1px solid #353535;
                    border-radius: 20px;
                }
                QLabel { border: none; background: transparent; }
            """)

            # 2. Making the Text White
            lbl_view = qtw.QLabel("View")
            lbl_view.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 13px;")

            # 3. Create a List button (inactive) with white text.
            self.toggle_style_inactive = "background-color: transparent; color: #ffffff; border-radius: 12px; font-weight: bold; font-size: 12px; padding: 6px 16px; border: none;"

            # 4. Making the Clip Counter White
            self.lbl_clip_count = qtw.QLabel("• 0 Clips")
            self.lbl_clip_count.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 13px;")
            
            top_pill_layout = qtw.QHBoxLayout(mega_top_pill)
            top_pill_layout.setContentsMargins(16, 6, 16, 6) # Capsule Internal Padding
            top_pill_layout.setSpacing(14)

            # "View" Text
            lbl_view = qtw.QLabel("View")
            lbl_view.setStyleSheet("color: #777777; font-weight: bold; font-size: 13px;")

            # Grid / List Toggle
            self.toggle_pill = qtw.QFrame()
            self.toggle_pill.setStyleSheet("QFrame { background-color: #141414; border-radius: 14px; border: none; }")
            pill_layout = qtw.QHBoxLayout(self.toggle_pill)
            pill_layout.setContentsMargins(2, 2, 2, 2)
            pill_layout.setSpacing(0)

            self.btn_view_grid = qtw.QPushButton("Grid")
            self.btn_view_list = qtw.QPushButton("List")
            
            self.toggle_style_active = "background-color: #5138e6; color: white; border-radius: 12px; font-weight: bold; font-size: 12px; padding: 6px 16px; border: none;"
            self.toggle_style_inactive = "background-color: transparent; color: #888888; border-radius: 12px; font-weight: bold; font-size: 12px; padding: 6px 16px; border: none;"

            self.btn_view_list.setStyleSheet(self.toggle_style_inactive)
            self.btn_view_grid.setStyleSheet(self.toggle_style_active)
            self.btn_view_list.setCursor(qtc.Qt.PointingHandCursor)
            self.btn_view_grid.setCursor(qtc.Qt.PointingHandCursor)

            pill_layout.addWidget(self.btn_view_grid)
            pill_layout.addWidget(self.btn_view_list)

            # Counter
            self.lbl_clip_count = qtw.QLabel("• 0 Clips")
            self.lbl_clip_count.setStyleSheet("color: #777777; font-weight: bold; font-size: 13px;")

            # BREATHABLE FILTER PAD
            self.btn_filter_pill = FilterPillButton()
            
            # Creating the menu and setting up the click handler!
            self.filter_menu = FilterMenu(self.ui)
            self.btn_filter_pill.clicked.connect(self.show_filter_menu)
            
            # Lbuild the island
            top_pill_layout.addWidget(lbl_view)
            top_pill_layout.addWidget(self.toggle_pill)
            top_pill_layout.addWidget(self.lbl_clip_count)

            top_pill_layout.addWidget(self.btn_filter_pill)

            top_bar_layout.addWidget(mega_top_pill)

            # 2. KILLING A QT TABLE 
            self.ui.table_clips.setShowGrid(False)
            
            # (Sorting buttons at the top
            self.ui.table_clips.horizontalHeader().setVisible(True)
            self.ui.table_clips.horizontalHeader().setHighlightSections(False)
            self.ui.table_clips.horizontalHeader().setDefaultAlignment(qtc.Qt.AlignCenter)
            
            self.ui.table_clips.verticalHeader().setVisible(False)
            self.ui.table_clips.setFrameShape(qtw.QFrame.NoFrame)
            self.ui.table_clips.setHorizontalScrollBarPolicy(qtc.Qt.ScrollBarAlwaysOff)
            
            self.ui.table_clips.verticalHeader().setDefaultSectionSize(46) 
            self.ui.table_clips.setIconSize(qtc.QSize(26, 26)) 

            self.ui.table_clips.setStyleSheet("""
                QTableWidget { 
                    background: transparent; 
                    border: none; 
                    outline: none; 
                }
                QTableWidget::item { 
                    padding: 4px 12px; 
                    border-bottom: 1px solid #282828; 
                    color: #d1d1d1; 
                    font-size: 13px;
                    font-family: 'Segoe UI', Arial, sans-serif;
                }
                QTableWidget::item:hover { 
                    background-color: #303030; 
                }
                QTableWidget::item:selected { 
                    background-color: #3a2e54; 
                    color: #ffffff; 
                }

                QHeaderView {
                    background-color: transparent;
                    border: none;
                }
                QHeaderView::section {
                    background-color: transparent; 
                    color: #d1d1d1; 
                    padding: 6px;
                    border: none;
                    border-bottom: 1px solid #333333; 
                    font-size: 13px;
                    font-weight: bold;
                }
                QHeaderView::section:hover {
                    color: #ffffff;
                }
                QHeaderView::section:checked {
                    color: #b29ae7;
                }
                QHeaderView::up-arrow, QHeaderView::down-arrow {
                    width: 0px; height: 0px; 
                }
            """)
            
            header = self.ui.table_clips.horizontalHeader()
            header.setStretchLastSection(False) 
            self.ui.table_clips.setColumnCount(4)
            self.ui.table_clips.setHorizontalHeaderLabels(["Game Name", "Type", "Date", "Duration"])

            # 1. Killing off wonky interactivity
            header.setSectionResizeMode(0, QHeaderView.Stretch) # Stretches behind the splitter
            header.setSectionResizeMode(1, QHeaderView.Fixed)   # Type – stone
            header.setSectionResizeMode(2, QHeaderView.Fixed)   # Date - stone
            header.setSectionResizeMode(3, QHeaderView.Fixed)   # Duration - stone
            
            header.setStretchLastSection(False)

            # 2. Assign the ideal width to fixed columns once.
            self.ui.table_clips.setColumnWidth(1, 100) # Type
            self.ui.table_clips.setColumnWidth(2, 160) # Date
            self.ui.table_clips.setColumnWidth(3, 100) # Duration

            # 3. NETFLIX-GRID
            self.grid_clips = qtw.QListWidget()
            self.grid_clips.setViewMode(qtw.QListWidget.IconMode)
            self.grid_clips.setResizeMode(qtw.QListWidget.Adjust)
            self.grid_clips.setSpacing(15)
            self.grid_clips.setContextMenuPolicy(Qt.CustomContextMenu)
            self.grid_clips.customContextMenuRequested.connect(self.show_grid_context_menu)
            self.grid_clips.viewport().installEventFilter(self)
            # We strictly fix the card sizes so they don't fly apart when hidden!
            self.grid_clips.setUniformItemSizes(True)
            # We allow only ONE clip to be selected at a time (to avoid frame bugs)
            self.grid_clips.setSelectionMode(qtw.QAbstractItemView.SingleSelection)
            
            # Boomerang Effect (Drag & Snap Back)
            self.grid_clips.setDragDropMode(qtw.QAbstractItemView.DragOnly)
            self.grid_clips.setMovement(qtw.QListView.Static)
            self.grid_clips.itemSelectionChanged.connect(self.on_grid_selection_changed)
            self.grid_clips.setStyleSheet("""
                QListWidget { background: transparent; border: none; outline: none; }
                
                QListWidget::item { 
                    border-top-left-radius: 0px; 
                    border-top-right-radius: 0px; 
                    border-bottom-left-radius: 12px; 
                    border-bottom-right-radius: 12px; 
                    border: 2px solid #444444; 
                    background-color: #2d2d2d; 
                    padding: 0px;
                    margin: 0px;
                } 
                QListWidget::item:selected { 
                    border: 3px solid #b29ae7; 
                }
                
                QScrollBar:vertical { border: none; background: transparent; width: 10px; margin: 2px; }
                QScrollBar::handle:vertical { background: #4e4e4e; min-height: 30px; border-radius: 4px; }
                QScrollBar::handle:vertical:hover { background: #b29ae7; }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            """)

            original_parent_layout = self.ui.table_clips.parentWidget().layout()
            original_idx = -1
            if original_parent_layout:
                original_idx = original_parent_layout.indexOf(self.ui.table_clips)

            # 4. LIBRARY BLOCK
            self.library_views_container = qtw.QFrame()
            self.library_views_container.setStyleSheet("QFrame { background-color: #2d2d2d; border: 1px solid #353535; border-radius: 12px; }")
            views_layout = qtw.QVBoxLayout(self.library_views_container)
            views_layout.setContentsMargins(10, 10, 10, 10)
            
            views_layout.addWidget(self.ui.table_clips)
            views_layout.addWidget(self.grid_clips)

            # 5. Putting It All Together
            self.left_master_layout = qtw.QVBoxLayout()
            self.left_master_layout.setContentsMargins(0, 0, 0, 0)
            self.left_master_layout.setSpacing(16)
            
            self.left_master_layout.addLayout(top_bar_layout)
            self.left_master_layout.addWidget(self.library_views_container)
            
            # Insert our new mega-block back into the SAVED old layout.
            if original_parent_layout:
                if original_idx != -1: 
                    original_parent_layout.insertLayout(original_idx, self.left_master_layout)
                else: 
                    original_parent_layout.addLayout(self.left_master_layout)

            # 6. ✨ DYNAMIC TOGGLES UwU ✨
            # Set initial view mode to 'List' instead of 'Grid'
            self.grid_clips.hide()
            self.ui.table_clips.show()
            self.btn_view_list.setStyleSheet(self.toggle_style_active)
            self.btn_view_grid.setStyleSheet(self.toggle_style_inactive)

            def set_view_mode(mode):
                if mode == "list":
                    self.grid_clips.hide()
                    self.ui.table_clips.show()
                    self.btn_view_list.setStyleSheet(self.toggle_style_active)
                    self.btn_view_grid.setStyleSheet(self.toggle_style_inactive)
                else:
                    self.ui.table_clips.hide()
                    self.grid_clips.show()
                    
                    # HARD GEOMETRY RECALCULATION (Pictures won't fly away anymore!)
                    self.grid_clips.doItemsLayout()
                    
                    self.btn_view_list.setStyleSheet(self.toggle_style_inactive)
                    self.btn_view_grid.setStyleSheet(self.toggle_style_active)
                    
                    if self.grid_clips.selectedItems():
                        self.grid_clips.scrollToItem(self.grid_clips.selectedItems()[0])
                    
            self.btn_view_list.clicked.connect(lambda: set_view_mode("list"))
            self.btn_view_grid.clicked.connect(lambda: set_view_mode("grid"))

        # --- UI INJECTION: SORTING PANEL (NEXT TO FILTER BUTTON) ---
        from PySide6.QtWidgets import QLabel, QComboBox

        # 1. Create a text label (like the one in View)
        lbl_sorting = QLabel("Sorting")
        lbl_sorting.setStyleSheet("color: #888888; font-weight: bold; font-family: 'Segoe UI'; font-size: 13px;")

        # 2. Creating a stylish sorting dropdown list
        self.combo_sort = QComboBox()
        self.combo_sort.setCursor(Qt.PointingHandCursor)
        self.combo_sort.setStyleSheet("""
            QComboBox {
                background-color: #383838; 
                color: #ffffff; 
                border: 2px solid #444444; 
                border-radius: 8px;
                padding: 4px 10px; 
                font-weight: bold; 
                font-family: 'Segoe UI'; 
                font-size: 13px; 
                min-height: 24px;
            }
            QComboBox:hover { background-color: #404040; border: 2px solid #6b5a8e; }
            QComboBox::drop-down { border: none; padding-right: 5px; }
            QComboBox QAbstractItemView {
                background-color: #252525; 
                color: white; 
                selection-background-color: #6b5a8e;
                border: 1px solid #444; 
                border-radius: 4px; 
                outline: none; 
                padding: 4px;
            }
        """)

        # 3. Adding elements with attractive icons
        self.combo_sort.addItem(QIcon(get_resource_path("defaultsort.png")), "Default (Don't touch)")
        self.combo_sort.addItem(QIcon(get_resource_path("lettersort1.png")), "Game Name (A - Z)")
        self.combo_sort.addItem(QIcon(get_resource_path("lettersort2.png")), "Game Name (Z - A)")
        self.combo_sort.addItem(QIcon(get_resource_path("lettersort1.png")), "Type (A - Z)")
        self.combo_sort.addItem(QIcon(get_resource_path("lettersort2.png")), "Type (Z - A)")
        self.combo_sort.addItem(QIcon(get_resource_path("datesort1.png")), "Date (Oldest First)")
        self.combo_sort.addItem(QIcon(get_resource_path("datesort2.png")), "Date (Newest First)")
        self.combo_sort.addItem(QIcon(get_resource_path("durationsort1.png")), "Duration (Shortest)")
        self.combo_sort.addItem(QIcon(get_resource_path("durationsort2.png")), "Duration (Longest)")

        self.combo_sort.currentIndexChanged.connect(self.apply_sorting)

        # 4. Locate the filter button and elegantly assemble the panel to its LEFT.
        filter_btn = getattr(self, 'btn_filter_pill', None) or getattr(self.ui, 'btn_filter', None)
        if filter_btn and filter_btn.parentWidget() and filter_btn.parentWidget().layout():
            layout = filter_btn.parentWidget().layout()
            idx = layout.indexOf(filter_btn)
            
            # 4.1. Removing the old button from the main layout (to move it to the new group)
            layout.takeAt(idx)
            
            # 4.2. Creating a separate container for our Sort/Filter group
            from PySide6.QtWidgets import QHBoxLayout, QWidget
            group_widget = QWidget()
            group_layout = QHBoxLayout(group_widget)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(14)
            
            # 4.3. Placing elements into our new super-container
            group_layout.addWidget(lbl_sorting)
            group_layout.addWidget(self.combo_sort)
            
            
            group_layout.addWidget(filter_btn)
            
            # 4.4. Insert a spacer (Stretch) into the main layout to shift everything to the right.
            layout.insertStretch(idx)
            
            # 4.5. Inserting our assembled group back into the main layout
            layout.insertWidget(idx + 1, group_widget)

            
        # "Hide" Arch-Shaped Insert Button
        if hasattr(self.ui, 'settings_tabs'):
            self.ui.settings_tabs.setCurrentIndex(0)
            from PySide6.QtWidgets import QPushButton, QWidget, QHBoxLayout, QVBoxLayout, QFrame, QScrollArea, QSizePolicy
            from PySide6.QtCore import QObject, QEvent
            
            # 1. Hide the old tab bar
            self.ui.settings_tabs.tabBar().hide()
            
            # STEP 1
            # Apply transparency ONLY to the page itself using its ID, so as not to break the buttons inside
            for i in range(self.ui.settings_tabs.count()):
                widget = self.ui.settings_tabs.widget(i)
                if widget:
                    obj_name = widget.objectName()
                    if obj_name:
                        widget.setStyleSheet(f"QWidget#{obj_name} {{ background: transparent; border: none; }}")
                    else:
                        widget.setAttribute(Qt.WA_TranslucentBackground)
            
            # --- REMEMBERING THE OLD LOCATION ---
            parent_widget = self.ui.settings_tabs.parentWidget()
            parent_layout = parent_widget.layout() if parent_widget else None
            insert_idx = -1
            if parent_layout:
                insert_idx = parent_layout.indexOf(self.ui.settings_tabs)
                if insert_idx != -1:
                    parent_layout.removeWidget(self.ui.settings_tabs)
            
            self.ui.settings_tabs.setParent(None)
            
            # 2. MAIN CONTAINER
            self.neo_wrapper = QWidget()
            self.neo_wrapper.setStyleSheet("background: transparent;")
            self.neo_wrapper.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            
            neo_layout = QHBoxLayout(self.neo_wrapper)
            neo_layout.setContentsMargins(0, 0, 0, 0)
            neo_layout.setSpacing(15)
            
            # 3. LEFT CIRCLE (Sidebar)
            sidebar_frame = QFrame()
            sidebar_frame.setFixedWidth(220)
            sidebar_frame.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            sidebar_frame.setStyleSheet("""
                QFrame { background-color: #2d2d2d; border-radius: 16px; border: 1px solid #383838; }
            """)
            sidebar_layout = QVBoxLayout(sidebar_frame)
            sidebar_layout.setAlignment(Qt.AlignTop)
            sidebar_layout.setContentsMargins(10, 15, 10, 15)
            sidebar_layout.setSpacing(10)
            
            pill_style = """
                QPushButton {
                    background-color: transparent; color: #a0a0a0;
                    border: 2px solid transparent; border-radius: 14px;
                    padding: 10px 15px; text-align: left; font-size: 14px; font-weight: 700;
                }
                QPushButton:hover { background-color: #383838; border: 2px solid #5a4b7a; color: #e0e0e0; }
                QPushButton:checked { background-color: #383838; border: 2px solid #8e7cc3; color: #ffffff; }
            """
            
            self.neo_nav_buttons = []
            custom_names = ["ℹ️  Source Info", "🎬  Video Settings", "🎵  Audio Settings", "🚀  Export Settings"]
            
            for i in range(self.ui.settings_tabs.count()):
                text = custom_names[i] if i < len(custom_names) else self.ui.settings_tabs.tabText(i)
                btn = QPushButton(text)
                btn.setCheckable(True)
                btn.setAutoExclusive(True)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setStyleSheet(pill_style)
                btn.clicked.connect(lambda checked, idx=i: self.ui.settings_tabs.setCurrentIndex(idx))
                sidebar_layout.addWidget(btn)
                self.neo_nav_buttons.append(btn)
                
            if self.neo_nav_buttons:
                self.neo_nav_buttons[0].setChecked(True)
                
            self.ui.settings_tabs.currentChanged.connect(
                lambda idx: self.neo_nav_buttons[idx].setChecked(True) if idx < len(self.neo_nav_buttons) else None
            )
            
            neo_layout.addWidget(sidebar_frame)
            
            # 4. Right circle with scrol
            self.right_scroll = QScrollArea()
            self.right_scroll.setWidgetResizable(True)
            self.right_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            
            self.right_scroll.setStyleSheet("""
                QScrollArea { 
                    background-color: #2d2d2d; 
                    border-radius: 16px; 
                    border: 1px solid #383838;
                }
                QWidget#qt_scrollarea_viewport {
                    background: transparent;
                    border: none;
                }
                QScrollBar:vertical {
                    background: transparent;
                    width: 12px;
                    margin: 15px 5px 15px 0px;
                }
                QScrollBar::handle:vertical {
                    background: #5a4b7a;
                    min-height: 30px;
                    border-radius: 5px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #8e7cc3;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px; 
                }
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                    background: none;
                }
            """)
            
            self.ui.settings_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.ui.settings_tabs.setStyleSheet("""
                QTabWidget { background: transparent; border: none; }
                QTabWidget::pane { border: none; background: transparent; }
                QTabWidget QLabel { color: #cccccc; font-weight: bold; background: transparent; }
                
                
                QTabWidget QPushButton {
                    background-color: #383838; color: #ffffff; 
                    border: 2px solid #444444; border-radius: 10px; 
                    padding: 6px 15px; font-weight: bold;
                }
                QTabWidget QPushButton:hover { background-color: #404040; border: 2px solid #6b5a8e; }
                QTabWidget QPushButton:pressed { background-color: #2d2d2d; border: 2px solid #b29ae7; }
                
                
                QTabWidget QComboBox, QTabWidget QLineEdit {
                    background-color: #383838; color: #ffffff; border: 2px solid #444444; 
                    border-radius: 12px; padding: 6px 14px; font-size: 12px; font-weight: bold;
                }
                QTabWidget QComboBox:hover, QTabWidget QLineEdit:hover { border: 2px solid #6b5a8e; background-color: #404040; }
                QTabWidget QComboBox:focus, QTabWidget QLineEdit:focus { border: 2px solid #b29ae7; background-color: #3a324a; }
                QTabWidget QComboBox::drop-down { border: none; width: 30px; }
                QTabWidget QComboBox::down-arrow {
                    image: none; border-left: 5px solid transparent; border-right: 5px solid transparent;
                    border-top: 5px solid #b29ae7; margin-right: 10px;
                }
                QTabWidget QComboBox QAbstractItemView {
                    background-color: #2d2d2d; color: #ffffff; border: 2px solid #b29ae7;
                    border-radius: 8px; selection-background-color: #b29ae7; selection-color: #111111; outline: none;
                }
                
               
                QTabWidget QCheckBox { color: #cccccc; font-weight: bold; spacing: 8px; background: transparent; }
                QTabWidget QCheckBox::indicator {
                    width: 20px; height: 20px; border-radius: 10px; border: 2px solid #444444; background-color: #383838;
                }
                QTabWidget QCheckBox::indicator:hover { border: 2px solid #6b5a8e; }
                QTabWidget QCheckBox::indicator:checked { background-color: #b29ae7; border: 2px solid #b29ae7; }
                
               
                QTabWidget QRadioButton { color: #cccccc; font-weight: bold; spacing: 8px; background: transparent; }
                QTabWidget QRadioButton::indicator {
                    width: 18px; height: 18px; border-radius: 9px; border: 2px solid #444444; background-color: #383838;
                }
                QTabWidget QRadioButton::indicator:hover { border: 2px solid #6b5a8e; }
                QTabWidget QRadioButton::indicator:checked { background-color: #b29ae7; border: 2px solid #b29ae7; }
            """)
            
            # Place tabs in the scroll area
            self.right_scroll.setWidget(self.ui.settings_tabs)
            
            # --- SAFE MASK (QRegion) LIKE IN THE PLAYER ---
            class RoundedCornerFilter(QObject):
                def eventFilter(self, obj, event):
                    if event.type() == QEvent.Type.Resize:
                        if obj.width() > 0 and obj.height() > 0:
                            try:
                                from PySide6.QtGui import QPainterPath, QRegion
                                path = QPainterPath()
                                path.addRoundedRect(0.0, 0.0, float(obj.width()), float(obj.height()), 16.0, 16.0)
                                obj.setMask(QRegion(path.toFillPolygon().toPolygon()))
                            except Exception:
                                pass
                    return False
            
            self.corner_mask = RoundedCornerFilter(self.right_scroll)
            self.right_scroll.installEventFilter(self.corner_mask)
            
            neo_layout.addWidget(self.right_scroll)
            
            # 5. Placing our wrapper back in the original location without conflicts
            if parent_layout:
                if insert_idx != -1:
                    parent_layout.insertWidget(insert_idx, self.neo_wrapper)
                else:
                    parent_layout.addWidget(self.neo_wrapper)
        
        # Codec list
        if hasattr(self.ui, 'combo_codec'):
            self.ui.combo_codec.clear()
            self.ui.combo_codec.addItem("H.264 (AVC)")
            self.ui.combo_codec.addItem("H.265 (HEVC)")
            self.ui.combo_codec.setCurrentIndex(1) # Default is H.265
            
        # Update the bitrate list when changing resolution
        if hasattr(self.ui, 'combo_quality'):
            self.ui.combo_quality.currentTextChanged.connect(self.update_bitrate_options) 
        
        # 4. BINDING BUTTONS TO FUNCTIONS
        # --- UI INJECTION: COPY BUTTONS ---
        from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget, QSizePolicy
        from PySide6.QtGui import QClipboard
        
        copy_icon_path = get_resource_path("copyfile.png")
        
        # 1. Copy Button for Source
        if hasattr(self.ui, 'source_label'):
            src_container = QWidget()
            src_layout = QHBoxLayout(src_container)
            src_layout.setContentsMargins(0, 0, 0, 0)
            src_layout.setSpacing(6)
            
            self.ui.source_label.parentWidget().layout().replaceWidget(self.ui.source_label, src_container)
            
            self.btn_copy_src = QPushButton()
            self.btn_copy_src.setFixedSize(20, 20)
            self.btn_copy_src.setToolTip("Copy raw source paths")
            self.btn_copy_src.setStyleSheet("background: transparent; border: none;")
            self.btn_copy_src.setCursor(Qt.PointingHandCursor)
            
            if os.path.exists(copy_icon_path): 
                self.btn_copy_src.setIcon(QIcon(copy_icon_path))
            else: 
                self.btn_copy_src.setText("📋")
                
            self.btn_copy_src.clicked.connect(lambda: QApplication.clipboard().setText(getattr(self, 'current_source_raw_paths', "")))
            self.btn_copy_src.hide() # Hidden by default
            
            self.ui.source_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            src_layout.addWidget(self.ui.source_label)
            src_layout.addWidget(self.btn_copy_src, alignment=Qt.AlignTop)
            src_layout.addStretch()

        # 2. Copy Button for Rendered Video Location
        if hasattr(self.ui, 'label_location'):
            loc_container = QWidget()
            loc_layout = QHBoxLayout(loc_container)
            loc_layout.setContentsMargins(0, 0, 0, 0)
            loc_layout.setSpacing(6)
            
            self.ui.label_location.parentWidget().layout().replaceWidget(self.ui.label_location, loc_container)
            
            # --- replace standard label with our Smart Label ---
            smart_label = ElidedLabel()
            smart_label.setStyleSheet(self.ui.label_location.styleSheet())
            smart_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.ui.label_location.deleteLater() # Destroy the old label
            self.ui.label_location = smart_label # Hijack the variable!
            
            
            self.btn_copy_loc = QPushButton()
            self.btn_copy_loc.setFixedSize(20, 20)
            self.btn_copy_loc.setToolTip("Copy raw output path")
            self.btn_copy_loc.setStyleSheet("background: transparent; border: none;")
            self.btn_copy_loc.setCursor(Qt.PointingHandCursor)
            
            if os.path.exists(copy_icon_path): 
                self.btn_copy_loc.setIcon(QIcon(copy_icon_path))
            else: 
                self.btn_copy_loc.setText("📋")
                
            self.btn_copy_loc.clicked.connect(lambda: QApplication.clipboard().setText(getattr(self, 'current_output_file', "")))
            self.btn_copy_loc.hide() # Hidden by default
            
            loc_layout.addWidget(self.ui.label_location)
            loc_layout.addWidget(self.btn_copy_loc, alignment=Qt.AlignVCenter)

        # --- UI INJECTION: REFRESH BUTTON ---
        from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QPushButton, QFrame, QSizePolicy
        
        # --- CIRCLE AND BUTTON STYLES ---
        pill_style = """
            QFrame { 
                background-color: #2d2d2d; 
                border-radius: 16px; 
                border: 1px solid #383838; 
            }
        """
        
        unified_table_style = """
            QPushButton { 
                background-color: #383838; 
                color: #ffffff; 
                border: 2px solid #444444; 
                border-radius: 14px; 
                font-family: 'Segoe UI', Arial, sans-serif;
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

        # 1. CREATE ONE COMMON MEGA-CAPSULATE
        mega_pill = QFrame()
        mega_pill.setStyleSheet(pill_style)
        mega_layout = QVBoxLayout(mega_pill)
        mega_layout.setContentsMargins(6, 6, 6, 6) # Slightly increased the margins from the edges of the circle
        mega_layout.setSpacing(4) # Distance between floors

        #2. CREATE TWO FLOORS INSIDE THE CAPSULE
        top_row = QHBoxLayout()
        top_row.setSpacing(4) # Distance between buttons
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(4)
        
        mega_layout.addLayout(top_row)
        mega_layout.addLayout(bottom_row)

        #3. PUT THE MEGA-CAPSULE ON THE VERY TOP (INSTEAD OF THE OLD FOLDER BUTTON)
        old_browse_btn = self.ui.btn_browse
        if old_browse_btn.parentWidget() and old_browse_btn.parentWidget().layout():
            old_browse_btn.parentWidget().layout().replaceWidget(old_browse_btn, mega_pill)
            
        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.setToolTip("Rescan folder for new clips")
        
        #4. TEAR ABOUT AND UPDATE FROM THEIR OLD PLACES
        btn_about = getattr(self.ui, 'btn_about', None)
        btn_update = getattr(self.ui, 'btn_update_check', None)
        
        if btn_about and btn_about.parentWidget() and btn_about.parentWidget().layout():
            btn_about.parentWidget().layout().removeWidget(btn_about)
        if btn_update and btn_update.parentWidget() and btn_update.parentWidget().layout():
            btn_update.parentWidget().layout().removeWidget(btn_update)
            
        # 5. Color the buttons and add cursors
        old_browse_btn.setStyleSheet(unified_table_style)
        self.btn_refresh.setStyleSheet(unified_table_style)
        old_browse_btn.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        
        if btn_about:
            btn_about.setStyleSheet(unified_table_style)
            btn_about.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn_about.setCursor(Qt.PointingHandCursor)
        if btn_update:
            btn_update.setStyleSheet(unified_table_style)
            btn_update.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn_update.setCursor(Qt.PointingHandCursor)
            
        # 6. LAY OUT THE BUTTONS BY FLOORS (70/30 on top, 50/50 on the bottom)
        top_row.addWidget(old_browse_btn, 7)
        top_row.addWidget(self.btn_refresh, 3)
        
        if btn_about: bottom_row.addWidget(btn_about, 5)
        if btn_update: bottom_row.addWidget(btn_update, 5)
        
        # 7. RECOVERING SIGNALS (Presses)
        self.btn_refresh.clicked.connect(self.scan_clips)
        self.ui.btn_browse.clicked.connect(self.choose_folder)
        if hasattr(self.ui, 'destination_button'):
            self.ui.destination_button.clicked.connect(self.choose_destination)
        if btn_about: btn_about.clicked.connect(self.show_about_dialog)
        if btn_update: btn_update.clicked.connect(self.check_for_updates)
        self.ui.btn_start.clicked.connect(self.start_render_thread)
        self.ui.btn_start.setEnabled(False)



        try:
            import PySide6.QtWidgets as qtw
            import PySide6.QtCore as qtc

            # 1. OUR ORIGINAL, BEAUTIFUL STYLES

            # Logs 
            btn_logs_style = """
                QPushButton { font-family: 'Segoe UI'; font-size: 12px; font-weight: bold; background-color: #383838; color: #ffffff; border: 2px solid #444444; border-radius: 8px; padding: 6px 14px; }
                QPushButton:hover { background-color: #404040; border: 2px solid #6b5a8e; }
                QPushButton:pressed { background-color: #3a324a; border: 2px solid #b29ae7; }
                QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }
                QPushButton::menu-indicator { image: none; }
            """
            
            # Start (Green — OUR BENCHMARK)
            start_btn_style = """
                QPushButton { font-family: 'Segoe UI'; font-size: 12px; font-weight: bold; background-color: #2e6b32; color: #ffffff; border: 2px solid #3e8e41; border-radius: 8px; padding: 6px 14px; }
                QPushButton:hover { background-color: #3e8e41; border: 2px solid #57c75b; }
                QPushButton:pressed { background-color: #235226; border: 2px solid #3e8e41; }
                QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }
            """

            # Pause (Yellow-Orange Copy of the Green One)
            btn_pause_style = """
                QPushButton { font-family: 'Segoe UI'; font-size: 12px; font-weight: bold; background-color: #8c7314; color: #ffffff; border: 2px solid #a88b11; border-radius: 8px; padding: 6px 14px; }
                QPushButton:hover { background-color: #a88b11; border: 2px solid #c9a716; }
                QPushButton:pressed { background-color: #6b570d; border: 2px solid #a88b11; }
                QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }
                QPushButton::menu-indicator { image: none; }
            """
            
            # Cancellation (Red copy of the green one)
            btn_cancel_style = """
                QPushButton { font-family: 'Segoe UI'; font-size: 12px; font-weight: bold; background-color: #8a2525; color: #ffffff; border: 2px solid #a82e2e; border-radius: 8px; padding: 6px 14px; }
                QPushButton:hover { background-color: #a82e2e; border: 2px solid #cc3939; }
                QPushButton:pressed { background-color: #661a1a; border: 2px solid #a82e2e; }
                QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }
                QPushButton::menu-indicator { image: none; }
            """

            # FORCE INJECT STYLES DIRECTLY INTO BUTTONS
            if hasattr(self.ui, 'btn_start'): 
                self.ui.btn_start.setStyleSheet(start_btn_style)
            elif hasattr(self.ui, 'btn_render'): 
                self.ui.btn_render.setStyleSheet(start_btn_style)
                
            if hasattr(self.ui, 'btn_pause'): 
                self.ui.btn_pause.setStyleSheet(btn_pause_style)
                
            if hasattr(self.ui, 'btn_cancel'): 
                self.ui.btn_cancel.setStyleSheet(btn_cancel_style)
                
            if hasattr(self.ui, 'btn_logs'): 
                self.ui.btn_logs.setStyleSheet(btn_logs_style)

            # 2. Remove Padding from the Parent Element for Perfect Width Symmetry
            parent_widget = self.ui.btn_start.parentWidget() if hasattr(self.ui, 'btn_start') else None
            if parent_widget:
                parent_widget.setStyleSheet("background: transparent; border: none;")
                if parent_widget.layout():
                    # Resetting the outer margins so that the monolith aligns perfectly with the width of the top tabs.
                    parent_widget.layout().setContentsMargins(0, 0, 0, 0)

            # 3. Creating Our Single Monolithic Circle
            self.render_dashboard = qtw.QFrame()
            self.render_dashboard.setStyleSheet("""
                QFrame { background-color: #2d2d2d; border: 1px solid #353535; border-radius: 12px; }
                QLabel { border: none; background: transparent; }
            """)
            
            dash_layout = qtw.QVBoxLayout(self.render_dashboard)
            dash_layout.setContentsMargins(18, 16, 18, 16)
            dash_layout.setSpacing(12)

            # TOP ROW 
            top_row = qtw.QHBoxLayout()
            
            if hasattr(self.ui, 'label_short_summary'):
                self.ui.label_short_summary.hide() 
                
                self.bottom_icon_label = qtw.QLabel()
                self.bottom_icon_label.setFixedSize(24, 24)
                
                self.bottom_text_label = qtw.QLabel()
                self.bottom_text_label.setStyleSheet("color: #e0e0e0; font-size: 13px;")
                
                top_row.addWidget(self.bottom_icon_label, 0, qtc.Qt.AlignVCenter)
                top_row.addWidget(self.bottom_text_label, 0, qtc.Qt.AlignVCenter)
                
                # Instant reset generator function
                def reset_bottom_summary():
                    css_icon = get_resource_path("unknown_icon.png").replace('\\', '/')
                    
                    # 1. Reset the bottom panel
                    self.bottom_icon_label.setStyleSheet(f"image: url('{css_icon}'); background: transparent; border: none;")
                    self.bottom_text_label.setText("<b>Select a clip to begin...</b>")
                    
                    # 2. Reset the top panel
                    if hasattr(self, 'custom_icon_label') and hasattr(self, 'custom_text_label'):
                        self.custom_icon_label.setStyleSheet(f"image: url('{css_icon}'); background: transparent; border: none;")
                        self.custom_text_label.setText("Select a clip to preview...")

                    css_logo_main = get_resource_path("logo.png").replace('\\', '/')
                    if hasattr(self, 'place_logo') and hasattr(self, 'place_text'):
                        self.place_logo.setStyleSheet(f"image: url('{css_logo_main}'); background: transparent; border: none;")
                        self.place_text.setText("Please select a clip from the library")
                        self.place_text.setStyleSheet("color: #888888; font-size: 14px; font-weight: bold; margin-top: 15px;")
                    
                self.reset_bottom_summary = reset_bottom_summary
                self.reset_bottom_summary()
            
            top_row.addStretch() 
            
            if hasattr(self.ui, 'label_status'):
                self.ui.label_status.setStyleSheet("color: #b29ae7; font-family: 'Segoe UI'; font-weight: bold; font-size: 12px;")
                self.ui.label_status.setAlignment(qtc.Qt.AlignRight | qtc.Qt.AlignVCenter)
                top_row.addWidget(self.ui.label_status)
            dash_layout.addLayout(top_row)

            # 2nd Row (6px Laser Line + Percentages)
            mid_row = qtw.QHBoxLayout()
            if hasattr(self.ui, 'progress_render'):
                self.ui.progress_render.setTextVisible(False)
                self.ui.progress_render.setRange(0, 1000)
                self.ui.progress_render.setStyleSheet("""
                    QProgressBar { background-color: #414141; border: none; border-radius: 3px; min-height: 6px; max-height: 6px; }
                    QProgressBar::chunk { background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #6b5a8e, stop:1 #b29ae7); border-radius: 3px; }
                """)
                mid_row.addWidget(self.ui.progress_render)
                
            if not hasattr(self, 'label_pct'):
                self.label_pct = qtw.QLabel("0%")
            self.label_pct.setStyleSheet("color: #ffffff; font-family: 'Segoe UI'; font-weight: bold; font-size: 13px; margin-left: 8px;")
            mid_row.addWidget(self.label_pct)
            dash_layout.addLayout(mid_row)

            # BOTTOM ROW: PERFECTLY ALIGNED, FULL-WIDTH BUTTONS
            btn_row = qtw.QHBoxLayout()
            btn_row.setContentsMargins(0, 0, 0, 0)
            btn_row.setSpacing(12) # Beautiful, even spacing between buttons
            
            # Strict Sequence
            buttons_queue = ['btn_start', 'btn_pause', 'btn_cancel', 'btn_logs']
            
            for btn_name in buttons_queue:
                if hasattr(self.ui, btn_name):
                    btn = getattr(self.ui, btn_name)
                    btn.setSizePolicy(qtw.QSizePolicy.Expanding, qtw.QSizePolicy.Fixed)
                    btn.setMinimumHeight(36) 
                    

                    # 1. Take the old button style
                    old_style = btn.styleSheet()
                    
                    # 2. Hardcode the 13px font, just like on the Refresh button!
                    btn.setStyleSheet(old_style + "\nQPushButton { font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; font-weight: bold; }")
                    
                    btn_row.addWidget(btn)

            dash_layout.addLayout(btn_row)

            # 4. Container Assembly
            if parent_widget and parent_widget.layout():
                parent_widget.layout().addWidget(self.render_dashboard)

        except Exception as e:
            print(f"Error building ultimate monolithic dashboard: {e}")
        
        
        # --- UI INJECTION: COPY BUTTONS ---
        from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget, QSizePolicy
        from PySide6.QtGui import QClipboard
        
        copy_icon_path = get_resource_path("copyfile.png")
        
        # 1. Copy Button for Source
        if hasattr(self.ui, 'source_label'):
            src_container = QWidget()
            src_layout = QHBoxLayout(src_container)
            src_layout.setContentsMargins(0, 0, 0, 0)
            src_layout.setSpacing(6) # Micro-gap between text and icon
            
            self.ui.source_label.parentWidget().layout().replaceWidget(self.ui.source_label, src_container)
            
            self.btn_copy_src = QPushButton()
            self.btn_copy_src.setFixedSize(20, 20)
            self.btn_copy_src.setToolTip("Copy raw source paths")
            self.btn_copy_src.setStyleSheet("background: transparent; border: none;")
            self.btn_copy_src.setCursor(Qt.PointingHandCursor)
            
            if os.path.exists(copy_icon_path): self.btn_copy_src.setIcon(QIcon(copy_icon_path))
            else: self.btn_copy_src.setText("📋")
                
            self.btn_copy_src.clicked.connect(lambda: QApplication.clipboard().setText(getattr(self, 'current_source_raw_paths', "")))
            self.btn_copy_src.hide() # Hidden by default (No clip = no button)
            
            self.ui.source_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            src_layout.addWidget(self.ui.source_label)
            src_layout.addWidget(self.btn_copy_src, alignment=Qt.AlignTop)
            src_layout.addStretch() # MAGIC: Pushes everything to the left wall!

        # 2. Copy Button for Rendered Video Location
        if hasattr(self.ui, 'label_location'):
            loc_container = QWidget()
            loc_layout = QHBoxLayout(loc_container)
            loc_layout.setContentsMargins(0, 0, 0, 0)
            loc_layout.setSpacing(6)
            
            self.ui.label_location.parentWidget().layout().replaceWidget(self.ui.label_location, loc_container)
            
            self.btn_copy_loc = QPushButton()
            self.btn_copy_loc.setFixedSize(20, 20)
            self.btn_copy_loc.setToolTip("Copy raw output path")
            self.btn_copy_loc.setStyleSheet("background: transparent; border: none;")
            self.btn_copy_loc.setCursor(Qt.PointingHandCursor)
            
            if os.path.exists(copy_icon_path): self.btn_copy_loc.setIcon(QIcon(copy_icon_path))
            else: self.btn_copy_loc.setText("📋")
                
            self.btn_copy_loc.clicked.connect(lambda: QApplication.clipboard().setText(getattr(self, 'current_output_file', "")))
            self.btn_copy_loc.hide() # Hidden by default (No clip = no button)
            
            self.ui.label_location.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            loc_layout.addWidget(self.ui.label_location)
            loc_layout.addWidget(self.btn_copy_loc, alignment=Qt.AlignVCenter)
            loc_layout.addStretch() # Pushes everything to the left wall!

        # --- FIXING THE INTERFACE AND PLAYER ---
        # 1. Give the right panel some breathing room
        right_layout = self.ui.right_panel.layout()
        if right_layout:
            right_layout.setContentsMargins(12, 12, 12, 12) 
            right_layout.setSpacing(8)

        # 2: Taming MPV Player and creating a Border Wrapper
        from PySide6.QtWidgets import QFrame, QStackedLayout, QVBoxLayout, QLabel
        
        # --- 1. FAKE BLACK BACKGROUND (Fills the entire space) ---
        self.video_wrapper = QFrame()
        self.video_wrapper.setStyleSheet("background-color: transparent; border: none;") 
        self.video_wrapper.installEventFilter(self)
        
        parent_layout = self.ui.video_container.parentWidget().layout()
        parent_layout.replaceWidget(self.ui.video_container, self.video_wrapper)
        
        # A layout that keeps the actual video strictly centered
        wrapper_layout = QVBoxLayout(self.video_wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- 2. LIVE VIDEO CONTAINER (Strictly 16:9) ---
        self.aspect_frame = QFrame()
        # Default 3px transparent border to prevent video flickering during cropping.
        self.aspect_frame.setStyleSheet("background-color: #000000; border: none; border-radius: 0px;")
        wrapper_layout.addWidget(self.aspect_frame)
        
        # 3. STACK WITH PLAYER AND PLUG
        self.video_stack = QStackedLayout(self.aspect_frame)
        self.video_stack.setContentsMargins(3, 3, 3, 3) # Offset to avoid hitting the frame
        
        # The Real Player
        self.ui.video_container.setStyleSheet("background-color: transparent; border: none;")
        self.video_stack.addWidget(self.ui.video_container)
        
        # 2 Placeholder
        self.placeholder_frame = QFrame()
        self.placeholder_frame.setStyleSheet("""
            QFrame {
                background-color: #1e1e1e; 
                border-radius: 0px; 
                border: 1px solid #333333;
            }
        """)
        place_layout = QVBoxLayout(self.placeholder_frame)
        place_layout.setAlignment(Qt.AlignCenter)
        
        self.place_logo = QLabel()
        logo_path = get_resource_path("logo.png")
        if os.path.exists(logo_path):
            from PySide6.QtGui import QPixmap
            self.place_logo.setPixmap(QPixmap(logo_path).scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.place_logo.setAlignment(Qt.AlignCenter)
        
        self.place_text = QLabel("Please select a clip from the library")
        self.place_text.setStyleSheet("color: #888888; font-size: 14px; font-weight: bold; margin-top: 15px;")
        self.place_text.setAlignment(Qt.AlignCenter)
        
        place_layout.addWidget(self.place_logo)
        place_layout.addWidget(self.place_text)
        self.video_stack.addWidget(self.placeholder_frame)
        
        # When starting, show MAP 2 (Stub)
        self.video_stack.setCurrentWidget(self.placeholder_frame)

        # --- CREATE A TOP PANEL  ---
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton
        
        self.player_header_frame = QFrame()
        self.player_header_frame.setStyleSheet("""
            QFrame {
                background-color: #2d2d2d;
                border-radius: 6px;
            }
        """)
        header_layout = QHBoxLayout(self.player_header_frame)
        header_layout.setContentsMargins(10, 8, 10, 8)
        header_layout.setSpacing(10)
        
        self.custom_icon_label = QLabel()
        self.custom_icon_label.setFixedSize(24, 24)
        self.custom_icon_label.setPixmap(QIcon(get_resource_path("unknown_icon.png")).pixmap(24, 24))
        
        self.custom_text_label = QLabel("Select a clip to preview...")
        self.custom_text_label.setStyleSheet("color: white; font-size: 13px; font-weight: bold;")
        
        header_layout.addWidget(self.custom_icon_label)
        header_layout.addWidget(self.custom_text_label)
        header_layout.addStretch()

        
        
        from PySide6.QtWidgets import QPushButton
        self.btn_close_clip = QPushButton("❌")
        self.btn_close_clip.setFixedSize(24, 24)
        self.btn_close_clip.setCursor(Qt.PointingHandCursor)
        self.btn_close_clip.setToolTip("Close Clip")
        self.btn_close_clip.setStyleSheet("""
            QPushButton {
                background-color: transparent; 
                border: none;
                border-radius: 6px; 
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #9e3636; 
            }
            QPushButton:pressed {
                background-color: #6b2424; 
            }
        """)
        self.btn_close_clip.hide()
        self.btn_close_clip.clicked.connect(self.close_current_clip)
        
        header_layout.addWidget(self.btn_close_clip)

        right_layout = self.ui.right_panel.layout()
        if right_layout:
            right_layout.insertWidget(0, self.player_header_frame)
            
        # Hide old labels from Qt Designer
        if hasattr(self.ui, 'label_player_header'):
            self.ui.label_player_header.hide()
        if hasattr(self.ui, 'label_player_icon'):
            self.ui.label_player_icon.hide()


        player_style = """
        QPushButton#btn_play, QPushButton#btn_skip_back, QPushButton#btn_skip_forward {
            background-color: transparent;
            border: none;
            border-radius: 4px;
            padding: 5px;
        }
        QPushButton#btn_play:hover, QPushButton#btn_skip_back:hover, QPushButton#btn_skip_forward:hover {
            background-color: rgba(255, 255, 255, 25); 
        }
        QPushButton#btn_play:pressed, QPushButton#btn_skip_back:pressed, QPushButton#btn_skip_forward:pressed {
            background-color: rgba(255, 255, 255, 40);
        }

        
        QSlider#slider_timeline::groove:horizontal {
            border-radius: 2px;
            height: 4px;
            background: rgba(255, 255, 255, 50); 
        QSlider#slider_timeline {
            margin-left: 15px;  
            margin-right: 5px;  
        }
        QSlider#slider_timeline::sub-page:horizontal {
            background: #1a9fff;
            border-radius: 2px;
        }
        QSlider#slider_timeline::handle:horizontal {
            background: #ffffff;
            width: 12px;
            height: 12px;
            margin: -4px 0; 
            border-radius: 6px;
        }
        QSlider#slider_timeline::handle:horizontal:hover {
            transform: scale(1.2);
            background: #1a9fff; 
        }
        """
        self.ui.right_panel.setStyleSheet(player_style)

        # --- SETTING UP BUTTON ICONS ---
        #1: Erase old text
        self.ui.btn_play.setText("")
        self.ui.btn_skip_back.setText("")
        self.ui.btn_skip_forward.setText("")

        # 2. Assign start images (pay attention to the exact file names!)
        self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_play.png")))
        self.ui.btn_skip_back.setIcon(QIcon(get_resource_path("less15.png")))
        self.ui.btn_skip_forward.setIcon(QIcon(get_resource_path("more15.png")))
        
        # 3. Make them larger so that all the beauty is clearly visible (you can play with the numbers 32, 32)
        self.ui.btn_play.setIconSize(QSize(32, 32))
        self.ui.btn_skip_back.setIconSize(QSize(32, 32))
        self.ui.btn_skip_forward.setIconSize(QSize(32, 32))

        # --- NEXT-GEN TIMELINE & CONTROLS UI REBUILD ---
        from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QFrame
        
        # 1. Mercilessly destroy the old Windows slider
        if hasattr(self.ui, 'slider_timeline'):
            self.ui.slider_timeline.setParent(None)
            self.ui.slider_timeline.deleteLater()
            delattr(self.ui, 'slider_timeline')

        # 2. Adjust button sizes (Make Play button bigger and bolder)
        self.ui.btn_play.setIconSize(QSize(48, 48))
        self.ui.btn_skip_back.setIconSize(QSize(32, 32))
        self.ui.btn_skip_forward.setIconSize(QSize(32, 32))

        # 3. Locate the original horizontal layout to hijack it
        right_layout = self.ui.right_panel.layout()
        if right_layout:
            controls_index = -1
            for i in range(right_layout.count()):
                item = right_layout.itemAt(i)
                if item.layout() and item.layout().objectName() == "layout_player_controls":
                    controls_index = i
                    break
                    
            if controls_index != -1:
                old_controls_layout = right_layout.itemAt(controls_index).layout()
                
                # Extract our widgets from the old layout
                while old_controls_layout.count():
                    item = old_controls_layout.takeAt(0)
                    if item.widget():
                        item.widget().setParent(None) 
                        
                # 4. Create a styled QFrame container for the footer (matches the header panel)
                self.player_footer_frame = QFrame()
                self.player_footer_frame.setObjectName("HudFrame")
                self.player_footer_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                
                # Hard height limit (so the panel doesn't bulge like in the photo)
                from PySide6.QtWidgets import QSizePolicy
                self.player_footer_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
                
                self.player_footer_frame.setStyleSheet("""
                    #HudFrame {
                        background-color: #2d2d2d;
                        border-radius: 6px;
                    }
                """)
                
                v_layout = QVBoxLayout(self.player_footer_frame)
                v_layout.setContentsMargins(15, 12, 15, 12)
                v_layout.setSpacing(5)
                
                # ROW 1: The Custom Timeline
                if not hasattr(self, 'custom_timeline'):
                    self.custom_timeline = CustomTimelineWidget()
                v_layout.addWidget(self.custom_timeline)
                v_layout.addSpacing(6)
                # ROW 2: The Time Label AND Theater Button (Perfectly centered)
                time_layout = QHBoxLayout()
                
                # --- IRONCLAD CENTERING (3 EQUAL BLOCKS) ---
                
                # 1. LEFT BLOCK (Volume & Speed)
                left_wrap = QWidget()
                lw = QHBoxLayout(left_wrap)
                lw.setContentsMargins(0, 0, 0, 0)
                lw.setSpacing(10) # Gap between volume and speed buttons
                
                self.volume_control = VolumeControlWidget(self.player_footer_frame)
                self.volume_control.slider.valueChanged.connect(self.set_vlc_volume)
                
                self.speed_control = SpeedControlWidget(self.player_footer_frame)
                self.speed_control.slider.valueChanged.connect(self.set_vlc_speed)
                
                lw.addWidget(self.volume_control, alignment=Qt.AlignLeft | Qt.AlignVCenter)
                lw.addWidget(self.speed_control, alignment=Qt.AlignLeft | Qt.AlignVCenter)
                lw.addStretch() # Pushes both buttons nicely to the left!
                
                # 2. CENTER BLOCK (Timer)
                center_wrap = QWidget()
                cw = QHBoxLayout(center_wrap)
                cw.setContentsMargins(0, 0, 0, 0)
                self.ui.label_time.setParent(self.player_footer_frame)
                self.ui.label_time.setAlignment(Qt.AlignCenter)
                self.ui.label_time.setStyleSheet("color: #cccccc; font-size: 13px; font-weight: bold; background: transparent;")
                cw.addWidget(self.ui.label_time, alignment=Qt.AlignCenter)
                
                # 3. RIGHT BLOCK (Theater + trim buttons)
                right_wrap = QWidget()
                rw = QHBoxLayout(right_wrap)
                rw.setContentsMargins(0, 0, 0, 0)
                rw.setSpacing(10) # Space between buttons
                
                from PySide6.QtWidgets import QPushButton
                
                # --- TRIM BUTTON (DUAL PURPOSE) ---
                self.btn_trim = QPushButton()
                self.btn_trim.setParent(self.player_footer_frame)
                self.btn_trim.setFixedHeight(30)
                self.btn_trim.setCursor(Qt.PointingHandCursor)
                
                # Apply a slightly golden premium style
                self.btn_trim.setStyleSheet("background-color: #cfa94a; color: black; border-radius: 15px; padding: 0 12px; font-weight: bold;")
                
                # Try to load custom scissors icon
                trim_icon_path = get_resource_path("trim_icon.png")
                if os.path.exists(trim_icon_path):
                    self.btn_trim.setIcon(QIcon(trim_icon_path))
                    self.btn_trim.setText(" Trim")
                else:
                    self.btn_trim.setText("✂️ Trim")
                
                # --- THEATER & FULLSCREEN PILL CONTAINER ---
                self.pill_container = QFrame()
                # Elegant dark background with full border control
                self.pill_container.setStyleSheet("QFrame { background-color: #4e4e4e; border-radius: 20px; border: none; }")
                
                pill_layout = QHBoxLayout(self.pill_container)
                # Add outer padding inside the pill (5px left/right) and 4px spacing between buttons
                pill_layout.setContentsMargins(5, 0, 5, 0)
                pill_layout.setSpacing(4) 

                # 1. THEATER MODE BUTTON
                self.btn_theater = QPushButton()
                self.btn_theater.setFixedSize(40, 40) 
                self.btn_theater.setCursor(Qt.PointingHandCursor)
                self.btn_theater.setToolTip("Theater Mode")
                self.btn_theater.setStyleSheet("""
                    QPushButton { background: transparent; border-radius: 20px; border: none; } 
                    QPushButton:hover { background: rgba(255, 255, 255, 40); }
                """)
                
                t_icon_path = get_resource_path("theatremode.png")
                if os.path.exists(t_icon_path):
                    self.btn_theater.setIcon(QIcon(t_icon_path))
                    self.btn_theater.setIconSize(QSize(26, 26))
                else:
                    self.btn_theater.setText("🎦")

                # 2. FULLSCREEN MODE BUTTON
                self.btn_fullscreen = QPushButton()
                self.btn_fullscreen.setFixedSize(40, 40)
                self.btn_fullscreen.setCursor(Qt.PointingHandCursor)
                self.btn_fullscreen.setToolTip("Full Screen (Press ESC to exit)")
                self.btn_fullscreen.setStyleSheet("""
                    QPushButton { background: transparent; border-radius: 20px; border: none; } 
                    QPushButton:hover { background: rgba(255, 255, 255, 40); }
                """)
                
                fs_icon_path = get_resource_path("btn_fullscreen.png")
                if os.path.exists(fs_icon_path):
                    self.btn_fullscreen.setIcon(QIcon(fs_icon_path))
                    # --- OPTIMIZED ACCORDING TO SMPEGUI13.UI BALANCE ---
                    self.btn_fullscreen.setIconSize(QSize(22, 22)) 
                else:
                    self.btn_fullscreen.setText("🔲")

                # Connect button signals
                self.btn_theater.clicked.connect(self.toggle_theater_mode)
                self.btn_trim.clicked.connect(self.toggle_trim_state)
                self.btn_fullscreen.clicked.connect(self.toggle_fullscreen) 
                
                pill_layout.addWidget(self.btn_theater)
                pill_layout.addWidget(self.btn_fullscreen)

                # New Cropping Toolbar
                self.trim_tools_pill = QFrame()
                self.trim_tools_pill.setStyleSheet("QFrame { background-color: #4e4e4e; border-radius: 20px; border: none; }")
                
                trim_tools_layout = QHBoxLayout(self.trim_tools_pill)
                trim_tools_layout.setContentsMargins(5, 0, 5, 0)
                trim_tools_layout.setSpacing(4)
                
                btn_style = """
                    QPushButton { background: transparent; border-radius: 20px; border: none; } 
                    QPushButton:hover { background: rgba(255, 255, 255, 40); }
                    QPushButton:pressed { background: rgba(255, 255, 255, 60); }
                """
                
                self.btn_clipcut1 = QPushButton()
                self.btn_clipcut1.setFixedSize(40, 40)
                self.btn_clipcut1.setCursor(Qt.PointingHandCursor)
                self.btn_clipcut1.setToolTip("Set Start (Cut Left)")
                self.btn_clipcut1.setStyleSheet(btn_style)
                icon1 = get_resource_path("clipcut1.png")
                if os.path.exists(icon1):
                    self.btn_clipcut1.setIcon(QIcon(icon1))
                    self.btn_clipcut1.setIconSize(QSize(22, 22))
                else:
                    self.btn_clipcut1.setText("⬅️")

                self.btn_clipcut2 = QPushButton()
                self.btn_clipcut2.setFixedSize(40, 40)
                self.btn_clipcut2.setCursor(Qt.PointingHandCursor)
                self.btn_clipcut2.setToolTip("Set End (Cut Right)")
                self.btn_clipcut2.setStyleSheet(btn_style)
                icon2 = get_resource_path("clipcut2.png")
                if os.path.exists(icon2):
                    self.btn_clipcut2.setIcon(QIcon(icon2))
                    self.btn_clipcut2.setIconSize(QSize(22, 22))
                else:
                    self.btn_clipcut2.setText("➡️")

                self.btn_clipcutback = QPushButton()
                self.btn_clipcutback.setFixedSize(40, 40)
                self.btn_clipcutback.setCursor(Qt.PointingHandCursor)
                self.btn_clipcutback.setToolTip("Jump to Start")
                self.btn_clipcutback.setStyleSheet(btn_style)
                iconback = get_resource_path("clipcutback.png")
                if os.path.exists(iconback):
                    self.btn_clipcutback.setIcon(QIcon(iconback))
                    self.btn_clipcutback.setIconSize(QSize(22, 22))
                else:
                    self.btn_clipcutback.setText("⏪")

                trim_tools_layout.addWidget(self.btn_clipcut1)
                trim_tools_layout.addWidget(self.btn_clipcut2)
                trim_tools_layout.addWidget(self.btn_clipcutback)
                
                self.trim_tools_pill.hide() # Hide at startup so it doesn't get in the way.
                
                # Integrating our brilliant Uno =)) logic!
                self.btn_clipcut1.clicked.connect(self.set_trim_start_to_playhead)
                self.btn_clipcut2.clicked.connect(self.set_trim_end_to_playhead)
                self.btn_clipcutback.clicked.connect(self.jump_to_trim_start)

                # Inject into the footer control bar
                # New Marker Button
                self.btn_add_marker = QPushButton()
                self.btn_add_marker.setFixedSize(40, 40)
                self.btn_add_marker.setCursor(Qt.PointingHandCursor)
                self.btn_add_marker.setToolTip("Add User Marker")
                
                # Style just like the audio: transparent, no shitty outlines.
                btn_style_marker = """
                    QPushButton { background: transparent; border: none; }
                    QPushButton:hover { background: rgba(255, 255, 255, 30); border-radius: 6px; }
                    QPushButton:pressed { background: rgba(255, 255, 255, 50); }
                """
                self.btn_add_marker.setStyleSheet(btn_style_marker)
                
                icon_marker_btn = get_resource_path("pointuser.png")
                if os.path.exists(icon_marker_btn):
                    self.btn_add_marker.setIcon(QIcon(icon_marker_btn))
                    self.btn_add_marker.setIconSize(QSize(22, 22))
                else:
                    self.btn_add_marker.setText("📍")
                
                self.btn_add_marker.clicked.connect(self.add_user_marker)

                # NEW CAMERA BUTTON
                self.btn_screenshot = QPushButton()
                self.btn_screenshot.setFixedSize(40, 40)
                self.btn_screenshot.setCursor(Qt.PointingHandCursor)
                self.btn_screenshot.setToolTip("Take Screenshot")
                self.btn_screenshot.setStyleSheet(btn_style_marker)
                
                icon_camera = get_resource_path("camera.png")
                if os.path.exists(icon_camera):
                    self.btn_screenshot.setIcon(QIcon(icon_camera))
                    self.btn_screenshot.setIconSize(QSize(22, 22))
                else:
                    self.btn_screenshot.setText("📸")
                
                self.btn_screenshot.clicked.connect(lambda: self.take_screenshot())

                # ASSEMBLING THE PANEL 
                rw.addStretch() 
                rw.addWidget(self.btn_add_marker, alignment=Qt.AlignVCenter) 
                rw.addWidget(self.btn_screenshot, alignment=Qt.AlignVCenter) 
                rw.addWidget(self.trim_tools_pill, alignment=Qt.AlignVCenter)
                rw.addWidget(self.btn_trim, alignment=Qt.AlignVCenter)
                rw.addWidget(self.pill_container, alignment=Qt.AlignVCenter)

                
                # Remember original layout index for seamless restoring
                self.controls_layout_index = controls_index
                
                # Glue the 3 blocks together with EQUAL weight (stretch=1) so the center is ABSOLUTE!
                time_layout.addWidget(left_wrap, 1)
                time_layout.addWidget(center_wrap, 1)
                time_layout.addWidget(right_wrap, 1)
                
                v_layout.addLayout(time_layout)
                
                # ROW 3: The Playback Buttons (Centered horizontally)
                
                # Reverting the playback buttons back to their normal, clean sizes
                self.ui.btn_play.setIconSize(QSize(48, 48))
                self.ui.btn_skip_back.setIconSize(QSize(32, 32))
                self.ui.btn_skip_forward.setIconSize(QSize(32, 32))

                self.ui.btn_play.setToolTip("Play / Pause")
                self.ui.btn_skip_back.setToolTip("Skip Back 15s")
                self.ui.btn_skip_forward.setToolTip("Skip Forward 15s")
                
                # --- ENABLE FINGER CURSORS ---
                self.ui.btn_play.setCursor(Qt.PointingHandCursor)
                self.ui.btn_skip_back.setCursor(Qt.PointingHandCursor)
                self.ui.btn_skip_forward.setCursor(Qt.PointingHandCursor)
                
                h_layout = QHBoxLayout()
                h_layout.setSpacing(5) # Normal spacing
                h_layout.addStretch() # Pushes buttons to center
                
                self.ui.btn_skip_back.setParent(self.player_footer_frame)
                self.ui.btn_play.setParent(self.player_footer_frame)
                self.ui.btn_skip_forward.setParent(self.player_footer_frame)
                
                h_layout.addWidget(self.ui.btn_skip_back)
                h_layout.addWidget(self.ui.btn_play)
                h_layout.addWidget(self.ui.btn_skip_forward)
                
                h_layout.addStretch() # Pushes buttons to center
                
                v_layout.addLayout(h_layout)
                
                from PySide6.QtWidgets import QSplitter, QWidget, QVBoxLayout
                # 1. Original button insert
                right_layout.insertWidget(controls_index, self.player_footer_frame)

                
                # THE PERFECT SPLITTER

                # 2. Vacuum absolutely everything out of the right-hand panel
                all_items = []
                while right_layout.count():
                    all_items.append(right_layout.takeAt(0))

                self.main_v_splitter = QSplitter(Qt.Vertical)

                # 3. Top Box (Player and Buttons)
                self.top_v_wrap = QWidget()
                top_v_layout = QVBoxLayout(self.top_v_wrap)
                # Add a 10px margin at the bottom (before the splitter)
                top_v_layout.setContentsMargins(0, 0, 0, 10) 
                top_v_layout.setSpacing(right_layout.spacing())

                # 4. Bottom Box (Tabs and Status)
                self.bottom_v_wrap = QWidget()
                bottom_v_layout = QVBoxLayout(self.bottom_v_wrap)
                # Add a 10px margin at the top (after the splitter)
                bottom_v_layout.setContentsMargins(0, 10, 0, 0) 
                bottom_v_layout.setSpacing(right_layout.spacing())

                # 5. Carefully arrange the components into two boxes.
                put_in_bottom = False
                for item in all_items:
                    #Now the splitter looks for both the tabs and our new wrapper.
                    if item.widget() == getattr(self.ui, 'settings_tabs', None) or item.widget() == getattr(self, 'neo_wrapper', None):
                        put_in_bottom = True
                    
                    target_layout = bottom_v_layout if put_in_bottom else top_v_layout
                    
                    # Transferring safely, preserving all proportions and springs
                    if item.widget(): target_layout.addWidget(item.widget())
                    elif item.layout(): target_layout.addLayout(item.layout())
                    elif item.spacerItem(): target_layout.addItem(item.spacerItem())

                from PySide6.QtWidgets import QSizePolicy
                from PySide6.QtCore import QObject, QEvent
                # 1. FIX PLAYER BUTTONS STRETCHING:
                # Force the video container to absorb 100% of extra vertical space.
                top_v_layout.setStretchFactor(self.ui.video_container, 1)

                # 2. FIX STATUS BAR EXPANDING:
                # Prevent the bottom status bar from becoming huge when tabs hide.
                if hasattr(self.ui, 'frame_status'):
                    self.ui.frame_status.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
                
                
                if hasattr(self, 'neo_wrapper'):
                    bottom_v_layout.setStretchFactor(self.neo_wrapper, 1)
                elif hasattr(self.ui, 'settings_tabs'):
                    bottom_v_layout.setStretchFactor(self.ui.settings_tabs, 1)

                # 3. MAKE "HIDE" BUTTON COLLAPSE THE SPLITTER:
                # This event filter watches your existing settings_tabs. 
                # When your 'Hide' button hides the tabs, it snaps the splitter to 0!
                class HideWatcher(QObject):
                    def __init__(self, splitter):
                        super().__init__()
                        self.splitter = splitter
                        
                    def eventFilter(self, obj, event):
                        if event.type() == QEvent.Type.Hide:
                            self.splitter.setSizes([10000, 0]) # Collapse the bottom pane
                        elif event.type() == QEvent.Type.Show:
                            self.splitter.setSizes([750, 250]) # Expand the bottom pane back
                        return False # Do not block the actual hide/show event
                
                self.hide_watcher = HideWatcher(self.main_v_splitter)
                if hasattr(self.ui, 'settings_tabs'):
                    self.ui.settings_tabs.installEventFilter(self.hide_watcher)

                # 6. Assembling the Splitter
                self.main_v_splitter.addWidget(self.top_v_wrap)
                self.main_v_splitter.addWidget(self.bottom_v_wrap)
                
                self.main_v_splitter.setCollapsible(0, False) # The player is immortal
                self.main_v_splitter.setCollapsible(1, True)  # Tabs can be collapsed/hidden
                self.main_v_splitter.setSizes([750, 250])     # Initial sizes
                # Beautiful modern splitter handle
                
                self.main_v_splitter.setStyleSheet("""
                    QSplitter::handle { 
                        background-color: #444444; 
                        
                        margin: 0px 40px; 
                        border-radius: 2px; 
                        height: 4px; 
                    } 
                    QSplitter::handle:hover { 
                        background-color: #b29ae7; 
                    }
                """)

                # 7. Place the splitter back into the CLEAN right-hand panel.
                right_layout.addWidget(self.main_v_splitter)

                # Saving the new index for Fullscreen
                self.controls_layout_index = top_v_layout.indexOf(self.player_footer_frame)
                self.custom_timeline.pause_requested.connect(self.on_timeline_press)
                self.custom_timeline.seek_requested.connect(self.on_timeline_seek)
                self.custom_timeline.resume_requested.connect(self.on_timeline_release)
                self.custom_timeline.trim_changed.connect(self.on_trim_changed) 
                self.custom_timeline.screenshot_requested.connect(self.take_screenshot)
                self.custom_timeline.add_marker_requested.connect(self.add_user_marker)
        
        # --- INITIALIZING THE MPV VIDEO PLAYER ---
        mpv_log_path = os.path.join(self.logs_dir, f"mpv_engine_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

        # Clean up any junk, if present
        if self.ui.video_container.layout():
            QWidget().setLayout(self.ui.video_container.layout())
            
        self.ui.video_container.setStyleSheet("background-color: transparent; border: none;")
        
        # We place our smart wrapper into the standard layout.
        layout = QVBoxLayout(self.ui.video_container)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.mpv_wrapper = MPVWrapper()
        layout.addWidget(self.mpv_wrapper)
        
        
        self.aspect_frame = self.mpv_wrapper.aspect_frame
        self.mpv_screen = self.mpv_wrapper.mpv_screen

        self.player = mpv.MPV(
            vo='gpu',
            panscan=1.0,
            keepaspect='no',
            wid=int(self.mpv_screen.winId()), 
            hwdec='auto',         
            keep_open='yes',      
            ao='wasapi',         
            log_file=mpv_log_path,
            loglevel='fatal'
        )
        self.player['af'] = 'rubberband'
        

        # --- FULLSCREEN SYSTEM INITIALIZATION ---
        self.is_fullscreen = False
        
        # 1. Setup the 3-second sleep timer
        self.fs_timer = QTimer(self)
        self.fs_timer.setInterval(3000) # 3 seconds
        self.fs_timer.timeout.connect(self.sleep_fullscreen_controls)
        
        # 2. Install the Global Radar to catch mouse moves and ESC
        self.fs_filter = FullscreenEventFilter(self)
        QApplication.instance().installEventFilter(self.fs_filter)
        
        # 3. Connect the Fullscreen button (make sure this name matches your Qt Designer button!)
        if hasattr(self.ui, 'btn_fullscreen'):
            # You can set the icon programmatically too
            icon_path = get_resource_path("btn_fullscreen.png")
            if os.path.exists(icon_path):
                self.ui.btn_fullscreen.setIcon(QIcon(icon_path))
            self.ui.btn_fullscreen.clicked.connect(self.toggle_fullscreen)


        # Button connections 
        if hasattr(self.ui, 'btn_play'):
            self.ui.btn_play.clicked.connect(self.toggle_play)
            self.ui.btn_skip_back.clicked.connect(self.skip_backward)
            self.ui.btn_skip_forward.clicked.connect(self.skip_forward)

        self.vlc_timer = QTimer(self.ui)
        self.vlc_timer.setInterval(16) # Update the interface every 200 milliseconds
        self.vlc_timer.timeout.connect(self.update_ui_from_vlc)
        self.vlc_timer.start() # Let it always work in the background



        

        if hasattr(self.ui, 'btn_logs'):
            from PySide6.QtWidgets import QMenu
            log_menu = QMenu(self.ui)
            
            action_current = log_menu.addAction("📄 Open current log")
            action_folder = log_menu.addAction("📂 Open log folder")
            
            action_current.triggered.connect(self.open_current_log)
            action_folder.triggered.connect(self.open_logs_folder)
            
            # Attach the menu to the button
            self.ui.btn_logs.setMenu(log_menu)
        
        # We connect the "Final setup" update to all interface changes
        if hasattr(self.ui, 'combo_quality'): self.ui.combo_quality.currentTextChanged.connect(self.update_final_setup)
        if hasattr(self.ui, 'combo_bitrate'): self.ui.combo_bitrate.currentTextChanged.connect(self.update_final_setup)
        if hasattr(self.ui, 'combo_codec'): self.ui.combo_codec.currentTextChanged.connect(self.update_final_setup)
        if hasattr(self.ui, 'combo_fps'): 
            self.ui.combo_fps.currentTextChanged.connect(self.update_final_setup)
            self.ui.combo_fps.currentTextChanged.connect(self.refresh_slider_if_needed)
            self.ui.combo_fps.currentTextChanged.connect(self.update_bitrate_options)
        self.ui.combo_fps.currentTextChanged.connect(self.refresh_slider_if_needed)
        if hasattr(self.ui, 'input_filename'): self.ui.input_filename.textChanged.connect(self.update_final_setup)

        if hasattr(self.ui, 'combo_encoder'):
            self.ui.combo_encoder.currentTextChanged.connect(self.update_final_setup)
        # Connect the pause and cancel buttons (they are initially disabled)
        if hasattr(self.ui, 'btn_cancel'):
            self.ui.btn_cancel.setEnabled(False)
            self.ui.btn_cancel.clicked.connect(self.cancel_render)
            
        if hasattr(self.ui, 'btn_pause'):
            self.ui.btn_pause.setEnabled(False)
            self.ui.btn_pause.clicked.connect(self.toggle_pause)
        
        if hasattr(self.ui, 'combo_quality'): 
            self.ui.combo_quality.currentTextChanged.connect(self.on_quality_mode_changed)

        # Hide the size slider and its text when the program starts
        if hasattr(self.ui, 'size_slider'):
            self.ui.size_slider.setVisible(False)
            self.ui.size_slider.valueChanged.connect(self.on_slider_moved)

        # --- UI INJECTION: INDEPENDENT BITRATE LABELS ---
        # Instead of stuffing multiple lines into one label, we create separate 
        # widgets so the Qt layout engine handles the vertical spacing perfectly
        if hasattr(self.ui, 'orig_res_label'):
            from PySide6.QtWidgets import QLabel
            
            parent_layout = self.ui.orig_res_label.parentWidget().layout()
            
            # Find the exact index of orig_res_label to insert right below it
            insert_index = -1
            for i in range(parent_layout.count()):
                if parent_layout.itemAt(i).widget() == self.ui.orig_res_label:
                    insert_index = i
                    break
                    
            if insert_index != -1:
                # 1. Create the Video Bitrate label
                self.ui.label_vbitrate = QLabel("Video Bitrate:")
                self.ui.label_vbitrate.setStyleSheet(self.ui.orig_res_label.styleSheet())
                parent_layout.insertWidget(insert_index + 1, self.ui.label_vbitrate)
                
                # 2. Create the Audio Bitrate label
                self.ui.label_abitrate = QLabel("Audio Bitrate:")
                self.ui.label_abitrate.setStyleSheet(self.ui.orig_res_label.styleSheet())
                parent_layout.insertWidget(insert_index + 2, self.ui.label_abitrate)

        # --- UI INJECTION: STRICT CUSTOM TARGET SIZE ---
        if hasattr(self.ui, 'label_target_size'):
            from PySide6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QSizePolicy, QLabel, QToolTip
            from PySide6.QtGui import QIntValidator, QPixmap
            from PySide6.QtCore import QObject, QEvent
            
            self.size_container = QWidget() 
            size_layout = QHBoxLayout(self.size_container)
            size_layout.setContentsMargins(0, 0, 0, 0)
            size_layout.setSpacing(6) 
            
            self.ui.label_target_size.parentWidget().layout().replaceWidget(self.ui.label_target_size, self.size_container)
            self.ui.label_target_size.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            
            self.input_custom_size = QLineEdit()
            self.input_custom_size.setPlaceholderText("MB")
            self.input_custom_size.setFixedWidth(60)
            self.input_custom_size.setValidator(QIntValidator(1, 999999))
            self.input_custom_size.hide()
            self.input_custom_size.textChanged.connect(self.on_custom_size_changed)
            

            self.warn_size = QLabel()
            self.warn_size.setFixedSize(16, 16)
            pix_path = get_resource_path("attention.png")
            if os.path.exists(pix_path):
                self.warn_size.setPixmap(QPixmap(pix_path).scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.warn_size.hide()
            

            class InstantTooltipFilter(QObject):
                def eventFilter(self, obj, event):
                    if event.type() == QEvent.Type.Enter:
                        QToolTip.showText(event.globalPos(), obj.toolTip(), obj)
                    elif event.type() == QEvent.Type.Leave:
                        QToolTip.hideText()
                    return False
                    
            self.instant_tooltip = InstantTooltipFilter()
            self.warn_size.installEventFilter(self.instant_tooltip)
            
            size_layout.addWidget(self.ui.label_target_size)
            size_layout.addWidget(self.input_custom_size)
            size_layout.addWidget(self.warn_size)
            size_layout.addStretch() 
            
            self.ui.label_target_size.setVisible(True)
            self.size_container.setVisible(False)
        
        if hasattr(self.ui, 'check_audio_only'):
            self.ui.check_audio_only.toggled.connect(self.on_audio_only_toggled)
        if hasattr(self.ui, 'check_mute_audio'):
            self.ui.check_mute_audio.toggled.connect(self.on_mute_audio_toggled)
        if hasattr(self.ui, 'combo_audio_format'):
            self.ui.combo_audio_format.currentTextChanged.connect(self.update_final_setup)
        if hasattr(self.ui, 'combo_audio_bitrate'):
            self.ui.combo_audio_bitrate.currentTextChanged.connect(self.update_final_setup)
    
        # 5. AUTOMATIC DATA LOADING AT PROGRAM START
        self.detect_gpu_and_set_encoder()
        
        # 1. Check if the user has a manually saved folder preference
        user_settings = self.load_user_settings()
        saved_folder = user_settings.get("last_clips_folder", "")
        
        default_path = r"C:\Program Files (x86)\Steam\userdata\1077964895\gamerecordings\clips"
        
        if saved_folder and os.path.exists(saved_folder):
            self.clips_folder = saved_folder
        elif os.path.exists(default_path):
            self.clips_folder = default_path
            
        if self.clips_folder:
            self.scan_clips()
        
        if hasattr(self.ui, 'main_splitter'):
            self.ui.main_splitter.setSizes([300, 1300]) 
            
            
            

        # --- UI INJECTION: CUSTOM INPUTS ---
        from PySide6.QtWidgets import QLineEdit, QLabel, QHBoxLayout, QWidget, QSizePolicy
        from PySide6.QtGui import QDoubleValidator, QIntValidator, QPixmap
        
        # Helper function to inject custom input and warning icon next to ComboBox
        def inject_custom_input(combo_widget, placeholder):
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8) # Small gap between input and icon
            
            combo_widget.parentWidget().layout().replaceWidget(combo_widget, container)
            
            # Tell the ComboBox to aggressively expand and fill all available horizontal space!
            combo_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            
            line_edit = QLineEdit()
            line_edit.setPlaceholderText(placeholder)
            # Make the input box exactly 70px wide (no more, no less) so it doesn't stretch
            line_edit.setFixedWidth(70) 
            line_edit.hide() # Hidden by default
            
            warn_icon = QLabel()
            warn_icon.setFixedSize(16, 16)
            
            # Load the attention icon smoothly
            pix_path = get_resource_path("attention.png")
            if os.path.exists(pix_path):
                pixmap = QPixmap(pix_path)
                warn_icon.setPixmap(pixmap.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            warn_icon.hide() # Hidden by default
            
            # ---> APPLY THE INSTANT TOOLTIP MAGIC HERE <---
            if hasattr(self, 'instant_tooltip'):
                warn_icon.installEventFilter(self.instant_tooltip)
            
            # Add widgets to layout. 
            layout.addWidget(combo_widget)
            layout.addWidget(line_edit)
            layout.addWidget(warn_icon)
            
            # Show/hide logic
            combo_widget.currentTextChanged.connect(lambda t: (
                line_edit.setVisible("Custom" in t),
                warn_icon.setVisible(False) if "Custom" not in t else None
            ))
            return line_edit, warn_icon
    
        # Inject 3 inputs and unpack the labels
        if hasattr(self.ui, 'combo_fps'):
            self.input_custom_fps, self.warn_fps = inject_custom_input(self.ui.combo_fps, "FPS")
            self.input_custom_fps.setValidator(QIntValidator(1, 120))
            self.input_custom_fps.textChanged.connect(self.validate_custom_fps)
            
        if hasattr(self.ui, 'combo_bitrate'):
            self.input_custom_vbitrate, self.warn_vbitrate = inject_custom_input(self.ui.combo_bitrate, "Mbps")
            self.input_custom_vbitrate.setValidator(QDoubleValidator(0.1, 200.0, 2))
            self.input_custom_vbitrate.textChanged.connect(self.validate_custom_vbitrate)
            
        if hasattr(self.ui, 'combo_audio_bitrate'):
            self.input_custom_abitrate, self.warn_abitrate = inject_custom_input(self.ui.combo_audio_bitrate, "kbps")
            self.input_custom_abitrate.setValidator(QIntValidator(1, 500))
            self.input_custom_abitrate.textChanged.connect(self.validate_custom_abitrate)
    
        if hasattr(self, 'custom_timeline'):
                self.custom_timeline.setEnabled(False) # Disable clicks into empty space
                self.custom_timeline.set_duration(0)   # Reset time
                self.custom_timeline.force_jump(0)     # Position the playhead at 0
                self.custom_timeline.canvas.markers.clear()
                self.custom_timeline.canvas.update()
                
        if hasattr(self.ui, 'label_time'):
            self.ui.label_time.setText("00:00 / 00:00")
        
        QApplication.instance().applicationStateChanged.connect(self.hide_hud_on_minimize)
    
    # --- CONTEXT MENU LOGIC ---
    def show_grid_context_menu(self, pos):
        """ Pop-up menu for the grid """
        from PySide6.QtWidgets import QMenu
        from PySide6.QtCore import Qt
        import os
        
        # 1. Check if we clicked on an image in the grid.
        item = self.grid_clips.itemAt(pos)
        if not item:
            return

        # 2. Retrieve the video path from the hidden key
        clip_path = item.data(Qt.UserRole + 1)
        if not clip_path or not os.path.exists(clip_path):
            return

        # 3. Creating a menu and getting rid of the ugly Windows shadow
        menu = QMenu(self.grid_clips)
        menu.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WA_TranslucentBackground)
        
        # Menu design
        menu.setStyleSheet("""
            QMenu { 
                background-color: #2d2d2d; 
                color: #ffffff; 
                border: 2px solid #444444; 
                border-radius: 8px; 
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 13px;
                font-weight: bold;
            }
            QMenu::item { 
                padding: 6px 24px 6px 24px; 
                border-radius: 4px;
                margin: 2px 4px;
            }
            QMenu::item:selected { 
                background-color: #6b5a8e; 
            }
            QMenu::separator {
                height: 1px;
                background-color: #444444;
                margin: 4px 10px;
            }
        """)
        
        action_open = menu.addAction("📂 Open in folder")
        menu.addSeparator()
        action_delete = menu.addAction("🗑️ Delete Clip")
        
        # 4. Linking to existing functions
        action_open.triggered.connect(lambda: self.open_clip_folder(clip_path))
        action_delete.triggered.connect(lambda: self.delete_clip(clip_path))
        
        # 5. Displaying the menu under the cursor
        menu.exec(self.grid_clips.viewport().mapToGlobal(pos))

    def show_clip_context_menu(self, pos):
        """ Pop-up menu for a standard list (List/Table) """
        from PySide6.QtWidgets import QMenu
        from PySide6.QtCore import Qt
        import os
        
        # 1. Check if we clicked on a valid row.
        item = self.ui.table_clips.itemAt(pos)
        if not item:
            return

        # 2. Retrieve the video path from the first cell (column) of the selected row.
        selected_row = item.row()
        clip_path = self.ui.table_clips.item(selected_row, 0).data(Qt.UserRole)
        
        if not clip_path or not os.path.exists(clip_path):
            return

        # 3. Creating a menu and getting rid of the ugly Windows shadow
        menu = QMenu(self.ui.table_clips)
        menu.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WA_TranslucentBackground)
        
        # Your signature menu design
        menu.setStyleSheet("""
            QMenu { 
                background-color: #2d2d2d; 
                color: #ffffff; 
                border: 2px solid #444444; 
                border-radius: 8px; 
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 13px;
                font-weight: bold;
            }
            QMenu::item { 
                padding: 6px 24px 6px 24px; 
                border-radius: 4px;
                margin: 2px 4px;
            }
            QMenu::item:selected { 
                background-color: #6b5a8e; 
            }
            QMenu::separator {
                height: 1px;
                background-color: #444444;
                margin: 4px 10px;
            }
        """)
        
        action_open = menu.addAction("📂 Open in folder")
        menu.addSeparator()
        action_delete = menu.addAction("🗑️ Delete Clip")
        
        # 4. Linking to existing functions
        action_open.triggered.connect(lambda: self.open_clip_folder(clip_path))
        action_delete.triggered.connect(lambda: self.delete_clip(clip_path))
        
        # 5. Displaying the menu under the cursor
        menu.exec(self.ui.table_clips.viewport().mapToGlobal(pos))

    def open_clip_folder(self, clip_path):
        """ Opens the clip's directory directly in Windows Explorer. """
        try:
            os.startfile(clip_path)
        except Exception as e:
            logging.error(f"Failed to open folder: {e}")

    def delete_clip(self, clip_path):
        """ Prompts for confirmation and deletes the clip folder permanently. """
        import shutil
        
        # 1. Double check with the user to prevent accidental deletion
        msg = QMessageBox(self.ui)
        msg.setWindowTitle("Delete Clip")
        msg.setText("Are you sure you want to delete this clip?")
        msg.setInformativeText("This will permanently delete the folder and all its contents.\nThis cannot be undone!")
        msg.setIcon(QMessageBox.Warning)
        
        btn_delete = msg.addButton("🗑️ Delete", QMessageBox.AcceptRole)
        btn_cancel = msg.addButton("Cancel", QMessageBox.RejectRole)
        
        msg.exec()
        
        if msg.clickedButton() == btn_delete:
            try:
                # 2. Stop MPV playback if the deleted clip is currently playing
                selected_row = self.ui.table_clips.currentRow()
                if selected_row >= 0:
                    playing_path = self.ui.table_clips.item(selected_row, 0).data(Qt.UserRole)
                    if playing_path == clip_path and hasattr(self, 'player'):
                        self.player.stop()
                        
                # 3. Nuke the folder from orbit
                shutil.rmtree(clip_path)
                logging.info(f"Deleted clip folder: {clip_path}")
                
                # 4. Refresh the UI
                self.scan_clips()
                
                if hasattr(self.ui, 'label_short_summary'):
                    if hasattr(self, 'reset_bottom_summary'): self.reset_bottom_summary()
                if hasattr(self.ui, 'label_detailed_summary'):
                    self.ui.label_detailed_summary.setText("Waiting for clip selection...")
                    
            except Exception as e:
                logging.error(f"Failed to delete clip: {e}")
                QMessageBox.critical(self.ui, "Error", f"Failed to delete the clip.\nIt might be in use by another program.\n\n{e}")

    def eventFilter(self, source, event):
        from PySide6.QtCore import QEvent, QTimer
        
        if source == self.ui and event.type() == QEvent.Type.WindowStateChange:
            if not self.ui.isMaximized() and not getattr(self, 'is_fullscreen', False):
                if getattr(self, 'needs_geometry_restore', False) and hasattr(self, 'true_normal_geom'):
                    
                    def restore_geom():
                        if not getattr(self, 'is_fullscreen', False) and not self.ui.isMaximized():
                            self.ui.setGeometry(self.true_normal_geom)
                            
                    QTimer.singleShot(50, restore_geom)
                    self.needs_geometry_restore = False

        # --- FLOATING PANEL RESIZE LOGIC ---
        if hasattr(self, 'video_wrapper') and source == self.video_wrapper and event.type() == QEvent.Type.Resize:
            if getattr(self, 'is_fullscreen', False) and hasattr(self, 'player_footer_frame'):
                self.align_fullscreen_hud()
            return False

        # 1. Disable right-click selection in the Table (List)
        if hasattr(self.ui, 'table_clips') and source == self.ui.table_clips.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.RightButton:
                    click_pos = event.position().toPoint()
                    self.show_clip_context_menu(click_pos)
                    return True
                    
        # 2. Disable right-click selection in the Grid
        if hasattr(self, 'grid_clips') and source == self.grid_clips.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.RightButton:
                    click_pos = event.position().toPoint()
                    self.show_grid_context_menu(click_pos)
                    return True

        return super().eventFilter(source, event)
    
    def set_status(self, text):
        """ Updates the status text and the progress bar """
        if hasattr(self.ui, 'label_status'):
            self.ui.label_status.setText(text.split('..')[0] + '..')
            
        if hasattr(self.ui, 'progress_render'):
            # 0
            if text in ["Ready", "Success", "Cancelled", "Error!"]:
                self.ui.progress_render.setValue(0)
                if hasattr(self, 'label_pct'): self.label_pct.setText("0%")
                if text != "Error!": self.ui.label_status.setText(text)
                
            # Separating Logic: The bar consumes 0.1%, yet the text displays WHOLE numbers!
            match = re.search(r'\(([\d.]+)%\)', text)
            if match:
                val_float = float(match.group(1))
                self.ui.progress_render.setValue(int(val_float * 10))
                if hasattr(self, 'label_pct'):
                    self.label_pct.setText(f"{int(val_float)}%") 

    def elide_path(self, path, max_len=75):
        """ Smart truncation of long paths (keeps start and end) """
        if len(path) <= max_len: return path
        half = (max_len - 7) // 2
        return path[:half] + " [...] " + path[-half:]
    
    def choose_folder(self):
        """ Opens a dialog for selecting a clips folder and remembers the choice. """
        target_path = getattr(self, 'clips_folder', "")
        
        if not target_path or not os.path.exists(target_path):
            target_path = r"C:\Program Files (x86)\Steam\userdata\1077964895\gamerecordings\clips"
            if not os.path.exists(target_path):
                target_path = "C:\\"

        folder = QFileDialog.getExistingDirectory(self.ui, "Select clips folder", target_path)
        if folder:
            self.clips_folder = folder
            self.save_user_settings("last_clips_folder", folder) # Save permanently!
            self.scan_clips()
    def close_current_clip(self):
        """ Completely destroys the current clip and clears the interface. """
        if getattr(self, '_is_switching', False):
            return

        self._force_pause = True
        
        # 1. STOP THE PLAYER
        if hasattr(self, 'player') and self.player:
            self.player.pause = True
            try:
                self.player.stop()
                self.player.play("")
            except:
                pass
                
        from PySide6.QtGui import QPixmap, QIcon
        
        # 2. Clearing the Player Interface and Cache
        if hasattr(self.ui, 'video_container'):
            self.ui.video_container.setStyleSheet("background-color: transparent; border: none;")
            
        if hasattr(self, 'custom_timeline'):
            if hasattr(self.custom_timeline, 'preview_widget'):
                self.custom_timeline.preview_widget.hide()
            if hasattr(self.custom_timeline, 'img_label'):
                self.custom_timeline.img_label.setPixmap(QPixmap()) 
            self.custom_timeline.thumb_dir = None
            self.custom_timeline.current_video_path = None
            if hasattr(self.custom_timeline, 'sniper'):
                self.custom_timeline.sniper.video_path = None
                if hasattr(self.custom_timeline.sniper, 'cache'):
                    self.custom_timeline.sniper.cache.clear()

            self.custom_timeline.set_vlc_time(0, False)
            self.custom_timeline.setEnabled(False)
            self.custom_timeline.set_duration(0)
            self.custom_timeline.force_jump(0)
            self.custom_timeline.canvas.markers.clear()
            self.custom_timeline.canvas.update()

        # 3. Resetting the Table and Grid
        if hasattr(self.ui, 'table_clips'):
            self.ui.table_clips.blockSignals(True)
            self.ui.table_clips.clearSelection()
            self.ui.table_clips.blockSignals(False)
        if hasattr(self, 'grid_clips'):
            self.grid_clips.blockSignals(True)
            self.grid_clips.clearSelection()
            self.grid_clips.blockSignals(False)
            
        # 4. Restoring the Player Placeholder and Header Text
        if hasattr(self, 'video_stack') and hasattr(self, 'placeholder_frame'):
            self.video_stack.setCurrentWidget(self.placeholder_frame)
            
        if hasattr(self, 'btn_close_clip'):
            self.btn_close_clip.hide()
        if hasattr(self, 'custom_text_label'):
            self.custom_text_label.setText("Select a clip to preview...")
        if hasattr(self, 'custom_icon_label'):
            self.custom_icon_label.setPixmap(QIcon(get_resource_path("unknown_icon.png")).pixmap(24, 24))
            
        # 5. Resetting the Time and the PLAY Button
        if hasattr(self.ui, 'label_time'):
            self.ui.label_time.setText("00:00 / 00:00")
            
        if hasattr(self.ui, 'btn_play'):
            self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_play.png")))

        # 6. GLOBAL WIPE OF ALL SETTINGS TABS (UI WIPE)
        # clean the Source Info tab
        if hasattr(self.ui, 'source_label'): self.ui.source_label.setText("Source: -")
        if hasattr(self.ui, 'orig_res_label'): self.ui.orig_res_label.setText("Original resolution: -")
        if hasattr(self.ui, 'label_vbitrate'): self.ui.label_vbitrate.setText("Video Bitrate: -")
        if hasattr(self.ui, 'label_abitrate'): self.ui.label_abitrate.setText("Audio Bitrate: -")
        if hasattr(self.ui, 'label_size'): self.ui.label_size.setText("Size: -")
        if hasattr(self.ui, 'label_duration'): self.ui.label_duration.setText("Time: -")
        if hasattr(self.ui, 'label_fps'): self.ui.label_fps.setText("FPS: -")

        # Hiding Copy Buttons
        if hasattr(self, 'btn_copy_src'): self.btn_copy_src.hide()
        if hasattr(self, 'btn_copy_loc'): self.btn_copy_loc.hide()

        # Cleaning Up Lists
        def clear_combo(name):
            if hasattr(self.ui, name):
                w = getattr(self.ui, name)
                w.blockSignals(True)
                w.clear()
                w.blockSignals(False)
                
        clear_combo('combo_quality')
        clear_combo('combo_fps')
        clear_combo('combo_bitrate')
        clear_combo('combo_audio_bitrate')

        # Hide the size slider
        if hasattr(self.ui, 'size_slider'): self.ui.size_slider.hide()
        if hasattr(self, 'size_container'): self.size_container.hide()

        # Clean Export Settings
        if hasattr(self.ui, 'input_filename'):
            self.ui.input_filename.blockSignals(True)
            self.ui.input_filename.clear()
            self.ui.input_filename.blockSignals(False)
            
        if hasattr(self.ui, 'label_short_summary'):
            if hasattr(self, 'reset_bottom_summary'): self.reset_bottom_summary()
        if hasattr(self.ui, 'label_detailed_summary'):
            self.ui.label_detailed_summary.setText("Waiting for clip selection...")
        if hasattr(self.ui, 'label_location'):
            self.ui.label_location.setText("Output: -")
            
        # We're locking down the render button
        if hasattr(self.ui, 'btn_start'):
            self.ui.btn_start.setEnabled(False)
            
    


    # VIDEO PLAYER CONTROLS
    def toggle_play(self):
        """ Toggles Play/Pause state in MPV and updates the button icon. """
        if not hasattr(self, 'custom_timeline') or not self.custom_timeline.isEnabled(): return
        if getattr(self.player, 'path', None) is None: return

        self.player.pause = not self.player.pause
        if hasattr(self.ui, 'btn_play'):
            icon_path = get_resource_path("icon_play.png") if self.player.pause else get_resource_path("icon_pause.png")
            from PySide6.QtGui import QIcon
            self.ui.btn_play.setIcon(QIcon(icon_path))
                
    def set_vlc_volume(self, value):
        """ Passes the volume value to MPV with a perceptual logarithmic curve for human hearing """
        if hasattr(self, 'player') and self.player:
            if value > 0:
                perceived_volume = (value / 100.0) ** 0.5 * 100.0
            else:
                perceived_volume = 0.0
                
            self.player.volume = perceived_volume
    def set_vlc_speed(self, value):
        """ Passes the speed value to MPV (MPV handles pitch correction automatically) """
        if hasattr(self, 'player') and self.player:
            # Convert 5..30 back to 0.5..3.0
            speed_float = value / 10.0
            self.player.speed = speed_float
    def toggle_theater_mode(self):
        """ Safely collapses side and bottom panels, aware of Fullscreen state, and swaps icon. """
        
        if getattr(self, 'is_fullscreen', False):
            self.toggle_fullscreen() 
            
        self.is_theater = not getattr(self, 'is_theater', False)
        
        if hasattr(self.ui, 'left_panel'):
            self.ui.left_panel.setVisible(not self.is_theater)
        else:
            if hasattr(self.ui, 'table_clips'):
                left_wrapper = self.ui.table_clips.parentWidget()
                if left_wrapper and "Splitter" not in type(left_wrapper).__name__ and left_wrapper.objectName() != "centralwidget":
                    left_wrapper.setVisible(not self.is_theater)
                else:
                    self.ui.table_clips.setVisible(not self.is_theater)

        if hasattr(self, 'mega_top_pill'):
            self.mega_top_pill.setVisible(not self.is_theater)
        elif hasattr(self.ui, 'mega_top_pill'):
            self.ui.mega_top_pill.setVisible(not self.is_theater)

        if hasattr(self, 'library_views_container'):
            self.library_views_container.setVisible(not self.is_theater)
        elif hasattr(self.ui, 'library_views_container'):
            self.ui.library_views_container.setVisible(not self.is_theater)

        if hasattr(self.ui, 'main_splitter'):
            self.ui.main_splitter.handle(1).setVisible(not self.is_theater)

        if hasattr(self, 'bottom_v_wrap'):
            self.bottom_v_wrap.setVisible(not self.is_theater)

        # Hiding new settings panels
        if hasattr(self.ui, 'settings_tabs'):
            self.ui.settings_tabs.setVisible(not self.is_theater)
        if hasattr(self, 'neo_wrapper'):
            self.neo_wrapper.setVisible(not self.is_theater)
            
        # Hiding the new render block
        if hasattr(self.ui, 'btn_start'):
            bottom_wrapper = self.ui.btn_start.parentWidget()
            if bottom_wrapper and "Splitter" not in type(bottom_wrapper).__name__ and bottom_wrapper.objectName() != "centralwidget":
                bottom_wrapper.setVisible(not self.is_theater)
        if hasattr(self, 'render_dashboard'):
            self.render_dashboard.setVisible(not self.is_theater)

        if hasattr(self, 'btn_refresh'):
            browse_wrapper = self.btn_refresh.parentWidget()
            if browse_wrapper: browse_wrapper.setVisible(not self.is_theater)
            
        if hasattr(self.ui, 'btn_about'): self.ui.btn_about.setVisible(not self.is_theater)
        if hasattr(self.ui, 'btn_update_check'): self.ui.btn_update_check.setVisible(not self.is_theater)

        # Set the background to black and remove the 10px splitter offset.
        if hasattr(self, 'video_wrapper'):
            bg_color = "black" if self.is_theater else "transparent"
            self.video_wrapper.setStyleSheet(f"background-color: {bg_color}; border: none;")
            
        if hasattr(self, 'top_v_wrap') and self.top_v_wrap.layout():
            margin_bottom = 0 if self.is_theater else 10
            self.top_v_wrap.layout().setContentsMargins(0, 0, 0, margin_bottom)
                
        # --- THE MAGIC SWAP ---
        if hasattr(self, 'btn_theater'):
            if self.is_theater:
                icon_path = get_resource_path("theatremodeclosed.png")
                if not os.path.exists(icon_path): icon_path = get_resource_path("theatremodeclosed.jpg")
                
                if os.path.exists(icon_path):
                    self.btn_theater.setIcon(QIcon(icon_path))
                else:
                    self.btn_theater.setText("❌")
            else:
                icon_path = get_resource_path("theatremode.png")
                if os.path.exists(icon_path):
                    self.btn_theater.setIcon(QIcon(icon_path))
                else:
                    self.btn_theater.setText("🎦") 
            
            from PySide6.QtCore import QEvent
            self.btn_theater.clearFocus()
            QApplication.postEvent(self.btn_theater, QEvent(QEvent.Type.Leave))

    def show_filter_menu(self):
        """ Calculates the coordinates and passes the ENTIRE PROGRAM (self) to the menu. """
        if not hasattr(self, 'btn_filter_pill'): return
        
        # 1. Forcefully destroy the old window to reset the Qt focus bug.
        if hasattr(self, 'filter_menu') and self.filter_menu:
            self.filter_menu.deleteLater()
            
        # 2. Creating a brand-new menu from scratch
        self.filter_menu = FilterMenu(self.ui)
        self.filter_menu.gather_statistics(self)
        
        # 3. Positioning and showcasing
        button_bottom_left = self.btn_filter_pill.mapToGlobal(QPoint(0, self.btn_filter_pill.height()))
        x_shift = self.filter_menu.width() - self.btn_filter_pill.width()
        
        self.filter_menu.move(button_bottom_left.x() - x_shift + 10, button_bottom_left.y() + 5)
        self.filter_menu.show()

    def apply_sorting(self):
        """ FAST INDEPENDENT SORTING ENGINE """
        if not hasattr(self.ui, 'table_clips'): return
        table = self.ui.table_clips
        sort_idx = self.combo_sort.currentIndex()
        
        import re
        import os
        from datetime import datetime
        from PySide6.QtCore import Qt
        
        # Freezing graphics and signals for instant speed
        table.setUpdatesEnabled(False)
        table.blockSignals(True)
        
        all_data = []
        for row in range(table.rowCount()):
            is_hidden = table.isRowHidden(row)
            row_items = [table.takeItem(row, col) for col in range(table.columnCount())]
            all_data.append({ 'table_items': row_items, 'orig_row': row, 'hidden': is_hidden })
            
        
        def get_sort_key(data):
            r = data['table_items']
            
            if sort_idx == 0: 
                # Read the actual modification date of the folder containing the clip
                clip_path = r[0].data(Qt.UserRole)
                if clip_path and os.path.exists(clip_path):
                    return os.path.getmtime(clip_path)
                return 0
                
            if sort_idx in (1, 2): # GAME NAME
                txt = r[0].text().lower() if r[0] else ""
                return re.sub(r'[^a-zа-я0-9]', '', txt)
                
            if sort_idx in (3, 4): # TYPE
                txt = r[1].text().lower() if r[1] else ""
                return re.sub(r'[^a-zа-я0-9]', '', txt)
                
            if sort_idx in (5, 6): # DATE
                txt = re.sub(r'\s+', ' ', r[2].text().strip()) if r[2] else ""
                try: return datetime.strptime(txt, "%d %B %Y %I:%M %p").timestamp()
                except:
                    try: return datetime.strptime(txt, "%d %B %Y").timestamp()
                    except: return 0
                    
            if sort_idx in (7, 8): # DURATION
                txt = r[3].text() if r[3] else ""
                h = int(re.search(r'(\d+)h', txt).group(1)) if 'h' in txt else 0
                m = int(re.search(r'(\d+)m', txt).group(1)) if 'm' in txt else 0
                s = int(re.search(r'(\d+)s', txt).group(1)) if 's' in txt else 0
                return h * 3600 + m * 60 + s
                
            return data['orig_row']

       
        reverse = sort_idx in (0, 2, 4, 6, 8) 
        all_data.sort(key=get_sort_key, reverse=reverse)
        
        for new_row, data in enumerate(all_data):
            for col, item in enumerate(data['table_items']):
                table.setItem(new_row, col, item)
            table.setRowHidden(new_row, data['hidden'])
            
        table.blockSignals(False)
        table.setUpdatesEnabled(True)
        
        
        if hasattr(self, 'fast_sync_grid'):
            self.fast_sync_grid()

    def fast_sync_grid(self):
        """ INSTANT GRID SYNCHRONIZATION """
        if not hasattr(self, 'grid_clips') or not hasattr(self.ui, 'table_clips'): return

        grid = self.grid_clips
        table = self.ui.table_clips

        grid.setUpdatesEnabled(False)
        grid.blockSignals(True)

        # 1. Create a dictionary for quick lookup clip_path -> row_index in the table
        table_order = {}
        for row in range(table.rowCount()):
            t_item = table.item(row, 0)
            if t_item:
                clip_path = t_item.data(Qt.UserRole)
                # Saving the index and visibility status
                table_order[clip_path] = {'row': row, 'hidden': table.isRowHidden(row)}

        # 2. Gently update grid elements 
        for i in range(grid.count()):
            item = grid.item(i)
            clip_path = item.data(Qt.UserRole + 1)
            
            if clip_path and clip_path in table_order:
                info = table_order[clip_path]
                
                item.setText(f"{info['row']:06d}")
                item.setData(Qt.UserRole, info['row']) 
                item.setHidden(info['hidden'])         
        # 3. Qt's built-in ultra-fast sort
        grid.sortItems(Qt.AscendingOrder)

        grid.blockSignals(False)
        grid.setUpdatesEnabled(True)

    # --- TRUE HIGH-END FULLSCREEN SYSTEM ---
    def toggle_fullscreen(self):
        """ Completely isolates the video container with Anti-Spam Lock & Black Background """
        
        if getattr(self, 'fullscreen_lock', False): return
        self.fullscreen_lock = True
        
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QEvent, Qt, QTimer
        from PySide6.QtGui import QIcon
        import os

        QTimer.singleShot(700, lambda: setattr(self, 'fullscreen_lock', False))

        self.is_fullscreen = not getattr(self, 'is_fullscreen', False)
        
        if self.is_fullscreen:
            # --- ENTERING TRUE FULLSCREEN ---
            self.window_maximized_before = self.ui.isMaximized()

            if not getattr(self, 'needs_geometry_restore', False):
                self.true_normal_geom = self.ui.normalGeometry()
            
            if getattr(self, 'is_theater', False):
                self.is_theater = False
                if hasattr(self, 'btn_theater'):
                    icon_path = get_resource_path("theatremode.png")
                    if os.path.exists(icon_path):
                        self.btn_theater.setIcon(QIcon(icon_path))
                    else:
                        self.btn_theater.setText("🎦")
            
            # Hide ALL old and NEW panels
            if hasattr(self.ui, 'left_panel'): self.ui.left_panel.hide()
            if hasattr(self, 'mega_top_pill'): self.mega_top_pill.hide()
            if hasattr(self, 'library_views_container'): self.library_views_container.hide()
            if hasattr(self.ui, 'settings_tabs'): self.ui.settings_tabs.hide()
            if hasattr(self, 'neo_wrapper'): self.neo_wrapper.hide()
            if hasattr(self.ui, 'frame_status'): self.ui.frame_status.hide()
            if hasattr(self, 'player_header_frame'): self.player_header_frame.hide()
            if hasattr(self, 'render_dashboard'): self.render_dashboard.hide() 
            
            if hasattr(self.ui, 'btn_start'):
                bw = self.ui.btn_start.parentWidget()
                if bw and "Splitter" not in type(bw).__name__ and bw.objectName() != "centralwidget": bw.hide()
            if hasattr(self, 'btn_refresh'):
                rw = self.btn_refresh.parentWidget()
                if rw: rw.hide()
            if hasattr(self.ui, 'btn_about'): self.ui.btn_about.hide()
            if hasattr(self.ui, 'btn_update_check'): self.ui.btn_update_check.hide()

            if hasattr(self.ui, 'main_splitter'):
                self.ui.main_splitter.handle(1).hide()
            if hasattr(self, 'main_v_splitter'):
                self.main_v_splitter.handle(1).hide()
            
            if hasattr(self, 'bottom_v_wrap'): 
                self.bottom_v_wrap.hide()
            
            # Collapse the 10px margin that the splitter had
            if hasattr(self, 'top_v_wrap') and self.top_v_wrap.layout():
                self.top_v_wrap.layout().setContentsMargins(0, 0, 0, 0)
                
            # Set the background to black (removes gray bars at the edges of the video)
            if hasattr(self, 'video_wrapper'):
                self.video_wrapper.setStyleSheet("background-color: black; border: none;")
            
            main_layout = self.ui.layout()
            if main_layout:
                self.original_main_margins = main_layout.contentsMargins()
                main_layout.setContentsMargins(0, 0, 0, 0)
                
            right_layout = self.ui.right_panel.layout()
            if right_layout:
                self.original_right_margins = right_layout.contentsMargins()
                self.original_right_spacing = right_layout.spacing()
                right_layout.setContentsMargins(0, 0, 0, 0)
                right_layout.setSpacing(0)

            self.ui.showFullScreen()

            self.player_footer_frame.setParent(self.ui)
            self.player_footer_frame.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            
            self.player_footer_frame.setObjectName("HudFrame")
            self.player_footer_frame.setStyleSheet("""
                QFrame#HudFrame { 
                    background-color: rgba(25, 25, 25, 200); 
                    border-radius: 16px; 
                    border: none;
                }
                QFrame#HudFrame QPushButton, QFrame#HudFrame QToolButton {
                    background-color: transparent;
                    border: none;
                }
            """)
            self.player_footer_frame.show()
            self.player_footer_frame.raise_()

            if hasattr(self, 'wake_up_fullscreen_controls'):
                self.wake_up_fullscreen_controls()

            QTimer.singleShot(50, self.align_fullscreen_hud)
            
        else:
            # --- EXITING FULLSCREEN ---
            if hasattr(self, 'fs_timer'): 
                self.fs_timer.stop()
            self.ui.setCursor(Qt.ArrowCursor) 
            
            is_t = getattr(self, 'is_theater', False)
            
            # Restoring panel visibility
            if hasattr(self.ui, 'left_panel'): self.ui.left_panel.setVisible(not is_t)
            if hasattr(self, 'mega_top_pill'): self.mega_top_pill.setVisible(not is_t)
            if hasattr(self, 'library_views_container'): self.library_views_container.setVisible(not is_t)
            if hasattr(self.ui, 'settings_tabs'): self.ui.settings_tabs.setVisible(not is_t)
            if hasattr(self, 'neo_wrapper'): self.neo_wrapper.setVisible(not is_t) 
            if hasattr(self.ui, 'frame_status'): self.ui.frame_status.setVisible(not is_t)
            if hasattr(self, 'bottom_v_wrap'): 
                self.bottom_v_wrap.setVisible(not is_t)
            if hasattr(self, 'render_dashboard'): self.render_dashboard.setVisible(not is_t)
            
            if hasattr(self.ui, 'btn_start'):
                bw = self.ui.btn_start.parentWidget()
                if bw and "Splitter" not in type(bw).__name__ and bw.objectName() != "centralwidget": bw.setVisible(not is_t)
            if hasattr(self, 'btn_refresh'):
                rw = self.btn_refresh.parentWidget()
                if rw: rw.setVisible(not is_t)
            if hasattr(self.ui, 'btn_about'): self.ui.btn_about.setVisible(not is_t)
            if hasattr(self.ui, 'btn_update_check'): self.ui.btn_update_check.setVisible(not is_t)

            if hasattr(self, 'player_header_frame'): self.player_header_frame.show()
            if hasattr(self.ui, 'main_splitter'): self.ui.main_splitter.handle(1).setVisible(not is_t)
            if hasattr(self, 'main_v_splitter'): 
                self.main_v_splitter.handle(1).setVisible(not is_t)
            
            # Restoring margins and transparent background
            if hasattr(self, 'top_v_wrap') and self.top_v_wrap.layout():
                margin_bottom = 0 if is_t else 10
                self.top_v_wrap.layout().setContentsMargins(0, 0, 0, margin_bottom)
            if hasattr(self, 'video_wrapper'):
                self.video_wrapper.setStyleSheet("background-color: transparent; border: none;")
            
            main_layout = self.ui.layout()
            if main_layout and hasattr(self, 'original_main_margins'):
                main_layout.setContentsMargins(self.original_main_margins)

            right_layout = self.ui.right_panel.layout()
            if right_layout and hasattr(self, 'original_right_margins'):
                right_layout.setContentsMargins(self.original_right_margins)
                right_layout.setSpacing(getattr(self, 'original_right_spacing', 8))

            self.player_footer_frame.setWindowFlags(Qt.Widget)
            self.player_footer_frame.setAttribute(Qt.WA_TranslucentBackground, False)
            self.player_footer_frame.setParent(self.ui.right_panel)
            self.player_footer_frame.clearMask()
            
            self.player_footer_frame.setMinimumWidth(0)
            self.player_footer_frame.setMaximumWidth(16777215)
            
            from PySide6.QtWidgets import QSizePolicy
            self.player_footer_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

            idx = getattr(self, 'controls_layout_index', -1)
            v_container = getattr(self.ui, 'video_container', None)
            
            def snap_to_cage():
                if v_container:
                    v_container.setMinimumSize(1, 1)
                    v_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                    v_container.updateGeometry()
                    parent = v_container.parentWidget()
                    if parent and parent.layout():
                        parent.layout().activate()
                        
            QTimer.singleShot(50, snap_to_cage)

            target_layout = getattr(self, 'top_v_wrap', self.ui.right_panel).layout()
            if target_layout and idx >= 0:
                target_layout.insertWidget(idx, self.player_footer_frame)
            else:
                if target_layout: target_layout.addWidget(self.player_footer_frame)

            self.player_footer_frame.setObjectName("HudFrame")
            self.player_footer_frame.setStyleSheet("QFrame#HudFrame { background-color: #2d2d2d; border-radius: 6px; border: none; }")
            self.player_footer_frame.show()
            
            if right_layout: right_layout.activate()

            if hasattr(self, 'btn_fullscreen'):
                self.btn_fullscreen.clearFocus()
                QApplication.postEvent(self.btn_fullscreen, QEvent(QEvent.Type.Leave))
            if hasattr(self, 'btn_theater'):
                self.btn_theater.clearFocus()
                QApplication.postEvent(self.btn_theater, QEvent(QEvent.Type.Leave))

            if getattr(self, 'window_maximized_before', False):
                screen_geom = self.ui.screen().availableGeometry()
                self.ui.setMinimumSize(screen_geom.size())
                self.ui.showNormal()
                self.ui.move(screen_geom.topLeft())
                self.ui.showMaximized()
                self.ui.setMinimumSize(1000, 650)
                self.needs_geometry_restore = True
            else:
                self.ui.showNormal()
                self.ui.setMinimumSize(1000, 600)
                if hasattr(self, 'true_normal_geom'):
                    self.ui.setGeometry(self.true_normal_geom)

    
    def align_fullscreen_hud(self):
        """ Calculates global coordinates and aligns the floating panel. """
        if not getattr(self, 'is_fullscreen', False) or not hasattr(self, 'player_footer_frame'):
            return
            
        from PySide6.QtGui import QPainterPath, QRegion
        
        w = self.ui.width()
        h = self.ui.height()
        footer_h = self.player_footer_frame.sizeHint().height()
        
        # Get the global coordinates of the window itself.
        global_pos = self.ui.mapToGlobal(self.ui.rect().topLeft())
        
        hud_w = w - 80
        hud_x = global_pos.x() + 40
        hud_y = global_pos.y() + h - footer_h - 15
        
        # Place the glass shard exactly in the center.
        self.player_footer_frame.setGeometry(hud_x, hud_y, hud_w, footer_h)
        
        #Applying the Rounding Mask
        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(hud_w), float(footer_h), 16.0, 16.0)
        region = QRegion(path.toFillPolygon().toPolygon())
        self.player_footer_frame.setMask(region)
    def hide_hud_on_minimize(self, state):
        from PySide6.QtCore import Qt
        
       # This matters to us ONLY if we are in fullscreen mode.
        if not getattr(self, 'is_fullscreen', False):
            return
            
        # If the program was minimized (Win+D) or you switched to another window (Alt-Tab)
        if state != Qt.ApplicationState.ApplicationActive:
            if hasattr(self, 'player_footer_frame'):
                self.player_footer_frame.hide()
        
        # If you switched away from the app and returned to it
        else:
            if hasattr(self, 'player_footer_frame'):
                self.player_footer_frame.show()
                # Force-wake the panel so it doesn't end up in a coma!
                if hasattr(self, 'wake_up_fullscreen_controls'):
                    self.wake_up_fullscreen_controls()

    def wake_up_fullscreen_controls(self):
        """ Restores mouse arrow visibility and maps HUD controls layer on motion. """
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        
        if not getattr(self, 'is_fullscreen', False): 
            return
            
        # If the program is minimized (Win+D) or we are currently Alt-Tabbing, completely ignore any mouse attempts to wake up the interface!
        if QApplication.instance().applicationState() != Qt.ApplicationState.ApplicationActive:
            return
        
        self.ui.setCursor(Qt.ArrowCursor) 
        if hasattr(self, 'player_footer_frame'):
            self.player_footer_frame.show()   
        self.fs_timer.start()           

    def sleep_fullscreen_controls(self):
        """ Completely terminates cursor rendering and hides controls layer after 3 seconds of stagnation. """
        if not getattr(self, 'is_fullscreen', False): return
        
        if hasattr(self, 'player_footer_frame') and self.player_footer_frame.underMouse():
            self.fs_timer.start() 
            return
            
        self.ui.setCursor(Qt.BlankCursor) 
        if hasattr(self, 'player_footer_frame'):
            self.player_footer_frame.hide()   
        
        from PySide6.QtWidgets import QToolTip
        QToolTip.hideText()
    def keyPressEvent(self, event):
        """ Captures keyboard events. Exits fullscreen seamlessly if Escape key is pressed. """
        if event.key() == Qt.Key_Escape and getattr(self, 'is_fullscreen', False):
            self.toggle_fullscreen()
            event.accept()
        else:
            super().keyPressEvent(event)

    def toggle_trim_state(self):
        """ Toggles between Trim mode and Normal mode seamlessly without interrupting playback """
        if not hasattr(self, 'custom_timeline'): return

        if self.custom_timeline.is_trim_mode:
            # TURN OFF TRIM MODE
            self.custom_timeline.disable_trim_mode()
            
            # Hide border on aspect_frame
            if hasattr(self, 'aspect_frame'):
                self.aspect_frame.setStyleSheet("border: 3px solid transparent; background-color: transparent;")
            
            # Hide the interactive border instantly
            if hasattr(self, 'video_overlay'):
                self.video_overlay.show_border = False
                self.video_overlay.update()

            if hasattr(self, 'border_overlay'):
                self.border_overlay.setStyleSheet("border: 3px solid #ffcc00; background-color: transparent;")
            
            # Restore to default Trim button with custom scissors icon...
            trim_icon_path = get_resource_path("trim_icon.png")
            if os.path.exists(trim_icon_path):
                self.btn_trim.setIcon(QIcon(trim_icon_path))
                self.btn_trim.setText(" Trim")
            else:
                self.btn_trim.setIcon(QIcon())
                self.btn_trim.setText("✂️ Trim")
                
            # Restore the slightly golden premium style
            self.btn_trim.setStyleSheet("background-color: #cfa94a; color: black; border-radius: 15px; padding: 0 12px; font-weight: bold;")
            

            if hasattr(self, 'aspect_frame'):
                self.aspect_frame.setStyleSheet("background-color: transparent;")
            if hasattr(self, 'trim_tools_pill'):
                self.trim_tools_pill.hide()
        else:
            # TURN ON TRIM MODE
            self.custom_timeline.enable_trim_mode()
            
            # Transform into Cancel button with custom cancel icon
            cancel_icon_path = get_resource_path("cancel.png")
            if os.path.exists(cancel_icon_path):
                self.btn_trim.setIcon(QIcon(cancel_icon_path))
                self.btn_trim.setText(" Cancel")
            else:
                self.btn_trim.setIcon(QIcon()) 
                self.btn_trim.setText("❌ Cancel")
                
            # Apply the red danger style
            self.btn_trim.setStyleSheet("background-color: #ff4444; color: white; border-radius: 15px; padding: 0 12px; font-weight: bold;")

            if hasattr(self, 'trim_tools_pill'):
                self.trim_tools_pill.show()
        # --- FORCE UI REFRESH ON TOGGLE ---
        self.update_final_setup()
        if hasattr(self.ui, 'combo_quality') and "Target File Size" in self.ui.combo_quality.currentText():
            self.setup_dynamic_slider()
    def set_trim_start_to_playhead(self):
        """ Sets the left end of the yellow strip with a UNO REVERSAL. """
        if not hasattr(self, 'custom_timeline'): return
        canvas = self.custom_timeline.canvas
        pos = canvas.visual_ms
        old_start = canvas.trim_start_ms
        old_end = canvas.trim_end_ms
        duration = old_end - old_start
        
        if pos >= old_end:
            # UNO CARD! The scroller is positioned *after* the end. 
            # We shift the entire segment as a whole: the scroller becomes the new start, and the end point flies further out! 
            canvas.trim_start_ms = pos
            canvas.trim_end_ms = min(pos + duration, canvas.duration_ms)
        else:

            canvas.trim_start_ms = pos
            
        self.custom_timeline.trim_changed.emit(int(canvas.trim_start_ms), int(canvas.trim_end_ms))
        canvas.update()

    def set_trim_end_to_playhead(self):
        """ Sets the right end of the yellow strip with a U-turn. """
        if not hasattr(self, 'custom_timeline'): return
        canvas = self.custom_timeline.canvas
        pos = canvas.visual_ms
        old_start = canvas.trim_start_ms
        old_end = canvas.trim_end_ms
        duration = old_end - old_start
        
        if pos <= old_start:
            # UNO CARD! The scroller is positioned before the start. 
            # We shift the entire chunk: the scroller becomes the new end, while the original start flies backward!
            canvas.trim_end_ms = pos
            canvas.trim_start_ms = max(pos - duration, 0.0)
        else:
            # Standard Click
            canvas.trim_end_ms = pos
            
        self.custom_timeline.trim_changed.emit(int(canvas.trim_start_ms), int(canvas.trim_end_ms))
        canvas.update()

    def jump_to_trim_start(self):
        """ Simply teleports the scroller back to the start of the clipping. """
        if not hasattr(self, 'custom_timeline'): return
        self.custom_timeline.force_jump(self.custom_timeline.trim_start_ms)
    def on_timeline_press(self):
        """ Triggered when the user clicks on the timeline track. """
        if hasattr(self, 'player') and self.player:
            # Check if video is playing (if pause is False, it means it is playing)
            self.was_playing_before_drag = not self.player.pause
            
            # Pause the video while the user is dragging the playhead
            self.player.pause = True

    def on_timeline_seek(self, position_ms):
        """ Commands MPV to jump. """
        if not hasattr(self, 'custom_timeline') or not self.custom_timeline.isEnabled(): 
            return
            
        if hasattr(self, 'player') and self.player:
            if getattr(self.player, 'duration', None):
                self.player.seek(position_ms / 1000.0, reference='absolute', precision='exact')


    def on_timeline_release(self):
        """ Triggered when the user releases the mouse button after dragging. """
        if hasattr(self, 'player') and self.player:
            
            # Restore playback state if it was playing before we clicked
            if getattr(self, 'was_playing_before_drag', False):
                self.player.pause = False
                
            # If you have a variable 'is_muted' in your scope, apply it to MPV like this:
            # (Replace the old audio_set_mute line with this one)
            if hasattr(self, 'is_muted'):
                self.player.mute = self.is_muted

    def skip_backward(self):
        """ Rewind 15 seconds using the Independent Timeline Engine """
        if not hasattr(self, 'custom_timeline') or not self.custom_timeline.isEnabled(): return
        new_time = self.custom_timeline.visual_ms - 15000
        self.custom_timeline.force_jump(new_time)

    def skip_forward(self):
        """ Skips 15 seconds forward using the Independent Timeline Engine """
        if not hasattr(self, 'custom_timeline') or not self.custom_timeline.isEnabled(): return
        new_time = self.custom_timeline.visual_ms + 15000
        self.custom_timeline.force_jump(new_time)

    def skip_back(self):
        """ Skips 15 seconds backward using the Independent Timeline Engine """
        if not hasattr(self, 'custom_timeline') or not self.custom_timeline.isEnabled(): return
        new_time = self.custom_timeline.visual_ms - 15000
        self.custom_timeline.force_jump(new_time)
        

    def generate_and_play_preview(self):
        """ Instantly loads and plays the Steam .mpd playlist using MPV. No proxy needed! """ 
        if not hasattr(self.ui, 'table_clips') or self.ui.table_clips.currentRow() < 0:
            return

        # 1. STOP CURRENT PLAYBACK
        self._is_switching = True
        self._force_pause = False

        
        # 2. GET THE CLIP FOLDER PATH
        clip_path = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0).data(Qt.UserRole)
        
        # STEP 1: FIND THE VIDEO FOLDER
        all_mpds = self.get_all_mpd_paths(clip_path)
        if not all_mpds: 
            return

        mpd_path = all_mpds[0] 

        # STEP 2: AUTO-SEARCH JSON TIMELINE
        # STEP 2: AUTO-SEARCH JSON TIMELINE
        offset_ms = 0
        
        def find_json_in_dir(directory):
            if not directory or not os.path.isdir(directory): 
                return None
            # Searching for the Right Timeline
            for root_dir, dirs, files in os.walk(directory):
                for file in files:
                    if file.startswith("timeline_") and file.endswith(".json"):
                        return os.path.join(root_dir, file)
            # Backup Option
            for root_dir, dirs, files in os.walk(directory):
                for file in files:
                    if file.endswith(".json") and "settings" not in file and "games" not in file:
                        return os.path.join(root_dir, file)
            return None

        # 1. Search strictly within the clip's own folder!
        json_path = find_json_in_dir(clip_path)

        # 2. If the clip is in the standard Steam folder (video/fg_123), look in the adjacent folder: timelines/fg_123.
        if not json_path:
            parent_dir = os.path.dirname(clip_path)
            if os.path.basename(parent_dir).lower() == "video":
                timelines_dir = os.path.join(os.path.dirname(parent_dir), "timelines")
                clip_folder_name = os.path.basename(clip_path)
                json_path = find_json_in_dir(os.path.join(timelines_dir, clip_folder_name))

        # 3. Passing to the Engine
        if hasattr(self, 'custom_timeline'):
            if json_path:
                print(f"Json was found successfully: {json_path}")
                
                json_name = os.path.basename(json_path) 
                video_folder_name = os.path.basename(os.path.dirname(mpd_path))
                
                json_match = re.search(r'(\d{8})_(\d{6})', json_name)
                video_match = re.search(r'(\d{8})_(\d{6})', video_folder_name)
                
                if json_match and video_match:
                    try:
                        j_str = json_match.group(1) + json_match.group(2)
                        v_str = video_match.group(1) + video_match.group(2)
                        
                        json_dt = datetime.strptime(j_str, "%Y%m%d%H%M%S")
                        video_dt = datetime.strptime(v_str, "%Y%m%d%H%M%S")
                        
                        offset_ms = int((video_dt - json_dt).total_seconds() * 1000)
                    except Exception as e:
                        print(f"Time Count Error: {e}")
                        offset_ms = 0
                        
                print(f"Delay: {offset_ms} ms")
                self.custom_timeline.canvas.load_timeline_json(json_path, offset_ms)
                
            else:
                print(f"No JSON found for this clip: {clip_path}")
                self.custom_timeline.canvas.markers.clear()
                self.custom_timeline.canvas.update()


        # 3. PREPARE THE CANVAS
        self.ui.video_container.setStyleSheet("background-color: transparent;")
        if hasattr(self, 'video_stack'): 
            self.video_stack.setCurrentWidget(self.ui.video_container)
        if hasattr(self, 'btn_close_clip'): 
            self.btn_close_clip.show()
        if hasattr(self, 'custom_timeline'): 
            self.custom_timeline.setEnabled(True)

        # 4. FEED THE RAW STEAM DASH FILE DIRECTLY TO MPV
        print(f"---> Feeding MPD directly to MPV: {mpd_path}")
        
        # A Reliable Path for Windows:
        abs_path = os.path.abspath(mpd_path).replace('\\', '/')
        
        # Start the video and unpause it.
        self.player.play(abs_path) 
        self.player.pause = False

        # --- BACKGROUND THUMBNAIL BATCH GENERATION (THE MATRIX 2.0) ---
        if hasattr(self, 'thumb_thread') and self.thumb_thread.isRunning():
            self.thumb_thread.stop()
            
        # Launch the Batch Generator
        self.thumb_thread = ThumbnailBatchThread(abs_path, self.current_clip_duration_sec, interval=3)
        
        if hasattr(self, 'custom_timeline'):
            self.custom_timeline.thumb_dir = self.thumb_thread.thumb_dir
            self.custom_timeline.current_video_path = abs_path
            
            # A function that removes the shield and activates the timeline
            def finish_switch():
                self.custom_timeline.setEnabled(True)
                self._is_switching = False 
                
            QTimer.singleShot(500, finish_switch)
                
        self.thumb_thread.start()

        # --- IMMEDIATELY UPDATE PLAY BUTTON ICON TO PAUSE ---
        if hasattr(self.ui, 'btn_play'):
            from PySide6.QtGui import QIcon
            icon_path = get_resource_path("icon_pause.png")
            self.ui.btn_play.setIcon(QIcon(icon_path))
        

    def closeEvent(self, event):
        """ Triggered automatically when the window's red 'X' button is clicked """
        self._force_pause = True
        
        # 1. Kill the player if it is active.
        if hasattr(self, 'player') and self.player:
            self.player.pause = True 
            try:
                self.player.command('stop') 
            except:
                pass
                
        # 2. Killing the frozen FFmpeg
        try:
            import psutil
            current_process = psutil.Process()
            # We are looking for all child processes launched by our program.
            children = current_process.children(recursive=True)
            for child in children:
                # If the process is named ffmpeg or ffprobe, terminate it.
                if "ffmpeg" in child.name().lower() or "ffprobe" in child.name().lower():
                    child.kill()
                    print(f"Zombie proccess killed: {child.name()}")
        except Exception as e:
            print(f"⚠️ Error with killing zombie pcorsalfgn: {e}")

        event.accept()

    
    def update_ui_from_vlc(self):
        """ Updates UI and Timeline from MPV engine """
        if not hasattr(self, 'player') or not self.player:
            return
            
        # If the strip is off, prevent the timer from toggling it!
        if hasattr(self, 'custom_timeline') and not self.custom_timeline.isEnabled():
            return

        # Safe check to prevent jumpiness after seeking
        if time.time() < getattr(self, '_ignore_vlc_until', 0):
            return

        try:
            duration_sec = getattr(self, 'current_clip_duration_sec', self.player.duration)
            if duration_sec is None or duration_sec <= 0:
                duration_sec = self.player.duration
                if duration_sec is None: return
                
            time_sec = self.player.time_pos
            

            current_dw = getattr(self.player, 'dwidth', None)
            if current_dw != getattr(self, '_last_video_width', None):
                self._last_video_width = current_dw
                if hasattr(self, 'recalculate_video_geometry'):
                    self.recalculate_video_geometry()
            
            # If duration is missing, the video is not fully loaded yet
            if duration_sec is None:
                return
                
            duration_ms = int(duration_sec * 1000)
            
            # MPV sometimes returns None for time_pos at the exact moment the video ends
            if time_sec is None:
                if getattr(self.player, 'eof_reached', False):
                    time_sec = duration_sec 
                else:
                    return
                    
            current_ms = int(time_sec * 1000)

            # --- AUTO-REWIND AT THE END OF VIDEO (EOF) ---
            # If MPV flags end-of-file, or we are within 100ms of the end
            if getattr(self.player, 'eof_reached', False) or current_ms >= duration_ms - 5:
                self.player.pause = True 
                self.player.seek(0, reference='absolute', precision='exact') 
                current_ms = 0 
                
                if hasattr(self, 'custom_timeline'):
                    self.custom_timeline.force_jump(0)
                    
                # Change the pause button back to play
                if hasattr(self.ui, 'btn_play'):
                    from PySide6.QtGui import QIcon
                    icon_path = get_resource_path("icon_play.png")
                    self.ui.btn_play.setIcon(QIcon(icon_path))

            is_playing = not self.player.pause

            # Send the data to our smooth custom timeline
            if hasattr(self, 'custom_timeline'):
                self.custom_timeline.set_duration(duration_ms)
                self.custom_timeline.set_vlc_time(current_ms, is_playing)

            # --- UPDATE TEXT TIMERS (00:00 / 00:00) ---
            def format_time(ms):
                """ Converts milliseconds into HH:MM:SS or MM:SS format """
                s = ms // 1000
                h = s // 3600
                m = (s % 3600) // 60 
                s = s % 60
                
                if h > 0:
                    return f"{h:02d}:{m:02d}:{s:02d}"
                return f"{m:02d}:{s:02d}"
            
            # --- YELLOW BORDER INDICATOR ---
            if getattr(self, 'is_fullscreen', False):
                if hasattr(self, 'aspect_frame'):
                    self.aspect_frame.setStyleSheet("border: 3px solid transparent; background-color: transparent;")
            else:
                if hasattr(self, 'custom_timeline') and self.custom_timeline.is_trim_mode:
                    if self.custom_timeline.trim_start_ms <= current_ms <= self.custom_timeline.trim_end_ms:
                        if hasattr(self, 'aspect_frame'):
                            # Draw perfect yellow border
                            self.aspect_frame.setStyleSheet("border: 3px solid #ffcc00; background-color: transparent;")
                    else:
                        if hasattr(self, 'aspect_frame'):
                            # Remove border
                            self.aspect_frame.setStyleSheet("border: 3px solid transparent; background-color: transparent;")
                else:
                    if hasattr(self, 'aspect_frame'):
                        # Remove border
                        self.aspect_frame.setStyleSheet("border: 3px solid transparent; background-color: transparent;")

            # --- UPDATE TEXT TIMERS (00:00 / 00:00) ---

            # Update the main timer label
            # Check if your specific UI label exists and update it ONLY if the text changed!
            if hasattr(self.ui, 'label_time'):
                current_str = format_time(current_ms)
                total_str = format_time(duration_ms)
                new_time_text = f"{current_str} / {total_str}"
                
                # Prevent UI lag by updating text only once per second
                if self.ui.label_time.text() != new_time_text:
                    self.ui.label_time.setText(new_time_text)
        except Exception as e:
            pass # Ignore random missing property errors during video switching
    def on_app_exit(self):
        """ Global Intercept: Triggers when the entire program closes. """
        print("CLEANING BEFORE CLOSING...")
        if hasattr(self, 'player') and self.player:
            try:
                self.player.command('stop')
                self.player.terminate()
            except: pass
            
        # Killing all zombie FFmpeg child processes
        try:
            import psutil
            current_process = psutil.Process()
            children = current_process.children(recursive=True)
            for child in children:
                if "ffmpeg" in child.name().lower() or "ffprobe" in child.name().lower():
                    child.kill()
                    print(f"Killed FFmpeg after exit: {child.name()}")
        except: pass
    
    def show_about_dialog(self):
        """ Shows the About dialog"""
        if getattr(self, '_about_is_open', False): 
            return # Block if already open
        self._about_is_open = True
        
        msg_box = QMessageBox(self.ui)
        msg_box.setWindowTitle("About Steempeg")
        
        # Logo of the window itself
        icon_path = get_resource_path("logo.png")
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            msg_box.setIconPixmap(pixmap)
        else:
            msg_box.setIcon(QMessageBox.Information)

        # Prepare 100% working absolute paths for icons within HTML
        # Use QUrl so Qt knows exactly where the images are located, even within an .exe file
        github_icon = QUrl.fromLocalFile(get_resource_path("github.jpg")).toString()
        steam_icon = QUrl.fromLocalFile(get_resource_path("steam.png")).toString()

        about_text = f"""
        <h3>Steempeg v{APP_VERSION_STR}</h3>
        <p><b>Build:</b> v{APP_VERSION_STR}</p>
        <p><b>Developer:</b> Emily 🎀 <span style="color: #888888; font-size: 10pt;">@applejuicy23</span></p>

        <p><img src="{github_icon}" width="16" height="16" align="middle"> <b>GitHub:</b> <a href="https://github.com/applejuicy23/steempeg">applejuicy23/steempeg</a></p>
        <p><img src="{steam_icon}" width="16" height="16" align="middle"> <b>Steam:</b> <a href="https://steamcommunity.com/id/applejuicy23/">applejuicy23</a></p>

        <p>A smart, elegant, and fast hardware-accelerated video renderer for Steam Clips.</p>
        <p>Powered by <b>FFmpeg,</b> <b>PyAV</b> & <b>MPV</b></p>

        <p style="font-size: 8pt; color: #777777; margin-top: 15px;">
        <i>Steempeg is an unofficial, community-created tool.<br>
        Not affiliated with, associated with, authorized, or endorsed by Valve Corporation or Steam.</i>
        </p>
        """
        
        msg_box.setText(about_text)
        msg_box.setTextInteractionFlags(Qt.TextBrowserInteraction)

        msg_box.setStandardButtons(QMessageBox.Close)
        msg_box.exec()
        
        self._about_is_open = False # Release the lock when closed

    def check_for_updates(self):
        """ Checks GitHub API for new releases with deep logging """
        import requests
        import webbrowser
        import re
        import logging

        CURRENT_VERSION = APP_VERSION_FLOAT
        logging.info("--- UPDATER: Button clicked! Starting check_for_updates ---")

        try:
            self.set_status("Checking for updates...")
            
            url = "https://api.github.com/repos/applejuicy23/steempeg/releases/latest"
            headers = {'User-Agent': 'Steempeg-Updater'}
            
            logging.info(f"UPDATER: Connecting to {url}...")
            
            # response API
            response = requests.get(url, headers=headers, timeout=5)
            logging.info(f"UPDATER: GitHub API responded with status code: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                latest_name = data.get("name", "")
                tag_name = data.get("tag_name", "")
                release_url = data.get("html_url", "https://github.com/applejuicy23/steempeg/releases")
                
                logging.info(f"UPDATER: Found release - Name: '{latest_name}', Tag: '{tag_name}'")
                
                # find version
                match = re.search(r'v(\d+(?:\.\d+)?)', tag_name + " " + latest_name, re.IGNORECASE)
                
                if match:
                    latest_version = float(match.group(1))
                    logging.info(f"UPDATER: Parsed version: {latest_version} (Local Current: {CURRENT_VERSION})")
                    
                    if latest_version > CURRENT_VERSION:
                        logging.info("UPDATER: Showing 'Update Available' dialog.")
                        
                        download_url = None
                        asset_name = None
                        
                        # Look for our .zip archive in the release on GitHub
                        for asset in data.get("assets", []):
                            name = asset.get("name", "").lower()
                            if name.endswith(".zip"):
                                download_url = asset.get("browser_download_url")
                                asset_name = asset.get("name")
                                break
                        
                        msg = QMessageBox(self.ui)
                        msg.setWindowTitle("Update Available!")
                        msg.setIcon(QMessageBox.Information)
                        msg.setText(f"<h3>Great news!</h3><p>A new version is available: <b>{latest_name}</b></p><p>You are currently on v{CURRENT_VERSION}.</p>")
                        
                        btn_download = msg.addButton("🚀 Install Update", QMessageBox.ActionRole)
                        btn_cancel = msg.addButton("Maybe Later", QMessageBox.RejectRole)
                        
                        msg.exec()
                        
                        if msg.clickedButton() == btn_download:
                            if download_url:
                                # Start downloading the ZIP archive directly in the program!
                                self.start_downloading_update(download_url, asset_name)
                            else:
                                # If for some reason the ZIP file is not found, open the browser
                                webbrowser.open(release_url)
                            
                    elif latest_version == CURRENT_VERSION:
                        logging.info("UPDATER: Showing 'Latest Version' dialog.")
                        QMessageBox.information(self.ui, "Updater", f"You are using the latest public version of Steempeg (v{CURRENT_VERSION})! 🎉")
                        
                    else:
                        logging.info("UPDATER: Showing 'Developer Build' dialog.")
                        QMessageBox.information(
                            self.ui, 
                            "Developer Build", 
                            f"Wow! You are on a developer build (v{CURRENT_VERSION}).\n"
                            f"The latest public release on GitHub is only v{latest_version}.\n"
                            f"Keep up the great work! 🚀🎀\n"
                            f"Developer awaits your LOG to fix the bug!🌷"
                        )
                else:
                    logging.warning("UPDATER: Regex failed to find 'vX.X' in the release name/tag.")
                    QMessageBox.warning(self.ui, "Updater", "Could not parse the version number from the latest GitHub release.")
            
            elif response.status_code == 404:
                logging.warning("UPDATER: 404 Not Found. This means the repo is private or has 0 public releases.")
                QMessageBox.information(self.ui, "Updater", f"You are on the pioneer version (v{CURRENT_VERSION})! No public releases found yet. 🎉")
            
            elif response.status_code == 403:
                logging.warning(f"UPDATER: 403 Forbidden. GitHub API Rate Limit exceeded! Response: {response.text}")
                QMessageBox.warning(self.ui, "Updater", "GitHub API rate limit exceeded. Please try checking for updates later.")
                
            else:
                logging.error(f"UPDATER: Unexpected status code {response.status_code}. Response: {response.text}")
                QMessageBox.warning(self.ui, "Updater", f"Could not check for updates. GitHub API returned status: {response.status_code}")
                
        except requests.exceptions.RequestException as e:
             logging.error(f"UPDATER: Network request failed: {e}")
             QMessageBox.critical(self.ui, "Updater Error", "Could not connect to GitHub. Check your internet connection!")
        except Exception as e:
            logging.error(f"UPDATER: Critical Python exception: {e}")
            QMessageBox.critical(self.ui, "Updater Error", f"An error occurred while checking for updates:\n{str(e)}")
        finally:
            self.set_status("Ready")
            logging.info("--- UPDATER: check_for_updates finished ---")

    def start_downloading_update(self, url, asset_name):
        """ Starts the background download and shows a progress bar """
        from PySide6.QtWidgets import QProgressDialog
        
        self.progress_dialog = QProgressDialog("Starting download...", "Cancel", 0, 100, self.ui)
        self.progress_dialog.setWindowTitle("Steempeg Updater")
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setAutoClose(True)
        self.progress_dialog.setValue(0)
        self.progress_dialog.setMinimumWidth(400) # Making the window wider for text

        self.update_thread = UpdateDownloadThread(url, os.path.dirname(sys.executable), asset_name)
        self.update_thread.progress_signal.connect(self.update_download_progress)
        self.update_thread.finished_signal.connect(self.on_update_downloaded)
        
        self.update_thread = UpdateDownloadThread(url, os.path.dirname(sys.executable), asset_name)

        self.update_thread.progress_signal.connect(self.update_download_progress)
        self.update_thread.finished_signal.connect(self.on_update_downloaded)
        
        self.progress_dialog.canceled.connect(self.update_thread.cancel)
        self.update_thread.start()
        self.progress_dialog.show()

    def update_download_progress(self, percent, text):
        """ Dynamically updates the text and progress bar of the updater """
        self.progress_dialog.setLabelText(text)
        self.progress_dialog.setValue(percent)

    def show_update_success(self, old_version, backup_folder):
        """ Shows a nice window after a successful update """
        msg = QMessageBox(self.ui)
        msg.setWindowTitle("Update Successful!")
        msg.setIcon(QMessageBox.Information)
        
        text = f"<h3>Steempeg is updated!</h3><p>Successfully updated from <b>v{old_version}</b> to the latest version.</p>"
        if backup_folder and backup_folder != "None":
            text += f"<p>Your old version was saved in the folder:<br><code>{backup_folder}</code></p>"
            
        msg.setText(text)
        
        btn_ok = msg.addButton("Good!", QMessageBox.AcceptRole)
        btn_folder = None
        if backup_folder and backup_folder != "None":
            btn_folder = msg.addButton("📂 Open Backup Folder", QMessageBox.ActionRole)
            
        msg.exec()
        
        if btn_folder and msg.clickedButton() == btn_folder:
            import subprocess
            backup_path = os.path.abspath(os.path.join(get_save_directory(), backup_folder))
            if os.path.exists(backup_path):
                os.startfile(backup_path)

    # final_asset_name
    def on_update_downloaded(self, success, filepath, final_asset_name):
        """ Unpacks the ZIP, asks about a backup, and launches the BAT ninja. """
        if not success:
            if filepath: QMessageBox.warning(self.ui, "Update Failed", f"Could not download the update.\n{filepath}")
            return

        import zipfile
        import shutil

        current_exe = sys.executable
        exe_dir = os.path.dirname(current_exe)
        
        # The BAT file will now ALWAYS use the real global version of the client!
        CURRENT_VERSION = APP_VERSION_STR 

        # 1. Unzip the downloaded ZIP file into a temporary folder.
        extract_dir = os.path.join(exe_dir, "_update_extracted")
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir, ignore_errors=True)
        os.makedirs(extract_dir, exist_ok=True)

        try:
            with zipfile.ZipFile(filepath, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
        except Exception as e:
            QMessageBox.critical(self.ui, "Extraction Error", f"Failed to unzip the update!\n{e}")
            return

        # Find the source folder inside the unpacked archive (in case the files are inside the Steempeg_v13 folder)
        extracted_items = os.listdir(extract_dir)
        if len(extracted_items) == 1 and os.path.isdir(os.path.join(extract_dir, extracted_items[0])):
            source_dir = os.path.join("_update_extracted", extracted_items[0])
        else:
            source_dir = "_update_extracted"

        # Looking for a new executable (smpeg13.exe)
        new_exe_name = "Steempeg.exe"
        full_source_path = os.path.join(exe_dir, source_dir)
        for file in os.listdir(full_source_path):
            if file.endswith(".exe") and "ffmpeg" not in file.lower() and "ffprobe" not in file.lower():
                new_exe_name = file
                break

        #2. Ask the user
        msg = QMessageBox(self.ui)
        msg.setWindowTitle("Update Ready to Install!")
        msg.setText("The new version has been downloaded and extracted.\nDo you want to replace the current files, or keep them as a backup?")
        msg.setIcon(QMessageBox.Question)
        
        btn_delete = msg.addButton("🗑️ Replace (Delete old)", QMessageBox.AcceptRole)
        btn_keep = msg.addButton("📦 Keep backup", QMessageBox.ActionRole)
        msg.exec()
        
        keep_old = (msg.clickedButton() == btn_keep)
        backup_folder_name = f"old_version_v{CURRENT_VERSION}" if keep_old else "None"
        is_backup_true = "True" if keep_old else "False"

        # 3. BAT-script
        pid = os.getpid()
        bat_path = os.path.join(exe_dir, "updater.bat")
        
        # We save the logs and cache folders so that the user does not lose their data!
        bat_content = f"""@echo off
        title Steempeg Updater
        echo Waiting for Steempeg to close completely...

        :wait_loop
        tasklist /FI "PID eq {pid}" | find "{pid}" > NUL
        if errorlevel 1 goto install
        timeout /t 1 /nobreak > NUL
        goto wait_loop

        :install
        echo Installing update...
        timeout /t 1 /nobreak > NUL

        if "{is_backup_true}"=="True" (
            echo Creating backup folder...
            mkdir "{backup_folder_name}"
            
            
            for %%I in (*.*) do if /I not "%%I"=="updater.bat" if /I not "%%I"=="{final_asset_name}.tmp" move "%%I" "{backup_folder_name}\" > NUL
            
            
            for /D %%D in (*) do (
                if /I not "%%D"=="{backup_folder_name}" if /I not "%%D"=="_update_extracted" if /I not "%%D"=="logs" if /I not "%%D"=="cache" move "%%D" "{backup_folder_name}\" > NUL
            )
        ) else (
            echo Cleaning old files...
            for %%I in (*.*) do if /I not "%%I"=="updater.bat" if /I not "%%I"=="{final_asset_name}.tmp" del /F /Q "%%I"
            for /D %%D in (*) do (
                if /I not "%%D"=="_update_extracted" if /I not "%%D"=="logs" if /I not "%%D"=="cache" rd /S /Q "%%D"
            )
        )

        echo Moving new files...
        xcopy /S /E /Y /C /I "{source_dir}\\*" ".\\" > NUL
        rd /S /Q "_update_extracted"
        del /F /Q "{final_asset_name}.tmp"

        echo Starting new version...
        start "" "{new_exe_name}" --updated-from {CURRENT_VERSION} --backup-folder "{backup_folder_name}"
        del "%~f0"
        """
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(bat_content)

        env = os.environ.copy()
        env.pop('_MEIPASS2', None)
        env.pop('_MEIPASS', None)
        
        subprocess.Popen([bat_path], shell=True, cwd=exe_dir, creationflags=0x08000000, env=env)
        
        QApplication.quit()
        sys.exit(0)


    def scan_clips(self):
        """ Scans both standard Steam folders AND custom extracted folders """
        if not hasattr(self.ui, 'table_clips'): return
        self.ui.table_clips.setSortingEnabled(False) 
        self.ui.table_clips.setRowCount(0)
        
        if not self.clips_folder or not os.path.exists(self.clips_folder): return

        base_folder = os.path.normpath(self.clips_folder)
        if os.path.basename(base_folder).lower() == "clips":
            base_folder = os.path.dirname(base_folder)

        folders_to_check = set()
        
        # Scenario 1: Standard Steam Structure (gamerecordings/clips & gamerecordings/video)
        for sub in ["clips", "video"]:
            sub_path = os.path.join(base_folder, sub)
            if os.path.exists(sub_path):
                for item in os.listdir(sub_path):
                    full = os.path.join(sub_path, item)
                    if os.path.isdir(full): folders_to_check.add(full)
                    
        # Scenario 2: selected the W:\SteamLibrary folder itself directly
        folders_to_check.add(base_folder)
        try:
            for item in os.listdir(base_folder):
                full = os.path.join(base_folder, item)
                if os.path.isdir(full) and item.lower().startswith(("clip_", "bg_", "fg_")):
                    folders_to_check.add(full)
        except Exception: pass

        try:
            # Sort the chaotic set() by folder modification time
            sorted_folders = sorted(list(folders_to_check), key=lambda x: os.path.getmtime(x) if os.path.exists(x) else 0, reverse=True)
            
            for full_path in sorted_folders:
                if not os.path.exists(full_path): continue

                folder_name = os.path.basename(full_path).lower()
                # We strictly allow only Steam clips!
                if not folder_name.startswith(("clip_", "bg_", "fg_")):
                    continue

                folder_name = os.path.basename(full_path).lower()
                if "steempeg" in folder_name or folder_name in ["logs", "cache", "_update_extracted"]:
                    continue
                
                has_mpd = False
                has_chunks = False
                mpd_path = None
                
                for root, dirs, files in os.walk(full_path):
                    for f in files:
                        if f.endswith(".mpd"):
                            has_mpd = True
                            mpd_path = os.path.join(root, f)
                            break 
                    if any("chunk-stream" in f for f in files):
                        has_chunks = True

                if has_chunks and not has_mpd:
                    recovered = self.recover_orphaned_clip(full_path)
                    if recovered: 
                        has_mpd = True
                        # Just in case, search for mpd again after recovery.
                        for root, dirs, files in os.walk(full_path):
                            for f in files:
                                if f.endswith(".mpd"):
                                    mpd_path = os.path.join(root, f)
                                    break 

                if not has_mpd: continue

                # MAGIC: Extracting Duration from MPD
                duration_str = "--:--"
                if mpd_path:
                    try:
                        import re
                        with open(mpd_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            
                            match = re.search(r'(?:mediaPresentationDuration|duration)="PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?"', content)
                            if match:
                                h = int(match.group(1)) if match.group(1) else 0
                                m = int(match.group(2)) if match.group(2) else 0
                                s = int(float(match.group(3))) if match.group(3) else 0
                                
                                # Formatting for a Beautiful Look
                                if h == 0 and m == 0: duration_str = f"{s}s"
                                elif h == 0: duration_str = f"{m}m {s}s"
                                else: duration_str = f"{h}h {m}m {s}s"
                    except: pass

                folder_name = os.path.basename(full_path)
                parts = folder_name.split("_")
                
                if len(parts) >= 4 and parts[1].isdigit():
                    prefix = parts[0].lower()
                    app_id = parts[1]
                    
                    if prefix == "clip": rec_type = "🎬 Clip"
                    elif prefix == "bg": rec_type = "📼 BG"
                    elif prefix == "fg": rec_type = "🎞️ FG"
                    else: rec_type = "Unknown"

                    raw_name = self.get_game_name(app_id)
                    game_name = f"   {raw_name}" 
                    icon = self.get_game_icon(app_id)

                    try:
                        from datetime import timezone
                        # 1. Concatenate the date and time from the folder into a single string (YYYYMMDD_HHMMSS)
                        raw_datetime_str = f"{parts[2]}_{parts[3]}"
                        
                        # 2. We tell Python: "This is UTC time (Greenwich Mean Time)!"
                        dt_utc = datetime.strptime(raw_datetime_str, "%Y%m%d_%H%M%S")
                        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                        
                        # 3. Automatically convert to your time zone (Windows will automatically detect that you are in UTC+3)
                        dt_local = dt_utc.astimezone()
                        
                        # 4. Unpack back into beautiful formats for the interface
                        formatted_date = dt_local.strftime("%d %B %Y")
                        formatted_time = dt_local.strftime("%I:%M %p")
                    except Exception as e:
                        # If the folder is named incorrectly, use the old fallback option.
                        try: formatted_date = datetime.strptime(parts[2], "%Y%m%d").strftime("%d %B %Y")
                        except: formatted_date = parts[2]
                        try: formatted_time = datetime.strptime(parts[3], "%H%M%S").strftime("%I:%M %p")
                        except: formatted_time = ""


                else:
                    rec_type = "Folder"
                    game_name = folder_name
                    formatted_date = "Unknown"
                    icon = QIcon()

                row_position = self.ui.table_clips.rowCount()
                self.ui.table_clips.insertRow(row_position)
                
                item_game = QTableWidgetItem(icon, game_name)
                item_game.setData(Qt.UserRole, full_path) 
                self.ui.table_clips.setItem(row_position, 0, item_game)
                
                item_type = QTableWidgetItem(rec_type)
                item_type.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                self.ui.table_clips.setItem(row_position, 1, item_type)
                
                item_date = QTableWidgetItem(formatted_date)
                self.ui.table_clips.setItem(row_position, 2, item_date)

                date_display = f"{formatted_date}\n{formatted_time}" if formatted_time else formatted_date
                
                item_date = QTableWidgetItem(date_display)
                item_date.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter) 
                self.ui.table_clips.setItem(row_position, 2, item_date)

                # Column 3: DURATION
                item_duration = QTableWidgetItem(duration_str)
                item_duration.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                self.ui.table_clips.setItem(row_position, 3, item_duration)

            self.ui.table_clips.setSortingEnabled(True)

            self.ui.table_clips.horizontalHeader().sectionClicked.connect(lambda: QTimer.singleShot(50, self.sync_grid_to_table))

            if hasattr(self, 'build_netflix_grid'):
                self.build_netflix_grid()
                
            if hasattr(self, 'lbl_clip_count'):
                self.lbl_clip_count.setText(f"• {self.ui.table_clips.rowCount()} Clips")
                
                    
        except Exception as e:
            import logging
            logging.error(f"Scan Error: {e}")
    
    def add_user_marker(self, target_ms=None):
        """ Sets a tag according to Gaben's GOST standard and saves it to JSON. """
        import time, json, os
        
        if not hasattr(self, 'custom_timeline'): return
        canvas = self.custom_timeline.canvas
        
        markers_list = getattr(canvas, 'markers', None)
        if markers_list is None: return

        # FIX: The "clicked" signal of QPushButton passes a boolean (False). 
        # We must ignore it so the marker doesn't fly to 0:00!
        if isinstance(target_ms, bool) or target_ms is None:
            current_time = int(canvas.visual_ms)
        else:
            current_time = int(target_ms)
            
        for m in markers_list:
            if m.get('time_ms', -1) == current_time:
                return 

        # Generate a powerful, unique ID
        new_id = str(int(time.time() * 1000))
        
        # 1. INTERNAL MARKER
        internal_marker = {
            'id': new_id,
            'time_ms': current_time,
            'icon_key': 'usermarker',
            'is_round': False,
            'title': '',
            'desc': ''
        }
        markers_list.append(internal_marker)
        markers_list.sort(key=lambda x: x.get('time_ms', 0))
        canvas.update()
        
        # 2. Steam Format
        json_path = getattr(canvas, 'current_json_path', None)
        if not json_path or not os.path.exists(json_path):
            return
            
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            if 'entries' not in data:
                data['entries'] = []
                
            raw_time = current_time + getattr(canvas, 'current_offset_ms', 0)
            
            steam_marker = {
                "id": new_id,
                "time": str(raw_time),
                "type": "usermarker",
                "title": "",
                "description": "",
                "icon": "steam_marker",
                "priority": 0
            }
            
            data['entries'].append(steam_marker)
            data['entries'].sort(key=lambda x: int(x.get('time', 0)))
            
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Marker save error: {e}")
    def take_screenshot(self, target_ms=None):
        """ Takes a clean screenshot directly from MPV and saves it to the global folder. """
        if not hasattr(self, 'player') or not self.player: return
        
        # Ensure the global folder exists (just in case)
        if not hasattr(self, 'screenshots_dir') or not os.path.exists(self.screenshots_dir):
            self.screenshots_dir = os.path.join(get_save_directory(), "Screenshots")
            os.makedirs(self.screenshots_dir, exist_ok=True)
            
        # Get the clip name (if selected) to add to the file name
        game_name = "Clip"
        row = self.ui.table_clips.currentRow()
        if hasattr(self.ui, 'table_clips') and row >= 0:
            item = self.ui.table_clips.item(row, 0)
            if item: 
                # Trim extra spaces from the ends of the name
                game_name = item.text().strip()
                # Replace characters forbidden in filenames with underscores.
                import re
                game_name = re.sub(r'[\\/*?:"<>|]', "_", game_name)

        # Determine the time (if a marker was clicked, use its time; otherwise, use the player's time)
        pos_ms = float(target_ms) if target_ms is not None else (getattr(self.player, 'time_pos', 0) * 1000)
        
        # Creating an attractive name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{game_name}_{int(pos_ms)}ms_{timestamp}.png"
        filepath = os.path.join(self.screenshots_dir, filename).replace('\\', '/')
        
        need_seek = False
        original_pos = getattr(self.player, 'time_pos', 0) * 1000
        
        # If we right-click far away from the slider, we need to jump there for a split second
        if target_ms is not None and abs(target_ms - original_pos) > 200:
            need_seek = True
            self.player.seek(pos_ms / 1000.0, reference='absolute', precision='exact')
            time.sleep(0.15) 
            
        try:
            self.player.command('screenshot-to-file', filepath, 'video')
            print(f"📸 Screenshot saved to: {filepath}")
        except Exception as e:
            print(f"Screenshot error: {e}")
            
        # We jump back in as if nothing had happened.
        if need_seek:
            self.player.seek(original_pos / 1000.0, reference='absolute', precision='exact')
    def choose_destination(self):
        """ Select a custom folder to save the finished video """
        folder = QFileDialog.getExistingDirectory(self.ui, "Select Destination Folder")
        if folder:
            self.custom_destination = folder
            self.ui.destination_button.setText(f"Destination: {folder}")
        else:
            # If we change our minds and click Cancel, we return to our cool folder
            default_export_dir = os.path.join(get_save_directory(), "rendered_videos").replace('\\', '/')
            if not os.path.exists(default_export_dir):
                os.makedirs(default_export_dir, exist_ok=True)
            self.custom_destination = default_export_dir
            self.ui.destination_button.setText(f"Destination: {default_export_dir}")
            
        self.update_final_setup()

    def open_logs_folder(self):
        if hasattr(self, 'logs_dir'):
            paths.open_in_file_manager(self.logs_dir)

    def open_current_log(self):
        if hasattr(self, 'current_log_file'):
            paths.open_in_file_manager(self.current_log_file)
        
    def get_all_mpd_paths(self, clip_path):
        return discovery.find_mpd_paths(clip_path)

    def fix_steam_manifest(self, mpd_path):
        return repair.fix_steam_manifest(mpd_path)

    def recover_orphaned_clip(self, folder_path):
        return repair.recover_orphaned_clip(folder_path)
    
    def get_game_name(self, app_id):
        app_id = str(app_id)
        # 1. сначала кэш
        if app_id in self.game_names_cache:
            return self.game_names_cache[app_id]
        # 2. иначе спросить Steam один раз и запомнить
        name = games.fetch_game_name(app_id)
        if name:
            self.game_names_cache[app_id] = name
            self.save_json_cache()
            return name
        return f"Unknown Game ({app_id})"
    
    def on_audio_only_toggled(self, checked):
        """ Disables video settings if audio-only mode is active """
        if checked and hasattr(self.ui, 'check_mute_audio'):
            self.ui.check_mute_audio.blockSignals(True)
            self.ui.check_mute_audio.setChecked(False)
            self.ui.check_mute_audio.blockSignals(False)
            
        if hasattr(self.ui, 'tab_video'): 
            self.ui.tab_video.setEnabled(not checked) # Freeze entire Video Tab
        self.update_final_setup()

    def on_mute_audio_toggled(self, checked):
        """ Disables audio settings if video-only mode is active """
        if checked and hasattr(self.ui, 'check_audio_only'):
            self.ui.check_audio_only.blockSignals(True)
            self.ui.check_audio_only.setChecked(False)
            self.ui.check_audio_only.blockSignals(False)
            
        if hasattr(self.ui, 'tab_audio'): 
            self.ui.tab_audio.setEnabled(not checked) # Freeze entire Audio Tab
        self.update_final_setup()
    
    def load_json_cache(self):
        return cache.read_json(self.json_cache_path)

    def save_json_cache(self):
        cache.write_json(self.json_cache_path, self.game_names_cache)

    def load_user_settings(self):
        return cache.read_json(os.path.join(self.cache_dir, "settings.json"))

    def save_user_settings(self, key, value):
        """ Saves a specific preference to the settings file permanently """
        path = os.path.join(self.cache_dir, "settings.json")
        settings = cache.read_json(path)
        settings[key] = value
        cache.write_json(path, settings)
    
    def get_game_icon(self, app_id):
        app_id = str(app_id)
        # 1. RAM-кэш
        if app_id in self.game_icons_cache:
            return self.game_icons_cache[app_id]
        # 2. диск-кэш, иначе скачиваем
        icon_path = os.path.join(self.cache_dir, f"{app_id}.jpg")
        if not os.path.exists(icon_path):
            if not games.download_icon(app_id, icon_path):
                return QIcon()
        # 3. строим Qt-иконку (это Qt -> остаётся тут) и кэшируем в RAM
        icon = QIcon(QPixmap(icon_path))
        self.game_icons_cache[app_id] = icon
        return icon

    def get_clip_size_and_duration(self, clip_path, mpd_content):
        # total size of the clip folder
        size_mb = discovery.folder_size_bytes(clip_path) / (1024 * 1024)
        size_str = f"{size_mb / 1024:.2f} GB" if size_mb >= 1000 else f"{size_mb:.1f} MB"

        # duration: the parsing lives in mpd.py now, the display formatting stays here
        seconds = mpd.parse_duration_seconds(mpd_content)
        if seconds is None:
            self.current_clip_duration_sec = 0.0   # reset so no old time stays from the last clip
            duration_str = "Unknown"
        else:
            self.current_clip_duration_sec = seconds
            # show H:MM:SS when it is over an hour, otherwise just MM:SS
            total = int(seconds)
            h, m, s = total // 3600, (total % 3600) // 60, total % 60
            duration_str = f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

        self.current_clip_duration_str = duration_str
        return size_str, duration_str
    
    def get_fps_from_mpd(self, mpd_path):
        return mpd.get_fps(mpd_path)

    def get_audio_bitrate_from_mpd(self, mpd_path):
        return mpd.get_audio_bitrate_kbps(mpd_path)
    
    def detect_gpu_and_set_encoder(self):
        """Probe the hardware encoders and fill the encoder dropdown."""
        if not hasattr(self.ui, 'combo_encoder'):
            return
        self.ui.combo_encoder.clear()

        logging.info("Starting silent hardware encoder probe...")
        encoders = capabilities.detect_supported_encoders()
        logging.info(f"Probe done. Available: {[name for name, _ in encoders]}")
        for display_name, codec in encoders:
            self.ui.combo_encoder.addItem(display_name, codec)

        # default to the first hardware encoder if there is one, otherwise CPU
        self.ui.combo_encoder.setCurrentIndex(1 if self.ui.combo_encoder.count() > 1 else 0)
    

    def on_grid_selection_changed(self):
        """ Select in Grid -> Quietly select in List -> List automatically updates the player """
        selected_items = getattr(self, 'grid_clips', None) and self.grid_clips.selectedItems()
        if not selected_items: return
        
        # In the Qt.UserRole card we have a ready-made string index (number)!
        row_idx = selected_items[0].data(Qt.UserRole)
        
        if hasattr(self.ui, 'table_clips'):
            # Check if this row is already selected
            if self.ui.table_clips.currentRow() != row_idx:
                # Just move the focus. The table itself will trigger the player exactly once!
                self.ui.table_clips.selectRow(row_idx)

    def build_netflix_grid(self):
        """ Transforms rows from a hidden table into vibrant cards. """
        import PySide6.QtWidgets as qtw
        if not hasattr(self, 'grid_clips') or not hasattr(self.ui, 'table_clips'):
            return
            
        self.grid_clips.clear()
        
        for row in range(self.ui.table_clips.rowCount()):
            title_item = self.ui.table_clips.item(row, 0)
            date_item = self.ui.table_clips.item(row, 2)
            time_item = self.ui.table_clips.item(row, 3)
            
            title = title_item.text() if title_item else "Unknown"
            date_str = date_item.text() if date_item else "Today"
            time_str = time_item.text() if time_item else "00:00"
            clip_path = title_item.data(Qt.UserRole) if title_item else None
            
            icon_path = ""
            thumb_path = ""
            badge_text = "Clip"
            
            if clip_path:
                clip_folder_name = os.path.basename(clip_path)
                parts = clip_folder_name.split("_")
                
                # Extract the clip type
                if len(parts) > 0:
                    prefix = parts[0].upper()
                    if prefix in ["FG", "BG", "CLIP"]: badge_text = prefix
                    
                if len(parts) >= 2 and parts[1].isdigit():
                    icon_path = os.path.join(self.cache_dir, f"{parts[1]}.jpg")
                    
                if os.path.exists(clip_path):
                    # Check "thumbnail.jpg" directly without scanning the folder
                    direct_thumb = os.path.join(clip_path, "thumbnail.jpg")
                    if os.path.exists(direct_thumb):
                        thumb_path = direct_thumb
                    else:
                        # Fallback option (in case the file has a different name)
                        # Only then do we use the resource-intensive os.listdir
                        for file in os.listdir(clip_path):
                            if file.endswith((".jpg", ".png", ".jpeg")):
                                thumb_path = os.path.join(clip_path, file)
                                break

            # Create the custom card
            card = ClipCard(title, f"{date_str} • {time_str}", badge_text, thumb_path, icon_path, row)
            
            item = qtw.QListWidgetItem(self.grid_clips)
            item.setSizeHint(qtc.QSize(260, 190))

            item.setData(Qt.UserRole, row) # Save row index for selection logic
            item.setData(Qt.UserRole + 1, clip_path) 
            self.grid_clips.setItemWidget(item, card)

            
            # SYNC VISIBILITY WITH TABLE
            if self.ui.table_clips.isRowHidden(row):
                item.setHidden(True)

    

    def update_quality_options(self):
        """ Reads the clip's XML data and prepares the UI for the render settings """
        if not hasattr(self.ui, 'table_clips'): return
        selected_row = self.ui.table_clips.currentRow()
        if selected_row < 0:
            self.ui.source_label.setText("Source:")
            self.ui.orig_res_label.setText("Original Resolution:")
            # Set default empty states for our new widgets
            if hasattr(self.ui, 'label_vbitrate'): self.ui.label_vbitrate.setText("Video Bitrate:")
            if hasattr(self.ui, 'label_abitrate'): self.ui.label_abitrate.setText("Audio Bitrate:")
            return
        if hasattr(self, 'grid_clips'):
            self.grid_clips.blockSignals(True) # To Avoid Conflicts
            for i in range(self.grid_clips.count()):
                item = self.grid_clips.item(i)
                # Verify the card's hidden index against the selected row in the table.
                if item.data(Qt.UserRole) == selected_row:
                    item.setSelected(True)
                    self.grid_clips.scrollToItem(item)# Automatically scroll to the desired tile!
                else:
                    item.setSelected(False)
            self.grid_clips.blockSignals(False)
        
        # --- 1. SAVE CURRENT USER SELECTION ---
        current_quality = self.ui.combo_quality.currentText() if hasattr(self.ui, 'combo_quality') else ""
        current_fps = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else ""
        current_bitrate = self.ui.combo_bitrate.currentText() if hasattr(self.ui, 'combo_bitrate') else ""
            
        # Extract the FULL path (for FFmpeg)
        clip_path = self.ui.table_clips.item(selected_row, 0).data(Qt.UserRole)
        

        
        # Extract ONLY the folder NAME (for example, bg_3513350_20260508) for the text field
        clip_folder_name = os.path.basename(clip_path)

        parts = clip_folder_name.split("_")
        if len(parts) >= 2 and parts[1].isdigit():
            self.current_game_icon = os.path.join(self.cache_dir, f"{parts[1]}.jpg")
        else:
            self.current_game_icon = ""

        ## Automatically insert a neat file name
        if hasattr(self.ui, 'input_filename'):
            self.ui.input_filename.setText(f"{clip_folder_name}_rendered")
            
        # Search for mpd files by full path
        all_mpds = self.get_all_mpd_paths(clip_path)

        if not all_mpds:
            self.ui.source_label.setText("Source: No MPD files found")
            self.ui.orig_res_label.setText("Original resolution: Unknown")
            # Update our new widgets
            if hasattr(self.ui, 'label_vbitrate'): self.ui.label_vbitrate.setText("Video Bitrate: Unknown")
            if hasattr(self.ui, 'label_abitrate'): self.ui.label_abitrate.setText("Audio Bitrate: Unknown")
            self.ui.combo_quality.clear()
            if hasattr(self, 'btn_copy_src'): self.btn_copy_src.hide()
            return

        # Update the label with the path to the sources
        source_dirs = [os.path.dirname(mpd) for mpd in all_mpds]
        unique_source_dirs = list(dict.fromkeys(source_dirs))
        
        # Save FULL raw paths to memory so our COPY button can copy them completely!
        self.current_source_raw_paths = "\n".join(unique_source_dirs)
        
        # Local helper to cleanly cut long HTML paths
        def elide_html_path(path, max_len=75):
            if len(path) <= max_len: return path
            half = (max_len - 5) // 2
            return path[:half] + "[...]" + path[-half:]
        
        # Apply the cut [...] only for the visual UI
        formatted_sources = "<br>".join([f"{i+1}. {elide_html_path(p)}" for i, p in enumerate(unique_source_dirs)])
        self.ui.source_label.setText(f"Source:<br><span style='font-size:8pt; color:#aaaaaa;'>{formatted_sources}</span>")
        
        # Show the copy button now that we have a valid path!
        if hasattr(self, 'btn_copy_src'): 
            self.btn_copy_src.show()

        # Reading bitrait
        orig_audio_bitrate = self.get_audio_bitrate_from_mpd(all_mpds[0]) if all_mpds else 192
        self.current_orig_audio_bitrate = orig_audio_bitrate

        if hasattr(self.ui, 'combo_audio_bitrate'):
            self.ui.combo_audio_bitrate.blockSignals(True)
            self.ui.combo_audio_bitrate.clear()
            
            bitrates = [
                (320, "320 kbps (Best Quality)"),
                (256, "256 kbps (High Quality)"),
                (192, "192 kbps (Good Quality)"),
                (128, "128 kbps (Standard)"),
                (64, "64 kbps (Bad)"),
                (32, "32 kbps (Very bad)")
            ]
            
            self.ui.combo_audio_bitrate.addItem(f"{orig_audio_bitrate} kbps (Original)")
            
            # We add to the list only those that do not exceed the original (with a small margin)
            for val, text in bitrates:
                if val <= orig_audio_bitrate + 15: 
                    self.ui.combo_audio_bitrate.addItem(text)
            
            self.ui.combo_audio_bitrate.insertSeparator(self.ui.combo_audio_bitrate.count())
            self.ui.combo_audio_bitrate.addItem("⚙️ Custom Audio...")

            self.ui.combo_audio_bitrate.blockSignals(False)
        
        unique_resolutions = set()
        max_height = 0
        self.current_orig_bitrate = 0

        # Parsing session.mpd to find the original resolution and bitrate
        for mpd_path in all_mpds:
            try:
                with open(mpd_path, 'r', encoding='utf-8') as file:
                    content = file.read()

                    # Call our function to calculate the size and time
                    clip_full_path = os.path.dirname(mpd_path)
                    size_str, duration_str = self.get_clip_size_and_duration(clip_full_path, content)
                    
                    if hasattr(self.ui, 'label_size'):
                        self.ui.label_size.setText(f"Size: {size_str}")
                    if hasattr(self.ui, 'label_duration'):
                        self.ui.label_duration.setText(f"Time: {duration_str}")

                    #1. Trying to find FPS in an XML file (the fastest way)
                    fps_match = re.search(r'\bframeRate="(\d+)(?:/\d+)?"', content)
                    if fps_match:
                        self.current_orig_fps = int(fps_match.group(1))
                    else:
                        # 2. Call ffprobe and let it READ THE MPD FILE!
                        self.current_orig_fps = self.get_fps_from_mpd(mpd_path)
                        
                    #UPDATE YOUR LABEL
                    if hasattr(self.ui, 'label_fps'):
                        self.ui.label_fps.setText(f"FPS: {self.current_orig_fps}")
                    
                    height_match = re.search(r'\bheight="(\d+)"', content)
                    width_match = re.search(r'\bwidth="(\d+)"', content)
                    bandwidth_match = re.search(r'\bbandwidth="(\d+)"', content)
                    
                    if bandwidth_match:
                        # Converting bitrate from bytes to mb
                        self.current_orig_bitrate = int(bandwidth_match.group(1)) / 1000000
                    
                    if height_match and width_match:
                        h = int(height_match.group(1))
                        w = int(width_match.group(1))
                        unique_resolutions.add(f"{w}x{h}")
                        if h > max_height: max_height = h
            except: pass

        if unique_resolutions:
            res_text = ", ".join(sorted(list(unique_resolutions)))
            audio_kbps = getattr(self, 'current_orig_audio_bitrate', 192)
            
            # Keep only the resolution here
            self.ui.orig_res_label.setText(f"Original resolution: {res_text}")
            
            # Populate Video Bitrate independently (Removed the '~' symbol!)
            if hasattr(self.ui, 'label_vbitrate'):
                if hasattr(self, 'current_orig_bitrate') and self.current_orig_bitrate > 0:
                    rounded_bitrate = int(round(self.current_orig_bitrate))
                    self.ui.label_vbitrate.setText(f"Video Bitrate: {rounded_bitrate} Mbps")
                else:
                    self.ui.label_vbitrate.setText("Video Bitrate: Unknown")
            
            # Populate Audio Bitrate independently
            if hasattr(self.ui, 'label_abitrate'):
                self.ui.label_abitrate.setText(f"Audio Bitrate: {audio_kbps} kbps")
                
        else:
            self.ui.orig_res_label.setText("Original resolution: Unknown")
            if hasattr(self.ui, 'label_vbitrate'): self.ui.label_vbitrate.setText("Video Bitrate: Unknown")
            if hasattr(self.ui, 'label_abitrate'): self.ui.label_abitrate.setText("Audio Bitrate: Unknown")
            max_height = 1080

        # Fill in the drop-down list of resolutions (cutting off those that are larger than the original)
        if hasattr(self.ui, 'combo_quality'):
            self.ui.combo_quality.clear()
            
            # Dynamic Original Title (eg: Original (Lossless, 1440p))
            if max_height > 0:
                self.ui.combo_quality.addItem(f"Original (Lossless, {max_height}p)")
            else:
                self.ui.combo_quality.addItem("Original (Lossless)")

            for preset_name, preset_height in self.all_qualities:
                if preset_height <= max_height:
                    self.ui.combo_quality.addItem(preset_name)
            
            self.ui.combo_quality.setCurrentIndex(0)
            self.ui.combo_quality.insertSeparator(self.ui.combo_quality.count())
            self.ui.combo_quality.addItem("🎯 Target File Size...")
            self.update_bitrate_options() # Calling a function to update bitrates
        
        if hasattr(self.ui, 'combo_fps'):
            self.ui.combo_fps.clear()
            
            # Take FPS from the clip
            fps_val = getattr(self, 'current_orig_fps', 60)
            
            if fps_val >= 60:
                self.ui.combo_fps.addItem(f"{fps_val} FPS (Original)")
                self.ui.combo_fps.addItem("30 FPS")
                self.ui.combo_fps.addItem("15 FPS")
            elif fps_val >= 30:
                self.ui.combo_fps.addItem(f"{fps_val} FPS (Original)")
                self.ui.combo_fps.addItem("15 FPS")
            else:
                self.ui.combo_fps.addItem(f"{fps_val} FPS (Original)")

            self.ui.combo_fps.insertSeparator(self.ui.combo_fps.count())
            self.ui.combo_fps.addItem("⚙️ Custom FPS...")

            self.ui.combo_fps.setCurrentIndex(0)
        else:
            print("ERROR: Widget combo_fps not found! Check objectName in Qt Designer.")
        
        # 2. RESTORE USER SELECTION (IF IT STILL EXISTS)
        if current_quality and hasattr(self.ui, 'combo_quality'):
            index = self.ui.combo_quality.findText(current_quality)
            if index >= 0: self.ui.combo_quality.setCurrentIndex(index)
            
        if current_fps and hasattr(self.ui, 'combo_fps'):
            index = self.ui.combo_fps.findText(current_fps)
            if index >= 0: self.ui.combo_fps.setCurrentIndex(index)
            
        if current_bitrate and hasattr(self.ui, 'combo_bitrate'):
            index = self.ui.combo_bitrate.findText(current_bitrate)
            if index >= 0: self.ui.combo_bitrate.setCurrentIndex(index)

        # Unlock start button safely
        if not getattr(self, '_is_rendering', False):
            self.ui.btn_start.setEnabled(True)

        self.ui.btn_start.setEnabled(True)
        self.update_final_setup()

        # --- PLAYER HEADER DATA ---
        game_item = self.ui.table_clips.item(selected_row, 0)
        game_name = game_item.text()
        game_icon = game_item.icon()
        
        clip_date = self.ui.table_clips.item(selected_row, 2).text()
        clip_time = self.ui.table_clips.item(selected_row, 3).text()
        
        # Updating our correct software panel
        if hasattr(self, 'custom_text_label'):
            header_html = f"<b>{game_name}</b> <span style='color: #888;'>&nbsp;&nbsp;•&nbsp;&nbsp; {clip_date} &nbsp;&nbsp;•&nbsp;&nbsp; {clip_time}</span>"
            self.custom_text_label.setText(header_html)
            
        if hasattr(self, 'custom_icon_label'):
            self.custom_icon_label.setPixmap(game_icon.pixmap(24, 24))

        # Automatically load and play the new clip. This overwrites the stuck frame of the previous clip!
        self.generate_and_play_preview()
        
    
    def update_bitrate_options(self):
        """ Refreshes lists, applies FPS math visually, and freezes settings if Original is selected. """
        if not hasattr(self.ui, 'combo_bitrate') or not hasattr(self.ui, 'combo_quality'):
            return 
            
        # --- SAVE CURRENT SELECTION (so it doesn't get lost when changing FPS) ---
        current_selection = self.ui.combo_bitrate.currentText()
        selected_level = current_selection.split(" - ")[0] if " - " in current_selection else ""

        self.ui.combo_bitrate.blockSignals(True)
        self.ui.combo_bitrate.clear()
        quality_text = self.ui.combo_quality.currentText()

        if "Original" in quality_text:
            if hasattr(self, 'current_orig_bitrate') and self.current_orig_bitrate > 0:
                self.ui.combo_bitrate.addItem(f"~{int(self.current_orig_bitrate)} Mbps (Original Copy)")
            else:
                self.ui.combo_bitrate.addItem("Original Bitrate (Copy)")
                
            self.ui.combo_bitrate.setEnabled(False) 
            if hasattr(self.ui, 'combo_fps'):
                self.ui.combo_fps.setCurrentIndex(0) 
                self.ui.combo_fps.setEnabled(False)
            if hasattr(self.ui, 'combo_codec'): self.ui.combo_codec.setEnabled(False)
            if hasattr(self.ui, 'combo_encoder'): self.ui.combo_encoder.setEnabled(False)
            self.ui.combo_bitrate.blockSignals(False)
            self.update_final_setup()
            return

        self.ui.combo_bitrate.setEnabled(True) 
        if hasattr(self.ui, 'combo_fps'): self.ui.combo_fps.setEnabled(True)
        if hasattr(self.ui, 'combo_codec'): self.ui.combo_codec.setEnabled(True)
        if hasattr(self.ui, 'combo_encoder'): self.ui.combo_encoder.setEnabled(True)
        
        match = re.search(r'^(\d+)p', quality_text)
        if not match: 
            self.ui.combo_bitrate.blockSignals(False)
            return
            
        res_key = f"{match.group(1)}p"
        added_any = False
        
        # Calculating the FPS Multiplier for Visuals
        fps_multiplier = 1.0
        fps_text = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else "60"
        orig_fps = getattr(self, 'current_orig_fps', 60)
        
        if "Custom" in fps_text and hasattr(self, 'input_custom_fps'):
            try: selected_fps = int(self.input_custom_fps.text())
            except: selected_fps = orig_fps
        else:
            try: selected_fps = int(re.search(r'(\d+)', fps_text).group(1))
            except: selected_fps = orig_fps
            
        if selected_fps < orig_fps and orig_fps > 0:
            fps_multiplier = selected_fps / orig_fps

        for quality_level in ["Ultra", "High", "Medium", "Low"]:
            if res_key in self.steam_bitrate_presets.get(quality_level, {}):
                preset_bitrate = self.steam_bitrate_presets[quality_level][res_key]
                
                if getattr(self, 'current_orig_bitrate', 0) == 0 or preset_bitrate <= (self.current_orig_bitrate + 5):
                    # We're multiplying right here just for the sake of appearance in the ComboBox!
                    scaled_bitrate = preset_bitrate * fps_multiplier
                    
                    display_val = f"{scaled_bitrate:.1f}".rstrip('0').rstrip('.') if scaled_bitrate % 1 != 0 else str(int(scaled_bitrate))
                    
                    self.ui.combo_bitrate.addItem(f"{quality_level} - {display_val} Mbps")
                    added_any = True
        
        if not added_any and res_key in self.steam_bitrate_presets["Low"]:
            lowest_bitrate = self.steam_bitrate_presets["Low"][res_key] * fps_multiplier
            display_val = f"{lowest_bitrate:.1f}".rstrip('0').rstrip('.') if lowest_bitrate % 1 != 0 else str(int(lowest_bitrate))
            self.ui.combo_bitrate.addItem(f"Low - {display_val} Mbps")
        
        self.ui.combo_bitrate.insertSeparator(self.ui.combo_bitrate.count())
        self.ui.combo_bitrate.addItem("⚙️ Custom Bitrate...")
        
        # --- RESTORING SELECTION ---
        if selected_level:
            for i in range(self.ui.combo_bitrate.count()):
                if self.ui.combo_bitrate.itemText(i).startswith(selected_level):
                    self.ui.combo_bitrate.setCurrentIndex(i)
                    break

        self.ui.combo_bitrate.blockSignals(False)
        self.update_final_setup()
    
    def refresh_slider_if_needed(self):
        """ Updates the monkeymeter if the user has switched FPS """
        if hasattr(self.ui, 'size_slider') and self.ui.size_slider.isVisible():
            self.on_slider_moved(self.ui.size_slider.value())

        
    def update_final_setup(self):
        """Dynamically updates the Detailed Summary, Size, and Save Path."""
        if not hasattr(self.ui, 'table_clips') or self.ui.table_clips.currentRow() < 0:
            if hasattr(self.ui, 'label_short_summary'):
                if hasattr(self, 'reset_bottom_summary'): self.reset_bottom_summary()
            if hasattr(self.ui, 'label_detailed_summary'):
                self.ui.label_detailed_summary.setText("Waiting for clip selection...")
            if hasattr(self.ui, 'label_status'):
                self.ui.label_status.setText("Ready")
                
            if hasattr(self, 'btn_copy_loc'): self.btn_copy_loc.hide()
            return

        #1: Read everything from the UI
        quality = self.ui.combo_quality.currentText() if hasattr(self.ui, 'combo_quality') else ""
        fps = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else ""
        bitrate_text = self.ui.combo_bitrate.currentText() if hasattr(self.ui, 'combo_bitrate') else ""
        codec_raw = self.ui.combo_codec.currentText() if hasattr(self.ui, 'combo_codec') else ""
        codec = codec_raw.split()[0] if codec_raw else "Unknown"
        encoder = self.ui.combo_encoder.currentText() if hasattr(self.ui, 'combo_encoder') else ""

        audio_only = self.ui.check_audio_only.isChecked() if hasattr(self.ui, 'check_audio_only') else False
        mute_audio = self.ui.check_mute_audio.isChecked() if hasattr(self.ui, 'check_mute_audio') else False
        audio_format = self.ui.combo_audio_format.currentText() if hasattr(self.ui, 'combo_audio_format') else "AAC"
        audio_bitrate = self.ui.combo_audio_bitrate.currentText() if hasattr(self.ui, 'combo_audio_bitrate') else "192 kbps"

        # 2. Calculate the file extension
        ext = ".mp3" if (audio_only and audio_format == "MP3") else (".aac" if audio_only else ".mp4")

        # 3. OVERWRITE PROTECTION 
        save_dir = self.custom_destination if self.custom_destination else get_save_directory()
        base_filename = self.ui.input_filename.text().strip() if hasattr(self.ui, 'input_filename') else "rendered"
        
        for e in [".mp4", ".mp3", ".aac"]:
            if base_filename.lower().endswith(e): base_filename = base_filename[:-4]

        test_path = os.path.join(save_dir, f"{base_filename}{ext}")
        counter = 1
        while os.path.exists(test_path):
            test_path = os.path.join(save_dir, f"{base_filename}_{counter}{ext}")
            counter += 1
            
        full_path = test_path
        final_filename = os.path.basename(full_path)
        self.current_output_file = full_path

        if hasattr(self.ui, 'label_location'):
            self.ui.label_location.setText(f"Output: {full_path}")
            
        if hasattr(self, 'btn_copy_loc') and full_path:
            self.btn_copy_loc.show()
            

        # 4. Collecting texts & Smart Math
        duration = self.get_effective_duration() # Use trimmed duration for math!
        
        # Format the beautiful "Clip time: ✂️ 00:10 - 01:50" string
        if hasattr(self, 'custom_timeline') and self.custom_timeline.is_trim_mode:
            start_s = self.custom_timeline.trim_start_ms / 1000.0
            end_s = self.custom_timeline.trim_end_ms / 1000.0
            
            s_h = int(start_s // 3600)
            s_m = int((start_s % 3600) // 60)
            s_s = int(start_s % 60)
            
            e_h = int(end_s // 3600)
            e_m = int((end_s % 3600) // 60)
            e_s = int(end_s % 60)
            
            if s_h > 0 or e_h > 0:
                duration_str = f"✂️ {s_h:02d}:{s_m:02d}:{s_s:02d} - {e_h:02d}:{e_m:02d}:{e_s:02d}"
            else:
                duration_str = f"✂️ {s_m:02d}:{s_s:02d} - {e_m:02d}:{e_s:02d}"
        else:
            duration_str = getattr(self, 'current_clip_duration_str', "Unknown")
        
        # Calculating the size using the EFFECTIVE duration
        size_str = "Unknown"
        fps_multiplier = 1.0
        if fps:
            if "Custom" in fps and hasattr(self, 'input_custom_fps'):
                try: selected_fps = int(self.input_custom_fps.text())
                except: selected_fps = getattr(self, 'current_orig_fps', 60)
            else:
                try: selected_fps = int(re.search(r'(\d+)', fps).group(1))
                except: selected_fps = getattr(self, 'current_orig_fps', 60)
                
            orig_fps = getattr(self, 'current_orig_fps', 60)
            if selected_fps < orig_fps and orig_fps > 0:
                fps_multiplier = selected_fps / orig_fps

        if duration > 0:
            if "Target File Size" in quality:
                if hasattr(self, 'dynamic_stops') and hasattr(self.ui, 'size_slider'):
                    target_mb = self.dynamic_stops[self.ui.size_slider.value()]
                    size_str = f"~{target_mb / 1024:.2f} GB (Target)" if target_mb >= 1000 else f"~{target_mb} MB (Target)"
            elif "Original" in bitrate_text:
                if hasattr(self, 'current_orig_bitrate') and self.current_orig_bitrate > 0:
                    orig_total_bitrate = (self.current_orig_bitrate * fps_multiplier) + 0.19 
                    size_mb = (orig_total_bitrate * duration) / 8 
                    size_str = f"Same as original (~{size_mb / 1024:.2f} GB)" if size_mb >= 1000 else f"Same as original (~{size_mb:.1f} MB)"
                else:
                    size_str = "Same as original"
            else:
                match = re.search(r'-\s*([\d.]+)\s*Mbps', bitrate_text)
                if match:
                    video_bitrate = float(match.group(1)) 
                    audio_bitrate_val = float(audio_bitrate.split(' ')[0]) / 1000 if ' ' in audio_bitrate else 0.19
                    if mute_audio: audio_bitrate_val = 0
                    total_bitrate = video_bitrate + audio_bitrate_val
                    size_mb = (total_bitrate * duration) / 8 
                    size_str = f"~{size_mb / 1024:.2f} GB" if size_mb >= 1000 else f"~{size_mb:.1f} MB"

        if audio_only:
            sound_info = f"{audio_format} {audio_bitrate.split(' ')[0]} kbps"
            other_info = ">> EXTRACT AUDIO ONLY (NO VIDEO)"
        elif mute_audio:
            sound_info = "None"
            other_info = ">> NO SOUND (MUTED)"
        else:
            sound_info = audio_bitrate
            other_info = "Normal Render"

        # 5. Smart Detailed Summary in Export Settings
        
        # --- CLEAN PARSING FOR UI DISPLAY ---
        
        # Parse Video Bitrate for UI
        video_bitrate_display = "Unknown"
        orig_v_bitrate = getattr(self, 'current_orig_bitrate', 10.0)

        if "Target File Size" in quality:
            val_mbps = getattr(self, 'custom_target_bitrate', 1500) / 1000
            scale_h = getattr(self, 'custom_target_height', -1)
            res_str = f"Auto: {scale_h}p" if scale_h > 0 else "Original"
            clean_mbps = int(round(val_mbps))
            video_bitrate_display = f"{clean_mbps} Mbps ({res_str})"
        elif "Custom" in bitrate_text:
            try:
                val = float(self.input_custom_vbitrate.text().replace(',', '.'))
                val = max(0.1, min(val, orig_v_bitrate))
                # Multiply by the FPS drop
                video_bitrate_display = f"⚙️ {val * fps_multiplier:.1f} Mbps"
            except:
                video_bitrate_display = f"{orig_v_bitrate * fps_multiplier:.1f} Mbps"
        elif "Original" in bitrate_text:
            video_bitrate_display = f"{orig_v_bitrate * fps_multiplier:.1f} Mbps"
        else:
            match = re.search(r'-\s*([\d.]+)\s*Mbps', bitrate_text)
            if match: 
                video_bitrate_display = f"{float(match.group(1)):.1f} Mbps"

        # Parse Audio Bitrate for UI
        orig_a_bitrate = getattr(self, 'current_orig_audio_bitrate', 192)
        if "Custom" in audio_bitrate:
            try:
                val = int(self.input_custom_abitrate.text())
                val = max(1, min(val, orig_a_bitrate))
                audio_bitrate_clean = f"⚙️ {val} kbps"
            except:
                audio_bitrate_clean = f"{orig_a_bitrate} kbps"
        else:
            # Clean up "(Original Copy)" just "192 kbps"
            audio_bitrate_clean = audio_bitrate.split('(')[0].strip() if audio_bitrate else "192 kbps"

        # Parse FPS for UI (includes the word "FPS" inside)
        orig_fps = getattr(self, 'current_orig_fps', 60)
        if "Custom" in fps:
            max_allowed = min(60, orig_fps)
            try:
                val = int(self.input_custom_fps.text())
                val = max(1, min(val, max_allowed))
                fps_display = f"⚙️ {val} FPS"
            except:
                fps_display = f"{max_allowed} FPS"
        else:
            val_str = fps.split(' ')[0] if fps else "Unknown"
            fps_display = f"{val_str} FPS" if val_str != "Unknown" else "Unknown"

        # Clean strings
        q_clean = quality.split('(')[0].strip() if quality else "Unknown"
        enc_clean = encoder if encoder else "Unknown"

        # Construct the final detailed text block 
        if audio_only:
            detailed_text = (
                f"Clip time: {duration_str}\n"
                f"Format: {audio_format}\n"
                f"Sound: {audio_format}, {audio_bitrate_clean}\n"
                f"Other settings: >> EXTRACT AUDIO ONLY (NO VIDEO)\n"
                f"Est. File Size: {size_str}"
            )
        elif mute_audio:
            detailed_text = (
                f"Clip time: {duration_str}\n"
                f"Quality: {q_clean}\n"
                f"FPS: {fps_display}\n"
                f"Bitrate: {video_bitrate_display}\n"
                f"Codec: {codec}\n"
                f"Encoder: {enc_clean}\n"
                f"Other settings: >> NO SOUND (MUTED)\n"
                f"Est. File Size: {size_str}"
            )
        else:
            detailed_text = (
                f"Clip time: {duration_str}\n"
                f"Quality: {q_clean}\n"
                f"FPS: {fps_display}\n"
                f"Bitrate: {video_bitrate_display}\n"
                f"Codec: {codec}\n"
                f"Encoder: {enc_clean}\n"
                f"Sound: {audio_format}, {audio_bitrate_clean}\n"
                f"Other settings: Normal Render\n"
                f"Est. File Size: {size_str}"
            )
            
        if hasattr(self.ui, 'label_detailed_summary'):
            self.ui.label_detailed_summary.setText(detailed_text)

        # 6. Short Summary ABOVE Ready 
        q_word = quality.split()[0] if quality.split() else "Unknown"
        
        game_name = "Steam Clip"
        if hasattr(self.ui, 'table_clips') and self.ui.table_clips.currentRow() >= 0:
            game_name = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0).text().strip()
            
        game_icon = getattr(self, 'current_game_icon', '')
        unknown_icon_path = get_resource_path("unknown_icon.png")
        target_icon = game_icon if (game_icon and os.path.exists(game_icon)) else unknown_icon_path

        if audio_only:
            text_part = f"<span style='font-size: 14px;'><b>{game_name} &nbsp;•&nbsp; AUDIO ONLY: {audio_format} {audio_bitrate_clean}</b></span>"
        elif mute_audio:
            text_part = f"<span style='font-size: 14px;'><b>{game_name} &nbsp;•&nbsp; {q_word}, {fps_display} &nbsp;•&nbsp; {video_bitrate_display} &nbsp;•&nbsp; {codec} (Muted)</b></span>"
        else:
            text_part = f"<span style='font-size: 14px;'><b>{game_name} &nbsp;•&nbsp; {q_word}, {fps_display} &nbsp;•&nbsp; {video_bitrate_display} &nbsp;•&nbsp; {codec}</b></span>"
            
        # GIVE ORDER TO OUR NEW CSS WIDGETS
        if hasattr(self, 'bottom_text_label'):
            self.bottom_text_label.setText(text_part)
            icon_css = target_icon.replace('\\', '/')
            self.bottom_icon_label.setStyleSheet(f"image: url('{icon_css}'); background: transparent; border: none;")
            
            # We are updating the TOP panel of the player!
            if hasattr(self, 'custom_text_label') and hasattr(self, 'custom_icon_label'):
                self.custom_icon_label.setStyleSheet(f"image: url('{icon_css}'); background: transparent; border: none;")
                

            # CONNECTING THE MAIN BOSS: Updating the CENTRAL plug!
            if hasattr(self, 'place_logo') and hasattr(self, 'place_text'):
                self.place_logo.setStyleSheet(f"image: url('{icon_css}'); background: transparent; border: none;")
                self.place_text.setText(f"Ready to play: {game_name}") 
                self.place_text.setStyleSheet("color: #a0a0a0; font-size: 15px; font-weight: bold; margin-top: 15px;")
            
        if hasattr(self.ui, 'label_status'):
            self.ui.label_status.setText("Ready")
    
    def validate_custom_fps(self, text):
        """ Validates FPS input and shows warning icon if boundaries are exceeded """
        if not text.strip():
            self.warn_fps.hide()
            self.update_final_setup()
            return
            
        try:
            val = int(text)
            orig_fps = getattr(self, 'current_orig_fps', 60)
            max_allowed = min(60, orig_fps)
            
            if val > max_allowed:
                self.warn_fps.setToolTip(f"The maximum FPS of the original video is {max_allowed} FPS. Higher values will be capped!")
                self.warn_fps.show()
            elif val < 1:
                self.warn_fps.setToolTip("FPS cannot be less than 1.")
                self.warn_fps.show()
            else:
                self.warn_fps.hide()
        except:
            self.warn_fps.hide()
            
        self.update_final_setup() # Live UI update

    def validate_custom_vbitrate(self, text):
        """ Validates video bitrate input and shows warning icon if boundaries are exceeded """
        if not text.strip():
            self.warn_vbitrate.hide()
            self.update_final_setup()
            return
            
        try:
            val = float(text.replace(',', '.'))
            orig_v_bitrate = getattr(self, 'current_orig_bitrate', 10.0)
            
            if val > orig_v_bitrate:
                self.warn_vbitrate.setToolTip(f"The maximum bitrate of the original video is {orig_v_bitrate:.1f} Mbps. Higher values will be capped!")
                self.warn_vbitrate.show()
            elif val < 0.1:
                self.warn_vbitrate.setToolTip("Video bitrate cannot be less than 0.1 Mbps.")
                self.warn_vbitrate.show()
            else:
                self.warn_vbitrate.hide()
        except:
            self.warn_vbitrate.hide()
            
        self.update_final_setup() # Live UI update

    def validate_custom_abitrate(self, text):
        """ Validates audio bitrate input and shows warning icon if boundaries are exceeded """
        if not text.strip():
            self.warn_abitrate.hide()
            self.update_final_setup()
            return
            
        try:
            val = int(text)
            orig_a_bitrate = getattr(self, 'current_orig_audio_bitrate', 192)
            
            if val > orig_a_bitrate:
                self.warn_abitrate.setToolTip(f"The maximum audio bitrate of the original file is {orig_a_bitrate} kbps. Higher values will be capped!")
                self.warn_abitrate.show()
            elif val < 1:
                self.warn_abitrate.setToolTip("Audio bitrate cannot be less than 1 kbps.")
                self.warn_abitrate.show()
            else:
                self.warn_abitrate.hide()
        except:
            self.warn_abitrate.hide()
            
        self.update_final_setup() # Live UI update

    def start_render_thread(self):
        """ Prepares parameters and starts the background rendering thread """
        if getattr(self, '_is_rendering', False):
            return
        
        if not hasattr(self.ui, 'table_clips') or self.ui.table_clips.currentRow() < 0:
            QMessageBox.warning(self.ui, "Error", "Please select a clip from the list first!")
            return
            
        clip_name = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0).data(Qt.UserRole)
        all_mpds = self.get_all_mpd_paths(clip_name)
        
        if not all_mpds:
            QMessageBox.warning(self.ui, "Error", "session.mpd files not found inside this clip!")
            return

        save_dir = self.custom_destination if self.custom_destination else get_save_directory()
        
        # We take the protected file name that we generated in update_final_setup
        output_file = getattr(self, 'current_output_file', "")
        if not output_file: 
            return # Empty Path Protection
            
        ffmpeg_exe = get_resource_path("ffmpeg.exe")
        if not os.path.exists(ffmpeg_exe):
            QMessageBox.critical(self.ui, "Error", "ffmpeg.exe not found!")
            return

        # Read the basic video settings
        quality_text = self.ui.combo_quality.currentText() if hasattr(self.ui, 'combo_quality') else "Original"
        fps_text = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else "60"
        bitrate_text = self.ui.combo_bitrate.currentText() if hasattr(self.ui, 'combo_bitrate') else "Original"
        
        # Get the codec and encoder
        selected_encoder = self.ui.combo_encoder.currentData(Qt.UserRole) if hasattr(self.ui, 'combo_encoder') else "libx264"
        if hasattr(self.ui, 'combo_codec') and "H.265" in self.ui.combo_codec.currentText():
            selected_encoder = selected_encoder.replace("h264", "hevc").replace("libx264", "libx265")

        # Read the audio settings
        audio_only = self.ui.check_audio_only.isChecked() if hasattr(self.ui, 'check_audio_only') else False
        mute_audio = self.ui.check_mute_audio.isChecked() if hasattr(self.ui, 'check_mute_audio') else False
        audio_format = self.ui.combo_audio_format.currentText() if hasattr(self.ui, 'combo_audio_format') else "AAC"

        # --- SMART TRIM EXTRACTION ---
        trim_start_sec = -1.0
        trim_duration_sec = -1.0
        
        if hasattr(self, 'custom_timeline') and self.custom_timeline.is_trim_mode:
            trim_start_sec = self.custom_timeline.trim_start_ms / 1000.0
            trim_duration_sec = (self.custom_timeline.trim_end_ms - self.custom_timeline.trim_start_ms) / 1000.0
            logging.info(f"TRIM MODE ACTIVE: Start at {trim_start_sec}s, Duration: {trim_duration_sec}s")
        
        # --- SMART PARSING & CLAMPING ---
        #1: Read and Protect FPS
        fps_multiplier = 1.0
        orig_fps = getattr(self, 'current_orig_fps', 60)
        max_allowed_fps = min(60, orig_fps) # No higher than 60, no higher than the original!
        
        if "Custom" in fps_text:
            try:
                val = int(self.input_custom_fps.text().strip())
                val = max(1, min(val, max_allowed_fps)) 
                fps_text = f"{val} FPS"
                fps_multiplier = val / orig_fps if orig_fps > 0 else 1.0
            except: fps_text = f"{max_allowed_fps} FPS" # Foolproof protection
        else:
            try:
                selected_fps = int(re.search(r'(\d+)', fps_text).group(1))
                fps_multiplier = selected_fps / orig_fps if orig_fps > 0 else 1.0
            except: pass

        #2: Read and Protect Video Bitrate
        video_bitrate = "12M"
        orig_v_bitrate = getattr(self, 'current_orig_bitrate', 10.0)
        target_scale_h = -1 

        if "Target File Size" in quality_text:
            video_bitrate = f"{getattr(self, 'custom_target_bitrate', 1500)}k"
            target_scale_h = getattr(self, 'custom_target_height', -1)
        elif "Custom" in bitrate_text:
            try:
                val_text = self.input_custom_vbitrate.text().replace(',', '.')
                val = float(val_text.strip())
                val = max(0.1, min(val, orig_v_bitrate)) 
                final_bitrate = int(val * fps_multiplier * 1000)
                if final_bitrate < 100: final_bitrate = 100
                video_bitrate = f"{final_bitrate}k"
            except: 
                final_bitrate = int(orig_v_bitrate * fps_multiplier * 1000)
                if final_bitrate < 100: final_bitrate = 100
                video_bitrate = f"{final_bitrate}k"
        elif "Original" not in bitrate_text:
            match = re.search(r'-\s*([\d.]+)\s*Mbps', bitrate_text)
            if match:
                base_bitrate = float(match.group(1))
                final_bitrate = int(base_bitrate * 1000)
                if final_bitrate < 100: final_bitrate = 100 
                video_bitrate = f"{final_bitrate}k"

        #3: Read and Protect Audio Bitrate
        audio_bitrate_kbps = "192k"
        orig_a_bitrate = getattr(self, 'current_orig_audio_bitrate', 192)
        
        if "Custom" in self.ui.combo_audio_bitrate.currentText():
            try:
                val = int(self.input_custom_abitrate.text().strip())
                val = max(1, min(val, orig_a_bitrate))
                audio_bitrate_kbps = f"{val}k"
            except: audio_bitrate_kbps = f"{orig_a_bitrate}k"
        elif self.ui.combo_audio_bitrate.currentText():
            audio_bitrate_kbps = self.ui.combo_audio_bitrate.currentText().split(' ')[0] + "k"

        # Turn interface buttons on/off
        self.ui.btn_start.setEnabled(False) 
        if hasattr(self.ui, 'btn_cancel'): self.ui.btn_cancel.setEnabled(True)
        if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setEnabled(True) 

        self.set_status("Initializing...")
        logging.info(f"--- RENDER STARTED ---")

        # --- LOCK THE RENDER ENGINE ---
        self._is_rendering = True

        logging.info(f"Source: {clip_name}")
        logging.info(f"Saving in: {output_file}")
        logging.info(f"Settings: Quality={quality_text}, FPS={fps_text}, Bitrate={video_bitrate}, Codec={selected_encoder}, AudioOnly={audio_only}, Muted={mute_audio}")

        try:
            self.thread = RenderThread(all_mpds, quality_text, output_file, ffmpeg_exe, save_dir, selected_encoder, video_bitrate, fps_text, audio_only, mute_audio, audio_format, audio_bitrate_kbps, target_scale_h, trim_start_sec, trim_duration_sec)
            self.thread.progress_signal.connect(self.set_status)
            self.thread.finished_signal.connect(self.on_render_finished)
            self.thread.start()
        except Exception as e:
            logging.error(f"Thread Start Error: {e}")
            self.set_status("Error!")
            self.ui.btn_start.setEnabled(True)
            if hasattr(self.ui, 'btn_cancel'): self.ui.btn_cancel.setEnabled(False)
            if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setEnabled(False)
            QMessageBox.critical(self.ui, "Thread Error", f"Could not start render:\n{e}")
    def clear_clip_state(self):
        """ Clears the interface when the clip is closed by clicking the X """
        
        self.ui.lbl_top_info.setText("Clip not chosen") 
        
        self.ui.lbl_source_resolution.setText("-")
        self.ui.lbl_source_fps.setText("-")
        self.ui.lbl_source_duration.setText("-")

      
        if hasattr(self, 'player'):
            self.player.command("stop")
        if hasattr(self, 'video_wrapper'):
            self.video_wrapper.layout().setCurrentIndex(1) 
        self.ui.btn_start.setEnabled(False)
        self.ui.btn_start.setText("Choose clip for render")

        if hasattr(self.ui, 'label_time'):
            self.ui.label_time.setText("00:00 / 00:00")
            
        if hasattr(self.ui, 'btn_play'):
            self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_play.png")))
            
        # 1. Clear the Source Info tab to dashes.
        if hasattr(self.ui, 'source_label'): self.ui.source_label.setText("Source: -")
        if hasattr(self.ui, 'orig_res_label'): self.ui.orig_res_label.setText("Original resolution: -")
        if hasattr(self.ui, 'label_vbitrate'): self.ui.label_vbitrate.setText("Video Bitrate: -")
        if hasattr(self.ui, 'label_abitrate'): self.ui.label_abitrate.setText("Audio Bitrate: -")
        if hasattr(self.ui, 'label_size'): self.ui.label_size.setText("Size: -")
        if hasattr(self.ui, 'label_duration'): self.ui.label_duration.setText("Time: -")
        if hasattr(self.ui, 'label_fps'): self.ui.label_fps.setText("FPS: -")

       # 2. Hiding the small path-copying icons
        if hasattr(self, 'btn_copy_src'): self.btn_copy_src.hide()
        if hasattr(self, 'btn_copy_loc'): self.btn_copy_loc.hide()

        # 3. Safely clearing dropdown lists (blocking signals to avoid crashing Python)
        def clear_combo(combo_name):
            if hasattr(self.ui, combo_name):
                widget = getattr(self.ui, combo_name)
                widget.blockSignals(True)
                widget.clear()
                widget.blockSignals(False)

        clear_combo('combo_quality')
        clear_combo('combo_fps')
        clear_combo('combo_bitrate')
        clear_combo('combo_audio_bitrate')

        # Hide the custom size slider (if it was open)
        if hasattr(self.ui, 'size_slider'): self.ui.size_slider.hide()
        if hasattr(self, 'size_container'): self.size_container.hide()

        #4. Clear the Export Settings and delete the filename.
        if hasattr(self.ui, 'input_filename'):
            self.ui.input_filename.blockSignals(True)
            self.ui.input_filename.clear()
            self.ui.input_filename.blockSignals(False)
            
        if hasattr(self.ui, 'label_short_summary'):
            if hasattr(self, 'reset_bottom_summary'): self.reset_bottom_summary()
        if hasattr(self.ui, 'label_detailed_summary'):
            self.ui.label_detailed_summary.setText("Waiting for clip selection...")
        if hasattr(self.ui, 'label_location'):
            self.ui.label_location.setText("Output: -")
            
        # 5. Hard-Block the Render Button
        if hasattr(self.ui, 'btn_start'):
            self.ui.btn_start.setEnabled(False)
    def on_quality_mode_changed(self, text):
        """ Hides or shows the slider and target inputs depending on the mode """
        is_target_mode = "Target File Size" in text
        
        if hasattr(self.ui, 'size_slider'):
            self.ui.size_slider.setVisible(is_target_mode)
            
        if hasattr(self, 'size_container'):
            self.size_container.setVisible(is_target_mode)
            
        if is_target_mode:
            self.setup_dynamic_slider()

    def get_effective_duration(self):
        """ Calculates the real duration of the video. If Trim is active, returns only the trimmed part! """
        if hasattr(self, 'custom_timeline') and self.custom_timeline.is_trim_mode:
            # Return duration of the yellow bar
            return max(0.1, (self.custom_timeline.trim_end_ms - self.custom_timeline.trim_start_ms) / 1000.0)
        return getattr(self, 'current_clip_duration_sec', 0)

    def on_trim_changed(self, start_ms, end_ms):
        """ Fires instantly when the user drags the yellow trim handles """
        # 1. Update text info in Export Settings
        self.update_final_setup()
        
        # 2. Recalculate slider sizes because shorter video = less Megabytes!
        if hasattr(self.ui, 'combo_quality') and "Target File Size" in self.ui.combo_quality.currentText():
            self.setup_dynamic_slider()
            
    def on_custom_size_changed(self, text):
        """ Live updates when typing a custom MB value with idiot-proof protection """
        if not text.strip():
            self.warn_size.hide()
            return
            
        try:
            target_mb = int(text)
            
            # --- Use EFFECTIVE duration for correct calculation! ---
            duration = self.get_effective_duration()
            orig_bitrate = getattr(self, 'current_orig_bitrate', 10)
            orig_mb = int((orig_bitrate * duration) / 8)
            if orig_mb < 1: orig_mb = 1
            
            # Idiot-proof protection lol
            if target_mb < 1:
                self.warn_size.setToolTip("Oops! Minimum size is 1 MB, otherwise the video will turn to dust")
                self.warn_size.show()
            elif target_mb > orig_mb:
                self.warn_size.setToolTip(f"No need to inflate the file! Maximum for this clip: {orig_mb} MB.\n The program will automatically cap the value to this limit.")
                self.warn_size.show()
            else:
                self.warn_size.hide()
                
            self.calculate_strict_target(target_mb, is_custom=True)
        except: 
            self.warn_size.hide()

    def setup_dynamic_slider(self):
        """ Generates strict slider steps and adds Lossless & Custom modes """
        duration = self.get_effective_duration() 
        if duration <= 0: return
            
        # Dynamically calculate the maximum MB for the current trimmed duration
        orig_mb = (getattr(self, 'current_orig_bitrate', 10) * duration) / 8 
        if orig_mb < 1: orig_mb = 1
        
        anchors = [10, 25, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, 4000, 5000]
        self.dynamic_stops = [size for size in anchors if size < orig_mb]
        
        self.dynamic_stops.append(int(orig_mb)) # Lossless
        self.dynamic_stops.append(-1) # Custom
        
        self.ui.size_slider.blockSignals(True)
        self.ui.size_slider.setMinimum(0)
        self.ui.size_slider.setMaximum(len(self.dynamic_stops) - 1)
        # Always snap to the new Lossless value when the trim changes
        self.ui.size_slider.setValue(len(self.dynamic_stops) - 2) 
        self.ui.size_slider.blockSignals(False)
        
        self.on_slider_moved(self.ui.size_slider.value())

    def calculate_strict_target(self, target_mb, is_lossless=False, is_custom=False):
        """Read the controls, run the bitrate math, show the result."""
        duration = self.get_effective_duration()

        # --- read inputs from the UI ---
        orig_video_mbps = getattr(self, 'current_orig_bitrate', 10)

        audio_text = self.ui.combo_audio_bitrate.currentText() if hasattr(self.ui, 'combo_audio_bitrate') else "192 kbps"
        if hasattr(self.ui, 'check_mute_audio') and self.ui.check_mute_audio.isChecked():
            audio_kbps = 0
        elif "Custom" in audio_text and hasattr(self, 'input_custom_abitrate'):
            try:
                audio_kbps = int(self.input_custom_abitrate.text())
            except ValueError:
                audio_kbps = getattr(self, 'current_orig_audio_bitrate', 192)
        else:
            match = re.search(r'(\d+)', audio_text)
            audio_kbps = int(match.group(1)) if match else 192

        fps_text = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else "60"
        if "Custom" in fps_text and hasattr(self, 'input_custom_fps'):
            try:
                fps = int(self.input_custom_fps.text())
            except ValueError:
                fps = getattr(self, 'current_orig_fps', 60)
        else:
            try:
                fps = int(re.search(r'(\d+)', fps_text).group(1))
            except (AttributeError, ValueError):
                fps = getattr(self, 'current_orig_fps', 60)

        # --- run the pure math ---
        plan = bitrate.plan_bitrate(duration, orig_video_mbps, target_mb, audio_kbps, fps,
                                    is_lossless=is_lossless, is_custom=is_custom)
        if plan is None:
            return

        # --- show the result ---
        self.custom_target_height = plan.height
        self.custom_target_bitrate = plan.video_kbps
        custom_tag = "⚙️ Custom " if is_custom else ""
        self.ui.label_target_size.setText(
            f"Target: <b>{custom_tag}{plan.target_mb} MB</b> | Safe Bitrate: {plan.video_kbps} kbps<br>"
            f"Quality: <span style='color:{plan.color}'><b>{plan.label}</b></span>"
        )
        self.update_final_setup()

    def on_slider_moved(self, index):
        """ Handles slider logic and reveals custom input if needed """
        target_mb = self.dynamic_stops[index]
        
        if target_mb == -1:
            self.input_custom_size.show()
            if self.input_custom_size.text():
                self.on_custom_size_changed(self.input_custom_size.text())
            else:
                self.ui.label_target_size.setText("Target: <b>--- MB</b> (Type specific size)<br>Quality: <span style='color:#aaaaaa'><b>Waiting for input...</b></span>")
        else:
            self.input_custom_size.hide()
            if hasattr(self, 'warn_size'): self.warn_size.hide() 
            self.calculate_strict_target(target_mb, is_lossless=(index == len(self.dynamic_stops) - 2))


    def cancel_render(self):
        """ Cancel Button Handler """
        logging.warning("User cancelled rendering (Cancel)")
        if hasattr(self, 'thread') and self.thread.isRunning():
            self.set_status("Cancelling... Please wait")
            if hasattr(self.ui, 'btn_cancel'): self.ui.btn_cancel.setEnabled(False)
            if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setEnabled(False)
            self.thread.cancel() # Send a cancel signal to the thread

    def toggle_pause(self):
        """ Pause button handler """
        logging.info("User Paused/Resumed rendering")
        if hasattr(self, 'thread') and self.thread.isRunning():
            is_paused = self.thread.toggle_pause() # Send a pause signal to the thread
            
            # Change the button text depending on the status
            if is_paused:
                if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setText("Resume")
                self.set_status("Paused...")
            else:
                if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setText("Pause")
                self.set_status("Process...")

    def on_render_finished(self, success, error_msg, output_file):
        """ Fires when the background rendering thread exits. """
        self._is_rendering = False
        
        # Unlocking the UI
        if hasattr(self.ui, 'btn_start'): self.ui.btn_start.setEnabled(True)
        if hasattr(self.ui, 'btn_cancel'): self.ui.btn_cancel.setEnabled(False)
        if hasattr(self.ui, 'btn_pause'): 
            self.ui.btn_pause.setEnabled(False)
            self.ui.btn_pause.setText("Pause")
            
        self.update_final_setup()
        
        # Show the result to the user
        if success:
            logging.info("=== RENDER SUCCESS ===")
            
            # 1. Set to 100% before the window appears
            if hasattr(self.ui, 'progress_render'):
                self.ui.progress_render.setValue(100)
                self.ui.progress_render.setFormat("100%")
            if hasattr(self.ui, 'label_status'):
                self.ui.label_status.setText("Success!")
            
            # A CUSTOM SUCCESS WINDOW
            msg_box = QMessageBox(self.ui)
            msg_box.setWindowTitle("Success!")
            msg_box.setText(f"Clip successfully saved to:\n{output_file}")
            msg_box.setIcon(QMessageBox.Information)
            
            btn_folder = msg_box.addButton("Open Folder", QMessageBox.ActionRole)
            btn_play = msg_box.addButton("Play Video", QMessageBox.ActionRole)
            btn_ok = msg_box.addButton(QMessageBox.Ok)
            
            # The code pauses here. The user sees 100% in the background and a window.
            msg_box.exec()
            
            # Handling User Selection
            if msg_box.clickedButton() == btn_folder:
                self.open_rendered_folder(output_file)
                
            elif msg_box.clickedButton() == btn_play:
                import os
                file_path = os.path.abspath(output_file)
                os.startfile(file_path)

            # 2. RESET PROGRESS ONLY AFTER CLOSING THE WINDOW
            if hasattr(self.ui, 'label_status'):
                self.ui.label_status.setText("Ready")
            if hasattr(self.ui, 'progress_render'):
                self.ui.progress_render.setValue(0)
                self.ui.progress_render.setFormat("0%")
                
        elif "cancelled by user" in error_msg.lower():
            logging.warning("=== RENDER CANCELED ===")
            if hasattr(self.ui, 'label_status'): self.ui.label_status.setText("Cancelled")
            QMessageBox.information(self.ui, "Cancelled", "Render was cancelled.")
            
            # Reset to Ready after closing the cancellation window
            if hasattr(self.ui, 'label_status'): self.ui.label_status.setText("Ready")
            if hasattr(self.ui, 'progress_render'):
                self.ui.progress_render.setValue(0)
                self.ui.progress_render.setFormat("0%")
            
        else:
            import os
            logging.error(f"=== RENDER ERROR === \n{error_msg}")
            if hasattr(self.ui, 'label_status'): self.ui.label_status.setText("Error!") 
            
            # --- STEEMPEG CUSTOM ERROR WINDOW ---
            from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton

            from PySide6.QtGui import QPixmap

            dialog = QDialog(self.ui)
            dialog.setWindowFlag(Qt.WindowType.FramelessWindowHint)
            # Make the window wider so that the image and logs fit comfortably.
            dialog.setFixedSize(780, 420)
            
            dialog.setStyleSheet("""
                QDialog { 
                    background-color: #202020; 
                    border: 1px solid #444444; 
                    border-radius: 8px; 
                }
                QLabel#ErrorTitle { 
                    color: #ff4444; 
                    font-size: 18px; 
                    font-weight: bold; 
                }
                QLabel#ErrorDesc { 
                    color: #cccccc; 
                    font-size: 13px; 
                }
                QTextEdit { 
                    background-color: #141414; 
                    color: #ff8888; 
                    border: 1px solid #333333; 
                    border-radius: 6px; 
                    padding: 8px; 
                    font-family: Consolas, monospace; 
                    font-size: 11px; 
                }
                
                QScrollBar:vertical { border: none; background: #141414; width: 12px; margin: 2px; border-radius: 4px; }
                QScrollBar::handle:vertical { background: #444444; min-height: 20px; border-radius: 4px; }
                QScrollBar::handle:vertical:hover { background: #666666; }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
                
                QPushButton { 
                    background-color: #333333; 
                    color: white; 
                    border: 1px solid #555555; 
                    border-radius: 16px; 
                    padding: 6px 20px; 
                    font-weight: bold; 
                    font-size: 12px; 
                    min-height: 32px;
                    outline: none;
                }
                QPushButton:hover { 
                    background-color: #444444; 
                    border: 1px solid #777777; 
                }
                QPushButton:pressed {
                    background-color: #222222;
                }
                
                QPushButton#LogBtn { 
                    background-color: #4a2525; 
                    border: 1px solid #7a3535; 
                }
                QPushButton#LogBtn:hover { 
                    background-color: #6a2e2e; 
                    border: 1px solid #9a4545; 
                }
            """)
            
            # --- MAIN LAYER (Horizontal) ---
            main_layout = QHBoxLayout(dialog)
            main_layout.setContentsMargins(20, 20, 20, 20)
            main_layout.setSpacing(20)

            # --- LEFT SIDE: Sad Image ---
            pic_label = QLabel()
            pixmap = QPixmap(get_resource_path("saderror.png"))
            
            if not pixmap.isNull():
                # Shrinking a huge image to 240 pixels in width with beautiful anti-aliasing
                scaled_pixmap = pixmap.scaledToWidth(240, Qt.TransformationMode.SmoothTransformation)
                pic_label.setPixmap(scaled_pixmap)
            else:
                pic_label.setText("Sad pic\nnot found =(")
                pic_label.setStyleSheet("color: gray; font-size: 12px;")
                
            pic_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
            main_layout.addWidget(pic_label)

            # --- RIGHT SIDE: Text, Logs, and Buttons ---
            content_layout = QVBoxLayout()
            content_layout.setSpacing(15)

            # 1. HEADER (without the crooked icon—text only)
            title_layout = QVBoxLayout()
            title_layout.setSpacing(2)

            title_lbl = QLabel("Render Failed")
            title_lbl.setObjectName("ErrorTitle")
            desc_lbl = QLabel("FFmpeg encountered a critical error during processing.")
            desc_lbl.setObjectName("ErrorDesc")
            
            title_layout.addWidget(title_lbl)
            title_layout.addWidget(desc_lbl)
            content_layout.addLayout(title_layout)

            # 2. LOGS FIELD
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            short_error = error_msg[-2000:] if len(error_msg) > 2000 else error_msg
            text_edit.setText(short_error)
            content_layout.addWidget(text_edit)

            # 3. Control Buttons
            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            
            btn_log = QPushButton("📄 Open Log File")
            btn_log.setObjectName("LogBtn")
            btn_log.setCursor(Qt.CursorShape.PointingHandCursor)
            
            btn_ok = QPushButton("Close")
            btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
            
            btn_layout.addWidget(btn_log)
            btn_layout.addWidget(btn_ok)
            
            content_layout.addLayout(btn_layout)
            
           # Bringing Everything Together in the Main Window
            main_layout.addLayout(content_layout)
            
            def open_log_and_close():
                import subprocess
                import os
                if hasattr(self, 'current_log_file') and os.path.exists(self.current_log_file):
                    log_path = os.path.abspath(self.current_log_file)
                    subprocess.Popen(["notepad.exe", log_path])
                dialog.accept()
                
            btn_log.clicked.connect(open_log_and_close)
            btn_ok.clicked.connect(dialog.accept)

            dialog.exec()
            
            # --- RESTORING THE INTERFACE TO NORMAL ---
            if hasattr(self.ui, 'label_status'): self.ui.label_status.setText("Ready")
            if hasattr(self.ui, 'progress_render'):
                self.ui.progress_render.setValue(0)
                self.ui.progress_render.setFormat("0%")
    def open_rendered_folder(self, file_path):
        """ Opens Windows Explorer and automatically highlights the rendered file! """
        import subprocess
        import os
        
        try:
            if os.path.exists(file_path):
                # Magic Windows command to open folder AND select the specific file
                subprocess.run(['explorer', '/select,', os.path.normpath(file_path)])
            else:
                # Fallback: Just open the directory if the file is somehow missing
                folder_dir = os.path.dirname(file_path)
                if folder_dir and os.path.exists(folder_dir):
                    os.startfile(folder_dir)
        except Exception as e:
            print(f"Failed to open folder: {e}")

    

# BACKGROUND RENDER THREAD (PROTECTS UI FROM FREEZING)
class RenderThread(QThread):
    progress_signal = Signal(str)  
    finished_signal = Signal(bool, str, str) 

    def __init__(self, mpd_paths, quality_text, output_file, ffmpeg_exe, save_dir, selected_encoder, video_bitrate, fps_text, audio_only, mute_audio, audio_format, audio_bitrate_kbps, target_scale_h=-1, trim_start_sec=-1.0, trim_duration_sec=-1.0):
        super().__init__()
        self.target_scale_h = target_scale_h 
        self.trim_start_sec = trim_start_sec
        self.trim_duration_sec = trim_duration_sec
        self.mpd_paths = mpd_paths
        self.quality_text = quality_text
        self.output_file = output_file 
        self.ffmpeg_exe = ffmpeg_exe
        self.save_dir = save_dir
        
        self.selected_encoder = selected_encoder
        self.video_bitrate = video_bitrate
        self.fps_text = fps_text
        
        self.audio_only = audio_only
        self.mute_audio = mute_audio
        self.audio_format = audio_format
        self.audio_bitrate_kbps = audio_bitrate_kbps
        
        self.target_scale_h = target_scale_h
        
        self.is_cancelled = False
        self.is_paused = False
        self.current_process = None

    def cancel(self):
        """ Force kills the FFmpeg process. """
        self.is_cancelled = True
        if self.current_process:
            try:
                subprocess.call(['taskkill', '/F', '/T', '/PID', str(self.current_process.pid)])
            except: pass

    def toggle_pause(self):
        """ Pauses or resumes FFmpeg at the OS level. """
        if not self.current_process:
            return False
            
        self.is_paused = not self.is_paused
        try:
            p = psutil.Process(self.current_process.pid)
            if self.is_paused: p.suspend()
            else: p.resume() 
        except:
            self.is_paused = not self.is_paused
            
        return self.is_paused

    def run(self):
        """ Main thread loop """
        temp_files = []
        concat_file = None
        try:
            creation_flags = 0x08000000 if sys.platform == "win32" else 0
            # Get the target extension (.mp4, .mp3, .aac) from the final output file
            _, ext = os.path.splitext(self.output_file)
            
            # STEP 1: Render each .mpd part
            for idx, mpd in enumerate(self.mpd_paths):
                if self.is_cancelled:
                    raise Exception("Render cancelled by user.")
                    
                # Use the correct extension for temporary files
                temp_mp4 = os.path.join(self.save_dir, f"temp_steempeg_part_{idx}{ext}")
                temp_files.append(temp_mp4)
                
                self.progress_signal.emit(f"Part {idx+1}/{len(self.mpd_paths)}.. (0%)")
                
                # Fix paths for FFmpeg (replace backslashes with forward slashes)
                safe_mpd = mpd.replace('\\', '/')

                fps_arg = ""
                if hasattr(self, 'fps_text') and "Original" not in self.fps_text:
                    match_fps = re.search(r'(\d+)', self.fps_text)
                    if match_fps:
                        fps_arg = f"-r {match_fps.group(1)} "
                

                
                
                # --- FFMPEG COMMAND GENERATION ---
                
                # 0. Inject Trim Arguments BEFORE the input for maximum seeking speed!
                trim_args = ""
                if self.trim_start_sec >= 0 and self.trim_duration_sec > 0:
                    trim_args = f"-ss {self.trim_start_sec:.3f} -t {self.trim_duration_sec:.3f} "
                
                # 1. Prepare the audio arguments
                if self.mute_audio:
                    base_audio = "-an" 
                else:
                    a_codec = "libmp3lame" if self.audio_format == "MP3" else "aac"
                    base_audio = f"-c:a {a_codec} -b:a {self.audio_bitrate_kbps}"

                # 2. Construct the final command based on video settings
                if self.audio_only:
                    cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" -vn {base_audio} -y "{temp_mp4}"'
                    
                elif "Original" in self.quality_text and "Target File" not in self.quality_text:
                    if self.mute_audio:
                        cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" {fps_arg}-c:v copy -an -y "{temp_mp4}"'
                    else:
                        cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" {fps_arg}-c copy -y "{temp_mp4}"'
                        
                elif "Target File Size" in self.quality_text:
                    bitrate_val = int(self.video_bitrate.replace('k', ''))
                    bufsize = f"{bitrate_val * 2}k" 
                    
                    if self.target_scale_h > 0:
                        scale_filter = f"scale=-2:min(ih\\,{self.target_scale_h})"
                    else:
                        scale_filter = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
                    
                    cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" -vf "{scale_filter}" {fps_arg}-c:v {self.selected_encoder} -b:v {self.video_bitrate} -maxrate {self.video_bitrate} -bufsize {bufsize} {base_audio} -y "{temp_mp4}"'
                    
                else:
                    match = re.search(r'^(\d+)p', self.quality_text)
                    if match:
                        target_height = match.group(1)
                        cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" -vf scale=-2:{target_height} {fps_arg}-c:v {self.selected_encoder} -b:v {self.video_bitrate} {base_audio} -y "{temp_mp4}"'
                    else:
                        cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" {fps_arg}-c copy -y "{temp_mp4}"'

                logging.debug(f"FFmpeg cmd for part {idx}: {cmd}")

                # Launch FFmpeg
                self.current_process = subprocess.Popen( 
                    cmd, shell=False, cwd=os.path.dirname(mpd),
                    creationflags=creation_flags, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, universal_newlines=True, encoding='utf-8', errors='ignore'
                )

                total_duration = 0
                last_ffmpeg_output = []

                # Read FFmpeg logs in real time
                for line in self.current_process.stdout:
                    if self.is_cancelled:
                        break
                        
                    clean_line = line.strip()
                    if clean_line:
                        # Collect the last 5 lines of logs for output in case of an error
                        logging.debug(f"[FFmpeg] {clean_line}")
                        last_ffmpeg_output.append(clean_line)
                        if len(last_ffmpeg_output) > 5:
                            last_ffmpeg_output.pop(0)
                            
                    # Parse the total duration of the video
                    if total_duration == 0:
                        dur_match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d+)", line)
                        if dur_match:
                            h, m, s = float(dur_match.group(1)), float(dur_match.group(2)), float(dur_match.group(3))
                            total_duration = h * 3600 + m * 60 + s

                    # Parse the current render time to calculate percentages
                    time_match = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d+)", line)
                    if time_match and total_duration > 0:
                        h, m, s = float(time_match.group(1)), float(time_match.group(2)), float(time_match.group(3))
                        current_time = h * 3600 + m * 60 + s
                        
                        # Calculating tenths of a unit for perfect smoothness!
                        percent = (current_time / total_duration) * 100.0
                        self.progress_signal.emit(f"Part {idx+1}/{len(self.mpd_paths)}.. ({min(percent, 100.0):.1f}%)")

                self.current_process.wait()
                
                # If this was an ultra-fast copy (Original), manually set to 100%.
                self.progress_signal.emit(f"Part {idx+1}/{len(self.mpd_paths)}.. (100%)")
                
                # Post-process checks
                if self.is_cancelled:
                    raise Exception("Render cancelled by user.")
                    
                if self.current_process.returncode != 0:
                    error_details = "\n".join(last_ffmpeg_output)

                    logging.error(f"FFmpeg ERROR in part {idx}:\n{error_details}")


                    raise Exception(f"Failed to render part {idx+1}.\nFFmpeg error:\n{error_details}")

            # Final check before gluing
            if self.is_cancelled:
                raise Exception("Render cancelled by user.")

            # --- FIX FOR 0 BYTES (BYPASS CONCAT FOR SINGLE FILES) ---
            # STAGE 2: Merging all rendered parts into one file
            if len(temp_files) == 1:
                # 99% of cases: No need to use the buggy 'concat' demuxer for a single file!
                self.progress_signal.emit("Finalizing...")
                import shutil
                
                # Directly move/rename the perfectly rendered temp file to the final destination!
                if os.path.exists(self.output_file):
                    os.remove(self.output_file)
                shutil.move(temp_files[0], self.output_file)
                
                self.finished_signal.emit(True, "", self.output_file)
            else:
                self.progress_signal.emit("Merging all parts...")
                concat_file = os.path.join(self.save_dir, "temp_concat_list.txt")
                
                # Create a text file with a list of chunks for FFmpeg
                with open(concat_file, "w", encoding="utf-8") as f:
                    for tmp in temp_files:
                        safe_path = tmp.replace('\\', '/')
                        f.write(f"file '{safe_path}'\n")

                # Run the merge without compression (-c copy)
                self.current_process = subprocess.Popen(
                    f'"{self.ffmpeg_exe}" -f concat -safe 0 -i "{concat_file}" -c copy -y "{self.output_file}"', 
                    shell=False, cwd=self.save_dir,
                    creationflags=creation_flags, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                self.current_process.wait()

                if self.is_cancelled:
                    raise Exception("Render cancelled by user.")

                if self.current_process.returncode == 0:
                    self.finished_signal.emit(True, "", self.output_file) # success
                else:
                    self.finished_signal.emit(False, "Merge failed.", "")

        except Exception as e:
            self.finished_signal.emit(False, str(e), "") # error
            
        finally:
            # STEP 3: CLEANING. Remove all temporary debris
            if concat_file and os.path.exists(concat_file):
                try: os.remove(concat_file)
                except: pass
            for tmp in temp_files:
                if os.path.exists(tmp):
                    try: os.remove(tmp)
                    except: pass

# BACKGROUND DOWNLOAD THREAD FOR UPDATER
class UpdateDownloadThread(QThread):
    progress_signal = Signal(int, str)
    finished_signal = Signal(bool, str, str)

    def __init__(self, url, save_dir, asset_name):
        super().__init__()
        self.url = url
        self.save_dir = save_dir
        self.asset_name = asset_name
        self.is_cancelled = False
        # Download the file with the .tmp appendix to avoid breaking anything
        self.dest_path = os.path.join(save_dir, f"{asset_name}.tmp")


    def cancel(self):
        self.is_cancelled = True

    def run(self):
        import requests
        import time
        try:
            response = requests.get(self.url, stream=True, timeout=10)
            response.raise_for_status()
            total_size = int(response.headers.get('content-length', 0))
            
            downloaded = 0
            start_time = time.time()
            
            with open(self.dest_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if self.is_cancelled: break
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if total_size > 0:
                            percent = int((downloaded / total_size) * 100)
                            
                            # Counting megabytes and speed
                            elapsed = time.time() - start_time
                            speed_mbps = (downloaded / 1024 / 1024) / elapsed if elapsed > 0 else 0
                            down_mb = downloaded / 1024 / 1024
                            total_mb = total_size / 1024 / 1024
                            
                            label_text = f"Downloading update...\n{down_mb:.1f} MB / {total_mb:.1f} MB ({speed_mbps:.1f} MB/s)"
                            
                            # TO UI
                            self.progress_signal.emit(percent, label_text)
                            
            if self.is_cancelled:
                if os.path.exists(self.dest_path): os.remove(self.dest_path)
                self.finished_signal.emit(False, "", "")
            else:
                # Pass the path n the original name (for example.. smpeg11.exe)
                self.finished_signal.emit(True, self.dest_path, self.asset_name)
        except Exception as e:
            self.finished_signal.emit(False, str(e), "")



import os
import PySide6.QtWidgets as qtw
import PySide6.QtCore as qtc
import PySide6.QtGui as qtg

class ClipCard(qtw.QWidget):
    def __init__(self, title, date_str, badge_text, thumb_path, icon_path, row_idx, parent=None):
        super().__init__(parent)
        self.row_idx = row_idx
        
        # Cell 260, border 3px. That means the inside is exactly 254 by 184!
        self.setFixedSize(254, 184) 
        self.setStyleSheet("QWidget { background: transparent; }")

        layout = qtw.QVBoxLayout(self)
        # Remove the fucking joystick, the picture will stick to the frame itself!
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. --- THUMBNAIL AREA ---
        self.thumb_label = qtw.QLabel(self)
        self.thumb_label.setFixedSize(254, 144) 
        self.thumb_label.setStyleSheet("background-color: #1a1a1a; border-radius: 0px;")
        
        # Remove the old setScaledContents(True) and implement a nice, smooth downscale:
        if thumb_path and os.path.exists(thumb_path):
            pixmap = qtg.QPixmap(thumb_path)
            if not pixmap.isNull():
                # Scaling an image while preserving aspect ratio and applying smoothing
                scaled_thumb = pixmap.scaled(
                    254, 144, 
                    qtc.Qt.KeepAspectRatioByExpanding, 
                    qtc.Qt.SmoothTransformation
                )
                self.thumb_label.setPixmap(scaled_thumb)

        # 2. --- GAME LOGO (OVERLAY) ---
        self.icon_label = qtw.QLabel(self.thumb_label)
        self.icon_label.setFixedSize(24, 24)
        self.icon_label.move(8, 8)
        if icon_path and os.path.exists(icon_path):
            self.icon_label.setPixmap(qtg.QPixmap(icon_path).scaled(24, 24, qtc.Qt.KeepAspectRatio, qtc.Qt.SmoothTransformation))

        # 3. --- BADGE (OVERLAY) ---
        self.badge_label = qtw.QLabel(badge_text, self.thumb_label)
        self.badge_label.setStyleSheet("background-color: #b29ae7; color: black; font-weight: bold; font-size: 11px; border-radius: 4px; padding: 2px 6px;")
        self.badge_label.adjustSize()
        badge_w = self.badge_label.width()
        # Move the badge to the new size
        self.badge_label.move(254 - badge_w - 6, 144 - 24)

        # 4. --- TEXT AREA (BOTTOM OF CARD) ---
        text_widget = qtw.QWidget()
        # Outer border radius of 12px, minus our padding of 3px = Perfect inner radius of 9px!
        text_widget.setStyleSheet("""
            QWidget { 
                background-color: #383838; 
                border: none; 
                border-top-left-radius: 0px; 
                border-top-right-radius: 0px; 
                border-bottom-left-radius: 9px; 
                border-bottom-right-radius: 9px; 
            }
        """)

        text_layout = qtw.QHBoxLayout(text_widget)
        text_layout.setContentsMargins(12, 0, 12, 0)

        title_lbl = qtw.QLabel(title)
        title_lbl.setStyleSheet("QLabel { color: #e0e0e0; font-weight: bold; font-size: 13px; background: transparent; border: none; }")

        date_lbl = qtw.QLabel(date_str)
        date_lbl.setStyleSheet("QLabel { color: #888888; font-size: 11px; background: transparent; border: none; }")

        text_layout.addWidget(title_lbl)
        text_layout.addStretch()
        text_layout.addWidget(date_lbl)

        layout.addWidget(self.thumb_label)
        layout.addWidget(text_widget)
# --- BACKGROUND WORKER: JIT THUMBNAIL SNIPER ---
import hashlib
import tempfile
import shutil
import subprocess
import os
import glob
from PySide6.QtCore import QThread, Signal

# --- SMART PREVIEW SNIPER 5.0 (RADAR RADIAL PRELOADER) ---
import os
import io
import re
import time
import av
import xml.etree.ElementTree as ET
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage, QPixmap

class PreviewSniperWorker(QThread):
    preview_ready = Signal(int, QPixmap)

    def __init__(self):
        super().__init__()
        self.video_path = "" 
        self.target_sec = -1
        self.cache = {}
        self.interval = 3 
        
        # Flag for thread termination
        self._is_killed = False
        
        # --- Manifest variables ---
        self.base_dir = ""
        self.init_filename = ""
        self.chunk_template = ""
        self.chunk_duration_sec = 3.0
        self.start_number = 1
        self.rep_id = "1"
        
        # --- RADAR (Radial Loader) ---
        self.bg_anchor = 0     
        self.bg_radius = 3      
        self.bg_left_done = False 
        self.bg_right_done = False 
        self.bg_side = "right" 

    def kill_worker(self):
        """ Abrupt stream termination during clip switching """
        self._is_killed = True
        self.cache.clear()

    def parse_mpd(self, mpd_path):
        self.base_dir = os.path.dirname(mpd_path)
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(mpd_path)
            root = tree.getroot()
            
            for elem in root.iter():
                if 'Representation' in elem.tag:
                    mime = elem.attrib.get('mimeType', '')
                    if 'video' in mime or not self.rep_id:
                        self.rep_id = elem.attrib.get('id', '1')
            
            for elem in root.iter():
                if 'SegmentTemplate' in elem.tag:
                    self.init_filename = elem.attrib.get('initialization', 'init.mp4')
                    self.chunk_template = elem.attrib.get('media', 'chunk_$Number$.m4s')
                    
                    timescale = float(elem.attrib.get('timescale', 1000))
                    duration = float(elem.attrib.get('duration', 3000))
                    self.chunk_duration_sec = duration / timescale
                    self.start_number = int(elem.attrib.get('startNumber', 1))
                    break
        except Exception as e:
            pass

    def request_frame(self, mpd_path, hover_sec):
        if self._is_killed: return # Protection against zombie threads
        
        target_sec = round(hover_sec / self.interval) * self.interval
        
        if self.video_path != mpd_path:
            self.video_path = mpd_path
            self.cache.clear()
            self.bg_anchor = 0
            self.bg_radius = self.interval
            self.bg_left_done = False
            self.bg_right_done = False
            self.parse_mpd(mpd_path)

        if target_sec in self.cache:
            self.preview_ready.emit(target_sec, self.cache[target_sec])
            return

        if self.target_sec == target_sec:
            return

        self.target_sec = target_sec
        if not self.isRunning():
            self.start()

    def run(self):
        import io, av
        from PySide6.QtGui import QImage
        last_serviced = -1
        
        # replaced while True with a kill-switch check!
        while not self._is_killed:
            # --- SMART TASK DISTRIBUTOR ---
            if self.target_sec != -1 and self.target_sec != last_serviced:
                sec = self.target_sec
                is_background = False
                self.bg_anchor = self.target_sec
                self.bg_radius = self.interval
                self.bg_left_done = False
                self.bg_right_done = False
            else:
                sec = -1
                while not (self.bg_left_done and self.bg_right_done):
                    if self.target_sec != last_serviced or self._is_killed:
                        break
                        
                    if not self.bg_right_done:
                        candidate = self.bg_anchor + self.bg_radius
                        if candidate not in self.cache:
                            sec = candidate
                            self.bg_side = "right"
                            break
                            
                    if not self.bg_left_done:
                        candidate = self.bg_anchor - self.bg_radius
                        if candidate >= 0:
                            if candidate not in self.cache:
                                sec = candidate
                                self.bg_side = "left"
                                break
                        else:
                            self.bg_left_done = True 
                            
                    self.bg_radius += self.interval
                
                if sec == -1:
                    if self.target_sec == last_serviced:
                        self.msleep(100)
                    continue
                    
                is_background = True

            try:
                chunk_offset = int(sec // self.chunk_duration_sec)
                chunk_num = self.start_number + chunk_offset
                
                real_init = self.init_filename.replace('$RepresentationID$', self.rep_id)
                real_chunk = self.chunk_template.replace('$RepresentationID$', self.rep_id)
                
                import re
                match = re.search(r'\$Number([^$]*)\$', real_chunk)
                if match:
                    format_spec = match.group(1)
                    num_str = format_spec % chunk_num if format_spec else str(chunk_num)
                    real_chunk = real_chunk[:match.start()] + num_str + real_chunk[match.end():]
                else:
                    real_chunk = real_chunk.replace('$Number$', str(chunk_num))
                    
                init_path = os.path.normpath(os.path.join(self.base_dir, real_init))
                chunk_path = os.path.normpath(os.path.join(self.base_dir, real_chunk))
                
                if not os.path.exists(init_path) or not os.path.exists(chunk_path):
                    if is_background:
                        if self.bg_side == "right": self.bg_right_done = True 
                        elif self.bg_side == "left": self.bg_left_done = True
                    else:
                        last_serviced = sec
                    continue

                # --- DECODING ---
                with open(init_path, 'rb') as f:
                    init_bytes = f.read()
                with open(chunk_path, 'rb') as f:
                    chunk_bytes = f.read()
                    
                ram_buffer = io.BytesIO(init_bytes + chunk_bytes)
                container = av.open(ram_buffer)
                stream = container.streams.video[0]
                
                for frame in container.decode(stream):
                    if self._is_killed: break #Emergency exit if the clip has been closed
                    
                    img = frame.to_image()
                    img = img.resize((160, 90))
                    
                    img_data = img.convert("RGBA").tobytes("raw", "RGBA")
                    qimg = QImage(img_data, img.width, img.height, QImage.Format_RGBA8888)
                    pixmap = QPixmap.fromImage(qimg)
                    
                    self.cache[sec] = pixmap
                    
                    # send only if the thread has not been killed
                    if not is_background and self.target_sec == sec and not self._is_killed:
                        self.preview_ready.emit(sec, pixmap)
                    break 
                    
                container.close()

                if not is_background:
                    last_serviced = sec

            except Exception as e:
                if is_background:
                    if self.bg_side == "right": self.bg_right_done = True
                    else: self.bg_left_done = True
                else:
                    last_serviced = sec
        
# --- BACKGROUND WORKER: THUMBNAIL BATCH GENERATOR (THE MATRIX 2.0) ---
class ThumbnailBatchThread(QThread):
    """ Generates all thumbnails in the background ONCE, using GPU. """
    finished_generation = Signal(str) 

    def __init__(self, mpd_path, duration_sec, interval=3, parent=None):
        super().__init__(parent)
        self.mpd_path = mpd_path
        self.duration_sec = duration_sec
        self.interval = interval 
        self.process = None
        
        import hashlib, tempfile
        path_hash = hashlib.md5(mpd_path.encode('utf-8')).hexdigest()[:10]
        self.thumb_dir = os.path.join(tempfile.gettempdir(), f"steempeg_batch_{path_hash}_{self.interval}s")
        os.makedirs(self.thumb_dir, exist_ok=True)

    def stop(self):
        """ FORCE-KILLING THE FFMPEG PROCESS BEFORE STOPPING THE STREAM! """
        if self.process:
            try:
                self.process.kill()
            except:
                pass
        self.terminate()

    def run(self):
        import glob, shutil
        existing_files = glob.glob(os.path.join(self.thumb_dir, "thumb_*.jpg"))
        expected_count = int(self.duration_sec // self.interval)
        
        if len(existing_files) >= expected_count * 0.9:
            self.finished_generation.emit(self.thumb_dir)
            return

        shutil.rmtree(self.thumb_dir, ignore_errors=True)
        os.makedirs(self.thumb_dir, exist_ok=True)

        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-hwaccel", "auto",       
            "-threads", "2",          
            "-i", self.mpd_path,
            "-vf", f"fps=1/{self.interval}", 
            "-q:v", "7",              
            "-s", "160x90",           
            os.path.join(self.thumb_dir, "thumb_%04d.jpg") 
        ]
        
        # We launch it via Popen so that we can kill it!
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        self.process = subprocess.Popen(cmd, creationflags=creationflags)
        self.process.wait()
        
        self.finished_generation.emit(self.thumb_dir)

from PySide6.QtCore import QObject, QEvent


    
class TimelineCanvas(QWidget):
    """ The inner canvas of the timeline (the one that stretches when you zoom) """
    pause_requested = Signal()        
    seek_requested = Signal(int)      
    resume_requested = Signal()
    trim_changed = Signal(int, int) 
    
    screenshot_requested = Signal(float) 
    add_marker_requested = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(52) 
        self.duration_ms = 0
        self.setMouseTracking(True)
        
        if 'ThumbnailPreviewWidget' in globals():
            self.preview_widget = ThumbnailPreviewWidget()

        self.visual_ms = 0.0  
        self.target_ms = 0.0  
        self.vlc_last_update_time = time.time()
        
        self.is_playing = False
        self.user_seek_lock_time = 0 
        
        self.is_trim_mode = False
        self.trim_start_ms = 0.0
        self.trim_end_ms = 0.0
        
        self.drag_state = 'none'
        self.last_frame_time = time.time()
        
        # 60 FPS Engine
        from PySide6.QtCore import QTimer
        self.fps_timer = QTimer(self)
        self.fps_timer.timeout.connect(self.process_60fps_frame)
        self.fps_timer.start(16) 
        
        # Colors
        from PySide6.QtGui import QColor, QImage
        self.track_color = QColor(255, 255, 255, 40)
        self.fill_color = QColor("#b29ae7")
        self.handle_color = QColor(255, 255, 255)
        self.trim_body_color = QColor(255, 204, 0, 80) 
        self.trim_handle_color = QColor(255, 204, 0) 

        from PySide6.QtGui import QImage, QPainter, QBrush
        from PySide6.QtCore import Qt, QRect
        
        h = QImage(get_resource_path("scrollerhead2.png"))
        b = QImage(get_resource_path("scrollerbody.png"))
        p = QImage(get_resource_path("scrolleback.png"))
        
        if not (h.isNull() or b.isNull() or p.isNull()):
            # Compress to Compact Dimensions
            h_s = h.scaledToWidth(8, Qt.SmoothTransformation)
            b_s = b.scaledToWidth(4, Qt.SmoothTransformation)
            p_s = p.scaledToWidth(4, Qt.SmoothTransformation)
            
            self.master_head_h = float(h_s.height())
            
            # Your hardcoded constant from paintEvent (height of the purple bar)
            track_h = 12 
            total_h = h_s.height() + track_h + p_s.height()
            
            # Create an absolutely empty, transparent canvas for our monolith.
            master = QImage(8, total_h, QImage.Format_ARGB32)
            master.fill(Qt.transparent)
            
            mp = QPainter(master)
            mp.setRenderHint(QPainter.Antialiasing, True)
            mp.setRenderHint(QPainter.SmoothPixmapTransform, True)
            
            # 1. Draw the torso exactly in the center (Offset X=2, Width=4)
            # Overlap by 1px at the top and bottom to avoid any gaps
            body_rect = QRect(2, h_s.height() - 1, 4, track_h + 2)
            brush = QBrush(b_s)
            mp.setBrushOrigin(body_rect.topLeft())
            mp.fillRect(body_rect, brush)
            
            # 2. Stamp the Head (X=0, Width=8) and the Bottom (X=2, Width=4) on top.
            mp.drawImage(0, 0, h_s)
            mp.drawImage(2, h_s.height() + track_h, p_s)
            mp.end()
            
            self.master_scroller_img = master
            self.has_custom_scroller = True
        else:
            self.has_custom_scroller = False

        self.hover_x = -1.0
        self.is_hovering = False

        self.current_video_path = ""
        self.current_preview_pixmap = None
        
        if 'PreviewSniperWorker' in globals():
            self.sniper = PreviewSniperWorker()
            self.sniper.preview_ready.connect(self.on_preview_ready)
            
            self.sniper_timer = QTimer(self)
            self.sniper_timer.setSingleShot(True)
            self.sniper_timer.timeout.connect(self.trigger_sniper)
        self.pending_sec = -1

        # LABELS AND ICONS CS2
        self.markers = []
        self.hovered_marker = None
        self.cached_pixmaps = {}
        
        # NEW FLOATING TOOLTIP (Will reside beneath the scrollbar)
        from PySide6.QtWidgets import QLabel
        self.text_tooltip = QLabel()
        self.text_tooltip.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.text_tooltip.setAttribute(Qt.WA_ShowWithoutActivating)
        self.text_tooltip.setStyleSheet("QLabel { background-color: #181818; color: white; border: 1px solid #444; border-radius: 4px; padding: 6px 10px; font-family: 'Segoe UI'; font-size: 12px; }")
        self.text_tooltip.hide()
        
        # We use your get_resource_path function so that the icons are always found!
        self.icon_paths = {
            'kill': get_resource_path("kill.png"),
            'knife': get_resource_path("knife.png"),
            'tazer': get_resource_path("tazer.png"),
            'grenade': get_resource_path("grenade.png"),
            'firemolotov': get_resource_path("firemolotov.png"),
            'flashbang': get_resource_path("flashbang.png"),
            'smoke': get_resource_path("smoke.png"),
            'bomb': get_resource_path("bomb.png"),
            'explosion': get_resource_path("explosion.png"),
            'defuse': get_resource_path("defuse.png"),
            'death': get_resource_path("death.png"),
            'screenshot': get_resource_path("screenshot.png"),
            'restrict': get_resource_path("restrict.png"),
            'point': get_resource_path("point.png"),
            'usermarker': get_resource_path("pointuser.png")
        }
            
        
        self.digit_paths = {
            '0': get_resource_path("zero.png"),
            '1': get_resource_path("one.png"),
            '2': get_resource_path("two.png"),
            '3': get_resource_path("three.png"),
            '4': get_resource_path("four.png"),
            '5': get_resource_path("five.png"),
            '6': get_resource_path("six.png"),
            '7': get_resource_path("seven.png"),
            '8': get_resource_path("eight.png"),
            '9': get_resource_path("nine.png")
        }


    def load_timeline_json(self, json_path, offset_ms=0):
        """ Reads JSON, adjusts chunk times, and populates the self.markers list. """
        import json, os
        
        self.current_json_path = json_path  
        self.current_offset_ms = offset_ms  
        
        self.markers.clear()
        if not os.path.exists(json_path): return
        
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            entries = data.get('entries', [])
            for entry in entries:
               # Subtract the time of the cut pieces!
                raw_time = int(entry.get('time', 0))
                time_ms = raw_time - offset_ms
                
                if time_ms < 0: continue 

                type_ = entry.get('type', '')
                title = entry.get('title', '')
                desc = entry.get('description', '')
                m_id = str(entry.get('id', '')) # TAKE STEAM ID!
                
                if type_ not in ['event', 'screenshot', 'error', 'restrict', 'usermarker']: continue
                
                icon_key, is_round = self.parse_event_to_icon(type_, title, desc)
                if icon_key == 'screenshot' and not title: title = "A screenshot"
                
                self.markers.append({
                    'id': m_id,  # SAVING THE ID IN MEMORY!
                    'time_ms': time_ms,
                    'icon_key': icon_key,
                    'is_round': is_round, 
                    'title': title,
                    'desc': desc
                })
            self.update()
        except Exception as e:
            print(f"Error loading JSON: {e}")

    def parse_event_to_icon(self, type_, title, desc):
        """ Smart detector: understands who killed whom and with what """
        import re
        t_low = title.lower()
        d_low = desc.lower()
        
        if type_ == 'usermarker': return 'usermarker', False 
        if type_ == 'screenshot': return 'screenshot', False
        if type_ in ['error', 'restrict']: return 'restrict', False
        
       # Catching rounds ("Start of round 16")
        round_match = re.search(r"start of round (\d+)", t_low)
        if round_match: 
            return round_match.group(1), True 
            
        if 'bomb planted' in t_low: return 'bomb', False
        if 'bomb exploded' in t_low or 'explosion' in t_low: return 'explosion', False
        if 'bomb defused' in t_low or 'defuse' in t_low: return 'defuse', False 
        if 'killed by' in t_low or 'killed yourself' in t_low: return 'death', False
        
        
        # Kills 
        if 'kill' in t_low:
            if 'knife' in d_low: return 'knife', False
            if 'zeus' in d_low or 'taser' in d_low: return 'tazer', False
            if 'he grenade' in d_low or 'grenade' in d_low: return 'grenade', False
            if 'fire' in d_low or 'molotov' in d_low or 'incendiary' in d_low: return 'firemolotov', False
            if 'flashbang' in d_low: return 'flashbang', False
            if 'smoke' in d_low: return 'smoke', False
            return 'kill', False 
            
        return 'point', False 

    def get_icon_pixmap(self, icon_key, is_round):
        """ Gets an icon or GLUES the round numbers (RETINA 2X RESOLUTION) """
        from PySide6.QtGui import QPixmap, QPainter
        from PySide6.QtCore import Qt
        import os
        
        if icon_key in self.cached_pixmaps:
            return self.cached_pixmaps[icon_key]
            
        if is_round:
            pixmaps = []
            for digit in str(icon_key): 
                path = self.digit_paths.get(digit)
                if path and os.path.exists(path):
                    pixmaps.append(QPixmap(path).scaledToHeight(36, Qt.SmoothTransformation))
            
            if not pixmaps: return None
            
            total_width = sum(p.width() for p in pixmaps)
            result = QPixmap(total_width, 36)
            result.fill(Qt.transparent)
            painter = QPainter(result)
            x_offset = 0
            for p in pixmaps:
                painter.drawPixmap(x_offset, 0, p)
                x_offset += p.width()
            painter.end()
            
            self.cached_pixmaps[icon_key] = result
            return result
        else:
            path = self.icon_paths.get(icon_key, self.icon_paths['point'])
            if path and os.path.exists(path):
                pixmap = QPixmap(path).scaledToHeight(36, Qt.SmoothTransformation)
                self.cached_pixmaps[icon_key] = pixmap
                return pixmap
        return None
    def on_preview_ready(self, sec, pixmap):
        if self.duration_ms <= 0: return
        if getattr(self, 'is_hovering', False):
            hover_ms = max(0.0, min(self.x_to_ms(self.hover_x), float(self.duration_ms)))
            current_target_sec = round((hover_ms // 1000) / 3.0) * 3
            if int(sec) == int(current_target_sec):
                if hasattr(self, 'preview_widget') and self.preview_widget.isVisible():
                    self.preview_widget.update_image_from_ram(pixmap)

    def trigger_sniper(self):
        if hasattr(self, 'sniper') and self.current_video_path and self.pending_sec >= 0:
            self.sniper.request_frame(self.current_video_path, self.pending_sec)

    def set_duration(self, duration_ms):
        self.duration_ms = max(1, duration_ms)

    def set_vlc_time(self, vlc_ms, is_playing):
        self.is_playing = is_playing
        if self.drag_state == 'playhead': return
        if vlc_ms != self.target_ms:
            self.target_ms = float(vlc_ms)
            self.vlc_last_update_time = time.time()

    def enable_trim_mode(self):
        if self.duration_ms <= 0: return
        self.is_trim_mode = True
        self.trim_start_ms = self.visual_ms
        self.trim_end_ms = min(self.trim_start_ms + 10000.0, self.duration_ms)
        self.trim_changed.emit(int(self.trim_start_ms), int(self.trim_end_ms))
        self.update()

    def disable_trim_mode(self):
        self.is_trim_mode = False
        self.update()

    def process_60fps_frame(self):
        now = time.time()
        delta_ms = (now - self.last_frame_time) * 1000.0
        self.last_frame_time = now # Update NO MATTER WHAT to avoid any jumps!
        
        if self.drag_state == 'playhead' or self.duration_ms <= 0: return
        if now < getattr(self, 'user_seek_lock_time', 0): return 

        # Perfect Interpolation During Zoom
        if getattr(self, 'is_zooming', False):
            # Detach from the MPV player (so it doesn't snap us back)
            # But continue to smoothly move the stick under our own power!
            if self.is_playing:
                self.visual_ms += delta_ms
                
            self.visual_ms = max(0.0, min(self.visual_ms, float(self.duration_ms)))
            self.update() # Rendering the frame: the canvas stretches, but the stick lives on!
            return

        # --- STANDARD ENGINE LOGIC (When zoom is finished) ---
        if self.is_playing:
            self.visual_ms += delta_ms
            drift = self.target_ms - self.visual_ms
            if abs(drift) > 1000: self.visual_ms = self.target_ms 
            else: self.visual_ms += drift * 0.1 
        else:
            self.visual_ms += (self.target_ms - self.visual_ms) * 0.3

        self.visual_ms = max(0.0, min(self.visual_ms, float(self.duration_ms)))
        self.update()
        
    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QColor, QPen, QFont
        from PySide6.QtCore import QRectF, Qt
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        width = float(self.width())
        painter.fillRect(self.rect(), QColor("#1e1e1e"))
        
        track_height = 12.0 
        track_y = 22.0 

        ruler_y = track_y + track_height + 3.0

        painter.fillRect(QRectF(0.0, track_y, width, track_height), self.track_color)
        if self.duration_ms <= 0: return
        
        fill_width = (self.visual_ms / self.duration_ms) * width
        painter.fillRect(QRectF(0.0, track_y, fill_width, track_height), self.fill_color)
        
        if self.is_trim_mode:
            start_x = (self.trim_start_ms / self.duration_ms) * width
            end_x = (self.trim_end_ms / self.duration_ms) * width
            painter.fillRect(QRectF(start_x, track_y, end_x - start_x, track_height), self.trim_body_color)
            painter.fillRect(QRectF(start_x, track_y - 2.0, 4.0, track_height + 4.0), self.trim_handle_color)
            painter.fillRect(QRectF(end_x - 4.0, track_y - 2.0, 4.0, track_height + 4.0), self.trim_handle_color)

        for marker in getattr(self, 'markers', []):
            if marker['is_round']:
                m_x = self.ms_to_x(marker['time_ms'])
                # Draw a 2px-wide tick mark over the purple background,
                # but BEFORE the white playhead bar is drawn at the end of the function!
                painter.fillRect(QRectF(m_x - 1.0, track_y, 2.0, track_height), QColor(255, 255, 255, 140))

        pixels_per_sec = width / (self.duration_ms / 1000.0)
        
        # SMART SCALING
        if pixels_per_sec < 0.1: step = 900       # 15-minute step (for very long durations)
        elif pixels_per_sec < 0.25: step = 600    # 10-minute step
        elif pixels_per_sec < 0.5: step = 300     # 5-minute step
        elif pixels_per_sec < 2: step = 60        # 1-minute step
        elif pixels_per_sec < 10: step = 10       # 10-second step
        elif pixels_per_sec < 50: step = 5        # 5-second step
        elif pixels_per_sec < 150: step = 1       # 1-second step
        else: step = 0.5                          # 0.5-second step (maximum zoom)

        rect = event.rect()
        start_sec = max(0, int(self.x_to_ms(rect.left()) / 1000))
        end_sec = min(int(self.duration_ms / 1000), int(self.x_to_ms(rect.right()) / 1000) + 1)
        start_sec -= start_sec % int(max(1, step)) 

        painter.setPen(QPen(QColor(255, 255, 255, 180), 1))
        painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
        
        ruler_y = track_y + track_height + 4 

        current_sec = start_sec
        while current_sec <= end_sec:
            x = self.ms_to_x(current_sec * 1000)
            is_major = (current_sec % max(10, step * 5) == 0) or (step >= 60 and current_sec % 60 == 0)

            if is_major:
                painter.drawLine(int(x), int(ruler_y), int(x), int(ruler_y + 8)) 
                
                # The New Mathematics of Time (With Clocks)
                h = int(current_sec // 3600)
                m = int((current_sec % 3600) // 60)
                s = int(current_sec % 60)
                
                # If the duration exceeds one hour, display H:MM:SS; otherwise, M:SS
                if h > 0:
                    time_str = f"{h}:{m:02d}:{s:02d}"
                else:
                    time_str = f"{m}:{s:02d}"
                    
                painter.drawText(int(x) + 3, int(ruler_y + 8), time_str) 
            else:
                painter.drawLine(int(x), int(ruler_y), int(x), int(ruler_y + 3)) 

            current_sec += step

        # Drawing icons and tooltips
        from PySide6.QtGui import QPainterPath 
        from PySide6.QtCore import QRect

        start_x_vp = 0
        end_x_vp = width
        scroll_area = self.parentWidget().parentWidget() if self.parentWidget() else None
        if hasattr(scroll_area, 'horizontalScrollBar'):
            start_x_vp = scroll_area.horizontalScrollBar().value()
            end_x_vp = start_x_vp + scroll_area.viewport().width()

        painter.setRenderHint(QPainter.Antialiasing, True)
        
        conn_pen = QPen(QColor(255, 255, 255, 150), 1) 
        conn_pen.setCapStyle(Qt.RoundCap) 
        
        def draw_marker(marker, is_hovered):
            m_x = self.ms_to_x(marker['time_ms'])
            pix = self.get_icon_pixmap(marker['icon_key'], marker['is_round'])
            if not pix: return

            # Visually Shrinking a Massive 36px Image Down to 18px
            base_w = pix.width() / 2.0
            base_h = pix.height() / 2.0
            
            draw_w = int(base_w * 1.2) if is_hovered else int(base_w)
            draw_h = int(base_h * 1.2) if is_hovered else int(base_h)
            
            base_icon_y = 2 
            base_bottom = base_icon_y + base_h
            
            draw_x = int(m_x - draw_w / 2)
            draw_y = int(base_icon_y - (draw_h - base_h) / 2)
            
            if not marker['is_round']:
                conn_x = int(m_x)
                if is_hovered:
                    painter.setPen(QPen(QColor(255, 255, 255, 255), 2, Qt.SolidLine, Qt.RoundCap))
                else:
                    painter.setPen(conn_pen)
                painter.drawLine(int(conn_x), int(base_bottom), int(conn_x), int(track_y))
            
            from PySide6.QtCore import QRect
            smooth_pix = pix.scaled(draw_w, draw_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawPixmap(draw_x, draw_y, smooth_pix)

        # 1. BACKGROUND LAYER: Draw ALL standard icons 
        hovered_m = getattr(self, 'hovered_marker', None)
        last_drawn_x = -9999
        marker_width = 16.0 
        
        # Sort the markers by time to ensure rendering proceeds strictly from left to right!
        sorted_markers = sorted(getattr(self, 'markers', []), key=lambda m: m['time_ms'])
        
        for marker in sorted_markers:
            if marker != hovered_m:
                m_x = self.ms_to_x(marker['time_ms'])
                
                # If the distance to the previous marker is less than 16px, make it transparent
                if (m_x - last_drawn_x) < marker_width:
                    painter.setOpacity(0.5)
                else:
                    painter.setOpacity(1.0)
                    last_drawn_x = m_x
                    
                draw_marker(marker, False)
                painter.setOpacity(1.0) # Make sure to reset it for the next one!
                
       # 2. TOP LAYER: Draw the hovered icon (Always 100% visible on top!)
        if hovered_m and hovered_m in getattr(self, 'markers', []):
            painter.setOpacity(1.0)
            draw_marker(hovered_m, True)

        # Hide the prediction (ghost) on icon hover.
        if getattr(self, 'is_hovering', False) and not getattr(self, 'is_hovering_trim_handle', False) and self.drag_state == 'none' and not getattr(self, 'hovered_marker', None):
            ghost_w = 4.0
            ghost_x = max(0.0, min(self.hover_x - (ghost_w / 2.0), width - ghost_w))
            painter.fillRect(QRectF(ghost_x, track_y - 4.0, ghost_w, track_height + 8.0), QColor(255, 255, 255, 80))

        #  ULTRA SCROLLER ASSEMBLY 
        if not getattr(self, 'has_custom_scroller', False):
            # Old white strip (if no images)
            handle_w = 4.0
            # Centering a standard white stick
            handle_x = fill_width - (handle_w / 2.0) 
            painter.fillRect(QRectF(handle_x, track_y - 4.0, handle_w, track_height + 8.0), self.handle_color)
        else:
            from PySide6.QtCore import QPointF
            from PySide6.QtGui import QPainter
            
            handle_w = 8.0
            
            # FIX 1: Center the scroller image! 
            # Subtract exactly half the width (4px) so the needle points precisely at the time.
            handle_x = fill_width - (handle_w / 2.0) 
            handle_y = track_y - self.master_head_h
            
            painter.save() 
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            
            painter.translate(handle_x, handle_y)
        
            painter.scale(1.001, 1.001) 
            
            painter.drawImage(QPointF(0.0, 0.0), self.master_scroller_img)
            
            painter.restore()

    def ms_to_x(self, ms):
        if self.duration_ms <= 0: return 0
        return (ms / self.duration_ms) * self.width()

    def x_to_ms(self, x):
        if self.width() <= 0: return 0
        return (max(0, min(x, self.width())) / self.width()) * self.duration_ms

    def mousePressEvent(self, event):
        from PySide6.QtCore import Qt
        if self.duration_ms <= 0: return
        x, y = event.position().x(), event.position().y()
        ms = self.x_to_ms(x)

        # CHECK ICON CLICK
        if event.button() == Qt.RightButton:
            if getattr(self, 'hovered_marker', None):
                #Right-click on an existing label
                self.show_marker_context_menu(event.globalPosition().toPoint(), self.hovered_marker)
            else:
                #Right-click on an empty space (or bar)
                self.show_track_context_menu(event.globalPosition().toPoint(), ms)
            return

        # --- HANDLING LEFT-CLICK ON LABEL ---
        if getattr(self, 'hovered_marker', None) and event.button() == Qt.LeftButton:
            jump_time = max(0, self.hovered_marker['time_ms'] - 2000)
            self.force_jump(jump_time)
            return

        # Disable the other buttons if we are not on the icon.
        if event.button() != Qt.LeftButton: return
        
        track_y, track_height = 22.0, 12.0 
        is_outside_track = (y < track_y) or (y > track_y + track_height)
        
        if self.is_trim_mode and not is_outside_track:
            start_x = self.ms_to_x(self.trim_start_ms)
            end_x = self.ms_to_x(self.trim_end_ms)
            hit_tolerance = 10 
            
            if abs(x - start_x) <= hit_tolerance:
                self.drag_state = 'trim_l'
                return
            elif abs(x - end_x) <= hit_tolerance:
                self.drag_state = 'trim_r'
                return
                
        self.drag_state = 'playhead'
        self.pause_requested.emit() 
        self.update_playhead(x)

    def show_marker_context_menu(self, pos, marker):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { 
                background-color: #2d2d2d; 
                color: #ffffff; 
                border: 2px solid #444444; 
                border-radius: 8px; 
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 13px;
                font-weight: bold;
            }
            QMenu::item { 
                padding: 6px 24px 6px 24px; 
                border-radius: 4px;
                margin: 2px 4px;
            }
            QMenu::item:selected { 
                background-color: #6b5a8e; 
            }
            QMenu::separator {
                height: 1px;
                background-color: #444444;
                margin: 4px 10px;
            }
        """)
        
        # Declare variables in advance so the code doesn't crash if the buttons are missing
        action_edit = None
        action_delete = None
        
        # Check whether the marker is custom or system-defined
        is_user_marker = marker.get('icon_key') == 'usermarker'
        
        if is_user_marker:
            action_edit = menu.addAction("✏️ Edit Marker")
            action_delete = menu.addAction("🗑️ Delete Marker")
            menu.addSeparator() 
            
        action_trim = menu.addAction("✂️ Set Trim Start Here")
        
        # NEW SCREENSHOT BUTTON
        action_screenshot = menu.addAction("📸 Take Screenshot Here")
        
        action = menu.exec(pos)
        
        # Handle clicks
        if action_edit and action == action_edit:
            self.edit_user_marker(marker)
        elif action_delete and action == action_delete:
            self.delete_user_marker(marker)
        elif action == action_trim:
            self.set_trim_start_from_marker(marker)
        elif action == action_screenshot: # Sending the order to take a screenshot
            self.screenshot_requested.emit(float(marker.get('time_ms', 0)))
    
    def show_track_context_menu(self, pos, time_ms):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #2d2d2d; color: #ffffff; border: 2px solid #444444; border-radius: 8px; font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; font-weight: bold; }
            QMenu::item { padding: 6px 24px 6px 24px; border-radius: 4px; margin: 2px 4px; }
            QMenu::item:selected { background-color: #6b5a8e; }
        """)

        action_add_marker = menu.addAction("📍 Add Marker Here")
        action_screenshot = menu.addAction("📸 Take Screenshot Here")
        
        action = menu.exec(pos)
        
        if action == action_add_marker:
            self.add_marker_requested.emit(float(time_ms))
        elif action == action_screenshot:
            self.screenshot_requested.emit(float(time_ms))

    def set_trim_start_from_marker(self, marker):
        """ Magic method: Snaps the start directly to the marker! """
        marker_ms = float(marker.get('time_ms', 0))
        
        # 1. If trim mode is OFF - emulate a click on the real Trim button!
        if not self.is_trim_mode:
            import PySide6.QtWidgets as qtw
            # Find the actual button in the main window and click it to sync the UI
            for btn in self.window().findChildren(qtw.QPushButton):
                if "Trim" in btn.text():
                    btn.click() 
                    break
                    
        # 2. UNO Reverse Magic: Move the yellow bar to the marker
        old_start = self.trim_start_ms
        old_end = self.trim_end_ms
        duration = old_end - old_start
        
        if marker_ms >= old_end:
            self.trim_start_ms = marker_ms
            self.trim_end_ms = min(marker_ms + duration, self.duration_ms)
        else:
            self.trim_start_ms = marker_ms
            
        self.trim_changed.emit(int(self.trim_start_ms), int(self.trim_end_ms))
        self.update()

    def edit_user_marker(self, marker):
        """ Opens the editing window and saves to Steam JSON. """
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTextEdit, QPushButton
        import json, os

        dialog = QDialog(self)
        dialog.setWindowTitle("Edit Steam Marker")
        dialog.setFixedSize(350, 250)
        dialog.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: white; }
            QLabel { color: #ccc; font-weight: bold; }
            QLineEdit, QTextEdit { background-color: #2d2d2d; color: white; border: 1px solid #555; border-radius: 4px; padding: 4px; }
            QPushButton { background-color: #444; color: white; border-radius: 4px; padding: 6px; font-weight: bold; }
            QPushButton:hover { background-color: #555; }
        """)

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Title:"))
        title_edit = QLineEdit(marker.get('title', ''))
        layout.addWidget(title_edit)

        layout.addWidget(QLabel("Description:"))
        desc_edit = QTextEdit(marker.get('desc', ''))
        layout.addWidget(desc_edit)

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

        save_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)

        if dialog.exec():
            # 1. Updating the program's memory
            marker['title'] = title_edit.text().strip()
            marker['desc'] = desc_edit.toPlainText().strip()
            if hasattr(self, 'text_tooltip'): self.text_tooltip.hide()
            self.update()

            # 2. Overwriting in the JSON file by ID!
            json_path = getattr(self, 'current_json_path', None)
            if not json_path or not os.path.exists(json_path): return
            try:
                with open(json_path, 'r', encoding='utf-8') as f: data = json.load(f)
                if 'entries' in data:
                    for e in data['entries']:
                        if str(e.get('id')) == str(marker.get('id')):
                            e['title'] = marker['title']
                            e['description'] = marker['desc'] # Steam uses 'description'
                            break
                    with open(json_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
            except Exception as e:
                print(f"Edit error: {e}")

    def delete_user_marker(self, marker):
        """ Burns a tag strictly by its ID. """
        import json, os
        
        if marker in getattr(self, 'markers', []):
            self.markers.remove(marker)
            self.hovered_marker = None
            if hasattr(self, 'text_tooltip'): self.text_tooltip.hide()
            self.update()
            
        json_path = getattr(self, 'current_json_path', None)
        if not json_path or not os.path.exists(json_path): return
        
        try:
            with open(json_path, 'r', encoding='utf-8') as f: data = json.load(f)
            if 'entries' in data:
                data['entries'] = [e for e in data['entries'] if str(e.get('id')) != str(marker.get('id'))]
                with open(json_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Delete error: {e}")

    def mouseMoveEvent(self, event):
        from PySide6.QtCore import Qt
        import os
        if self.duration_ms <= 0: return
        
        x, y = event.position().x(), event.position().y()
        ms = self.x_to_ms(x)
        
        self.hover_x = float(x)
        self.is_hovering = True 
        self.is_hovering_trim_handle = False

        found_marker = None
        for marker in getattr(self, 'markers', []):
            m_x = self.ms_to_x(marker['time_ms'])
            pix = self.get_icon_pixmap(marker['icon_key'], marker['is_round'])
            
            # DIVIDE THE WIDTH BY 2 (since the image in the cache is now 36px, while on the screen it is 18px).
            pw = (pix.width() / 2.0) if pix else 18.0
            
            if abs(x - m_x) <= (pw / 2) + 8 and 0 <= y <= 28:
                found_marker = marker
                break
        
        # Updating the UI when the icon focus changes.
        if found_marker != getattr(self, 'hovered_marker', None):
            self.hovered_marker = found_marker
            self.update()
            
            # Logic for a Pop-up Tooltip Beneath the Scrollbar
            if hasattr(self, 'text_tooltip'):
                if found_marker:
                    title = found_marker.get('title', '')
                    desc = found_marker.get('desc', '')
                    
                    # Filling the void and adding a hint!
                    if found_marker.get('icon_key') == 'usermarker':
                        if not title: title = "User Marker"
                        
                    html_text = f"<b>{title}</b>"
                    if desc: html_text += f"<br>{desc}"
                    
                    self.text_tooltip.setText(html_text)
                    self.text_tooltip.adjustSize()
                    
                    from PySide6.QtCore import QPoint
                    scroll_area = self.parentWidget().parentWidget() if self.parentWidget() else self
                    global_y = scroll_area.mapToGlobal(QPoint(0, scroll_area.height() + 4)).y()
                    global_x = self.mapToGlobal(QPoint(int(m_x), 0)).x() - (self.text_tooltip.width() // 2)
                    
                    self.text_tooltip.move(global_x, global_y)
                    self.text_tooltip.show()
                else:
                    self.text_tooltip.hide()
        
        #Change the cursor to the default (arrow) when hovering over an icon.
        if found_marker:
            current_cursor = Qt.ArrowCursor
        else:
            current_cursor = Qt.PointingHandCursor
            
        track_y, track_height = 22.0, 12.0 
        is_outside_trim_hitbox = (y < track_y - 10.0) or (y > track_y + track_height + 10.0)
        
        if self.is_trim_mode and not is_outside_trim_hitbox:
            start_x, end_x = self.ms_to_x(self.trim_start_ms), self.ms_to_x(self.trim_end_ms)
            if abs(x - start_x) <= 10 or abs(x - end_x) <= 10:
                current_cursor, self.is_hovering_trim_handle = Qt.SizeHorCursor, True
                
        if self.drag_state in ['trim_l', 'trim_r']:
            current_cursor, self.is_hovering_trim_handle = Qt.SizeHorCursor, True
            
        self.setCursor(current_cursor)
        
        if hasattr(self, 'preview_widget') and not getattr(self, 'hovered_marker', None):
            hover_ms = max(0.0, min(ms, float(self.duration_ms)))
            sec = int(hover_ms // 1000)
            h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
            time_str = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
            
            is_in_trim = self.is_trim_mode and (self.trim_start_ms <= hover_ms <= self.trim_end_ms)
            current_thumb_dir = getattr(self, 'thumb_dir', None)
            has_disk_thumb = False
            
            if current_thumb_dir and os.path.exists(current_thumb_dir):
                index = (sec // 3) + 1
                img_path = os.path.join(current_thumb_dir, f"thumb_{index:04d}.jpg")
                if os.path.exists(img_path):
                    has_disk_thumb = True
                    self.preview_widget.update_info(time_str, is_in_trim, hover_ms, current_thumb_dir)
            
            if not has_disk_thumb:
                target_sec = round(sec / 3.0) * 3
                if hasattr(self, 'sniper') and target_sec in self.sniper.cache:
                    self.preview_widget.update_info(time_str, is_in_trim, hover_ms, None)
                    self.preview_widget.update_image_from_ram(self.sniper.cache[target_sec])
                else:
                    if hasattr(self, 'sniper') and self.current_video_path:
                        self.pending_sec = sec
                        if hasattr(self, 'sniper_timer'): self.sniper_timer.start(120) 
                    
                    self.preview_widget.update_info(time_str, is_in_trim, hover_ms, None)
                    from PySide6.QtGui import QPixmap
                    self.preview_widget.img_label.setPixmap(QPixmap())
                    self.preview_widget.img_label.setText("Generating...")

            if self.parentWidget() and self.parentWidget().parentWidget():
                target_x = event.globalPosition().x() - (self.preview_widget.width() // 2)
                target_y = self.parentWidget().parentWidget().mapToGlobal(self.parentWidget().parentWidget().rect().topLeft()).y() - self.preview_widget.height() - 5
                
                min_x = self.parentWidget().parentWidget().mapToGlobal(self.parentWidget().parentWidget().rect().topLeft()).x()
                max_x = min_x + self.parentWidget().parentWidget().width() - self.preview_widget.width()
                clamped_x = max(min_x, min(target_x, max_x))
                self.preview_widget.move(clamped_x, target_y)
                self.preview_widget.show()
        
        if self.drag_state == 'none':
            self.update() 
            return
            
        if self.drag_state == 'playhead':
            self.update_playhead(x)
        elif self.drag_state == 'trim_l':
            self.trim_start_ms = max(0.0, min(ms, self.trim_end_ms - 1000))
            self.update()
        elif self.drag_state == 'trim_r':
            self.trim_end_ms = min(float(self.duration_ms), max(ms, self.trim_start_ms + 1000))
            self.update()
    
    def mouseReleaseEvent(self, event):
        from PySide6.QtCore import Qt
        if event.button() != Qt.LeftButton: return
        if self.drag_state == 'playhead':
            self.user_seek_lock_time = time.time() + 0.15 
            self.update_playhead(event.position().x())
            self.resume_requested.emit()
        elif self.drag_state in ['trim_l', 'trim_r']:
            self.trim_changed.emit(int(self.trim_start_ms), int(self.trim_end_ms))
        self.drag_state = 'none'

    def update_playhead(self, mouse_x):
        # Allow the mouse to move beyond the edges without hard clipping
        percentage = max(0.0, min(mouse_x / self.width(), 1.0))
        self.visual_ms = float(percentage * self.duration_ms)
        self.target_ms = self.visual_ms 
        self.seek_requested.emit(int(self.visual_ms))
        self.update()
        
    def force_jump(self, new_position_ms):
        if self.duration_ms <= 0: return
        self.visual_ms = max(0.0, min(float(new_position_ms), float(self.duration_ms)))
        self.target_ms = self.visual_ms 
        self.user_seek_lock_time = time.time() + 0.15 
        self.seek_requested.emit(int(self.visual_ms))
        self.update()

    def leaveEvent(self, event):
        from PySide6.QtCore import Qt
        self.is_hovering = False
        self.hover_x = -1.0
        if hasattr(self, 'preview_widget'): self.preview_widget.hide()
        if hasattr(self, 'text_tooltip'): self.text_tooltip.hide()
        self.setCursor(Qt.ArrowCursor) 
        self.update() 
        super().leaveEvent(event)

    # Explicitly intercept the wheel directly on the canvas so Qt doesn't eat up the scroll
    def wheelEvent(self, event):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QScrollArea
        # If Alt or Ctrl is pressed, we forcefully break the event out
        if (event.modifiers() & Qt.AltModifier) or (event.modifiers() & Qt.ControlModifier):
            parent = self.parentWidget()
            while parent:
                if isinstance(parent, QScrollArea):
                    parent.handle_zoom(event)
                    event.accept()
                    return
                parent = parent.parentWidget()
        event.ignore()


from PySide6.QtWidgets import QScrollArea, QSizePolicy

class CustomTimelineWidget(QScrollArea):
    pause_requested = Signal()        
    seek_requested = Signal(int)      
    resume_requested = Signal()
    trim_changed = Signal(int, int) 
    

    screenshot_requested = Signal(object)
    add_marker_requested = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtCore import Qt
        
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        self.canvas = TimelineCanvas(self)
        self.setWidget(self.canvas)
        self.setWidgetResizable(False) 
        
        self.canvas.pause_requested.connect(self.pause_requested.emit)
        self.canvas.seek_requested.connect(self.seek_requested.emit)
        self.canvas.resume_requested.connect(self.resume_requested.emit)
        self.canvas.trim_changed.connect(self.trim_changed.emit)
        
        # Connecting the Canvas to the Widget
        self.canvas.screenshot_requested.connect(self.screenshot_requested.emit)
        self.canvas.add_marker_requested.connect(self.add_marker_requested.emit)

        # The CONTAINER is rigidly and permanently set to 38px! No changes when zooming, nothing will creep up!        self.setFixedHeight(38)

        canvas_h = 52     # Canvas height/divisions (TimelineCanvas)
        top_gap = 0    # Gap from divisions to strip (your distance to scales)
        bar_h = 13 # Height of the scrollbar itself
        bottom_gap = 5    # Gap from the bottom of the strip to the button panel (your distance to the buttons)

        # We calculate the total height of the container automatically:
        total_h = canvas_h + top_gap + bar_h + bottom_gap
        #Add 6px to the overall height of the container to compensate for the padding-top.
        self.setFixedHeight(total_h + 6) 
        


        # Customize styles: the f-line will insert your gaps directly into the style sheet!
        self.setStyleSheet(f"""
            QScrollArea {{ 
                border: none; 
                background: #1e1e1e; 
                border-radius: 8px; 
                padding: 6px 12px 0px 12px; /* Margins: top (6px), right (12px), bottom (0), left (12px) */
            }}
            
            QScrollArea > QWidget#qt_scrollarea_viewport {{ background: transparent; }}
            QScrollArea > QWidget > QWidget {{ background: transparent; }}
            
            QScrollBar:horizontal {{
                height: {bar_h}px;
                background: #4e4e4e; 
                border-radius: 3px;
                /* margin: top (top_gap), right (4), bottom (bottom_gap), left (4) */
                margin: {top_gap}px 4px {bottom_gap}px 4px; 
            }}
            QScrollBar::handle:horizontal {{
                background: #9f8dba; 
                border-radius: 2px;
                min-width: 30px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: #cdbfe6; 
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
        """)
        self.zoom_level = 1.0
        self.update_scrollbar_visibility() 

    def update_scrollbar_visibility(self):
        """ Toggles the scrollbar ON/OFF, LEAVING the container height constant """
        from PySide6.QtCore import Qt
        if self.zoom_level <= 1.01:
            # There is no scrollbar - hide it at the root
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        else:
           # There is a scale: we draw a thin horizontal line without compressing the canvas
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        base_width = self.viewport().width()
        new_width = max(base_width, int(base_width * self.zoom_level))
        self.canvas.setMinimumWidth(new_width)
        self.canvas.resize(new_width, self.canvas.height())

    def handle_zoom(self, event):
        delta = event.angleDelta().y()
        if delta == 0: return
        zoom_factor = 1.15 if delta > 0 else 0.85 
        
        old_zoom = self.zoom_level
        
        # We're raising the limit from 100 to 3,000!
        new_zoom = max(1.0, min(old_zoom * zoom_factor, 3000.0))
        
        if new_zoom == old_zoom: return
        self.zoom_level = new_zoom

        # GLUING THE STICK TO THE CANVAS
        self.canvas.is_zooming = True
        if hasattr(self, '_zoom_timer'):
            self._zoom_timer.stop()
        else:
            from PySide6.QtCore import QTimer
            self._zoom_timer = QTimer(self)
            self._zoom_timer.setSingleShot(True)
            # 150ms after the wheel stops, lift the freeze.
            self._zoom_timer.timeout.connect(lambda: setattr(self.canvas, 'is_zooming', False))
        self._zoom_timer.start(150)

        # Treat the mouse globally
        viewport_pos = self.viewport().mapFromGlobal(event.globalPosition().toPoint())
        mouse_x = viewport_pos.x()
        
        h_bar = self.horizontalScrollBar()
        old_scroll = h_bar.value()
        
        target_x_canvas = old_scroll + mouse_x
        old_width = self.canvas.width()
        ratio = target_x_canvas / old_width if old_width > 0 else 0

        # Stretching the Canvas
        base_width = self.viewport().width()
        new_width = max(base_width, int(base_width * new_zoom))
        self.canvas.setMinimumWidth(new_width)
        self.canvas.resize(new_width, self.canvas.height())

        
        new_scroll = int((new_width * ratio) - mouse_x)
        h_bar.setValue(new_scroll)
        self.update_scrollbar_visibility()

    def wheelEvent(self, event):
        from PySide6.QtCore import Qt
        if (event.modifiers() & Qt.AltModifier) or (event.modifiers() & Qt.ControlModifier):
            self.handle_zoom(event)
            event.accept()
        else:
            # Scrolling without holding Alt/Ctrl moves the strip left/right!
            delta = event.angleDelta().y()
            if delta != 0:
                h_bar = self.horizontalScrollBar()
                old_val = h_bar.value()

                step = 40
                if delta < 0:
                    new_val = old_val + step
                else:
                    new_val = old_val - step
                h_bar.setValue(max(h_bar.minimum(), min(new_val, h_bar.maximum())))
                event.accept()
            else:
                super().wheelEvent(event)

    @property
    def is_trim_mode(self): return self.canvas.is_trim_mode
    @property
    def trim_start_ms(self): return self.canvas.trim_start_ms
    @property
    def trim_end_ms(self): return self.canvas.trim_end_ms
    @property
    def visual_ms(self): return self.canvas.visual_ms
    @property
    def thumb_dir(self): return getattr(self.canvas, 'thumb_dir', None)
    @thumb_dir.setter
    def thumb_dir(self, val): self.canvas.thumb_dir = val
    @property
    def current_video_path(self):
        return self.canvas.current_video_path

    @current_video_path.setter
    def current_video_path(self, val):
        # 1. Brutal Memory Purge
        if hasattr(self.canvas, 'sniper') and self.canvas.sniper:
            self.canvas.sniper.kill_worker()
            self.canvas.sniper.quit()
            self.canvas.sniper.wait()
            
            # 2. Resurrecting a completely fresh, blank sniper
            self.canvas.sniper = PreviewSniperWorker()
            self.canvas.sniper.preview_ready.connect(self.canvas.on_preview_ready)
            
        # 3. Only now are we introducing the new path.
        self.canvas.current_video_path = val

    def force_jump(self, ms): self.canvas.force_jump(ms)
    def set_duration(self, ms): self.canvas.set_duration(ms)
    def set_vlc_time(self, ms, is_p): self.canvas.set_vlc_time(ms, is_p)
    def enable_trim_mode(self): self.canvas.enable_trim_mode()
    def disable_trim_mode(self): self.canvas.disable_trim_mode()
    
from PySide6.QtWidgets import QLabel, QFrame, QVBoxLayout, QWidget
from PySide6.QtCore import Qt, QPoint

# --- FLOATING TIMELINE PREVIEW WIDGET ---
class ThumbnailPreviewWidget(QWidget):
    """ A floating tooltip-like widget that shows a video frame and time on hover. """
    def __init__(self, parent=None):
        super().__init__(parent)
        # Make the window a "ghost" (stays on top, no borders, doesn't steal focus)
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        # Stylish container frame
        self.frame = QFrame()
        self.frame.setStyleSheet("QFrame { background-color: #181818; border: 1px solid #333; border-radius: 6px; }")
        self.frame_layout = QVBoxLayout(self.frame)
        self.frame_layout.setContentsMargins(4, 4, 4, 4)
        self.frame_layout.setSpacing(4)

        # Thumbnail image placeholder
        self.img_label = QLabel("No Frame")
        self.img_label.setFixedSize(160, 90) # Perfect 16:9 ratio
        self.img_label.setStyleSheet("background-color: #000000; border-radius: 4px; color: #555;")
        self.img_label.setAlignment(Qt.AlignCenter)

        # Timecode label
        self.time_label = QLabel("00:00")
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setStyleSheet("background-color: #2d2d2d; border-radius: 4px; padding: 2px; color: white; font-weight: bold; font-size: 11px;")

        self.frame_layout.addWidget(self.img_label)
        self.frame_layout.addWidget(self.time_label)
        self.layout.addWidget(self.frame)
        self.hide()
        
    def update_info(self, time_str, is_in_trim, hover_ms, thumb_dir):
        """ Updates UI and instantly loads the pre-generated image. """
        self.time_label.setText(time_str)
        
        if is_in_trim:
            self.time_label.setStyleSheet("background-color: #2d2d2d; border-radius: 4px; padding: 2px; color: #ffcc00; font-weight: bold; font-size: 11px;")
        else:
            self.time_label.setStyleSheet("background-color: #2d2d2d; border-radius: 4px; padding: 2px; color: white; font-weight: bold; font-size: 11px;")

        # --- INSTANT IMAGE LOADING ---
        from PySide6.QtGui import QPixmap
        import os
        
        if thumb_dir and os.path.exists(thumb_dir):
            sec = int(hover_ms // 1000)
            # Math: 0-2s -> thumb_0001, 3-5s -> thumb_0002 (3 SECOND INTERVAL)
            index = (sec // 3) + 1 
            img_path = os.path.join(thumb_dir, f"thumb_{index:04d}.jpg")
            
            if os.path.exists(img_path):
                self.img_label.setPixmap(QPixmap(img_path))
                return
                
        # If still generating in the background...
        self.img_label.setPixmap(QPixmap())
        self.img_label.setText("Generating...")

    def set_image(self, img_path):
        """ Called when the sniper successfully extracts the frame. """
        from PySide6.QtGui import QPixmap
        self.img_label.setPixmap(QPixmap(img_path))

    def update_image_from_ram(self, pixmap):
        """ Instantly applies a generated QPixmap from the Sniper's RAM cache """
        if pixmap:
            self.img_label.setPixmap(pixmap)
        else:
            self.img_label.setPixmap(QPixmap())
            self.img_label.setText("Sniper Loading...")

from PySide6.QtCore import QObject, QEvent, Qt



  
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSlider, QLabel



from PySide6.QtCore import QObject, QEvent



    

if __name__ == "__main__":
    import sys
    import os
    import argparse
    import traceback
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtGui import QIcon
    from PySide6.QtCore import QTimer
    
    os.environ["QT_MEDIA_BACKEND"] = "windows"
    

    parser = argparse.ArgumentParser()
    parser.add_argument('--updated-from', type=str, default="")
    parser.add_argument('--backup-folder', type=str, default="")
    args, unknown = parser.parse_known_args()


    try:
        import ctypes
        myappid = f'steempeg.app.v{APP_VERSION_STR}' 
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except: pass

    app = QApplication(sys.argv)

    icon_path = get_resource_path("logo.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))


    try:
        window = SteempegApp()
        
        if getattr(window, 'ui', None) is None:
            QMessageBox.critical(None, "Interface Error", "Failed to load smpegui13.ui!")
            sys.exit(1)
            
        if os.path.exists(icon_path): 
            window.ui.setWindowIcon(QIcon(icon_path))
            
        # --- ADDING COLLAPSE AND EXPAND BUTTONS ---
        from PySide6.QtCore import Qt
        window.ui.setWindowFlags(window.ui.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)
        
    
        window.ui.showMaximized()
        
        if args.updated_from:
            QTimer.singleShot(1000, lambda: window.show_update_success(args.updated_from, args.backup_folder))
            
        sys.exit(app.exec())

    except Exception as e:
        # Now no mistake can hide =)))))))) =))))) dsfhnuijdfgbjiklgfvbjknlbfcvxjknml
        error_text = traceback.format_exc()
        print(error_text)
        try:
            import logging
            logging.critical("="*40)
            logging.critical("FATAL ERROR:")
            logging.critical(error_text)
            logging.critical("="*40)
        except:
            pass # If the logger has not yet been created
            
        QMessageBox.critical(None, "FATAL ERROR", f"APP ERROR:\n{error_text}")
def global_exception_handler(exc_type, exc_value, exc_traceback):
        import traceback
        error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        print(f"CRITICAL FATAL CRASH:\n{error_msg}")
        try:
            import logging
            logging.critical(f"UNCAUGHT FATAL ERROR:\n{error_msg}")
        except: pass
sys.excepthook = global_exception_handler
