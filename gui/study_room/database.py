"""莲心自习室的轻量 SQLite 数据层。"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from utils.paths import get_user_data_dir


class StudyDatabase:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or (get_user_data_dir() / "study_room.db"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self.path), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self):
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS study_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    estimate_minutes INTEGER NOT NULL DEFAULT 25,
                    break_minutes INTEGER NOT NULL DEFAULT 5,
                    repeat_enabled INTEGER NOT NULL DEFAULT 0,
                    completed INTEGER NOT NULL DEFAULT 0,
                    completed_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS focus_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER,
                    task_name TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    duration_seconds INTEGER NOT NULL DEFAULT 0,
                    completed INTEGER NOT NULL DEFAULT 0,
                    focus_type TEXT NOT NULL DEFAULT '番茄专注'
                );
                CREATE TABLE IF NOT EXISTS room_visits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT
                );
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(study_tasks)")}
            if "break_minutes" not in columns:
                conn.execute("ALTER TABLE study_tasks ADD COLUMN break_minutes INTEGER NOT NULL DEFAULT 5")
            if "repeat_enabled" not in columns:
                conn.execute("ALTER TABLE study_tasks ADD COLUMN repeat_enabled INTEGER NOT NULL DEFAULT 0")
            if "completed_at" not in columns:
                conn.execute("ALTER TABLE study_tasks ADD COLUMN completed_at TEXT")

    @staticmethod
    def _now():
        return datetime.now().replace(microsecond=0).isoformat(sep=" ")

    def add_task(self, title: str, estimate_minutes: int = 25,
                 break_minutes: int = 5, repeat_enabled: bool = False) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO study_tasks
                   (title, estimate_minutes, break_minutes, repeat_enabled, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (title.strip(), max(1, int(estimate_minutes)), max(0, int(break_minutes)),
                 int(bool(repeat_enabled)), self._now()),
            )
            return int(cur.lastrowid)

    def tasks(self, include_completed: bool = True):
        sql = "SELECT * FROM study_tasks"
        if not include_completed:
            sql += " WHERE completed = 0"
        sql += " ORDER BY completed ASC, created_at DESC"
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql)]

    def toggle_task(self, task_id: int):
        with self._connect() as conn:
            conn.execute(
                """UPDATE study_tasks SET
                   completed = CASE completed WHEN 0 THEN 1 ELSE 0 END,
                   completed_at = CASE completed WHEN 0 THEN ? ELSE NULL END
                   WHERE id = ?""",
                (self._now(), int(task_id)),
            )

    def delete_task(self, task_id: int):
        with self._connect() as conn:
            conn.execute("DELETE FROM study_tasks WHERE id = ?", (int(task_id),))

    def update_task(self, task_id: int, title: str, estimate_minutes: int,
                    break_minutes: int, repeat_enabled: bool):
        """更新任务配置，返回是否找到并更新了任务。"""
        with self._connect() as conn:
            cur = conn.execute(
                """UPDATE study_tasks SET title = ?, estimate_minutes = ?,
                   break_minutes = ?, repeat_enabled = ? WHERE id = ?""",
                (title.strip(), max(1, int(estimate_minutes)), max(0, int(break_minutes)),
                 int(bool(repeat_enabled)), int(task_id)),
            )
            return cur.rowcount > 0

    def open_visit(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("INSERT INTO room_visits(opened_at) VALUES (?)", (self._now(),))
            return int(cur.lastrowid)

    def close_visit(self, visit_id: int):
        with self._connect() as conn:
            conn.execute(
                "UPDATE room_visits SET closed_at = COALESCE(closed_at, ?) WHERE id = ?",
                (self._now(), int(visit_id)),
            )

    def add_focus_session(self, task_id, task_name: str, started_at: str,
                          duration_seconds: int, completed: bool):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO focus_sessions
                   (task_id, task_name, started_at, ended_at, duration_seconds, completed)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (task_id, task_name or "未命名专注", started_at, self._now(),
                 max(0, int(duration_seconds)), int(bool(completed))),
            )

    def _day_bounds(self, day=None):
        day = day or datetime.now().date()
        start = datetime.combine(day, datetime.min.time())
        return start, start + timedelta(days=1)

    def stats(self, day=None) -> dict:
        start, end = self._day_bounds(day)
        start_s, end_s = start.isoformat(sep=" "), end.isoformat(sep=" ")
        with self._connect() as conn:
            focus = conn.execute(
                """SELECT COALESCE(SUM(duration_seconds), 0) AS seconds,
                          COUNT(*) AS sessions,
                          COALESCE(SUM(completed), 0) AS completed
                   FROM focus_sessions WHERE started_at >= ? AND started_at < ?""",
                (start_s, end_s),
            ).fetchone()
            visits = conn.execute(
                """SELECT opened_at, closed_at FROM room_visits
                   WHERE opened_at < ? AND (closed_at IS NULL OR closed_at > ?)""",
                (end_s, start_s),
            ).fetchall()
            room_seconds = 0
            now = datetime.now()
            for row in visits:
                opened = max(datetime.fromisoformat(row["opened_at"]), start)
                closed = datetime.fromisoformat(row["closed_at"]) if row["closed_at"] else now
                closed = min(closed, end)
                if closed > opened:
                    room_seconds += int((closed - opened).total_seconds())
            return {
                "focus_seconds": int(focus["seconds"]),
                "sessions": int(focus["sessions"]),
                "completed": int(focus["completed"]),
                "completed_sessions": int(focus["completed"]),
                "interrupted_sessions": max(0, int(focus["sessions"]) - int(focus["completed"])),
                "room_seconds": room_seconds,
                "visits": len(visits),
            }

    @staticmethod
    def _range_bounds(period: str = "today"):
        today = datetime.now().date()
        if period == "week":
            start_day = today - timedelta(days=today.weekday())
            end_day = start_day + timedelta(days=7)
        elif period == "month":
            start_day = today.replace(day=1)
            if start_day.month == 12:
                end_day = start_day.replace(year=start_day.year + 1, month=1)
            else:
                end_day = start_day.replace(month=start_day.month + 1)
        elif period == "year":
            start_day = today.replace(month=1, day=1)
            end_day = start_day.replace(year=start_day.year + 1)
        else:
            start_day = today
            end_day = today + timedelta(days=1)
        return datetime.combine(start_day, datetime.min.time()), datetime.combine(end_day, datetime.min.time())

    @staticmethod
    def _previous_range_bounds(period: str = "today"):
        """返回与当前统计范围等价的上一个完整自然周期。"""
        current_start, current_end = StudyDatabase._range_bounds(period)
        if period == "month":
            previous_end = current_start
            if current_start.month == 1:
                previous_start = current_start.replace(year=current_start.year - 1, month=12)
            else:
                previous_start = current_start.replace(month=current_start.month - 1)
        elif period == "year":
            previous_start = current_start.replace(year=current_start.year - 1)
            previous_end = current_start
        else:
            span = current_end - current_start
            previous_start = current_start - span
            previous_end = current_start
        return previous_start, previous_end

    def stats_range(self, period: str = "today") -> dict:
        """按今天/本周/本月/本年统计，保留旧 stats() 接口兼容。"""
        start, end = self._range_bounds(period)
        previous_start, previous_end = self._previous_range_bounds(period)
        start_s, end_s = start.isoformat(sep=" "), end.isoformat(sep=" ")
        previous_start_s = previous_start.isoformat(sep=" ")
        previous_end_s = previous_end.isoformat(sep=" ")
        with self._connect() as conn:
            focus = conn.execute(
                """SELECT COALESCE(SUM(duration_seconds), 0) AS seconds,
                          COUNT(*) AS sessions,
                          COALESCE(SUM(completed), 0) AS completed
                   FROM focus_sessions WHERE started_at >= ? AND started_at < ?""",
                (start_s, end_s),
            ).fetchone()
            visits = conn.execute(
                """SELECT opened_at, closed_at FROM room_visits
                   WHERE opened_at < ? AND (closed_at IS NULL OR closed_at > ?)""",
                (end_s, start_s),
            ).fetchall()
            room_seconds = 0
            now = datetime.now()
            for row in visits:
                opened = max(datetime.fromisoformat(row["opened_at"]), start)
                closed = datetime.fromisoformat(row["closed_at"]) if row["closed_at"] else now
                closed = min(closed, end)
                if closed > opened:
                    room_seconds += int((closed - opened).total_seconds())
            completed_tasks = conn.execute(
                """SELECT COUNT(*) AS total FROM study_tasks
                   WHERE completed = 1 AND completed_at >= ? AND completed_at < ?""",
                (start_s, end_s),
            ).fetchone()["total"]
            previous_focus = conn.execute(
                """SELECT COALESCE(SUM(duration_seconds), 0) AS seconds,
                          COALESCE(SUM(completed), 0) AS completed
                   FROM focus_sessions WHERE started_at >= ? AND started_at < ?""",
                (previous_start_s, previous_end_s),
            ).fetchone()
            previous_labels = {"today": "昨天", "week": "上周", "month": "上月", "year": "去年"}
            return {
                "focus_seconds": int(focus["seconds"]),
                "sessions": int(focus["sessions"]),
                "completed": int(focus["completed"]),
                "completed_sessions": int(focus["completed"]),
                "interrupted_sessions": max(0, int(focus["sessions"]) - int(focus["completed"])),
                "completed_tasks": int(completed_tasks),
                "room_seconds": room_seconds,
                "visits": len(visits),
                "period": period,
                "previous_focus_seconds": int(previous_focus["seconds"]),
                "previous_completed_sessions": int(previous_focus["completed"]),
                "previous_label": previous_labels.get(period, "上一周期"),
            }

    def week_trend(self):
        """返回当前自然周周一至周日，未到的日期也保留为 0。"""
        today = datetime.now().date()
        monday = today - timedelta(days=today.weekday())
        return [
            {"date": monday + timedelta(days=offset),
             "focus_seconds": self.stats(monday + timedelta(days=offset))["focus_seconds"]}
            for offset in range(7)
        ]

    def trend(self, days: int = 7):
        today = datetime.now().date()
        return [
            {"date": today - timedelta(days=offset),
             "focus_seconds": self.stats(today - timedelta(days=offset))["focus_seconds"]}
            for offset in reversed(range(max(1, days)))
        ]

    def streak(self) -> int:
        streak = 0
        day = datetime.now().date()
        while True:
            if self.stats(day)["completed"] <= 0:
                break
            streak += 1
            day -= timedelta(days=1)
        return streak
