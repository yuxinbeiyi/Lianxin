"""
BilibiliHistoryManager：B站冲浪数据管理
管理兴趣标签、浏览记录、已推荐视频去重。

数据文件：~/.lianxin/bilibili_history.json
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from utils.paths import get_user_data_dir

_HISTORY_PATH = get_user_data_dir() / "bilibili_history.json"

_SEARCH_COOLDOWN_SECONDS = 30
_TAG_COOLDOWN_HOURS = 48
_DECAY_PER_7_DAYS = 3


class BilibiliHistoryManager:

    def __init__(self):
        self._data = self._load()

    def _load(self) -> dict:
        try:
            if _HISTORY_PATH.exists():
                raw = _HISTORY_PATH.read_text(encoding="utf-8")
                data = json.loads(raw)
                if "tags" in data and "history" in data and "seen_bvids" in data:
                    return data
        except Exception:
            pass
        return self._default()

    def _default(self) -> dict:
        return {
            "tags": [],
            "history": [],
            "seen_bvids": [],
            "last_search_time": 0,
        }

    def save(self):
        try:
            _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            _HISTORY_PATH.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            print(f"[BilibiliHistory] 保存失败: {e}")

    # ── 标签管理 ──────────────────────────────────────────────

    def get_tags(self, status: str = "active") -> list[dict]:
        return [t for t in self._data["tags"] if t.get("status", "active") == status]

    def get_tag_keywords(self, status: str = "active") -> list[str]:
        return [t["keyword"] for t in self.get_tags(status)]

    def add_tag(self, keyword: str, base_score: int = 50, source: str = "auto"):
        keyword = keyword.strip()
        if not keyword:
            return
        existing = None
        for t in self._data["tags"]:
            if t["keyword"] == keyword:
                existing = t
                break
        if existing:
            if existing.get("status") == "paused":
                existing["status"] = "active"
            return
        self._data["tags"].append({
            "keyword": keyword,
            "base_score": base_score,
            "boost_score": 0,
            "status": "active",
            "source": source,
            "added_at": time.time(),
            "last_searched": 0,
        })

    def remove_tag(self, keyword: str):
        self._data["tags"] = [
            t for t in self._data["tags"] if t["keyword"] != keyword
        ]

    def pause_tag(self, keyword: str):
        for t in self._data["tags"]:
            if t["keyword"] == keyword:
                t["status"] = "paused"
                return

    def resume_tag(self, keyword: str):
        for t in self._data["tags"]:
            if t["keyword"] == keyword:
                t["status"] = "active"
                return

    def update_tag_score(self, keyword: str, delta: int):
        for t in self._data["tags"]:
            if t["keyword"] == keyword:
                t["boost_score"] = t.get("boost_score", 0) + delta
                return

    def get_weighted_tags(self, limit: int = 5) -> list[str]:
        now = time.time()
        scored = []
        for t in self._data["tags"]:
            if t.get("status") != "active":
                continue
            last = t.get("last_searched", 0)
            if last > 0 and (now - last) < _TAG_COOLDOWN_HOURS * 3600:
                continue
            base = t.get("base_score", 50)
            boost = t.get("boost_score", 0)
            added = t.get("added_at", now)
            days_since = (now - added) / 86400.0
            decay = (days_since / 7.0) * _DECAY_PER_7_DAYS
            final = max(0, base + boost - decay)
            scored.append((t["keyword"], final))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [kw for kw, _ in scored[:limit]]

    def mark_tag_searched(self, keyword: str):
        now = time.time()
        for t in self._data["tags"]:
            if t["keyword"] == keyword:
                t["last_searched"] = now
                return

    # ── 浏览记录 ──────────────────────────────────────────────

    def add_record(self, keyword: str, results: list[dict]) -> str:
        now = datetime.now()
        record_id = f"rec_{int(time.time() * 1000)}"
        record = {
            "id": record_id,
            "date": now.isoformat(),
            "keyword": keyword,
            "results": [
                {
                    "title": v.get("title", ""),
                    "author": v.get("author", ""),
                    "bvid": v.get("bvid", ""),
                    "play_count": v.get("play_count", 0),
                    "description": v.get("description", ""),
                    "link": v.get("link", ""),
                    "user_reaction": "",
                }
                for v in results
            ],
        }
        self._data["history"].insert(0, record)
        if len(self._data["history"]) > 200:
            self._data["history"] = self._data["history"][:200]
        for v in results:
            bvid = v.get("bvid", "")
            if bvid and not self.is_seen(bvid):
                self._data["seen_bvids"].append({
                    "bvid": bvid,
                    "seen_at": time.time(),
                })
        if len(self._data["seen_bvids"]) > 500:
            self._data["seen_bvids"] = self._data["seen_bvids"][-500:]
        return record_id

    def get_history(self, limit: int = 50, keyword: str = "") -> list[dict]:
        records = self._data["history"]
        if keyword:
            records = [r for r in records if keyword.lower() in r.get("keyword", "").lower()]
        return records[:limit]

    def react_to_video(self, record_id: str, bvid: str, reaction: str):
        for rec in self._data["history"]:
            if rec["id"] == record_id:
                for v in rec["results"]:
                    if v["bvid"] == bvid:
                        v["user_reaction"] = reaction
                        kw = rec.get("keyword", "")
                        if kw:
                            if reaction == "liked":
                                self.update_tag_score(kw, 10)
                            elif reaction == "disliked":
                                self.update_tag_score(kw, -5)
                        return

    def clear_history(self):
        self._data["history"] = []

    # ── 去重 ──────────────────────────────────────────────────

    def is_seen(self, bvid: str) -> bool:
        for item in self._data["seen_bvids"]:
            if item["bvid"] == bvid:
                return True
        return False

    def filter_seen(self, results: list[dict]) -> list[dict]:
        return [v for v in results if not self.is_seen(v.get("bvid", ""))]

    # ── 限流 ──────────────────────────────────────────────────

    def can_search(self) -> bool:
        last = self._data.get("last_search_time", 0)
        return (time.time() - last) >= _SEARCH_COOLDOWN_SECONDS

    def mark_searched(self):
        self._data["last_search_time"] = time.time()

    # ── 统计 ──────────────────────────────────────────────────

    def get_stats(self) -> dict:
        tags = self._data["tags"]
        active = sum(1 for t in tags if t.get("status") == "active")
        paused = sum(1 for t in tags if t.get("status") == "paused")
        return {
            "total_tags": len(tags),
            "active_tags": active,
            "paused_tags": paused,
            "total_records": len(self._data["history"]),
            "total_seen": len(self._data["seen_bvids"]),
        }


_history_mgr = None


def get_bilibili_history() -> BilibiliHistoryManager:
    global _history_mgr
    if _history_mgr is None:
        _history_mgr = BilibiliHistoryManager()
    return _history_mgr
