# gui/task_progress_bar.py
"""
任务进度条组件（第三阶段）
嵌入 chat_widget 顶部，实时显示当前会话任务进度。
"""

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QProgressBar, QApplication
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt5.QtGui import QFont


class TaskProgressBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._completed = 0
        self._total = 0
        self._label_text = ""
        self._visible = False
        self._build_ui()
        self.hide()
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._maybe_hide)

    def _build_ui(self):
        self.setFixedHeight(32)
        self.setStyleSheet("""
            TaskProgressBar {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(74, 144, 217, 30), stop:1 rgba(100, 180, 255, 30));
                border-bottom: 1px solid rgba(74, 144, 217, 60);
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)

        self._icon = QLabel("📋")
        self._icon.setFont(QFont("Microsoft YaHei UI", 11))
        self._icon.setStyleSheet("background: transparent;")
        layout.addWidget(self._icon)

        self._label = QLabel("")
        self._label.setFont(QFont("Microsoft YaHei UI", 10))
        self._label.setStyleSheet("color: #2C3E50; background: transparent;")
        layout.addWidget(self._label)

        layout.addStretch()

        self._count = QLabel("")
        self._count.setFont(QFont("Microsoft YaHei UI", 10))
        self._count.setStyleSheet("color: #7F8C8D; background: transparent;")
        layout.addWidget(self._count)

        self._bar = QProgressBar()
        self._bar.setFixedSize(100, 14)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet("""
            QProgressBar {
                background: rgba(74, 144, 217, 25);
                border: none;
                border-radius: 7px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4A90D9, stop:1 #64B4FF);
                border-radius: 7px;
            }
        """)
        layout.addWidget(self._bar)

    def refresh(self, completed: int, total: int, label: str):
        self._completed = completed
        self._total = total
        self._label_text = label

        if total < 2:
            self.hide()
            self._visible = False
            return

        self._label.setText(label if label else "准备中...")
        self._count.setText(f"[{completed}/{total}]")
        self._bar.setMaximum(total)
        self._bar.setValue(completed)
        self.show()
        self._visible = True

        if completed >= total and total > 0:
            self._hide_timer.start(2000)

    def _maybe_hide(self):
        if self._completed >= self._total and self._total > 0:
            self.hide()
            self._visible = False