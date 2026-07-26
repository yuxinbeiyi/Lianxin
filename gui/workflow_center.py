"""Workflow run center: history, steps, artifacts, cancellation and retry."""

from __future__ import annotations

import json

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTextBrowser,
    QVBoxLayout,
)

from brain.workflow import get_workflow_store


class WorkflowCenter(QDialog):
    def __init__(self, parent=None, *, retry_callback=None, cancel_callback=None):
        super().__init__(parent)
        self._store = get_workflow_store()
        self._retry_callback = retry_callback
        self._cancel_callback = cancel_callback
        self._runs: list[dict] = []
        self.setWindowTitle("任务运行中心")
        self.resize(1080, 680)
        self.setStyleSheet(
            "QDialog{background:#1E2833;color:#E7ECF5;}"
            "QTableWidget,QTextBrowser{background:#25313F;color:#E7ECF5;border:1px solid #3C4B5D;}"
            "QPushButton{background:#3D4B68;color:#EEF2FF;border:0;border-radius:5px;padding:6px 12px;}"
            "QPushButton:hover{background:#596D96;}"
        )
        self._build_ui()
        self._refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_preserving_selection)
        self._timer.start(3000)

    def _build_ui(self):
        root = QVBoxLayout(self)
        title = QLabel("任务运行中心")
        title.setStyleSheet("font-size:16px;font-weight:bold;color:#AFC1FF;")
        root.addWidget(title)
        root.addWidget(QLabel("统一查看对话、自动任务、模型轮次、工具步骤、缓存命中和生成产物。"))

        splitter = QSplitter(Qt.Vertical, self)
        self._runs_table = QTableWidget(0, 9, splitter)
        self._runs_table.setHorizontalHeaderLabels(
            ["ID", "开始时间", "类型", "标题", "会话", "状态", "尝试", "Token", "结果"]
        )
        self._runs_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._runs_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._runs_table.verticalHeader().setVisible(False)
        self._runs_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._runs_table.horizontalHeader().setStretchLastSection(True)
        self._runs_table.itemSelectionChanged.connect(self._show_selected)

        lower = QSplitter(Qt.Horizontal, splitter)
        self._steps_table = QTableWidget(0, 7, lower)
        self._steps_table.setHorizontalHeaderLabels(
            ["顺序", "步骤", "类型", "状态", "缓存", "耗时", "输出/错误"]
        )
        self._steps_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._steps_table.verticalHeader().setVisible(False)
        self._steps_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._steps_table.horizontalHeader().setStretchLastSection(True)
        self._detail = QTextBrowser(lower)
        lower.addWidget(self._steps_table)
        lower.addWidget(self._detail)
        lower.setSizes([650, 380])
        splitter.addWidget(self._runs_table)
        splitter.addWidget(lower)
        splitter.setSizes([300, 330])
        root.addWidget(splitter, 1)

        buttons = QHBoxLayout()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self._refresh)
        cancel = QPushButton("取消运行")
        cancel.clicked.connect(self._cancel)
        retry = QPushButton("重试失败任务")
        retry.clicked.connect(self._retry)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        buttons.addWidget(refresh)
        buttons.addWidget(cancel)
        buttons.addWidget(retry)
        buttons.addStretch()
        buttons.addWidget(close)
        root.addLayout(buttons)

    def _selected_run(self):
        row = self._runs_table.currentRow()
        return self._runs[row] if 0 <= row < len(self._runs) else None

    def _refresh_preserving_selection(self):
        selected = self._selected_run()
        selected_id = int(selected["id"]) if selected else 0
        self._refresh(selected_id)

    def _refresh(self, selected_id: int = 0):
        self._runs = self._store.list_runs(300)
        self._runs_table.setRowCount(len(self._runs))
        selected_row = 0
        for row_index, run in enumerate(self._runs):
            if int(run["id"]) == int(selected_id):
                selected_row = row_index
            total_tokens = int(run.get("input_tokens", 0)) + int(run.get("output_tokens", 0))
            values = [
                run["id"], str(run.get("started_at", ""))[:19].replace("T", " "),
                run.get("kind", ""), run.get("title", ""), run.get("session_id", ""),
                run.get("status", ""), run.get("attempt", 1), total_tokens,
                run.get("result_summary") or run.get("error") or "",
            ]
            for column, value in enumerate(values):
                self._runs_table.setItem(row_index, column, QTableWidgetItem(str(value)))
        if self._runs:
            self._runs_table.selectRow(selected_row)
        else:
            self._detail.setPlainText("还没有 Workflow 运行记录。")

    def _show_selected(self):
        run = self._selected_run()
        if not run:
            return
        steps = self._store.list_steps(int(run["id"]))
        self._steps_table.setRowCount(len(steps))
        for row_index, step in enumerate(steps):
            values = [
                step.get("sequence", ""), step.get("name", ""), step.get("kind", ""),
                step.get("status", ""), "是" if step.get("cached") else "否",
                f"{float(step.get('duration_ms', 0) or 0) / 1000:.2f}s",
                step.get("output_preview") or step.get("error") or "",
            ]
            for column, value in enumerate(values):
                self._steps_table.setItem(row_index, column, QTableWidgetItem(str(value)))
        detail = dict(run)
        detail["artifacts"] = self._store.list_artifacts(int(run["id"]))
        try:
            from brain.task_store import get_task_store
            detail["task_entities"] = get_task_store().list_tasks_for_workflow(int(run["id"]))
        except Exception:
            detail["task_entities"] = []
        self._detail.setPlainText(json.dumps(detail, ensure_ascii=False, indent=2, default=str))

    def _cancel(self):
        run = self._selected_run()
        if not run or run.get("status") != "running":
            QMessageBox.information(self, "无法取消", "请选择一条正在运行的任务。")
            return
        if run.get("kind") == "duty":
            QMessageBox.information(self, "请在职责中心操作", "后台职责请在“后台职责中心”暂停，避免中断数据库事务。")
            return
        self._store.request_cancel(int(run["id"]))
        if self._cancel_callback:
            self._cancel_callback(run)
        QMessageBox.information(self, "已请求取消", "取消信号已经发送，当前安全步骤结束后停止。")
        self._refresh(int(run["id"]))

    def _retry(self):
        run = self._selected_run()
        if not run or run.get("status") not in {"failed", "interrupted", "cancelled"}:
            QMessageBox.information(self, "无法重试", "请选择失败、中断或已取消的任务。")
            return
        if not self._retry_callback:
            QMessageBox.information(self, "无法重试", "当前运行类型没有可用的重试执行器。")
            return
        submitted = self._retry_callback(run)
        if submitted is False:
            return
        QMessageBox.information(self, "已提交", "任务已按原始输入重新提交。")

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)
