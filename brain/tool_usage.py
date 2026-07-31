"""Persistent, privacy-conscious tool usage events and aggregates."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from utils.paths import get_user_data_dir


SUCCESS_STATUSES = {"success", "cached"}
VALID_STATUSES = SUCCESS_STATUSES | {"failure", "blocked", "cancelled"}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def classify_tool_result(result: object, *, failed: bool = False) -> str:
    if failed:
        return "failure"
    text = str(result or "").strip()
    lowered = text.lower()
    if text.startswith(("[取消]", "[CANCELLED]")) or "工作流已取消" in text:
        return "cancelled"
    if text.startswith(("[拒绝]", "[REJECTED]")) or "已阻止" in text[:100]:
        return "blocked"
    if (
        text.startswith(("[ERROR]", "错误", "工具执行错误", "未知工具", "参数错误"))
        or "失败" in text[:100]
        or lowered.startswith("error")
    ):
        return "failure"
    return "success"


@dataclass(frozen=True)
class ToolUsageSummary:
    tool_name: str
    call_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    blocked_count: int = 0
    cancelled_count: int = 0
    cached_count: int = 0
    total_duration_ms: float = 0.0
    last_called: str = ""

    @property
    def success_rate(self) -> float:
        return self.success_count / self.call_count if self.call_count else 0.0

    @property
    def avg_duration_ms(self) -> float:
        return self.total_duration_ms / self.call_count if self.call_count else 0.0


class ToolUsageStore:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path or (get_user_data_dir() / "tool_usage.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _ensure_schema(self) -> None:
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tool_usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_name TEXT NOT NULL,
                    source_kind TEXT NOT NULL DEFAULT 'builtin',
                    provider_id TEXT NOT NULL DEFAULT 'lianxin',
                    invocation_mode TEXT NOT NULL DEFAULT 'auto',
                    status TEXT NOT NULL,
                    duration_ms REAL NOT NULL DEFAULT 0,
                    session_id INTEGER,
                    workflow_run_id INTEGER,
                    channel TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tool_usage_name_time
                    ON tool_usage_events(tool_name, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_tool_usage_status_time
                    ON tool_usage_events(status, created_at DESC);
            """)
        finally:
            conn.close()

    def record(self, tool_name: str, *, status: str, duration_ms: float = 0.0,
               source_kind: str = "builtin", provider_id: str = "lianxin",
               invocation_mode: str = "auto", session_id: int | None = None,
               workflow_run_id: int | None = None, channel: str = "") -> None:
        normalized_status = status if status in VALID_STATUSES else "failure"
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO tool_usage_events
                   (tool_name,source_kind,provider_id,invocation_mode,status,duration_ms,
                    session_id,workflow_run_id,channel,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (str(tool_name), str(source_kind), str(provider_id), str(invocation_mode),
                 normalized_status, max(0.0, float(duration_ms or 0)), session_id,
                 workflow_run_id, str(channel or ""), _now()),
            )
        finally:
            conn.close()

    def summaries(self, tool_names: Iterable[str] = (), *, days: int | None = None
                  ) -> dict[str, ToolUsageSummary]:
        filters: list[str] = []
        params: list[object] = []
        names = list(dict.fromkeys(str(name) for name in tool_names if name))
        if names:
            filters.append("tool_name IN (%s)" % ",".join("?" for _ in names))
            params.extend(names)
        if days is not None:
            cutoff = datetime.now(timezone.utc).astimezone() - timedelta(days=max(0, int(days)))
            filters.append("created_at >= ?")
            params.append(cutoff.isoformat(timespec="seconds"))
        where = " WHERE " + " AND ".join(filters) if filters else ""
        conn = self._connect()
        try:
            rows = conn.execute(
                f"""SELECT tool_name, COUNT(*) AS call_count,
                    SUM(CASE WHEN status IN ('success','cached') THEN 1 ELSE 0 END) success_count,
                    SUM(CASE WHEN status='failure' THEN 1 ELSE 0 END) failure_count,
                    SUM(CASE WHEN status='blocked' THEN 1 ELSE 0 END) blocked_count,
                    SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END) cancelled_count,
                    SUM(CASE WHEN status='cached' THEN 1 ELSE 0 END) cached_count,
                    SUM(duration_ms) total_duration_ms, MAX(created_at) last_called
                    FROM tool_usage_events{where} GROUP BY tool_name""",
                params,
            ).fetchall()
        finally:
            conn.close()
        result = {
            row["tool_name"]: ToolUsageSummary(
                tool_name=row["tool_name"], call_count=int(row["call_count"] or 0),
                success_count=int(row["success_count"] or 0),
                failure_count=int(row["failure_count"] or 0),
                blocked_count=int(row["blocked_count"] or 0),
                cancelled_count=int(row["cancelled_count"] or 0),
                cached_count=int(row["cached_count"] or 0),
                total_duration_ms=float(row["total_duration_ms"] or 0),
                last_called=str(row["last_called"] or ""),
            ) for row in rows
        }
        for name in names:
            result.setdefault(name, ToolUsageSummary(name))
        return result

    def overview(self, *, days: int | None = None) -> dict:
        summaries = list(self.summaries(days=days).values())
        calls = sum(item.call_count for item in summaries)
        successes = sum(item.success_count for item in summaries)
        return {
            "call_count": calls,
            "success_count": successes,
            "success_rate": successes / calls if calls else 0.0,
            "avg_duration_ms": (
                sum(item.total_duration_ms for item in summaries) / calls if calls else 0.0
            ),
            "used_tool_count": sum(1 for item in summaries if item.call_count),
        }

    def recent_tool_names(self, limit: int = 12) -> list[str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT tool_name, MAX(created_at) last_called FROM tool_usage_events
                   GROUP BY tool_name ORDER BY last_called DESC LIMIT ?""",
                (max(1, int(limit)),),
            ).fetchall()
        finally:
            conn.close()
        return [str(row["tool_name"]) for row in rows]

    def reset(self) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM tool_usage_events")
        finally:
            conn.close()


_store: ToolUsageStore | None = None


def get_tool_usage_store() -> ToolUsageStore:
    global _store
    if _store is None:
        _store = ToolUsageStore()
    return _store

