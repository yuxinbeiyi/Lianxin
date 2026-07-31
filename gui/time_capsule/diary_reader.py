"""Read-only access helpers for Time Capsule diary content."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from .database import TimeCapsuleDatabase


def normalize_diary_date(value: str | None, *, today: date | None = None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    current = today or datetime.now().astimezone().date()
    aliases = {
        "今天": current, "今日": current,
        "昨天": current - timedelta(days=1), "昨日": current - timedelta(days=1),
        "前天": current - timedelta(days=2),
    }
    if text in aliases:
        return aliases[text].isoformat()
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", text):
        year, month, day = (int(part) for part in text.split("-"))
        return date(year, month, day).isoformat()
    match = re.fullmatch(r"(\d{1,2})月(\d{1,2})日", text)
    if match:
        return date(current.year, int(match.group(1)), int(match.group(2))).isoformat()
    return text


def infer_diary_date(message: str, *, today: date | None = None) -> str | None:
    text = str(message or "")
    for alias in ("前天", "昨天", "昨日", "今天", "今日"):
        if alias in text:
            return normalize_diary_date(alias, today=today)
    match = re.search(r"(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}月\d{1,2}日)", text)
    return normalize_diary_date(match.group(1), today=today) if match else None


def _format_capsule(capsule: dict) -> str:
    parts = [f"【{capsule.get('date', '')} 的时间胶囊】"]
    if capsule.get("user_content"):
        parts.append(f"主人留下的书页：\n{capsule['user_content']}")
    if capsule.get("lianxin_content"):
        parts.append(f"莲心留下的书页：\n{capsule['lianxin_content']}")
    if capsule.get("traces"):
        parts.append("后来的笔迹：\n" + "\n".join(
            f"- {'莲心' if item.get('author') == 'lianxin' else '主人'}：{item.get('content', '')}"
            for item in capsule["traces"]
        ))
    if capsule.get("collections"):
        parts.append("这一天的附件：\n" + "\n".join(
            f"- {item.get('title') or item.get('kind') or '附件'}"
            for item in capsule["collections"][:12]
        ))
    return "\n\n".join(parts)


def read_diary(*, date_value: str | None = None, keyword: str | None = None,
               limit: int = 1, database: TimeCapsuleDatabase | None = None) -> str:
    store = database or TimeCapsuleDatabase()
    normalized = normalize_diary_date(date_value)
    if normalized:
        capsule = store.read_day(normalized)
        if not capsule or not any((capsule.get("user_content"), capsule.get("lianxin_content"),
                                   capsule.get("traces"), capsule.get("collections"))):
            return f"没有找到 {normalized} 的时间胶囊。"
        return _format_capsule(capsule)
    if keyword:
        results = store.search(str(keyword), limit=max(1, min(20, int(limit or 1))))
        if not results:
            return f"没有找到包含“{keyword}”的时间胶囊。"
        capsules = [store.read_day(item["date"]) for item in results]
        return "找到的共同回忆：\n\n" + "\n\n".join(_format_capsule(item) for item in capsules if item)
    results = store.timeline(limit=max(1, min(10, int(limit or 1))))
    if not results:
        return "时间胶囊还是空的。"
    capsules = [store.read_day(item["date"]) for item in results]
    return "最近的共同回忆：\n\n" + "\n\n".join(_format_capsule(item) for item in capsules if item)


def build_diary_context(message: str, *, limit: int = 3) -> str:
    return read_diary(date_value=infer_diary_date(message), limit=limit)
