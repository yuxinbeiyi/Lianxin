"""Persistent workflow runs, steps, artifacts and reusable tool-result cache."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from utils.paths import get_user_data_dir


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class WorkflowStore:
    """SQLite-backed audit log shared by conversations and background tasks."""

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path or (get_user_data_dir() / "workflows.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()
        self.recover_interrupted_runs()
        self.cleanup_cache()

    def _connect(self):
        conn = sqlite3.connect(str(self.db_path), timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _ensure_schema(self):
        conn = self._connect()
        try:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS workflow_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_key TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL DEFAULT 'conversation',
                title TEXT NOT NULL DEFAULT '',
                session_id INTEGER,
                channel TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                attempt INTEGER NOT NULL DEFAULT 1,
                retry_of_run_id INTEGER,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                result_summary TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL DEFAULT '',
                finished_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workflow_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                step_key TEXT NOT NULL,
                name TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'tool',
                status TEXT NOT NULL DEFAULT 'running',
                sequence INTEGER NOT NULL DEFAULT 0,
                cached INTEGER NOT NULL DEFAULT 0,
                input_json TEXT NOT NULL DEFAULT '{}',
                output_preview TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                duration_ms REAL NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL DEFAULT '',
                UNIQUE(run_id, step_key)
            );
            CREATE TABLE IF NOT EXISTS workflow_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                step_id INTEGER,
                artifact_type TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                uri TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                fingerprint TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS workflow_cache (
                cache_key TEXT PRIMARY KEY,
                namespace TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                expires_at REAL NOT NULL DEFAULT 0,
                hit_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_workflow_runs_status ON workflow_runs(status,id DESC);
            CREATE INDEX IF NOT EXISTS idx_workflow_runs_session ON workflow_runs(session_id,id DESC);
            CREATE INDEX IF NOT EXISTS idx_workflow_steps_run ON workflow_steps(run_id,sequence,id);
            CREATE INDEX IF NOT EXISTS idx_workflow_artifacts_run ON workflow_artifacts(run_id,id);
            CREATE INDEX IF NOT EXISTS idx_workflow_cache_expiry ON workflow_cache(expires_at);
            """)
        finally:
            conn.close()

    def recover_interrupted_runs(self) -> int:
        timestamp = _now()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                """UPDATE workflow_runs SET status='interrupted',
                   error=CASE WHEN error='' THEN 'application stopped before completion' ELSE error END,
                   finished_at=?,updated_at=? WHERE status='running'""",
                (timestamp, timestamp),
            )
            conn.execute(
                """UPDATE workflow_steps SET status='interrupted',
                   error=CASE WHEN error='' THEN 'application stopped before completion' ELSE error END,
                   finished_at=? WHERE status='running'""",
                (timestamp,),
            )
            conn.commit()
            return int(cur.rowcount)
        finally:
            conn.close()

    def begin_run(self, *, kind: str, title: str, session_id: int | None = None,
                  channel: str = "", metadata: dict | None = None,
                  retry_of_run_id: int | None = None) -> dict:
        timestamp = _now()
        run_key = uuid.uuid4().hex
        attempt = 1
        if retry_of_run_id:
            previous = self.get_run(retry_of_run_id)
            attempt = int(previous.get("attempt", 0) or 0) + 1 if previous else 1
        conn = self._connect()
        try:
            cur = conn.execute(
                """INSERT INTO workflow_runs
                   (run_key,kind,title,session_id,channel,status,attempt,retry_of_run_id,
                    metadata_json,started_at,created_at,updated_at)
                   VALUES (?,?,?,?,?,'running',?,?,?,?,?,?)""",
                (run_key, str(kind), str(title)[:240], session_id, str(channel or ""),
                 attempt, retry_of_run_id, json.dumps(metadata or {}, ensure_ascii=False, default=str),
                 timestamp, timestamp, timestamp),
            )
            return self.get_run(int(cur.lastrowid))
        finally:
            conn.close()

    def finish_run(self, run_id: int, *, status: str, result_summary: str = "",
                   error: str = "", input_tokens: int = 0, output_tokens: int = 0) -> dict:
        timestamp = _now()
        conn = self._connect()
        try:
            conn.execute(
                """UPDATE workflow_runs SET status=?,result_summary=?,error=?,input_tokens=?,
                   output_tokens=?,finished_at=?,updated_at=? WHERE id=?""",
                (status, str(result_summary or "")[:2000], str(error or "")[:4000],
                 max(0, int(input_tokens)), max(0, int(output_tokens)), timestamp, timestamp, int(run_id)),
            )
        finally:
            conn.close()
        return self.get_run(run_id)

    def get_run(self, run_id: int) -> dict:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM workflow_runs WHERE id=?", (int(run_id),)).fetchone()
        finally:
            conn.close()
        return self._decode(row)

    def list_runs(self, limit: int = 200, *, status: str = "") -> list[dict]:
        conn = self._connect()
        try:
            if status:
                rows = conn.execute(
                    "SELECT * FROM workflow_runs WHERE status=? ORDER BY id DESC LIMIT ?",
                    (status, max(1, int(limit))),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM workflow_runs ORDER BY id DESC LIMIT ?", (max(1, int(limit)),)
                ).fetchall()
        finally:
            conn.close()
        return [self._decode(row) for row in rows]

    def start_step(self, run_id: int, *, step_key: str, name: str, kind: str = "tool",
                   input_data: dict | None = None) -> int:
        conn = self._connect()
        timestamp = _now()
        try:
            sequence = conn.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM workflow_steps WHERE run_id=?",
                (int(run_id),),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO workflow_steps
                   (run_id,step_key,name,kind,status,sequence,input_json,started_at)
                   VALUES (?,?,?,?, 'running',?,?,?)
                   ON CONFLICT(run_id,step_key) DO UPDATE SET
                     name=excluded.name,kind=excluded.kind,status='running',input_json=excluded.input_json,
                     error='',output_preview='',duration_ms=0,started_at=excluded.started_at,finished_at=''""",
                (int(run_id), str(step_key), str(name)[:160], str(kind), int(sequence),
                 json.dumps(input_data or {}, ensure_ascii=False, default=str)[:8000], timestamp),
            )
            row = conn.execute(
                "SELECT id FROM workflow_steps WHERE run_id=? AND step_key=?",
                (int(run_id), str(step_key)),
            ).fetchone()
            return int(row["id"])
        finally:
            conn.close()

    def finish_step(self, step_id: int, *, status: str, output_preview: str = "",
                    error: str = "", duration_ms: float = 0, cached: bool = False) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """UPDATE workflow_steps SET status=?,output_preview=?,error=?,duration_ms=?,
                   cached=?,finished_at=? WHERE id=?""",
                (status, str(output_preview or "")[:4000], str(error or "")[:4000],
                 max(0.0, float(duration_ms)), int(bool(cached)), _now(), int(step_id)),
            )
        finally:
            conn.close()

    def list_steps(self, run_id: int) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM workflow_steps WHERE run_id=? ORDER BY sequence,id", (int(run_id),)
            ).fetchall()
        finally:
            conn.close()
        return [self._decode(row) for row in rows]

    def add_artifact(self, run_id: int, *, artifact_type: str, name: str = "", uri: str = "",
                     content_hash: str = "", metadata: dict | None = None,
                     step_id: int | None = None) -> int:
        fingerprint = hashlib.sha256(
            f"{int(run_id)}:{artifact_type}:{uri}:{content_hash}:{name}".encode("utf-8")
        ).hexdigest()
        conn = self._connect()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO workflow_artifacts
                   (run_id,step_id,artifact_type,name,uri,content_hash,metadata_json,created_at,fingerprint)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (int(run_id), step_id, str(artifact_type), str(name)[:240], str(uri)[:2000],
                 str(content_hash), json.dumps(metadata or {}, ensure_ascii=False, default=str), _now(), fingerprint),
            )
            row = conn.execute("SELECT id FROM workflow_artifacts WHERE fingerprint=?", (fingerprint,)).fetchone()
            return int(row["id"])
        finally:
            conn.close()

    def list_artifacts(self, run_id: int) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM workflow_artifacts WHERE run_id=? ORDER BY id", (int(run_id),)
            ).fetchall()
        finally:
            conn.close()
        return [self._decode(row) for row in rows]

    def request_cancel(self, run_id: int) -> bool:
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE workflow_runs SET cancel_requested=1,updated_at=? WHERE id=? AND status='running'",
                (_now(), int(run_id)),
            )
            return bool(cur.rowcount)
        finally:
            conn.close()

    def is_cancel_requested(self, run_id: int) -> bool:
        run = self.get_run(run_id)
        return bool(run.get("cancel_requested"))

    def retry_run(self, run_id: int) -> dict:
        previous = self.get_run(run_id)
        if not previous:
            raise ValueError("workflow run not found")
        return self.begin_run(
            kind=previous["kind"], title=previous["title"], session_id=previous.get("session_id"),
            channel=previous.get("channel", ""), metadata=previous.get("metadata", {}),
            retry_of_run_id=int(run_id),
        )

    @staticmethod
    def cache_key(namespace: str, payload: dict) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(f"{namespace}:{encoded}".encode("utf-8")).hexdigest()

    def get_cache(self, namespace: str, payload: dict) -> str | None:
        key = self.cache_key(namespace, payload)
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT content,expires_at FROM workflow_cache WHERE cache_key=?", (key,)
            ).fetchone()
            if not row or (float(row["expires_at"] or 0) and float(row["expires_at"]) < time.time()):
                if row:
                    conn.execute("DELETE FROM workflow_cache WHERE cache_key=?", (key,))
                return None
            conn.execute(
                "UPDATE workflow_cache SET hit_count=hit_count+1,updated_at=? WHERE cache_key=?",
                (_now(), key),
            )
            return str(row["content"])
        finally:
            conn.close()

    def put_cache(self, namespace: str, payload: dict, content: str, *, ttl_seconds: int,
                  metadata: dict | None = None) -> None:
        key = self.cache_key(namespace, payload)
        timestamp = _now()
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO workflow_cache
                   (cache_key,namespace,content,metadata_json,expires_at,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(cache_key) DO UPDATE SET content=excluded.content,
                     metadata_json=excluded.metadata_json,expires_at=excluded.expires_at,updated_at=excluded.updated_at""",
                (key, namespace, str(content), json.dumps(metadata or {}, ensure_ascii=False),
                 time.time() + max(1, int(ttl_seconds)), timestamp, timestamp),
            )
        finally:
            conn.close()

    def cleanup_cache(self, *, max_entries: int = 1000) -> int:
        """Delete only expired or least-recently-used cache rows; audit runs are retained."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            expired = conn.execute(
                "DELETE FROM workflow_cache WHERE expires_at>0 AND expires_at<?", (time.time(),)
            ).rowcount
            overflow = conn.execute(
                "SELECT MAX(0,COUNT(*)-?) FROM workflow_cache", (max(1, int(max_entries)),)
            ).fetchone()[0]
            removed = int(expired)
            if overflow:
                cur = conn.execute(
                    """DELETE FROM workflow_cache WHERE cache_key IN (
                       SELECT cache_key FROM workflow_cache ORDER BY updated_at ASC LIMIT ?
                    )""",
                    (int(overflow),),
                )
                removed += int(cur.rowcount)
            conn.commit()
            return removed
        finally:
            conn.close()

    @staticmethod
    def _decode(row) -> dict:
        if not row:
            return {}
        item = dict(row)
        for key in ("metadata_json", "input_json"):
            if key in item:
                try:
                    item[key.removesuffix("_json")] = json.loads(item.pop(key) or "{}")
                except (TypeError, ValueError, json.JSONDecodeError):
                    item[key.removesuffix("_json")] = {}
        return item


_store: WorkflowStore | None = None
_store_lock = threading.Lock()
_context = threading.local()


def get_workflow_store() -> WorkflowStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = WorkflowStore()
    return _store


def set_workflow_context(run_id: int | None, *, step_key: str = "") -> None:
    _context.run_id = int(run_id or 0)
    _context.step_key = str(step_key or "")


def get_workflow_context() -> tuple[int, str]:
    return int(getattr(_context, "run_id", 0) or 0), str(getattr(_context, "step_key", "") or "")


@contextmanager
def workflow_context(run_id: int | None, *, step_key: str = ""):
    previous = get_workflow_context()
    set_workflow_context(run_id, step_key=step_key)
    try:
        yield
    finally:
        set_workflow_context(previous[0], step_key=previous[1])
