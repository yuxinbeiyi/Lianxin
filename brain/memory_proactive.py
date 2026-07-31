"""Memory-to-proactive bridge: model evaluates meaning, code enforces timing."""
from __future__ import annotations
import hashlib, json, threading
from datetime import datetime, timedelta
from brain.graph_memory import _get_conn

_lock = threading.RLock()
_schema_ready_path = ""

def _now(): return datetime.now().astimezone()
def _iso(dt): return dt.isoformat(timespec="seconds")

def _ensure():
    global _schema_ready_path
    conn = _get_conn()
    db_row = conn.execute("PRAGMA database_list").fetchone()
    db_path = str(db_row["file"] if db_row else "")
    if _schema_ready_path == db_path:
        return conn
    with _lock:
        if _schema_ready_path == db_path:
            return conn
        conn.executescript("""
    CREATE TABLE IF NOT EXISTS memory_proactive_cues (
      id INTEGER PRIMARY KEY AUTOINCREMENT, source_kind TEXT NOT NULL, source_id INTEGER NOT NULL,
      fingerprint TEXT NOT NULL UNIQUE, content TEXT NOT NULL, state_type TEXT DEFAULT '',
      status TEXT NOT NULL DEFAULT 'candidate', due_at TEXT DEFAULT '', window_end TEXT DEFAULT '',
      action TEXT DEFAULT 'contact', suggested_message TEXT DEFAULT '', rationale TEXT DEFAULT '',
      confidence REAL DEFAULT 0, persona_id TEXT DEFAULT '', attempts INTEGER DEFAULT 0,
      last_error TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      delivered_at TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_memory_cues_due ON memory_proactive_cues(status,due_at);
    CREATE TABLE IF NOT EXISTS memory_proactive_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, cue_id INTEGER, action TEXT NOT NULL,
      detail TEXT DEFAULT '', created_at TEXT NOT NULL
    );
        """); conn.commit(); _schema_ready_path = db_path
    return conn

def _fingerprint(kind, source_id, content):
    return hashlib.sha256(f"{kind}:{source_id}:{content}".encode("utf-8")).hexdigest()

def collect_candidates(limit=8, *, now=None):
    """Expose explicit current states to the model; no semantic inference here."""
    # Ensure lifecycle expiry has run before candidates are copied.
    from brain.current_state import list_current_states
    list_current_states(now=now)
    conn = _ensure(); now = _iso(now or _now())
    rows = conn.execute("""SELECT id,state_type,content,confidence,expires_at,source_channel
      FROM memory_current_states WHERE status='active' AND expires_at>? ORDER BY expires_at LIMIT ?""", (now, max(1, int(limit)))).fetchall()
    out=[]
    with _lock:
        for r in rows:
            d=dict(r); fp=_fingerprint("current_state", d["id"], d["content"])
            conn.execute("""INSERT OR IGNORE INTO memory_proactive_cues
              (source_kind,source_id,fingerprint,content,state_type,confidence,created_at,updated_at)
              VALUES ('current_state',?,?,?,?,?,?,?)""", (d["id"],fp,d["content"],d["state_type"],float(d["confidence"] or 0),_now().isoformat(),_now().isoformat()))
            status_row = conn.execute("SELECT status FROM memory_proactive_cues WHERE fingerprint=?", (fp,)).fetchone()
            if status_row and status_row["status"] == "candidate":
                out.append({"source_kind":"current_state", "source_id":d["id"], "content":d["content"], "state_type":d["state_type"], "confidence":d["confidence"], "expires_at":d["expires_at"], "fingerprint":fp})
        conn.commit()
    return out

