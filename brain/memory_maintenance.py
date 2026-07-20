"""Idempotent, low-frequency maintenance for memory and current-state data."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime

from brain.graph_memory import _get_conn


_RUN_LOCK = threading.Lock()


def _ensure_tables():
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_maintenance_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT DEFAULT '',
            duration_ms REAL DEFAULT 0,
            stats_json TEXT NOT NULL DEFAULT '{}',
            error TEXT DEFAULT ''
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_maintenance_runs_started "
        "ON memory_maintenance_runs(started_at DESC)"
    )
    conn.commit()
    return conn


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _table_exists(conn, table: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone())


def _valid_message_ids(conn) -> set[int] | None:
    if not _table_exists(conn, "messages"):
        return None
    return {
        int(row["id"])
        for row in conn.execute("SELECT id FROM messages").fetchall()
    }


def _clean_source_message_ids(conn, valid_ids: set[int] | None) -> int:
    """Remove references to deleted chat messages without changing audit events."""
    if valid_ids is None:
        return 0
    cleaned = 0
    targets = [
        ("memory_fragments", "id"),
        ("memory_conflict_candidates", "id"),
        ("memory_conflict_events", "id"),
        ("memory_state_events", "id"),
        ("memory_current_states", "id"),
    ]
    for table, key in targets:
        if not _table_exists(conn, table):
            continue
        rows = conn.execute(
            f"SELECT {key}, source_message_ids FROM {table} "
            "WHERE source_message_ids IS NOT NULL AND source_message_ids<>''"
        ).fetchall()
        for row in rows:
            try:
                values = json.loads(row["source_message_ids"] or "[]")
            except (TypeError, json.JSONDecodeError):
                values = []
            valid = []
            for value in values:
                try:
                    item = int(value)
                except (TypeError, ValueError):
                    continue
                if item in valid_ids and item not in valid:
                    valid.append(item)
            if valid != values:
                conn.execute(
                    f"UPDATE {table} SET source_message_ids=? WHERE {key}=?",
                    (json.dumps(valid, ensure_ascii=False), row[key]),
                )
                cleaned += 1
    return cleaned


def _cleanup_orphans(conn) -> dict:
    stats = {}
    if _table_exists(conn, "memory_fragments"):
        cur = conn.execute(
            "DELETE FROM memory_fragments WHERE fact_id NOT IN "
            "(SELECT id FROM memory_facts)"
        )
        stats["orphan_fragments_removed"] = cur.rowcount
    if _table_exists(conn, "memory_conflict_candidates"):
        cur = conn.execute(
            "DELETE FROM memory_conflict_candidates WHERE existing_fact_id NOT IN "
            "(SELECT id FROM memory_facts) OR new_fact_id NOT IN (SELECT id FROM memory_facts)"
        )
        stats["orphan_conflict_candidates_removed"] = cur.rowcount
    if _table_exists(conn, "memory_fact_relations"):
        cur = conn.execute(
            "DELETE FROM memory_fact_relations WHERE source_fact_id NOT IN "
            "(SELECT id FROM memory_facts) OR target_fact_id NOT IN (SELECT id FROM memory_facts)"
        )
        stats["orphan_relations_removed"] = cur.rowcount
    if _table_exists(conn, "memory_conflict_events"):
        cur = conn.execute(
            "DELETE FROM memory_conflict_events WHERE candidate_id NOT IN "
            "(SELECT id FROM memory_conflict_candidates)"
        )
        stats["orphan_conflict_events_removed"] = cur.rowcount
    return stats


def _scan_conflict_candidates(conn, batch_size: int) -> int:
    try:
        from brain.memory_conflicts import record_conflict_candidates
        rows = conn.execute(
            """SELECT id FROM memory_facts WHERE status='active'
               ORDER BY COALESCE(quality_updated_at, ''), id DESC LIMIT ?""",
            (max(1, min(int(batch_size), 100)),),
        ).fetchall()
        discovered = 0
        for row in rows:
            discovered += len(record_conflict_candidates(int(row["id"])))
        return discovered
    except Exception:
        return 0


def run_memory_maintenance(
    *,
    trigger: str = "scheduled",
    conflict_scan_batch: int = 10,
    now: datetime | None = None,
) -> dict:
    """Run one maintenance pass. A concurrent pass is skipped safely."""
    if not _RUN_LOCK.acquire(blocking=False):
        return {"status": "skipped", "reason": "already_running"}
    started = time.perf_counter()
    started_at = _iso(now or _now())
    conn = _ensure_tables()
    run_id = conn.execute(
        "INSERT INTO memory_maintenance_runs(trigger,status,started_at) VALUES (?, 'running', ?)",
        (str(trigger or "scheduled"), started_at),
    ).lastrowid
    conn.commit()
    try:
        from brain.current_state import expire_current_states
        from brain.memory_quality import get_memory_statistics, recalculate_memory_quality

        current = now or _now()
        stats = {"current_states_expired": expire_current_states(now=current)}
        stats.update(_cleanup_orphans(conn))
        stats["source_references_cleaned"] = _clean_source_message_ids(
            conn, _valid_message_ids(conn)
        )
        stats["conflict_candidates_discovered"] = _scan_conflict_candidates(
            conn, conflict_scan_batch
        )
        stats["quality"] = recalculate_memory_quality(now=current)
        stats["memory"] = get_memory_statistics()
        conn.commit()
        finished_at = _iso(_now())
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        conn.execute(
            """UPDATE memory_maintenance_runs SET status='success', finished_at=?,
                   duration_ms=?, stats_json=? WHERE id=?""",
            (finished_at, duration_ms, json.dumps(stats, ensure_ascii=False, default=str), run_id),
        )
        conn.execute(
            """DELETE FROM memory_maintenance_runs
               WHERE id NOT IN (
                   SELECT id FROM memory_maintenance_runs ORDER BY id DESC LIMIT 100
               )"""
        )
        conn.commit()
        return {"status": "success", "run_id": run_id, "duration_ms": duration_ms, **stats}
    except Exception as exc:
        conn.rollback()
        finished_at = _iso(_now())
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        conn.execute(
            """UPDATE memory_maintenance_runs SET status='failed', finished_at=?,
                   duration_ms=?, error=? WHERE id=?""",
            (finished_at, duration_ms, str(exc)[:1000], run_id),
        )
        conn.commit()
        return {
            "status": "failed", "run_id": run_id,
            "duration_ms": duration_ms, "error": str(exc),
        }
    finally:
        _RUN_LOCK.release()


def get_last_maintenance_run() -> dict | None:
    row = _ensure_tables().execute(
        "SELECT * FROM memory_maintenance_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    result = dict(row)
    try:
        result["stats"] = json.loads(result.pop("stats_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        result["stats"] = {}
    return result


def should_run_maintenance(interval_hours: float = 6.0, *, now: datetime | None = None) -> bool:
    last = get_last_maintenance_run()
    if not last or last.get("status") != "success":
        return True
    current = now or _now()
    finished = last.get("finished_at", "")
    try:
        previous = datetime.fromisoformat(finished)
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=current.tzinfo)
        return (current - previous.astimezone(current.tzinfo)).total_seconds() >= max(1.0, float(interval_hours) * 3600)
    except (TypeError, ValueError):
        return True


def get_maintenance_runs(limit: int = 20) -> list[dict]:
    rows = _ensure_tables().execute(
        "SELECT * FROM memory_maintenance_runs ORDER BY id DESC LIMIT ?",
        (max(1, min(int(limit), 100)),),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["stats"] = json.loads(item.pop("stats_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            item["stats"] = {}
        result.append(item)
    return result
