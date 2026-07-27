"""莲心自习室的轻量 SQLite 数据层。"""

import json
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
                CREATE TABLE IF NOT EXISTS study_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    task_id INTEGER,
                    task_name TEXT NOT NULL DEFAULT '',
                    occurred_at TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_study_events_occurred_at
                    ON study_events(occurred_at DESC);
                CREATE TABLE IF NOT EXISTS companion_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_name TEXT NOT NULL DEFAULT '', duration_seconds INTEGER NOT NULL DEFAULT 0,
                    content TEXT NOT NULL, created_at TEXT NOT NULL,
                    liked INTEGER NOT NULL DEFAULT 0, favorited INTEGER NOT NULL DEFAULT 0,
                    hidden INTEGER NOT NULL DEFAULT 0, lianxin_liked INTEGER NOT NULL DEFAULT 0
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

    @staticmethod
    def _record_event(conn, event_type: str, task_id=None, task_name: str = "", **details):
        """写入可回溯的自习室事件；不进入聊天或长期记忆系统。"""
        conn.execute(
            """INSERT INTO study_events(event_type, task_id, task_name, occurred_at, details_json)
               VALUES (?, ?, ?, ?, ?)""",
            (event_type, task_id, task_name or "", StudyDatabase._now(),
             json.dumps(details, ensure_ascii=False, separators=(",", ":"))),
        )

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
            task_id = int(cur.lastrowid)
            self._record_event(conn, "task_created", task_id, title.strip(),
                               estimate_minutes=max(1, int(estimate_minutes)),
                               break_minutes=max(0, int(break_minutes)),
                               repeat_enabled=bool(repeat_enabled))
            return task_id

    def tasks(self, include_completed: bool = True):
        sql = "SELECT * FROM study_tasks"
        if not include_completed:
            sql += " WHERE completed = 0"
        sql += " ORDER BY completed ASC, created_at DESC"
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql)]

    def toggle_task(self, task_id: int):
        with self._connect() as conn:
            task = conn.execute("SELECT title, completed FROM study_tasks WHERE id = ?", (int(task_id),)).fetchone()
            if task is None:
                return False
            completed = not bool(task["completed"])
            conn.execute(
                """UPDATE study_tasks SET completed = ?, completed_at = ?
                   WHERE id = ?""",
                (int(completed), self._now() if completed else None, int(task_id)),
            )
            self._record_event(conn, "task_completed" if completed else "task_reopened",
                               int(task_id), task["title"])
            return True

    def complete_task(self, task_id: int) -> bool:
        """幂等标记任务完成，供一次专注结束后的明确确认使用。"""
        with self._connect() as conn:
            task = conn.execute("SELECT title, completed FROM study_tasks WHERE id = ?", (int(task_id),)).fetchone()
            if task is None:
                return False
            if not task["completed"]:
                conn.execute("UPDATE study_tasks SET completed = 1, completed_at = ? WHERE id = ?",
                             (self._now(), int(task_id)))
                self._record_event(conn, "task_completed", int(task_id), task["title"], source="focus_completion")
            return True

    def delete_task(self, task_id: int):
        with self._connect() as conn:
            task = conn.execute("SELECT title FROM study_tasks WHERE id = ?", (int(task_id),)).fetchone()
            conn.execute("DELETE FROM study_tasks WHERE id = ?", (int(task_id),))
            if task is not None:
                self._record_event(conn, "task_deleted", int(task_id), task["title"])

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
            if cur.rowcount:
                self._record_event(conn, "task_updated", int(task_id), title.strip(),
                                   estimate_minutes=max(1, int(estimate_minutes)),
                                   break_minutes=max(0, int(break_minutes)),
                                   repeat_enabled=bool(repeat_enabled))
            return cur.rowcount > 0

    def open_visit(self) -> int:
        with self._connect() as conn:
            now = self._now()
            # 上次异常退出时不会触发 close_visit；在新窗口打开时收束遗留访问，
            # 避免同一时段被多个未关闭记录重复累计。
            conn.execute("UPDATE room_visits SET closed_at = ? WHERE closed_at IS NULL", (now,))
            cur = conn.execute("INSERT INTO room_visits(opened_at) VALUES (?)", (now,))
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
            safe_name = task_name or "未命名专注"
            seconds = max(0, int(duration_seconds))
            conn.execute(
                """INSERT INTO focus_sessions
                   (task_id, task_name, started_at, ended_at, duration_seconds, completed)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (task_id, safe_name, started_at, self._now(), seconds, int(bool(completed))),
            )
            self._record_event(conn, "focus_completed" if completed else "focus_interrupted",
                               task_id, safe_name, duration_seconds=seconds, completed=bool(completed))
        try:
            from brain.interaction_events import record_interaction
            record_interaction(
                feature="study_room",
                event_type="focus_completed" if completed else "focus_interrupted",
                local_date=str(started_at)[:10],
                occurred_at=str(started_at),
                source_id=f"focus:{task_id or 0}:{started_at}:{seconds}",
                content=f"{safe_name}，专注 {seconds // 60} 分钟",
                summary=f"{safe_name}，专注 {seconds // 60} 分钟",
                metadata={"task_id": task_id, "duration_seconds": seconds, "completed": bool(completed)},
            )
        except Exception as exc:
            print(f"[互动事件] 自习室事件记录失败: {exc}")

    def recent_focus_sessions(self, limit: int = 8) -> list[dict]:
        """读取最近专注，完成与中断均保留，便于用户回看自己的节奏。"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT task_id, task_name, started_at, ended_at, duration_seconds, completed
                   FROM focus_sessions ORDER BY ended_at DESC, id DESC LIMIT ?""",
                (max(1, min(30, int(limit))),),
            ).fetchall()
        return [{**dict(row), "completed": bool(row["completed"])} for row in rows]

    def create_companion_note(self, task_name: str, duration_seconds: int) -> None:
        """完成专注后的本地陪伴纸条，不调用模型。"""
        minutes = max(1, int(duration_seconds) // 60)
        templates = (
            "{task}的这 {minutes} 分钟已经被你好好完成了，慢慢积累也很了不起。",
            "我看见你为{task}留出了专注的时间，辛苦啦，去喝口水吧。",
            "{minutes} 分钟的认真会悄悄变成之后的底气。{task}，继续按自己的节奏来。",
            "今天的{task}又向前走了一点。完成一段，就值得为自己点个赞。",
        )
        task = task_name or "这一段专注"
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM companion_notes").fetchone()[0]
            content = templates[(count + minutes) % len(templates)].format(task=task, minutes=minutes)
            conn.execute("""INSERT INTO companion_notes(task_name, duration_seconds, content, created_at)
                            VALUES (?, ?, ?, ?)""", (task, int(duration_seconds), content, self._now()))

    def companion_notes(self, limit: int = 12) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("""SELECT * FROM companion_notes WHERE hidden = 0
                                 ORDER BY created_at DESC, id DESC LIMIT ?""",
                                (max(1, min(30, int(limit))),)).fetchall()
        return [{**dict(row), "liked": bool(row["liked"]), "favorited": bool(row["favorited"]),
                 "lianxin_liked": bool(row["lianxin_liked"])} for row in rows]

    def update_note(self, note_id: int, action: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM companion_notes WHERE id = ?", (int(note_id),)).fetchone()
            if row is None:
                return False
            if action == "like":
                liked = not bool(row["liked"])
                # 固定低概率，避免刷新页面时反复随机改变莲心的回应。
                lianxin_liked = int(liked and int(note_id) % 5 == 0)
                conn.execute("UPDATE companion_notes SET liked = ?, lianxin_liked = ? WHERE id = ?",
                             (int(liked), lianxin_liked, int(note_id)))
            elif action == "favorite":
                conn.execute("UPDATE companion_notes SET favorited = CASE favorited WHEN 0 THEN 1 ELSE 0 END WHERE id = ?",
                             (int(note_id),))
            elif action == "hide":
                conn.execute("UPDATE companion_notes SET hidden = 1 WHERE id = ?", (int(note_id),))
            else:
                return False
            return True

    def week_events(self, limit: int = 20) -> list[dict]:
        today = datetime.now().date()
        start = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time()).isoformat(sep=" ")
        with self._connect() as conn:
            rows = conn.execute("""SELECT * FROM study_events WHERE occurred_at >= ?
                                 ORDER BY occurred_at DESC, id DESC LIMIT ?""", (start, max(1, min(40, int(limit))))).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["details"] = json.loads(item.pop("details_json") or "{}")
            except json.JSONDecodeError:
                item["details"] = {}
            result.append(item)
        return result

    def focus_sessions_between(self, start: datetime, end: datetime) -> list[dict]:
        """返回指定左闭右开区间内的专注记录，供报告层做可解释聚合。"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT task_id, task_name, started_at, ended_at, duration_seconds, completed
                   FROM focus_sessions
                   WHERE started_at >= ? AND started_at < ?
                   ORDER BY started_at ASC, id ASC""",
                (start.isoformat(sep=" "), end.isoformat(sep=" ")),
            ).fetchall()
        return [{**dict(row), "completed": bool(row["completed"])} for row in rows]

    def events_between(self, start: datetime, end: datetime) -> list[dict]:
        """返回报告周期内的自习室事件；删除的任务也能保留其历史足迹。"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM study_events
                   WHERE occurred_at >= ? AND occurred_at < ?
                   ORDER BY occurred_at ASC, id ASC""",
                (start.isoformat(sep=" "), end.isoformat(sep=" ")),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["details"] = json.loads(item.pop("details_json") or "{}")
            except json.JSONDecodeError:
                item["details"] = {}
            result.append(item)
        return result

    def room_seconds_between(self, start: datetime, end: datetime) -> int:
        """返回去重后的自习室打开时长。"""
        with self._connect() as conn:
            return self._room_seconds(conn, start, end)

    @staticmethod
    def _room_seconds(conn, start: datetime, end: datetime) -> int:
        """合并访问区间后计算时长，旧异常记录不会造成重叠重复计时。"""
        rows = conn.execute(
            """SELECT opened_at, closed_at FROM room_visits
               WHERE opened_at < ? AND (closed_at IS NULL OR closed_at > ?)""",
            (end.isoformat(sep=" "), start.isoformat(sep=" ")),
        ).fetchall()
        now = datetime.now()
        intervals = []
        for row in rows:
            opened = max(datetime.fromisoformat(row["opened_at"]), start)
            closed = datetime.fromisoformat(row["closed_at"]) if row["closed_at"] else now
            closed = min(closed, end)
            if closed > opened:
                intervals.append((opened, closed))
        if not intervals:
            return 0
        intervals.sort(key=lambda interval: interval[0])
        merged = [list(intervals[0])]
        for opened, closed in intervals[1:]:
            previous = merged[-1]
            if opened <= previous[1]:
                previous[1] = max(previous[1], closed)
            else:
                merged.append([opened, closed])
        return sum(int((closed - opened).total_seconds()) for opened, closed in merged)

    def reset_statistics(self):
        """清除专注和房间访问记录；任务清单本身不受影响。"""
        with self._connect() as conn:
            conn.execute("DELETE FROM focus_sessions")
            conn.execute("DELETE FROM room_visits")
            conn.execute("DELETE FROM study_events WHERE event_type LIKE 'focus_%'")

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
            room_seconds = self._room_seconds(conn, start, end)
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
            room_seconds = self._room_seconds(conn, start, end)
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

    def time_rewind(self, weeks: int = 53, active_day_seconds: int = 300) -> dict:
        """返回按周对齐的年度专注热力图及连续专注摘要。"""
        weeks = max(1, int(weeks))
        active_day_seconds = max(1, int(active_day_seconds))
        today = datetime.now().date()
        start_day = today - timedelta(days=today.weekday() + (weeks - 1) * 7)
        end_day = start_day + timedelta(days=weeks * 7)
        summary_start = today - timedelta(days=364)
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT substr(started_at, 1, 10) AS day,
                          COALESCE(SUM(duration_seconds), 0) AS focus_seconds,
                          COUNT(*) AS sessions,
                          COALESCE(SUM(completed), 0) AS completed_sessions
                   FROM focus_sessions
                   WHERE started_at >= ? AND started_at < ?
                   GROUP BY substr(started_at, 1, 10)""",
                (datetime.combine(start_day, datetime.min.time()).isoformat(sep=" "),
                 datetime.combine(end_day, datetime.min.time()).isoformat(sep=" ")),
            ).fetchall()
        by_day = {
            row["day"]: {
                "focus_seconds": int(row["focus_seconds"]),
                "sessions": int(row["sessions"]),
                "completed_sessions": int(row["completed_sessions"]),
            }
            for row in rows
        }
        days = []
        for offset in range(weeks * 7):
            day = start_day + timedelta(days=offset)
            value = by_day.get(day.isoformat(), {})
            days.append({
                "date": day.isoformat(),
                "focus_seconds": int(value.get("focus_seconds", 0)),
                "sessions": int(value.get("sessions", 0)),
                "completed_sessions": int(value.get("completed_sessions", 0)),
                "future": day > today,
            })

        summary_days = [item for item in days if summary_start <= datetime.fromisoformat(item["date"]).date() <= today]
        completed_sessions = sum(item["completed_sessions"] for item in summary_days)
        longest_streak = current_streak = running_streak = 0
        for item in summary_days:
            if item["focus_seconds"] >= active_day_seconds:
                running_streak += 1
                longest_streak = max(longest_streak, running_streak)
            else:
                running_streak = 0
        for item in reversed(summary_days):
            if item["focus_seconds"] < active_day_seconds:
                break
            current_streak += 1
        return {
            "weeks": weeks,
            "active_day_seconds": active_day_seconds,
            "days": days,
            "completed_sessions": completed_sessions,
            "longest_streak": longest_streak,
            "current_streak": current_streak,
        }

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
