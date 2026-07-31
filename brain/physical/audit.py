"""将异步具身任务的真实终态同步到 WorkflowStore。"""

from __future__ import annotations

import threading
import time

from brain.physical.models import PhysicalTask, TaskStatus
from brain.workflow import WorkflowStore, get_workflow_store


class PhysicalTaskAuditor:
    def __init__(self, runtime, *, store: WorkflowStore | None = None):
        self.store = store or get_workflow_store()
        self._records: dict[str, tuple[int, int, float]] = {}
        self._lock = threading.Lock()
        runtime.add_event_listener(self._on_event)

    def track(self, task: PhysicalTask, *, channel: str = "", source: str = "tool") -> int:
        run = self.store.begin_run(
            kind="physical_task", title=task.kind, channel=channel,
            metadata={"physical_task_id": task.id, "payload": task.payload, "source": source},
        )
        step_id = self.store.start_step(
            run["id"], step_key=f"physical:{task.id}", name=task.kind,
            kind="physical", input_data=task.payload,
        )
        with self._lock:
            self._records[task.id] = (int(run["id"]), step_id, time.perf_counter())
        return int(run["id"])

    def _on_event(self, task: PhysicalTask, _event: dict) -> None:
        if not task.status.is_terminal:
            return
        with self._lock:
            record = self._records.pop(task.id, None)
        if record is None:
            return
        run_id, step_id, started = record
        duration_ms = (time.perf_counter() - started) * 1000
        status, summary, error = self._outcome(task)
        self.store.finish_step(step_id, status=status, output_preview=summary, error=error, duration_ms=duration_ms)
        self.store.finish_run(run_id, status=status, result_summary=summary, error=error)

    @staticmethod
    def _outcome(task: PhysicalTask) -> tuple[str, str, str]:
        if task.status == TaskStatus.ARRIVED:
            return "success", f"具身任务完成：{task.kind}", ""
        if task.status == TaskStatus.CANCELLED:
            return "cancelled", "具身任务已取消", ""
        error = task.error or task.status.value
        return "failed", "", error
