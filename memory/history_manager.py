"""
HistoryManager：会话历史管理（SQLite）
负责创建会话、保存消息、读取历史记录。
数据库路径：memory/conversations.db

线程安全说明：
- 每个线程通过 threading.local() 获得独立的 SQLite 连接
- WAL 模式允许多个连接并发读取，写入时自动等待 busy_timeout
- 不需要外部锁，sqlite3 模块内部序列化对单个连接的操作
"""

import sqlite3
import threading
from pathlib import Path
from datetime import datetime

_DB_PATH = Path(__file__).parent / "conversations.db"
_local = threading.local()


def _get_connection() -> sqlite3.Connection:
    """为当前线程获取（或创建）独立的 SQLite 连接。"""
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=2000")     # 写冲突最多等 2 秒（太长会导致界面卡顿，太短会频繁 SQLITE_BUSY）
        conn.execute("PRAGMA wal_autocheckpoint=500")
        conn.execute("PRAGMA synchronous=NORMAL")     # WAL 模式下 NORMAL 安全且更快
        _init_db(conn)
        _local.conn = conn
    return _local.conn


def _init_db(conn: sqlite3.Connection):
    """初始化数据库表结构（首次运行时创建），并执行迁移。"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT    NOT NULL DEFAULT '新对话',
            created_at TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            role       TEXT    NOT NULL,
            content    TEXT    NOT NULL,
            timestamp  TEXT    NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );
    """)
    conn.commit()
    _migrate_db(conn)


def _migrate_db(conn: sqlite3.Connection):
    """安全为 sessions 表添加新列（幂等，已存在时忽略）。"""
    for sql in (
        "ALTER TABLE sessions ADD COLUMN summary   TEXT    DEFAULT ''",
        "ALTER TABLE sessions ADD COLUMN is_pinned INTEGER DEFAULT 0",
    ):
        try:
            conn.execute(sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # 列已存在，跳过


class HistoryManager:
    def __init__(self):
        # 不再在 __init__ 中创建连接——由 _get_connection() 在首次使用时按需创建
        pass

    # ── 会话管理 ─────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        """获取当前线程的数据库连接。"""
        return _get_connection()

    def new_session(self) -> int:
        """创建新会话，返回 session_id。"""
        conn = self._conn()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute(
            "INSERT INTO sessions (title, created_at) VALUES (?, ?)",
            ("新对话", now)
        )
        conn.commit()
        return cur.lastrowid

    def update_title(self, session_id: int, title: str):
        """更新会话标题。"""
        conn = self._conn()
        conn.execute(
            "UPDATE sessions SET title = ? WHERE id = ?",
            (title[:30], session_id)
        )
        conn.commit()

    # ── 消息管理 ─────────────────────────────────────────────

    def save_message(self, session_id: int, role: str, content: str):
        """保存一条消息（role: 'user' | 'assistant'）。"""
        conn = self._conn()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, role, content, now)
        )
        conn.commit()

    # ── 读取接口 ─────────────────────────────────────────────

    def get_last_session_id(self) -> int | None:
        """返回最近一次会话的 ID，若无历史则返回 None。"""
        conn = self._conn()
        cur = conn.execute(
            "SELECT id FROM sessions ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        return row[0] if row else None

    def update_session_title(self, session_id: int, new_title: str):
        """重命名会话标题（供历史对话框双击修改使用）。"""
        conn = self._conn()
        conn.execute(
            "UPDATE sessions SET title = ? WHERE id = ?",
            (new_title[:50], session_id)
        )
        conn.commit()

    def get_sessions(self) -> list[dict]:
        """返回所有会话列表：置顶优先，其余按时间倒序。"""
        conn = self._conn()
        cur = conn.execute(
            "SELECT id, title, created_at, summary, is_pinned "
            "FROM sessions ORDER BY is_pinned DESC, id DESC"
        )
        return [dict(row) for row in cur.fetchall()]

    def search_sessions(self, keyword: str) -> list[dict]:
        """按关键词搜索标题、摘要、消息内容，返回匹配会话列表。"""
        conn = self._conn()
        kw = f"%{keyword}%"
        cur = conn.execute(
            "SELECT DISTINCT s.id, s.title, s.created_at, s.summary, s.is_pinned "
            "FROM sessions s LEFT JOIN messages m ON m.session_id = s.id "
            "WHERE s.title LIKE ? OR s.summary LIKE ? OR m.content LIKE ? "
            "ORDER BY s.is_pinned DESC, s.id DESC",
            (kw, kw, kw),
        )
        return [dict(row) for row in cur.fetchall()]

    def update_summary(self, session_id: int, summary: str):
        """保存 AI 生成的摘要。"""
        conn = self._conn()
        conn.execute(
            "UPDATE sessions SET summary = ? WHERE id = ?",
            (summary, session_id),
        )
        conn.commit()

    def toggle_pin(self, session_id: int):
        """切换置顶状态。"""
        conn = self._conn()
        conn.execute(
            "UPDATE sessions SET is_pinned = CASE WHEN is_pinned=1 THEN 0 ELSE 1 END "
            "WHERE id = ?",
            (session_id,),
        )
        conn.commit()

    def delete_session(self, session_id: int):
        """删除会话及其所有消息。"""
        conn = self._conn()
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()

    def get_messages(self, session_id: int, limit: int = None) -> list[dict]:
        """返回指定会话的消息，按时间正序。
        如果指定了 limit，只返回最近 N 条。
        """
        conn = self._conn()
        if limit is not None:
            cur = conn.execute(
                "SELECT role, content, timestamp FROM messages "
                "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit)
            )
            rows = list(cur.fetchall())
            rows.reverse()
            return [dict(row) for row in rows]
        cur = conn.execute(
            "SELECT role, content, timestamp FROM messages "
            "WHERE session_id = ? ORDER BY id ASC",
            (session_id,)
        )
        return [dict(row) for row in cur.fetchall()]

    def get_message_count(self, session_id: int) -> int:
        """返回指定会话的消息数量。"""
        conn = self._conn()
        cur = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,)
        )
        return cur.fetchone()[0]

    def search_session_messages(self, session_id: int, keyword: str, limit: int = 10) -> list[dict]:
        """在指定会话中搜索包含关键词的消息，按时间正序返回。"""
        conn = self._conn()
        kw = f"%{keyword}%"
        cur = conn.execute(
            "SELECT role, content, timestamp FROM messages "
            "WHERE session_id = ? AND content LIKE ? "
            "ORDER BY id DESC LIMIT ?",
            (session_id, kw, limit)
        )
        rows = list(cur.fetchall())
        rows.reverse()
        return [dict(row) for row in rows]

    # ── 清理 ─────────────────────────────────────────────────

    def close(self):
        """关闭当前线程的数据库连接。"""
        if hasattr(_local, "conn") and _local.conn is not None:
            _local.conn.close()
            _local.conn = None
