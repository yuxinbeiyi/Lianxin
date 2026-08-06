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

            result = reindex_pending_facts(max_items=self.max_items)
            try:
                from config import get_rag_config
                from utils.rag_ann_index import get_rag_ann_index

                ann = get_rag_ann_index()
                if get_rag_config().get("rag_ann_enabled", True):
                    from brain.graph_memory import _get_conn

                    rows = _get_conn().execute(
                        """SELECT id, embedding FROM memory_facts
                           WHERE embedding IS NOT NULL AND status='active'
                           ORDER BY id"""
                    ).fetchall()
                    database_ids = [row["id"] for row in rows]
                    validation = ann.validate_ids(database_ids)
                    should_build = ann.needs_build() or not validation.get("consistent", False)
                    if should_build:
                        ann_result = ann.build_from_rows(
                            [(row["id"], row["embedding"]) for row in rows],
                            model_name="BAAI/bge-small-zh-v1.5",
                        )
                    else:
                        ann_result = {"status": "consistent", "indexed": 0,
                                      "index_count": validation.get("index_count", 0)}
                    result["ann_validation"] = validation
                    result["ann"] = ann_result
            except Exception as exc:
                result["ann"] = {"status": "failed", "error": str(exc)}
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
