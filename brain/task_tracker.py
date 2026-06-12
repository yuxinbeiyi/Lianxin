# brain/task_tracker.py
"""
会话级任务追踪器（第三阶段）
借鉴 Claude Code TodoWrite 设计：LLM 全量替换任务列表，GUI 实时显示进度。
"""

import threading
from typing import Callable

# ── 任务状态类型 ─────────────────────────────────────────────────
VALID_STATUSES = {"pending", "in_progress", "completed"}


class TaskTracker:
    """会话级任务追踪器（单例，非持久化）"""

    def __init__(self):
        self._lock = threading.Lock()
        self._todos: list[dict] = []
        self._observers: list[Callable[[], None]] = []

    # ── 公开接口 ──

    def update(self, todos: list[dict]) -> str:
        """全量替换任务列表，返回校验结果说明"""
        valid, msg = self._validate(todos)
        if not valid:
            return msg

        with self._lock:
            self._todos = todos[:]

        self._notify()
        return "任务清单已更新"

    def get_todos(self) -> list[dict]:
        with self._lock:
            return self._todos[:]

    def get_progress(self) -> tuple[int, int, str]:
        """返回 (已完成数, 总数, 当前进行中任务名)"""
        with self._lock:
            total = len(self._todos)
            completed = sum(1 for t in self._todos if t["status"] == "completed")
            in_progress = next((t["activeForm"] for t in self._todos if t["status"] == "in_progress"), "")
        return completed, total, in_progress

    def clear(self):
        with self._lock:
            self._todos.clear()
        self._notify()

    def observe(self, callback: Callable[[], None]):
        self._observers.append(callback)

    def unobserve(self, callback: Callable[[], None]):
        if callback in self._observers:
            self._observers.remove(callback)

    # ── 内部 ──

    def _validate(self, todos: list[dict]) -> tuple[bool, str]:
        if not isinstance(todos, list):
            return False, "错误：todos 必须是列表"
        if len(todos) == 0:
            return True, ""

        in_progress_count = 0
        for i, t in enumerate(todos):
            if not isinstance(t, dict):
                return False, f"错误：第 {i+1} 个任务必须是对象"
            if not t.get("content"):
                return False, f"错误：第 {i+1} 个任务缺少 content"
            if t.get("status") == "in_progress" and not t.get("activeForm"):
                return False, f"错误：第 {i+1} 个 in_progress 任务缺少 activeForm"
            if t.get("status") not in VALID_STATUSES:
                return False, f"错误：第 {i+1} 个任务状态无效，必须是 {VALID_STATUSES}"
            if t["status"] == "in_progress":
                in_progress_count += 1

        if in_progress_count > 1:
            return False, f"错误：最多只能有 1 个任务处于 in_progress 状态，当前 {in_progress_count} 个"
        return True, ""

    def _notify(self):
        for cb in self._observers:
            try:
                cb()
            except Exception:
                pass


# ── 单例 ────────────────────────────────────────────────────────

_tracker: TaskTracker | None = None


def get_task_tracker() -> TaskTracker:
    global _tracker
    if _tracker is None:
        _tracker = TaskTracker()
    return _tracker


def reset_task_tracker():
    get_task_tracker().clear()