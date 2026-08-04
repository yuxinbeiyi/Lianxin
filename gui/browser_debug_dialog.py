"""浏览器自动化调试面板：仅显示脱敏任务事件。"""

from __future__ import annotations

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)


class BrowserDebugDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🌐 浏览器任务调试")
        self.resize(980, 520)
        self.setMinimumSize(760, 420)
        self.setStyleSheet("""
            QDialog { background: #FFFFFF; }
            QLabel { color: #27333A; }
            QTableWidget { background: #FFFFFF; color: #27333A; gridline-color: #DDE5E8; }
            QHeaderView::section { background: #EEF5F4; color: #27333A; padding: 6px; }
            QPushButton { padding: 5px 12px; border: 1px solid #B8CFCA; border-radius: 6px; background: #F2F8F7; }
            QPushButton:hover { background: #DDEEEA; }
        """)
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("最近浏览器任务（日志已脱敏）")
        title.setFont(QFont("Microsoft YaHei UI", 12, QFont.Bold))
        header.addWidget(title)
        header.addStretch()
        self._status = QLabel("等待任务")
        header.addWidget(self._status)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh)
        header.addWidget(refresh)
        root.addLayout(header)

        self._table = QTableWidget(0, 9)
        self._table.setHorizontalHeaderLabels([
            "时间", "任务", "事件", "步骤", "工具", "页面", "快照", "耗时", "结果/错误",
        ])
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self._table)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(1500)
        self.refresh()

    def refresh(self):
        try:
            from brain.browser_task_log import read_recent
            rows = read_recent(120)
        except Exception as exc:
            self._status.setText(f"读取失败：{exc}")
            return
        self._table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                str(row.get("timestamp", ""))[-23:],
                str(row.get("task_id", "")),
                str(row.get("event", "")),
                str(row.get("step", "")),
                str(row.get("tool", "")),
                str(row.get("url", "") or "")[:80],
                str(row.get("snapshot_id", "") or ""),
                self._format_duration(row.get("duration_ms")),
                str(row.get("error_code") or row.get("result_preview") or row.get("reason") or "")[:180],
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self._table.setItem(row_index, column, item)
        self._status.setText(f"最近 {len(rows)} 条事件 · 自动刷新")

    @staticmethod
    def _format_duration(value) -> str:
        try:
            return f"{float(value):.0f} ms" if value is not None else ""
        except (TypeError, ValueError):
            return ""

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)

