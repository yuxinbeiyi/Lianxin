"""Explainable quality and lifecycle signals for long-term memories."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from brain.graph_memory import _get_conn


SOURCE_SCORES = {
    "user_saved": 1.0,
    "user_correction": 1.0,
    "merged": 0.8,
    "auto_extracted": 0.72,
    "migration": 0.55,
}
QUALITY_WEIGHTS = {
    "evidence": 0.40,
    "source": 0.20,
    "strength": 0.15,
    "recency": 0.15,
    "access": 0.10,
}
_QUALITY_LOCK = __import__("threading").RLock()


def _ensure_schema():
    """Initialize graph_memory's schema before quality queries on old databases."""
    return _get_conn()


def _parse_time(value: str, now: datetime) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=now.tzinfo)
    return parsed.astimezone(now.tzinfo)


def _age_days(value: str, now: datetime) -> float:
    parsed = _parse_time(value, now)
    if parsed is None:
        return 365.0
    return max(0.0, (now - parsed).total_seconds() / 86400.0)


def _source_score(source: str) -> float:
    return SOURCE_SCORES.get(str(source or ""), 0.60)


def _fact_quality(fact: dict, fragments: list[dict], relations: list[dict], pending_count: int, now: datetime) -> tuple[float, dict, str, str]:
    if fragments:
        confidences = [
            min(1.0, max(0.0, float(fragment.get("confidence", 0.5))))
            for fragment in fragments
        ]
        confidence = sum(confidences) / len(confidences)
        evidence = min(1.0, confidence * 0.72 + min(len(fragments), 4) / 4.0 * 0.28)
    else:
        evidence = 0.65 if fact.get("source") in {"user_saved", "user_correction"} else 0.30

    strength = min(1.0, max(0.0, float(fact.get("strength", 1) or 1)) / 5.0)
    source = _source_score(fact.get("source", ""))
    age = _age_days(fact.get("updated_at") or fact.get("created_at", ""), now)
    base_horizon = {
        "events": 365.0,
        "knowledge": 730.0,
        "profile": 730.0,
        "preferences": 730.0,
        "behaviors": 540.0,
        "skills": 540.0,
    }.get(fact.get("category"), 540.0)
    emotional_weight = min(1.0, max(0.0, float(fact.get("emotional_weight", 0.5) or 0.5)))
    horizon = base_horizon * (0.65 + emotional_weight * 0.70)
    recency = max(0.10, 1.0 - age / horizon)
    access_count = max(0, int(fact.get("access_count", 0) or 0))
    access = min(1.0, math.log1p(access_count) / math.log(11))
    breakdown = {
        "evidence": round(evidence, 4),
        "source": round(source, 4),
        "strength": round(strength, 4),
        "recency": round(recency, 4),
        "access": round(access, 4),
        "age_days": round(age, 2),
        "evidence_count": len(fragments),
        "relation_count": len(relations),
        "pending_conflicts": pending_count,
        "emotional_weight": round(emotional_weight, 4),
        "decay_horizon_days": round(horizon, 2),
    }
    score = sum(breakdown[key] * weight for key, weight in QUALITY_WEIGHTS.items())
    score = round(min(1.0, max(0.0, score)), 4)
    if pending_count:
        review_status = "needs_confirmation"
    elif any(relation.get("relation") == "contradicts" for relation in relations):
        review_status = "conflicted"
    elif not fragments and fact.get("source") == "auto_extracted":
        review_status = "low_evidence"
    elif score < 0.35:
        review_status = "low_quality"
    elif age > horizon and access_count == 0:
        review_status = "stale"
    else:
        review_status = "normal"
    if fact.get("status") == "retired":
        lifecycle_stage = "retired"
    elif age > horizon * 1.5 and access_count == 0:
        lifecycle_stage = "decaying"
    elif score >= 0.70 and len(fragments) >= 1:
        lifecycle_stage = "stable"
    else:
        lifecycle_stage = "maturing"
    return score, breakdown, review_status, lifecycle_stage


def calculate_memory_quality(fact_id: int, *, now: datetime | None = None) -> dict:
    """Calculate quality without writing it, useful for diagnostics and tests."""
    conn = _ensure_schema()
    row = conn.execute("SELECT * FROM memory_facts WHERE id=?", (int(fact_id),)).fetchone()
    if not row:
        raise ValueError(f"没有找到记忆#{fact_id}")
    fact = dict(row)
    fragments = [dict(item) for item in conn.execute(
        "SELECT * FROM memory_fragments WHERE fact_id=? AND status='active'",
        (int(fact_id),),
    ).fetchall()]
    try:
        from brain.memory_conflicts import get_fact_relations, list_conflict_candidates
        relations = get_fact_relations(int(fact_id))
        pending = len(list_conflict_candidates(status="pending", fact_id=int(fact_id), limit=100))
        pending += len(list_conflict_candidates(status="needs_confirmation", fact_id=int(fact_id), limit=100))
    except Exception:
        relations, pending = [], 0
    current = now or datetime.now().astimezone()
    score, breakdown, review_status, lifecycle_stage = _fact_quality(fact, fragments, relations, pending, current)
    return {
        "fact_id": int(fact_id),
        "content": fact["content"],
        "category": fact["category"],
        "score": score,
        "review_status": review_status,
        "lifecycle_stage": lifecycle_stage,
        "breakdown": breakdown,
    }


