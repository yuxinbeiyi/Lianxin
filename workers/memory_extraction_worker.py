"""QThread adapter for one persistent automatic-memory extraction pass."""

from __future__ import annotations

from PyQt5.QtCore import QThread, pyqtSignal


class MemoryExtractionWorker(QThread):
    """Run the pipeline outside the GUI and AgentCore response threads."""

    completed = pyqtSignal(object)
    failed = pyqtSignal(object)

    def __init__(
        self,
        *,
        pipeline,
        session_id: int,
        trigger: str = "scheduled",
        force: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.pipeline = pipeline
        self.session_id = int(session_id)
        self.trigger = str(trigger)
        self.force = bool(force)

    def run(self) -> None:
        try:
            result = self.pipeline.run_once(
                self.session_id, trigger=self.trigger, force=self.force
            )
            if result.get("status") == "failed":
                self.failed.emit(result)
            else:
                self.completed.emit(result)
        except Exception as exc:
            self.failed.emit({"status": "failed", "error": str(exc)})
