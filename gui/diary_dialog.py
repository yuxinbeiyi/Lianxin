"""
gui/diary_dialog.py - 日记查看对话框（支持搜索和日期筛选）
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                             QScrollArea, QWidget, QLabel, QCheckBox, QMessageBox,
                             QTextEdit, QLineEdit, QDateEdit, QComboBox, QSpinBox,
                             QTimeEdit, QFrame, QGroupBox)
from PyQt5.QtCore import Qt, pyqtSignal, QDate, QTime
from PyQt5.QtGui import QFont
from utils.diary import get_all_diaries, get_diary_count, init_diary_db
from utils.settings import get_settings
from config import get_diary_config, save_diary_config
import random
import pygame
from pathlib import Path
from datetime import datetime

class DiaryDialog(QDialog):
    diary_changed = pyqtSignal()

    def __init__(self, parent=None, main_window=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window)
        self.setWindowTitle("📔 莲心日记")
        self.resize(700, 600)
        self.setMinimumSize(500, 450)
        self._all_diaries = []  # 存储所有日记原始数据
        self._main_window = main_window  # 主窗口引用，用于回响功能
        self._setup_ui()
        self._load_diaries()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # 第一行：标题栏 + 日记总数 + 自动语音复选框
        title_bar = QHBoxLayout()
        title = QLabel("莲心日记")
        title.setFont(QFont("Microsoft YaHei UI", 12, QFont.Bold))
        title.setStyleSheet("color: #6B3A1F;")
        title_bar.addWidget(title)

        self.total_count_label = QLabel()
        self.total_count_label.setFont(QFont("Microsoft YaHei UI", 9))
        self.total_count_label.setStyleSheet("color: #8B5A2B;")
        title_bar.addWidget(self.total_count_label)

        title_bar.addStretch()
        self.auto_voice_cb = QCheckBox("🔊 自动语音")
        self.auto_voice_cb.setChecked(False)
        self.auto_voice_cb.setStyleSheet("color: #6B3A1F; background-color: #F5E6C8; padding: 2px 6px; border-radius: 4px;")
        title_bar.addWidget(self.auto_voice_cb)
        main_layout.addLayout(title_bar)

        # 第二行：搜索和筛选栏
        search_layout = QHBoxLayout()
        search_layout.setSpacing(8)

        search_label = QLabel("🔍 搜索：")
        search_label.setFont(QFont("Microsoft YaHei UI", 9))
        search_label.setStyleSheet("color: #6B3A1F;")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入关键词，搜索日记内容...")
        self.search_input.setFont(QFont("Microsoft YaHei UI", 9))
        self.search_input.setMinimumWidth(200)
        self.search_input.textChanged.connect(self._filter_diaries)

        date_label = QLabel("📅 日期：")
        date_label.setFont(QFont("Microsoft YaHei UI", 9))
        date_label.setStyleSheet("color: #6B3A1F;")
        self.date_filter = QDateEdit()
        self.date_filter.setCalendarPopup(True)
        self.date_filter.setDisplayFormat("yyyy-MM-dd")
        self.date_filter.setSpecialValueText("全部日期")
        self.date_filter.setDate(QDate(2000, 1, 1))
        self.date_filter.dateChanged.connect(self._filter_diaries)

        clear_btn = QPushButton("清除筛选")
        clear_btn.setFixedSize(80, 28)
        clear_btn.setFont(QFont("Microsoft YaHei UI", 8))
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #E8D8C0;
                color: #6B3A1F;
                border-radius: 5px;
                border: none;
            }
            QPushButton:hover {
                background-color: #D8C8A0;
            }
        """)
        clear_btn.clicked.connect(self._clear_filters)

        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(date_label)
        search_layout.addWidget(self.date_filter)
        search_layout.addWidget(clear_btn)
        search_layout.addStretch()
        main_layout.addLayout(search_layout)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical {
                width: 10px;
                background: #F5E6C8;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #D8C8A0;
                border-radius: 5px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #C0A880;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("background: transparent;")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setAlignment(Qt.AlignTop)
        self.content_layout.setSpacing(12)
        scroll.setWidget(self.content_widget)
        main_layout.addWidget(scroll)

        # 操作按钮
        btn_layout = QHBoxLayout()

        write_now_btn = QPushButton("✏️ 立即生成今天的日记")
        write_now_btn.setFixedSize(180, 30)
        write_now_btn.setStyleSheet("""
            QPushButton {
                background-color: #6C7BFF;
                color: white;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover  { background-color: #5A6AEE; }
        """)
        write_now_btn.clicked.connect(self._on_write_now)
        btn_layout.addWidget(write_now_btn)

        settings_btn = QPushButton("⚙️ 设置")
        settings_btn.setFixedSize(80, 30)
        settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #E8D8C0;
                color: #000000;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover { background-color: #D8C8A0; }
        """)
        settings_btn.clicked.connect(self._on_diary_settings)
        btn_layout.addWidget(settings_btn)

        btn_layout.addStretch()

        close_btn = QPushButton("关闭")
        close_btn.setFixedSize(80, 30)
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        main_layout.addLayout(btn_layout)

        # 应用全局字体大小
        settings = get_settings()
        font_size = settings.font_size
        self.setFont(QFont("Microsoft YaHei UI", font_size))

        # ========== 设置背景图片 ==========
        from pathlib import Path
        from utils.resource_path import get_asset_path
        bg_path = get_asset_path("莲心日记本.jpg")
        if bg_path.exists():
            self.setStyleSheet(f"""
                QDialog {{
                    background-image: url("{str(bg_path).replace(chr(92), '/')}");
                    background-position: center;
                    background-repeat: no-repeat;
                    background-color: #FDF8F0;
                }}
                QScrollArea, QLabel, QLineEdit, QDateEdit, QPushButton {{
                    background-color: rgba(253, 248, 240, 220);
                    color: #4A2A1A;
                    border-radius: 5px;
                }}
                QPushButton {{
                    background-color: #E8D8C0;
                    color: #4A2A1A;
                    border-radius: 6px;
                    border: none;
                    padding: 6px 12px;
                }}
                QPushButton:hover {{ background-color: #D8C8A0; }}
            """)



    def _clear_filters(self):
        """清除所有筛选条件"""
        self.search_input.clear()
        self.date_filter.setDate(QDate(2000, 1, 1))  # 特殊值代表全部
        # 触发重新筛选（上面两个操作会自动触发 textChanged 和 dateChanged）

    def _filter_diaries(self):
        """根据搜索关键词和日期筛选日记"""
        keyword = self.search_input.text().strip().lower()
        selected_date = self.date_filter.date()
        # 判断是否选择了具体日期（年份大于2000）
        has_date_filter = selected_date.year() > 2000
        target_date_str = selected_date.toString("yyyy-MM-dd") if has_date_filter else None
        
        # 清空当前显示
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # 筛选日记
        filtered = []
        for diary in self._all_diaries:
            # 日期筛选
            if has_date_filter and diary["date"] != target_date_str:
                continue
            # 关键词筛选（匹配正文、天气、情绪天气）
            if keyword:
                content_match = keyword in diary["content"].lower()
                weather_match = keyword in diary.get("weather", "").lower()
                if not (content_match or weather_match):
                    continue
            filtered.append(diary)
        
        # 更新总数显示
        if has_date_filter or keyword:
            self.total_count_label.setText(f"（筛选出 {len(filtered)} / {len(self._all_diaries)} 篇）")
        else:
            self.total_count_label.setText(f"（共 {len(self._all_diaries)} 篇）")
        
        if not filtered:
            empty_label = QLabel("没有找到符合条件的日记。")
            empty_label.setAlignment(Qt.AlignCenter)
            empty_label.setStyleSheet("color: #FFFFFF; padding: 40px;")

            self.content_layout.addWidget(empty_label)
            return
        
        # 显示筛选后的日记，高亮关键词
        for diary in filtered:
            card = self._create_diary_card(diary, highlight_keyword=keyword if keyword else None)
            self.content_layout.addWidget(card)
        self.content_layout.addStretch()

    def _load_diaries(self):
        """加载所有日记原始数据"""
        self._all_diaries = get_all_diaries()
        # 重新应用筛选（显示全部）
        self._filter_diaries()

    def _create_diary_card(self, diary, highlight_keyword=None):
        settings = get_settings()
        base_font_size = settings.font_size

        card = QWidget()
        card.setCursor(Qt.PointingHandCursor)
        card.setToolTip("双击卡片展开完整日记")  # 鼠标悬停提示
        card.setStyleSheet("""
            QWidget {
                background-color: #FFF8F0;
                border-radius: 12px;
                border: 1px solid #E8D8C0;
            }
        """)
        
        # 高亮背景（如果有关键词匹配）
        if highlight_keyword:
            content_lower = diary["content"].lower()
            weather_lower = diary.get("weather", "").lower()
            if highlight_keyword in content_lower or highlight_keyword in weather_lower:
                card.setStyleSheet("""
                    QWidget {
                        background-color: #FFE8B0;
                        border-radius: 12px;
                        border: 2px solid #FFB347;
                    }
                """)
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # 日期和天气行
        header = QHBoxLayout()
        date_label = QLabel(diary["date"])
        date_label.setFont(QFont("Microsoft YaHei UI", base_font_size + 1, QFont.Bold))
        date_label.setStyleSheet("color: #8B5A2B;")
        weather_label = QLabel(diary.get("weather", ""))
        weather_label.setFont(QFont("Segoe UI Emoji", base_font_size))
        header.addWidget(date_label)
        header.addWidget(weather_label)
        header.addStretch()
        layout.addLayout(header)

        # 正文摘要
        content = diary["content"]
        if len(content) > 100:
            summary = content[:100] + "..."
        else:
            summary = content
        content_label = QLabel(summary)
        content_label.setWordWrap(True)
        content_label.setFont(QFont("Microsoft YaHei UI", base_font_size))
        content_label.setStyleSheet("color: #4A2A1A; margin: 4px 0;")
        layout.addWidget(content_label)

        # 按钮行
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        echo_btn = QPushButton("💬 回响")
        echo_btn.setFixedSize(80, 28)
        echo_btn.setFont(QFont("Microsoft YaHei UI", base_font_size - 1))
        echo_btn.setStyleSheet("background: #E8D8C0; border-radius: 5px;")
        echo_btn.clicked.connect(lambda: self._on_echo(diary))
        btn_layout.addWidget(echo_btn)

        rewrite_btn = QPushButton("🔄 重写")
        rewrite_btn.setFixedSize(80, 28)
        rewrite_btn.setFont(QFont("Microsoft YaHei UI", base_font_size - 1))
        rewrite_btn.setStyleSheet("background: #F0E0C8; border-radius: 5px;")
        rewrite_btn.clicked.connect(lambda: self._on_rewrite(diary["date"]))
        btn_layout.addWidget(rewrite_btn)
        layout.addLayout(btn_layout)

        # 新增提示标签：双击展开完整日记
        tip_label = QLabel("💡 双击卡片展开完整日记")
        tip_label.setFont(QFont("Microsoft YaHei UI", base_font_size - 2))
        tip_label.setStyleSheet("color: #6B3A1F; padding-top: 4px;")
        tip_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(tip_label)

        # 双击卡片展开完整内容
        card.mouseDoubleClickEvent = lambda event: self._show_full_content(content)
        return card

    def _on_echo(self, diary):
        if diary.get("echo_text"):
            if self._main_window is None:
                QMessageBox.warning(self, "错误", "无法连接到主窗口，请重启莲心。")
                return
            self._main_window._chat_widget.add_ai_message(diary["echo_text"])
            if self.auto_voice_cb.isChecked():
                self._main_window._speak(diary["echo_text"])
        else:
            QMessageBox.information(self, "提示", "这条日记没有回响语。")

    def _on_rewrite(self, date_str):
        reply = QMessageBox.question(self, "重写日记", f"确定要重新生成 {date_str} 的日记吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.diary_changed.emit()
            self.accept()
            if self._main_window:
                self._main_window.regenerate_diary_by_date(date_str)

    def _show_full_content(self, content):
        # 播放随机翻页音效
        try:
            # 确保 pygame.mixer 已初始化
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            from utils.resource_path import get_asset_path
            sound_dir = get_asset_path("sound")
            page_files = ["page1.mp3", "page2.mp3"]
            selected = random.choice(page_files)
            sound_path = sound_dir / selected
            if sound_path.exists():
                pygame.mixer.Sound(str(sound_path)).play()
            else:
                print(f"[翻页音效] 文件不存在: {sound_path}")
        except Exception as e:
            print(f"[翻页音效] 播放失败: {e}")

        dialog = QDialog(self)
        dialog.setWindowTitle("完整日记")
        dialog.setMinimumSize(500, 400)
        dialog.resize(550, 450)
        
        dialog.setStyleSheet("""
            QDialog {
                background-color: #FDF8F0;
                border-radius: 8px;
            }
        """)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        
        text_edit = QTextEdit()
        text_edit.setPlainText(content)
        text_edit.setReadOnly(True)
        text_edit.setFont(QFont("Microsoft YaHei UI", 12))
        text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #FFF8F0;
                color: #4A2A1A;
                border: 1px solid #E8D8C0;
                border-radius: 8px;
                padding: 12px;
                font-size: 12pt;
            }
            QTextEdit:focus {
                border: 1px solid #D8C8A0;
            }
        """)
        layout.addWidget(text_edit)
        
        btn = QPushButton("关闭")
        btn.setFixedSize(80, 30)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #E8D8C0;
                color: #D8C8A0;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #D8C8A0;
            }
        """)
        btn.clicked.connect(dialog.accept)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(btn)
        layout.addLayout(btn_layout)
        
        dialog.exec_()

    def _on_write_now(self):
        """立即生成今天的日记。"""
        from PyQt5.QtWidgets import QMessageBox
        if self._main_window is None:
            return
        # 检查是否已有今天的日记
        if self._main_window._has_today_diary():
            reply = QMessageBox.question(
                self, "确认", "今天的日记已经存在，是否重新生成？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        QMessageBox.information(self, "提示", "正在生成今天的日记，请稍候...")
        self._main_window._write_diary_now()


    def _on_diary_settings(self):
        """打开日记设置对话框。"""
        dlg = DiarySettingsDialog(self, main_window=self._main_window)
        dlg.diary_config_changed.connect(self.diary_changed.emit)
        if self._main_window:
            dlg.diary_config_changed.connect(self._main_window._setup_diary_timer)
        dlg.exec_()


class DiarySettingsDialog(QDialog):
    """日记设置对话框：消息方向、参考条数、定时生成、重新生成等。"""
    diary_config_changed = pyqtSignal()

    def __init__(self, parent=None, main_window=None):
        super().__init__(parent)
        self._main_window = main_window
        self.setWindowTitle("日记设置")
        self.setMinimumSize(440, 420)
        self.setModal(True)
        self.setStyleSheet("""
            QDialog {
                background-color: #FDF8F0;
            }
            QLabel {
                color: #6B3A1F;
            }
            QCheckBox {
                color: #6B3A1F;
                background-color: #F5E6C8;
                padding: 4px 8px;
                border-radius: 4px;
            }
            QComboBox {
                background-color: #F5E6C8;
                color: #4A2A1A;
                border: 1px solid #D8C8A0;
                border-radius: 4px;
                padding: 2px 6px;
            }
            QComboBox QAbstractItemView {
                background-color: #FDF8F0;
                color: #4A2A1A;
                selection-background-color: #E8D8C0;
                selection-color: #4A2A1A;
                outline: none;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: #E8D8C0;
                color: #4A2A1A;
            }
            QComboBox QAbstractItemView::item:selected {
                background-color: #D8C8A0;
                color: #4A2A1A;
            }
            QSpinBox {
                background-color: #F5E6C8;
                color: #4A2A1A;
                border: 1px solid #D8C8A0;
                border-radius: 4px;
                padding: 2px 4px;
            }
            QTimeEdit {
                background-color: #F5E6C8;
                color: #4A2A1A;
                border: 1px solid #D8C8A0;
                border-radius: 4px;
                padding: 2px 4px;
            }
            QDateEdit {
                background-color: #F5E6C8;
                color: #4A2A1A;
                border: 1px solid #D8C8A0;
                border-radius: 4px;
                padding: 2px 4px;
            }
            QPushButton {
                color: #4A2A1A;
            }
        """)
        self._load_config()
        self._build_ui()
        self._init_ui()

    def _load_config(self):
        cfg = get_diary_config()
        self._diary_direction = cfg.get("direction", "latest")
        self._diary_max_messages = cfg.get("max_messages", 30)
        self._diary_scheduled_enabled = cfg.get("scheduled_enabled", True)
        self._diary_scheduled_time = cfg.get("scheduled_time", "23:55")

    def _save_config(self):
        save_diary_config({
            "direction": self._diary_direction,
            "max_messages": self._diary_max_messages,
            "scheduled_enabled": self._diary_scheduled_enabled,
            "scheduled_time": self._diary_scheduled_time,
        })

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(18, 18, 18, 18)

        # 消息方向
        dir_frame = self._create_frame()
        dir_layout = QHBoxLayout(dir_frame)
        dir_layout.addWidget(QLabel("日记生成使用消息方向："))
        self._dir_combo = QComboBox()
        self._dir_combo.addItem("取当天最早消息", "earliest")
        self._dir_combo.addItem("取当天最晚消息", "latest")
        dir_layout.addWidget(self._dir_combo)
        dir_layout.addStretch()
        layout.addWidget(dir_frame)

        # 消息条数
        count_frame = self._create_frame()
        count_layout = QHBoxLayout(count_frame)
        count_layout.addWidget(QLabel("参考消息条数："))
        self._msg_spin = QSpinBox()
        self._msg_spin.setRange(1, 9999)
        self._msg_spin.setValue(30)
        count_layout.addWidget(self._msg_spin)
        count_layout.addStretch()
        layout.addWidget(count_frame)

        # 定时写日记
        sched_frame = self._create_frame()
        sched_layout = QVBoxLayout(sched_frame)
        sched_layout.setSpacing(8)
        self._sched_cb = QCheckBox("启用定时写日记（每天自动生成）")
        sched_layout.addWidget(self._sched_cb)
        time_layout = QHBoxLayout()
        time_layout.addWidget(QLabel("每天生成时间："))
        self._time_edit = QTimeEdit()
        self._time_edit.setDisplayFormat("HH:mm")
        time_layout.addWidget(self._time_edit)
        time_layout.addStretch()
        sched_layout.addLayout(time_layout)
        sched_note = QLabel("莲心会在设定时间自动写日记（如果当天已有则不会重复生成）")
        sched_note.setWordWrap(True)
        sched_note.setFont(QFont("Microsoft YaHei UI", 8))
        
        sched_layout.addWidget(sched_note)
        layout.addWidget(sched_frame)

        # 重新生成
        regen_frame = self._create_frame()
        regen_layout = QHBoxLayout(regen_frame)
        regen_layout.addWidget(QLabel("重新生成日期："))
        self._regen_date = QDateEdit()
        self._regen_date.setCalendarPopup(True)
        self._regen_date.setDate(QDate.currentDate())
        self._regen_date.setDisplayFormat("yyyy-MM-dd")
        regen_layout.addWidget(self._regen_date)
        regen_btn = QPushButton("重新生成")
        regen_btn.setCursor(Qt.PointingHandCursor)
        regen_btn.clicked.connect(self._on_regenerate)
        regen_layout.addWidget(regen_btn)
        regen_layout.addStretch()
        layout.addWidget(regen_frame)

        # 日记总数
        count_label_layout = QHBoxLayout()
        self._count_label = QLabel()
        count_label_layout.addWidget(self._count_label)
        count_label_layout.addStretch()
        layout.addLayout(count_label_layout)

        layout.addStretch()

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(80, 32)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        save_btn = QPushButton("保存")
        save_btn.setFixedSize(80, 32)
        save_btn.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #6C7BFF;
                color: white;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover { background-color: #5A6AEE; }
        """)
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def _create_frame(self):
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: #F5E6C8;
                border-radius: 8px;
                border: 1px solid #D8C8A0;
            }
        """)
        return frame

    def _init_ui(self):
        idx = self._dir_combo.findData(self._diary_direction)
        if idx >= 0:
            self._dir_combo.setCurrentIndex(idx)
        self._msg_spin.setValue(self._diary_max_messages)
        self._sched_cb.setChecked(self._diary_scheduled_enabled)
        time_parts = self._diary_scheduled_time.split(":")
        if len(time_parts) == 2:
            self._time_edit.setTime(QTime(int(time_parts[0]), int(time_parts[1])))
        else:
            self._time_edit.setTime(QTime(23, 55))
        init_diary_db()
        self._count_label.setText(f"当前日记总数：{get_diary_count()} 篇")

    def _on_save(self):
        self._diary_direction = self._dir_combo.currentData()
        self._diary_max_messages = self._msg_spin.value()
        self._diary_scheduled_enabled = self._sched_cb.isChecked()
        self._diary_scheduled_time = self._time_edit.time().toString("HH:mm")
        self._save_config()
        self.diary_config_changed.emit()
        self.accept()

    def _on_regenerate(self):
        date = self._regen_date.date().toString("yyyy-MM-dd")
        if self._main_window:
            self._main_window.regenerate_diary_by_date(date)
            QMessageBox.information(self, "提示", f"开始重新生成 {date} 的日记，请稍后查看结果。")
        else:
            QMessageBox.warning(self, "提示", "无法直接触发，请重启莲心后再试。")