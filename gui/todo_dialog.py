"""
TodoDialog：待办清单管理对话框
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QMessageBox, QInputDialog, QWidget,
    QCheckBox, QComboBox, QDateTimeEdit, QAbstractItemView, QMenu
)
from PyQt5.QtCore import Qt, QDateTime, QThread, QTimer
from PyQt5.QtGui import QFont

from utils.todo_manager import TodoManager, PRIORITY_DISPLAY


class TodoDialog(QDialog):
    def __init__(self, todo_manager: TodoManager, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window)
        self._manager = todo_manager
        self.setWindowTitle("✅ 待办清单")
        self.setMinimumSize(500, 400)
        self.resize(550, 450)
        self.setModal(False)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._build_ui()
        self._refresh_list()
        # 注册观察者，当数据变化时自动刷新列表
        self._manager.register_observer(self._refresh_list)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # 标题和搜索框
        top_layout = QHBoxLayout()
        title = QLabel("✅ 待办清单")
        title.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
        title.setStyleSheet("color: #3A3A5C;")
        top_layout.addWidget(title)
        top_layout.addStretch()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索待办...")
        self._search_edit.textChanged.connect(lambda: self._refresh_list())
        top_layout.addWidget(self._search_edit)
        layout.addLayout(top_layout)

        # 列表
        self._list = QListWidget()
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)
        self._list.setAlternatingRowColors(True)
        layout.addWidget(self._list)

        # 按钮行
        btn_layout = QHBoxLayout()
        self._add_btn = QPushButton("➕ 添加待办")
        self._add_btn.clicked.connect(self._on_add)
        self._del_btn = QPushButton("🗑️ 删除")
        self._del_btn.clicked.connect(self._on_delete)
        self._complete_btn = QPushButton("✔️ 完成/重开")
        self._complete_btn.clicked.connect(self._on_toggle_complete)
        btn_layout.addWidget(self._add_btn)
        btn_layout.addWidget(self._del_btn)
        btn_layout.addWidget(self._complete_btn)
        btn_layout.addStretch()
        self._close_btn = QPushButton("关闭")
        self._close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self._close_btn)
        layout.addLayout(btn_layout)

    def _refresh_list(self, keyword: str = None):
        """刷新列表显示所有待办（包括已完成），支持关键词过滤"""
        # AI 工具在子线程中调用时，切换回主线程再操作 GUI
        from PyQt5.QtWidgets import QApplication
        if QThread.currentThread() is not QApplication.instance().thread():
            QTimer.singleShot(0, self._refresh_list)
            return
        if keyword is None:
            keyword = self._search_edit.text() if hasattr(self, '_search_edit') else ""
        self._list.clear()
        todos = self._manager.get_todos(completed=True)  # 获取所有待办
        # 排序：未完成的排在前面，已完成排后面；同状态按优先级+截止时间
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
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(5, 2, 5, 2)

            # 复选框（状态）
            cb = QCheckBox()
            cb.setChecked(todo.completed)
            # 使用 lambda 捕获当前 todo.id，注意需要创建新变量
            def make_handler(tid):
                return lambda state: self._on_checkbox_changed(tid, state)
            cb.stateChanged.connect(make_handler(todo.id))
            layout.addWidget(cb)

            # 优先级标签
            priority_text = PRIORITY_DISPLAY.get(todo.priority, "中")
            priority_lbl = QLabel(priority_text)
            priority_lbl.setFixedWidth(50)
            if todo.priority == "high":
                priority_lbl.setStyleSheet("color: #FF3B30; font-weight: bold;")
            elif todo.priority == "medium":
                priority_lbl.setStyleSheet("color: #FF9500;")
            else:
                priority_lbl.setStyleSheet("color: #888888;")
            layout.addWidget(priority_lbl)

            # 截止时间
            due_str = ""
            if todo.due_time:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(todo.due_time)
                    due_str = dt.strftime("%m-%d %H:%M")
                except:
                    due_str = "无效时间"
            due_lbl = QLabel(due_str)
            due_lbl.setFixedWidth(100)
            
            layout.addWidget(due_lbl)

            # 标题（已完成加删除线和灰色）
            title_lbl = QLabel(todo.title)
            title_lbl.setWordWrap(True)
            if todo.completed:
                title_lbl.setStyleSheet("color: #AAAAAA; text-decoration: line-through;")
            layout.addWidget(title_lbl, 1)

            item.setSizeHint(widget.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, widget)

    def _on_checkbox_changed(self, todo_id, state):
        """复选框状态改变：切换完成状态"""
        self._manager.toggle_complete(todo_id)
        # 无需手动刷新，观察者会自动触发 _refresh_list

    def _on_toggle_complete(self):
        """按钮：切换当前选中待办的完成状态"""
        current_item = self._list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "提示", "请先选中一个待办")
            return
        todo_id = current_item.data(Qt.UserRole)
        self._manager.toggle_complete(todo_id)
        # 观察者会自动刷新

    def _on_add(self):
        """添加待办对话框"""
        title, ok = QInputDialog.getText(self, "添加待办", "待办标题:")
        if not ok or not title.strip():
            return
        title = title.strip()
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QDateTimeEdit, QComboBox, QDialogButtonBox
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
            self._manager.add_todo(title, due_time, priority)
            # 观察者会自动刷新

    def _on_delete(self):
        """删除选中的待办（永久删除）"""
        current_item = self._list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "提示", "请先选中一个待办")
            return
        todo_id = current_item.data(Qt.UserRole)
        reply = QMessageBox.question(self, "确认删除", "确定要永久删除这个待办吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self._manager.delete_todo(todo_id)
            # 观察者会自动刷新

    def _show_context_menu(self, pos):
        item = self._list.itemAt(pos)
        if not item:
            return
        todo_id = item.data(Qt.UserRole)
        todo = self._manager.get_todo_by_id(todo_id)
        if not todo:
            return
        menu = QMenu()
        edit_action = menu.addAction("✏️ 编辑")
        toggle_action = menu.addAction("✔️ 完成/重开")
        delete_action = menu.addAction("🗑️ 删除")
        action = menu.exec_(self._list.mapToGlobal(pos))
        if action == edit_action:
            self._edit_todo(todo)
        elif action == toggle_action:
            self._manager.toggle_complete(todo_id)
            # 观察者会自动刷新
        elif action == delete_action:
            reply = QMessageBox.question(self, "确认删除", "确定要永久删除这个待办吗？",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self._manager.delete_todo(todo_id)
                # 观察者会自动刷新

    def _edit_todo(self, todo):
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
                self._manager.update_todo(todo.id, title=new_title, due_time=new_due, priority=new_priority)
                # 观察者会自动刷新

    def showEvent(self, event):
        """每次对话框显示时重新注册观察者并刷新列表"""
        super().showEvent(event)
        self._manager.register_observer(self._refresh_list)
        self._refresh_list()

    def closeEvent(self, event):
        """关闭窗口时注销观察者"""
        self._manager.unregister_observer(self._refresh_list)
        event.accept()