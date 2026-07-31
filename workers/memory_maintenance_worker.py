"""QThread adapter for one memory maintenance pass."""

from PyQt5.QtCore import QThread, pyqtSignal


class MemoryMaintenanceWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, *, trigger: str = "scheduled", conflict_scan_batch: int = 10, parent=None):
        super().__init__(parent)
        self.trigger = trigger
        self.conflict_scan_batch = conflict_scan_batch

    def run(self):
        try:
            from brain.memory_maintenance import run_memory_maintenance
            result = run_memory_maintenance(
                trigger=self.trigger,
                conflict_scan_batch=self.conflict_scan_batch,
            )
            if result.get("status") == "failed":
                self.failed.emit(result.get("error", "未知维护错误"))
            else:
                self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
