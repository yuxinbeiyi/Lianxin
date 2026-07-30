"""PAL：管理具身任务、状态机、取消与固定步长推进。"""

from __future__ import annotations

import itertools
import time
from collections import deque

from brain.physical.models import PhysicalTask, TaskStatus
from brain.physical.planner import AStarPlanner
from brain.physical.simulator import SnakeSimulator
from brain.physical.world import WorldState


class PhysicalRuntime:
    def __init__(self, world: WorldState | None = None, *, cell_size: int = 20,
                 simulator: SnakeSimulator | None = None):
        self.world = world or WorldState()
        self.planner = AStarPlanner(self.world, cell_size=cell_size)
        self.simulator = simulator or SnakeSimulator(self.world)
        self._queue: deque[PhysicalTask] = deque()
        self._task_ids = itertools.count(1)
        self.event_log: list[dict] = []
        self._event_listeners: list = []

    def add_event_listener(self, listener) -> None:
        if listener not in self._event_listeners:
            self._event_listeners.append(listener)

    def submit_navigation(self, marker_id: str, *, objective: str = "shortest") -> PhysicalTask:
        return self._enqueue("navigate_to_marker", {"marker_id": marker_id, "objective": objective})

    def find_pending_task(self, kind: str) -> PhysicalTask | None:
        """返回活动或排队中的同类未终止任务，供入口层去重。"""
        active = self.world.active_task
        if active is not None and active.kind == kind and not active.status.is_terminal:
            return active
        return next((task for task in self._queue if task.kind == kind and not task.status.is_terminal), None)

    def manual_move(self, direction: str) -> bool:
        """在无自动导航任务时执行一次手动蛇移动。"""
        if self.find_pending_task("navigate_to_marker") is not None:
            raise ValueError("自动导航执行中，不能执行手动移动")
        moved = self.simulator.manual_move(direction)
        self.world.revision += 1
        return moved

    def cancel_active_task(self) -> bool:
        task = self.world.active_task
        if task is None or task.status.is_terminal:
            return False
        self.simulator.stop()
        self._set_status(task, TaskStatus.CANCELLED, "任务已取消")
        return True

    def emergency_stop(self) -> bool:
        self._queue.clear()
        return self.cancel_active_task()

    def reset(self) -> None:
        self._queue.clear()
        self.simulator.stop()
        self.world.active_task = None
        point_type = self.world.snake.head.__class__
        self.world.snake.body = [
            point_type(180, 400), point_type(160, 400), point_type(140, 400),
        ]
        self.world.snake.direction = "right"
        self.world.snake.speed = 0.0
        self.world.revision += 1

    def tick(self, dt: float = 0.02) -> None:
        if dt <= 0:
            raise ValueError("dt 必须大于零")
        task = self.world.active_task
        if task is None or task.status.is_terminal:
            task = self._start_next_task()
            if task is None:
                return

        if task.kind == "navigate_to_marker":
            self._tick_navigation(task, dt)
        else:
            self._set_status(task, TaskStatus.INVALID_GOAL, f"未知任务类型：{task.kind}")

    def _enqueue(self, kind: str, payload: dict) -> PhysicalTask:
        task = PhysicalTask(id=f"physical-{next(self._task_ids)}", kind=kind, payload=payload)
        self._queue.append(task)
        self._emit(task, "queued")
        return task

    def _start_next_task(self) -> PhysicalTask | None:
        if not self._queue:
            return None
        task = self._queue.popleft()
        self.world.active_task = task
        self.world.revision += 1
        self._set_status(task, TaskStatus.VALIDATING)
        return task

    def _tick_navigation(self, task: PhysicalTask, dt: float) -> None:
        if task.status == TaskStatus.VALIDATING:
            marker = self.world.markers.get(str(task.payload["marker_id"]))
            if marker is None or not self.world.is_position_free(marker.position):
                self._set_status(task, TaskStatus.INVALID_GOAL, "目标标记不存在或不可到达")
                return
            # 目标在任务开始时冻结；后续界面编辑不会改写在途任务的终点。
            task.payload["target_x"] = marker.position.x
            task.payload["target_y"] = marker.position.y
            self._set_status(task, TaskStatus.PLANNING)
        if task.status == TaskStatus.PLANNING:
            target = self.world.snake.head.__class__(task.payload["target_x"], task.payload["target_y"])
            path = self.planner.plan(self.world.snake.head, target)
            if path is None:
                self._set_status(task, TaskStatus.NO_PATH, "找不到可通行路径")
                return
            task.path = path
            task.path_index = 0
            self._set_status(task, TaskStatus.PATH_READY)
        if task.status == TaskStatus.PATH_READY:
            self._set_status(task, TaskStatus.MOVING)
        if task.status == TaskStatus.MOVING:
            task.path_index, arrived, blocked = self.simulator.follow_path(task.path, task.path_index, dt)
            if blocked:
                self._set_status(task, TaskStatus.BLOCKED, "执行中检测到碰撞")
            elif arrived:
                self._set_status(task, TaskStatus.ARRIVED)


    def _set_status(self, task: PhysicalTask, status: TaskStatus, error: str = "") -> None:
        task.status = status
        task.error = error
        self.world.revision += 1
        self._emit(task, "status_changed")

    def _emit(self, task: PhysicalTask, event_type: str) -> None:
        event = {
            "type": event_type, "task_id": task.id, "status": task.status.value,
            "error": task.error, "timestamp": round(time.time(), 3),
        }
        task.events.append(event)
        self.event_log.append(event)
        for listener in tuple(self._event_listeners):
            try:
                listener(task, event)
            except Exception:
                # 审计或订阅者失败不能中断物理控制闭环。
                continue
