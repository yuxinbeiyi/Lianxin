"""QThread adapter for a bounded, idle-only memory embedding pass."""

from __future__ import annotations

from PyQt5.QtCore import QThread, pyqtSignal


class EmbeddingIndexWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, *, max_items: int, parent=None):
        super().__init__(parent)
        self.max_items = max(1, int(max_items))

    def run(self) -> None:
        try:
            from brain.memory_rag import reindex_pending_facts

            self.completed.emit(reindex_pending_facts(max_items=self.max_items))
        except Exception as exc:
            self.failed.emit(str(exc))
