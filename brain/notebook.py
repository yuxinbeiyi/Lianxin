# brain/notebook.py
"""
会话级草稿本（第四阶段）
借鉴 Claude Code Notebook 设计：LLM 用 key-value 存储临时笔记，
数据不受对话上下文压缩影响。标记 persist=True 的笔记可跨会话保留。

非持久笔记（persist=False）会在 24 小时后自动过期清理。
"""

import json
import threading
import os
from datetime import datetime, timedelta
from typing import Optional

_VALID_KEY_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
_MAX_VALUE_LEN = 8000
_MAX_ENTRIES = 50
_TTL_HOURS = 24                                 # 非持久笔记的存活时间
_PERSIST_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "notebook_persist.json")


class Note:
    def __init__(self, value: str, persist: bool = False, created_at: str = "",
                 expires_at: Optional[str] = None):
        self.value = value
        self.persist = persist
        self.created_at = created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.expires_at = expires_at            # ISO 格式字符串，非持久笔记的过期时间

    def to_dict(self) -> dict:
        d = {"value": self.value, "persist": self.persist, "created_at": self.created_at}
        if self.expires_at:
            d["expires_at"] = self.expires_at
        return d

    @staticmethod
    def from_dict(d: dict) -> "Note":
        return Note(
            value=d["value"],
            persist=d.get("persist", False),
            created_at=d.get("created_at", ""),
            expires_at=d.get("expires_at"),
        )


class Notebook:
    def __init__(self):
        self._lock = threading.Lock()
        self._store: dict[str, Note] = {}
        self._load_persisted()
        self._cleanup_expired()                 # 启动时清理过期笔记

    def _clean_key(self, key: str) -> str:
        key = key.strip().lower().replace(" ", "_")
        return "".join(c for c in key if c in _VALID_KEY_CHARS)

    def write(self, key: str, value: str, persist: bool = False) -> str:
        key = self._clean_key(key)
        if not key:
            return "错误：key 不能为空，请使用英文/数字/下划线"
        value = value[:_MAX_VALUE_LEN]
        with self._lock:
            if len(self._store) >= _MAX_ENTRIES and key not in self._store:
                return f"错误：草稿本已满（最多 {_MAX_ENTRIES} 条），请先删除不需要的笔记"
            note = Note(value=value, persist=persist)
            if not persist:
                note.expires_at = (datetime.now() + timedelta(hours=_TTL_HOURS)).isoformat()
            self._store[key] = note
        if persist:
            self._save_persisted()
        return f"已写入草稿本 [{key}]（{len(value)} 字符）{'🔒 持久化' if persist else ''}"

    def read(self, key: str = "") -> str:
        key = self._clean_key(key) if key else ""
        with self._lock:
            if key:
                note = self._store.get(key)
                return note.value if note else f"草稿本中没有 [{key}]"
            if not self._store:
                return "草稿本为空"
            lines = []
            for k, n in self._store.items():
                tag = "🔒" if n.persist else "  "
                expires = f" ⏳{n.expires_at[:16]}" if n.expires_at else ""
                lines.append(f"{tag} [{k}] ({len(n.value)} 字符) — {n.created_at}{expires}")
            return "草稿本目录：\n" + "\n".join(lines)

    def delete(self, key: str) -> str:
        key = self._clean_key(key)
        if not key:
            return "错误：请指定要删除的笔记 key"
        with self._lock:
            note = self._store.pop(key, None)
            if note is None:
                return f"草稿本中没有 [{key}]"
            was_persist = note.persist
        if was_persist:
            self._save_persisted()
        return f"已删除 [{key}]"

    def clear(self, keep_persistent: bool = True):
        with self._lock:
            if keep_persistent:
                self._store = {k: n for k, n in self._store.items() if n.persist}
            else:
                self._store.clear()

    def get_all(self) -> dict[str, Note]:
        with self._lock:
            return dict(self._store)

    def _cleanup_expired(self):
        """清理过期的非持久笔记（启动时调用）。"""
        now = datetime.now()
        expired = []
        with self._lock:
            for key, note in list(self._store.items()):
                if note.persist:
                    continue
                if note.expires_at:
                    try:
                        expires = datetime.fromisoformat(note.expires_at)
                        if expires < now:
                            expired.append(key)
                    except (ValueError, TypeError):
                        pass
            for key in expired:
                del self._store[key]
        if expired:
            print(f"[草稿本] 已清理 {len(expired)} 条过期笔记 ({_TTL_HOURS}h TTL)")

    def _load_persisted(self):
        try:
            if os.path.exists(_PERSIST_FILE):
                with open(_PERSIST_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                with self._lock:
                    for k, v in data.items():
                        self._store[k] = Note.from_dict(v)
                print(f"[草稿本] 已加载 {len(data)} 条持久笔记")
        except Exception as e:
            print(f"[草稿本] 加载持久笔记失败: {e}")

    def _save_persisted(self):
        try:
            os.makedirs(os.path.dirname(_PERSIST_FILE), exist_ok=True)
            with self._lock:
                data = {k: n.to_dict() for k, n in self._store.items() if n.persist}
            with open(_PERSIST_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[草稿本] 保存持久笔记失败: {e}")


_notebook: Optional[Notebook] = None


def get_notebook() -> Notebook:
    global _notebook
    if _notebook is None:
        _notebook = Notebook()
    return _notebook
