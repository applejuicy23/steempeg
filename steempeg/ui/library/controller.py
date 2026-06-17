"""Clip library: grid/list view, context menus, scanning and folder actions.

Mixed into the main application. These methods populate and refresh the clip
library, drive the right-click menus and clip deletion, and let the user choose
the clips folder. They run on the application instance and reach its widgets and
state through self.
"""
import logging
import os
import shutil

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox


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