def recalculate_memory_quality(
    *, fact_id: int | None = None, limit: int | None = None,
    now: datetime | None = None,
) -> dict:
    """Persist quality scores for active facts and return aggregate statistics."""
    with _QUALITY_LOCK:
        conn = _ensure_schema()
        sql = "SELECT id FROM memory_facts WHERE status='active'"
        params: list = []
        if fact_id is not None:
            sql += " AND id=?"
            params.append(int(fact_id))
        sql += " ORDER BY id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, min(int(limit), 500)))
        ids = [int(row["id"]) for row in conn.execute(sql, params).fetchall()]
        current = now or datetime.now().astimezone()
        updated = []
        for item_id in ids:
            result = calculate_memory_quality(item_id, now=current)
            conn.execute(
                """UPDATE memory_facts SET quality_score=?, review_status=?, lifecycle_stage=?,
                       quality_updated_at=? WHERE id=? AND status='active'""",
                (result["score"], result["review_status"], result["lifecycle_stage"], current.isoformat(timespec="seconds"), item_id),
            )
            updated.append(result)
        conn.commit()
        scores = [item["score"] for item in updated]
        return {
            "updated": len(updated),
            "average_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
            "review_counts": {
                status: sum(item["review_status"] == status for item in updated)
                for status in {item["review_status"] for item in updated}
            },
            "items": updated,
        }


def set_memory_emotional_weight(fact_id: int, weight: float) -> dict:
    conn = _ensure_schema()
    value = min(1.0, max(0.0, float(weight)))
    conn.execute("UPDATE memory_facts SET emotional_weight=?,updated_at=? WHERE id=?", (value, datetime.now().astimezone().isoformat(timespec="seconds"), int(fact_id)))
    conn.commit()
    return calculate_memory_quality(int(fact_id))


def retire_memory(fact_id: int, reason: str = "") -> bool:
    conn = _ensure_schema()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    cur = conn.execute("UPDATE memory_facts SET status='retired',lifecycle_stage='retired',valid_to=?,updated_at=? WHERE id=? AND status='active'", (now, now, int(fact_id)))
    conn.commit()
    return cur.rowcount > 0


def restore_memory(fact_id: int) -> bool:
    conn = _ensure_schema()
    cur = conn.execute("UPDATE memory_facts SET status='active',lifecycle_stage='maturing',valid_to='',updated_at=? WHERE id=? AND status='retired'", (datetime.now().astimezone().isoformat(timespec="seconds"), int(fact_id)))
    conn.commit()
    return cur.rowcount > 0


def record_memory_access(fact_ids: list[int] | tuple[int, ...]) -> int:
    """Record real retrievals; callers should invoke this only after a hit is used."""
    clean = []
    for value in fact_ids or []:
        try:
            item_id = int(value)
        except (TypeError, ValueError):
            continue
        if item_id > 0 and item_id not in clean:
            clean.append(item_id)
    if not clean:
        return 0
    conn = _ensure_schema()
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    conn.executemany(
        """UPDATE memory_facts SET access_count=COALESCE(access_count, 0)+1,
               last_accessed_at=? WHERE id=? AND status='active'""",
        [(timestamp, item_id) for item_id in clean],
    )
    conn.commit()
    return len(clean)


def get_memory_statistics() -> dict:
    conn = _ensure_schema()
    total = conn.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
    active = conn.execute("SELECT COUNT(*) FROM memory_facts WHERE status='active'").fetchone()[0]
    quality = conn.execute(
        "SELECT AVG(quality_score) FROM memory_facts WHERE status='active'"
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT review_status, COUNT(*) AS count FROM memory_facts "
        "WHERE status='active' GROUP BY review_status"
    ).fetchall()
    try:
        from brain.memory_conflicts import list_conflict_candidates
        pending_conflicts = len(list_conflict_candidates(status="pending", limit=100))
        pending_conflicts += len(list_conflict_candidates(status="needs_confirmation", limit=100))
    except Exception:
        pending_conflicts = 0
    return {
        "total_facts": total,
        "active_facts": active,
        "inactive_facts": total - active,
        "average_quality": round(float(quality or 0.0), 4),
        "review_status_counts": {row["review_status"]: row["count"] for row in rows},
        "pending_conflicts": pending_conflicts,
        "lifecycle_stage_counts": {
            row["lifecycle_stage"] or "maturing": row["count"]
            for row in conn.execute("SELECT lifecycle_stage,COUNT(*) AS count FROM memory_facts WHERE status='active' GROUP BY lifecycle_stage").fetchall()
        },
    }


def explain_memory_quality(fact_id: int) -> str:
    result = calculate_memory_quality(fact_id)
    breakdown = result["breakdown"]
    return (
        f"记忆#{result['fact_id']} 质量分 {result['score']:.0%}（{result['review_status']}）\n"
        f"证据 {breakdown['evidence']:.0%} · 来源 {breakdown['source']:.0%} · "
        f"强度 {breakdown['strength']:.0%} · 新鲜度 {breakdown['recency']:.0%} · "
        f"召回 {breakdown['access']:.0%}\n"
        f"证据碎片 {breakdown['evidence_count']} 条 · 关联 {breakdown['relation_count']} 条 · "
        f"待裁决候选 {breakdown['pending_conflicts']} 条"
    )
