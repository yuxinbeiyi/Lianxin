"""栅格化与 A* 路径规划。"""

from __future__ import annotations

import heapq
import itertools
import math

from brain.physical.models import Point
from brain.physical.world import WorldState


class AStarPlanner:
    def __init__(self, world: WorldState, *, cell_size: int = 20):
        if cell_size <= 0:
            raise ValueError("cell_size 必须大于零")
        self.world = world
        self.cell_size = cell_size
        self.columns = math.ceil(world.width / cell_size)
        self.rows = math.ceil(world.height / cell_size)

    def plan(self, start: Point, goal: Point, *, radius: float = 0.0) -> list[Point] | None:
        if not self.world.is_position_free(start, radius=radius):
            return None
        if not self.world.is_position_free(goal, radius=radius):
            return None
        start_cell = self._to_cell(start)
        goal_cell = self._to_cell(goal)
        if not self._is_free(start_cell, radius) or not self._is_free(goal_cell, radius):
            return None
        if start_cell == goal_cell:
            return [goal]

        frontier: list[tuple[float, int, tuple[int, int]]] = []
        sequence = itertools.count()
        heapq.heappush(frontier, (0.0, next(sequence), start_cell))
        came_from: dict[tuple[int, int], tuple[int, int] | None] = {start_cell: None}
        cost: dict[tuple[int, int], float] = {start_cell: 0.0}

        while frontier:
            _, _, current = heapq.heappop(frontier)
            if current == goal_cell:
                return self._build_path(came_from, current, start, goal)
            for neighbor in self._neighbors(current, radius):
                candidate_cost = cost[current] + 1.0
                if candidate_cost >= cost.get(neighbor, float("inf")):
                    continue
                cost[neighbor] = candidate_cost
                priority = candidate_cost + self._manhattan(neighbor, goal_cell)
                heapq.heappush(frontier, (priority, next(sequence), neighbor))
                came_from[neighbor] = current
        return None

    def _build_path(self, came_from, current, start: Point, goal: Point) -> list[Point]:
        cells = [current]
        while came_from[current] is not None:
            current = came_from[current]
            cells.append(current)
        cells.reverse()
        points = [start]
        points.extend(self._cell_center(cell) for cell in cells[1:-1])
        points.append(goal)
        return points

    def _neighbors(self, cell: tuple[int, int], radius: float):
        x, y = cell
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            candidate = (x + dx, y + dy)
            if self._is_free(candidate, radius):
                yield candidate

    def _is_free(self, cell: tuple[int, int], radius: float) -> bool:
        x, y = cell
        if not (0 <= x < self.columns and 0 <= y < self.rows):
            return False
        return self.world.is_position_free(self._cell_center(cell), radius=radius)

    def _to_cell(self, point: Point) -> tuple[int, int]:
        return (
            min(self.columns - 1, max(0, int(point.x // self.cell_size))),
            min(self.rows - 1, max(0, int(point.y // self.cell_size))),
        )

    def _cell_center(self, cell: tuple[int, int]) -> Point:
        x, y = cell
        return Point(
            min(self.world.width - self.cell_size / 2, x * self.cell_size + self.cell_size / 2),
            min(self.world.height - self.cell_size / 2, y * self.cell_size + self.cell_size / 2),
        )

    @staticmethod
    def _manhattan(left: tuple[int, int], right: tuple[int, int]) -> float:
        return abs(left[0] - right[0]) + abs(left[1] - right[1])
