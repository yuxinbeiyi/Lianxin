"""虚拟世界的唯一权威状态。"""

from __future__ import annotations

from dataclasses import dataclass, field

from brain.physical.models import Marker, Obstacle, PhysicalTask, Point, SnakeState


@dataclass
class WorldState:
    width: int = 800
    height: int = 800
    snake: SnakeState = field(default_factory=lambda: SnakeState([
        Point(180, 400), Point(160, 400), Point(140, 400),
    ]))
    obstacles: list[Obstacle] = field(default_factory=list)
    markers: dict[str, Marker] = field(default_factory=dict)
    active_marker_id: str = ""
    active_task: PhysicalTask | None = None
    revision: int = 0

    def add_marker(self, marker: Marker, *, active: bool = True) -> None:
        self._require_in_bounds(marker.position)
        self.markers[marker.id] = marker
        if active:
            self.active_marker_id = marker.id
        self.revision += 1

    def add_obstacle(self, obstacle: Obstacle) -> None:
        if obstacle.width <= 0 or obstacle.height <= 0:
            raise ValueError("障碍物的宽高必须大于零")
        self._require_in_bounds(Point(obstacle.x, obstacle.y))
        self._require_in_bounds(Point(obstacle.x + obstacle.width, obstacle.y + obstacle.height))
        self.obstacles.append(obstacle)
        self.revision += 1

    def clear_obstacles(self) -> None:
        if self.obstacles:
            self.obstacles.clear()
            self.revision += 1

    def remove_obstacle_at(self, point: Point) -> bool:
        for index in range(len(self.obstacles) - 1, -1, -1):
            if self.obstacles[index].contains(point):
                del self.obstacles[index]
                self.revision += 1
                return True
        return False

    def is_position_free(self, point: Point, *, radius: float = 0.0) -> bool:
        if point.x - radius < 0 or point.y - radius < 0:
            return False
        if point.x + radius > self.width or point.y + radius > self.height:
            return False
        return not any(obstacle.contains(point, margin=radius) for obstacle in self.obstacles)

    def is_snake_move_free(self, point: Point) -> bool:
        """判断蛇头能否进入目标格，尾格本步会移出，允许复用。"""
        if not self.is_position_free(point):
            return False
        return point not in self.snake.body[:-1]

    def _require_in_bounds(self, point: Point) -> None:
        if not (0 <= point.x <= self.width and 0 <= point.y <= self.height):
            raise ValueError("位置超出世界边界")
