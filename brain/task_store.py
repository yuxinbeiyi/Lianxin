"""Unified SQLite persistence for Todo, AutoTask and their Workflow relations."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from utils.paths import get_user_data_dir


logger = logging.getLogger("TaskStore")


class TaskStore:
    """Transactional task repository with non-destructive legacy JSON migration."""

    def __init__(self, db_path: Path | str | None = None, *, migrate_legacy: bool = True):
        self.db_path = Path(db_path or (get_user_data_dir() / "tasks.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._ensure_schema()
        if migrate_legacy:
            try:
                self.migrate_legacy_json()
            except Exception as exc:
                logger.warning("旧任务 JSON 迁移失败，将在下次启动重试: %s", exc)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS todos (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    due_time TEXT,
                    priority TEXT NOT NULL DEFAULT 'medium',
                    completed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_todos_status_due
                    ON todos(completed,due_time,priority);

                CREATE TABLE IF NOT EXISTS auto_tasks (
                    task_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    schedule_type TEXT NOT NULL DEFAULT 'once',
                    next_run TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_auto_tasks_schedule
                    ON auto_tasks(enabled,status,next_run,schedule_type);

                CREATE TABLE IF NOT EXISTS auto_task_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    step INTEGER NOT NULL DEFAULT 0,
                    success INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    workflow_run_id INTEGER,
                    fingerprint TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_auto_task_logs_task
                    ON auto_task_logs(task_id,id DESC);

                CREATE TABLE IF NOT EXISTS task_relations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE(source_type,source_id,target_type,target_id,relation)
                );

                CREATE TABLE IF NOT EXISTS task_workflow_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_type TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    workflow_run_id INTEGER NOT NULL,
                    relation TEXT NOT NULL DEFAULT 'execution',
                    created_at TEXT NOT NULL,
                    UNIQUE(task_type,task_id,workflow_run_id,relation)
                );
                CREATE INDEX IF NOT EXISTS idx_task_workflow_entity
                    ON task_workflow_runs(task_type,task_id,id DESC);

                CREATE TABLE IF NOT EXISTS task_store_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )
            conn.commit()

    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())

    def _meta(self, key: str) -> str:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT value FROM task_store_meta WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else ""

    def _set_meta(self, key: str, value: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """INSERT INTO task_store_meta(key,value,updated_at) VALUES (?,?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
                (key, value, time.time()),
            )
            conn.commit()

    def migrate_legacy_json(self, data_dir: Path | str | None = None) -> dict[str, int]:
        """Import legacy JSON once. Source files remain untouched as recovery copies."""
        if self._meta("legacy_json_migration_v1"):
            return {"todos": 0, "auto_tasks": 0, "logs": 0}
        root = Path(data_dir or get_user_data_dir())
        imported = {"todos": 0, "auto_tasks": 0, "logs": 0}
        try:
            todo_path = root / "todo.json"
            task_path = root / "auto_tasks.json"
            log_path = root / "auto_task_logs.json"
            todos = self._load_json_list(todo_path, "todos")
            tasks = self._load_json_list(task_path, "tasks")
            logs = self._load_json_list(log_path, "logs")
            with self._lock, closing(self._connect()) as conn:
                conn.execute("BEGIN IMMEDIATE")
                for todo in todos:
                    self._upsert_todo_conn(conn, todo)
                    imported["todos"] += 1
                for task in tasks:
                    self._upsert_auto_task_conn(conn, task)
                    imported["auto_tasks"] += 1
                for log in logs:
                    if self._insert_log_conn(conn, log):
                        imported["logs"] += 1
                conn.execute(
                    "INSERT OR REPLACE INTO task_store_meta(key,value,updated_at) VALUES (?,?,?)",
                    ("legacy_json_migration_v1", json.dumps(imported, ensure_ascii=False), time.time()),
                )
                conn.commit()
        except Exception:
            # A failed migration is retried next startup; no marker is written.
            raise
        return imported

    @staticmethod
    def _load_json_list(path: Path, key: str) -> list[dict]:
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            values = payload.get(key, []) if isinstance(payload, dict) else []
            return [item for item in values if isinstance(item, dict)]
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"无法读取旧任务文件 {path.name}: {exc}") from exc

    def _upsert_todo_conn(self, conn: sqlite3.Connection, todo: dict) -> None:
        now = self._now()
        conn.execute(
            """INSERT INTO todos(id,title,description,due_time,priority,completed,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                 description=excluded.description,due_time=excluded.due_time,
                 priority=excluded.priority,completed=excluded.completed,
                 created_at=excluded.created_at,updated_at=excluded.updated_at""",
            (
                str(todo.get("id", "")), str(todo.get("title", "")),
                str(todo.get("description", "")), todo.get("due_time"),
                str(todo.get("priority", "medium")), int(bool(todo.get("completed", False))),
                str(todo.get("created_at") or now), now,
            ),
        )

    def replace_todos(self, todos: Iterable[dict]) -> None:
        items = list(todos)
        ids = {str(item.get("id", "")) for item in items if item.get("id")}
        with self._lock, closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            for item in items:
                self._upsert_todo_conn(conn, item)
            if ids:
                placeholders = ",".join("?" for _ in ids)
                conn.execute(f"DELETE FROM todos WHERE id NOT IN ({placeholders})", tuple(ids))
            else:
                conn.execute("DELETE FROM todos")
            conn.commit()

    def list_todos(self) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM todos ORDER BY created_at,id").fetchall()
        return [dict(row) | {"completed": bool(row["completed"])} for row in rows]

    def _upsert_auto_task_conn(self, conn: sqlite3.Connection, task: dict) -> None:
        now = self._now()
        payload = dict(task)
        conn.execute(
            """INSERT INTO auto_tasks(task_id,name,description,status,enabled,schedule_type,
                   next_run,payload_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(task_id) DO UPDATE SET name=excluded.name,
                 description=excluded.description,status=excluded.status,enabled=excluded.enabled,
                 schedule_type=excluded.schedule_type,next_run=excluded.next_run,
                 payload_json=excluded.payload_json,created_at=excluded.created_at,
                 updated_at=excluded.updated_at""",
            (
                str(task.get("task_id", "")), str(task.get("name", "")),
                str(task.get("description", "")), str(task.get("status", "active")),
                int(bool(task.get("enabled", True))), str(task.get("schedule_type", "once")),
                str(task.get("next_run", "") or ""),
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str),
                str(task.get("created_at") or now), now,
            ),
        )

    def replace_auto_tasks(self, tasks: Iterable[dict]) -> None:
        items = list(tasks)
        ids = {str(item.get("task_id", "")) for item in items if item.get("task_id")}
        with self._lock, closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            for item in items:
                self._upsert_auto_task_conn(conn, item)
            if ids:
                placeholders = ",".join("?" for _ in ids)
                conn.execute(f"DELETE FROM auto_tasks WHERE task_id NOT IN ({placeholders})", tuple(ids))
            else:
                conn.execute("DELETE FROM auto_tasks")
            conn.commit()

    def list_auto_tasks(self) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT payload_json FROM auto_tasks ORDER BY created_at,task_id").fetchall()
        result = []
        for row in rows:
            try:
                result.append(json.loads(row["payload_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return result

    @staticmethod
    def _log_fingerprint(log: dict) -> str:
        import hashlib
        raw = "|".join(str(log.get(k, "")) for k in (
            "task_id", "timestamp", "step", "success", "message", "duration_ms", "workflow_run_id"
        ))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _insert_log_conn(self, conn: sqlite3.Connection, log: dict) -> bool:
        cur = conn.execute(
            """INSERT OR IGNORE INTO auto_task_logs
               (task_id,timestamp,step,success,message,duration_ms,workflow_run_id,fingerprint)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                str(log.get("task_id", "")), str(log.get("timestamp") or self._now()),
                int(log.get("step", 0) or 0), int(bool(log.get("success", False))),
                str(log.get("message", "")), int(log.get("duration_ms", 0) or 0),
                log.get("workflow_run_id"), self._log_fingerprint(log),
            ),
        )
        return bool(cur.rowcount)

    def replace_auto_task_logs(self, logs: Iterable[dict]) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM auto_task_logs")
            for log in list(logs)[-500:]:
                self._insert_log_conn(conn, log)
            conn.commit()

    def list_auto_task_logs(self, task_id: str | None = None, limit: int = 500) -> list[dict]:
        with closing(self._connect()) as conn:
            if task_id:
                rows = conn.execute(
                    "SELECT * FROM auto_task_logs WHERE task_id=? ORDER BY id DESC LIMIT ?",
                    (str(task_id), max(1, int(limit))),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM auto_task_logs ORDER BY id DESC LIMIT ?", (max(1, int(limit)),)
                ).fetchall()
        return [
            dict(row) | {"success": bool(row["success"])}
            for row in reversed(rows)
        ]

    def bind_workflow(self, task_type: str, task_id: str, workflow_run_id: int,
                      relation: str = "execution") -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """INSERT OR IGNORE INTO task_workflow_runs
                   (task_type,task_id,workflow_run_id,relation,created_at) VALUES (?,?,?,?,?)""",
                (str(task_type), str(task_id), int(workflow_run_id), str(relation), self._now()),
            )
            conn.commit()

    def list_workflows(self, task_type: str, task_id: str) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """SELECT * FROM task_workflow_runs WHERE task_type=? AND task_id=?
                   ORDER BY id DESC""",
                (str(task_type), str(task_id)),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_tasks_for_workflow(self, workflow_run_id: int) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """SELECT * FROM task_workflow_runs WHERE workflow_run_id=? ORDER BY id""",
                (int(workflow_run_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def link_tasks(self, source_type: str, source_id: str, target_type: str, target_id: str,
                   relation: str, metadata: dict | None = None) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """INSERT OR IGNORE INTO task_relations
                   (source_type,source_id,target_type,target_id,relation,metadata_json,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (str(source_type), str(source_id), str(target_type), str(target_id), str(relation),
                 json.dumps(metadata or {}, ensure_ascii=False, default=str), self._now()),
            )
            conn.commit()

    def list_relations(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """SELECT * FROM task_relations
                   WHERE (source_type=? AND source_id=?) OR (target_type=? AND target_id=?)
                   ORDER BY id""",
                (str(entity_type), str(entity_id), str(entity_type), str(entity_id)),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.pop("metadata_json", "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                item["metadata"] = {}
            result.append(item)
        return result


_store: TaskStore | None = None
_store_lock = threading.Lock()


def get_task_store() -> TaskStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = TaskStore()
    return _store
