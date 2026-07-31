"""
QuickLaunchDialog：快捷启动应用管理面板
允许用户添加/编辑/删除常用应用，便于 open_app 快速查找启动。
数据存储在 user_config.json 的 quick_launch_apps 字段中。
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QLineEdit, QFormLayout,
    QFileDialog, QMessageBox, QDialogButtonBox,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from pathlib import Path
from config import get_quick_launch_apps, save_quick_launch_apps


class QuickLaunchDialog(QDialog):
    """快捷启动应用列表管理对话框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("快捷启动应用管理")
        self.setMinimumSize(680, 420)
        self.setModal(True)
        self._apps: list[dict] = []
        self._build_ui()
        self._load_apps()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 说明文字
        tip = QLabel(
            "在这里添加你常用的应用，之后在 QQ 或桌面端说「打开xxx」时，莲心会优先从这里匹配。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #666; font-size: 12px; margin-bottom: 8px;")
        layout.addWidget(tip)

        # 表格
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["应用名称", "可执行文件", "完整路径"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

        # 操作按钮
        btn_layout = QHBoxLayout()
        btn_add = QPushButton("＋ 添加")
        btn_add.setFixedWidth(100)
        btn_add.clicked.connect(self._on_add)

        btn_edit = QPushButton("✏ 编辑")
        btn_edit.setFixedWidth(100)
        btn_edit.clicked.connect(self._on_edit)

        btn_delete = QPushButton("✕ 删除")
        btn_delete.setFixedWidth(100)
        btn_delete.clicked.connect(self._on_delete)

        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_edit)
        btn_layout.addWidget(btn_delete)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 关闭按钮
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.setFixedWidth(80)
        btn_close.clicked.connect(self.accept)
        close_layout.addWidget(btn_close)
        layout.addLayout(close_layout)

    def _load_apps(self):
        self._apps = get_quick_launch_apps()
        self._refresh_table()

    def _refresh_table(self):
        self._table.setRowCount(len(self._apps))
        for row, app in enumerate(self._apps):
            name = app.get("name", "")
            exe_name = app.get("exe_name", "")
            path = app.get("path", "")
            self._table.setItem(row, 0, QTableWidgetItem(name))
            self._table.setItem(row, 1, QTableWidgetItem(exe_name))
            self._table.setItem(row, 2, QTableWidgetItem(path))

    def _on_add(self):
        dlg = QuickLaunchEditDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            data = dlg.get_data()
            self._apps.append(data)
            save_quick_launch_apps(self._apps)
            self._refresh_table()

    def _on_edit(self):
        row = self._table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选中一个应用")
            return
        dlg = QuickLaunchEditDialog(self, data=self._apps[row])
        if dlg.exec_() == QDialog.Accepted:
            self._apps[row] = dlg.get_data()
            save_quick_launch_apps(self._apps)
            self._refresh_table()

    def _on_delete(self):
        row = self._table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选中一个应用")
            return
        name = self._apps[row].get("name", "")
        ok = QMessageBox.question(
            self, "确认删除", f"确定要删除「{name}」吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if ok == QMessageBox.Yes:
            del self._apps[row]
            save_quick_launch_apps(self._apps)
            self._refresh_table()


class QuickLaunchEditDialog(QDialog):
    """添加/编辑单个快捷启动应用的对话框。"""

    def __init__(self, parent=None, data: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("添加应用" if data is None else "编辑应用")
        self.setMinimumWidth(450)
        self._data = data
        self._build_ui()

    def _build_ui(self):
        layout = QFormLayout(self)

        self._edit_name = QLineEdit()
        self._edit_name.setPlaceholderText("例如：网易云音乐")
        self._edit_name.setMaxLength(50)
        layout.addRow("应用名称：", self._edit_name)

        self._edit_exe = QLineEdit()
        self._edit_exe.setPlaceholderText("例如：cloudmusic.exe（可选，用于 PATH 搜索）")
        self._edit_exe.setMaxLength(100)
        layout.addRow("可执行文件：", self._edit_exe)

        # 路径 + 浏览按钮
        path_layout = QHBoxLayout()
        self._edit_path = QLineEdit()
        self._edit_path.setPlaceholderText("例如：E:\\CloudMusic\\CloudMusic\\cloudmusic.exe（可选）")
        self._edit_path.setMaxLength(300)
        btn_browse = QPushButton("浏览")
        btn_browse.setFixedWidth(60)
        btn_browse.clicked.connect(self._on_browse)
        path_layout.addWidget(self._edit_path)
        path_layout.addWidget(btn_browse)
        layout.addRow("完整路径：", path_layout)

        # 提示
        tip = QLabel("名称必填，路径和可执行文件至少填一个。莲心会按：完整路径 → 可执行文件(PATH) 的顺序查找。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #999; font-size: 11px;")
        layout.addRow(tip)

        # 保存/取消
        btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        layout.addRow(btn_box)

        # 编辑模式：填充已有数据
        if self._data:
            self._edit_name.setText(self._data.get("name", ""))
            self._edit_exe.setText(self._data.get("exe_name", ""))
            self._edit_path.setText(self._data.get("path", ""))

    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择应用程序", "",
            "可执行文件 (*.exe);;所有文件 (*.*)"
        )
        if path:
            self._edit_path.setText(path)

    def _on_save(self):
        name = self._edit_name.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "应用名称不能为空")
            return
        self._result = {
            "name": name,
            "exe_name": self._edit_exe.text().strip(),
            "path": self._edit_path.text().strip(),
        }
        self.accept()

    def get_data(self) -> dict:
        return self._result
