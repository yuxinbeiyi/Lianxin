"""Semantic conflict candidates and audited fact reconciliation.

Code discovers potentially related facts.  A model (or an explicit user action)
must decide their semantic relationship before any destructive state transition.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from difflib import SequenceMatcher

from brain.graph_memory import _get_conn


DECISIONS = ("duplicate", "complements", "contradicts", "supersedes", "unrelated")
DESTRUCTIVE_DECISIONS = {"duplicate", "supersedes"}
AUTO_APPLY_CONFIDENCE = 0.8
CANDIDATE_THRESHOLD = 0.62
_lock = threading.RLock()


def _ensure_tables():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memory_conflict_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            existing_fact_id INTEGER NOT NULL,
            new_fact_id INTEGER NOT NULL,
            similarity REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            decision TEXT DEFAULT '',
            decision_confidence REAL NOT NULL DEFAULT 0,
            rationale TEXT DEFAULT '',
            review_model TEXT DEFAULT '',
            source_session_id INTEGER,
            source_channel TEXT DEFAULT '',
            source_message_ids TEXT NOT NULL DEFAULT '[]',
            persona_id TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            reviewed_at TEXT DEFAULT '',
            UNIQUE(existing_fact_id, new_fact_id)
        );
        CREATE TABLE IF NOT EXISTS memory_fact_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_fact_id INTEGER NOT NULL,
            target_fact_id INTEGER NOT NULL,
            relation TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0,
            rationale TEXT DEFAULT '',
            candidate_id INTEGER,
            created_at TEXT NOT NULL,
            UNIQUE(source_fact_id, target_fact_id, relation)
        );
        CREATE TABLE IF NOT EXISTS memory_conflict_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            decision TEXT NOT NULL,
            confidence REAL NOT NULL,
            rationale TEXT NOT NULL,
            applied INTEGER NOT NULL DEFAULT 0,
            review_model TEXT DEFAULT '',
            source_session_id INTEGER,
            source_channel TEXT DEFAULT '',
            source_message_ids TEXT NOT NULL DEFAULT '[]',
            persona_id TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_memory_conflict_status
            ON memory_conflict_candidates(status);
        CREATE INDEX IF NOT EXISTS idx_memory_conflict_existing
            ON memory_conflict_candidates(existing_fact_id);
        CREATE INDEX IF NOT EXISTS idx_memory_conflict_new
            ON memory_conflict_candidates(new_fact_id);
        CREATE INDEX IF NOT EXISTS idx_memory_fact_rel_source
            ON memory_fact_relations(source_fact_id);
        CREATE INDEX IF NOT EXISTS idx_memory_fact_rel_target
            ON memory_fact_relations(target_fact_id);
        CREATE INDEX IF NOT EXISTS idx_memory_conflict_events_candidate
            ON memory_conflict_events(candidate_id);
    """)
    conn.commit()
    return conn


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _compare_text(content: str) -> str:
    text = re.sub(r"【记录于\d{4}-\d{2}-\d{2}】", "", str(content or ""))
    return "".join(text.casefold().split())


def _message_ids_json(values: list[int] | None) -> str:
    clean = []
    for value in values or []:
        try:
            message_id = int(value)
        except (TypeError, ValueError):
            continue
        if message_id > 0 and message_id not in clean:
            clean.append(message_id)
    return json.dumps(clean, ensure_ascii=False)


def _candidate_to_dict(row) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    try:
        result["source_message_ids"] = json.loads(
            result.get("source_message_ids") or "[]"
        )
    except (TypeError, json.JSONDecodeError):
        result["source_message_ids"] = []
    return result


