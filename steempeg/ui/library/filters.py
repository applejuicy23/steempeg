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
    QSizePolicy,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.locale_time import parse_clip_datetime_text, qt_time_display_format
from steempeg.core.dash.health import ClipHealth
from steempeg.core.steam_paths import steam_id_from_clips_folder
from steempeg.ui.icon_assets import health_icon
from steempeg.ui.widgets import BlockCombo, FlowLayout

_CLIP_HEALTH_ROLE = Qt.UserRole + 2
_CLIP_CURED_ROLE = Qt.UserRole + 4


def _row_display_health_level(item) -> str:
    if item and item.data(_CLIP_CURED_ROLE):
        return ClipHealth.CURED.value
    return item.data(_CLIP_HEALTH_ROLE) or ClipHealth.HEALTHY.value


def _library_root_for_clip(clip_path: str, roots) -> str | None:
    """Longest matching library root for a clip folder path, or None."""
    if not clip_path or not roots:
        return None
    norm = os.path.normpath(clip_path)
    norm_key = os.path.normcase(norm)
    matches = []
    for root in roots:
        if not root:
            continue
        rn = os.path.normpath(root)
        rn_key = os.path.normcase(rn)
        if norm_key == rn_key or norm_key.startswith(rn_key + os.sep):
            matches.append(rn)
    return max(matches, key=len) if matches else None


def clip_folder_sort_key(clip_path: str, roots=None) -> tuple:
    """Stable, user-meaningful folder key for library sorting.

    Prefers the configured library root (same grouping as Folders filter pills).
    Falls back to the parent directory of the clip path. Uses ``normcase`` so
    Windows path case noise does not split groups. Second tuple element is the
    clip path itself for a deterministic order within a folder.
    """
    if not clip_path:
        return ("", "")
    norm = os.path.normpath(str(clip_path))
    root = _library_root_for_clip(norm, roots or [])
    folder = root if root else (os.path.dirname(norm) or norm)
    return (os.path.normcase(folder), os.path.normcase(norm))


