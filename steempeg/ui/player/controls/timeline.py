"""The seekable timeline: zoomable canvas, scroll wrapper and hover preview.

TimelineCanvas is the inner widget that draws the playhead, trim handles, chapter
and event markers and reacts to clicks and drags, emitting seek/trim/marker signals.
CustomTimelineWidget wraps it in a horizontally scrolling, zoomable QScrollArea.
ThumbnailPreviewWidget is the floating thumbnail shown while hovering the timeline,
fed by PreviewSniperWorker.
"""
import json
import os
import re
import logging
import time

import PySide6.QtWidgets as qtw
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.paths import get_resource_path
from steempeg.ui.player.thumbnails import PreviewSniperWorker
from steempeg.core.steam_screenshots import timeline_json_start_utc
from steempeg.services.steam_markers import MarkerIconStore, app_id_from_clip_paths


class TimelineCanvas(QWidget):
    """ The inner canvas of the timeline (the one that stretches when you zoom) """
    _RULER_GAP = 4
    _MAJOR_TICK_H = 10      # longer major ticks (was 8)
    _MINOR_TICK_H = 4
    _RULER_FONT_PT = 8
    _CANVAS_H = 58

    pause_requested = Signal()        
    seek_requested = Signal(int)      
    resume_requested = Signal()
    trim_changed = Signal(int, int) 
    
    screenshot_requested = Signal(float) 
    add_marker_requested = Signal(float)
    open_steam_screenshot_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(self._CANVAS_H)
        self.duration_ms = 0
        self.setMouseTracking(True)
        
        if 'ThumbnailPreviewWidget' in globals():
            self.preview_widget = ThumbnailPreviewWidget()

        self.visual_ms = 0.0  
        self.target_ms = 0.0  
        self.vlc_last_update_time = time.time()
        
        self.is_playing = False
        # Current mpv playback rate. The 60fps interpolation advances the playhead by
        # wall-clock time, so it must be scaled by this or it races ahead at 1x and gets
        # yanked back (visible jitter when zoomed in, especially at 0.1x).
        self.playback_speed = 1.0
        self.user_seek_lock_time = 0 
        
        self.is_trim_mode = False
        self.trim_start_ms = 0.0
        self.trim_end_ms = 0.0
        
        self.drag_state = 'none'
        self.last_frame_time = time.time()
        
        # 60 FPS Engine
        self.fps_timer = QTimer(self)
        self.fps_timer.timeout.connect(self.process_60fps_frame)
        self.fps_timer.start(16) 
        
        # Colors
        self.track_color = QColor(255, 255, 255, 40)
        self.fill_color = QColor("#b29ae7")
        self.handle_color = QColor(255, 255, 255)
        self.trim_body_color = QColor(255, 204, 0, 80) 
        self.trim_handle_color = QColor(255, 204, 0) 

        
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
        self._thumb_dir_media_path = ""
        self._batch_thumbs_busy = False
        if 'PreviewSniperWorker' in globals():
            self.sniper = PreviewSniperWorker()
            self.sniper.preview_ready.connect(self.on_preview_ready)
            
            self.sniper_timer = QTimer(self)
            self.sniper_timer.setSingleShot(True)
            self.sniper_timer.timeout.connect(self.trigger_sniper)
        self.pending_sec = -1
        self._hover_preview_bucket = -1

        # LABELS AND ICONS CS2
        self.markers = []
        self.mode_segments = []
        self.clip_ranges = []
        self.hovered_marker = None
        self.cached_pixmaps = {}
        self.current_app_id = None
        self.marker_store = MarkerIconStore()
        
        # NEW FLOATING TOOLTIP (Will reside beneath the scrollbar)
        self.text_tooltip = QLabel()
        self.text_tooltip.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.text_tooltip.setAttribute(Qt.WA_ShowWithoutActivating)
        self.text_tooltip.setStyleSheet("QLabel { background-color: #181818; color: white; border: 1px solid #444; border-radius: 4px; padding: 6px 10px; font-family: 'Segoe UI'; font-size: 12px; }")
        self.text_tooltip.hide()

        self._ruler_font = QFont("Segoe UI Semibold", self._RULER_FONT_PT)
        
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


    def load_timeline_json(self, json_path, offset_ms=0, clip_path=None):
        """ Reads JSON, adjusts chunk times, and populates the self.markers list. """
        
        self.current_json_path = json_path  
        self.current_offset_ms = offset_ms
        self.current_clip_path = clip_path
        self.current_json_start_utc = timeline_json_start_utc(json_path)
        self.current_app_id = app_id_from_clip_paths(json_path, clip_path)
        
        self.markers.clear()
        self.mode_segments = []
        self.clip_ranges = []
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
                    'raw_time_ms': raw_time,
                    'icon': entry.get('icon', ''),
                    'icon_key': icon_key,
                    'is_round': is_round,
                    'title': title,
                    'desc': desc
                })

            # --- Gamemode segments: menu/lobby/loading = hatching on the strip ---
            # Offset-aware: entries before the clip start only set the mode the clip OPENS in,
            # instead of collapsing to 0 (which smeared 'loading' across the whole gameplay).
            raw_gm = sorted(
                (int(e.get('time', 0)), int(e.get('mode', 0)))
                for e in entries if e.get('type') == 'gamemode'
            )
            start_mode = 0
            gm = []
            for raw_t, m in raw_gm:
                t = raw_t - offset_ms
                if t <= 0:
                    start_mode = m          # last mode active before the clip begins
                else:
                    gm.append((t, m))
            gm = [(0, start_mode)] + gm     # the clip opens in start_mode
            for i, (t, m) in enumerate(gm):
                end = gm[i + 1][0] if i + 1 < len(gm) else 10**12
                if end > t:
                    self.mode_segments.append((t, end, m))

            # --- Featured clip moments (possible_clip>=3): use each event's own duration ---
            CLIP_LEAD = 2000  # clip starts slightly before the event; tune to match Steam
            feat = []
            for ev in entries:
                if ev.get('type') == 'event' and int(ev.get('possible_clip', 0) or 0) >= 3:
                    t = max(0, int(ev.get('time', 0)) - offset_ms - CLIP_LEAD)
                    dur = int(ev.get('duration', 0) or 0)
                    if dur > 0:
                        feat.append((t, t + dur))
            feat.sort()
            for a, b in feat:
                if self.clip_ranges and a <= self.clip_ranges[-1][1]:
                    self.clip_ranges[-1] = (self.clip_ranges[-1][0], max(self.clip_ranges[-1][1], b))
                else:
                    self.clip_ranges.append((a, b))

            self.update()
        except Exception as e:
            print(f"Error loading JSON: {e}")

    def parse_event_to_icon(self, type_, title, desc):
        """ Smart detector: understands who killed whom and with what """
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

    def _legacy_icon_pixmap(self, icon_key, is_round):
        """ Gets an icon or GLUES the round numbers (RETINA 2X RESOLUTION) """
        
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
    def get_icon_pixmap(self, marker):
        """ Иконка метки: сначала реальный markers.svg, затем бандл-ассеты как фолбэк. """
        icon = marker.get('icon', '')
        app_id = self.current_app_id
        if icon and app_id:
            pix = self.marker_store.get_icon(app_id, icon, 36)
            if pix is not None:
                return pix
        #2. Fallback: bundle assets / gluing numbers / steam_ (the old CS2 way)
        return self._legacy_icon_pixmap(marker['icon_key'], marker['is_round'])
    def on_preview_ready(self, sec, pixmap):
        if self.duration_ms <= 0:
            return
        if getattr(self, 'sniper', None) and not self._sniper_path_matches():
            return
        if not getattr(self, 'is_hovering', False):
            return
        hover_ms = max(0.0, min(self.x_to_ms(self.hover_x), float(self.duration_ms)))
        current_target_sec = round((hover_ms // 1000) / 3.0) * 3
        if int(sec) != int(current_target_sec):
            return
        # Disk thumbs are authoritative for 3s buckets; sniper must not overwrite them.
        thumb_dir = getattr(self, 'thumb_dir', None)
        if thumb_dir and os.path.exists(thumb_dir):
            index = (int(current_target_sec) // 3) + 1
            if os.path.exists(os.path.join(thumb_dir, f"thumb_{index:04d}.jpg")):
                return
        if hasattr(self, 'preview_widget') and self.preview_widget.isVisible():
            self.preview_widget.update_image_from_ram(pixmap)

    def _norm_media_path(self, path) -> str:
        if not path:
            return ""
        return os.path.normcase(os.path.normpath(str(path))).replace("\\", "/")

    def _sniper_path_matches(self) -> bool:
        if not hasattr(self, 'sniper') or not self.current_video_path:
            return False
        return self._norm_media_path(self.sniper.video_path) == self._norm_media_path(self.current_video_path)

    def _thumb_dir_is_valid(self):
        thumb_dir = getattr(self, 'thumb_dir', None)
        if not thumb_dir or not os.path.exists(thumb_dir):
            return False
        src = getattr(self, '_thumb_dir_media_path', '')
        return bool(src) and self._norm_media_path(src) == self._norm_media_path(self.current_video_path)

    def trigger_sniper(self):
        if hasattr(self, 'sniper') and self.current_video_path and self.pending_sec >= 0:
            self.sniper.request_frame(self.current_video_path, self.pending_sec)

    def _trim_handle_at(self, x, y):
        """Return 'trim_l', 'trim_r', or None. Vertical grab zone matches paint + hover cursor."""
        if not self.is_trim_mode:
            return None
        track_y, track_height = 28.0, 12.0
        hit_tolerance = 10.0
        vertical_pad = 10.0
        if y < track_y - vertical_pad or y > track_y + track_height + vertical_pad:
            return None
        start_x = self.ms_to_x(self.trim_start_ms)
        end_x = self.ms_to_x(self.trim_end_ms)
        if abs(x - start_x) <= hit_tolerance:
            return 'trim_l'
        if abs(x - end_x) <= hit_tolerance:
            return 'trim_r'
        return None

    def set_duration(self, duration_ms):
        self.duration_ms = max(0, int(duration_ms))

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
                self.visual_ms += delta_ms * self.playback_speed
                
            self.visual_ms = max(0.0, min(self.visual_ms, float(self.duration_ms)))
            self.update() # Rendering the frame: the canvas stretches, but the stick lives on!
            return

        # --- STANDARD ENGINE LOGIC (When zoom is finished) ---
        if self.is_playing:
            self.visual_ms += delta_ms * self.playback_speed
            drift = self.target_ms - self.visual_ms
            if abs(drift) > 1000: self.visual_ms = self.target_ms 
            else: self.visual_ms += drift * 0.1 
        else:
            self.visual_ms += (self.target_ms - self.visual_ms) * 0.3

        self.visual_ms = max(0.0, min(self.visual_ms, float(self.duration_ms)))
        self.update()
        
    def paintEvent(self, event):
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        width = float(self.width())
        pad = 12.0
        usable_w = width - (pad * 2)

        painter.fillRect(self.rect(), QColor("#1e1e1e"))
        
        track_height = 12.0 
        track_y = 28.0

        painter.fillRect(QRectF(pad, track_y, usable_w, track_height), self.track_color)

        # Disabled / no-clip state: hatch the whole track so it clearly reads as "locked"
        # (and so stale game-mode segments from a previous clip can't bleed across the bar).
        if not self.isEnabled() or self.duration_ms <= 1:
            track_rect = QRectF(pad, track_y, usable_w, track_height)
            painter.save()
            painter.setClipRect(track_rect)
            painter.setPen(QPen(QColor(255, 255, 255, 70), 2))
            step = 7
            xx = int(pad) - int(track_height)
            while xx < int(pad + usable_w):
                painter.drawLine(xx, int(track_y + track_height), xx + int(track_height), int(track_y))
                xx += step
            painter.restore()
            return

        if self.duration_ms <= 0: return
        
        fill_x_end = self.ms_to_x(self.visual_ms)
        painter.fillRect(QRectF(pad, track_y, fill_x_end - pad, track_height), self.fill_color)
        
        if self.is_trim_mode:
            start_x = self.ms_to_x(self.trim_start_ms)
            end_x = self.ms_to_x(self.trim_end_ms)
            painter.fillRect(QRectF(start_x, track_y, end_x - start_x, track_height), self.trim_body_color)
            painter.fillRect(QRectF(start_x, track_y - 2.0, 4.0, track_height + 4.0), self.trim_handle_color)
            painter.fillRect(QRectF(end_x - 4.0, track_y - 2.0, 4.0, track_height + 4.0), self.trim_handle_color)

        # --- Gamemode: Shading non-game segments (menu / lobby / loading) ---
        for seg_start, seg_end, seg_mode in getattr(self, 'mode_segments', []):
            if seg_mode in (0, 1): 
                continue
            sx = self.ms_to_x(seg_start)
            ex = self.ms_to_x(min(seg_end, self.duration_ms))
            if ex - sx <= 0:
                continue
            seg_rect = QRectF(sx, track_y, ex - sx, track_height)
            painter.fillRect(seg_rect, QColor(0, 0, 0, 55))     # slight dim, keeps the bar visible
            painter.save()
            painter.setClipRect(seg_rect)
            painter.setPen(QPen(QColor(255, 255, 255, 150), 2))
            step = 7
            xx = (int(sx) // step) * step - int(track_height)
            while xx < int(ex):
                painter.drawLine(xx, int(track_y + track_height), xx + int(track_height), int(track_y))
                xx += step
            painter.restore()

        # --- Featured clips: yellow dotted line under the stripe ---
        if getattr(self, 'clip_ranges', None):
            painter.setPen(QPen(QColor(240, 200, 60), 2, Qt.DashLine))
            dash_y = int(track_y + track_height + 1)
            for a, b in self.clip_ranges:
                ax = self.ms_to_x(a)
                bx = self.ms_to_x(min(b, self.duration_ms))
                if bx - ax > 0:
                    painter.drawLine(int(ax), dash_y, int(bx), dash_y)

        for marker in getattr(self, 'markers', []):
            if marker['is_round']:
                m_x = self.ms_to_x(marker['time_ms'])
                # Draw a 2px-wide tick mark over the purple background,
                # but BEFORE the white playhead bar is drawn at the end of the function!
                painter.fillRect(QRectF(m_x - 1.0, track_y, 2.0, track_height), QColor(255, 255, 255, 140))

        pixels_per_sec = usable_w / (self.duration_ms / 1000.0) # Заменили width на usable_w
        
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
        painter.setFont(self._ruler_font)

        ruler_y = track_y + track_height + self._RULER_GAP

        current_sec = start_sec
        while current_sec <= end_sec:
            x = self.ms_to_x(current_sec * 1000)
            x_pix = round(x)
            is_major = (current_sec % max(10, step * 5) == 0) or (step >= 60 and current_sec % 60 == 0)

            if is_major:
                tick_bot = int(ruler_y + self._MAJOR_TICK_H)
                painter.drawLine(x_pix, int(ruler_y), x_pix, tick_bot)

                h = int(current_sec // 3600)
                m = int((current_sec % 3600) // 60)
                s = int(current_sec % 60)

                if h > 0:
                    time_str = f"{h}:{m:02d}:{s:02d}"
                else:
                    time_str = f"{m}:{s:02d}"

                painter.drawText(x_pix + 3, tick_bot, time_str)
            else:
                painter.drawLine(x_pix, int(ruler_y), x_pix, int(ruler_y + self._MINOR_TICK_H))

            current_sec += step

        # Drawing icons and tooltips

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
            pix = self.get_icon_pixmap(marker)
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
            ghost_x = max(pad, min(self.hover_x - (ghost_w / 2.0), width - pad - ghost_w))
            painter.fillRect(QRectF(ghost_x, track_y - 4.0, ghost_w, track_height + 8.0), QColor(255, 255, 255, 80))

        #  ULTRA SCROLLER ASSEMBLY 
        if not getattr(self, 'has_custom_scroller', False):
            # Old white strip (if no images)
            handle_w = 4.0
            # Centering a standard white stick
            handle_x = fill_x_end - (handle_w / 2.0) 
            painter.fillRect(QRectF(handle_x, track_y - 4.0, handle_w, track_height + 8.0), self.handle_color)
        else:
            
            handle_w = 8.0
            
            # FIX 1: Center the scroller image! 
            # Subtract exactly half the width (4px) so the needle points precisely at the time.
            handle_x = fill_x_end - (handle_w / 2.0) 
            handle_y = track_y - self.master_head_h
            
            painter.save() 
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            
            painter.translate(handle_x, handle_y)
        
            painter.scale(1.001, 1.001) 
            
            painter.drawImage(QPointF(0.0, 0.0), self.master_scroller_img)
            
            painter.restore()

    def ms_to_x(self, ms):
        pad = 12.0
        usable_w = float(self.width()) - (pad * 2)
        if self.duration_ms <= 0 or usable_w <= 0: return pad
        x = pad + (ms / self.duration_ms) * usable_w
        return max(pad, min(x, float(self.width()) - pad))

    def x_to_ms(self, x):
        pad = 12.0
        usable_w = float(self.width()) - (pad * 2)
        if usable_w <= 0: return 0
        relative_x = max(0.0, min(x - pad, usable_w))
        return (relative_x / usable_w) * self.duration_ms

    def mousePressEvent(self, event):
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
        
        trim_handle = self._trim_handle_at(x, y)
        if trim_handle:
            self.drag_state = trim_handle
            return

        self.drag_state = 'playhead'
        self.pause_requested.emit() 
        self.update_playhead(x)

    def show_marker_context_menu(self, pos, marker):
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
        is_screenshot_marker = marker.get('icon_key') == 'screenshot'
        
        if is_user_marker:
            action_edit = menu.addAction("✏️ Edit Marker")
            action_delete = menu.addAction("🗑️ Delete Marker")
            menu.addSeparator() 

        action_open_screenshot = None
        if is_screenshot_marker:
            action_open_screenshot = menu.addAction("🖼 Open Screenshot")
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
        elif action_open_screenshot and action == action_open_screenshot:
            self.open_steam_screenshot_requested.emit(marker)
        elif action == action_trim:
            self.set_trim_start_from_marker(marker)
        elif action == action_screenshot: # Sending the order to take a screenshot
            self.screenshot_requested.emit(float(marker.get('time_ms', 0)))
    
    def show_track_context_menu(self, pos, time_ms):
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
        if self.duration_ms <= 0: return
        
        x, y = event.position().x(), event.position().y()
        ms = self.x_to_ms(x)
        
        self.hover_x = float(x)
        self.is_hovering = True 
        self.is_hovering_trim_handle = False

        found_marker = None
        for marker in getattr(self, 'markers', []):
            m_x = self.ms_to_x(marker['time_ms'])
            pix = self.get_icon_pixmap(marker)

            
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
            
        if self._trim_handle_at(x, y):
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
            current_thumb_dir = getattr(self, 'thumb_dir', None) if self._thumb_dir_is_valid() else None
            has_disk_thumb = False
            
            bucket_sec = round(sec / 3.0) * 3
            if current_thumb_dir:
                index = (bucket_sec // 3) + 1
                img_path = os.path.join(current_thumb_dir, f"thumb_{index:04d}.jpg")
                if os.path.exists(img_path):
                    has_disk_thumb = True

            sniper_cache = getattr(self.sniper, 'cache', {}) if hasattr(self, 'sniper') else {}

            bucket_changed = bucket_sec != self._hover_preview_bucket
            if bucket_changed:
                self._hover_preview_bucket = bucket_sec

            self.preview_widget.update_time_display(time_str, is_in_trim)

            if has_disk_thumb:
                if bucket_changed or getattr(self, '_batch_thumbs_busy', False):
                    self.preview_widget.load_disk_thumbnail(hover_ms, current_thumb_dir)
            elif bucket_changed:
                if bucket_sec in sniper_cache:
                    self.preview_widget.set_preview_pixmap(sniper_cache[bucket_sec])
                else:
                    self.preview_widget.clear_for_new_media()
                    self.preview_widget.start_loading()

            if not has_disk_thumb and self.current_video_path and bucket_changed:
                self.pending_sec = bucket_sec
                if hasattr(self, 'sniper_timer'):
                    self.sniper_timer.start(100)

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
        if event.button() != Qt.LeftButton: return
        if self.drag_state == 'playhead':
            self.user_seek_lock_time = time.time() + 0.15 
            self.update_playhead(event.position().x())
            self.resume_requested.emit()
        elif self.drag_state in ['trim_l', 'trim_r']:
            self.trim_changed.emit(int(self.trim_start_ms), int(self.trim_end_ms))
        self.drag_state = 'none'

    def update_playhead(self, mouse_x):
        # Use the SAME padded mapping as x_to_ms/ms_to_x, otherwise the playhead is
        # drawn off from where the cursor clicked (up to ±pad px, worst at the edges).
        self.visual_ms = max(0.0, min(self.x_to_ms(mouse_x), float(self.duration_ms)))
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
        self.is_hovering = False
        self.hover_x = -1.0
        self._hover_preview_bucket = -1
        if hasattr(self, 'preview_widget'): self.preview_widget.hide()
        if hasattr(self, 'text_tooltip'): self.text_tooltip.hide()
        self.setCursor(Qt.ArrowCursor) 
        self.update() 
        super().leaveEvent(event)

    # Explicitly intercept the wheel directly on the canvas so Qt doesn't eat up the scroll
    def wheelEvent(self, event):
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



class CustomTimelineWidget(QScrollArea):
    pause_requested = Signal()        
    seek_requested = Signal(int)      
    resume_requested = Signal()
    trim_changed = Signal(int, int) 
    

    screenshot_requested = Signal(object)
    add_marker_requested = Signal(float)
    open_steam_screenshot_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        
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
        self.canvas.open_steam_screenshot_requested.connect(self.open_steam_screenshot_requested.emit)

        # The CONTAINER is rigidly and permanently set to 38px! No changes when zooming, nothing will creep up!        self.setFixedHeight(38)

        canvas_h = TimelineCanvas._CANVAS_H
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
    def thumb_dir(self, val):
        self.canvas.thumb_dir = val
        if val:
            self.canvas._thumb_dir_media_path = getattr(self.canvas, 'current_video_path', '') or ''
        else:
            self.canvas._thumb_dir_media_path = ''

    @property
    def current_video_path(self):
        return self.canvas.current_video_path

    @current_video_path.setter
    def current_video_path(self, val):
        val = val or ""
        old = getattr(self.canvas, 'current_video_path', '') or ''
        if hasattr(self.canvas, 'sniper') and self.canvas.sniper:
            norm = self.canvas._norm_media_path
            if norm(val) != norm(old):
                self.canvas.sniper.kill_worker()
                self.canvas.sniper.cache.clear()
            self.canvas.sniper.video_path = val
        if val != old:
            self.canvas._hover_preview_bucket = -1
            self.canvas.thumb_dir = None
            self.canvas._thumb_dir_media_path = ''
            self.canvas._batch_thumbs_busy = False
            if hasattr(self.canvas, 'preview_widget'):
                self.canvas.preview_widget.clear_for_new_media()
        self.canvas.current_video_path = val

    def force_jump(self, ms): self.canvas.force_jump(ms)
    def set_duration(self, ms): self.canvas.set_duration(ms)
    def set_vlc_time(self, ms, is_p): self.canvas.set_vlc_time(ms, is_p)
    def enable_trim_mode(self): self.canvas.enable_trim_mode()
    def disable_trim_mode(self): self.canvas.disable_trim_mode()
    

# --- TIMELINE HOVER PREVIEW SPINNER ---
class PreviewSpinnerOverlay(QWidget):
    """MPV-style loading arc over the hover thumbnail (no text)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._angle = 0
        self._spin = QTimer(self)
        self._spin.setInterval(33)
        self._spin.timeout.connect(self._advance)
        self.hide()

    def _advance(self):
        self._angle = (self._angle + 24) % 360
        self.update()

    def start(self):
        if not self._spin.isActive():
            self._spin.start()
        self.show()
        self.raise_()

    def stop(self):
        self._spin.stop()
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        radius = 14.0
        pen = QPen(QColor("#b29ae7"))
        pen.setWidth(4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(
            int(cx - radius), int(cy - radius), int(2 * radius), int(2 * radius),
            self._angle * 16, 110 * 16,
        )


# --- FLOATING TIMELINE PREVIEW WIDGET ---
class ThumbnailPreviewWidget(QWidget):
    """A floating tooltip-like widget that shows a video frame and time on hover."""
    _THUMB_W = 160
    _THUMB_H = 90

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.frame = QFrame()
        self.frame.setStyleSheet("QFrame { background-color: #181818; border: 1px solid #333; border-radius: 6px; }")
        self.frame_layout = QVBoxLayout(self.frame)
        self.frame_layout.setContentsMargins(4, 4, 4, 4)
        self.frame_layout.setSpacing(4)

        self._thumb_host = QWidget()
        self._thumb_host.setFixedSize(self._THUMB_W, self._THUMB_H)

        self.img_label = QLabel(self._thumb_host)
        self.img_label.setGeometry(0, 0, self._THUMB_W, self._THUMB_H)
        self.img_label.setStyleSheet("background-color: #000000; border-radius: 4px;")
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._loading_overlay = PreviewSpinnerOverlay(self._thumb_host)
        self._loading_overlay.setGeometry(0, 0, self._THUMB_W, self._THUMB_H)

        self.time_label = QLabel("00:00")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setStyleSheet(
            "background-color: #2d2d2d; border-radius: 4px; padding: 2px; "
            "color: white; font-weight: bold; font-size: 11px;"
        )

        self.frame_layout.addWidget(self._thumb_host)
        self.frame_layout.addWidget(self.time_label)
        self.layout.addWidget(self.frame)
        self.hide()

    def hideEvent(self, event):
        self._loading_overlay.stop()
        super().hideEvent(event)

    def clear_for_new_media(self):
        self._loading_overlay.stop()
        self.img_label.clear()
        self.img_label.setPixmap(QPixmap())

    def update_time_display(self, time_str, is_in_trim):
        self.time_label.setText(time_str)
        if is_in_trim:
            self.time_label.setStyleSheet(
                "background-color: #2d2d2d; border-radius: 4px; padding: 2px; "
                "color: #ffcc00; font-weight: bold; font-size: 11px;"
            )
        else:
            self.time_label.setStyleSheet(
                "background-color: #2d2d2d; border-radius: 4px; padding: 2px; "
                "color: white; font-weight: bold; font-size: 11px;"
            )

    def _apply_pixmap(self, pixmap):
        if pixmap is not None and not pixmap.isNull():
            self.img_label.setPixmap(
                pixmap.scaled(
                    self._THUMB_W, self._THUMB_H,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self._loading_overlay.stop()

    def load_disk_thumbnail(self, hover_ms, thumb_dir):
        if not thumb_dir or not os.path.exists(thumb_dir):
            return False
        sec = int(hover_ms // 1000)
        bucket_sec = round(sec / 3.0) * 3
        index = (bucket_sec // 3) + 1
        img_path = os.path.join(thumb_dir, f"thumb_{index:04d}.jpg")
        if not os.path.exists(img_path):
            return False
        self._apply_pixmap(QPixmap(img_path))
        return True

    def start_loading(self):
        self.img_label.clear()
        self.img_label.setPixmap(QPixmap())
        self._loading_overlay.start()

    def set_preview_pixmap(self, pixmap):
        if pixmap is not None and not pixmap.isNull():
            self._apply_pixmap(pixmap)

    def update_image_from_ram(self, pixmap):
        """Instantly applies a generated QPixmap from the Sniper's RAM cache."""
        self.set_preview_pixmap(pixmap)

    def update_info(self, time_str, is_in_trim, hover_ms, thumb_dir):
        """Legacy entry point — updates time and loads a disk thumb when available."""
        self.update_time_display(time_str, is_in_trim)
        if thumb_dir:
            self.load_disk_thumbnail(hover_ms, thumb_dir)