def record_conflict_candidates(
    new_fact_id: int,
    *,
    threshold: float = CANDIDATE_THRESHOLD,
    limit: int = 3,
) -> list[dict]:
    """Record likely-related active facts without deciding their relationship."""
    with _lock:
        conn = _ensure_tables()
        new_fact = conn.execute(
            "SELECT id, content, category FROM memory_facts WHERE id=? AND status='active'",
            (int(new_fact_id),),
        ).fetchone()
        if not new_fact:
            return []

        scores: dict[int, float] = {}
        try:
            from brain.memory_rag import search_similar
            related = search_similar(
                new_fact["content"], top_k=max(limit * 3, 8),
                threshold=max(0.5, threshold - 0.08), category=new_fact["category"],
                track_access=False,
            )
            for _combined, item in related:
                fact_id = int(item.get("memory_id", 0))
                if fact_id and fact_id != int(new_fact_id):
                    scores[fact_id] = max(
                        scores.get(fact_id, 0.0),
                        float(item.get("semantic_similarity", 0.0)),
                    )
        except Exception:
            pass

        # Lexical fallback keeps candidate discovery functional when embeddings
        # are unavailable. It only proposes; it never performs a semantic action.
        normalized_new = _compare_text(new_fact["content"])
        rows = conn.execute(
            """SELECT id, content FROM memory_facts
               WHERE category=? AND status='active' AND id<>?""",
            (new_fact["category"], int(new_fact_id)),
        ).fetchall()
        for row in rows:
            lexical = SequenceMatcher(
                None, normalized_new, _compare_text(row["content"])
            ).ratio()
            if lexical >= threshold:
                scores[int(row["id"])] = max(scores.get(int(row["id"]), 0.0), lexical)

        ranked = sorted(
            ((fact_id, score) for fact_id, score in scores.items() if score >= threshold),
            key=lambda item: item[1], reverse=True,
        )[:max(1, min(int(limit), 10))]
        timestamp = _now()
        for existing_fact_id, similarity in ranked:
            conn.execute(
                """INSERT INTO memory_conflict_candidates (
                       existing_fact_id, new_fact_id, similarity, status, created_at
                   ) VALUES (?, ?, ?, 'pending', ?)
                   ON CONFLICT(existing_fact_id, new_fact_id) DO UPDATE SET
                       similarity=MAX(similarity, excluded.similarity)""",
                (existing_fact_id, int(new_fact_id), float(similarity), timestamp),
            )
        conn.commit()
        return list_conflict_candidates(status="pending", fact_id=int(new_fact_id), limit=limit)


def list_conflict_candidates(
    *, status: str = "pending", fact_id: int | None = None, limit: int = 20
) -> list[dict]:
    conn = _ensure_tables()
    sql = """SELECT c.*, old.content AS existing_content,
                    old.category AS category, old.status AS existing_status,
                    new.content AS new_content, new.status AS new_status
             FROM memory_conflict_candidates c
             JOIN memory_facts old ON old.id=c.existing_fact_id
             JOIN memory_facts new ON new.id=c.new_fact_id WHERE 1=1"""
    params: list = []
    if status and status != "all":
        sql += " AND c.status=?"
        params.append(status)
    if fact_id is not None:
        sql += " AND (c.existing_fact_id=? OR c.new_fact_id=?)"
        params.extend([int(fact_id), int(fact_id)])
    sql += " ORDER BY c.id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 100)))
    return [_candidate_to_dict(row) for row in conn.execute(sql, params).fetchall()]


def get_conflict_candidate(candidate_id: int) -> dict | None:
    row = _ensure_tables().execute(
        """SELECT c.*, old.content AS existing_content,
                  old.category AS category, old.status AS existing_status,
                  new.content AS new_content, new.status AS new_status
           FROM memory_conflict_candidates c
           JOIN memory_facts old ON old.id=c.existing_fact_id
           JOIN memory_facts new ON new.id=c.new_fact_id
           WHERE c.id=?""",
        (int(candidate_id),),
    ).fetchone()
    return _candidate_to_dict(row)


def get_fact_relations(fact_id: int) -> list[dict]:
    rows = _ensure_tables().execute(
        """SELECT r.*, source.content AS source_content,
                  target.content AS target_content
           FROM memory_fact_relations r
           JOIN memory_facts source ON source.id=r.source_fact_id
           JOIN memory_facts target ON target.id=r.target_fact_id
           WHERE r.source_fact_id=? OR r.target_fact_id=?
           ORDER BY r.id DESC""",
        (int(fact_id), int(fact_id)),
    ).fetchall()
    return [dict(row) for row in rows]


