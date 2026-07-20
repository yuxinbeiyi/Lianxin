"""Narrative memory layers built on top of existing facts and fragments.

Facts/fragments remain the source of truth. Entity profiles, episodes and sagas
are derived records and can be rebuilt without losing the original evidence.
"""
from __future__ import annotations

import hashlib
import json
import threading
import re
from datetime import datetime

from brain.graph_memory import _get_conn

_lock = threading.RLock()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _json(value, default):
    try:
        return json.loads(value or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _ensure_tables():
    conn = _get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS memory_entity_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        entity_type TEXT NOT NULL DEFAULT 'concept',
        summary TEXT DEFAULT '',
        current_status TEXT DEFAULT '',
        confidence REAL NOT NULL DEFAULT 0.5,
        mention_count INTEGER NOT NULL DEFAULT 0,
        source_fact_ids TEXT NOT NULL DEFAULT '[]',
        related_entity_ids TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'active',
        first_seen_at TEXT DEFAULT '',
        last_seen_at TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(name, entity_type)
    );
    CREATE TABLE IF NOT EXISTS memory_episodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        category TEXT DEFAULT 'general',
        entity_ids TEXT NOT NULL DEFAULT '[]',
        fragment_ids TEXT NOT NULL DEFAULT '[]',
        source_fact_ids TEXT NOT NULL DEFAULT '[]',
        confidence REAL NOT NULL DEFAULT 0.5,
        status TEXT NOT NULL DEFAULT 'active',
        occurred_from TEXT DEFAULT '',
        occurred_to TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        fingerprint TEXT NOT NULL UNIQUE
    );
    CREATE TABLE IF NOT EXISTS memory_sagas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        episode_ids TEXT NOT NULL DEFAULT '[]',
        entity_ids TEXT NOT NULL DEFAULT '[]',
        confidence REAL NOT NULL DEFAULT 0.5,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        fingerprint TEXT NOT NULL UNIQUE
    );
    CREATE TABLE IF NOT EXISTS memory_narrative_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        status TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT DEFAULT '',
        candidates INTEGER NOT NULL DEFAULT 0,
        episodes_created INTEGER NOT NULL DEFAULT 0,
        entities_updated INTEGER NOT NULL DEFAULT 0,
        error TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_entity_profiles_status ON memory_entity_profiles(status);
    CREATE INDEX IF NOT EXISTS idx_episodes_status ON memory_episodes(status);
    CREATE INDEX IF NOT EXISTS idx_episodes_updated ON memory_episodes(updated_at);
    CREATE INDEX IF NOT EXISTS idx_sagas_status ON memory_sagas(status);
    """)
    conn.commit()
    return conn


def _episode_fingerprint(title: str, fragment_ids: list[int]) -> str:
    raw = f"{title.strip().lower()}:{','.join(map(str, sorted(set(fragment_ids))))}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def collect_narrative_candidates(limit: int = 36) -> list[dict]:
    """Return evidence not already incorporated into an active episode."""
    conn = _ensure_tables()
    rows = conn.execute(
        """SELECT id, fact_id, content, category, source_session_id,
                  source_channel, source_message_ids, confidence, occurred_at,
                  created_at, updated_at
           FROM memory_fragments WHERE status='active'
           ORDER BY COALESCE(occurred_at, updated_at, created_at) DESC LIMIT 300"""
    ).fetchall()
    used: set[int] = set()
    for row in conn.execute("SELECT fragment_ids FROM memory_episodes WHERE status='active'").fetchall():
        used.update(int(value) for value in _json(row["fragment_ids"], []) if str(value).isdigit())
    candidates = []
    for row in rows:
        if int(row["id"]) in used:
            continue
        item = dict(row)
        item["source_message_ids"] = _json(item.get("source_message_ids"), [])
        candidates.append(item)
        if len(candidates) >= max(1, min(100, int(limit))):
            break
    return candidates


def _upsert_entity(conn, item: dict, source_fact_ids: list[int], timestamp: str) -> int | None:
    name = " ".join(str(item.get("name", "")).split()).strip()[:120]
    if not name:
        return None
    entity_type = str(item.get("entity_type", item.get("type", "concept")) or "concept").strip()[:40]
    row = conn.execute(
        "SELECT * FROM memory_entity_profiles WHERE name=? AND entity_type=?",
        (name, entity_type),
    ).fetchone()
    confidence = min(1.0, max(0.0, float(item.get("confidence", 0.5) or 0.5)))
    summary = str(item.get("summary", "") or "").strip()[:800]
    current_status = str(item.get("current_status", "") or "").strip()[:500]
    existing_ids = _json(row["source_fact_ids"], []) if row else []
    merged_ids = list(dict.fromkeys([int(value) for value in existing_ids + source_fact_ids]))
    if row:
        conn.execute(
            """UPDATE memory_entity_profiles SET summary=?, current_status=?, confidence=?,
               mention_count=mention_count+1, source_fact_ids=?, last_seen_at=?, updated_at=?
               WHERE id=?""",
            (summary or row["summary"], current_status or row["current_status"],
             max(confidence, float(row["confidence"] or 0)), json.dumps(merged_ids),
             timestamp, timestamp, int(row["id"])),
        )
        return int(row["id"])
    cur = conn.execute(
        """INSERT INTO memory_entity_profiles
           (name,entity_type,summary,current_status,confidence,mention_count,
            source_fact_ids,first_seen_at,last_seen_at,created_at,updated_at)
           VALUES (?,?,?,?,?,1,?,?,?,?,?)""",
        (name, entity_type, summary, current_status, confidence,
         json.dumps(merged_ids), timestamp, timestamp, timestamp, timestamp),
    )
    return int(cur.lastrowid)


def apply_narrative_result(result: dict, candidates: list[dict]) -> dict:
    """Validate a model result against candidate IDs before persisting it."""
    conn = _ensure_tables()
    by_id = {int(item["id"]): item for item in candidates}
    created = 0
    entities = 0
    candidate_ids = set(by_id)
    timestamp = _now()
    created_episode_ids: list[int] = []
    with _lock:
        all_fact_ids = sorted({int(item["fact_id"]) for item in candidates})
        for entity in result.get("entities", []) if isinstance(result, dict) else []:
            if isinstance(entity, dict) and _upsert_entity(conn, entity, all_fact_ids, timestamp):
                entities += 1
        for episode in result.get("episodes", []) if isinstance(result, dict) else []:
            if not isinstance(episode, dict):
                continue
            raw_fragments = episode.get("fragment_ids", [])
            fragment_ids = []
            for value in raw_fragments if isinstance(raw_fragments, list) else []:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
                if value in candidate_ids and value not in fragment_ids:
                    fragment_ids.append(value)
            if len(fragment_ids) < 2:
                continue
            title = str(episode.get("title", "未命名经历") or "未命名经历").strip()[:160]
            summary = str(episode.get("summary", "") or "").strip()[:1600]
            if not summary:
                continue
            fingerprint = _episode_fingerprint(title, fragment_ids)
            existing = conn.execute("SELECT id FROM memory_episodes WHERE fingerprint=?", (fingerprint,)).fetchone()
            if existing:
                created_episode_ids.append(int(existing["id"]))
                continue
            source_fact_ids = sorted({int(by_id[item]["fact_id"]) for item in fragment_ids})
            entity_ids = []
            for entity in episode.get("entities", []) if isinstance(episode.get("entities"), list) else []:
                entity_id = _upsert_entity(conn, entity if isinstance(entity, dict) else {"name": entity}, source_fact_ids, timestamp)
                if entity_id and entity_id not in entity_ids:
                    entity_ids.append(entity_id)
                    entities += 1
            confidence = min(1.0, max(0.0, float(episode.get("confidence", 0.6) or 0.6)))
            cur = conn.execute(
                """INSERT INTO memory_episodes
                   (title,summary,category,entity_ids,fragment_ids,source_fact_ids,
                    confidence,occurred_from,occurred_to,created_at,updated_at,fingerprint)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (title, summary, str(episode.get("category", "general"))[:40],
                 json.dumps(entity_ids), json.dumps(fragment_ids), json.dumps(source_fact_ids),
                 confidence, str(episode.get("occurred_from", "") or "")[:40],
                 str(episode.get("occurred_to", "") or "")[:40], timestamp, timestamp, fingerprint),
            )
            created_episode_ids.append(int(cur.lastrowid))
            created += 1

        for saga in result.get("sagas", []) if isinstance(result, dict) else []:
            if not isinstance(saga, dict) or len(created_episode_ids) < 2:
                continue
            raw_indices = saga.get("episode_indices", [])
            episode_ids = []
            for value in raw_indices if isinstance(raw_indices, list) else []:
                try:
                    index = int(value)
                except (TypeError, ValueError):
                    continue
                if 0 <= index < len(created_episode_ids):
                    episode_ids.append(created_episode_ids[index])
            episode_ids = list(dict.fromkeys(episode_ids))
            if len(episode_ids) < 2:
                continue
            title = str(saga.get("title", "未命名记忆弧线") or "未命名记忆弧线").strip()[:160]
            summary = str(saga.get("summary", "") or "").strip()[:1800]
            if not summary:
                continue
            fingerprint = hashlib.sha256(f"{title}:{','.join(map(str, episode_ids))}".encode("utf-8")).hexdigest()
            conn.execute(
                """INSERT OR IGNORE INTO memory_sagas
                   (title,summary,episode_ids,confidence,created_at,updated_at,fingerprint)
                   VALUES (?,?,?,?,?,?,?)""",
                (title, summary, json.dumps(episode_ids),
                 min(1.0, max(0.0, float(saga.get("confidence", 0.6) or 0.6))),
                 timestamp, timestamp, fingerprint),
            )
        conn.commit()
    return {"episodes_created": created, "entities_updated": entities, "episode_ids": created_episode_ids}


