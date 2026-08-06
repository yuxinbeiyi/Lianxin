"""Small persistent cache for locally generated memory embeddings.

The cache is an acceleration layer only.  SQLite ``memory_facts`` remains the
source of truth and cached values can always be discarded and regenerated.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path

from utils.paths import get_user_data_dir


MODEL_NAME = "BAAI/bge-small-zh-v1.5"
CACHE_VERSION = 1
_init_lock = threading.Lock()
_initialized: set[str] = set()


def _cache_path() -> Path:
    return get_user_data_dir() / "rag" / "embedding_cache.sqlite3"


def _connect() -> sqlite3.Connection:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    key = str(path)
    if key not in _initialized:
        with _init_lock:
            if key not in _initialized:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS embedding_cache (
                        content_hash TEXT NOT NULL,
                        model_name TEXT NOT NULL,
                        dimension INTEGER NOT NULL,
                        cache_version INTEGER NOT NULL,
                        embedding BLOB NOT NULL,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (content_hash, model_name, dimension, cache_version)
                    )"""
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_embedding_cache_updated "
                    "ON embedding_cache(updated_at)"
                )
                conn.commit()
                _initialized.add(key)
    return conn


def content_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def get_many(texts: list[str], *, model_name: str = MODEL_NAME,
             dimension: int = 0) -> dict[str, bytes]:
    if not texts:
        return {}
    hashes = {content_hash(text): text for text in texts}
    conn = _connect()
    try:
        placeholders = ",".join("?" for _ in hashes)
        rows = conn.execute(
            "SELECT content_hash, embedding FROM embedding_cache "
            "WHERE content_hash IN ("
            + placeholders
            + ") AND model_name=? AND dimension=? AND cache_version=?",
            [*hashes, model_name, int(dimension), CACHE_VERSION],
        ).fetchall()
        return {hashes[row[0]]: bytes(row[1]) for row in rows}
    finally:
        conn.close()


def put_many(items: list[tuple[str, bytes]], *, model_name: str = MODEL_NAME,
             dimension: int) -> int:
    if not items:
        return 0
    conn = _connect()
    try:
        conn.executemany(
            """INSERT OR REPLACE INTO embedding_cache
               (content_hash, model_name, dimension, cache_version, embedding)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (content_hash(text), model_name, int(dimension), CACHE_VERSION, blob)
                for text, blob in items
            ],
        )
        conn.commit()
        return len(items)
    finally:
        conn.close()


def clear() -> None:
    """Clear the acceleration cache; memory facts are not affected."""
    conn = _connect()
    try:
        conn.execute("DELETE FROM embedding_cache")
        conn.commit()
    finally:
        conn.close()
