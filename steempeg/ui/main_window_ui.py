# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'smpegui13.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QProgressBar,
    QPushButton, QSizePolicy, QSlider, QSpacerItem,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget)

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        if not Dialog.objectName():
            Dialog.setObjectName(u"Dialog")
        Dialog.resize(1277, 817)
        self.horizontalLayout_main = QHBoxLayout(Dialog)
        self.horizontalLayout_main.setObjectName(u"horizontalLayout_main")
        self.main_splitter = QSplitter(Dialog)
        self.main_splitter.setObjectName(u"main_splitter")
        self.main_splitter.setOrientation(Qt.Orientation.Horizontal)
        self.main_splitter.setHandleWidth(6)
        self.left_panel = QWidget(self.main_splitter)
        self.left_panel.setObjectName(u"left_panel")
        self.verticalLayout_left = QVBoxLayout(self.left_panel)
        self.verticalLayout_left.setObjectName(u"verticalLayout_left")
        self.verticalLayout_left.setContentsMargins(0, 0, -1, 0)
        self.label_13 = QLabel(self.left_panel)
        self.label_13.setObjectName(u"label_13")
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        self.label_13.setFont(font)

        self.verticalLayout_left.addWidget(self.label_13)

        self.table_clips = QTableWidget(self.left_panel)
        self.table_clips.setObjectName(u"table_clips")

        self.verticalLayout_left.addWidget(self.table_clips)

        self.btn_browse = QPushButton(self.left_panel)
        self.btn_browse.setObjectName(u"btn_browse")

        self.verticalLayout_left.addWidget(self.btn_browse)

        self.horizontalLayout_duo = QHBoxLayout()
        self.horizontalLayout_duo.setObjectName(u"horizontalLayout_duo")
        self.btn_about = QPushButton(self.left_panel)
        self.btn_about.setObjectName(u"btn_about")

        self.horizontalLayout_duo.addWidget(self.btn_about)

        self.btn_update_check = QPushButton(self.left_panel)
        self.btn_update_check.setObjectName(u"btn_update_check")

        self.horizontalLayout_duo.addWidget(self.btn_update_check)


        self.verticalLayout_left.addLayout(self.horizontalLayout_duo)

        self.main_splitter.addWidget(self.left_panel)
        self.right_panel = QWidget(self.main_splitter)
        self.right_panel.setObjectName(u"right_panel")
        self.verticalLayout_right = QVBoxLayout(self.right_panel)
        self.verticalLayout_right.setObjectName(u"verticalLayout_right")
        self.verticalLayout_right.setContentsMargins(0, 0, 0, 0)
        self.video_container = QWidget(self.right_panel)
        self.video_container.setObjectName(u"video_container")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.video_container.sizePolicy().hasHeightForWidth())
        self.video_container.setSizePolicy(sizePolicy)
        self.video_container.setMinimumSize(QSize(0, 280))

        self.verticalLayout_right.addWidget(self.video_container)

        self.layout_player_controls = QHBoxLayout()
        self.layout_player_controls.setSpacing(8)
        self.layout_player_controls.setObjectName(u"layout_player_controls")
        self.btn_skip_back = QPushButton(self.right_panel)
        self.btn_skip_back.setObjectName(u"btn_skip_back")
        self.btn_skip_back.setMaximumSize(QSize(40, 16777215))

        self.layout_player_controls.addWidget(self.btn_skip_back)

        self.btn_play = QPushButton(self.right_panel)
        self.btn_play.setObjectName(u"btn_play")
        self.btn_play.setMinimumSize(QSize(80, 0))

        self.layout_player_controls.addWidget(self.btn_play)

        self.btn_skip_forward = QPushButton(self.right_panel)
        self.btn_skip_forward.setObjectName(u"btn_skip_forward")
        self.btn_skip_forward.setMaximumSize(QSize(40, 16777215))

        self.layout_player_controls.addWidget(self.btn_skip_forward)

        self.slider_timeline = QSlider(self.right_panel)
        self.slider_timeline.setObjectName(u"slider_timeline")
        self.slider_timeline.setOrientation(Qt.Orientation.Horizontal)

        self.layout_player_controls.addWidget(self.slider_timeline)

        self.label_time = QLabel(self.right_panel)
        self.label_time.setObjectName(u"label_time")
        self.label_time.setMinimumSize(QSize(90, 0))
        font1 = QFont()
        font1.setBold(True)
        self.label_time.setFont(font1)
        self.label_time.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.layout_player_controls.addWidget(self.label_time)


        self.verticalLayout_right.addLayout(self.layout_player_controls)

        self.settings_tabs = QTabWidget(self.right_panel)
        self.settings_tabs.setObjectName(u"settings_tabs")
        self.tab_source = QWidget()
        self.tab_source.setObjectName(u"tab_source")
        self.verticalLayout_source = QVBoxLayout(self.tab_source)
        self.verticalLayout_source.setObjectName(u"verticalLayout_source")
        self.source_label = QLabel(self.tab_source)
        self.source_label.setObjectName(u"source_label")

        self.verticalLayout_source.addWidget(self.source_label)

        self.orig_res_label = QLabel(self.tab_source)
        self.orig_res_label.setObjectName(u"orig_res_label")

        self.verticalLayout_source.addWidget(self.orig_res_label)

        self.label_duration = QLabel(self.tab_source)
        self.label_duration.setObjectName(u"label_duration")

        self.verticalLayout_source.addWidget(self.label_duration)

        self.label_fps = QLabel(self.tab_source)
        self.label_fps.setObjectName(u"label_fps")

        self.verticalLayout_source.addWidget(self.label_fps)

        self.label_size = QLabel(self.tab_source)
        self.label_size.setObjectName(u"label_size")

        self.verticalLayout_source.addWidget(self.label_size)

        self.vs1 = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_source.addItem(self.vs1)

        self.settings_tabs.addTab(self.tab_source, "")
        self.tab_video = QWidget()
        self.tab_video.setObjectName(u"tab_video")
        self.verticalLayout_video = QVBoxLayout(self.tab_video)
        self.verticalLayout_video.setObjectName(u"verticalLayout_video")
        self.label_2 = QLabel(self.tab_video)
        self.label_2.setObjectName(u"label_2")

        self.verticalLayout_video.addWidget(self.label_2)

        self.combo_quality = QComboBox(self.tab_video)
        self.combo_quality.setObjectName(u"combo_quality")

        self.verticalLayout_video.addWidget(self.combo_quality)

        self.label_target_size = QLabel(self.tab_video)
        self.label_target_size.setObjectName(u"label_target_size")

        self.verticalLayout_video.addWidget(self.label_target_size)

        self.size_slider = QSlider(self.tab_video)
        self.size_slider.setObjectName(u"size_slider")
        self.size_slider.setOrientation(Qt.Orientation.Horizontal)

        self.verticalLayout_video.addWidget(self.size_slider)

        self.label_5 = QLabel(self.tab_video)
        self.label_5.setObjectName(u"label_5")

        self.verticalLayout_video.addWidget(self.label_5)

        self.combo_fps = QComboBox(self.tab_video)
        self.combo_fps.setObjectName(u"combo_fps")

        self.verticalLayout_video.addWidget(self.combo_fps)

        self.label_4 = QLabel(self.tab_video)
        self.label_4.setObjectName(u"label_4")

        self.verticalLayout_video.addWidget(self.label_4)

        self.combo_bitrate = QComboBox(self.tab_video)
        self.combo_bitrate.setObjectName(u"combo_bitrate")

        self.verticalLayout_video.addWidget(self.combo_bitrate)

        self.horizontalLayout_codecs = QHBoxLayout()
        self.horizontalLayout_codecs.setObjectName(u"horizontalLayout_codecs")
        self.vboxLayout = QVBoxLayout()
        self.vboxLayout.setObjectName(u"vboxLayout")
        self.label_14 = QLabel(self.tab_video)
        self.label_14.setObjectName(u"label_14")

        self.vboxLayout.addWidget(self.label_14)

        self.combo_codec = QComboBox(self.tab_video)
        self.combo_codec.setObjectName(u"combo_codec")

        self.vboxLayout.addWidget(self.combo_codec)


        self.horizontalLayout_codecs.addLayout(self.vboxLayout)

        self.vboxLayout1 = QVBoxLayout()
        self.vboxLayout1.setObjectName(u"vboxLayout1")
        self.label_6 = QLabel(self.tab_video)
        self.label_6.setObjectName(u"label_6")

        self.vboxLayout1.addWidget(self.label_6)

        self.combo_encoder = QComboBox(self.tab_video)
        self.combo_encoder.setObjectName(u"combo_encoder")

        self.vboxLayout1.addWidget(self.combo_encoder)


        self.horizontalLayout_codecs.addLayout(self.vboxLayout1)


        self.verticalLayout_video.addLayout(self.horizontalLayout_codecs)

        self.check_mute_audio = QCheckBox(self.tab_video)
        self.check_mute_audio.setObjectName(u"check_mute_audio")

        self.verticalLayout_video.addWidget(self.check_mute_audio)

        self.vs2 = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_video.addItem(self.vs2)

        self.settings_tabs.addTab(self.tab_video, "")
        self.tab_audio = QWidget()
        self.tab_audio.setObjectName(u"tab_audio")
        self.verticalLayout_audio = QVBoxLayout(self.tab_audio)
        self.verticalLayout_audio.setSpacing(15)
        self.verticalLayout_audio.setObjectName(u"verticalLayout_audio")
        self.frame_audio_settings = QFrame(self.tab_audio)
        self.frame_audio_settings.setObjectName(u"frame_audio_settings")
        self.gridLayout_audio = QGridLayout(self.frame_audio_settings)
        self.gridLayout_audio.setObjectName(u"gridLayout_audio")
        self.label_audio_format = QLabel(self.frame_audio_settings)
        self.label_audio_format.setObjectName(u"label_audio_format")

        self.gridLayout_audio.addWidget(self.label_audio_format, 0, 0, 1, 1)

        self.combo_audio_format = QComboBox(self.frame_audio_settings)
        self.combo_audio_format.addItem("")
        self.combo_audio_format.addItem("")
        self.combo_audio_format.setObjectName(u"combo_audio_format")

        self.gridLayout_audio.addWidget(self.combo_audio_format, 0, 1, 1, 1)

        self.label_audio_bitrate = QLabel(self.frame_audio_settings)
        self.label_audio_bitrate.setObjectName(u"label_audio_bitrate")

        self.gridLayout_audio.addWidget(self.label_audio_bitrate, 1, 0, 1, 1)

        self.combo_audio_bitrate = QComboBox(self.frame_audio_settings)
        self.combo_audio_bitrate.setObjectName(u"combo_audio_bitrate")

        self.gridLayout_audio.addWidget(self.combo_audio_bitrate, 1, 1, 1, 1)


        self.verticalLayout_audio.addWidget(self.frame_audio_settings)

        self.check_audio_only = QCheckBox(self.tab_audio)
        self.check_audio_only.setObjectName(u"check_audio_only")

        self.verticalLayout_audio.addWidget(self.check_audio_only)

        self.vs3 = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_audio.addItem(self.vs3)

        self.settings_tabs.addTab(self.tab_audio, "")
        self.tab_export = QWidget()
        self.tab_export.setObjectName(u"tab_export")
        self.verticalLayout_export = QVBoxLayout(self.tab_export)
        self.verticalLayout_export.setObjectName(u"verticalLayout_export")
        self.group_summary = QGroupBox(self.tab_export)
        self.group_summary.setObjectName(u"group_summary")
        self.group_summary.setFont(font1)
        self.verticalLayout_summary = QVBoxLayout(self.group_summary)
        self.verticalLayout_summary.setObjectName(u"verticalLayout_summary")
        self.label_detailed_summary = QLabel(self.group_summary)
        self.label_detailed_summary.setObjectName(u"label_detailed_summary")
        font2 = QFont()
        font2.setBold(False)
        self.label_detailed_summary.setFont(font2)

        self.verticalLayout_summary.addWidget(self.label_detailed_summary)


        self.verticalLayout_export.addWidget(self.group_summary)

        self.label_10 = QLabel(self.tab_export)
        self.label_10.setObjectName(u"label_10")

        self.verticalLayout_export.addWidget(self.label_10)

        self.input_filename = QLineEdit(self.tab_export)
        self.input_filename.setObjectName(u"input_filename")

        self.verticalLayout_export.addWidget(self.input_filename)

        self.destination_button = QPushButton(self.tab_export)
        self.destination_button.setObjectName(u"destination_button")
        self.destination_button.setMinimumSize(QSize(0, 30))

        self.verticalLayout_export.addWidget(self.destination_button)

        self.label_location = QLabel(self.tab_export)
        self.label_location.setObjectName(u"label_location")
        font3 = QFont()
        font3.setPointSize(9)
        self.label_location.setFont(font3)
        self.label_location.setWordWrap(True)

        self.verticalLayout_export.addWidget(self.label_location)

        self.vs4 = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_export.addItem(self.vs4)

        self.settings_tabs.addTab(self.tab_export, "")

        self.verticalLayout_right.addWidget(self.settings_tabs)

        self.frame_status = QFrame(self.right_panel)
        self.frame_status.setObjectName(u"frame_status")
        self.frame_status.setFrameShape(QFrame.Shape.StyledPanel)
        self.verticalLayout_status = QVBoxLayout(self.frame_status)
        self.verticalLayout_status.setObjectName(u"verticalLayout_status")
        self.label_short_summary = QLabel(self.frame_status)
        self.label_short_summary.setObjectName(u"label_short_summary")
        self.label_short_summary.setFont(font1)

        self.verticalLayout_status.addWidget(self.label_short_summary)

        self.horizontalLayout_progress = QHBoxLayout()
        self.horizontalLayout_progress.setObjectName(u"horizontalLayout_progress")
        self.label_status = QLabel(self.frame_status)
        self.label_status.setObjectName(u"label_status")

        self.horizontalLayout_progress.addWidget(self.label_status)

        self.progress_render = QProgressBar(self.frame_status)
        self.progress_render.setObjectName(u"progress_render")
        self.progress_render.setValue(0)

        self.horizontalLayout_progress.addWidget(self.progress_render)


        self.verticalLayout_status.addLayout(self.horizontalLayout_progress)

        self.horizontalLayout_buttons = QHBoxLayout()
        self.horizontalLayout_buttons.setObjectName(u"horizontalLayout_buttons")
        self.btn_start = QPushButton(self.frame_status)
        self.btn_start.setObjectName(u"btn_start")
        self.btn_start.setMinimumSize(QSize(150, 35))

        self.horizontalLayout_buttons.addWidget(self.btn_start)

        self.btn_pause = QPushButton(self.frame_status)
        self.btn_pause.setObjectName(u"btn_pause")
        self.btn_pause.setMinimumSize(QSize(0, 35))

        self.horizontalLayout_buttons.addWidget(self.btn_pause)

        self.btn_cancel = QPushButton(self.frame_status)
        self.btn_cancel.setObjectName(u"btn_cancel")
        self.btn_cancel.setMinimumSize(QSize(0, 35))

        self.horizontalLayout_buttons.addWidget(self.btn_cancel)

        self.btn_logs = QPushButton(self.frame_status)
        self.btn_logs.setObjectName(u"btn_logs")
        self.btn_logs.setMinimumSize(QSize(0, 35))

        self.horizontalLayout_buttons.addWidget(self.btn_logs)


        self.verticalLayout_status.addLayout(self.horizontalLayout_buttons)


        self.verticalLayout_right.addWidget(self.frame_status)

        self.main_splitter.addWidget(self.right_panel)

        self.horizontalLayout_main.addWidget(self.main_splitter)


        self.retranslateUi(Dialog)

        self.settings_tabs.setCurrentIndex(2)


        QMetaObject.connectSlotsByName(Dialog)
    # setupUi

    def retranslateUi(self, Dialog):
        Dialog.setWindowTitle(QCoreApplication.translate("Dialog", u"Steempeg v10", None))
        self.main_splitter.setStyleSheet(QCoreApplication.translate("Dialog", u"QSplitter::handle { background-color: #444; margin: 0px 2px; border-radius: 2px; } QSplitter::handle:hover { background-color: #666; }", None))
        self.label_13.setText(QCoreApplication.translate("Dialog", u"\U0001f4c1 Clips Library", None))
        self.btn_browse.setText(QCoreApplication.translate("Dialog", u"Choose Folder...", None))
        self.btn_about.setText(QCoreApplication.translate("Dialog", u"\u2139\ufe0f About", None))
        self.btn_update_check.setText(QCoreApplication.translate("Dialog", u"\U0001f504 Check for updates", None))
        self.video_container.setStyleSheet(QCoreApplication.translate("Dialog", u"background-color: #000000; border: 1px solid #333; border-radius: 6px;", None))
        self.btn_skip_back.setText(QCoreApplication.translate("Dialog", u"\u23ea", None))
        self.btn_play.setText(QCoreApplication.translate("Dialog", u"\u25b6 Play", None))
        self.btn_skip_forward.setText(QCoreApplication.translate("Dialog", u"\u23e9", None))
        self.label_time.setText(QCoreApplication.translate("Dialog", u"00:00 / 00:00", None))
        self.source_label.setText(QCoreApplication.translate("Dialog", u"Source:", None))
        self.orig_res_label.setText(QCoreApplication.translate("Dialog", u"Original resolution:", None))
        self.label_duration.setText(QCoreApplication.translate("Dialog", u"Time:", None))
        self.label_fps.setText(QCoreApplication.translate("Dialog", u"FPS:", None))
        self.label_size.setText(QCoreApplication.translate("Dialog", u"Size:", None))
        self.settings_tabs.setTabText(self.settings_tabs.indexOf(self.tab_source), QCoreApplication.translate("Dialog", u"\u2139\ufe0f Source Info", None))
        self.label_2.setText(QCoreApplication.translate("Dialog", u"Quality Preset", None))
        self.label_target_size.setText(QCoreApplication.translate("Dialog", u"Target Size", None))
        self.label_5.setText(QCoreApplication.translate("Dialog", u"Framerate (FPS)", None))
        self.label_4.setText(QCoreApplication.translate("Dialog", u"Bitrate", None))
        self.label_14.setText(QCoreApplication.translate("Dialog", u"Codec", None))
        self.label_6.setText(QCoreApplication.translate("Dialog", u"Hardware Encoder", None))
        self.check_mute_audio.setText(QCoreApplication.translate("Dialog", u"\U0001f507 Disable Audio (Video Only)", None))
        self.settings_tabs.setTabText(self.settings_tabs.indexOf(self.tab_video), QCoreApplication.translate("Dialog", u"\U0001f39e Video Settings", None))
        self.label_audio_format.setText(QCoreApplication.translate("Dialog", u"Format:", None))
        self.combo_audio_format.setItemText(0, QCoreApplication.translate("Dialog", u"AAC", None))
        self.combo_audio_format.setItemText(1, QCoreApplication.translate("Dialog", u"MP3", None))

        self.label_audio_bitrate.setText(QCoreApplication.translate("Dialog", u"Bitrate:", None))
        self.check_audio_only.setText(QCoreApplication.translate("Dialog", u"\U0001f39e\U0000fe0f Disable Video (Extract Audio Only)", None))
        self.settings_tabs.setTabText(self.settings_tabs.indexOf(self.tab_audio), QCoreApplication.translate("Dialog", u"\U0001f3b5 Audio Settings", None))
        self.group_summary.setTitle(QCoreApplication.translate("Dialog", u"Final Render Details", None))
        self.label_detailed_summary.setText(QCoreApplication.translate("Dialog", u"...", None))
        self.label_10.setText(QCoreApplication.translate("Dialog", u"Output File Name", None))
        self.destination_button.setText(QCoreApplication.translate("Dialog", u"Choose Destination Folder...", None))
        self.label_location.setText(QCoreApplication.translate("Dialog", u"Location: ...", None))
        self.settings_tabs.setTabText(self.settings_tabs.indexOf(self.tab_export), QCoreApplication.translate("Dialog", u"\U0001f4be Export Settings", None))
        self.frame_status.setStyleSheet(QCoreApplication.translate("Dialog", u"QFrame { background-color: rgba(255, 255, 255, 0.05); border-radius: 6px; padding: 5px; }", None))
        self.label_short_summary.setText(QCoreApplication.translate("Dialog", u"Select a clip to begin...", None))
        self.label_status.setText(QCoreApplication.translate("Dialog", u"Ready", None))
        self.btn_start.setStyleSheet(QCoreApplication.translate("Dialog", u"background-color: #2e7d32; color: white; font-weight: bold; border-radius: 4px;", None))
        self.btn_start.setText(QCoreApplication.translate("Dialog", u"\U0001f6a9 START RENDER", None))
        self.btn_pause.setText(QCoreApplication.translate("Dialog", u"Pause", None))
        self.btn_cancel.setText(QCoreApplication.translate("Dialog", u"Cancel", None))
        self.btn_logs.setText(QCoreApplication.translate("Dialog", u"Logs", None))
    # retranslateUi

