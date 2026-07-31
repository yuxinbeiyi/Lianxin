"""Request-level memory diagnostics stored alongside the memory database.

Diagnostics deliberately record only owner conversations and truncated payloads;
the panel is a developer aid, not a second conversation history.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from brain.graph_memory import _get_conn

_lock = threading.RLock()

def _now():
    return datetime.now().astimezone().isoformat(timespec="seconds")

def _ensure():
    conn = _get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS memory_debug_requests (
      id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT NOT NULL UNIQUE,
      session_id INTEGER, channel TEXT DEFAULT '', persona_id TEXT DEFAULT '',
      persona_revision INTEGER DEFAULT 0, user_message TEXT DEFAULT '',
      started_at TEXT NOT NULL, finished_at TEXT DEFAULT '', status TEXT DEFAULT 'running',
      response_preview TEXT DEFAULT '', duration_ms REAL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS memory_debug_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT NOT NULL,
      event_type TEXT NOT NULL, memory_id INTEGER, score REAL,
      reason TEXT DEFAULT '', payload_json TEXT DEFAULT '{}', created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_debug_events_trace ON memory_debug_events(trace_id);
    CREATE INDEX IF NOT EXISTS idx_debug_requests_started ON memory_debug_requests(started_at);
    """)
    conn.commit()
    return conn

def start_memory_trace(*, session_id=None, channel="", persona_id="", persona_revision=0,
                       user_message="") -> str:
    trace_id = uuid.uuid4().hex
    with _lock:
        conn = _ensure()
        conn.execute("""INSERT INTO memory_debug_requests
          (trace_id,session_id,channel,persona_id,persona_revision,user_message,started_at)
          VALUES (?,?,?,?,?,?,?)""", (trace_id, session_id, channel, persona_id,
          int(persona_revision or 0), str(user_message or "")[:500], _now()))
        conn.commit()
    return trace_id

def record_memory_event(trace_id, event_type, *, memory_id=None, score=None,
                        reason="", payload=None):
    if not trace_id:
        return
    try:
        encoded = json.dumps(payload or {}, ensure_ascii=False, default=str)[:4000]
    except Exception:
        encoded = "{}"
    with _lock:
        conn = _ensure()
        conn.execute("""INSERT INTO memory_debug_events
          (trace_id,event_type,memory_id,score,reason,payload_json,created_at)
          VALUES (?,?,?,?,?,?,?)""", (trace_id, str(event_type), memory_id, score,
          str(reason or "")[:500], encoded, _now()))
        conn.commit()

def finish_memory_trace(trace_id, *, status="success", response="", duration_ms=0):
    if not trace_id:
        return
    with _lock:
        conn = _ensure()
        conn.execute("""UPDATE memory_debug_requests SET finished_at=?,status=?,
          response_preview=?,duration_ms=? WHERE trace_id=?""", (_now(), status,
          str(response or "")[:500], float(duration_ms or 0), trace_id))
        conn.commit()

def get_memory_traces(limit=100, *, persona_id="", channel="", status=""):
    conn = _ensure()
    sql = "SELECT * FROM memory_debug_requests WHERE 1=1"
    args = []
    for field, value in (("persona_id", persona_id), ("channel", channel), ("status", status)):
        if value:
            sql += f" AND {field}=?"; args.append(value)
    sql += " ORDER BY id DESC LIMIT ?"; args.append(max(1, min(500, int(limit))))
    return [dict(r) for r in conn.execute(sql, args).fetchall()]

def get_trace_events(trace_id):
    conn = _ensure()
    rows = conn.execute("SELECT * FROM memory_debug_events WHERE trace_id=? ORDER BY id", (trace_id,)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try: item["payload"] = json.loads(item.pop("payload_json") or "{}")
        except Exception: item["payload"] = {}
        result.append(item)
    return result

def get_memory_diagnostic_stats():
    conn = _ensure()
    row = conn.execute(
        """SELECT COUNT(*) total, SUM(status='success') success,
           SUM(status='failed') failed, SUM(status='running') running
           FROM memory_debug_requests"""
    ).fetchone()
    events = conn.execute("SELECT event_type, COUNT(*) count FROM memory_debug_events GROUP BY event_type ORDER BY count DESC").fetchall()
    traces = get_memory_traces(300)
    recall_by_prompt = {}
    for trace in traces:
        persona = trace.get("persona_id") or "default"
        prompt = " ".join((trace.get("user_message") or "").lower().split())
        if not prompt:
            continue
        ids = {event.get("memory_id") for event in get_trace_events(trace["trace_id"])
               if event.get("event_type") == "rag_memory_injected" and event.get("memory_id")}
        recall_by_prompt.setdefault(prompt, {})[persona] = ids
    mismatches = 0
    for per_persona in recall_by_prompt.values():
        if len(per_persona) > 1 and len({tuple(sorted(ids)) for ids in per_persona.values()}) > 1:
            mismatches += 1
    return {"requests": dict(row), "events": [dict(r) for r in events],
            "persona_recall_mismatches": mismatches}

def prune_memory_diagnostics(keep=300):
    with _lock:
        conn = _ensure()
        conn.execute("DELETE FROM memory_debug_events WHERE trace_id IN (SELECT trace_id FROM memory_debug_requests ORDER BY id DESC LIMIT -1 OFFSET ?)", (max(10, int(keep)),))
        conn.execute("DELETE FROM memory_debug_requests WHERE id NOT IN (SELECT id FROM memory_debug_requests ORDER BY id DESC LIMIT ?)", (max(10, int(keep)),))
        conn.commit()
