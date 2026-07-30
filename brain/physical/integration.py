"""具身运行时与持久化审计的进程内集成。"""

from __future__ import annotations

import threading

from brain.physical.audit import PhysicalTaskAuditor
from brain.physical.runtime import PhysicalRuntime


_auditors: dict[int, PhysicalTaskAuditor] = {}
_auditor_lock = threading.Lock()


def get_physical_task_auditor(runtime: PhysicalRuntime) -> PhysicalTaskAuditor:
    """为每个权威运行时创建且只创建一个任务审计器。"""
    key = id(runtime)
    with _auditor_lock:
        auditor = _auditors.get(key)
        if auditor is None:
            auditor = PhysicalTaskAuditor(runtime)
            _auditors[key] = auditor
        return auditor