def list_entity_profiles(limit: int = 200) -> list[dict]:
    rows = _ensure_tables().execute(
        "SELECT * FROM memory_entity_profiles WHERE status='active' ORDER BY mention_count DESC,id DESC LIMIT ?",
        (max(1, min(500, int(limit))),),
    ).fetchall()
    return [dict(row) for row in rows]


def list_episodes(limit: int = 200) -> list[dict]:
    rows = _ensure_tables().execute(
        "SELECT * FROM memory_episodes WHERE status='active' ORDER BY updated_at DESC,id DESC LIMIT ?",
        (max(1, min(500, int(limit))),),
    ).fetchall()
    return [dict(row) for row in rows]


def list_sagas(limit: int = 100) -> list[dict]:
    rows = _ensure_tables().execute(
        "SELECT * FROM memory_sagas WHERE status='active' ORDER BY updated_at DESC,id DESC LIMIT ?",
        (max(1, min(200, int(limit))),),
    ).fetchall()
    return [dict(row) for row in rows]


def get_narrative_context(query: str, limit: int = 4) -> list[dict]:
    """Lightweight lexical narrative lookup used as one hybrid-search channel."""
    terms = []
    text = " ".join(str(query or "").lower().split())
    for term in re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", text):
        terms.append(term)
        if re.fullmatch(r"[\u4e00-\u9fff]+", term) and len(term) > 2:
            terms.extend(term[index:index + 2] for index in range(len(term) - 1))
    if not terms:
        return []
    rows = list_episodes(300)
    scored = []
    for row in rows:
        haystack = f"{row.get('title','')} {row.get('summary','')}".lower()
        hits = sum(haystack.count(term) for term in terms)
        if hits:
            scored.append((hits / max(1, len(terms)), row))
    scored.sort(key=lambda item: (item[0], item[1].get("updated_at", "")), reverse=True)
    return [{**row, "narrative_score": score, "source_table": "memory_episodes"}
            for score, row in scored[:max(1, min(20, int(limit)))]]


