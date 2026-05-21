"""
gui/diary_dialog.py - 日记查看对话框（支持搜索和日期筛选）
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                             QScrollArea, QWidget, QLabel, QCheckBox, QMessageBox,
                             QTextEdit, QLineEdit, QDateEdit)
from PyQt5.QtCore import Qt, pyqtSignal, QDate
from PyQt5.QtGui import QFont
from utils.diary import get_all_diaries
from utils.settings import get_settings
import random
import pygame
from pathlib import Path

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
        title_bar.addWidget(title)

        self.total_count_label = QLabel()
        self.total_count_label.setFont(QFont("Microsoft YaHei UI", 9))
        self.total_count_label.setStyleSheet("color: #8B5A2B;")
        title_bar.addWidget(self.total_count_label)

        title_bar.addStretch()
        self.auto_voice_cb = QCheckBox("🔊 自动语音")
        self.auto_voice_cb.setChecked(False)
        title_bar.addWidget(self.auto_voice_cb)
        main_layout.addLayout(title_bar)

        # 第二行：搜索和筛选栏
        search_layout = QHBoxLayout()
        search_layout.setSpacing(8)

        search_label = QLabel("🔍 搜索：")
        search_label.setFont(QFont("Microsoft YaHei UI", 9))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入关键词，搜索日记内容...")
        self.search_input.setFont(QFont("Microsoft YaHei UI", 9))
        self.search_input.setMinimumWidth(200)
        self.search_input.textChanged.connect(self._filter_diaries)

        date_label = QLabel("📅 日期：")
        date_label.setFont(QFont("Microsoft YaHei UI", 9))
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
                color: #4A2A1A;
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
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("background: transparent;")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setAlignment(Qt.AlignTop)
        self.content_layout.setSpacing(12)
        scroll.setWidget(self.content_widget)
        main_layout.addWidget(scroll)

        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.setFixedSize(80, 30)
        close_btn.clicked.connect(self.accept)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        main_layout.addLayout(btn_layout)

        # 应用全局字体大小
        settings = get_settings()
        font_size = settings.font_size
        self.setFont(QFont("Microsoft YaHei UI", font_size))

        # ========== 设置背景图片 ==========
        from pathlib import Path
        bg_path = Path(__file__).parent.parent / "assets" / "莲心日记本.jpg"
        if bg_path.exists():
            img_url = bg_path.as_posix()  # 转为 Unix 风格路径
            self.setStyleSheet(f"""
                QDialog {{
                    background-image: url("{img_url}");
                    background-position: center;
                    background-repeat: no-repeat;
                    background-attachment: fixed;
                    background-color: #FDF8F0;
                }}
                QScrollArea, QLabel, QLineEdit, QDateEdit, QPushButton {{
                    background-color: rgba(253, 248, 240, 220);
                    border-radius: 5px;
                }}
                QCheckBox {{
                    background-color: transparent;
                }}
                QScrollArea {{
                    background: transparent;
                    border: none;
                }}
            """)
        else:
            self.setStyleSheet("background-color: #FDF8F0;")



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
            empty_label.setStyleSheet("color: #A0522D; padding: 40px;")
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
        tip_label.setStyleSheet("color: #A0A0A0; padding-top: 4px;")
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
            sound_dir = Path(__file__).parent.parent / "assets" / "sound"
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
                color: #4A2A1A;
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