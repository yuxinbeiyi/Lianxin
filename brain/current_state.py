"""Time-bounded user state memory with source provenance and audit events."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from functools import wraps

from brain.graph_memory import _get_conn


STATE_TYPES = (
    "health", "emotion", "location", "project",
    "relationship", "plan", "other",
)
SOURCE_QUALITIES = ("direct_statement", "user_confirmed", "inferred")
DEFAULT_DURATION_DAYS = {
    "health": 7,
    "emotion": 3,
    "location": 7,
    "project": 30,
    "relationship": 30,
    "plan": 14,
    "other": 14,
}
MAX_ACTIVE_STATES = 12
MAX_DURATION_DAYS = 90
_state_lock = threading.RLock()


def _serialized(func):
    """Serialize lifecycle mutations shared by desktop and bridge threads."""
    @wraps(func)
    def wrapped(*args, **kwargs):
        with _state_lock:
            return func(*args, **kwargs)
    return wrapped


def _ensure_tables():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memory_current_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            state_type TEXT NOT NULL DEFAULT 'other',
            content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            confidence REAL NOT NULL DEFAULT 0.8,
            source_quality TEXT NOT NULL DEFAULT 'direct_statement',
            valid_from TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            resolved_at TEXT DEFAULT '',
            resolve_reason TEXT DEFAULT '',
            source_session_id INTEGER,
            source_channel TEXT DEFAULT '',
            source_message_ids TEXT NOT NULL DEFAULT '[]',
            persona_id TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memory_state_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            state_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            content TEXT NOT NULL,
            state_type TEXT NOT NULL,
            expires_at TEXT DEFAULT '',
            reason TEXT DEFAULT '',
            source_session_id INTEGER,
            source_channel TEXT DEFAULT '',
            source_message_ids TEXT NOT NULL DEFAULT '[]',
            persona_id TEXT DEFAULT '',
            observed_at TEXT DEFAULT '',
            fingerprint TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_current_states_status
            ON memory_current_states(status);
        CREATE INDEX IF NOT EXISTS idx_current_states_type
            ON memory_current_states(state_type);
        CREATE INDEX IF NOT EXISTS idx_current_states_expiry
            ON memory_current_states(expires_at);
        CREATE INDEX IF NOT EXISTS idx_state_events_state
            ON memory_state_events(state_id);
    """)
    conn.commit()
    return conn


def _local_now(now: datetime | None = None) -> datetime:
    value = now or datetime.now().astimezone()
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return value.astimezone()


def _parse_datetime(value: str, *, now: datetime | None = None) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("时间不能为空")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("时间格式无效，请使用 ISO 8601 或 YYYY-MM-DD HH:MM:SS") from exc
    local_now = _local_now(now)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_now.tzinfo)
    return parsed.astimezone(local_now.tzinfo)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


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


def _normalize_content(content: str) -> str:
    return " ".join(str(content or "").split()).strip()[:500]


def _normalize_type(state_type: str) -> str:
    value = str(state_type or "other").strip().lower()
    return value if value in STATE_TYPES else "other"


def _normalize_quality(source_quality: str) -> str:
    value = str(source_quality or "direct_statement").strip().lower()
    return value if value in SOURCE_QUALITIES else "direct_statement"


def _normalize_confidence(confidence: float, source_quality: str) -> float:
    try:
        value = min(1.0, max(0.0, float(confidence)))
    except (TypeError, ValueError):
        value = 0.8
    cap = 0.6 if source_quality == "inferred" else 0.95
    return min(value, cap)


