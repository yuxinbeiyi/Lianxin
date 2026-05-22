"""
AlarmDialog：闹钟/倒计时设置对话框
"""

import os
from datetime import datetime
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QPushButton, QLineEdit, QComboBox, QSpinBox,
    QListWidget, QListWidgetItem, QMessageBox, QFileDialog,
    QGroupBox, QFrame, QCheckBox, QTimeEdit, QMenu, QInputDialog
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QTime, QDateTime
from PyQt5.QtGui import QFont, QColor

from utils.alarm_manager import REPEAT_LABELS, REPEAT_VALUES
from pathlib import Path


class AlarmDialog(QDialog):
    """闹钟/倒计时/提醒/待办设置对话框"""

    # 信号：闹钟列表变化时通知主窗口
    alarms_changed = pyqtSignal()

    def __init__(self, alarm_manager, parent=None, todo_manager=None):
        super().__init__(parent)
        self._manager = alarm_manager  # 使用主窗口传入的实例
        self._todo_manager = todo_manager  # 待办管理器
        self.setWindowTitle("⏰ 闹钟&提醒")
        self.setMinimumSize(550, 620)
        self.resize(580, 680)
        self.setModal(False)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._build_ui()
        self._refresh_alarm_list()
        self._refresh_countdown_list()
        if self._todo_manager:
            self._refresh_todo_list()

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
        title = QLabel("⏰ 闹钟&提醒")
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
        # 提醒标签页
        reminder_tab = self._build_reminder_tab()
        # 待办标签页
        todo_tab = self._build_todo_tab()

        self._tab_widget.addTab(alarm_tab, "⏰ 定时闹钟")
        self._tab_widget.addTab(countdown_tab, "⏳ 倒计时")
        self._tab_widget.addTab(reminder_tab, "📋 提醒")
        self._tab_widget.addTab(todo_tab, "✅ 待办")

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

    # ── 提醒标签页 ──────────────────────────────────────────

    def _build_reminder_tab(self):
        """构建提醒管理标签页"""
        from utils.reminder_manager import ReminderManager
        from utils.settings import get_settings

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)

        self._reminder_manager = ReminderManager()
        self._reminder_settings = get_settings()

        # 全局智能提醒开关
        self._reminder_smart_cb = QCheckBox("全局智能提醒（AI生成文案）")
        self._reminder_smart_cb.setChecked(self._reminder_settings.global_smart_reminder)
        self._reminder_smart_cb.stateChanged.connect(
            lambda: setattr(self._reminder_settings, 'global_smart_reminder', self._reminder_smart_cb.isChecked())
        )
        layout.addWidget(self._reminder_smart_cb)

        # 添加新提醒区域
        add_layout = QHBoxLayout()
        add_layout.addWidget(QLabel("名称:"))
        self._rem_name_edit = QLineEdit()
        self._rem_name_edit.setPlaceholderText("如：喝水")
        add_layout.addWidget(self._rem_name_edit)

        add_layout.addWidget(QLabel("时间:"))
        self._rem_time_edit = QTimeEdit()
        self._rem_time_edit.setDisplayFormat("HH:mm")
        self._rem_time_edit.setTime(QTime.currentTime())
        add_layout.addWidget(self._rem_time_edit)

        add_layout.addWidget(QLabel("重复:"))
        self._rem_rule_combo = QComboBox()
        self._rem_rule_combo.addItems(["一次", "每天", "每周", "每月"])
        add_layout.addWidget(self._rem_rule_combo)

        add_btn = QPushButton("添加")
        add_btn.clicked.connect(self._add_reminder)
        add_layout.addWidget(add_btn)
        layout.addLayout(add_layout)

        # 提醒列表
        self._reminder_list = QListWidget()
        self._reminder_list.setSelectionMode(QListWidget.SingleSelection)
        self._reminder_list.itemDoubleClicked.connect(lambda item: self._toggle_reminder_item(item))
        layout.addWidget(self._reminder_list)

        # 操作按钮
        btn_layout = QHBoxLayout()
        del_btn = QPushButton("删除选中")
        del_btn.clicked.connect(self._delete_reminder_item)
        toggle_btn = QPushButton("启用/禁用")
        toggle_btn.clicked.connect(lambda: self._toggle_reminder_item(None))
        btn_layout.addWidget(del_btn)
        btn_layout.addWidget(toggle_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._refresh_reminder_list()
        return tab

    def _refresh_reminder_list(self):
        self._reminder_list.clear()
        for r in self._reminder_manager.get_all():
            status = "✅" if r["enabled"] else "❌"
            repeat_text = {"once": "一次", "daily": "每天", "weekly": "每周", "monthly": "每月"}.get(r["rule"], r["rule"])
            text = f"{status} {r['name']}  {r['time']}  {repeat_text}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, r["id"])
            if r["enabled"]:
                item.setForeground(QColor(255, 140, 0))
            self._reminder_list.addItem(item)

    def _add_reminder(self):
        name = self._rem_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入提醒名称")
            return
        time_str = self._rem_time_edit.time().toString("HH:mm")
        rule_text = self._rem_rule_combo.currentText()
        rule_map = {"一次": "once", "每天": "daily", "每周": "weekly", "每月": "monthly"}
        self._reminder_manager.add(name, rule_map[rule_text], time_str)
        self._refresh_reminder_list()
        self._rem_name_edit.clear()

    def _delete_reminder_item(self):
        current = self._reminder_list.currentItem()
        if not current:
            return
        rid = current.data(Qt.UserRole)
        reply = QMessageBox.question(self, "确认删除", "确定要删除这个提醒吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self._reminder_manager.delete(rid)
            self._refresh_reminder_list()

    def _toggle_reminder_item(self, item=None):
        if item is None:
            item = self._reminder_list.currentItem()
        if not item:
            return
        rid = item.data(Qt.UserRole)
        for r in self._reminder_manager.get_all():
            if r["id"] == rid:
                self._reminder_manager.enable(rid, not r["enabled"])
                self._refresh_reminder_list()
                return

    # ── 待办标签页 ──────────────────────────────────────────

    def _build_todo_tab(self):
        """构建待办清单标签页"""
        from utils.todo_manager import PRIORITY_DISPLAY

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        # 搜索栏
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("🔍"))
        self._todo_search_edit = QLineEdit()
        self._todo_search_edit.setPlaceholderText("搜索待办...")
        self._todo_search_edit.textChanged.connect(lambda: self._refresh_todo_list())
        search_layout.addWidget(self._todo_search_edit)
        layout.addLayout(search_layout)

        # 待办列表
        self._todo_list = QListWidget()
        self._todo_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._todo_list.customContextMenuRequested.connect(self._todo_context_menu)
        self._todo_list.setAlternatingRowColors(True)
        self._todo_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #E0E0E8;
                border-radius: 6px;
                background-color: rgba(255, 255, 255, 200);
            }
            QListWidget::item {
                padding: 4px;
            }
        """)
        layout.addWidget(self._todo_list)

        # 按钮行
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ 添加待办")
        add_btn.clicked.connect(self._todo_add)
        del_btn = QPushButton("🗑️ 删除")
        del_btn.clicked.connect(self._todo_delete)
        complete_btn = QPushButton("✔️ 完成/重开")
        complete_btn.clicked.connect(self._todo_toggle_complete)
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(del_btn)
        btn_layout.addWidget(complete_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        if self._todo_manager is None:
            empty_label = QLabel("待办功能不可用")
            empty_label.setAlignment(Qt.AlignCenter)
            empty_label.setStyleSheet("color: #A0522D; padding: 40px;")
            layout.addWidget(empty_label)

        return tab

    def _refresh_todo_list(self):
        """刷新待办列表显示"""
        if self._todo_manager is None:
            return
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import QThread
        from utils.todo_manager import PRIORITY_DISPLAY

        if QThread.currentThread() is not QApplication.instance().thread():
            QTimer.singleShot(0, self._refresh_todo_list)
            return

        keyword = self._todo_search_edit.text().strip().lower() if hasattr(self, '_todo_search_edit') else ""
        self._todo_list.clear()
        todos = self._todo_manager.get_todos(completed=True)

        def sort_key(t):
            status_order = 0 if not t.completed else 1
            priority_order = {"high": 0, "medium": 1, "low": 2}.get(t.priority, 1)
            due_order = 0 if t.due_time else 1
            due_time = t.due_time if t.due_time else "9999-12-31"
            return (status_order, priority_order, due_order, due_time)
        todos.sort(key=sort_key)

        for todo in todos:
            if keyword and keyword.lower() not in todo.title.lower():
                continue
            item = QListWidgetItem()
            item.setData(Qt.UserRole, todo.id)
            widget = QWidget()
            row = QHBoxLayout(widget)
            row.setContentsMargins(5, 2, 5, 2)

            cb = QCheckBox()
            cb.setChecked(todo.completed)
            def make_handler(tid):
                return lambda state: self._todo_checkbox_changed(tid, state)
            cb.stateChanged.connect(make_handler(todo.id))
            row.addWidget(cb)

            priority_text = PRIORITY_DISPLAY.get(todo.priority, "中")
            plbl = QLabel(priority_text)
            plbl.setFixedWidth(50)
            if todo.priority == "high":
                plbl.setStyleSheet("color: #FF3B30; font-weight: bold;")
            elif todo.priority == "medium":
                plbl.setStyleSheet("color: #FF9500;")
            else:
                plbl.setStyleSheet("color: #888888;")
            row.addWidget(plbl)

            due_str = ""
            if todo.due_time:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(todo.due_time)
                    due_str = dt.strftime("%m-%d %H:%M")
                except:
                    due_str = ""
            due_lbl = QLabel(due_str)
            due_lbl.setFixedWidth(90)
            due_lbl.setStyleSheet("color: #555555;")
            row.addWidget(due_lbl)

            title_lbl = QLabel(todo.title)
            title_lbl.setWordWrap(True)
            if todo.completed:
                title_lbl.setStyleSheet("color: #AAAAAA; text-decoration: line-through;")
            row.addWidget(title_lbl, 1)

            item.setSizeHint(widget.sizeHint())
            self._todo_list.addItem(item)
            self._todo_list.setItemWidget(item, widget)

    def _todo_checkbox_changed(self, todo_id, state):
        if self._todo_manager is None:
            return
        self._todo_manager.toggle_complete(todo_id)

    def _todo_add(self):
        if self._todo_manager is None:
            return
        from PyQt5.QtWidgets import QInputDialog, QDialog, QDateTimeEdit, QComboBox, QDialogButtonBox
        title, ok = QInputDialog.getText(self, "添加待办", "待办标题:")
        if not ok or not title.strip():
            return
        title = title.strip()
        dlg = QDialog(self)
        dlg.setWindowTitle("详细设置（可选）")
        dlg_layout = QVBoxLayout(dlg)
        dt_edit = QDateTimeEdit()
        dt_edit.setCalendarPopup(True)
        dt_edit.setDateTime(QDateTime.currentDateTime())
        dt_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        dlg_layout.addWidget(QLabel("截止时间（可选）:"))
        dlg_layout.addWidget(dt_edit)
        priority_combo = QComboBox()
        priority_combo.addItems(["中", "高", "低"])
        dlg_layout.addWidget(QLabel("优先级:"))
        dlg_layout.addWidget(priority_combo)
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dlg.accept)
        btn_box.rejected.connect(dlg.reject)
        dlg_layout.addWidget(btn_box)
        if dlg.exec_() == QDialog.Accepted:
            due_time = dt_edit.dateTime().toString("yyyy-MM-ddTHH:mm:ss")
            priority_text = priority_combo.currentText()
            priority = {"高": "high", "中": "medium", "低": "low"}.get(priority_text, "medium")
            self._todo_manager.add_todo(title, due_time, priority)
            self._refresh_todo_list()

    def _todo_delete(self):
        if self._todo_manager is None:
            return
        current = self._todo_list.currentItem()
        if not current:
            QMessageBox.warning(self, "提示", "请先选中一个待办")
            return
        todo_id = current.data(Qt.UserRole)
        reply = QMessageBox.question(self, "确认删除", "确定要永久删除这个待办吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self._todo_manager.delete_todo(todo_id)
            self._refresh_todo_list()

    def _todo_toggle_complete(self):
        if self._todo_manager is None:
            return
        current = self._todo_list.currentItem()
        if not current:
            QMessageBox.warning(self, "提示", "请先选中一个待办")
            return
        self._todo_manager.toggle_complete(current.data(Qt.UserRole))
        self._refresh_todo_list()

    def _todo_context_menu(self, pos):
        if self._todo_manager is None:
            return
        item = self._todo_list.itemAt(pos)
        if not item:
            return
        todo_id = item.data(Qt.UserRole)
        todo = self._todo_manager.get_todo_by_id(todo_id)
        if not todo:
            return
        menu = QMenu()
        edit_action = menu.addAction("✏️ 编辑")
        toggle_action = menu.addAction("✔️ 完成/重开")
        delete_action = menu.addAction("🗑️ 删除")
        action = menu.exec_(self._todo_list.mapToGlobal(pos))
        if action == edit_action:
            self._todo_edit(todo)
        elif action == toggle_action:
            self._todo_manager.toggle_complete(todo_id)
            self._refresh_todo_list()
        elif action == delete_action:
            reply = QMessageBox.question(self, "确认删除", "确定要永久删除这个待办吗？",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self._todo_manager.delete_todo(todo_id)
                self._refresh_todo_list()

    def _todo_edit(self, todo):
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QDateTimeEdit, QComboBox, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("编辑待办")
        layout = QVBoxLayout(dlg)
        title_edit = QLineEdit(todo.title)
        layout.addWidget(QLabel("标题:"))
        layout.addWidget(title_edit)
        dt_edit = QDateTimeEdit()
        if todo.due_time:
            try:
                dt = QDateTime.fromString(todo.due_time, "yyyy-MM-ddTHH:mm:ss")
                dt_edit.setDateTime(dt)
            except:
                dt_edit.setDateTime(QDateTime.currentDateTime())
        else:
            dt_edit.setDateTime(QDateTime.currentDateTime())
        dt_edit.setCalendarPopup(True)
        dt_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        layout.addWidget(QLabel("截止时间:"))
        layout.addWidget(dt_edit)
        priority_combo = QComboBox()
        priority_combo.addItems(["高", "中", "低"])
        priority_map = {"high": "高", "medium": "中", "low": "低"}
        priority_combo.setCurrentText(priority_map.get(todo.priority, "中"))
        layout.addWidget(QLabel("优先级:"))
        layout.addWidget(priority_combo)
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dlg.accept)
        btn_box.rejected.connect(dlg.reject)
        layout.addWidget(btn_box)
        if dlg.exec_() == QDialog.Accepted:
            new_title = title_edit.text().strip()
            if new_title:
                new_due = dt_edit.dateTime().toString("yyyy-MM-ddTHH:mm:ss")
                new_priority = {"高": "high", "中": "medium", "低": "low"}.get(priority_combo.currentText(), "medium")
                self._todo_manager.update_todo(todo.id, title=new_title, due_time=new_due, priority=new_priority)
                self._refresh_todo_list()

    # ── 窗口事件 ─────────────────────────────────────────────

    def showEvent(self, event):
        """每次显示时注册待办观察者并刷新"""
        super().showEvent(event)
        if self._todo_manager:
            self._todo_manager.register_observer(self._refresh_todo_list)
            self._refresh_todo_list()

    def closeEvent(self, event):
        self._update_timer.stop()
        if self._todo_manager:
            self._todo_manager.unregister_observer(self._refresh_todo_list)
        event.accept()