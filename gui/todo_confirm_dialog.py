"""
todo_confirm_dialog.py — 莲心提取待办后的确认弹窗
桌面端专用：弹出确认框，用户同意后才真正添加待办。
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
)
from PyQt5.QtCore import Qt, QTimer
from config import get_todo_auto_confirm, save_todo_auto_confirm


class TodoConfirmDialog(QDialog):
    """待办确认弹窗。

    莲心从对话中自动提取待办后，弹出此窗口让用户确认。
    支持"以后都自动添加"选项，与待办选项卡双向同步。
    30 秒无操作自动关闭（视为拒绝）。
    """

    def __init__(self, items: list, parent=None):
        """
        Args:
            items: [{"title": str, "due_time": str|None, "priority": str}, ...]
        """
        super().__init__(parent)
        self._items = items
        self._accepted = False

        self.setWindowTitle("莲心待办确认")
        self.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(360)

        layout = QVBoxLayout()
        layout.setSpacing(12)

        # 标题
        title_lbl = QLabel("🔔 莲心想要为你添加以下待办/提醒：")
        title_lbl.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title_lbl)

        # 待办列表
        for item in items:
            item_text = f"📋 {item['title']}"
            if item.get("due_time"):
                item_text += f"\n   ⏰ {item['due_time']}"
            lbl = QLabel(item_text)
            lbl.setStyleSheet("font-size: 13px; padding: 4px 0;")
            layout.addWidget(lbl)

        layout.addSpacing(8)

        # 按钮行
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self._btn_yes = QPushButton("✅ 添加")
        self._btn_yes.setMinimumHeight(36)
        self._btn_yes.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50; color: white;
                border: none; border-radius: 6px;
                font-size: 14px; font-weight: bold; padding: 6px 20px;
            }
            QPushButton:hover { background-color: #45a049; }
        """)
        self._btn_yes.clicked.connect(self._on_accept)

        self._btn_no = QPushButton("❌ 不需要")
        self._btn_no.setMinimumHeight(36)
        self._btn_no.setStyleSheet("""
            QPushButton {
                background-color: #f44336; color: white;
                border: none; border-radius: 6px;
                font-size: 14px; font-weight: bold; padding: 6px 20px;
            }
            QPushButton:hover { background-color: #e53935; }
        """)
        self._btn_no.clicked.connect(self.reject)

        btn_layout.addWidget(self._btn_yes)
        btn_layout.addWidget(self._btn_no)
        layout.addLayout(btn_layout)

        # "不再询问" 复选框
        self._auto_check = QCheckBox("以后都自动添加，不再询问")
        self._auto_check.setStyleSheet("font-size: 12px; color: #888;")
        layout.addWidget(self._auto_check)

        # 倒计时标签
        self._countdown_lbl = QLabel("30 秒后自动忽略")
        self._countdown_lbl.setStyleSheet("font-size: 11px; color: #aaa;")
        self._countdown_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._countdown_lbl)

        self.setLayout(layout)

        # 30 秒倒计时
        self._countdown = 30
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    def _tick(self):
        self._countdown -= 1
        if self._countdown <= 0:
            self._timer.stop()
            self.reject()
        else:
            self._countdown_lbl.setText(f"{self._countdown} 秒后自动忽略")

    def _on_accept(self):
        self._timer.stop()
        self._accepted = True
        self.accept()

    def is_auto_mode(self) -> bool:
        """用户是否勾选了'以后都自动添加'"""
        return self._auto_check.isChecked()

    def was_accepted(self) -> bool:
        return self._accepted