def _resolve_expiry(
    *,
    expires_at: str = "",
    duration_days: int | None = None,
    state_type: str = "other",
    now: datetime | None = None,
) -> str:
    local_now = _local_now(now)
    max_expiry = local_now + timedelta(days=MAX_DURATION_DAYS)
    if expires_at:
        expiry = _parse_datetime(expires_at, now=local_now)
    else:
        days = duration_days
        if days is None:
            days = DEFAULT_DURATION_DAYS[_normalize_type(state_type)]
        try:
            days = int(days)
        except (TypeError, ValueError) as exc:
            raise ValueError("duration_days 必须是整数") from exc
        if days < 1:
            raise ValueError("duration_days 至少为 1 天")
        expiry = local_now + timedelta(days=min(days, MAX_DURATION_DAYS))
    if expiry <= local_now:
        raise ValueError("过期时间必须晚于当前时间")
    return _iso(min(expiry, max_expiry))


def _row_to_dict(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    try:
        item["source_message_ids"] = json.loads(item.get("source_message_ids") or "[]")
    except (TypeError, json.JSONDecodeError):
        item["source_message_ids"] = []
    return item


def _append_event(
    conn,
    state: dict,
    action: str,
    *,
    reason: str = "",
    source_session_id: int | None = None,
    source_channel: str = "",
    source_message_ids: list[int] | None = None,
    persona_id: str = "",
    observed_at: str = "",
    now: datetime | None = None,
) -> None:
    message_ids_json = _message_ids_json(source_message_ids)
    payload = json.dumps({
        "state_id": state["id"],
        "action": action,
        "content": state["content"],
        "expires_at": state.get("expires_at", ""),
        "message_ids": json.loads(message_ids_json),
        "reason": reason,
    }, sort_keys=True, ensure_ascii=False)
    fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    conn.execute(
        """INSERT INTO memory_state_events (
               state_id, action, content, state_type, expires_at, reason,
               source_session_id, source_channel, source_message_ids,
               persona_id, observed_at, fingerprint, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(fingerprint) DO NOTHING""",
        (
            state["id"], action, state["content"], state["state_type"],
            state.get("expires_at", ""), str(reason or "")[:200],
            source_session_id, str(source_channel or ""), message_ids_json,
            str(persona_id or ""), str(observed_at or ""), fingerprint,
            _iso(_local_now(now)),
        ),
    )


@_serialized
def expire_current_states(*, now: datetime | None = None) -> int:
    conn = _ensure_tables()
    local_now = _local_now(now)
    rows = conn.execute(
        "SELECT * FROM memory_current_states WHERE status='active'"
    ).fetchall()
    expired = 0
    try:
        for row in rows:
            state = _row_to_dict(row)
            try:
                expiry = _parse_datetime(state["expires_at"], now=local_now)
                is_expired = expiry <= local_now
                reason = "有效期已到，系统自动结束"
            except ValueError:
                is_expired = True
                reason = "过期时间无效，系统安全结束"
            if not is_expired:
                continue
            timestamp = _iso(local_now)
            conn.execute(
                """UPDATE memory_current_states
                   SET status='expired', resolved_at=?, resolve_reason=?, updated_at=?
                   WHERE id=? AND status='active'""",
                (timestamp, reason, timestamp, state["id"]),
            )
            state["status"] = "expired"
            _append_event(conn, state, "expire", reason=reason, now=local_now)
            expired += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return expired


@_serialized
def set_current_state(
    content: str,
    state_type: str = "other",
    *,
    expires_at: str = "",
    duration_days: int | None = None,
    confidence: float = 0.9,
    source_quality: str = "direct_statement",
    source_session_id: int | None = None,
    source_channel: str = "",
    source_message_ids: list[int] | None = None,
    persona_id: str = "",
    observed_at: str = "",
    now: datetime | None = None,
) -> dict:
    conn = _ensure_tables()
    local_now = _local_now(now)
    expire_current_states(now=local_now)
    content = _normalize_content(content)
    if not content:
        raise ValueError("状态内容不能为空")
    state_type = _normalize_type(state_type)
    source_quality = _normalize_quality(source_quality)
    confidence = _normalize_confidence(confidence, source_quality)
    expiry = _resolve_expiry(
        expires_at=expires_at, duration_days=duration_days,
        state_type=state_type, now=local_now,
    )

    existing_rows = conn.execute(
        """SELECT * FROM memory_current_states
           WHERE status='active' AND state_type=? ORDER BY id DESC""",
        (state_type,),
    ).fetchall()
    for row in existing_rows:
        existing = _row_to_dict(row)
        similarity = SequenceMatcher(
            None, existing["content"].casefold(), content.casefold()
        ).ratio()
        if similarity >= 0.9:
            _append_event(
                conn, existing, "confirm",
                source_session_id=source_session_id,
                source_channel=source_channel,
                source_message_ids=source_message_ids,
                persona_id=persona_id,
                observed_at=observed_at,
                now=local_now,
            )
            conn.commit()
            existing["operation"] = "duplicate"
            return existing

    active_count = conn.execute(
        "SELECT COUNT(*) FROM memory_current_states WHERE status='active'"
    ).fetchone()[0]
    if active_count >= MAX_ACTIVE_STATES:
        raise ValueError(f"活跃状态已达到上限（{MAX_ACTIVE_STATES} 条），请先结束过时状态")

    timestamp = _iso(local_now)
    message_ids_json = _message_ids_json(source_message_ids)
    try:
        cur = conn.execute(
            """INSERT INTO memory_current_states (
                   state_type, content, status, confidence, source_quality,
                   valid_from, expires_at, source_session_id, source_channel,
                   source_message_ids, persona_id, created_at, updated_at
               ) VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                state_type, content, confidence, source_quality,
                str(observed_at or timestamp), expiry, source_session_id,
                str(source_channel or ""), message_ids_json, str(persona_id or ""),
                timestamp, timestamp,
            ),
        )
        state = _row_to_dict(conn.execute(
            "SELECT * FROM memory_current_states WHERE id=?", (cur.lastrowid,)
        ).fetchone())
        _append_event(
            conn, state, "set",
            source_session_id=source_session_id,
            source_channel=source_channel,
            source_message_ids=source_message_ids,
            persona_id=persona_id,
            observed_at=observed_at,
            now=local_now,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    state["operation"] = "created"
    return state


@_serialized
def update_current_state(
    state_id: int,
    *,
    content: str | None = None,
    state_type: str | None = None,
    expires_at: str = "",
    duration_days: int | None = None,
    source_session_id: int | None = None,
    source_channel: str = "",
    source_message_ids: list[int] | None = None,
    persona_id: str = "",
    observed_at: str = "",
    now: datetime | None = None,
) -> dict:
    conn = _ensure_tables()
    local_now = _local_now(now)
    expire_current_states(now=local_now)
    existing = _row_to_dict(conn.execute(
        "SELECT * FROM memory_current_states WHERE id=? AND status='active'",
        (int(state_id),),
    ).fetchone())
    if not existing:
        raise ValueError(f"没有找到活跃状态#{state_id}")
    if content is None and state_type is None and not expires_at and duration_days is None:
        raise ValueError("update 至少需要修改内容、类型或有效期")

    new_content = existing["content"] if content is None else _normalize_content(content)
    if not new_content:
        raise ValueError("状态内容不能为空")
    new_type = existing["state_type"] if state_type is None else _normalize_type(state_type)
    new_expiry = existing["expires_at"]
    if expires_at or duration_days is not None:
        new_expiry = _resolve_expiry(
            expires_at=expires_at, duration_days=duration_days,
            state_type=new_type, now=local_now,
        )
    timestamp = _iso(local_now)
    # A direct UI/API update may not carry request provenance. In that case keep
    # the original source instead of erasing the audit trail.
    effective_session_id = (
        source_session_id
        if source_session_id is not None
        else existing.get("source_session_id")
    )
    effective_channel = str(source_channel or existing.get("source_channel") or "")
    effective_message_ids = (
        source_message_ids
        if source_message_ids
        else existing.get("source_message_ids") or []
    )
    effective_persona_id = str(persona_id or existing.get("persona_id") or "")
    message_ids_json = _message_ids_json(effective_message_ids)
    try:
        conn.execute(
            """UPDATE memory_current_states
               SET content=?, state_type=?, expires_at=?, source_session_id=?,
                   source_channel=?, source_message_ids=?, persona_id=?, updated_at=?
               WHERE id=? AND status='active'""",
            (
                new_content, new_type, new_expiry, effective_session_id,
                effective_channel, message_ids_json, effective_persona_id,
                timestamp, int(state_id),
            ),
        )
        state = _row_to_dict(conn.execute(
            "SELECT * FROM memory_current_states WHERE id=?", (int(state_id),)
        ).fetchone())
        _append_event(
            conn, state, "update",
            source_session_id=source_session_id,
            source_channel=source_channel,
            source_message_ids=source_message_ids,
            persona_id=persona_id,
            observed_at=observed_at,
            now=local_now,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    state["operation"] = "updated"
    return state


@_serialized
def resolve_current_state(
    state_id: int,
    reason: str,
    *,
    source_session_id: int | None = None,
    source_channel: str = "",
    source_message_ids: list[int] | None = None,
    persona_id: str = "",
    observed_at: str = "",
    now: datetime | None = None,
) -> dict:
    conn = _ensure_tables()
    local_now = _local_now(now)
    expire_current_states(now=local_now)
    state = _row_to_dict(conn.execute(
        "SELECT * FROM memory_current_states WHERE id=? AND status='active'",
        (int(state_id),),
    ).fetchone())
    if not state:
        raise ValueError(f"没有找到活跃状态#{state_id}")
    reason = _normalize_content(reason)[:200]
    if not reason:
        raise ValueError("结束状态时必须说明原因")
    timestamp = _iso(local_now)
    try:
        conn.execute(
            """UPDATE memory_current_states
               SET status='resolved', resolved_at=?, resolve_reason=?, updated_at=?
               WHERE id=? AND status='active'""",
            (timestamp, reason, timestamp, int(state_id)),
        )
        state["status"] = "resolved"
        state["resolved_at"] = timestamp
        state["resolve_reason"] = reason
        _append_event(
            conn, state, "resolve", reason=reason,
            source_session_id=source_session_id,
            source_channel=source_channel,
            source_message_ids=source_message_ids,
            persona_id=persona_id,
            observed_at=observed_at,
            now=local_now,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    state["operation"] = "resolved"
    return state


@_serialized
def list_current_states(
    *, include_inactive: bool = False, now: datetime | None = None
) -> list[dict]:
    conn = _ensure_tables()
    expire_current_states(now=now)
    sql = "SELECT * FROM memory_current_states"
    if not include_inactive:
        sql += " WHERE status='active'"
    sql += " ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, expires_at, id DESC"
    return [_row_to_dict(row) for row in conn.execute(sql).fetchall()]


def get_state_events(state_id: int) -> list[dict]:
    conn = _ensure_tables()
    rows = conn.execute(
        """SELECT * FROM memory_state_events
           WHERE state_id=? ORDER BY id ASC""",
        (int(state_id),),
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def format_current_state_context(*, now: datetime | None = None) -> str:
    states = list_current_states(now=now)
    if not states:
        return ""
    labels = {
        "health": "健康", "emotion": "情绪", "location": "位置",
        "project": "项目", "relationship": "关系", "plan": "计划",
        "other": "其他",
    }
    lines = [
        "【用户当前状态（有时效）】",
        "以下内容只在标注的有效期内成立；过期后不得继续当作当前事实。",
    ]
    for state in states:
        expiry = state["expires_at"].replace("T", " ")[:16]
        lines.append(
            f"- [状态#{state['id']}][{labels.get(state['state_type'], '其他')}] "
            f"{state['content']}（有效至 {expiry}，置信度 {float(state['confidence']):.0%}）"
        )
    lines.append(
        "用户说明状态变化时，调用 update_current_state 更新或结束对应状态；"
        "不要把这些临时状态另存为永久偏好或稳定人格。"
    )
    return "\n".join(lines)
