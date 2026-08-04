"""浏览器任务结构化审计日志。

日志采用脱敏 JSONL，便于人工排查和后续调试面板读取。写入失败不会影响
浏览器任务本身；单文件超过上限时自动轮换，避免长期运行无限增长。
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "browser_tasks.jsonl"
MAX_LOG_BYTES = 5 * 1024 * 1024
MAX_ROTATED_FILES = 3
_LOCK = threading.Lock()


def _rotate_if_needed() -> None:
    try:
        if not LOG_PATH.exists() or LOG_PATH.stat().st_size < MAX_LOG_BYTES:
            return
        for index in range(MAX_ROTATED_FILES, 0, -1):
            src = LOG_PATH.with_name(f"{LOG_PATH.name}.{index}")
            if index == MAX_ROTATED_FILES and src.exists():
                src.unlink(missing_ok=True)
            elif src.exists():
                src.rename(LOG_PATH.with_name(f"{LOG_PATH.name}.{index + 1}"))
        LOG_PATH.rename(LOG_PATH.with_name(f"{LOG_PATH.name}.1"))
    except Exception:
        pass


def append_event(event: dict[str, Any]) -> None:
    """写入一条结构化事件。调用方应在写入前完成敏感字段脱敏。"""
    try:
        safe = dict(event or {})
        safe.setdefault("schema_version", 1)
        safe.setdefault("timestamp", datetime.now().isoformat(timespec="milliseconds"))
        safe.setdefault("task_id", "")
        safe.setdefault("event", "step")
        safe["redacted"] = True
        # 限制日志中可能被误传入的长文本字段。
        for key in ("result", "result_preview", "error", "reason"):
            if key in safe and safe[key] is not None:
                safe[key] = str(safe[key])[:2000]
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            _rotate_if_needed()
            with LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(safe, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_recent(limit: int = 100, task_id: str = "") -> list[dict[str, Any]]:
    """读取最近的脱敏事件，返回时间正序列表。"""
    try:
        limit = max(1, min(1000, int(limit)))
    except (TypeError, ValueError):
        limit = 100
    rows: list[dict[str, Any]] = []
    try:
        if not LOG_PATH.exists():
            return rows
        with LOG_PATH.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle.readlines()[-limit * 3:]:
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if task_id and str(item.get("task_id", "")) != str(task_id):
                    continue
                rows.append(item)
        return rows[-limit:]
    except Exception:
        return rows


def latest_task(task_id: str = "") -> dict[str, Any]:
    rows = read_recent(500, task_id=task_id)
    if not rows:
        return {"task_id": task_id, "status": "idle", "steps": []}
    selected = str(task_id or rows[-1].get("task_id", ""))
    task_rows = [row for row in rows if str(row.get("task_id", "")) == selected]
    steps = [row for row in task_rows if row.get("event") == "step"]
    status = "running"
    for row in reversed(task_rows):
        if row.get("event") in {
            "completed", "cancelled", "failed", "stopped", "action_limit", "timed_out",
        }:
            status = str(row.get("status") or row.get("event"))
            break
    return {
        "task_id": selected,
        "status": status,
        "steps": steps[-100:],
        "events": task_rows[-100:],
    }
