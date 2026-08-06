"""Diagnostics for incremental memory embedding synchronization."""

from __future__ import annotations


def get_embedding_sync_status() -> dict:
    """Return bounded, content-free synchronization statistics."""
    try:
        from brain.graph_memory import _get_conn

        conn = _get_conn()
        total = int(conn.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0])
        active = int(conn.execute(
            "SELECT COUNT(*) FROM memory_facts WHERE status='active'"
        ).fetchone()[0])
        pending = int(conn.execute(
            "SELECT COUNT(*) FROM memory_facts "
            "WHERE status='active' AND embedding IS NULL"
        ).fetchone()[0])
        indexed = int(conn.execute(
            "SELECT COUNT(*) FROM memory_facts "
            "WHERE status='active' AND embedding IS NOT NULL"
        ).fetchone()[0])
        return {
            "status": "pending" if pending else "ready",
            "total": total,
            "active": active,
            "indexed": indexed,
            "pending": pending,
        }
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}
