# -*- coding: utf-8 -*-
"""
AutoTaskManager — 自动化任务核心管理器
负责 CRUD、SQLite 持久化、调度计算、执行日志。
"""

import logging
from datetime import datetime
from typing import Optional, Callable

from utils.auto_task_data import AutoTask, ActionStep
from brain.task_store import TaskStore, get_task_store

logger = logging.getLogger("AutoTaskManager")

class AutoTaskManager:
    """自动化任务管理器（单例）"""

    def __init__(self, store: TaskStore | None = None):
        self._store = store or get_task_store()
        self._tasks: list[AutoTask] = []
        self._execution_logs: list[dict] = []
        self._observers: list[Callable[[], None]] = []
        self._load()

    # ── 持久化 ──

    def _load(self):
        try:
            self._tasks = [AutoTask.from_dict(d) for d in self._store.list_auto_tasks()]
            print(f"[AutoTaskManager] SQLite 已加载 {len(self._tasks)} 个自动化任务")
        except Exception as e:
            logger.warning(f"加载 tasks.db 自动任务失败: {e}")
            print(f"[AutoTaskManager] 加载任务数据库失败: {e}")
            self._tasks = []

        try:
            self._execution_logs = self._store.list_auto_task_logs(limit=500)
            print(f"[AutoTaskManager] SQLite 已加载 {len(self._execution_logs)} 条执行日志")
        except Exception:
            self._execution_logs = []

    def save(self):
        try:
            self._store.replace_auto_tasks(t.to_dict() for t in self._tasks)
        except Exception as e:
            logger.error(f"保存 tasks.db 自动任务失败: {e}")

    def _save_logs(self):
        try:
            self._store.replace_auto_task_logs(self._execution_logs[-500:])
        except Exception:
            pass

    # ── CRUD ──

    def add_task(self, task: AutoTask) -> AutoTask:
        if not task.next_run:
            task.next_run = task.compute_next_run()
        self._tasks.append(task)
        self.save()
        self._notify()
        print(f"[AutoTaskManager] 新增任务: 「{task.name}」(ID:{task.task_id}) type={task.schedule_type} next={task.next_run}")
        return task

    def update_task(self, task_id: str, **kwargs) -> bool:
        for t in self._tasks:
            if t.task_id == task_id:
                for k, v in kwargs.items():
                    if hasattr(t, k):
                        setattr(t, k, v)
                if "schedule_type" in kwargs or "schedule_time" in kwargs or "interval_minutes" in kwargs:
                    t.next_run = t.compute_next_run()
                self.save()
                self._notify()
                return True
        return False

    def delete_task(self, task_id: str) -> bool:
        before = len(self._tasks)
        self._tasks = [t for t in self._tasks if t.task_id != task_id]
        if len(self._tasks) < before:
            self.save()
            self._notify()
            print(f"[AutoTaskManager] 删除任务: ID={task_id} (剩余 {len(self._tasks)} 个)")
            return True
        return False

    def get_task(self, task_id: str) -> Optional[AutoTask]:
        for t in self._tasks:
            if t.task_id == task_id:
                return t
        return None

    def get_all_tasks(self) -> list[AutoTask]:
        return list(self._tasks)

    def get_active_tasks(self) -> list[AutoTask]:
        return [t for t in self._tasks if t.enabled and t.status == "active"]

    def toggle_enabled(self, task_id: str) -> bool:
        for t in self._tasks:
            if t.task_id == task_id:
                t.enabled = not t.enabled
                if t.enabled and not t.next_run:
                    t.next_run = t.compute_next_run()
                self.save()
                self._notify()
                return True
        return False

    def pause_task(self, task_id: str) -> bool:
        return self.update_task(task_id, status="paused")

    def resume_task(self, task_id: str) -> bool:
        for t in self._tasks:
            if t.task_id == task_id:
                t.status = "active"
                t.next_run = t.compute_next_run()
                self.save()
                self._notify()
                return True
        return False

    def complete_task(self, task_id: str) -> bool:
        return self.update_task(task_id, status="completed")

    # ── P4: 自动清理已完成的 once 任务 ──

    def cleanup_old_completed_tasks(self, hours: int = 24) -> int:
        """移除已完成超过指定小时数的 once 任务。返回移除数量。"""
        now = datetime.now()
        to_remove = []
        for t in self._tasks:
            if t.schedule_type != "once":
                continue
            if t.status != "completed":
                continue
            if not t.last_executed:
                # 无执行记录但状态为 completed，也清理
                to_remove.append(t.task_id)
                continue
            try:
                last_dt = datetime.strptime(t.last_executed, "%Y-%m-%d %H:%M")
                if (now - last_dt).total_seconds() > hours * 3600:
                    to_remove.append(t.task_id)
            except ValueError:
                to_remove.append(t.task_id)

        if to_remove:
            self._tasks = [t for t in self._tasks if t.task_id not in to_remove]
            self.save()
            self._notify()
            print(f"[AutoTaskManager] 已清理 {len(to_remove)} 个过期 once 任务")
        return len(to_remove)

    # ── 调度检查 ──

    def get_due_tasks(self) -> list[AutoTask]:
        now = datetime.now()
        due = []
        for t in self._tasks:
            if not t.enabled or t.status != "active":
                continue
            if t.has_reached_max:
                continue
            if not t.next_run:
                t.next_run = t.compute_next_run()
                self.save()
                if not t.next_run:
                    # once 任务无法计算 → 标记为已完成
                    if t.schedule_type == "once":
                        t.status = "completed"
                        self.save()
                        print(f"[AutoTaskManager] once 任务「{t.name}」无有效时间，自动标记完成")
                    else:
                        print(f"[AutoTaskManager] 任务「{t.name}」无法计算 next_run，跳过")
                    continue
                print(f"[AutoTaskManager] 补算 next_run: 「{t.name}」-> {t.next_run}")
                # 补算后不跳过，继续判断是否到期
            try:
                next_dt = datetime.strptime(t.next_run, "%Y-%m-%d %H:%M")
                if next_dt <= now:
                    due.append(t)
            except ValueError:
                continue
        return due

    def get_missed_tasks(self) -> list[AutoTask]:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        missed = []
        for t in self._tasks:
            if not t.enabled or t.status != "active":
                continue
            if t.missed_action != "ask":
                continue
            if t.last_asked_date == today:
                continue
            if not t.next_run:
                continue
            try:
                next_dt = datetime.strptime(t.next_run, "%Y-%m-%d %H:%M")
                if next_dt < now:
                    missed.append(t)
            except ValueError:
                continue
        return missed

    def mark_asked(self, task_id: str):
        today = datetime.now().strftime("%Y-%m-%d")
        self.update_task(task_id, last_asked_date=today)

    def mark_executed(self, task_id: str, success: bool, result: str = ""):
        for t in self._tasks:
            if t.task_id == task_id:
                t.last_executed = datetime.now().strftime("%Y-%m-%d %H:%M")
                t.execution_count += 1
                t.last_result = result
                if success:
                    # once 类型执行一次即完成
                    if t.schedule_type == "once":
                        t.status = "completed"
                        t.next_run = ""
                        print(f"[AutoTaskManager] 一次性任务「{t.name}」已完成")
                    elif t.has_reached_max:
                        t.status = "completed"
                        print(f"[AutoTaskManager] 任务「{t.name}」已完成(已达最大执行次数 {t.max_executions})")
                    else:
                        t.next_run = t.compute_next_run()
                        print(f"[AutoTaskManager] 任务「{t.name}」执行成功，下次: {t.next_run}")
                else:
                    print(f"[AutoTaskManager] 任务「{t.name}」执行失败: {result[:100]}")
                self.save()
                self._notify()
                return

    # ── 工具链管理 ──

    def set_actions(self, task_id: str, actions: list[ActionStep]) -> bool:
        return self.update_task(task_id, actions=actions)

    def has_actions(self, task_id: str) -> bool:
        t = self.get_task(task_id)
        return t is not None and len(t.actions) > 0

    # ── 执行日志 ──

    def add_log(self, task_id: str, step: int, success: bool,
                message: str, duration_ms: int = 0):
        log_entry = {
            "task_id": task_id,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "step": step,
            "success": success,
            "message": message,
            "duration_ms": duration_ms,
        }
        self._execution_logs.append(log_entry)
        if len(self._execution_logs) > 500:
            self._execution_logs = self._execution_logs[-200:]
        self._save_logs()

    def get_logs(self, task_id: str = None, limit: int = 50) -> list[dict]:
        if task_id:
            return [l for l in self._execution_logs if l["task_id"] == task_id][-limit:]
        return self._execution_logs[-limit:]

    def get_workflow_runs(self, task_id: str) -> list[dict]:
        return self._store.list_workflows("auto_task", task_id)

    def bind_workflow(self, task_id: str, workflow_run_id: int,
                      relation: str = "execution") -> None:
        self._store.bind_workflow("auto_task", task_id, workflow_run_id, relation)

    def link_todo(self, task_id: str, todo_id: str, relation: str = "automates") -> None:
        self._store.link_tasks("todo", todo_id, "auto_task", task_id, relation)

    # ── 观察者 ──

    def observe(self, callback: Callable[[], None]):
        self._observers.append(callback)

    def unobserve(self, callback: Callable[[], None]):
        if callback in self._observers:
            self._observers.remove(callback)

    def _notify(self):
        for cb in self._observers:
            try:
                cb()
            except Exception:
                pass


# ── 单例 ──

_auto_task_manager: Optional[AutoTaskManager] = None


def get_auto_task_manager() -> AutoTaskManager:
    global _auto_task_manager
    if _auto_task_manager is None:
        _auto_task_manager = AutoTaskManager()
    return _auto_task_manager
