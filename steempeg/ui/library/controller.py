"""Clip library: grid/list view, context menus, scanning, filtering and metadata.

Mixed into the main application. These methods populate and refresh the clip
library, drive the right-click menus and clip deletion, handle sorting/filtering,
resolve game names and icons, and let the user choose the clips folder. They run on
the application instance and reach its widgets and state through self.
"""
import logging
import os
import re
import shutil
from datetime import datetime, timezone

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, QItemSelection, QItemSelectionModel
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QTableWidgetItem,
)

from steempeg.core import games
from steempeg.core.dash import discovery, mpd
from steempeg.infra.locale_time import format_clip_date, format_clip_time, parse_clip_datetime_text
from steempeg.ui.library.filters import FilterMenu
from steempeg.ui.library.grid_view import ClipCard


_LIBRARY_MENU_STYLE = """
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
"""


class LibraryMixin:
    def _context_menu_clip_paths_table(self, pos) -> list:
        item = self.ui.table_clips.itemAt(pos)
        if not item:
            return []

        clicked_row = item.row()
        selected_rows = {idx.row() for idx in self.ui.table_clips.selectionModel().selectedRows()}
        if clicked_row in selected_rows and len(selected_rows) > 1:
            rows = sorted(selected_rows)
        else:
            rows = [clicked_row]

        paths = []
        seen = set()
        for row in rows:
            cell = self.ui.table_clips.item(row, 0)
            if not cell:
                continue
            path = cell.data(Qt.UserRole)
            if not path:
                continue
            norm = os.path.normpath(path)
            if norm in seen or not os.path.exists(path):
                continue
            seen.add(norm)
            paths.append(path)
        return paths

    def _context_menu_clip_paths_grid(self, pos) -> list:
        item = self.grid_clips.itemAt(pos)
        if not item:
            return []

        clicked_path = item.data(Qt.UserRole + 1)
        selected_items = self.grid_clips.selectedItems()
        selected_paths = [
            it.data(Qt.UserRole + 1) for it in selected_items if it.data(Qt.UserRole + 1)
        ]

        if clicked_path in selected_paths and len(selected_paths) > 1:
            candidates = selected_paths
        else:
            candidates = [clicked_path]

        paths = []
        seen = set()
        for path in candidates:
            if not path:
                continue
            norm = os.path.normpath(path)
            if norm in seen or not os.path.exists(path):
                continue
            seen.add(norm)
            paths.append(path)
        return paths

    def _populate_library_context_menu(self, menu, clip_paths: list):
        count = len(clip_paths)
        if count == 0:
            return

        queue_label = "📋 Add to queue" if count == 1 else f"📋 Add to queue ({count})"
        action_queue = menu.addAction(queue_label)
        action_queue.triggered.connect(lambda: self.add_clips_to_render_queue(clip_paths))

        menu.addSeparator()
        action_open = menu.addAction("📂 Open in folder")
        action_delete = menu.addAction("🗑️ Delete Clip" if count == 1 else f"🗑️ Delete Clips ({count})")

        if count == 1:
            clip_path = clip_paths[0]
            action_open.triggered.connect(lambda: self.open_clip_folder(clip_path))
            action_delete.triggered.connect(lambda: self.delete_clip(clip_path))
        else:
            action_open.setEnabled(False)
            action_delete.setEnabled(False)

    def sync_grid_from_table_selection(self):
        """Mirror multi-selection from the list into the grid."""
        if not hasattr(self, 'grid_clips') or not hasattr(self.ui, 'table_clips'):
            return

        selected_rows = {idx.row() for idx in self.ui.table_clips.selectionModel().selectedRows()}

        self.grid_clips.blockSignals(True)
        self.grid_clips.clearSelection()
        for i in range(self.grid_clips.count()):
            item = self.grid_clips.item(i)
            if item.data(Qt.UserRole) in selected_rows:
                item.setSelected(True)
        self.grid_clips.blockSignals(False)
        self._sync_grid_card_visuals()

    def _sync_grid_card_visuals(self) -> None:
        """Paint selection on ClipCard widgets — QListWidget item chrome is hidden underneath."""
        if not hasattr(self, 'grid_clips'):
            return
        for i in range(self.grid_clips.count()):
            item = self.grid_clips.item(i)
            card = self.grid_clips.itemWidget(item)
            if isinstance(card, ClipCard):
                card.set_selected(item.isSelected())

    def sync_table_from_grid_selection(self, *, keep_current_cell: bool = False) -> None:
        """Mirror multi-selection from the grid into the list."""
        if not hasattr(self, 'grid_clips') or not hasattr(self.ui, 'table_clips'):
            return

        selected_items = self.grid_clips.selectedItems()
        table = self.ui.table_clips
        if not selected_items:
            table.blockSignals(True)
            table.clearSelection()
            table.blockSignals(False)
            return

        rows = sorted({
            item.data(Qt.UserRole)
            for item in selected_items
            if item.data(Qt.UserRole) is not None
        })

        selection = QItemSelection()
        for row in rows:
            if row < 0 or row >= table.rowCount():
                continue
            selection.select(
                table.model().index(row, 0),
                table.model().index(row, table.columnCount() - 1),
            )

        table.blockSignals(True)
        table.selectionModel().clearSelection()
        if not selection.isEmpty():
            table.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.Select)
            current_row = table.currentRow()
            if not keep_current_cell or current_row not in rows:
                table.setCurrentCell(rows[0], 0)
        table.blockSignals(False)

    def _publish_grid_selection(self, *, update_preview: bool = True) -> None:
        """Mirror grid selection into the table; reload preview only on plain LMB clicks."""
        if not self.grid_clips.selectedItems():
            self.sync_table_from_grid_selection()
            self._sync_grid_card_visuals()
            return
        self.sync_table_from_grid_selection(keep_current_cell=not update_preview)
        self._sync_grid_card_visuals()
        if update_preview and hasattr(self.ui, 'table_clips') and self.ui.table_clips.currentRow() >= 0:
            self.update_quality_options()

    def _grid_select_item(self, item, event=None, *, force_single: bool = False) -> None:
        """LMB selection for grid cards — setItemWidget breaks default Qt hit-testing."""
        grid = self.grid_clips
        mods = QApplication.keyboardModifiers()
        if event is not None:
            mods |= event.modifiers()
        if force_single:
            mods = Qt.NoModifier

        is_multi = bool(mods & (Qt.ControlModifier | Qt.ShiftModifier)) and not force_single
        update_preview = not is_multi

        self._grid_select_in_progress = True
        try:
            grid.blockSignals(True)
            if mods & Qt.ControlModifier:
                item.setSelected(not item.isSelected())
            elif mods & Qt.ShiftModifier:
                anchor = getattr(self, '_grid_anchor_item', None)
                try:
                    anchor_row = grid.row(anchor) if anchor is not None else -1
                except RuntimeError:
                    anchor_row = -1  # anchor item was destroyed by a grid rebuild
                if anchor_row < 0:
                    anchor_row = grid.row(item)
                    self._grid_anchor_item = item
                lo, hi = sorted((anchor_row, grid.row(item)))
                grid.clearSelection()
                for i in range(lo, hi + 1):
                    row_item = grid.item(i)
                    if row_item and not row_item.isHidden():
                        row_item.setSelected(True)
            else:
                grid.clearSelection()
                item.setSelected(True)
                self._grid_anchor_item = item

            if not (mods & (Qt.ControlModifier | Qt.ShiftModifier)):
                self._grid_anchor_item = item

            grid.blockSignals(False)
        finally:
            self._grid_select_in_progress = False

        self._publish_grid_selection(update_preview=update_preview)

    def _handle_grid_card_context_menu(self, item, event) -> None:
        # Right-click only opens the menu; it never changes the selection.
        # The menu resolves its target from the clip under the cursor (see
        # _context_menu_clip_paths_grid), so left-click stays the only way to select.
        # The card sends a position relative to itself, so map it back to the grid
        # viewport to pop the menu exactly where the cursor is (not the card center).
        viewport_pos = self.grid_clips.viewport().mapFromGlobal(event.globalPosition().toPoint())
        self.show_grid_context_menu(viewport_pos)

    def _handle_grid_viewport_press(self, event) -> bool:
        if event.button() != Qt.LeftButton:
            return False

        pos = event.position().toPoint()
        item = self.grid_clips.itemAt(pos)
        if item is None:
            # Clicking empty space inside the grid keeps the current selection
            # (the purple outline stays); only clicking another card changes it.
            return True

        self._grid_select_item(item, event)
        return True

    def show_grid_context_menu(self, pos):
        """ Pop-up menu for the grid """
        clip_paths = self._context_menu_clip_paths_grid(pos)
        if not clip_paths:
            return

        # Keep QMenu's own native popup flags (Qt.Popup). Overriding them with a
        # translucent frameless window made the menu a layered top-level that
        # wouldn't close on focus loss and slid behind the main window.
        menu = QMenu(self.grid_clips)
        menu.setStyleSheet(_LIBRARY_MENU_STYLE)

        self._populate_library_context_menu(menu, clip_paths)
        menu.exec(self.grid_clips.viewport().mapToGlobal(pos))

    def show_clip_context_menu(self, pos):
        """ Pop-up menu for a standard list (List/Table) """
        clip_paths = self._context_menu_clip_paths_table(pos)
        if not clip_paths:
            return

        # See show_grid_context_menu: keep the native Qt.Popup flags so the menu
        # closes correctly instead of lingering behind the window.
        menu = QMenu(self.ui.table_clips)
        menu.setStyleSheet(_LIBRARY_MENU_STYLE)

        self._populate_library_context_menu(menu, clip_paths)
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
    def refresh_library(self):
        """ Refresh button: wipe the active filter, deselect the current clip/queue job,
        reset the player + settings panel, then rescan the folder from scratch. """
        # 1. Drop the remembered filter so the menu reopens at defaults and nothing stays hidden
        self.saved_filter_state = None
        if getattr(self, 'filter_menu', None) is not None:
            try:
                self.filter_menu.deleteLater()
            except Exception:
                pass
            self.filter_menu = None

        # 2. Reset the selected clip, the player surface and every settings tab
        if hasattr(self, 'close_current_clip'):
            self.close_current_clip()

        # 3. Drop the queue selection (the queued jobs themselves are kept)
        self._selected_queue_job_id = None
        if hasattr(self, 'refresh_render_queue_panel'):
            self.refresh_render_queue_panel()

        # 4. Rescan the folder
        self.scan_clips()

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
                        formatted_date = format_clip_date(dt_local)
                        formatted_time = format_clip_time(dt_local)
                    except Exception as e:
                        # If the folder is named incorrectly, use the old fallback option.
                        try: formatted_date = format_clip_date(datetime.strptime(parts[2], "%Y%m%d"))
                        except: formatted_date = parts[2]
                        try: formatted_time = format_clip_time(datetime.strptime(parts[3], "%H%M%S"))
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
            self.ui.table_clips.horizontalHeader().setSectionsClickable(False)

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
        """Qt signal fallback — custom card clicks publish selection manually."""
        if getattr(self, '_grid_select_in_progress', False):
            return
        self._publish_grid_selection()

    def build_netflix_grid(self):
        """ Transforms rows from a hidden table into vibrant cards. """
        if not hasattr(self, 'grid_clips') or not hasattr(self.ui, 'table_clips'):
            return

        # Items get destroyed below — drop the stale Shift anchor or range-select breaks.
        self._grid_anchor_item = None
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
            item = QListWidgetItem(self.grid_clips)
            item.setSizeHint(QSize(260, 190))
            item.setData(Qt.UserRole, row)
            item.setData(Qt.UserRole + 1, clip_path)

            card = ClipCard(
                title,
                f"{date_str} • {time_str}",
                badge_text,
                thumb_path,
                icon_path,
                row,
                on_left_click=lambda ev, grid_item=item: self._grid_select_item(grid_item, ev),
                on_right_click=lambda ev, grid_item=item: self._handle_grid_card_context_menu(grid_item, ev),
            )
            self.grid_clips.setItemWidget(item, card)

            
            # SYNC VISIBILITY WITH TABLE
            if self.ui.table_clips.isRowHidden(row):
                item.setHidden(True)

        self.sync_grid_from_table_selection()

    def show_filter_menu(self):
        """ Calculates the coordinates and passes the ENTIRE PROGRAM (self) to the menu. """
        if not hasattr(self, 'btn_filter_pill'): return
        
        # 1. Forcefully destroy the old window to reset the Qt focus bug.
        if hasattr(self, 'filter_menu') and self.filter_menu:
            self.filter_menu.deleteLater()
            
        # 2. Creating a brand-new menu from scratch
        self.filter_menu = FilterMenu(self.ui)
        self.filter_menu.gather_statistics(self)

        button_bottom_left = self.btn_filter_pill.mapToGlobal(QPoint(0, self.btn_filter_pill.height()))
        x_shift = self.filter_menu.width() - self.btn_filter_pill.width()
        menu_y = button_bottom_left.y() + 5
        self.filter_menu.move(button_bottom_left.x() - x_shift + 10, menu_y)

        if hasattr(self, 'btn_refresh'):
            footer_top = self.btn_refresh.mapToGlobal(QPoint(0, 0)).y()
            self.filter_menu.set_content_max_height(max(160, footer_top - menu_y - 8))

        self.filter_menu.show()

    def apply_sorting(self):
        """ FAST INDEPENDENT SORTING ENGINE """
        if not hasattr(self.ui, 'table_clips'): return
        table = self.ui.table_clips
        sort_idx = self.combo_sort.currentIndex()
        
        
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
                qdt = parse_clip_datetime_text(txt)
                if qdt is not None:
                    return qdt.toSecsSinceEpoch()
                return 0
                    
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

    

    # --- TRUE HIGH-END FULLSCREEN SYSTEM ---
    def get_game_name(self, app_id):
        app_id = str(app_id)
        # 1. Cache first
        if app_id in self.game_names_cache:
            return self.game_names_cache[app_id]
        # 2. Otherwise, ask Steam once and remember
        name = games.fetch_game_name(app_id)
        if name:
            self.game_names_cache[app_id] = name
            self.save_json_cache()
            return name
        return f"Unknown Game ({app_id})"
    



    

    
    def get_game_icon(self, app_id):
        app_id = str(app_id)
        # 1. RAM cache
        if app_id in self.game_icons_cache:
            return self.game_icons_cache[app_id]
        # 2. disk cache, otherwise download
        icon_path = os.path.join(self.cache_dir, f"{app_id}.jpg")
        if not os.path.exists(icon_path):
            if not games.download_icon(app_id, icon_path):
                return QIcon()
        # 3. Build a Qt icon (this is Qt -> stays here) and cache it in RAM
        icon = QIcon(QPixmap(icon_path))
        self.game_icons_cache[app_id] = icon
        return icon

    def set_view_mode(self, mode):
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