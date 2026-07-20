"""Audited feedback from user corrections to derived narrative memory."""
from __future__ import annotations

import json
from datetime import datetime

from brain.graph_memory import _get_conn


def _now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _ids(value):
    try:
        return {int(item) for item in json.loads(value or "[]")}
    except (TypeError, ValueError, json.JSONDecodeError):
        return set()


def _ensure():
    conn = _get_conn()
    try:
        from brain.memory_narrative import _ensure_tables
        _ensure_tables()
    except Exception:
        pass
    conn.execute("""CREATE TABLE IF NOT EXISTS memory_correction_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, fact_ids TEXT NOT NULL,
        action TEXT NOT NULL, reason TEXT DEFAULT '', affected_episodes TEXT DEFAULT '[]',
        affected_entities TEXT DEFAULT '[]', affected_sagas TEXT DEFAULT '[]', created_at TEXT NOT NULL
    )""")
    conn.commit()
    return conn


def apply_correction_feedback(fact_ids, *, action="update", reason="", conn=None, commit=True) -> dict:
    """Mark derived records for review instead of silently leaving stale narratives."""
    if conn is None:
        conn = _ensure()
    else:
        _ensure()
    clean_ids = sorted({int(value) for value in fact_ids if int(value) > 0})
    if not clean_ids:
        return {"episodes": [], "entities": [], "sagas": []}
    episode_ids = []
    entity_ids = []
    saga_ids = []
    for row in conn.execute("SELECT id,source_fact_ids,entity_ids FROM memory_episodes WHERE status='active'").fetchall():
        if _ids(row["source_fact_ids"]) & set(clean_ids):
            episode_ids.append(int(row["id"]))
            conn.execute("UPDATE memory_episodes SET status='needs_review',updated_at=? WHERE id=?", (_now(), int(row["id"])))
            entity_ids.extend(_ids(row["entity_ids"]))
    entity_ids = sorted(set(entity_ids))
    if entity_ids:
        placeholders = ",".join("?" for _ in entity_ids)
        conn.execute(
            f"UPDATE memory_entity_profiles SET status='needs_review', confidence=MAX(0.05, confidence*0.6), updated_at=? WHERE id IN ({placeholders})",
            [_now(), *entity_ids],
        )
    for row in conn.execute("SELECT id,episode_ids FROM memory_sagas WHERE status='active'").fetchall():
        if _ids(row["episode_ids"]) & set(episode_ids):
            saga_ids.append(int(row["id"]))
            conn.execute("UPDATE memory_sagas SET status='needs_review',confidence=MAX(0.05, confidence*0.6),updated_at=? WHERE id=?", (_now(), int(row["id"])))
    conn.execute(
        """INSERT INTO memory_correction_events
           (fact_ids,action,reason,affected_episodes,affected_entities,affected_sagas,created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (json.dumps(clean_ids), str(action), str(reason or "")[:500], json.dumps(episode_ids),
         json.dumps(entity_ids), json.dumps(saga_ids), _now()),
    )
    if commit:
        conn.commit()
    return {"episodes": episode_ids, "entities": entity_ids, "sagas": saga_ids}


def list_correction_events(limit=50):
    rows = _ensure().execute("SELECT * FROM memory_correction_events ORDER BY id DESC LIMIT ?", (max(1, min(200, int(limit))),)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        for key in ("fact_ids", "affected_episodes", "affected_entities", "affected_sagas"):
            try:
                item[key] = json.loads(item[key] or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                item[key] = []
        result.append(item)
    return result
