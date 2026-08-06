"""Content-free diagnostics for immediate and background memory writes."""

from __future__ import annotations


def get_memory_write_status() -> dict:
    """Return safe status counters without exposing memory text."""
    result = {
        "immediate": {"last_status": "unknown"},
        "background": {"status": "unknown", "pending_messages": 0},
        "facts": {"active": 0, "manual": 0, "automatic": 0},
    }
    try:
        from brain.graph_memory import _get_conn

        conn = _get_conn()
        result["facts"]["active"] = int(conn.execute(
            "SELECT COUNT(*) FROM memory_facts WHERE status='active'"
        ).fetchone()[0])
        result["facts"]["manual"] = int(conn.execute(
            "SELECT COUNT(*) FROM memory_facts "
            "WHERE status='active' AND source='user_saved'"
        ).fetchone()[0])
        result["facts"]["automatic"] = int(conn.execute(
            "SELECT COUNT(*) FROM memory_facts "
            "WHERE status='active' AND source='auto_extracted'"
        ).fetchone()[0])
    except Exception as exc:
        result["facts"]["error"] = str(exc)

    try:
        from config import get_memory_config
        result["background"]["enabled"] = bool(get_memory_config().get("auto_extract", True))
    except Exception:
        result["background"]["enabled"] = False
    return result