def _folder_pill_label(path: str) -> str:
    sid = steam_id_from_clips_folder(path)
    base = os.path.basename(path.rstrip("\\/")) or path
    if sid:
        # Distinguish clips vs video (or nested) roots that share a Steam ID.
        return f"Steam {sid} · {base}"
    return base[:16] + "…" if len(base) > 18 else base


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
        
        # Classic single-column width (~29.1). Wide shells switch to a 3-column
        # arrangement via _relayout_sections — block internals stay unchanged.
        self.setFixedWidth(460)
        self._three_col = False
        self._last_packed_h = 0
        self._popup_avail_h = 0
        self._three_col_body_h = 0

        self.container = QFrame(self)
        self.container.setObjectName("MainFilterContainer")
        self.container.setStyleSheet("""
            QFrame#MainFilterContainer { background-color: #252525; border: 1px solid #3d3d3d; border-radius: 16px; }
        """)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.addWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

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
            # Don't vertically expand into the column floor — that squares off radius.
            capsule.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
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

        # Sections host: stack page (tall window) or 3 independent columns (squeezed).
        # Columns are separate VBoxes so a tall Games panel cannot stretch mid/right
        # rows the way QGridLayout rowspan does.
        self._sections_host = QWidget()
        self._sections_host.setObjectName("FilterSectionsHost")
        self._sections_host.setStyleSheet("background: transparent;")
        # Maximum vertical: never expand into empty space under the columns (the void).
        self._sections_host.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        sections_outer = QVBoxLayout(self._sections_host)
        sections_outer.setContentsMargins(0, 0, 0, 0)
        sections_outer.setSpacing(0)
        sections_outer.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._stack_page = QWidget()
        self._stack_page.setStyleSheet("background: transparent;")
        self._stack_lay = QVBoxLayout(self._stack_page)
        self._stack_lay.setContentsMargins(0, 0, 0, 0)
        self._stack_lay.setSpacing(8)
        self._stack_lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._cols_page = QWidget()
        self._cols_page.setStyleSheet("background: transparent;")
        self._cols_page.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        cols_row = QHBoxLayout(self._cols_page)
        cols_row.setContentsMargins(0, 0, 0, 0)
        cols_row.setSpacing(12)
        cols_row.setAlignment(Qt.AlignmentFlag.AlignTop)

        def _make_col():
            col = QWidget()
            col.setStyleSheet("background: transparent;")
            col.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            lay = QVBoxLayout(col)
            # Bottom inset so CategoryCapsule border-radius isn't clipped by the column floor.
            lay.setContentsMargins(0, 0, 0, 8)
            lay.setSpacing(12)
            lay.setAlignment(Qt.AlignmentFlag.AlignTop)
            return col, lay

        self._col_games, self._col_games_lay = _make_col()
        # Mid is a plain column like Games/right — QScrollArea was clipping Folders'
        # bottom border-radius even with padding.
        self._col_mid, self._col_mid_lay = _make_col()
        self._col_right, self._col_right_lay = _make_col()
        self._col_mid_inner = self._col_mid  # alias used by stretch height measure

        # Games / mid share space; right (Date/Time/Dur) gets a bit more so steppers fit.
        top = Qt.AlignmentFlag.AlignTop
        cols_row.addWidget(self._col_games, 4, top)
        cols_row.addWidget(self._col_mid, 4, top)
        cols_row.addWidget(self._col_right, 5, top)
        self._col_games.setMinimumWidth(200)
        self._col_mid.setMinimumWidth(200)
        self._col_right.setMinimumWidth(320)

        sections_outer.addWidget(self._stack_page)
        sections_outer.addWidget(self._cols_page)
        self._cols_page.hide()

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
        self._games_scroll.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._games_scroll.setMinimumHeight(104)
        self._games_capsule = create_category_capsule("🎮 Games:", self._games_scroll)

        # --- TYPE ---
        self.types_container = QWidget()
        self.types_layout = FlowLayout()
        self.types_container.setLayout(self.types_layout)
        self.types_container.setMouseTracking(True)
        self.types_container.installEventFilter(self)
        self._type_capsule = create_category_capsule("📂 Type:", self.types_container)

        # --- HEALTH (post-29.1; sits with Type/Date in column 2) ---
        self.health_container = QWidget()
        self.health_layout = FlowLayout()
        self.health_container.setLayout(self.health_layout)
        self.health_container.setMouseTracking(True)
        self.health_container.installEventFilter(self)
        self._health_capsule = create_category_capsule("💚 Health:", self.health_container)

        self._HEALTH_PILL_TEXT = {
            ClipHealth.HEALTHY: "Healthy",
            ClipHealth.DEGRADED: "Issues",
            ClipHealth.DEAD: "Dead",
            ClipHealth.CURED: "Cured",
        }
        for level in (ClipHealth.HEALTHY, ClipHealth.DEGRADED, ClipHealth.DEAD, ClipHealth.CURED):
            btn = QPushButton(f" {self._HEALTH_PILL_TEXT[level]}")
            btn.setIcon(health_icon(level, 14))
            btn.setIconSize(QSize(14, 14))
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._PILL_BTN_STYLE)
            btn.setProperty("health_level", level.value)
            btn.clicked.connect(self.update_live_count)
            if level == ClipHealth.CURED:
                btn.hide()
            self.health_layout.addWidget(btn)

        # --- FOLDERS (library roots — fills column 2 with Type/Health) ---
        self.folders_container = QWidget()
        self.folders_layout = FlowLayout()
        self.folders_container.setLayout(self.folders_layout)
        self.folders_container.setMouseTracking(True)
        self.folders_container.installEventFilter(self)
        self._folders_capsule = create_category_capsule("📁 Folders:", self.folders_container)
        self._folder_checked_memory = {}

        # --- 3. SMART INPUTS STYLE (Clean, small pills + Rounded Spinners) ---
        temp_dir = tempfile.gettempdir()
        up_path = os.path.join(temp_dir, "smpeg_up.png").replace('\\', '/')
        down_path = os.path.join(temp_dir, "smpeg_down.png").replace('\\', '/')

        pix = QPixmap(16, 16)

        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon([QPoint(3, 11), QPoint(8, 5), QPoint(13, 11)])
        p.end()
        pix.save(up_path, "PNG")

        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon([QPoint(3, 5), QPoint(8, 11), QPoint(13, 5)])
        p.end()
        pix.save(down_path, "PNG")

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

        def _bound_row_29(label_a: str, widget_a, label_b: str, widget_b) -> QWidget:
            """29.1-style horizontal From|To row — do not restack vertically."""
            host = QWidget()
            host.setStyleSheet("background: transparent;")
            row = QHBoxLayout(host)
            row.setContentsMargins(0, 0, 0, 4)
            row.setSpacing(6)
            lbl_a = QLabel(label_a)
            lbl_a.setStyleSheet("color: #888888; font-weight: bold;")
            lbl_b = QLabel(label_b)
            lbl_b.setStyleSheet("color: #888888; font-weight: bold;")
            for w in (widget_a, widget_b):
                w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                w.setMinimumWidth(108)
            row.addWidget(lbl_a, 0)
            row.addWidget(widget_a, 1)
            row.addSpacing(10)
            row.addWidget(lbl_b, 0)
            row.addWidget(widget_b, 1)
            return host

        # --- DATE ---
        self.input_min_date = QDateEdit()
        self.input_max_date = QDateEdit()
        for de in (self.input_min_date, self.input_max_date):
            de.setCalendarPopup(True)
            de.setStyleSheet(smart_input_style)
            de.setCursor(Qt.PointingHandCursor)
            de.setDateRange(QDate(2020, 1, 1), QDate(2050, 12, 31))
        self._date_capsule = create_category_capsule(
            "📅 Date:",
            _bound_row_29("📅 From:", self.input_min_date, "📅 To:", self.input_max_date),
        )

        # --- TIME OF CREATION ---
        self.input_min_time = QTimeEdit()
        self.input_max_time = QTimeEdit()
        for te in (self.input_min_time, self.input_max_time):
            te.setDisplayFormat(qt_time_display_format())
            te.setStyleSheet(smart_input_style)
            te.setCursor(Qt.PointingHandCursor)
        self._time_capsule = create_category_capsule(
            "⏰ Time of creation:",
            _bound_row_29("🕒 From:", self.input_min_time, "🕒 To:", self.input_max_time),
        )

        # --- DURATION ---
        self.input_min_dur = QTimeEdit()
        self.input_max_dur = QTimeEdit()
        for de in (self.input_min_dur, self.input_max_dur):
            de.setDisplayFormat("HH:mm:ss")
            de.setStyleSheet(smart_input_style)
            de.setCursor(Qt.PointingHandCursor)
        self._dur_capsule = create_category_capsule(
            "⏱ Duration:",
            _bound_row_29("⏱ Min:", self.input_min_dur, "⏱ Max:", self.input_max_dur),
        )

        self._place_filter_columns(three_col=False)
        layout.addWidget(self._sections_host)

        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 2, 0, 0)
        bottom_layout.setSpacing(8)
        
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
        self.btn_clear.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_clear.clicked.connect(self.clear_filters)

        self.btn_apply = QPushButton("Apply Filters (0)")
        self.btn_apply.setCursor(Qt.PointingHandCursor)
        self.btn_apply.setStyleSheet(unified_table_style)
        self.btn_apply.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_apply.clicked.connect(self.apply_filters)

        bottom_layout.addWidget(self.btn_clear, 1)
        bottom_layout.addWidget(self.btn_apply, 1)
        layout.addLayout(bottom_layout)

        self._outer_layout = main_layout
        self._inner_layout = layout
        self._bottom_layout = bottom_layout
        self._density = None

    def _filter_host_width(self) -> int:
        """Width of the window under the filter pill (Choose-a-Clip sheet or main)."""
        app = getattr(self, "app", None)
        pill = getattr(app, "btn_filter_pill", None) if app is not None else None
        if pill is not None:
            try:
                host = pill.window()
                if host is not None:
                    w = int(host.width() or 0)
                    if w > 0:
                        return w
            except RuntimeError:
                pass
        panel = getattr(getattr(app, "ui", None), "left_panel", None) if app is not None else None
        if panel is not None:
            try:
                return int(panel.width() or 0)
            except RuntimeError:
                pass
        return 0

    def _filter_host_height(self) -> int:
        app = getattr(self, "app", None)
        pill = getattr(app, "btn_filter_pill", None) if app is not None else None
        if pill is None:
            return 0
        try:
            host = pill.window()
            return int(host.height() or 0) if host is not None else 0
        except RuntimeError:
            return 0

    def _width_for_mode(self, three_col: bool, dense) -> int:
        host_w = self._filter_host_width()
        compact = bool(getattr(dense, "compact", False)) if dense is not None else False
        if three_col:
            # Stay inside the Choose-a-Clip / main host; small left spill is OK.
            if host_w <= 0:
                return 1000
            return min(max(host_w - 32, 900), min(1140, host_w + 80))
        if host_w <= 0:
            return 480 if compact else 460
        usable = max(360, host_w - 24)
        # Wider stack on compact/Deck sheets so pills wrap less and height drops.
        return min(usable, 640 if compact else 520)

    def _want_three_columns(self) -> bool:
        """
        After set_content_max_height, trust `_three_col` (stack vs protrude).
        Before first measure, stay on the classic stack so apply_density doesn't
        stretch 3-col chrome and lock a stub height on tall windows.
        """
        avail = int(getattr(self, "_popup_avail_h", 0) or 0)
        if avail >= 160:
            return bool(getattr(self, "_three_col", False))
        return False

    def _resolve_menu_width(self, dense) -> int:
        return self._width_for_mode(self._want_three_columns(), dense)

    def _clear_box(self, lay) -> None:
        if lay is None:
            return
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def _place_filter_columns(self, *, three_col: bool) -> None:
        """
        Squeezed: Games | Type+Health+Folders | Date+Time+Duration
        Tall:     one vertical stack (29.1 + Health + Folders).

        Mid/right columns pack to the top; Games only grows to match their height
        — never the other way around (that was the giant gap bug).
        """
        games = self._games_capsule
        type_c = self._type_capsule
        health = self._health_capsule
        folders = self._folders_capsule
        date = self._date_capsule
        time_c = self._time_capsule
        dur = self._dur_capsule

        self._three_col = bool(three_col)
        self._clear_box(self._stack_lay)
        self._clear_box(self._col_games_lay)
        self._clear_box(self._col_mid_lay)
        self._clear_box(self._col_right_lay)

        if three_col:
            self._col_games_lay.addWidget(games)
            self._col_mid_lay.addWidget(type_c)
            self._col_mid_lay.addWidget(health)
            self._col_mid_lay.addWidget(folders)
            self._col_right_lay.addWidget(date)
            self._col_right_lay.addWidget(time_c)
            self._col_right_lay.addWidget(dur)
            self._stack_page.hide()
            self._cols_page.show()
        else:
            self._clear_fixed_col_heights()
            for w in (games, type_c, health, folders, date, time_c, dur):
                self._stack_lay.addWidget(w)
            self._cols_page.hide()
            self._stack_page.show()

    def _clear_fixed_col_heights(self) -> None:
        for w in (
            getattr(self, "_col_games", None),
            getattr(self, "_col_mid", None),
            getattr(self, "_col_right", None),
            getattr(self, "_cols_page", None),
            getattr(self, "_stack_page", None),
            getattr(self, "_games_capsule", None),
            getattr(self, "_sections_host", None),
        ):
            if w is None:
                continue
            w.setMinimumHeight(0)
            w.setMaximumHeight(16777215)

    def _stretch_games_column(self) -> None:
        """Share one column floor; Games bottom aligns with Folders (mid) bottom."""
        if not getattr(self, "_three_col", False):
            return
        avail = int(getattr(self, "_popup_avail_h", 0) or 0)
        chrome = self._chrome_and_buttons_h()
        # Room under capsules so radius + pill AA aren't shaved by the column floor.
        radius_pad = 12
        for lay in (
            getattr(self, "_col_games_lay", None),
            getattr(self, "_col_mid_lay", None),
            getattr(self, "_col_right_lay", None),
        ):
            if lay is not None:
                lay.setContentsMargins(0, 0, 0, radius_pad)

        mid = getattr(self, "_col_mid", None) or getattr(self, "_col_mid_inner", None)
        mid_natural = max(
            1,
            int(mid.sizeHint().height()) if mid is not None else 0,
            int(mid.minimumSizeHint().height()) if mid is not None else 0,
        )
        right_natural = max(1, int(self._col_right.sizeHint().height()))
        # Never shorter than mid — Folders/SteamLibrary must stay fully visible.
        target = max(mid_natural, right_natural) + 4
        if avail >= 160:
            target = max(mid_natural + 4, min(target, max(mid_natural, avail - chrome)))

        games_floor = 108 if getattr(self, "_density", None) and getattr(self._density, "compact", False) else 124
        games_chrome = 12 + 12 + 22 + 8
        # Match Games capsule bottom to mid body (Folders), not extra empty under mid.
        mid_body = max(games_floor + games_chrome, mid_natural - radius_pad)
        games_body = max(games_floor, mid_body - games_chrome)
        self._games_scroll.setFixedHeight(games_body)

        self._col_games.setFixedHeight(target)
        self._col_mid.setFixedHeight(target)
        self._col_right.setFixedHeight(target)
        self._cols_page.setFixedHeight(target)
        host = getattr(self, "_sections_host", None)
        if host is not None:
            host.setFixedHeight(target)
        self._three_col_body_h = target

    def _tighten_three_col_chrome(self) -> None:
        """Pull content up and kill dead air under the buttons."""
        if not getattr(self, "_three_col", False):
            # Stack: tight chrome so Clear/Apply sit under Duration, not in a void.
            dense = getattr(self, "_density", None)
            compact = bool(getattr(dense, "compact", False)) if dense else False
            outer = 6 if compact else 8
            inner = 8 if compact else 12
            gap = 6 if compact else 8
            if getattr(self, "_outer_layout", None) is not None:
                self._outer_layout.setContentsMargins(outer, outer, outer, outer)
            if getattr(self, "_inner_layout", None) is not None:
                self._inner_layout.setContentsMargins(inner, inner, inner, inner)
                self._inner_layout.setSpacing(gap)
                self._inner_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            if getattr(self, "_bottom_layout", None) is not None:
                self._bottom_layout.setContentsMargins(0, 2, 0, 0)
            return
        if getattr(self, "_outer_layout", None) is not None:
            self._outer_layout.setContentsMargins(8, 6, 8, 6)
        if getattr(self, "_inner_layout", None) is not None:
            self._inner_layout.setContentsMargins(12, 8, 12, 8)
            self._inner_layout.setSpacing(8)
            self._inner_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        if getattr(self, "_bottom_layout", None) is not None:
            # Buttons sit right under the column floor.
            self._bottom_layout.setContentsMargins(0, 4, 0, 0)

    def _clear_popup_height_lock(self) -> None:
        """Undo setFixedHeight so the popup can grow again on remasure."""
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)

    def _chrome_and_buttons_h(self) -> int:
        outer = getattr(self, "_outer_layout", None) or self.layout()
        inner = getattr(self, "_inner_layout", None)
        bottom = getattr(self, "_bottom_layout", None)
        h = 0
        if outer is not None:
            m = outer.contentsMargins()
            h += m.top() + m.bottom()
        if inner is not None:
            m = inner.contentsMargins()
            h += m.top() + m.bottom() + max(0, int(inner.spacing()))
        if bottom is not None:
            m = bottom.contentsMargins()
            h += m.top() + m.bottom()
        btn_h = 36
        for name in ("btn_clear", "btn_apply"):
            btn = getattr(self, name, None)
            if btn is not None:
                btn_h = max(btn_h, int(btn.sizeHint().height()))
        return h + btn_h

    def _stack_sections_h(self, games_h: int) -> int:
        """Classic stack body height for mode decision / stack pack."""
        stack = getattr(self, "_stack_lay", None)
        if stack is None:
            return games_h + 280
        total = 0
        visible = 0
        games_cap = getattr(self, "_games_capsule", None)
        for i in range(stack.count()):
            item = stack.itemAt(i)
            w = item.widget() if item is not None else None
            if w is None or w.isHidden():
                continue
            if w is games_cap:
                # Title + margins around the games scroll — don't trust inflated sizeHints.
                chrome = 12 + 12 + 22 + 8
                total += games_h + chrome
            else:
                total += max(
                    int(w.minimumHeight() or 0),
                    int(w.minimumSizeHint().height()),
                    int(w.sizeHint().height()),
                )
            visible += 1
        if visible > 1:
            total += int(stack.spacing()) * (visible - 1)
        return total

    def _three_col_sections_h(self) -> int:
        """Tight 3-col body — cols_page fixed floor only (no stretch void)."""
        cols = getattr(self, "_cols_page", None)
        if cols is None:
            return 280
        return max(
            int(cols.minimumHeight() or 0),
            int(cols.height() or 0) if cols.minimumHeight() > 0 else 0,
            int(cols.sizeHint().height()),
            200,
        )

    def _content_height_hint(self) -> int:
        """Popup height from current mode body + chrome. No prev/avail inflation."""
        gs = getattr(self, "_games_scroll", None)
        games_h = 0
        if gs is not None:
            games_h = max(int(gs.height() or 0), int(gs.minimumHeight() or 0))
        body = (
            self._three_col_sections_h()
            if getattr(self, "_three_col", False)
            else self._stack_sections_h(games_h)
        )
        return max(120, body + self._chrome_and_buttons_h())

    def sizeHint(self):
        w = self.width() if self.width() > 0 else int(self.minimumWidth() or 460)
        return QSize(max(w, 1), self._content_height_hint())

    def minimumSizeHint(self):
        return self.sizeHint()

    def _pack_popup_height(self) -> None:
        """Snap popup height. 3-col is deterministic; stack shrink-wraps to buttons."""
        avail = int(getattr(self, "_popup_avail_h", 0) or 0)

        if getattr(self, "_three_col", False):
            # No probe/resize dance — that made Clear/Apply drift across opens.
            body = int(getattr(self, "_three_col_body_h", 0) or 0)
            if body <= 0:
                body = self._three_col_sections_h()
            host = getattr(self, "_sections_host", None)
            if host is not None:
                host.setFixedHeight(body)
            cols = getattr(self, "_cols_page", None)
            if cols is not None:
                cols.setFixedHeight(body)
            hint_h = body + self._chrome_and_buttons_h()
            hint_h = max(120, int(hint_h))
            if avail >= 160:
                hint_h = min(hint_h, avail)
            self.setFixedHeight(hint_h)
            self._last_packed_h = hint_h
            return

        self._clear_popup_height_lock()
        host = getattr(self, "_sections_host", None)
        if host is not None:
            host.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            host.setMinimumHeight(0)
            host.setMaximumHeight(16777215)

        lay = self.layout()
        if lay is not None:
            lay.activate()
        probe = max(self._content_height_hint(), 480)
        if avail >= 160:
            probe = min(probe, avail)
        self.resize(max(self.width(), 1), probe)

        btn = getattr(self, "btn_apply", None) or getattr(self, "btn_clear", None)
        if btn is not None and btn.height() > 0:
            bottom_y = btn.mapTo(self, QPoint(0, btn.height())).y()
            outer = getattr(self, "_outer_layout", None)
            pad = outer.contentsMargins().bottom() if outer is not None else 8
            hint_h = bottom_y + pad
        else:
            hint_h = probe

        hint_h = max(120, int(hint_h))
        if avail >= 160:
            hint_h = min(hint_h, avail)
        self.setFixedHeight(hint_h)
        self._last_packed_h = hint_h

    def _apply_height_floor(self) -> None:
        """Keep FixedHeight; only clamp if content somehow exceeds avail."""
        avail = int(getattr(self, "_popup_avail_h", 0) or 0)
        if avail < 160:
            return
        if self.height() > avail:
            self.setFixedHeight(avail)
            self._last_packed_h = avail

    def _relayout_sections(self) -> None:
        dense = getattr(self, "_density", None)
        three = self._want_three_columns()
        if dense is not None:
            target_w = self._width_for_mode(three, dense)
            if self.width() != target_w:
                self.setFixedWidth(target_w)
        self._place_filter_columns(three_col=three)
        self._tighten_three_col_chrome()
        if three:
            self._stretch_games_column()
        # Height is owned by set_content_max_height.

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
        width = self._resolve_menu_width(dense)
        self.setFixedWidth(width)

        font = 11 if compact else 13
        pad_v = 2 if compact else 4
        pad_h = 8 if compact else 12
        min_h = 18 if compact else 24
        radius = 8 if compact else 10
        border = 1 if compact else 2
        outer_m = 6 if compact else 8
        inner_m = 8 if compact else 12
        gap = 6 if compact else 8
        cap_m = 8 if compact else 12
        title_font = 11 if compact else 13
        pill_r = 10 if compact else 14

        if getattr(self, "_outer_layout", None) is not None:
            self._outer_layout.setContentsMargins(outer_m, outer_m, outer_m, outer_m)
        if getattr(self, "_inner_layout", None) is not None:
            self._inner_layout.setContentsMargins(inner_m, inner_m, inner_m, inner_m)
            self._inner_layout.setSpacing(gap)
        if getattr(self, "_bottom_layout", None) is not None:
            self._bottom_layout.setContentsMargins(0, 2, 0, 0)

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
                getattr(self, "folders_container", None),
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
        from steempeg.ui.widgets.combo_chrome import (
            apply_dark_combo_popup,
            combo_popup_item_rules,
        )

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
            apply_dark_combo_popup(combo, dense=dense)

        dt_style = self._date_time_input_style_for(dense)
        if dt_style:
            cap_lbl = f"color: #888888; font-weight: bold; font-size: {10 if compact else 12}px;"
            for w in self.findChildren(QDateEdit):
                w.setStyleSheet(dt_style)
                w.setMaximumWidth(16777215)
            for w in self.findChildren(QTimeEdit):
                w.setStyleSheet(dt_style)
                w.setMaximumWidth(16777215)
            for lbl in self.findChildren(QLabel):
                ss = lbl.styleSheet() or ""
                if "#888888" in ss and "font-weight: bold" in ss:
                    lbl.setStyleSheet(cap_lbl)

        games_min = 92 if compact else 104
        self._games_scroll.setMinimumHeight(games_min)
        self._relayout_sections()

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

    def set_content_max_height(self, max_px: int, *, relayout: bool = True) -> None:
        """Size Games + pick stack vs 3-col.

        Full / normal shells keep the classic vertical stack (29.1 look).
        3-col only when vertical room under the filter pill is clearly tight.
        """
        self._popup_avail_h = max(160, int(max_px))
        dense = getattr(self, "_density", None)
        host_w = self._filter_host_width()
        games_floor = 108 if dense is not None and getattr(dense, "compact", False) else 124
        inset = 64 if dense is not None and getattr(dense, "compact", False) else 84
        avail = self._popup_avail_h

        self.setUpdatesEnabled(False)
        try:
            self._clear_popup_height_lock()

            if relayout:
                # Measure classic stack width for games wrap height.
                self._place_filter_columns(three_col=False)
                self._tighten_three_col_chrome()
                target_w = self._width_for_mode(False, dense)
                self.setFixedWidth(target_w)
                width = max(120, target_w - inset)
                content = self.games_layout.heightForWidth(width) + 4
                chrome = self._chrome_and_buttons_h()
                self._games_scroll.setFixedHeight(games_floor)
                non_games = max(80, self._stack_sections_h(games_floor) - games_floor)
                # Modest games band for fit math — not "half the shell".
                stack_games_h = max(games_floor, min(content, 220))
                stack_h = chrome + non_games + stack_games_h

                # If the classic stack would stick past the floor, go wide (3-col).
                # Do NOT skip that just because avail/host look "tall" — short
                # Choose-a-Clip / Deck shells still overflow in one column.
                can_three = host_w <= 0 or host_w >= 780
                stack_fits = stack_h <= avail - 8
                three = bool(can_three and not stack_fits)

                if three:
                    self._place_filter_columns(three_col=True)
                    self.setFixedWidth(self._width_for_mode(True, dense))
                    self._tighten_three_col_chrome()
                    self._stretch_games_column()
                else:
                    self._place_filter_columns(three_col=False)
                    self._tighten_three_col_chrome()
                    self.setFixedWidth(target_w)
                    # Games = content height only. Never inflate to fill avail
                    # (that opened the void under the Games: title).
                    room = max(games_floor, avail - chrome - non_games)
                    fit_games = max(games_floor, min(content, room))
                    self._games_scroll.setFixedHeight(fit_games)
            elif getattr(self, "_three_col", False):
                self._stretch_games_column()
            else:
                # Re-pack only: keep mode, refit games to new avail.
                width = max(120, self.width() - inset)
                content = self.games_layout.heightForWidth(width) + 4
                chrome = self._chrome_and_buttons_h()
                non_games = max(80, self._stack_sections_h(games_floor) - games_floor)
                room = max(games_floor, avail - chrome - non_games)
                fit_games = max(games_floor, min(content, room))
                self._games_scroll.setFixedHeight(fit_games)

            self._pack_popup_height()
            self._apply_height_floor()
        finally:
            self.setUpdatesEnabled(True)

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
        folders_c = getattr(self, 'folders_container', None)
        pill_hosts = (games_c, types_c, health_c, folders_c)
        if source in pill_hosts and source is not None and et in self._MOUSE_EVENTS:
            if source is games_c:
                layout = self.games_layout
            elif source is types_c:
                layout = self.types_layout
            elif source is health_c:
                layout = self.health_layout
            else:
                layout = self.folders_layout
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
                    elif layout is self.folders_layout:
                        self._sync_folder_memory()
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
                    elif self._drag_layout is self.folders_layout:
                        self._sync_folder_memory()
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
        txt = (text or "").strip()
        if not txt or txt in {"--:--", "—", "-", "Unknown"}:
            return 0
        h = int(re.search(r"(\d+)h", txt).group(1)) if "h" in txt else 0
        m = int(re.search(r"(\d+)m", txt).group(1)) if "m" in txt else 0
        s = int(re.search(r"(\d+)s", txt).group(1)) if "s" in txt else 0
        if h or m or s:
            return h * 3600 + m * 60 + s
        # Fallback for MM:SS / H:MM:SS cells that never used the h/m/s labels.
        clock = re.fullmatch(r"(\d+):([0-5]\d)(?::([0-5]\d))?", txt)
        if not clock:
            return 0
        parts = [int(p) for p in clock.groups() if p is not None]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        return parts[0] * 3600 + parts[1] * 60 + parts[2]

    def _get_checked_health_levels(self):
        # Use isHidden() (local hide), not isVisible() (needs ancestors shown).
        # gather_statistics → update_live_count runs before the popup is shown;
        # isVisible() was False for every Health pill → honest 0 with purple pills.
        levels = []
        for i in range(self.health_layout.count()):
            w = self.health_layout.itemAt(i).widget()
            if w and not w.isHidden() and w.isChecked():
                levels.append(w.property("health_level"))
        return levels

    def _library_has_cured_clips(self) -> bool:
        app = getattr(self, "app", None)
        table = getattr(getattr(app, "ui", None), "table_clips", None)
        if table is None:
            return False
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item and item.data(_CLIP_CURED_ROLE):
                return True
        return False

    def _sync_cured_health_pill(self) -> None:
        """Show the Cured chip only when at least one library row is cured."""
        has_cured = self._library_has_cured_clips()
        for i in range(self.health_layout.count()):
            w = self.health_layout.itemAt(i).widget()
            if not w or w.property("health_level") != ClipHealth.CURED.value:
                continue
            w.setVisible(has_cured)
            if not has_cured:
                w.setChecked(True)
            break

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
            btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(self._on_type_toggled)
            self.types_layout.addWidget(btn)

    def _sync_folder_memory(self):
        for i in range(self.folders_layout.count()):
            w = self.folders_layout.itemAt(i).widget()
            if w:
                self._folder_checked_memory[w.property("raw_name")] = w.isChecked()

    def _rebuild_folder_buttons(self, available_roots, saved_state=None):
        self._sync_folder_memory()
        while self.folders_layout.count():
            item = self.folders_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        roots = sorted(available_roots)
        if (
            saved_state
            and saved_state.get("active")
            and saved_state.get("folders")
        ):
            # normcase: Windows path case must not drop saved folder pills on reopen.
            saved = {
                os.path.normcase(os.path.normpath(p))
                for p in saved_state["folders"]
                if p
            }
            for root in roots:
                self._folder_checked_memory[root] = os.path.normcase(root) in saved

        for root in roots:
            label = _folder_pill_label(root)
            btn = QPushButton(f" {label}")
            btn.setCheckable(True)
            checked = self._folder_checked_memory.get(root, True)
            btn.setChecked(checked)
            self._folder_checked_memory[root] = checked
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._PILL_BTN_STYLE)
            btn.setProperty("raw_name", root)
            btn.setToolTip(root)
            btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(self._on_folder_toggled)
            self.folders_layout.addWidget(btn)

    def _configured_library_roots(self):
        roots = getattr(getattr(self, "app", None), "clips_folders", None) or []
        return [os.path.normpath(p) for p in roots if p]

    def _roots_present_in_table(self):
        """Configured library roots offered in the Folders filter pills."""
        return set(self._configured_library_roots())

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
        self.input_min_time.setTime(QTime(0, 0, 0))
        self.input_max_time.setTime(QTime(23, 59, 59))
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

    def _on_folder_toggled(self):
        if getattr(self, '_is_gathering', False):
            return
        self._sync_folder_memory()
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
        for name, icon in unique_games.items():
            short_name = name[:14] + '...' if len(name) > 14 else name
            btn = QPushButton(icon, f" {short_name}")
            btn.setCheckable(True)
            if saved_state and saved_state.get('active') and saved_state.get('games'):
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
        if saved_state and saved_state.get('active'):
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
            if saved_state and saved_state.get('active') and saved_state.get('health'):
                w.setChecked(level in saved_state['health'])
            else:
                w.setChecked(True)

        self._sync_cured_health_pill()

        self._rebuild_folder_buttons(self._roots_present_in_table(), saved_state)

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

        self._sync_cured_health_pill()

        self._folder_checked_memory = {r: True for r in self._roots_present_in_table()}
        self._rebuild_folder_buttons(self._roots_present_in_table())

        min_dt = full_stats['min_dt'] or QDateTime.currentDateTime().addMonths(-1)
        max_dt = full_stats['max_dt'] or QDateTime.currentDateTime()
        self.actual_min_dt = min_dt
        self.actual_max_dt = max_dt
        self.actual_min_sec = full_stats['min_sec']
        self.actual_max_sec = full_stats['max_sec']

        self.input_min_date.setDate(min_dt.date())
        self.input_max_date.setDate(max_dt.date())
        self.input_min_time.setTime(QTime(0, 0, 0))
        self.input_max_time.setTime(QTime(23, 59, 59))
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
        total = table.rowCount()

        sel_games = self._get_checked_names(self.games_layout)
        sel_types = self._get_checked_names(self.types_layout)
        sel_health = self._get_checked_health_levels()
        sel_folders = self._get_checked_names(self.folders_layout)
        roots = self._configured_library_roots()
        sel_folder_keys = {
            os.path.normcase(os.path.normpath(p)) for p in sel_folders if p
        }

        # Mid-rebuild (no pills yet) → keep the full total, not a flash of 0.
        building = (
            self.games_layout.count() == 0
            or self.types_layout.count() == 0
            or self.health_layout.count() == 0
        )
        if building:
            self.btn_apply.setText(f"Apply Filters ({total})")
            return

        # Intentional empty category (incl. all Folders off) → honest 0.
        # Do NOT substitute the library total — that looked like the filter
        # "forgot" a pending Folders selection (Apply Filters (258)).
        if not sel_games or not sel_types or not sel_health:
            self.btn_apply.setText("Apply Filters (0)")
            return
        if self.folders_layout.count() > 0 and not sel_folder_keys:
            self.btn_apply.setText("Apply Filters (0)")
            return

        min_date, max_date = self.input_min_date.date(), self.input_max_date.date()
        min_time = self._qtime_to_sec(self.input_min_time.time())
        max_time = self._qtime_to_sec(self.input_max_time.time())
        min_dur, max_dur = self._resolved_duration_bounds()
        skip_duration = max_dur <= 0 and min_dur <= 0

        count = 0
        for row in range(total):
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
            if show and sel_folder_keys and r_g:
                clip_path = r_g.data(Qt.UserRole) or ""
                root = _library_root_for_clip(clip_path, roots)
                if root is None or os.path.normcase(root) not in sel_folder_keys:
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

            if show and r_dur and not skip_duration:
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
        selected_folders = self._get_checked_names(self.folders_layout)
        roots = self._configured_library_roots()
        folder_filter_on = bool(selected_folders) or self.folders_layout.count() == 0

        filter_active = bool(
            selected_games and selected_types and selected_health and folder_filter_on
        )

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
            saved['folders'] = selected_folders
        else:
            saved['games'] = []
        self.app.saved_filter_state = saved

        visible_count = 0
        if not filter_active:
            # No games/types/health/folders selected → treat as "show everything".
            for row in range(table.rowCount()):
                table.setRowHidden(row, False)
            visible_count = table.rowCount()
        else:
            min_date = self.input_min_date.date()
            max_date = self.input_max_date.date()
            min_time = self._qtime_to_sec(self.input_min_time.time())
            max_time = self._qtime_to_sec(self.input_max_time.time())
            min_dur = min_dur_sec
            max_dur = max_dur_sec
            skip_duration = max_dur <= 0 and min_dur <= 0

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
                if show and selected_folders and item_game:
                    clip_path = item_game.data(Qt.UserRole) or ""
                    root = _library_root_for_clip(clip_path, roots)
                    if root is None or root not in selected_folders:
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

                if show and item_dur and not skip_duration:
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
        # Keep the library header • N Clips on the filtered size (not rowCount).
        if hasattr(self.app, '_update_library_count_label'):
            self.app._update_library_count_label()