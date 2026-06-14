"""
reminder_dialog.py - 智能提醒管理对话框
支持添加、删除、启用/禁用提醒，全局智能提醒开关
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLineEdit, QComboBox, QTimeEdit, QLabel, QMessageBox,
    QCheckBox
)
from PyQt5.QtCore import Qt, QTime
from PyQt5.QtGui import QColor, QFont
from utils.reminder_manager import ReminderManager
from utils.settings import get_settings


class ReminderDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⏰ 智能提醒")
        self.setMinimumSize(500, 400)
        self.resize(550, 450)
        self.setModal(False)

        self.manager = ReminderManager()
        self.settings = get_settings()

        self._build_ui()
        self._refresh_list()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 全局智能提醒开关
        self.global_smart_cb = QCheckBox("🌐 全局智能提醒（AI生成文案）")
        self.global_smart_cb.setToolTip("开启后，所有提醒都将由AI生成不同文案；关闭后使用固定话术")
        self.global_smart_cb.setChecked(self.settings.global_smart_reminder)
        self.global_smart_cb.stateChanged.connect(self._on_global_smart_changed)
        layout.addWidget(self.global_smart_cb)

        # 添加新提醒区域
        add_group = QHBoxLayout()
        add_group.addWidget(QLabel("名称:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("提醒名称，如：喝水")
        add_group.addWidget(self.name_edit)

        add_group.addWidget(QLabel("时间:"))
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setTime(QTime.currentTime())
        add_group.addWidget(self.time_edit)

        add_group.addWidget(QLabel("重复:"))
        self.rule_combo = QComboBox()
        self.rule_combo.addItems(["一次", "每天", "每周", "每月"])
        add_group.addWidget(self.rule_combo)

        self.add_btn = QPushButton("添加")
        self.add_btn.clicked.connect(self._add_reminder)
        add_group.addWidget(self.add_btn)

        layout.addLayout(add_group)

        # 提醒列表
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        self.list_widget.itemDoubleClicked.connect(self._toggle_reminder)
        layout.addWidget(self.list_widget)

        # 操作按钮
        btn_layout = QHBoxLayout()
        self.delete_btn = QPushButton("删除选中")
        self.delete_btn.clicked.connect(self._delete_reminder)
        self.toggle_btn = QPushButton("启用/禁用")
        self.toggle_btn.clicked.connect(self._toggle_reminder)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)

        btn_layout.addWidget(self.delete_btn)
        btn_layout.addWidget(self.toggle_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        # 底部提示
        tip_label = QLabel("💡 我会主动提醒你的~")
        tip_label.setAlignment(Qt.AlignCenter)
        tip_label.setStyleSheet("color: #888888; font-size: 10pt; margin-top: 8px;")
        layout.addWidget(tip_label)

        # 样式优化
        self.setStyleSheet("""
            QListWidget::item:selected { background-color: #FFD966; color: #000000; }
        """)

    def _on_global_smart_changed(self):
        """保存全局智能提醒设置"""
        self.settings.global_smart_reminder = self.global_smart_cb.isChecked()

    def _refresh_list(self):
        """刷新提醒列表，启用项显示为橙黄色"""
        self.list_widget.clear()
        reminders = self.manager.get_all()
        for r in reminders:
            status = "✅" if r["enabled"] else "❌"
            repeat_text = {
                "once": "一次",
                "daily": "每天",
                "weekly": "每周",
                "monthly": "每月"
            }.get(r["rule"], r["rule"])
            text = f"{status} {r['name']}  {r['time']}  {repeat_text}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, r["id"])
            # 启用项文字设为橙黄色
            if r["enabled"]:
                item.setForeground(QColor(255, 140, 0))
            self.list_widget.addItem(item)

    def _add_reminder(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入提醒名称")
            return
        time_str = self.time_edit.time().toString("HH:mm")
        rule = self.rule_combo.currentText()
        rule_map = {"一次": "once", "每天": "daily", "每周": "weekly", "每月": "monthly"}
        rule_key = rule_map[rule]

        # 注意：不再传递 smart_reply 参数，因为使用全局开关
        self.manager.add(name, rule_key, time_str)
        self._refresh_list()
        self.name_edit.clear()

    def _delete_reminder(self):
        current = self.list_widget.currentItem()
        if not current:
            QMessageBox.information(self, "提示", "请先选中一个提醒")
            return
        rid = current.data(Qt.UserRole)
        reply = QMessageBox.question(self, "确认删除", "确定要删除这个提醒吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.manager.delete(rid)
            self._refresh_list()

    def _toggle_reminder(self, item=None):
        """切换选中提醒的启用/禁用状态"""
        if item is None:
            current = self.list_widget.currentItem()
        else:
            current = item
        if not current:
            QMessageBox.information(self, "提示", "请先选中一个提醒")
            return
        rid = current.data(Qt.UserRole)
        reminders = self.manager.get_all()
        for r in reminders:
            if r["id"] == rid:
                new_state = not r["enabled"]
                self.manager.enable(rid, new_state)
                self._refresh_list()
                return