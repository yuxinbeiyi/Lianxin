"""Runtime truth source for Lianxin's self-knowledge about capabilities.

The UI and the model both read ``brain.capability_catalog``.  This module adds
a compact, cached and tool-friendly projection; it never owns availability or
permission state itself.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass

from brain.capability_catalog import CapabilityDescriptor, list_capabilities


_CACHE_TTL_SECONDS = 15.0
_cache_lock = threading.RLock()
_cached_index: "CapabilityIndex | None" = None
_cached_at = 0.0


@dataclass(frozen=True)
class CapabilityIndex:
    version: str
    total: int
    available: int
    categories: tuple[str, ...]


def _status(item: CapabilityDescriptor) -> str:
    if item.enabled and item.available:
        return "可直接使用"
    if not item.enabled:
        return "已停用，需要先在能力中枢启用"
    return "当前不可用"


def _version(items: list[CapabilityDescriptor]) -> str:
    payload = "\n".join(
        f"{item.name}|{item.enabled}|{item.available}|{item.category}|{item.version}"
        for item in items
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def invalidate_capability_knowledge_cache() -> None:
    """Call after a capability source is enabled, disabled or refreshed."""
    global _cached_index, _cached_at
    with _cache_lock:
        _cached_index = None
        _cached_at = 0.0


def get_capability_index(*, force_refresh: bool = False) -> CapabilityIndex:
    global _cached_index, _cached_at
    with _cache_lock:
        if not force_refresh and _cached_index and time.monotonic() - _cached_at < _CACHE_TTL_SECONDS:
            return _cached_index
        items = list_capabilities()
        available = [item for item in items if item.enabled and item.available]
        _cached_index = CapabilityIndex(
            version=_version(items), total=len(items), available=len(available),
            categories=tuple(sorted({item.category for item in available})),
        )
        _cached_at = time.monotonic()
        return _cached_index


def is_capability_inquiry(text: str) -> bool:
    """Keep the self-knowledge tool out of ordinary task and social messages."""
    normalized = re.sub(r"\s+", "", str(text or "").lower())
    patterns = (
        r"你(会|能|可以)(做|干|帮).*(什么|哪些)",
        r"你有(什么|哪些).*(功能|能力|工具|技能)",
        r"你(的)?(功能|能力|工具|技能)(有|是|包括)",
        r"你支不支持",
        r"你能不能(看|读|写|搜索|联网|画|生成|拍)",
        r"莲心(会|能|可以|有).*(什么|哪些|功能|能力|工具|技能)",
    )
    return any(re.search(pattern, normalized) for pattern in patterns)


def _match(items: list[CapabilityDescriptor], query: str, category: str) -> list[CapabilityDescriptor]:
    category = str(category or "").strip()
    if category:
        items = [item for item in items if category.lower() in item.category.lower()]
    terms = [term for term in re.split(r"[\s,，、]+", str(query or "").lower()) if term]
    if not terms:
        return items
    def score(item: CapabilityDescriptor) -> int:
        haystack = " ".join((item.name, item.display_name, item.description, item.category)).lower()
        return sum(term in haystack for term in terms)
    return [item for item in items if score(item)]


def query_capabilities(query: str = "", *, category: str = "", limit: int = 20) -> dict:
    """Return a bounded, user-facing view of the current runtime catalog."""
    items = list_capabilities()
    matched = _match(items, query, category)
    bounded = matched[:max(1, min(int(limit), 50))]
    return {
        "catalog_version": _version(items),
        "total_matches": len(matched),
        "items": [
            {
                "name": item.name,
                "display_name": item.display_name,
                "description": item.description[:240],
                "category": item.category,
                "source": item.source_kind,
                "status": _status(item),
            }
            for item in bounded
        ],
    }


def format_capability_query(query: str = "", category: str = "", limit: int = 20) -> str:
    result = query_capabilities(query, category=category, limit=limit)
    items = result["items"]
    if not items:
        return "未找到匹配能力。请说明想了解的功能或分类；不要据此猜测自己具备未列出的能力。"
    lines = [f"能力目录版本 {result['catalog_version']}；匹配 {result['total_matches']} 项："]
    lines.extend(
        f"- {item['display_name']}（{item['category']}，{item['status']}）：{item['description']}"
        for item in items
    )
    return "\n".join(lines)
