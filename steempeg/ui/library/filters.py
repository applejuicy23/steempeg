"""Filter popup for the library: a date/time range picker plus game and type filters.

DateGroup and TimeGroup are small composite pickers built from BlockCombo; FilterMenu
is the popup itself. It receives the owning application via gather_statistics(app_window)
rather than importing it, so this module stays free of any back-reference to the app.
"""
import os
import re
import tempfile
from datetime import datetime

from PySide6.QtCore import Qt, QDate, QDateTime, QPoint, QTime
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from steempeg.ui.widgets import BlockCombo, FlowLayout


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