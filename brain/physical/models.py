"""具身运行时的无副作用领域模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Obstacle:
    x: float
    y: float
    width: float
    height: float
    id: str = ""

    def contains(self, point: Point, *, margin: float = 0.0) -> bool:
        return (
            self.x - margin <= point.x <= self.x + self.width + margin
            and self.y - margin <= point.y <= self.y + self.height + margin
        )


@dataclass(frozen=True)
class Marker:
    id: str
    position: Point


@dataclass
class SnakeState:
    """离散网格贪吃蛇状态，body[0] 永远是蛇头。"""
    body: list[Point]
    direction: str = "right"
    speed: float = 0.0

    @property
    def head(self) -> Point:
        return self.body[0]


# 保留导入兼容，后续模块统一改用 SnakeState。
TankState = SnakeState


class TaskStatus(str, Enum):
    QUEUED = "QUEUED"
    VALIDATING = "VALIDATING"
    PLANNING = "PLANNING"
    PATH_READY = "PATH_READY"
    MOVING = "MOVING"
    ARRIVED = "ARRIVED"
    NO_PATH = "NO_PATH"
    INVALID_GOAL = "INVALID_GOAL"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            TaskStatus.ARRIVED,
            TaskStatus.NO_PATH,
            TaskStatus.INVALID_GOAL,
            TaskStatus.BLOCKED,
            TaskStatus.CANCELLED,
        }


@dataclass
class PhysicalTask:
    id: str
    kind: str
    payload: dict[str, Any]
    status: TaskStatus = TaskStatus.QUEUED
    path: list[Point] = field(default_factory=list)
    path_index: int = 0
    error: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