def get_conflict_events(candidate_id: int) -> list[dict]:
    rows = _ensure_tables().execute(
        """SELECT * FROM memory_conflict_events
           WHERE candidate_id=? ORDER BY id ASC""",
        (int(candidate_id),),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["source_message_ids"] = json.loads(
                item.get("source_message_ids") or "[]"
            )
        except (TypeError, json.JSONDecodeError):
            item["source_message_ids"] = []
        item["applied"] = bool(item.get("applied"))
        result.append(item)
    return result


def resolve_conflict_candidate(
    candidate_id: int,
    decision: str,
    *,
    confidence: float,
    rationale: str,
    review_model: str = "",
    source_session_id: int | None = None,
    source_channel: str = "",
    source_message_ids: list[int] | None = None,
    persona_id: str = "",
) -> dict:
    """Apply a semantic decision with guarded destructive transitions."""
    decision = str(decision or "").strip().lower()
    if decision not in DECISIONS:
        raise ValueError("decision 必须是 duplicate、complements、contradicts、supersedes 或 unrelated")
    try:
        confidence = min(1.0, max(0.0, float(confidence)))
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence 必须是 0 到 1 之间的数字") from exc
    rationale = " ".join(str(rationale or "").split()).strip()[:500]
    if not rationale:
        raise ValueError("语义裁决必须提供 rationale")

    with _lock:
        conn = _ensure_tables()
        candidate = get_conflict_candidate(int(candidate_id))
        if not candidate:
            raise ValueError(f"没有找到冲突候选 #{candidate_id}")
        if candidate["status"] not in {"pending", "needs_confirmation"}:
            raise ValueError(f"冲突候选 #{candidate_id} 已经完成裁决")
        if candidate["existing_status"] != "active" or candidate["new_status"] != "active":
            raise ValueError("候选事实已不再同时有效，请刷新候选后重试")

        timestamp = _now()
        candidate_status = "resolved"
        if decision in DESTRUCTIVE_DECISIONS and confidence < AUTO_APPLY_CONFIDENCE:
            candidate_status = "needs_confirmation"

        try:
            if candidate_status == "resolved" and decision == "duplicate":
                conn.execute(
                    """UPDATE memory_facts SET
                           strength=strength + COALESCE((SELECT strength FROM memory_facts WHERE id=?), 1),
                           updated_at=datetime('now','localtime') WHERE id=?""",
                    (candidate["new_fact_id"], candidate["existing_fact_id"]),
                )
                conn.execute(
                    "UPDATE memory_fragments SET fact_id=? WHERE fact_id=?",
                    (candidate["existing_fact_id"], candidate["new_fact_id"]),
                )
                conn.execute(
                    """UPDATE memory_facts SET status='duplicate', valid_to=?,
                           updated_at=datetime('now','localtime') WHERE id=?""",
                    (timestamp, candidate["new_fact_id"]),
                )
            elif candidate_status == "resolved" and decision == "supersedes":
                conn.execute(
                    """UPDATE memory_facts SET status='superseded', valid_to=?,
                           updated_at=datetime('now','localtime') WHERE id=?""",
                    (timestamp, candidate["existing_fact_id"]),
                )
                conn.execute(
                    """UPDATE memory_fragments SET status='superseded',
                           updated_at=datetime('now','localtime')
                       WHERE fact_id=? AND status='active'""",
                    (candidate["existing_fact_id"],),
                )
                conn.execute(
                    """UPDATE memory_facts SET valid_from=CASE
                           WHEN valid_from='' THEN COALESCE(NULLIF(occurred_at,''), ?) ELSE valid_from END
                       WHERE id=?""",
                    (timestamp, candidate["new_fact_id"]),
                )

            if candidate_status == "resolved" and decision != "unrelated":
                conn.execute(
                    """INSERT INTO memory_fact_relations (
                           source_fact_id, target_fact_id, relation, confidence,
                           rationale, candidate_id, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(source_fact_id, target_fact_id, relation) DO UPDATE SET
                           confidence=MAX(confidence, excluded.confidence),
                           rationale=excluded.rationale, candidate_id=excluded.candidate_id""",
                    (
                        candidate["new_fact_id"], candidate["existing_fact_id"],
                        decision, confidence, rationale, int(candidate_id), timestamp,
                    ),
                )

            message_ids_json = _message_ids_json(source_message_ids)
            conn.execute(
                """INSERT INTO memory_conflict_events (
                       candidate_id, decision, confidence, rationale, applied,
                       review_model, source_session_id, source_channel,
                       source_message_ids, persona_id, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(candidate_id), decision, confidence, rationale,
                    1 if candidate_status == "resolved" else 0,
                    str(review_model or ""), source_session_id,
                    str(source_channel or ""), message_ids_json,
                    str(persona_id or ""), timestamp,
                ),
            )
            conn.execute(
                """UPDATE memory_conflict_candidates SET
                       status=?, decision=?, decision_confidence=?, rationale=?,
                       review_model=?, source_session_id=?, source_channel=?,
                       source_message_ids=?, persona_id=?, reviewed_at=?
                   WHERE id=?""",
                (
                    candidate_status, decision, confidence, rationale,
                    str(review_model or ""), source_session_id,
                    str(source_channel or ""), message_ids_json,
                    str(persona_id or ""), timestamp, int(candidate_id),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        result = get_conflict_candidate(int(candidate_id))
        result["applied"] = candidate_status == "resolved"
        return result


def format_candidate_list(candidates: list[dict]) -> str:
    if not candidates:
        return "当前没有等待语义裁决的长期记忆候选。"
    lines = ["等待语义裁决的长期记忆候选："]
    for item in candidates:
        review_note = " · 需要用户确认" if item.get("status") == "needs_confirmation" else ""
        lines.append(
            f"- 候选#{item['id']}（相似度 {float(item['similarity']):.0%}{review_note}）\n"
            f"  旧记忆#{item['existing_fact_id']}：{item['existing_content']}\n"
            f"  新记忆#{item['new_fact_id']}：{item['new_content']}"
        )
    lines.append(
        "请根据语义选择 duplicate、complements、contradicts、supersedes 或 unrelated；"
        "不要仅凭相似度裁决。"
    )
    return "\n".join(lines)
