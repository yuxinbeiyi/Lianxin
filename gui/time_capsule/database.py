"""Time Capsule 的本地 SQLite 数据层与旧日记无损迁移。"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from utils.paths import get_legacy_memory_dir, get_user_data_dir


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class TimeCapsuleDatabase:
    """Shared-memory store.  Every migration is additive and idempotent."""

    def __init__(self, path: Path | str | None = None, *, migrate_legacy: bool = True,
                 legacy_sources: list[Path | str] | None = None):
        self.path = Path(path or (get_user_data_dir() / "time_capsule.db"))
        self.legacy_sources = [Path(item) for item in legacy_sources] if legacy_sources is not None else None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        if migrate_legacy:
            self.migrate_legacy_diaries()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self.path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS capsule_days (
                    date TEXT PRIMARY KEY,
                    user_content TEXT NOT NULL DEFAULT '',
                    lianxin_content TEXT NOT NULL DEFAULT '',
                    weather TEXT NOT NULL DEFAULT '',
                    sealed INTEGER NOT NULL DEFAULT 0,
                    sealed_at TEXT NOT NULL DEFAULT '',
                    is_red_line INTEGER NOT NULL DEFAULT 0,
                    echo_text TEXT NOT NULL DEFAULT '',
                    source_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS capsule_revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    capsule_date TEXT NOT NULL,
                    author TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(capsule_date, author, content)
                );
                CREATE INDEX IF NOT EXISTS idx_capsule_revisions_date
                    ON capsule_revisions(capsule_date, id DESC);
                CREATE TABLE IF NOT EXISTS capsule_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    capsule_date TEXT NOT NULL,
                    author TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_capsule_traces_date
                    ON capsule_traces(capsule_date, id ASC);
                CREATE TABLE IF NOT EXISTS capsule_collections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    capsule_date TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    uri TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    favorite INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_capsule_collections_date
                    ON capsule_collections(capsule_date, id DESC);
                CREATE TABLE IF NOT EXISTS tree_hole_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    author TEXT NOT NULL,
                    content TEXT NOT NULL,
                    echo_of INTEGER,
                    opened INTEGER NOT NULL DEFAULT 1,
                    favorite INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tree_hole_created
                    ON tree_hole_notes(created_at DESC, id DESC);
                CREATE TABLE IF NOT EXISTS capsule_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    source_date TEXT NOT NULL DEFAULT '',
                    cover_kind TEXT NOT NULL DEFAULT 'story',
                    favorite INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE(title, source_date)
                );
                CREATE TABLE IF NOT EXISTS capsule_visits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id INTEGER,
                    capsule_date TEXT NOT NULL DEFAULT '',
                    visited_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS capsule_migrations (
                    migration_key TEXT PRIMARY KEY,
                    completed_at TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}'
                );
                """
            )

    @staticmethod
    def _day_dict(row) -> dict:
        if row is None:
            return {}
        data = dict(row)
        data["sealed"] = bool(data.get("sealed"))
        data["is_red_line"] = bool(data.get("is_red_line"))
        try:
            data["source"] = json.loads(data.pop("source_json") or "{}")
        except json.JSONDecodeError:
            data["source"] = {}
        return data

    def ensure_day(self, day: str) -> None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO capsule_days(date, created_at, updated_at)
                   VALUES (?, ?, ?)""",
                (day, now, now),
            )

    def get_day(self, day: str) -> dict:
        self.ensure_day(day)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM capsule_days WHERE date = ?", (day,)).fetchone()
            traces = conn.execute(
                "SELECT * FROM capsule_traces WHERE capsule_date = ? AND archived = 0 ORDER BY id",
                (day,),
            ).fetchall()
            collections = conn.execute(
                "SELECT * FROM capsule_collections WHERE capsule_date = ? ORDER BY id DESC",
                (day,),
            ).fetchall()
        result = self._day_dict(row)
        result["traces"] = [dict(item) for item in traces]
        result["collections"] = [self._collection_dict(item) for item in collections]
        return result

    def _save_content(self, day: str, author: str, content: str, **fields) -> dict:
        column = "user_content" if author == "user" else "lianxin_content"
        self.ensure_day(day)
        now = _now()
        with self._connect() as conn:
            previous = conn.execute(
                f"SELECT {column} AS content FROM capsule_days WHERE date = ?", (day,)
            ).fetchone()
            old_content = str(previous["content"] or "") if previous else ""
            if old_content and old_content != content:
                conn.execute(
                    """INSERT OR IGNORE INTO capsule_revisions
                       (capsule_date, author, content, created_at) VALUES (?, ?, ?, ?)""",
                    (day, author, old_content, now),
                )
            assignments = [f"{column} = ?", "updated_at = ?"]
            values = [str(content or ""), now]
            allowed = {"weather", "is_red_line", "echo_text", "source_json"}
            for key, value in fields.items():
                if key in allowed:
                    assignments.append(f"{key} = ?")
                    values.append(value)
            values.append(day)
            conn.execute(
                f"UPDATE capsule_days SET {', '.join(assignments)} WHERE date = ?", values
            )
        return self.get_day(day)

    def save_user_content(self, day: str, content: str) -> dict:
        return self._save_content(day, "user", content)

    def save_lianxin_content(self, day: str, content: str, *, weather: str = "",
                             is_red_line: bool = False, echo_text: str = "",
                             source: dict | None = None) -> dict:
        result = self._save_content(
            day, "lianxin", content, weather=str(weather or ""),
            is_red_line=int(bool(is_red_line)), echo_text=str(echo_text or ""),
            source_json=json.dumps(source or {}, ensure_ascii=False),
        )
        if echo_text and not any(
            trace["author"] == "lianxin" and trace["content"] == echo_text
            for trace in result.get("traces", [])
        ):
            self.add_trace(day, "lianxin", echo_text)
            result = self.get_day(day)
        return result

    def seal_day(self, day: str) -> dict:
        self.ensure_day(day)
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """UPDATE capsule_days SET sealed = 1, sealed_at = CASE
                       WHEN sealed_at = '' THEN ? ELSE sealed_at END, updated_at = ? WHERE date = ?""",
                (now, now, day),
            )
            row = conn.execute("SELECT * FROM capsule_days WHERE date = ?", (day,)).fetchone()
            content = str(row["user_content"] or row["lianxin_content"] or "").strip()
            if content:
                title = self._memory_title(day, content)
                conn.execute(
                    """INSERT OR IGNORE INTO capsule_memories
                       (title, description, source_date, cover_kind, favorite, created_at)
                       VALUES (?, ?, ?, 'story', 1, ?)""",
                    (title, content[:180], day, now),
                )
        return self.get_day(day)

    def link_memory_fact(self, day: str, fact_id: int) -> None:
        if not fact_id:
            return
        self.ensure_day(day)
        with self._connect() as conn:
            row = conn.execute("SELECT source_json FROM capsule_days WHERE date = ?", (day,)).fetchone()
            try:
                source = json.loads(row["source_json"] or "{}") if row else {}
            except json.JSONDecodeError:
                source = {}
            source["memory_fact_id"] = int(fact_id)
            source["memory_linked_at"] = _now()
            conn.execute(
                "UPDATE capsule_days SET source_json = ?, updated_at = ? WHERE date = ?",
                (json.dumps(source, ensure_ascii=False), _now(), day),
            )

    def record_visit(self, memory_id: int, capsule_date: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO capsule_visits(memory_id, capsule_date, visited_at) VALUES (?, ?, ?)",
                (int(memory_id), str(capsule_date or ""), _now()),
            )

    @staticmethod
    def _memory_title(day: str, content: str) -> str:
        first = next((line.strip("# *-\t") for line in content.splitlines() if line.strip()), "")
        return first[:24] or f"{day} 的故事"

    def add_trace(self, day: str, author: str, content: str) -> dict:
        text = str(content or "").strip()
        if not text:
            return self.get_day(day)
        self.ensure_day(day)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO capsule_traces(capsule_date, author, content, created_at) VALUES (?, ?, ?, ?)",
                (day, "lianxin" if author == "lianxin" else "user", text, _now()),
            )
        return self.get_day(day)

    @staticmethod
    def _collection_dict(row) -> dict:
        data = dict(row)
        data["favorite"] = bool(data.get("favorite"))
        try:
            data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
        except json.JSONDecodeError:
            data["metadata"] = {}
        return data

    def add_collection(self, day: str, kind: str, title: str = "", uri: str = "",
                       metadata: dict | None = None) -> dict:
        allowed = {"photo", "music", "study", "game", "chat", "file", "location"}
        kind = kind if kind in allowed else "file"
        default_titles = {
            "photo": "一张照片", "music": "一起听过的音乐", "study": "一段专注",
            "game": "一起玩过的游戏", "chat": "一句想记住的话",
            "file": "一份共同文件", "location": "一起到过的地方",
        }
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO capsule_collections
                   (capsule_date, kind, title, uri, metadata_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (day, kind, str(title or default_titles[kind]), str(uri or ""),
                 json.dumps(metadata or {}, ensure_ascii=False), _now()),
            )
        return self.get_day(day)

    def toggle_collection_favorite(self, collection_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE capsule_collections
                   SET favorite = CASE favorite WHEN 0 THEN 1 ELSE 0 END WHERE id = ?""",
                (int(collection_id),),
            )

    def add_tree_note(self, author: str, content: str, echo_of: int | None = None) -> int:
        text = str(content or "").strip()
        if not text:
            return 0
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO tree_hole_notes(author, content, echo_of, created_at)
                   VALUES (?, ?, ?, ?)""",
                ("lianxin" if author == "lianxin" else "user", text, echo_of, _now()),
            )
            return int(cur.lastrowid)

    def toggle_tree_favorite(self, note_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE tree_hole_notes
                   SET favorite = CASE favorite WHEN 0 THEN 1 ELSE 0 END WHERE id = ?""",
                (int(note_id),),
            )

    def timeline(self, limit: int = 120) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM capsule_days
                   WHERE user_content <> '' OR lianxin_content <> '' OR sealed = 1
                   ORDER BY date DESC LIMIT ?""",
                (max(1, min(500, int(limit))),),
            ).fetchall()
        return [self._day_dict(row) for row in rows]

    def tree_notes(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tree_hole_notes ORDER BY created_at DESC, id DESC LIMIT ?",
                (max(1, min(300, int(limit))),),
            ).fetchall()
        return [{**dict(row), "favorite": bool(row["favorite"]), "opened": bool(row["opened"])} for row in rows]

    def memories(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM capsule_memories ORDER BY favorite DESC, created_at DESC LIMIT ?",
                (max(1, min(300, int(limit))),),
            ).fetchall()
        return [{**dict(row), "favorite": bool(row["favorite"])} for row in rows]

    def recent_collections(self, days: int = 7, limit: int = 20) -> list[dict]:
        start = (date.today() - timedelta(days=max(1, int(days)) - 1)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM capsule_collections WHERE capsule_date >= ?
                   ORDER BY created_at DESC, id DESC LIMIT ?""",
                (start, max(1, min(100, int(limit)))),
            ).fetchall()
        return [self._collection_dict(row) for row in rows]

    def contribution(self, weeks: int = 53) -> dict:
        today = date.today()
        start = today - timedelta(days=today.weekday() + (max(1, weeks) - 1) * 7)
        with self._connect() as conn:
            capsule_rows = conn.execute(
                """SELECT date,
                          (CASE WHEN user_content <> '' THEN 1 ELSE 0 END +
                           CASE WHEN lianxin_content <> '' THEN 1 ELSE 0 END +
                           sealed) AS activity
                   FROM capsule_days WHERE date >= ? AND date <= ?""",
                (start.isoformat(), today.isoformat()),
            ).fetchall()
            trace_rows = conn.execute(
                """SELECT capsule_date AS date, COUNT(*) AS total FROM capsule_traces
                   WHERE capsule_date >= ? AND capsule_date <= ? GROUP BY capsule_date""",
                (start.isoformat(), today.isoformat()),
            ).fetchall()
            collection_rows = conn.execute(
                """SELECT capsule_date AS date, COUNT(*) AS total FROM capsule_collections
                   WHERE capsule_date >= ? AND capsule_date <= ? GROUP BY capsule_date""",
                (start.isoformat(), today.isoformat()),
            ).fetchall()
        activity = {row["date"]: int(row["activity"]) for row in capsule_rows}
        for rows in (trace_rows, collection_rows):
            for row in rows:
                activity[row["date"]] = activity.get(row["date"], 0) + int(row["total"])
        self._merge_study_activity(activity, start, today)
        days = []
        running = longest = 0
        for offset in range(weeks * 7):
            current = start + timedelta(days=offset)
            value = activity.get(current.isoformat(), 0)
            days.append({"date": current.isoformat(), "value": value, "future": current > today})
            if current <= today and value:
                running += 1
                longest = max(longest, running)
            elif current <= today:
                running = 0
        current_streak = 0
        cursor = today
        while activity.get(cursor.isoformat(), 0):
            current_streak += 1
            cursor -= timedelta(days=1)
        return {
            "days": days,
            "active_days": sum(1 for value in activity.values() if value),
            "longest_streak": longest,
            "current_streak": current_streak,
        }

    @staticmethod
    def _merge_study_activity(activity: dict, start: date, end: date) -> None:
        path = get_user_data_dir() / "study_room.db"
        if not path.exists():
            return
        try:
            conn = sqlite3.connect(str(path), timeout=3)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT substr(started_at, 1, 10) AS day, COUNT(*) AS total
                   FROM focus_sessions WHERE started_at >= ? AND started_at < ?
                   GROUP BY substr(started_at, 1, 10)""",
                (start.isoformat(), (end + timedelta(days=1)).isoformat()),
            ).fetchall()
            conn.close()
            for row in rows:
                activity[row["day"]] = activity.get(row["day"], 0) + int(row["total"])
        except (sqlite3.Error, OSError):
            return

    def search(self, query: str, limit: int = 80) -> list[dict]:
        term = f"%{str(query or '').strip()}%"
        if term == "%%":
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT date, user_content, lianxin_content, weather, sealed
                   FROM capsule_days d
                   WHERE d.user_content LIKE ? OR d.lianxin_content LIKE ?
                      OR d.weather LIKE ?
                      OR EXISTS (
                          SELECT 1 FROM capsule_traces t
                          WHERE t.capsule_date = d.date AND t.content LIKE ?
                      )
                      OR EXISTS (
                          SELECT 1 FROM capsule_collections c
                          WHERE c.capsule_date = d.date AND (c.title LIKE ? OR c.uri LIKE ?)
                      )
                      OR EXISTS (
                          SELECT 1 FROM capsule_memories m
                          WHERE m.source_date = d.date
                            AND (m.title LIKE ? OR m.description LIKE ?)
                      )
                   ORDER BY date DESC LIMIT ?""",
                (
                    term, term, term, term, term, term, term, term,
                    max(1, min(200, int(limit))),
                ),
            ).fetchall()
        return [dict(row) for row in rows]

    def initial_state(self, today: str | None = None) -> dict:
        today = today or date.today().isoformat()
        timeline = self.timeline()
        return {
            "today": self.get_day(today),
            "timeline": timeline,
            "contribution": self.contribution(),
            "recent_collections": self.recent_collections(),
            "tree_notes": self.tree_notes(),
            "memories": self.memories(),
            "companion": self.companion_state(timeline),
        }

    def companion_state(self, timeline: list[dict] | None = None) -> dict:
        timeline = timeline if timeline is not None else self.timeline(10)
        latest = timeline[0] if timeline else {}
        content = str(latest.get("lianxin_content") or latest.get("user_content") or "").strip()
        message = "今天的书页还很安静。我在这里，等你一起留下新的故事。"
        if content:
            message = f"我刚刚又想起了 {latest.get('date', '那一天')}。有些时间被写下来以后，就不会轻易走丢了。"
        return {
            "message": message,
            "recent": [
                {"date": item.get("date", ""), "title": self._memory_title(item.get("date", ""),
                 str(item.get("user_content") or item.get("lianxin_content") or ""))}
                for item in timeline[:3]
            ],
        }

    def migrate_legacy_diaries(self) -> dict:
        sources = self.legacy_sources or [
            get_legacy_memory_dir() / "diary.db", get_user_data_dir() / "diary.db"
        ]
        imported = 0
        for source in sources:
            if not source.exists() or source.resolve() == self.path.resolve():
                continue
            key = f"legacy_diary:{source.resolve()}"
            with self._connect() as conn:
                if conn.execute(
                    "SELECT 1 FROM capsule_migrations WHERE migration_key = ?", (key,)
                ).fetchone():
                    continue
            try:
                legacy = sqlite3.connect(str(source), timeout=5)
                legacy.row_factory = sqlite3.Row
                rows = legacy.execute("SELECT * FROM diary ORDER BY date").fetchall()
                legacy.close()
            except sqlite3.Error:
                continue
            for row in rows:
                payload = dict(row)
                self.save_lianxin_content(
                    str(payload.get("date", "")), str(payload.get("content", "")),
                    weather=str(payload.get("weather", "") or ""),
                    is_red_line=bool(payload.get("is_red_line", 0)),
                    echo_text=str(payload.get("echo_text", "") or ""),
                    source={"legacy_diary": str(source)},
                )
                if int(payload.get("status", 1) or 0):
                    self.seal_day(str(payload.get("date", "")))
                imported += 1
            with self._connect() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO capsule_migrations
                       (migration_key, completed_at, details_json) VALUES (?, ?, ?)""",
                    (key, _now(), json.dumps({"rows": len(rows)}, ensure_ascii=False)),
                )
        return {"imported": imported}
