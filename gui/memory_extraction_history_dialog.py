"""Auditable history and operator controls for background memory extraction."""

from __future__ import annotations

import json

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from brain.memory_extraction_pipeline import MemoryExtractionStore


class MemoryExtractionHistoryDialog(QDialog):
    def __init__(self, scheduler, parent=None):
        super().__init__(parent)
        self._scheduler = scheduler
        state = scheduler._build_state()
        if state.history_manager is None:
            raise RuntimeError("当前没有可用的会话历史数据库")
        self._store = MemoryExtractionStore(state.history_manager.db_path)
        self._runs: list[dict] = []

        self.setWindowTitle("记忆提取运行历史")
        self.resize(980, 620)
        self.setStyleSheet(
            "QDialog,QWidget{background:#1E2833;color:#E8ECF3;}"
            "QTableWidget,QTextBrowser{background:#242F3D;border:1px solid #3D4A5A;}"
            "QPushButton{background:#3D4A64;border:0;border-radius:5px;padding:6px 12px;}"
            "QPushButton:hover{background:#596B91;}"
        )
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.addWidget(QLabel("每次提取的消息范围、模型契约、Token、失败原因与降级路径都保留在这里。"))

        splitter = QSplitter(Qt.Vertical, self)
        self._table = QTableWidget(0, 10, splitter)
        self._table.setHorizontalHeaderLabels(
            ["ID", "时间", "会话", "消息范围", "触发", "状态", "模型", "Token", "耗时", "契约/降级"]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.itemSelectionChanged.connect(self._show_selected)

        self._detail = QTextBrowser(splitter)
        splitter.addWidget(self._table)
        splitter.addWidget(self._detail)
        splitter.setSizes([360, 200])
        root.addWidget(splitter, 1)

        buttons = QHBoxLayout()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self._refresh)
        source = QPushButton("查看来源消息")
        source.clicked.connect(self._show_sources)
        retry = QPushButton("重试失败任务")
        retry.clicked.connect(self._retry)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        buttons.addWidget(refresh)
        buttons.addWidget(source)
        buttons.addWidget(retry)
        buttons.addStretch()
        buttons.addWidget(close)
        root.addLayout(buttons)

    def _refresh(self):
        self._runs = self._store.list_runs(None, 200)
        self._table.setRowCount(len(self._runs))
        for row_index, run in enumerate(self._runs):
            token_count = int(run.get("input_tokens", 0)) + int(run.get("output_tokens", 0))
            values = [
                run.get("id", ""),
                str(run.get("started_at", ""))[:19].replace("T", " "),
                run.get("session_id", ""),
                f"{run.get('from_message_id', 0)}–{run.get('to_message_id', 0)}",
                run.get("trigger", ""),
                run.get("status", ""),
                run.get("model", ""),
                token_count,
                f"{float(run.get('duration_ms', 0) or 0) / 1000:.1f}s",
                f"{run.get('contract_version') or '-'} / {'降级' if run.get('graph_fallback_used') else '单次'}",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, int(run["id"]))
                self._table.setItem(row_index, column, item)
        if self._runs:
            self._table.selectRow(0)
        else:
            self._detail.setPlainText("还没有记忆提取运行记录。")

    def _selected_run(self) -> dict | None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._runs):
            return None
        return self._runs[row]

    def _show_selected(self):
        run = self._selected_run()
        if not run:
            return
        detail = dict(run)
        detail["total_tokens"] = int(run.get("input_tokens", 0)) + int(run.get("output_tokens", 0))
        self._detail.setPlainText(json.dumps(detail, ensure_ascii=False, indent=2, default=str))

    def _show_sources(self):
        run = self._selected_run()
        if not run:
            return
        rows = self._store.list_run_source_messages(int(run["id"]))
        dialog = QDialog(self)
        dialog.setWindowTitle(f"提取运行 #{run['id']} 的来源消息")
        dialog.resize(760, 520)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser(dialog)
        browser.setPlainText("\n\n".join(
            f"[{row.get('timestamp', '')}] #{row['id']}  {row.get('role', '')}\n{row.get('content', '')}"
            for row in rows
        ) or "来源消息已不存在。")
        layout.addWidget(browser)
        close = QPushButton("关闭", dialog)
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec_()

    def _retry(self):
        run = self._selected_run()
        if not run or run.get("status") != "failed":
            QMessageBox.information(self, "无法重试", "请选择一条失败的运行记录。")
            return
        self._store.resume_session(int(run["session_id"]), reset_failures=False)
        self._scheduler.manual_trigger(
            "memory_extraction",
            session_id=int(run["session_id"]),
            trigger=f"manual_retry:{run['id']}",
            force=True,
        )
        QMessageBox.information(self, "已提交", "失败任务已进入后台重试。")
