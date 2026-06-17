"""Clip library: grid/list view, context menus, scanning and folder actions.

Mixed into the main application. These methods populate and refresh the clip
library, drive the right-click menus and clip deletion, and let the user choose
the clips folder. They run on the application instance and reach its widgets and
state through self.
"""
import logging
import os
import re
import shutil
from datetime import datetime, timezone

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFileDialog,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QTableWidgetItem,
)

from steempeg.core.dash import discovery, mpd
from steempeg.ui.library.grid_view import ClipCard


class LibraryMixin:
    def show_grid_context_menu(self, pos):
        """ Pop-up menu for the grid """
        
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
            logging.error(f"Scan Error: {e}")
    
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
            
            item = QListWidgetItem(self.grid_clips)
            item.setSizeHint(QSize(260, 190))

            item.setData(Qt.UserRole, row) # Save row index for selection logic
            item.setData(Qt.UserRole + 1, clip_path) 
            self.grid_clips.setItemWidget(item, card)

            
            # SYNC VISIBILITY WITH TABLE
            if self.ui.table_clips.isRowHidden(row):
                item.setHidden(True)