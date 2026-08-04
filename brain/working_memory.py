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
        last_active_at TEXT NOT NULL, expires_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        model_summary TEXT DEFAULT '', model_facts_json TEXT DEFAULT '[]',
        task_state TEXT DEFAULT 'none', summary_source TEXT DEFAULT 'code', summary_updated_at TEXT DEFAULT ''
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_working_topics_active ON memory_working_topics(status,last_active_at)")
    for sql in (
        "ALTER TABLE memory_working_topics ADD COLUMN model_summary TEXT DEFAULT ''",
        "ALTER TABLE memory_working_topics ADD COLUMN model_facts_json TEXT DEFAULT '[]'",
        "ALTER TABLE memory_working_topics ADD COLUMN task_state TEXT DEFAULT 'none'",
        "ALTER TABLE memory_working_topics ADD COLUMN summary_source TEXT DEFAULT 'code'",
        "ALTER TABLE memory_working_topics ADD COLUMN summary_updated_at TEXT DEFAULT ''",
    ):
        try:
            conn.execute(sql)
        except Exception:
            pass
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
    seen_assistant = set()
    seen_user_loops = set()
    for message in messages:
        content = str(message.get("content", "") or "").strip()
        if not content:
            continue
        is_user = message.get("role") == "user"
        if not is_user:
            # 重复模型输出通常是一次生成故障，不应被工作记忆再次强化。
            normalized = re.sub(r"\s+", " ", content)
            if normalized in seen_assistant:
                continue
            seen_assistant.add(normalized)
        role = "用户" if is_user else "莲心"
        lines.append(f"{role}：{content[:240]}")
        if is_user and ("?" in content or "？" in content or "待" in content or "需要" in content):
            loop = content[:180]
            if loop not in seen_user_loops:
                seen_user_loops.add(loop)
                open_loops.append(loop)
    if active and not open_loops and active["summary_source"] == "model":
        try:
            open_loops = json.loads(active["open_loops_json"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            open_loops = []
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


def acknowledge_quote_reply(*, session_id: int | None = None) -> int:
    """引用确认型消息到达时，关闭当前话题的未闭环任务。

    话题摘要本身仍保留，便于后续自然回忆；这里只清除“待继续执行”的
    open loop，避免用户说“我看过了/谢谢推荐”后旧任务再次被捞起。
    """
    conn = _ensure()
    now = _now().isoformat(timespec="seconds")
    cur = conn.execute(
        """UPDATE memory_working_topics
           SET open_loops_json='[]', task_state='acknowledged', updated_at=?
           WHERE status='active' AND session_id IS ?""",
        (now, session_id),
    )
    conn.commit()
    return int(cur.rowcount or 0)


def get_working_topic(topic_id: int | None = None, session_id: int | None = None) -> dict | None:
    conn = _ensure()
    if topic_id:
        row = conn.execute("SELECT * FROM memory_working_topics WHERE id=?", (int(topic_id),)).fetchone()
    elif session_id is not None:
        row = conn.execute("""SELECT * FROM memory_working_topics WHERE status='active' AND session_id IS ?
          AND expires_at>=? ORDER BY last_active_at DESC LIMIT 1""", (session_id, _now().isoformat(timespec="seconds"))).fetchone()
    else:
        row = conn.execute("""SELECT * FROM memory_working_topics WHERE status='active' AND expires_at>=?
          ORDER BY last_active_at DESC LIMIT 1""", (_now().isoformat(timespec="seconds"),)).fetchone()
    if not row:
        return None
    result = dict(row)
    result["facts"] = json.loads(result.pop("facts_json") or "[]")
    result["model_facts"] = json.loads(result.pop("model_facts_json", "[]") or "[]")
    result["open_loops"] = json.loads(result.pop("open_loops_json") or "[]")
    return result


def should_refresh_model_summary(topic: dict | None, interval_minutes: int = 10) -> bool:
    if not topic or not topic.get("model_summary"):
        return True
    try:
        updated = datetime.fromisoformat(topic.get("summary_updated_at", ""))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=_now().tzinfo)
        return (_now() - updated.astimezone(_now().tzinfo)).total_seconds() >= max(1, int(interval_minutes)) * 60
    except (TypeError, ValueError):
        return True


def format_working_memory_context(topic: dict | None = None) -> str:
    topic = topic or get_working_topic()
    if not topic or not (topic.get("summary") or topic.get("model_summary")):
        return ""
    summary = topic.get("model_summary") or topic.get("summary")
    lines = ["【当前话题工作记忆】", f"主题：{topic.get('topic_label', '当前话题')}", summary]
    lines.append("这是辅助线索；必须优先依据本轮用户消息和最近一条真实对话，不要复述旧回复。")
    if topic.get("model_summary"):
        lines.append(f"模型任务阶段：{topic.get('task_state', 'none')}")
    facts = topic.get("model_facts") or topic.get("facts") or []
    if facts:
        lines.append("当前稳定事实：" + "；".join(str(item)[:180] for item in facts[:5]))
    loops = topic.get("open_loops") or []
    if loops:
        lines.append("未闭环问题：" + "；".join(loops[:3]))
    lines.append("这只是当前话题的临时工作记忆；话题切换后不要把它当作长期事实。")
    return "\n".join(lines)


def apply_model_summary(topic_id: int, *, summary: str, facts: list[str] | None = None,
                        open_loops: list[str] | None = None, task_state: str = "none") -> bool:
    allowed = {"none", "exploring", "planning", "executing", "waiting", "done"}
    state = task_state if task_state in allowed else "none"
    conn = _ensure()
    row = conn.execute("SELECT id FROM memory_working_topics WHERE id=?", (int(topic_id),)).fetchone()
    if not row:
        return False
    now = _now().isoformat(timespec="seconds")
    conn.execute("""UPDATE memory_working_topics SET model_summary=?,model_facts_json=?,open_loops_json=?,
      task_state=?,summary_source='model',summary_updated_at=?,updated_at=? WHERE id=?""", (
        str(summary or "").strip()[:2200], json.dumps([str(item)[:240] for item in (facts or [])[:8]], ensure_ascii=False),
        json.dumps([str(item)[:240] for item in (open_loops or [])[:8]], ensure_ascii=False), state, now, now, int(topic_id)))
    conn.commit()
    return True
