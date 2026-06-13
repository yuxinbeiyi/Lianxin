# brain/notebook.py
"""
会话级草稿本（第四阶段）
借鉴 Claude Code Notebook 设计：LLM 用 key-value 存储临时笔记，
数据不受对话上下文压缩影响。标记 persist=True 的笔记可跨会话保留。
"""

import json
import threading
import os
from datetime import datetime
from typing import Optional

_VALID_KEY_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
_MAX_VALUE_LEN = 8000
_MAX_ENTRIES = 50
_PERSIST_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "notebook_persist.json")


class Note:
    def __init__(self, value: str, persist: bool = False, created_at: str = ""):
        self.value = value
        self.persist = persist
        self.created_at = created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self) -> dict:
        return {"value": self.value, "persist": self.persist, "created_at": self.created_at}

    @staticmethod
    def from_dict(d: dict) -> "Note":
        return Note(value=d["value"], persist=d.get("persist", False), created_at=d.get("created_at", ""))


class Notebook:
    def __init__(self):
        self._lock = threading.Lock()
        self._store: dict[str, Note] = {}
        self._load_persisted()

    def _clean_key(self, key: str) -> str:
        key = key.strip().lower().replace(" ", "_")
        return "".join(c for c in key if c in _VALID_KEY_CHARS)

    def write(self, key: str, value: str, persist: bool = False) -> str:
        key = self._clean_key(key)
        if not key:
            return "错误：key 不能为空，请使用英文/数字/下划线"
        value = value[: _MAX_VALUE_LEN]
        with self._lock:
            if len(self._store) >= _MAX_ENTRIES and key not in self._store:
                return f"错误：草稿本已满（最多 {_MAX_ENTRIES} 条），请先删除不需要的笔记"
            self._store[key] = Note(value=value, persist=persist)
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
                lines.append(f"{tag} [{k}] ({len(n.value)} 字符) — {n.created_at}")
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
