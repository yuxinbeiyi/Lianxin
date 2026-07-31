"""进程内具身运行时宿主：单例时钟、并发保护与状态查询。"""

from __future__ import annotations

import threading
import time

from brain.physical.models import PhysicalTask
from brain.physical.runtime import PhysicalRuntime


class PhysicalRuntimeHost:
    def __init__(self, runtime: PhysicalRuntime | None = None, *, tick_seconds: float = 0.02):
        self.runtime = runtime or PhysicalRuntime()
        self.tick_seconds = tick_seconds
        self.lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="physical-runtime", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def submit_navigation(self, marker_id: str) -> PhysicalTask:
        with self.lock:
            return self.runtime.submit_navigation(marker_id)

    def manual_move(self, direction: str) -> bool:
        """在线程锁内执行一格手动蛇控制。"""
        with self.lock:
            return self.runtime.manual_move(direction)

    def cancel_active_task(self) -> bool:
        with self.lock:
            return self.runtime.cancel_active_task()

    def emergency_stop(self) -> bool:
        with self.lock:
            return self.runtime.emergency_stop()

    def status(self) -> dict:
        with self.lock:
            world = self.runtime.world
            task = world.active_task
            return {
                "running": self._thread is not None and self._thread.is_alive(),
                "snake": {
                    "x": round(world.snake.head.x, 1),
                    "y": round(world.snake.head.y, 1),
                    "direction": world.snake.direction,
                    "speed": round(world.snake.speed, 1),
                },
                "active_marker_id": world.active_marker_id,
                "task": None if task is None else {
                    "id": task.id, "kind": task.kind, "status": task.status.value,
                    "error": task.error,
                },
            }

    def _run(self) -> None:
        deadline = time.monotonic()
        while not self._stop_event.is_set():
            with self.lock:
                self.runtime.tick(self.tick_seconds)
            deadline += self.tick_seconds
            self._stop_event.wait(max(0.0, deadline - time.monotonic()))


_host: PhysicalRuntimeHost | None = None
_host_lock = threading.Lock()


def get_physical_runtime_host() -> PhysicalRuntimeHost:
    global _host
    if _host is None:
        with _host_lock:
            if _host is None:
                _host = PhysicalRuntimeHost()
                _host.start()
    return _host
