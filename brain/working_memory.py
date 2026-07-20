"""Persistent topic working memory for the current conversation focus."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from brain.graph_memory import _get_conn


def _now():
    return datetime.now().astimezone()


def _ensure():
    conn = _get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS memory_working_topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT, topic_key TEXT NOT NULL UNIQUE,
        topic_label TEXT NOT NULL, summary TEXT DEFAULT '', facts_json TEXT DEFAULT '[]',
        open_loops_json TEXT DEFAULT '[]', session_id INTEGER, status TEXT DEFAULT 'active',
        last_active_at TEXT NOT NULL, expires_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_working_topics_active ON memory_working_topics(status,last_active_at)")
    conn.commit()
    return conn


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", str(text or "").lower())}


def _topic_key(text: str) -> str:
    tokens = sorted(_tokens(text))[:12]
    return " ".join(tokens) or "general"


def update_working_topic(*, user_message: str, recent_messages: list[dict] | None = None,
                         session_id: int | None = None, ttl_minutes: int = 120) -> dict:
    conn = _ensure()
    now = _now()
    semantic_key = _topic_key(user_message)
    key = f"session:{session_id or 0}|{semantic_key}"
    active = conn.execute(
        "SELECT * FROM memory_working_topics WHERE status='active' AND session_id IS ? ORDER BY last_active_at DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if active:
        active_semantic = str(active["topic_key"]).split("|", 1)[-1]
        overlap = len(_tokens(semantic_key) & _tokens(active_semantic)) / max(1, len(_tokens(semantic_key) | _tokens(active_semantic)))
        if overlap < 0.12 and semantic_key != "general":
            conn.execute("UPDATE memory_working_topics SET status='archived',updated_at=? WHERE id=?", (now.isoformat(timespec="seconds"), int(active["id"])))
            active = None
    messages = list(recent_messages or [])[-8:]
    lines = []
    facts = []
    open_loops = []
    for message in messages:
        content = str(message.get("content", "") or "").strip()
        if not content:
            continue
        role = "用户" if message.get("role") == "user" else "莲心"
        lines.append(f"{role}：{content[:240]}")
        if message.get("role") == "user" and ("?" in content or "？" in content or "待" in content or "需要" in content):
            open_loops.append(content[:180])
    summary = "\n".join(lines)[-1800:]
    expires = now + timedelta(minutes=max(15, min(720, int(ttl_minutes))))
    if active and active["topic_key"] == key:
        topic_id = int(active["id"])
        conn.execute("""UPDATE memory_working_topics SET topic_label=?,summary=?,facts_json=?,open_loops_json=?,
          session_id=?,last_active_at=?,expires_at=?,updated_at=? WHERE id=?""", (
            user_message.strip()[:80] or "当前话题", summary, json.dumps(facts, ensure_ascii=False),
            json.dumps(open_loops, ensure_ascii=False), session_id, now.isoformat(timespec="seconds"),
            expires.isoformat(timespec="seconds"), now.isoformat(timespec="seconds"), topic_id))
    else:
        cur = conn.execute("""INSERT INTO memory_working_topics
          (topic_key,topic_label,summary,facts_json,open_loops_json,session_id,last_active_at,expires_at,updated_at)
          VALUES (?,?,?,?,?,?,?,?,?)""", (key, user_message.strip()[:80] or "当前话题", summary,
          json.dumps(facts, ensure_ascii=False), json.dumps(open_loops, ensure_ascii=False), session_id,
          now.isoformat(timespec="seconds"), expires.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")))
        topic_id = int(cur.lastrowid)
    conn.execute("UPDATE memory_working_topics SET status='expired' WHERE status='active' AND expires_at<?", (now.isoformat(timespec="seconds"),))
    conn.commit()
    return get_working_topic(topic_id)


def get_working_topic(topic_id: int | None = None) -> dict | None:
    conn = _ensure()
    if topic_id:
        row = conn.execute("SELECT * FROM memory_working_topics WHERE id=?", (int(topic_id),)).fetchone()
    else:
        row = conn.execute("""SELECT * FROM memory_working_topics WHERE status='active' AND expires_at>=?
          ORDER BY last_active_at DESC LIMIT 1""", (_now().isoformat(timespec="seconds"),)).fetchone()
    if not row:
        return None
    result = dict(row)
    result["facts"] = json.loads(result.pop("facts_json") or "[]")
    result["open_loops"] = json.loads(result.pop("open_loops_json") or "[]")
    return result


def format_working_memory_context(topic: dict | None = None) -> str:
    topic = topic or get_working_topic()
    if not topic or not topic.get("summary"):
        return ""
    lines = ["【当前话题工作记忆】", f"主题：{topic.get('topic_label', '当前话题')}", topic["summary"]]
    loops = topic.get("open_loops") or []
    if loops:
        lines.append("未闭环问题：" + "；".join(loops[:3]))
    lines.append("这只是当前话题的临时工作记忆；话题切换后不要把它当作长期事实。")
    return "\n".join(lines)
