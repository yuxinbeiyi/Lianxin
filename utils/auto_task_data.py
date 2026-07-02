# -*- coding: utf-8 -*-
"""
auto_task_data.py — 自动化任务数据模型
定义 AutoTask、ActionStep 等核心数据结构。
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional

# 调度类型
SCHEDULE_TYPES = ["once", "interval", "daily", "weekly", "monthly"]
SCHEDULE_LABELS = {
    "once":     "仅一次",
    "interval": "间隔执行",
    "daily":    "每天",
    "weekly":   "每周",
    "monthly":  "每月",
}

# 错过策略
MISSED_ACTIONS = ["ask", "skip", "auto_execute"]
MISSED_LABELS = {
    "ask":          "询问我",
    "skip":         "跳过",
    "auto_execute": "自动补做",
}

# 任务状态 — P3: 新增 "executing" 区分等待与执行中
STATUS_VALUES = ["active", "executing", "paused", "completed", "failed"]
STATUS_LABELS = {
    "active":    "等待中",
    "executing": "执行中…",
    "paused":    "已暂停",
    "completed": "已完成",
    "failed":    "失败",
}


class ActionStep:
    """工具链中的一个执行步骤"""

    def __init__(self, order: int = 0, tool_name: str = "",
                 tool_params: dict = None, description: str = "",
                 depends_on: Optional[int] = None):
        self.order = order
        self.tool_name = tool_name
        self.tool_params = tool_params or {}
        self.description = description
        self.depends_on = depends_on

    def to_dict(self) -> dict:
        return {
            "order": self.order,
            "tool_name": self.tool_name,
            "tool_params": self.tool_params,
            "description": self.description,
            "depends_on": self.depends_on,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ActionStep":
        return cls(
            order=d.get("order", 0),
            tool_name=d.get("tool_name", ""),
            tool_params=d.get("tool_params", {}),
            description=d.get("description", ""),
            depends_on=d.get("depends_on"),
        )


class AutoTask:
    """自动化任务"""

    def __init__(self,
                 task_id: str = None,
                 name: str = "",
                 description: str = "",
                 source: str = "manual",
                 schedule_type: str = "daily",
                 schedule_time: str = "08:00",
                 interval_minutes: int = 0,
                 weekdays: list = None,
                 day_of_month: int = None,
                 advance_minutes: int = 0,
                 enabled: bool = True,
                 actions: list = None,
                 max_executions: Optional[int] = None,
                 execution_count: int = 0,
                 last_executed: str = "",
                 next_run: str = "",
                 missed_action: str = "ask",
                 status: str = "active",
                 last_result: str = "",
                 last_asked_date: str = "",
                 created_at: str = "",
                 tags: list = None,
                 ):
        self.task_id = task_id or uuid.uuid4().hex[:12]
        self.name = name
        self.description = description
        self.source = source
        self.schedule_type = schedule_type
        self.schedule_time = schedule_time
        self.interval_minutes = interval_minutes
        self.weekdays = weekdays or []
        self.day_of_month = day_of_month
        self.advance_minutes = advance_minutes
        self.enabled = enabled
        self.actions = actions or []
        self.max_executions = max_executions
        self.execution_count = execution_count
        self.last_executed = last_executed
        self.next_run = next_run
        self.missed_action = missed_action
        self.status = status
        self.last_result = last_result
        self.last_asked_date = last_asked_date
        self.created_at = created_at or datetime.now().strftime("%Y-%m-%d %H:%M")
        self.tags = tags or []

    # ── 计算属性 ──

    @property
    def is_due(self) -> bool:
        """判断是否到期（next_run <= now）。"""
        if not self.next_run or not self.enabled or self.status != "active":
            return False
        try:
            next_dt = datetime.strptime(self.next_run, "%Y-%m-%d %H:%M")
            return next_dt <= datetime.now()
        except ValueError:
            return False

    @property
    def is_missed(self) -> bool:
        """判断是否错过（next_run < now 且今天还没问过）。"""
        if not self.next_run or not self.enabled or self.status != "active":
            return False
        try:
            next_dt = datetime.strptime(self.next_run, "%Y-%m-%d %H:%M")
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            return next_dt < now and self.last_asked_date != today
        except ValueError:
            return False

    @property
    def has_reached_max(self) -> bool:
        """是否已达到最大执行次数。"""
        if self.max_executions is None:
            return False
        return self.execution_count >= self.max_executions

    def compute_next_run(self, from_time: datetime = None) -> str:
        """根据调度规则计算下次执行时间。"""
        if from_time is None:
            from_time = datetime.now()

        if self.schedule_type == "once":
            # 如果已有 next_run 且在将来，保留
            if self.next_run:
                try:
                    existing = datetime.strptime(self.next_run, "%Y-%m-%d %H:%M")
                    if existing > from_time:
                        return self.next_run
                except ValueError:
                    pass
            # 根据 schedule_time 计算今天的执行时间
            if self.schedule_time:
                try:
                    h, m = self._parse_time()
                    next_dt = from_time.replace(hour=h, minute=m, second=0, microsecond=0)
                    # 如果今天已过，推到明天
                    if next_dt <= from_time:
                        next_dt += timedelta(days=1)
                    return next_dt.strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    pass
            return ""

        if self.schedule_type == "interval":
            if self.interval_minutes <= 0:
                return ""
            next_dt = from_time + timedelta(minutes=self.interval_minutes)
            return next_dt.strftime("%Y-%m-%d %H:%M")

        if self.schedule_type == "daily":
            h, m = self._parse_time()
            next_dt = from_time.replace(hour=h, minute=m, second=0, microsecond=0)
            if next_dt <= from_time:
                next_dt += timedelta(days=1)
            return next_dt.strftime("%Y-%m-%d %H:%M")

        if self.schedule_type == "weekly":
            if not self.weekdays:
                return ""
            h, m = self._parse_time()
            current_wd = from_time.weekday()
            for wd in sorted(self.weekdays):
                days_ahead = wd - current_wd
                if days_ahead < 0 or (days_ahead == 0 and from_time.hour * 60 + from_time.minute >= h * 60 + m):
                    days_ahead += 7
                next_dt = from_time.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=days_ahead)
                return next_dt.strftime("%Y-%m-%d %H:%M")
            return ""

        if self.schedule_type == "monthly":
            if not self.day_of_month:
                return ""
            h, m = self._parse_time()
            try:
                next_dt = from_time.replace(day=min(self.day_of_month, 28), hour=h, minute=m, second=0, microsecond=0)
            except ValueError:
                return ""
            if next_dt <= from_time:
                if from_time.month == 12:
                    next_dt = next_dt.replace(year=from_time.year + 1, month=1)
                else:
                    next_dt = next_dt.replace(month=from_time.month + 1)
            return next_dt.strftime("%Y-%m-%d %H:%M")

        return ""

    def _parse_time(self) -> tuple:
        """解析 schedule_time 为 (hour, minute)。"""
        try:
            parts = self.schedule_time.split(":")
            return int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            return 8, 0

    # ── 序列化 ──

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "schedule_type": self.schedule_type,
            "schedule_time": self.schedule_time,
            "interval_minutes": self.interval_minutes,
            "weekdays": self.weekdays,
            "day_of_month": self.day_of_month,
            "advance_minutes": self.advance_minutes,
            "enabled": self.enabled,
            "actions": [a.to_dict() if isinstance(a, ActionStep) else a for a in self.actions],
            "max_executions": self.max_executions,
            "execution_count": self.execution_count,
            "last_executed": self.last_executed,
            "next_run": self.next_run,
            "missed_action": self.missed_action,
            "status": self.status,
            "last_result": self.last_result,
            "last_asked_date": self.last_asked_date,
            "created_at": self.created_at,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AutoTask":
        actions = []
        for a in d.get("actions", []):
            if isinstance(a, ActionStep):
                actions.append(a)
            else:
                actions.append(ActionStep.from_dict(a))
        return cls(
            task_id=d.get("task_id"),
            name=d.get("name", ""),
            description=d.get("description", ""),
            source=d.get("source", "manual"),
            schedule_type=d.get("schedule_type", "daily"),
            schedule_time=d.get("schedule_time", "08:00"),
            interval_minutes=d.get("interval_minutes", 0),
            weekdays=d.get("weekdays", []),
            day_of_month=d.get("day_of_month"),
            advance_minutes=d.get("advance_minutes", 0),
            enabled=d.get("enabled", True),
            actions=actions,
            max_executions=d.get("max_executions"),
            execution_count=d.get("execution_count", 0),
            last_executed=d.get("last_executed", ""),
            next_run=d.get("next_run", ""),
            missed_action=d.get("missed_action", "ask"),
            status=d.get("status", "active"),
            last_result=d.get("last_result", ""),
            last_asked_date=d.get("last_asked_date", ""),
            created_at=d.get("created_at", ""),
            tags=d.get("tags", []),
        )