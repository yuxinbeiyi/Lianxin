"""固定步长的二维坦克路径跟随控制器。"""

from __future__ import annotations

from brain.physical.models import Point
from brain.physical.world import WorldState


class SnakeController:
    """固定节拍消费 A* 路径的离散网格控制器。"""
    def __init__(self, *, step_seconds: float = 0.14):
        self.step_seconds = step_seconds
        self._elapsed = 0.0

    def follow_path(self, world: WorldState, path: list[Point], path_index: int, dt: float) -> tuple[int, bool, bool]:
        """每到一个节拍移动一格，返回路径索引、到达与碰撞状态。"""
        if dt <= 0 or not path:
            return path_index, False, False
        self._elapsed += dt
        if self._elapsed < self.step_seconds:
            return path_index, False, False
        self._elapsed %= self.step_seconds
        snake = world.snake
        while path_index < len(path) and path[path_index] == snake.head:
            path_index += 1
        if path_index >= len(path):
            snake.speed = 0.0
            return path_index, True, False
        if not self.move(world, path[path_index]):
            return path_index, False, True
        return path_index + 1, path_index + 1 >= len(path), False

    def move(self, world: WorldState, target: Point) -> bool:
        """将蛇整体前移一格；本阶段不增加身体长度。"""
        snake = world.snake
        if not world.is_snake_move_free(target):
            snake.speed = 0.0
            return False
        snake.direction = self._direction(snake.head, target)
        snake.body = [target, *snake.body[:-1]]
        snake.speed = 1.0 / self.step_seconds
        world.revision += 1
        return True

    @staticmethod
    def _direction(origin: Point, target: Point) -> str:
        if target.x > origin.x:
            return "right"
        if target.x < origin.x:
            return "left"
        return "down" if target.y > origin.y else "up"
