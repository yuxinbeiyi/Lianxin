"""
AlarmDialog：闹钟/倒计时设置对话框
"""

import os
from datetime import datetime
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QPushButton, QLineEdit, QComboBox, QSpinBox,
    QListWidget, QListWidgetItem, QMessageBox, QFileDialog,
    QGroupBox, QFrame, QCheckBox
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont

from utils.alarm_manager import REPEAT_LABELS, REPEAT_VALUES
from pathlib import Path


class AlarmDialog(QDialog):
    """闹钟/倒计时设置对话框"""

    # 信号：闹钟列表变化时通知主窗口
    alarms_changed = pyqtSignal()

    def __init__(self, alarm_manager, parent=None):
        super().__init__(parent)
        self._manager = alarm_manager  # 使用主窗口传入的实例
        self.setWindowTitle("⏰ 闹钟与倒计时")
        self.setMinimumSize(500, 600)
        self.resize(550, 650)
        self.setModal(False)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._build_ui()
        self._refresh_alarm_list()
        self._refresh_countdown_list()

        # 每秒刷新倒计时显示（只刷新显示，不处理结束事件）
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._refresh_countdown_list)
        self._update_timer.start(1000)

    # ── 界面构建 ─────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # 标题
        title = QLabel("⏰ 闹钟与倒计时")
        title.setFont(QFont("Microsoft YaHei UI", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #5060DD;")
        layout.addWidget(title)

        # 标签页
        self._tab_widget = QTabWidget()
        self._tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #D8D8EE;
                border-radius: 8px;
                background-color: rgba(248, 248, 252, 200);
            }
            QTabBar::tab {
                padding: 6px 16px;
                font-size: 11px;
            }
        """)

        # 闹钟标签页
        alarm_tab = self._build_alarm_tab()
        # 倒计时标签页
        countdown_tab = self._build_countdown_tab()

        self._tab_widget.addTab(alarm_tab, "⏰ 定时闹钟")
        self._tab_widget.addTab(countdown_tab, "⏳ 倒计时")

        layout.addWidget(self._tab_widget)

    def _build_alarm_tab(self):
        """构建闹钟设置标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        # 添加闹钟表单
        form_group = QGroupBox("添加新闹钟")
        form_group.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        form_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #D8D8EE;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
        """)
        form_layout = QVBoxLayout(form_group)

        # 闹钟名称
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("名称："))
        self._alarm_name_edit = QLineEdit()
        self._alarm_name_edit.setPlaceholderText("例如：吃药、开会")
        name_row.addWidget(self._alarm_name_edit)
        form_layout.addLayout(name_row)

        # 时间设置
        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("时间："))
        self._alarm_hour_spin = QSpinBox()
        self._alarm_hour_spin.setRange(0, 23)
        self._alarm_hour_spin.setSuffix(" 时")
        self._alarm_hour_spin.setFixedWidth(80)
        self._alarm_min_spin = QSpinBox()
        self._alarm_min_spin.setRange(0, 59)
        self._alarm_min_spin.setSuffix(" 分")
        self._alarm_min_spin.setFixedWidth(80)
        time_row.addWidget(self._alarm_hour_spin)
        time_row.addWidget(self._alarm_min_spin)
        time_row.addStretch()
        form_layout.addLayout(time_row)

        # 重复模式
        repeat_row = QHBoxLayout()
        repeat_row.addWidget(QLabel("重复："))
        self._alarm_repeat_combo = QComboBox()
        self._alarm_repeat_combo.addItems(list(REPEAT_LABELS.values()))
        repeat_row.addWidget(self._alarm_repeat_combo)
        repeat_row.addStretch()
        form_layout.addLayout(repeat_row)

        # 添加按钮
        add_btn = QPushButton("➕ 添加闹钟")
        add_btn.setFixedHeight(32)
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: #6C7BFF;
                color: white;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover { background-color: #5A6AEE; }
        """)
        add_btn.clicked.connect(self._on_add_alarm)
        form_layout.addWidget(add_btn)

        layout.addWidget(form_group)

        # 闹钟列表
        list_group = QGroupBox("闹钟列表")
        list_group.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        list_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #D8D8EE;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
        """)
        list_layout = QVBoxLayout(list_group)

        self._alarm_list = QListWidget()
        self._alarm_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #E0E0E8;
                border-radius: 6px;
                background-color: rgba(255, 255, 255, 200);
            }
            QListWidget::item {
                padding: 8px;
            }
        """)
        list_layout.addWidget(self._alarm_list)

        # 操作按钮行
        alarm_btn_row = QHBoxLayout()
        self._alarm_delete_btn = QPushButton("删除选中")
        self._alarm_delete_btn.setCursor(Qt.PointingHandCursor)
        self._alarm_delete_btn.clicked.connect(self._on_delete_alarm)
        self._alarm_toggle_btn = QPushButton("启用/禁用")
        self._alarm_toggle_btn.setCursor(Qt.PointingHandCursor)
        self._alarm_toggle_btn.clicked.connect(self._on_toggle_alarm)
        alarm_btn_row.addWidget(self._alarm_delete_btn)
        alarm_btn_row.addWidget(self._alarm_toggle_btn)
        alarm_btn_row.addStretch()
        list_layout.addLayout(alarm_btn_row)

        layout.addWidget(list_group)

        return tab

    def _build_countdown_tab(self):
        """构建倒计时标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        # 动态倒计时大字显示区域
        self._dynamic_countdown_label = QLabel("")
        self._dynamic_countdown_label.setFont(QFont("Consolas", 28, QFont.Bold))
        self._dynamic_countdown_label.setAlignment(Qt.AlignCenter)
        self._dynamic_countdown_label.setStyleSheet("color: #FF6B6B; padding: 15px; background-color: rgba(255, 255, 255, 150); border-radius: 12px;")
        self._dynamic_countdown_label.hide()
        layout.addWidget(self._dynamic_countdown_label)

        # 添加倒计时表单
        form_group = QGroupBox("开始倒计时")
        form_group.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        form_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #D8D8EE;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
        """)
        form_layout = QVBoxLayout(form_group)

        # 倒计时名称
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("名称："))
        self._cd_name_edit = QLineEdit()
        self._cd_name_edit.setPlaceholderText("例如：煮鸡蛋、休息")
        name_row.addWidget(self._cd_name_edit)
        form_layout.addLayout(name_row)

        # 时间设置
        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("时长："))
        self._cd_hour_spin = QSpinBox()
        self._cd_hour_spin.setRange(0, 99)
        self._cd_hour_spin.setSuffix(" 时")
        self._cd_hour_spin.setFixedWidth(80)
        self._cd_min_spin = QSpinBox()
        self._cd_min_spin.setRange(0, 59)
        self._cd_min_spin.setSuffix(" 分")
        self._cd_min_spin.setFixedWidth(80)
        self._cd_sec_spin = QSpinBox()
        self._cd_sec_spin.setRange(0, 59)
        self._cd_sec_spin.setSuffix(" 秒")
        self._cd_sec_spin.setFixedWidth(80)
        time_row.addWidget(self._cd_hour_spin)
        time_row.addWidget(self._cd_min_spin)
        time_row.addWidget(self._cd_sec_spin)
        time_row.addStretch()
        form_layout.addLayout(time_row)

        # 开始按钮
        start_btn = QPushButton("▶ 开始倒计时")
        start_btn.setFixedHeight(32)
        start_btn.setCursor(Qt.PointingHandCursor)
        start_btn.setStyleSheet("""
            QPushButton {
                background-color: #34C759;
                color: white;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover { background-color: #2DA84D; }
        """)
        start_btn.clicked.connect(self._on_start_countdown)
        form_layout.addWidget(start_btn)

        layout.addWidget(form_group)

        # 运行中倒计时列表
        running_group = QGroupBox("运行中的倒计时")
        running_group.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        running_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #D8D8EE;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
        """)
        running_layout = QVBoxLayout(running_group)

        self._countdown_list = QListWidget()
        self._countdown_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #E0E0E8;
                border-radius: 6px;
                background-color: rgba(255, 255, 255, 200);
            }
            QListWidget::item {
                padding: 8px;
            }
        """)
        running_layout.addWidget(self._countdown_list)

        # 取消按钮
        cancel_btn = QPushButton("✖ 取消选中")
        cancel_btn.setFixedHeight(32)
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9500;
                color: white;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover { background-color: #E08600; }
        """)
        cancel_btn.clicked.connect(self._on_cancel_countdown)
        running_layout.addWidget(cancel_btn)

        layout.addWidget(running_group)

        return tab

    # ── 辅助方法 ─────────────────────────────────────────────

    def _refresh_alarm_list(self):
        """刷新闹钟列表显示"""
        self._alarm_list.clear()
        for alarm in self._manager.get_alarms():
            repeat_text = REPEAT_LABELS.get(alarm.repeat, "仅一次")
            status = "✓" if alarm.enabled else "✗"
            text = f"[{status}] {alarm.time_str} {alarm.name} | {repeat_text}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, alarm.id)
            if not alarm.enabled:
                item.setForeground(Qt.gray)
            self._alarm_list.addItem(item)

    def _refresh_countdown_list(self):
        """刷新倒计时列表显示，并更新动态大字显示（实时计算剩余时间）"""
        # 获取运行中的倒计时
        countdowns = self._manager.get_countdowns()
        now = datetime.now()
        
        self._countdown_list.clear()
        
        # 动态大字显示（显示第一个倒计时）
        if countdowns:
            cd = countdowns[0]
            if cd.end_time:
                remaining = int((cd.end_time - now).total_seconds())
                remaining = max(0, remaining)
                h = remaining // 3600
                m = (remaining % 3600) // 60
                s = remaining % 60
                time_str = f"{h:02d}:{m:02d}:{s:02d}"
                self._dynamic_countdown_label.setText(f"⏳ 倒计时中\n{time_str}")
                self._dynamic_countdown_label.repaint()
                self._dynamic_countdown_label.show()
            else:
                self._dynamic_countdown_label.hide()
        else:
            self._dynamic_countdown_label.hide()
        
        # 列表显示
        for cd in countdowns:
            if cd.end_time:
                remaining = int((cd.end_time - now).total_seconds())
                remaining = max(0, remaining)
                h = remaining // 3600
                m = (remaining % 3600) // 60
                s = remaining % 60
                time_str = f"{h:02d}:{m:02d}:{s:02d}"
                text = f"⏳ {cd.name} | 剩余 {time_str}"
            else:
                text = f"⏳ {cd.name} | 剩余 00:00:00"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, cd.id)
            self._countdown_list.addItem(item)

    # ── 闹钟操作 ─────────────────────────────────────────────

    def _on_add_alarm(self):
        """添加闹钟"""
        name = self._alarm_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入闹钟名称")
            return

        hour = self._alarm_hour_spin.value()
        minute = self._alarm_min_spin.value()
        time_str = f"{hour:02d}:{minute:02d}"

        repeat_text = self._alarm_repeat_combo.currentText()
        repeat = REPEAT_VALUES.get(repeat_text, "once")

        self._manager.add_alarm(name, time_str, repeat)
        self._refresh_alarm_list()
        self.alarms_changed.emit()

        # 清空表单
        self._alarm_name_edit.clear()

    def _on_delete_alarm(self):
        """删除选中闹钟"""
        current = self._alarm_list.currentItem()
        if not current:
            QMessageBox.warning(self, "提示", "请先选中一个闹钟")
            return
        alarm_id = current.data(Qt.UserRole)
        reply = QMessageBox.question(self, "确认删除", "确定要删除这个闹钟吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self._manager.delete_alarm(alarm_id)
            self._refresh_alarm_list()
            self.alarms_changed.emit()

    def _on_toggle_alarm(self):
        """启用/禁用选中闹钟"""
        current = self._alarm_list.currentItem()
        if not current:
            QMessageBox.warning(self, "提示", "请先选中一个闹钟")
            return
        alarm_id = current.data(Qt.UserRole)
        self._manager.toggle_enabled(alarm_id)
        self._refresh_alarm_list()
        self.alarms_changed.emit()

    # ── 倒计时操作 ───────────────────────────────────────────

    def _on_start_countdown(self):
        """开始倒计时"""
        name = self._cd_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入倒计时名称")
            return

        total_seconds = (self._cd_hour_spin.value() * 3600 +
                        self._cd_min_spin.value() * 60 +
                        self._cd_sec_spin.value())
        if total_seconds <= 0:
            QMessageBox.warning(self, "提示", "请设置大于0的时长")
            return

        self._manager.add_countdown(name, total_seconds)
        self._refresh_countdown_list()

        # 清空表单
        self._cd_name_edit.clear()
        self._cd_hour_spin.setValue(0)
        self._cd_min_spin.setValue(0)
        self._cd_sec_spin.setValue(0)

    def _on_cancel_countdown(self):
        """取消选中的倒计时"""
        current = self._countdown_list.currentItem()
        if not current:
            QMessageBox.warning(self, "提示", "请先选中一个倒计时")
            return
        cd_id = current.data(Qt.UserRole)
        self._manager.remove_countdown(cd_id)
        self._refresh_countdown_list()

    # ── 关闭事件 ─────────────────────────────────────────────

    def closeEvent(self, event):
        self._update_timer.stop()
        event.accept()