def apply_evaluations(items, *, now=None):
    conn=_ensure(); now=now or _now()
    if now.tzinfo is None: now=now.replace(tzinfo=_now().tzinfo)
    for item in items or []:
        fp=item.get("fingerprint")
        if not fp: continue
        decision=item.get("decision") if isinstance(item.get("decision"), dict) else item
        action=str(decision.get("action", "skip")).lower()
        status="approved" if action in ("contact","remind","check_in") else ("suppressed" if action=="suppress" else "dismissed")
        due=str(decision.get("due_at", "") or "")
        end=str(decision.get("window_end", "") or "")
        try:
            parsed=datetime.fromisoformat(due.replace("Z","+00:00")) if due else now
            if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=now.tzinfo)
            if parsed < now-timedelta(minutes=1): parsed=now
            if parsed > now+timedelta(days=30): parsed=now+timedelta(days=30)
            due=_iso(parsed)
        except Exception: due=_iso(now)
        conn.execute("""UPDATE memory_proactive_cues SET status=?,due_at=?,window_end=?,action=?,
          suggested_message=?,rationale=?,confidence=?,updated_at=? WHERE fingerprint=?""", (status,due,end,action,
          str(decision.get("message_instruction", ""))[:500],str(decision.get("rationale", ""))[:500],float(decision.get("confidence",0) or 0),_iso(now),fp))
        conn.execute("INSERT INTO memory_proactive_events(cue_id,action,detail,created_at) SELECT id,?,?,? FROM memory_proactive_cues WHERE fingerprint=?", ("evaluated",status,_iso(now),fp))
    conn.commit()

def get_due_cue(now=None):
    conn=_ensure(); now=_iso(now or _now())
    row=conn.execute("""SELECT c.* FROM memory_proactive_cues c WHERE c.status='approved' AND c.due_at<=?
      AND (c.window_end='' OR c.window_end>=?) AND (c.source_kind!='current_state' OR EXISTS(
        SELECT 1 FROM memory_current_states s WHERE s.id=c.source_id AND s.status='active'))
      ORDER BY c.confidence DESC,c.due_at LIMIT 1""",(now,now)).fetchone()
    return dict(row) if row else None

def get_active_suppression(now=None):
    conn=_ensure(); now=_iso(now or _now())
    try:
        row=conn.execute("""SELECT c.* FROM memory_proactive_cues c WHERE c.status='suppressed'
      AND c.due_at<=? AND c.window_end!='' AND c.window_end>=?
      AND (c.source_kind!='current_state' OR EXISTS(SELECT 1 FROM memory_current_states s WHERE s.id=c.source_id AND s.status='active'))
      ORDER BY c.confidence DESC LIMIT 1""",(now,now)).fetchone()
    except Exception:
        return None
    return dict(row) if row else None

def mark_cue_delivered(cue_id, text=""):
    conn=_ensure(); now=_iso(_now()); conn.execute("UPDATE memory_proactive_cues SET status='delivered',delivered_at=?,updated_at=?,suggested_message=? WHERE id=?",(now,now,str(text or "")[:500],int(cue_id))); conn.execute("INSERT INTO memory_proactive_events(cue_id,action,detail,created_at) VALUES(?,?,?,?)",(int(cue_id),"delivered",str(text or "")[:200],now)); conn.commit()

def mark_cue_failed(cue_id, error):
    conn=_ensure(); conn.execute("UPDATE memory_proactive_cues SET status='failed',attempts=attempts+1,last_error=?,updated_at=? WHERE id=?",(str(error)[:500],_iso(_now()),int(cue_id))); conn.commit()

def list_cues(limit=100):
    conn=_ensure(); return [dict(r) for r in conn.execute("SELECT * FROM memory_proactive_cues ORDER BY id DESC LIMIT ?",(max(1,min(500,int(limit))),)).fetchall()]

def should_evaluate(interval_minutes=30):
    conn=_ensure(); row=conn.execute("SELECT created_at FROM memory_proactive_events WHERE action='evaluation_batch' ORDER BY id DESC LIMIT 1").fetchone()
    if not row: return True
    try: return (_now()-datetime.fromisoformat(row["created_at"])).total_seconds() >= max(5,int(interval_minutes))*60
    except Exception: return True

def record_evaluation_batch(detail=""):
    conn=_ensure(); conn.execute("INSERT INTO memory_proactive_events(cue_id,action,detail,created_at) VALUES(NULL,'evaluation_batch',?,?)",(str(detail)[:300],_iso(_now()))); conn.commit()