def get_entity_context(query: str, limit: int = 8) -> list[dict]:
    """Aggregate an entity profile and its connected episodes for entity queries."""
    text = " ".join(str(query or "").lower().split())
    if not text:
        return []
    rows = list_entity_profiles(300)
    output = []
    for row in rows:
        name = str(row.get("name", "")).lower()
        summary = f"{row.get('summary', '')} {row.get('current_status', '')}".lower()
        if name not in text and not any(term in summary for term in text.split() if len(term) > 1):
            continue
        output.append({**row, "narrative_score": 1.0 if name in text else 0.45,
                       "source_table": "memory_entity_profiles"})
    output.sort(key=lambda item: (item["narrative_score"], item.get("mention_count", 0)), reverse=True)
    return output[:max(1, min(30, int(limit)))]


def get_narrative_statistics() -> dict:
    conn = _ensure_tables()
    return {
        "entities": conn.execute("SELECT COUNT(*) FROM memory_entity_profiles WHERE status='active'").fetchone()[0],
        "episodes": conn.execute("SELECT COUNT(*) FROM memory_episodes WHERE status='active'").fetchone()[0],
        "sagas": conn.execute("SELECT COUNT(*) FROM memory_sagas WHERE status='active'").fetchone()[0],
    }


def merge_narrative_duplicates(limit: int = 100) -> dict:
    """Merge adjacent derived records while preserving all source IDs."""
    conn = _ensure_tables()
    merged_episodes = 0
    merged_sagas = 0

    def overlap(left: str, right: str) -> float:
        a = {token for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", left.lower())}
        b = {token for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", right.lower())}
        return len(a & b) / max(1, len(a | b))

    episodes = list_episodes(limit)
    for index, survivor in enumerate(episodes):
        if survivor.get("status") != "active":
            continue
        survivor_entities = _json(survivor.get("entity_ids"), [])
        survivor_fragments = _json(survivor.get("fragment_ids"), [])
        survivor_facts = _json(survivor.get("source_fact_ids"), [])
        for duplicate in episodes[index + 1:]:
            if duplicate.get("status") != "active" or duplicate.get("category") != survivor.get("category"):
                continue
            duplicate_entities = _json(duplicate.get("entity_ids"), [])
            same_entity = bool(set(survivor_entities) & set(duplicate_entities))
            if not same_entity and overlap(survivor.get("title", ""), duplicate.get("title", "")) < 0.55:
                continue
            fragments = list(dict.fromkeys(survivor_fragments + _json(duplicate.get("fragment_ids"), [])))
            facts = list(dict.fromkeys(survivor_facts + _json(duplicate.get("source_fact_ids"), [])))
            entities = list(dict.fromkeys(survivor_entities + duplicate_entities))
            summary = survivor.get("summary", "")
            if duplicate.get("summary") and duplicate["summary"] not in summary:
                summary = (summary + "\n" + duplicate["summary"])[:1800]
            conn.execute(
                """UPDATE memory_episodes SET summary=?,entity_ids=?,fragment_ids=?,source_fact_ids=?,
                   confidence=MAX(confidence,?),updated_at=? WHERE id=?""",
                (summary, json.dumps(entities), json.dumps(fragments), json.dumps(facts),
                 float(duplicate.get("confidence", 0.5) or 0.5), _now(), int(survivor["id"])),
            )
            conn.execute("UPDATE memory_episodes SET status='merged',updated_at=? WHERE id=?", (_now(), int(duplicate["id"])))
            for saga_row in conn.execute("SELECT id,episode_ids FROM memory_sagas WHERE status='active'").fetchall():
                saga_episode_ids = _json(saga_row["episode_ids"], [])
                if int(duplicate["id"]) not in saga_episode_ids:
                    continue
                saga_episode_ids = [
                    int(survivor["id"]) if int(value) == int(duplicate["id"]) else int(value)
                    for value in saga_episode_ids
                ]
                conn.execute(
                    "UPDATE memory_sagas SET episode_ids=?,updated_at=? WHERE id=?",
                    (json.dumps(list(dict.fromkeys(saga_episode_ids))), _now(), int(saga_row["id"])),
                )
            survivor_fragments, survivor_facts, survivor_entities = fragments, facts, entities
            duplicate["status"] = "merged"
            merged_episodes += 1

    sagas = list_sagas(limit)
    for index, survivor in enumerate(sagas):
        if survivor.get("status") != "active":
            continue
        for duplicate in sagas[index + 1:]:
            if duplicate.get("status") != "active" or overlap(survivor.get("title", ""), duplicate.get("title", "")) < 0.55:
                continue
            episode_ids = list(dict.fromkeys(_json(survivor.get("episode_ids"), []) + _json(duplicate.get("episode_ids"), [])))
            summary = survivor.get("summary", "")
            if duplicate.get("summary") and duplicate["summary"] not in summary:
                summary = (summary + "\n" + duplicate["summary"])[:2000]
            conn.execute("UPDATE memory_sagas SET summary=?,episode_ids=?,updated_at=? WHERE id=?", (summary, json.dumps(episode_ids), _now(), int(survivor["id"])))
            conn.execute("UPDATE memory_sagas SET status='merged',updated_at=? WHERE id=?", (_now(), int(duplicate["id"])))
            duplicate["status"] = "merged"
            merged_sagas += 1
    conn.commit()
    return {"episodes_merged": merged_episodes, "sagas_merged": merged_sagas}


def start_narrative_run(candidates: int) -> int:
    conn = _ensure_tables()
    cur = conn.execute(
        "INSERT INTO memory_narrative_runs(status,started_at,candidates) VALUES('running',?,?)",
        (_now(), max(0, int(candidates))),
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_narrative_run(run_id: int, *, status: str, episodes_created: int = 0,
                         entities_updated: int = 0, error: str = "") -> None:
    conn = _ensure_tables()
    conn.execute(
        """UPDATE memory_narrative_runs SET status=?,finished_at=?,episodes_created=?,
           entities_updated=?,error=? WHERE id=?""",
        (str(status), _now(), max(0, int(episodes_created)), max(0, int(entities_updated)),
         str(error or "")[:1000], int(run_id)),
    )
    conn.commit()


def get_last_narrative_run() -> dict | None:
    row = _ensure_tables().execute(
        "SELECT * FROM memory_narrative_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def should_run_narrative(interval_hours: float = 12.0) -> bool:
    last = get_last_narrative_run()
    if not last or last.get("status") != "success":
        return True
    try:
        previous = datetime.fromisoformat(last.get("finished_at", ""))
        return (datetime.now().astimezone() - previous.astimezone()).total_seconds() >= max(1.0, float(interval_hours) * 3600)
    except (TypeError, ValueError):
        return True
