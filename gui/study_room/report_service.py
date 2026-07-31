"""莲心自习室的本地周报/月报聚合与叙事服务。"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta


class StudyReportService:
    """只读取自习室本地数据，生成可解释、无需 LLM 的周期报告。"""

    def __init__(self, database, today_provider=None):
        self.db = database
        self._today_provider = today_provider or date.today

    def build(self, period: str, anchor: str = "") -> dict:
        period = period if period in {"week", "month"} else "week"
        today = self._today_provider()
        start, end = self._bounds(period, anchor, today)
        is_current = start.date() <= today < end.date()
        current_end = min(end, datetime.combine(today + timedelta(days=1), time.min)) if is_current else end
        previous_start, previous_end, previous_label = self._previous_bounds(
            period, start, end, current_end, is_current,
        )

        current = self._aggregate(start, current_end)
        previous = self._aggregate(previous_start, previous_end)
        elapsed_days = max(1, (current_end.date() - start.date()).days)
        payload = {
            "type": period,
            "anchor": start.date().isoformat(),
            "start": start.date().isoformat(),
            "end": (end.date() - timedelta(days=1)).isoformat(),
            "label": self._label(period, start),
            "is_current": is_current,
            "is_complete": not is_current,
            "elapsed_days": elapsed_days,
            "period_days": (end.date() - start.date()).days,
            "metrics": current["metrics"],
            "comparison": self._comparison(current["metrics"], previous["metrics"], previous_label),
            "daily_trend": current["daily_trend"],
            "weekly_trend": current["weekly_trend"],
            "top_tasks": current["top_tasks"],
            "time_bands": current["time_bands"],
            "highlights": current["highlights"],
        }
        payload["narrative"] = self._narrative(payload)
        return payload

    @staticmethod
    def _bounds(period: str, anchor: str, today: date) -> tuple[datetime, datetime]:
        if period == "month":
            value = today
            if anchor:
                try:
                    value = datetime.strptime(anchor[:7], "%Y-%m").date().replace(day=1)
                except ValueError:
                    pass
            start_day = value.replace(day=1)
            end_day = (start_day.replace(day=28) + timedelta(days=4)).replace(day=1)
        else:
            value = today
            if anchor:
                try:
                    value = datetime.fromisoformat(anchor[:10]).date()
                except ValueError:
                    pass
            start_day = value - timedelta(days=value.weekday())
            end_day = start_day + timedelta(days=7)
        return datetime.combine(start_day, time.min), datetime.combine(end_day, time.min)

    @staticmethod
    def _previous_bounds(period, start, end, current_end, is_current):
        if is_current:
            span = current_end - start
            if period == "month":
                previous_start = (start - timedelta(days=1)).replace(day=1)
                return previous_start, previous_start + span, "上月同期"
            return start - span, start, "上周同期" if period == "week" else "上月同期"
        if period == "month":
            previous_end = start
            previous_start = (start - timedelta(days=1)).replace(day=1)
            return previous_start, previous_end, "上月"
        return start - (end - start), start, "上周"

    @staticmethod
    def _label(period: str, start: datetime) -> str:
        if period == "month":
            return f"{start.year}年{start.month}月"
        end = start + timedelta(days=6)
        return f"{start.month}月{start.day}日–{end.month}月{end.day}日"

    def _aggregate(self, start: datetime, end: datetime) -> dict:
        sessions = self.db.focus_sessions_between(start, end)
        events = self.db.events_between(start, end)
        daily = { (start.date() + timedelta(days=offset)).isoformat(): 0
                  for offset in range((end.date() - start.date()).days) }
        weekly = defaultdict(int)
        task_totals = defaultdict(lambda: {"seconds": 0, "sessions": 0, "completed_sessions": 0})
        bands = {name: 0 for name in ("清晨", "上午", "下午", "晚上", "深夜")}
        active_days = set()
        completed_days = set()
        completed_seconds = interrupted_seconds = longest_seconds = 0

        for item in sessions:
            started = datetime.fromisoformat(item["started_at"])
            day_key = started.date().isoformat()
            seconds = max(0, int(item["duration_seconds"] or 0))
            completed = bool(item["completed"])
            daily.setdefault(day_key, 0)
            daily[day_key] += seconds
            week_key = (started.date() - timedelta(days=started.weekday())).isoformat()
            weekly[week_key] += seconds
            active_days.add(day_key)
            if completed:
                completed_days.add(day_key)
                completed_seconds += seconds
            else:
                interrupted_seconds += seconds
            longest_seconds = max(longest_seconds, seconds)
            task = (item.get("task_name") or "").strip() or "未绑定任务"
            task_totals[task]["seconds"] += seconds
            task_totals[task]["sessions"] += 1
            task_totals[task]["completed_sessions"] += int(completed)
            bands[self._time_band(started.hour)] += seconds

        focus_seconds = completed_seconds + interrupted_seconds
        sessions_count = len(sessions)
        completed_sessions = sum(1 for item in sessions if item["completed"])
        interrupted_sessions = sessions_count - completed_sessions
        task_completed_events = sum(1 for item in events if item["event_type"] == "task_completed")
        active_sorted = sorted(active_days)
        longest_streak = self._longest_streak(active_sorted)
        best_day = max(daily.items(), key=lambda item: item[1], default=("", 0))
        top_band = max(bands.items(), key=lambda item: item[1], default=("", 0))
        room_seconds = self.db.room_seconds_between(start, end)
        metrics = {
            "focus_seconds": focus_seconds,
            "completed_focus_seconds": completed_seconds,
            "interrupted_focus_seconds": interrupted_seconds,
            "sessions": sessions_count,
            "completed_sessions": completed_sessions,
            "interrupted_sessions": interrupted_sessions,
            "completion_rate": round(completed_sessions * 100 / sessions_count) if sessions_count else 0,
            "active_days": len(active_days),
            "completed_days": len(completed_days),
            "longest_streak": longest_streak,
            "longest_session_seconds": longest_seconds,
            "average_session_seconds": round(focus_seconds / sessions_count) if sessions_count else 0,
            "completed_tasks": task_completed_events,
            "room_seconds": room_seconds,
        }
        top_tasks = [
            {"task_name": name, **data}
            for name, data in sorted(task_totals.items(), key=lambda item: (-item[1]["seconds"], item[0]))[:5]
        ]
        highlights = {
            "best_day": {"date": best_day[0], "focus_seconds": best_day[1]} if best_day[1] else None,
            "most_common_time_band": top_band[0] if top_band[1] else "",
            "time_band_seconds": top_band[1],
        }
        return {
            "metrics": metrics,
            "daily_trend": [{"date": key, "focus_seconds": value} for key, value in daily.items()],
            "weekly_trend": [{"week_start": key, "focus_seconds": value} for key, value in sorted(weekly.items())],
            "top_tasks": top_tasks,
            "time_bands": [{"name": name, "focus_seconds": seconds} for name, seconds in bands.items()],
            "highlights": highlights,
        }

    @staticmethod
    def _time_band(hour: int) -> str:
        if 5 <= hour < 9:
            return "清晨"
        if hour < 12:
            return "上午"
        if hour < 18:
            return "下午"
        if hour < 24:
            return "晚上"
        return "深夜"

    @staticmethod
    def _longest_streak(days: list[str]) -> int:
        if not days:
            return 0
        streak = best = 1
        previous = date.fromisoformat(days[0])
        for value in days[1:]:
            current = date.fromisoformat(value)
            streak = streak + 1 if current == previous + timedelta(days=1) else 1
            best = max(best, streak)
            previous = current
        return best

    @staticmethod
    def _comparison(current: dict, previous: dict, label: str) -> dict:
        return {
            "previous_label": label,
            "has_previous_data": bool(previous["sessions"]),
            "focus_delta_seconds": current["focus_seconds"] - previous["focus_seconds"],
            "active_days_delta": current["active_days"] - previous["active_days"],
            "completed_sessions_delta": current["completed_sessions"] - previous["completed_sessions"],
        }

    @staticmethod
    def _narrative(report: dict) -> dict:
        metrics = report["metrics"]
        if not metrics["sessions"]:
            return {
                "title": "从一小段开始就很好",
                "body": "这段时间还没有留下专注记录。自习室会在这里，等你开始第一段属于自己的时间。",
                "suggestion": "下一次只需要完成 25 分钟的小目标。",
            }
        if metrics["active_days"] >= min(4, report["elapsed_days"]):
            title = "你的节奏正在稳定下来"
            body = f"你在 {metrics['active_days']} 天里留下了专注记录，连续学习最长达到 {metrics['longest_streak']} 天。"
            suggestion = "下个周期可以保持相近的开始时间，让这份节奏自然延续。"
        elif metrics["interrupted_sessions"] > metrics["completed_sessions"]:
            title = "重新开始本身也是积累"
            body = f"这段时间共开始了 {metrics['sessions']} 次专注，其中有 {metrics['interrupted_sessions']} 次提前结束。"
            suggestion = "下次可以先选择 25 分钟的小段专注，让回到任务更轻一些。"
        else:
            title = "你正在把时间留给重要的事"
            body = f"你完成了 {metrics['completed_sessions']} 次专注，共投入 {metrics['focus_seconds'] // 60} 分钟。"
            suggestion = "下个周期挑一个最重要的任务，继续从一段专注开始。"
        return {"title": title, "body": body, "suggestion": suggestion}
