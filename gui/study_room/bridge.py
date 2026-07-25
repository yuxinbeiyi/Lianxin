"""莲心自习室 Web 前端与 Python 计时/数据层之间的桥接。"""

import json
from datetime import datetime

from PyQt5.QtCore import QObject, QSettings, QTimer, pyqtSignal, pyqtSlot

from .database import StudyDatabase
from .timer import FocusTimer

try:
    from config import get_user_name
except Exception:  # pragma: no cover - 启动早期配置异常时使用回退称呼
    get_user_name = lambda: "雨心"


class StudyRoomBridge(QObject):
    """QWebChannel 暴露的稳定后端接口，前端不直接接触 SQLite。"""

    timer_tick = pyqtSignal(str)
    phase_changed = pyqtSignal(str)
    tasks_changed = pyqtSignal(str)
    statistics_changed = pyqtSignal(str)
    companion_message = pyqtSignal(str)
    focus_completed = pyqtSignal(str)
    clock_changed = pyqtSignal(str)
    minimize_requested = pyqtSignal()
    fullscreen_requested = pyqtSignal()
    focus_fullscreen_requested = pyqtSignal(bool)
    close_requested = pyqtSignal()

    def __init__(self, parent=None, db_path=None):
        super().__init__(parent)
        self.db = StudyDatabase(db_path)
        self.visit_id = self.db.open_visit()
        self.timer = FocusTimer(self)
        self.timer.tick.connect(self._on_tick)
        self.timer.phase_changed.connect(self._on_phase_changed)
        self.timer.completed.connect(self._on_completed)
        self._closed = False
        self._task_id = None
        self._settings = QSettings("Lianxin", "StudyRoom")
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(30_000)
        self._clock_timer.timeout.connect(self._emit_clock)
        self._clock_timer.start()
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(30_000)
        self._stats_timer.timeout.connect(self._emit_statistics)
        self._stats_timer.start()

    @staticmethod
    def _json(payload):
        return json.dumps(payload, ensure_ascii=False)

    def _task_payload(self):
        return [
            {"id": task["id"], "title": task["title"], "completed": bool(task["completed"]),
             "estimate_minutes": task["estimate_minutes"], "break_minutes": task.get("break_minutes", 5),
             "repeat_enabled": bool(task.get("repeat_enabled", 0))}
            for task in self.db.tasks()
        ]

    def _stats_payload(self):
        data = self.db.stats_range("today")
        trend = self.db.week_trend()
        return {
            "focus_seconds": data["focus_seconds"],
            "room_seconds": data["room_seconds"],
            "visits": data["visits"],
            "completed": data["completed"],
            "completed_sessions": data.get("completed_sessions", data["completed"]),
            "interrupted_sessions": data.get("interrupted_sessions", 0),
            "completed_tasks": data.get("completed_tasks", 0),
            "streak": self.db.streak(),
            "period": "today",
            "previous_focus_seconds": data.get("previous_focus_seconds", 0),
            "previous_completed_sessions": data.get("previous_completed_sessions", 0),
            "previous_label": data.get("previous_label", "昨天"),
            "trend": [{"date": row["date"].isoformat(), "focus_seconds": row["focus_seconds"]} for row in trend],
        }

    def _state_payload(self):
        return {
            "tasks": self._task_payload(),
            "stats": self._stats_payload(),
            "timer": {
                "phase": self.timer.phase,
                "remaining": self.timer.remaining,
                "total": self.timer.total,
                "break_seconds": self.timer.break_seconds,
                "repeat_enabled": self.timer.repeat_enabled,
                "task_name": self.timer.task_name,
                "active": self.timer.active,
                "paused": self.timer.paused,
            },
            "user_name": get_user_name(),
            "settings": self._settings_payload(),
            "clock": self._clock_payload(),
        }

    @staticmethod
    def _clock_payload():
        now = datetime.now()
        weekdays = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
        lunar = "农历日期不可用"
        try:
            from zhdate import ZhDate
            value = ZhDate.from_datetime(now)
            months = ("", "正", "二", "三", "四", "五", "六", "七", "八", "九", "十", "冬", "腊")
            days = ("", "初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
                    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
                    "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十")
            prefix = "闰" if getattr(value, "is_leap", getattr(value, "leap_month", False)) else ""
            lunar = f"农历{prefix}{months[value.lunar_month]}月{days[value.lunar_day]}"
        except Exception:
            pass
        return {"time": now.strftime("%H:%M"), "date": f"{now.year}年{now.month}月{now.day}日",
                "weekday": weekdays[now.weekday()], "lunar": lunar}

    def _emit_clock(self):
        self.clock_changed.emit(self._json(self._clock_payload()))

    def _settings_payload(self):
        return {
            "focus_minutes": int(self._settings.value("focus_minutes", 25)),
            "break_minutes": int(self._settings.value("break_minutes", 5)),
            "auto_break": str(self._settings.value("auto_break", "true")).lower() in ("1", "true", "yes"),
            "auto_fullscreen": str(self._settings.value("auto_fullscreen", "true")).lower() in ("1", "true", "yes"),
            "show_completion": str(self._settings.value("show_completion", "true")).lower() in ("1", "true", "yes"),
            "animations": str(self._settings.value("animations", "true")).lower() in ("1", "true", "yes"),
        }

    def _emit_tasks_and_stats(self):
        self.tasks_changed.emit(self._json(self._task_payload()))
        self._emit_statistics()

    def _emit_statistics(self):
        self.statistics_changed.emit(self._json(self._stats_payload()))

    @pyqtSlot(result=str)
    def get_initial_state(self):
        return self._json(self._state_payload())

    @pyqtSlot(str, result=str)
    def get_statistics(self, period="today"):
        period = period if period in ("today", "week", "month", "year") else "today"
        data = self.db.stats_range(period)
        data["streak"] = self.db.streak()
        trend = self.db.week_trend()
        data["trend"] = [{"date": row["date"].isoformat(), "focus_seconds": row["focus_seconds"]} for row in trend]
        return self._json(data)

    @pyqtSlot(int, int, int)
    def start_focus(self, focus_minutes, break_minutes, task_id=-1):
        if self.timer.active:
            return
        task_id = int(task_id)
        task_name = ""
        task_estimate = None
        task_break = None
        task_repeat = False
        if task_id >= 0:
            for task in self.db.tasks(include_completed=False):
                if task["id"] == task_id:
                    task_name = task["title"]
                    task_estimate = task["estimate_minutes"]
                    task_break = task.get("break_minutes", 5)
                    task_repeat = bool(task.get("repeat_enabled", 0))
                    break
        self._task_id = task_id if task_name else None
        if task_estimate:
            focus_minutes = task_estimate
        if task_break is not None:
            break_minutes = task_break
        focus_minutes = max(1, min(180, int(focus_minutes)))
        break_minutes = max(0, min(60, int(break_minutes)))
        self.timer.start_focus(focus_minutes * 60, break_minutes * 60, task_name, task_repeat)
        self.companion_message.emit("专注已经开始了。我会在这里陪你，把注意力留给眼前这一件事。")

    @pyqtSlot()
    def toggle_pause(self):
        self.timer.toggle_pause()

    @pyqtSlot()
    def stop_focus(self):
        if not self.timer.active:
            return
        phase = self.timer.phase
        started_at = self.timer.started_at
        elapsed = self.timer.stop()
        if phase == "focus" and elapsed > 0:
            self.db.add_focus_session(self._task_id, self.timer.task_name, started_at, elapsed, False)
        self._emit_tasks_and_stats()
        self.companion_message.emit("这一段先到这里也没关系，能够开始并坚持一会儿，本身就是积累。")

    @pyqtSlot(str, int, int, bool, result=int)
    def add_task(self, title, estimate_minutes=25, break_minutes=5, repeat_enabled=False):
        title = (title or "").strip()
        if not title:
            return 0
        task_id = self.db.add_task(title, max(1, min(600, int(estimate_minutes))),
                                   max(0, min(60, int(break_minutes))), bool(repeat_enabled))
        self._emit_tasks_and_stats()
        return task_id

    @pyqtSlot(int)
    def toggle_task(self, task_id):
        self.db.toggle_task(int(task_id))
        self._emit_tasks_and_stats()

    @pyqtSlot(int)
    def delete_task(self, task_id):
        self.db.delete_task(int(task_id))
        self._emit_tasks_and_stats()

    @pyqtSlot(int, str, int, int, bool)
    def update_task(self, task_id, title, estimate_minutes=25, break_minutes=5, repeat_enabled=False):
        title = (title or "").strip()
        if not title:
            return
        self.db.update_task(
            int(task_id), title, max(1, min(600, int(estimate_minutes))),
            max(0, min(60, int(break_minutes))), bool(repeat_enabled),
        )
        self._emit_tasks_and_stats()
        self.companion_message.emit("任务配置已更新，开始专注时会使用新的时长。")

    @pyqtSlot()
    def refresh_statistics(self):
        self.statistics_changed.emit(self._json(self._stats_payload()))

    @pyqtSlot(int, int, bool, bool, bool, bool)
    def save_settings(self, focus_minutes, break_minutes, auto_break, auto_fullscreen,
                      show_completion, animations):
        self._settings.setValue("focus_minutes", max(1, min(180, int(focus_minutes))))
        self._settings.setValue("break_minutes", max(0, min(60, int(break_minutes))))
        self._settings.setValue("auto_break", bool(auto_break))
        self._settings.setValue("auto_fullscreen", bool(auto_fullscreen))
        self._settings.setValue("show_completion", bool(show_completion))
        self._settings.setValue("animations", bool(animations))
        self._settings.sync()
        self.companion_message.emit("自习室设置已保存，之后开始专注时会使用新的偏好。")

    @pyqtSlot()
    def minimize_window(self):
        self.minimize_requested.emit()

    @pyqtSlot()
    def toggle_fullscreen(self):
        self.fullscreen_requested.emit()

    @pyqtSlot(bool)
    def set_focus_fullscreen(self, enabled):
        """进入/离开沉浸专注时请求窗口调整，宿主负责保留原窗口状态。"""
        self.focus_fullscreen_requested.emit(bool(enabled))

    @pyqtSlot()
    def close_window(self):
        self.close_requested.emit()

    def _on_tick(self, remaining, phase):
        self.timer_tick.emit(self._json({"remaining": remaining, "total": self.timer.total, "phase": phase,
                                         "task_name": self.timer.task_name,
                                         "repeat_enabled": self.timer.repeat_enabled}))

    def _on_phase_changed(self, phase):
        self.phase_changed.emit(phase)

    def _on_completed(self, phase, duration):
        if phase == "focus":
            self.db.add_focus_session(self._task_id, self.timer.task_name,
                                      self.timer.started_at, duration, True)
            self._emit_tasks_and_stats()
            self.focus_completed.emit(self._json({"task_name": self.timer.task_name, "duration": duration}))
            self.companion_message.emit("辛苦啦，这段时间你确实专注在重要的事情上。接下来可以喝口水，再决定是否继续。")
        else:
            self.companion_message.emit("休息结束了。准备好之后，再慢慢回到下一段专注吧。")

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        if self.timer.active:
            phase = self.timer.phase
            elapsed = self.timer.stop()
            if phase == "focus" and elapsed > 0:
                self.db.add_focus_session(self._task_id, self.timer.task_name,
                                          self.timer.started_at, elapsed, False)
        self.db.close_visit(self.visit_id)
