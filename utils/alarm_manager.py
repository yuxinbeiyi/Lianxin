"""
AlarmManager：闹钟数据管理
管理定时闹钟列表，支持持久化到用户目录/.lianxin/alarms.json。
"""

import json
import uuid
from pathlib import Path
from datetime import datetime, date, timedelta
from utils.paths import get_user_data_dir

_ALARMS_PATH = get_user_data_dir() / "alarms.json"

# 重复模式映射（内部键 → 显示文字）
REPEAT_LABELS = {
    "once":     "仅一次",
    "daily":    "每天",
    "weekdays": "工作日",
    "weekends": "周末",
}

# 重复模式显示文字 → 内部键
REPEAT_VALUES = {v: k for k, v in REPEAT_LABELS.items()}


class AlarmItem:
    def __init__(self, id=None, name="", time_str="08:00",
                 repeat="once", enabled=True, last_fired_date=""):
        self.id              = id or str(uuid.uuid4())[:8]
        self.name            = name            # 闹钟备注名
        self.time_str        = time_str        # "HH:MM"
        self.repeat          = repeat          # once / daily / weekdays / weekends
        self.enabled         = enabled         # 是否启用
        self.last_fired_date = last_fired_date # "YYYY-MM-DD"，防止同天重复触发

    def to_dict(self) -> dict:
        return {
            "id":              self.id,
            "name":            self.name,
            "time_str":        self.time_str,
            "repeat":          self.repeat,
            "enabled":         self.enabled,
            "last_fired_date": self.last_fired_date,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AlarmItem":
        return cls(
            id=d.get("id"),
            name=d.get("name", ""),
            time_str=d.get("time_str", "08:00"),
            repeat=d.get("repeat", "once"),
            enabled=d.get("enabled", True),
            last_fired_date=d.get("last_fired_date", ""),
        )


class CountdownItem:
    """倒计时项（不持久化，仅运行时）"""
    def __init__(self, id=None, name="", total_seconds=0, remaining_seconds=0):
        self.id = id or str(uuid.uuid4())[:8]
        self.name = name              # 倒计时备注名
        self.total_seconds = total_seconds  # 总秒数
        self.remaining_seconds = remaining_seconds  # 剩余秒数
        self.end_time = None          # 结束时间（datetime）


class AlarmManager:
    def __init__(self):
        self._alarms: list[AlarmItem] = []
        self._countdowns: list[CountdownItem] = []  # 运行时倒计时
        self._load()

    # ── 持久化 ────────────────────────────────────────────────

    def _load(self):
        try:
            if _ALARMS_PATH.exists():
                raw = json.loads(_ALARMS_PATH.read_text(encoding="utf-8"))
                self._alarms = [AlarmItem.from_dict(d) for d in raw.get("alarms", [])]
            else:
                self._alarms = []
        except Exception:
            self._alarms = []

    def save(self):
        _ALARMS_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            _ALARMS_PATH.write_text(
                json.dumps(
                    {"alarms": [a.to_dict() for a in self._alarms]},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ── 闹钟 CRUD ─────────────────────────────────────────────

    def get_alarms(self) -> list[AlarmItem]:
        return list(self._alarms)

    def add_alarm(self, name: str, time_str: str, repeat: str) -> AlarmItem:
        alarm = AlarmItem(name=name, time_str=time_str, repeat=repeat)
        self._alarms.append(alarm)
        self.save()
        return alarm

    def update_alarm(self, alarm_id: str, name: str, time_str: str,
                     repeat: str, enabled: bool):
        for a in self._alarms:
            if a.id == alarm_id:
                a.name = name
                a.time_str = time_str
                a.repeat = repeat
                a.enabled = enabled
                self.save()
                break

    def delete_alarm(self, alarm_id: str):
        self._alarms = [a for a in self._alarms if a.id != alarm_id]
        self.save()

    def toggle_enabled(self, alarm_id: str):
        for a in self._alarms:
            if a.id == alarm_id:
                a.enabled = not a.enabled
                self.save()
                break

    # ── 倒计时 CRUD（运行时）────────────────────────────────

    def add_countdown(self, name: str, total_seconds: int) -> CountdownItem:
        """添加一个倒计时"""
        now = datetime.now()
        item = CountdownItem(
            name=name,
            total_seconds=total_seconds,
            remaining_seconds=total_seconds
        )
        item.end_time = now + timedelta(seconds=total_seconds)
        self._countdowns.append(item)
        return item

    def get_countdowns(self) -> list[CountdownItem]:
        """获取所有运行中的倒计时"""
        return list(self._countdowns)

    def remove_countdown(self, countdown_id: str):
        """移除倒计时"""
        self._countdowns = [c for c in self._countdowns if c.id != countdown_id]

    def update_countdowns(self):
        """
        更新所有倒计时的剩余时间，返回已结束的倒计时列表。
        注意：此方法会移除已结束的倒计时。
        """
        now = datetime.now()
        finished = []
        remaining = []
        for cd in self._countdowns:
            if cd.end_time and now >= cd.end_time:
                finished.append(cd)
            else:
                if cd.end_time:
                    cd.remaining_seconds = max(0, int((cd.end_time - now).total_seconds()))
                remaining.append(cd)
        self._countdowns = remaining
        return finished

    # ── 触发判断 ──────────────────────────────────────────────

    def get_due_alarms(self) -> list[AlarmItem]:
        """返回当前时刻应响的闹钟列表（每天每个闹钟最多触发一次）。"""
        now = datetime.now()
        current_hhmm = now.strftime("%H:%M")
        today = date.today().isoformat()
        weekday = now.weekday()

        due = []
        for alarm in self._alarms:
            if not alarm.enabled:
                continue
            if alarm.time_str != current_hhmm:
                continue
            if alarm.last_fired_date == today:
                continue
            if alarm.repeat == "weekdays" and weekday >= 5:
                continue
            if alarm.repeat == "weekends" and weekday < 5:
                continue
            due.append(alarm)
        
        return due

    def mark_fired(self, alarm_id: str):
        """记录闹钟已响；仅一次的闹钟自动禁用。"""
        today = date.today().isoformat()
        for a in self._alarms:
            if a.id == alarm_id:
                a.last_fired_date = today
                if a.repeat == "once":
                    a.enabled = False
                self.save()
                break