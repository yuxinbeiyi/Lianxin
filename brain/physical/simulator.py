"""V1 的设备适配器：内存中的二维坦克模拟器。"""

from __future__ import annotations

from brain.physical.controller import SnakeController
from brain.physical.models import Point
from brain.physical.world import WorldState


class SnakeSimulator:
    """二维贪吃蛇的本地设备适配器。"""
    def __init__(self, world: WorldState, controller: SnakeController | None = None):
        self.world = world
        self.controller = controller or SnakeController()

    def follow_path(self, path, path_index: int, dt: float):
        return self.controller.follow_path(self.world, path, path_index, dt)

    def manual_move(self, direction: str) -> bool:
        """执行一次手动单格移动，用于控制器调试。"""
        head = self.world.snake.head
        offsets = {"up": (0, -20), "down": (0, 20), "left": (-20, 0), "right": (20, 0)}
        if direction not in offsets:
            raise ValueError("direction 必须是 up、down、left 或 right")
        dx, dy = offsets[direction]
        return self.controller.move(self.world, Point(head.x + dx, head.y + dy))

    def stop(self) -> None:
        self.world.snake.speed = 0.0


TankSimulator = SnakeSimulator
