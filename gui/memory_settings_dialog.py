# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QSpinBox,QWidget,
    QPushButton, QScrollArea, QFrame, QLineEdit, QFileDialog, QComboBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from config import get_memory_config, save_memory_config


class MemorySettingsDialog(QDialog):
    """记忆系统独立设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mem_cfg = get_memory_config()

        self.setWindowTitle("🧠 记忆系统设置")
        self.setMinimumSize(500, 420)
        self.resize(520, 460)
        self.setModal(True)
        self.setStyleSheet("background-color: #F8F8FC;")
        self._build_ui()
        self._load_from_config()

    def _create_frame(self):
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: #F0F2F7;
                border-radius: 8px;
                border: 1px solid #E0E0E8;
            }
        """)
        return frame

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 16, 20, 16)

        # 标题
        title = QLabel("🧠 记忆系统设置")
        title.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
        title.setStyleSheet("color: #3A3A5C;")
        layout.addWidget(title)

        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #E0E0E8; max-height: 1px;")
        layout.addWidget(line)

        # 滚动区域（保留扩展性）
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(14)
        scroll_layout.setContentsMargins(0, 0, 0, 0)

        # 自动提取开关
        auto_frame = self._create_frame()
        auto_vbox = QVBoxLayout(auto_frame)
        auto_vbox.setSpacing(8)
        self._memory_auto_cb = QCheckBox("自动提取对话记忆")
        self._memory_auto_cb.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        auto_vbox.addWidget(self._memory_auto_cb)
        auto_desc = QLabel(
            "开启后，莲心会自动从对话中提取关键信息保存到长期记忆中，\n"
            "下次对话时会根据记忆回忆起你的过往信息。\n"
            "关闭后记忆系统仍然可用，但不会自动新增记忆。"
        )
        auto_desc.setWordWrap(True)
        auto_desc.setStyleSheet("color: #888; font-size: 11px; padding: 4px 0;")
        auto_vbox.addWidget(auto_desc)
        scroll_layout.addWidget(auto_frame)

        # 提取间隔（对话轮数）
        interval_frame = self._create_frame()
        interval_vbox = QVBoxLayout(interval_frame)
        interval_vbox.setSpacing(8)
        interval_title = QLabel("自动提取轮次间隔")
        interval_title.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        interval_vbox.addWidget(interval_title)
        self._memory_extract_interval_spin = QSpinBox()
        self._memory_extract_interval_spin.setRange(1, 30)
        self._memory_extract_interval_spin.setSuffix(" 轮对话")
        interval_vbox.addWidget(self._memory_extract_interval_spin)
        interval_desc = QLabel("每完成 N 轮对话后触发一次自动提取，间隔越小记忆越及时但也越占用Token。")
        interval_desc.setWordWrap(True)
        interval_desc.setStyleSheet("color: #888; font-size: 11px; padding: 4px 0;")
        interval_vbox.addWidget(interval_desc)
        scroll_layout.addWidget(interval_frame)

        # 单次提取最大消息数
        count_frame = self._create_frame()
        count_vbox = QVBoxLayout(count_frame)
        count_vbox.setSpacing(8)
        count_title = QLabel("单次提取最大消息数")
        count_title.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        count_vbox.addWidget(count_title)
        self._memory_extract_msgs_spin = QSpinBox()
        self._memory_extract_msgs_spin.setRange(5, 100)
        self._memory_extract_msgs_spin.setSuffix(" 条")
        count_vbox.addWidget(self._memory_extract_msgs_spin)
        count_desc = QLabel("单次自动提取最多包含多少条最近消息，数值越大包含上下文越多但也越慢。")
        count_desc.setWordWrap(True)
        count_desc.setStyleSheet("color: #888; font-size: 11px; padding: 4px 0;")
        count_vbox.addWidget(count_desc)
        scroll_layout.addWidget(count_frame)

        # 说明
        tip = QLabel(
            "💡 记忆系统保存在 `data/memory.json` 中\n"
            "· 所有记忆会在对话开始时自动检索，并作为上下文提供给模型\n"
            "· 即使关闭自动提取，你仍然可以在「记忆检索」工具中手动查询记忆\n"
            "· 长期记忆是莲心「记住你」的核心，可以让莲心越来越懂你"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #888; font-size: 12px; padding: 8px;")
        scroll_layout.addWidget(tip)

        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedSize(80, 32)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_save = QPushButton("保存")
        btn_save.setFixedSize(80, 32)
        btn_save.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(btn_save)

        layout.addLayout(btn_row)

    def _load_from_config(self):
        self._memory_auto_cb.setChecked(self._mem_cfg.get("auto_extract", True))
        self._memory_extract_interval_spin.setValue(self._mem_cfg.get("extract_interval", 6))
        self._memory_extract_msgs_spin.setValue(self._mem_cfg.get("extract_message_count", 20))

    def _on_save(self):
        cfg = {
            "auto_extract": self._memory_auto_cb.isChecked(),
            "extract_interval": self._memory_extract_interval_spin.value(),
            "extract_message_count": self._memory_extract_msgs_spin.value(),
        }
        save_memory_config(cfg)
        self.accept()
