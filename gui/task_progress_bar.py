# gui/task_progress_bar.py
"""
任务进度条组件（第三阶段）
固定在聊天区上方 — 白色背景 + 绿色进度条 + 实时工具执行信息副标题。
"""

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QProgressBar
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QFont


class TaskProgressBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._completed = 0
        self._total = 0
        self._label_text = ""
        self._build_ui()
        self.hide()
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._maybe_hide)

    def _build_ui(self):
        self.setFixedHeight(52)
        self.setStyleSheet("""
            TaskProgressBar {
                background: #FFFFFF;
                border-bottom: 1px solid #E8E8E8;
            }
        """)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 4, 14, 4)
        outer.setSpacing(0)

        # ── 左侧 双行信息 ──────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(1)

        # 第一行：图标 + 任务名 + 计数
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self._icon = QLabel("📋")
        self._icon.setFont(QFont("Microsoft YaHei UI", 11))
        self._icon.setStyleSheet("background: transparent;")
        top_row.addWidget(self._icon)

        self._label = QLabel("")
        self._label.setFont(QFont("Microsoft YaHei UI", 10))
        self._label.setStyleSheet(
            "color: #1E8449; background: transparent; font-weight: bold;"
        )
        top_row.addWidget(self._label)

        top_row.addStretch()

        self._count = QLabel("")
        self._count.setFont(QFont("Microsoft YaHei UI", 10))
        self._count.setStyleSheet("color: #7F8C8D; background: transparent;")
        top_row.addWidget(self._count)

        left.addLayout(top_row)

        # 第二行：副标题 — 最新工具执行信息
        self._subtitle = QLabel("")
        self._subtitle.setFont(QFont("Microsoft YaHei UI", 9))
        self._subtitle.setStyleSheet(
            "color: #27AE60; background: transparent; padding-left: 22px;"
        )
        left.addWidget(self._subtitle)

        outer.addLayout(left)

        # ── 右侧 绿色进度条 ────────────────────────────
        self._bar = QProgressBar()
        self._bar.setFixedSize(110, 16)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet("""
            QProgressBar {
                background: #E8F5E9;
                border: none;
                border-radius: 8px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #27AE60, stop:1 #2ECC71);
                border-radius: 8px;
            }
        """)
        outer.addWidget(self._bar)

    # ── 公开方法 ───────────────────────────────────────

    def refresh(self, completed: int, total: int, label: str):
        self._completed = completed
        self._total = total
        self._label_text = label

        if total < 2:
            self.hide()
            return

        self._label.setText(label if label else "准备中...")
        self._count.setText(f"[{completed}/{total}]")
        self._bar.setMaximum(total)
        self._bar.setValue(completed)
        self.show()

        if completed >= total and total > 0:
            self._subtitle.setText("✅ 全部完成")
            self._subtitle.setStyleSheet(
                "color: #27AE60; background: transparent; padding-left: 22px;"
            )
            self._hide_timer.start(2000)

    def set_subtitle(self, text: str):
        """设置副标题（最新工具调用/结果信息）"""
        if self._total >= 2:
            self._subtitle.setText(text)
            self._subtitle.setStyleSheet(
                "color: #27AE60; background: transparent; padding-left: 22px;"
            )

    def _maybe_hide(self):
        if self._completed >= self._total and self._total > 0:
            self.hide()
