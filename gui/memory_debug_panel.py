"""Developer-facing memory recall and lifecycle diagnostics."""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit, QSplitter, QComboBox
from PyQt5.QtCore import Qt

class MemoryDebugPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root=QVBoxLayout(self); root.setSpacing(8)
        top=QHBoxLayout(); self._stats=QLabel(); top.addWidget(self._stats); top.addStretch()
        self._persona=QComboBox(); self._persona.addItem("全部人格", ""); top.addWidget(self._persona)
        self._channel=QComboBox(); self._channel.addItems(["全部渠道","desktop","qq","wechat"]); top.addWidget(self._channel)
        refresh=QPushButton("刷新"); refresh.clicked.connect(self.refresh); top.addWidget(refresh); root.addLayout(top)
        self._table=QTableWidget(0,7); self._table.setHorizontalHeaderLabels(["时间","渠道","人格","用户消息","状态","耗时","Trace"]); self._table.setSelectionBehavior(QTableWidget.SelectRows); self._table.setEditTriggers(QTableWidget.NoEditTriggers); self._table.itemSelectionChanged.connect(self._show_selected); root.addWidget(self._table,2)
        split=QSplitter(Qt.Vertical); self._detail=QTextEdit(); self._detail.setReadOnly(True); split.addWidget(self._detail); root.addWidget(split,1)
        self._traces=[]; self.refresh()

    def refresh(self):
        try:
            from brain.memory_diagnostics import get_memory_traces, get_memory_diagnostic_stats
            channel=self._channel.currentText() if hasattr(self,"_channel") and self._channel.currentText() != "全部渠道" else ""
            selected_persona=self._persona.currentData() or ""
            all_traces=get_memory_traces(150, channel=channel)
            known={self._persona.itemData(i) for i in range(self._persona.count())}
            for persona in sorted({t.get("persona_id","") for t in all_traces if t.get("persona_id","")}):
                if persona not in known: self._persona.addItem(persona,persona)
            self._traces=[t for t in all_traces if not selected_persona or t.get("persona_id")==selected_persona]
            diagnostic_stats=get_memory_diagnostic_stats()
            stats=diagnostic_stats.get("requests", {})
            try:
                from brain.memory_narrative import get_narrative_statistics
                narrative = get_narrative_statistics()
            except Exception:
                narrative = {"entities": 0, "episodes": 0, "sagas": 0}
            self._stats.setText(
                f"请求 {stats.get('total',0) or 0} · 成功 {stats.get('success',0) or 0} · "
                f"失败 {stats.get('failed',0) or 0} · 跨人格召回差异 "
                f"{diagnostic_stats.get('persona_recall_mismatches',0)} · "
                f"实体 {narrative['entities']} · Episode {narrative['episodes']} · Saga {narrative['sagas']}"
            )
            self._table.setRowCount(len(self._traces))
            for row,item in enumerate(self._traces):
                values=[str(item.get("started_at",""))[:19],item.get("channel", ""),item.get("persona_id", "") or "默认",item.get("user_message", "")[:80],item.get("status", ""),f"{float(item.get('duration_ms') or 0):.0f} ms",item.get("trace_id", "")[:10]]
                for col,value in enumerate(values): self._table.setItem(row,col,QTableWidgetItem(value))
            self._table.resizeColumnsToContents(); self._table.setColumnWidth(3,280)
        except Exception as exc: self._stats.setText(f"诊断加载失败：{exc}")

    def _show_selected(self):
        rows=self._table.selectionModel().selectedRows()
        if not rows: return
        item=self._traces[rows[0].row()]
        try:
            from brain.memory_diagnostics import get_trace_events
            events=get_trace_events(item["trace_id"])
            lines=[f"Trace: {item['trace_id']}",f"人格: {item.get('persona_id') or '默认'} / revision {item.get('persona_revision',0)}",f"请求: {item.get('user_message','')}",f"回复: {item.get('response_preview','')}","", "事件明细："]
            for ev in events:
                lines.append(f"[{ev.get('created_at','')[:19]}] {ev.get('event_type')}  {ev.get('reason','')}  score={ev.get('score','')}")
                payload=ev.get("payload",{})
                if payload: lines.append("  " + str(payload)[:1600])
            self._detail.setPlainText("\n".join(lines))
        except Exception as exc: self._detail.setPlainText(f"加载 Trace 失败：{exc}")
