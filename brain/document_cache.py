"""Private, content-addressed cache for Markdown document conversions."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from utils.paths import get_user_data_dir


_DEFAULT_MAX_BYTES = 128 * 1024 * 1024
_DEFAULT_MAX_AGE_DAYS = 30


@dataclass(frozen=True)
class CachedDocument:
    content: str
    digest: str
    cache_path: Path
    cache_hit: bool


class MarkdownDocumentCache:
    """Store generated Markdown outside source directories and deduplicate by SHA-256."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        max_bytes: int = _DEFAULT_MAX_BYTES,
        max_age_days: int = _DEFAULT_MAX_AGE_DAYS,
    ) -> None:
        self.root = root or get_user_data_dir() / "document_cache"
        self.max_bytes = max(0, int(max_bytes))
        self.max_age = timedelta(days=max(0, int(max_age_days)))
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        self.cleanup()

    def get_or_create(
        self,
        source_path: Path,
        converter: Callable[[Path], str],
    ) -> CachedDocument:
        """Return cached Markdown or convert once and atomically persist the result."""
        digest = self._digest(source_path)
        markdown_path, metadata_path = self._paths_for(digest)

        with self._lock:
            cached = self._read(markdown_path, metadata_path, digest)
            if cached is not None:
                os.utime(markdown_path, None)
                return CachedDocument(cached, digest, markdown_path, True)

            content = converter(source_path).strip()
            if not content:
                raise RuntimeError("文档转换结果为空，未写入缓存")

            metadata = {
                "schema_version": 1,
                "digest": digest,
                "suffix": source_path.suffix.lower(),
                "content_chars": len(content),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._atomic_write(markdown_path, content)
            self._atomic_write(metadata_path, json.dumps(metadata, ensure_ascii=False))
            self.cleanup(exclude={digest})
            return CachedDocument(content, digest, markdown_path, False)

    def cleanup(self, *, exclude: set[str] | None = None) -> None:
        """Remove expired entries, then evict least-recently-used entries over the size cap."""
        exclude = exclude or set()
        with self._lock:
            entries: list[tuple[Path, Path, int, float, str]] = []
            now = datetime.now(timezone.utc)
            for metadata_path in self.root.rglob("*.json"):
                digest = metadata_path.stem
                markdown_path = metadata_path.with_suffix(".md")
                if not markdown_path.exists():
                    self._remove_entry(markdown_path, metadata_path)
                    continue
                try:
                    created_at = self._metadata_created_at(metadata_path)
                    if digest not in exclude and now - created_at > self.max_age:
                        self._remove_entry(markdown_path, metadata_path)
                        continue
                    stat = markdown_path.stat()
                    entries.append((markdown_path, metadata_path, stat.st_size, stat.st_mtime, digest))
                except (OSError, ValueError, json.JSONDecodeError):
                    self._remove_entry(markdown_path, metadata_path)

            total_size = sum(item[2] for item in entries)
            for markdown_path, metadata_path, size, _, digest in sorted(entries, key=lambda item: item[3]):
                if total_size <= self.max_bytes:
                    break
                if digest in exclude:
                    continue
                self._remove_entry(markdown_path, metadata_path)
                total_size -= size

            for shard in self.root.iterdir():
                if shard.is_dir() and not any(shard.iterdir()):
                    shard.rmdir()

    def clear(self) -> None:
        """Delete only this cache directory; source documents are never touched."""
        with self._lock:
            if self.root.exists():
                shutil.rmtree(self.root)
            self.root.mkdir(parents=True, exist_ok=True)

    def stats(self) -> tuple[int, int]:
        """Return (entry_count, byte_count) without exposing source document paths."""
        with self._lock:
            entries = list(self.root.rglob("*.md"))
            return len(entries), sum(path.stat().st_size for path in entries if path.is_file())

    @staticmethod
    def _digest(source_path: Path) -> str:
        digest = hashlib.sha256()
        with source_path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _paths_for(self, digest: str) -> tuple[Path, Path]:
        shard = self.root / digest[:2]
        shard.mkdir(parents=True, exist_ok=True)
        return shard / f"{digest}.md", shard / f"{digest}.json"

    @staticmethod
    def _read(markdown_path: Path, metadata_path: Path, digest: str) -> str | None:
        if not markdown_path.is_file() or not metadata_path.is_file():
            return None
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("digest") != digest:
                return None
            content = markdown_path.read_text(encoding="utf-8")
            return content if content.strip() else None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _metadata_created_at(metadata_path: Path) -> datetime:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        created_at = datetime.fromisoformat(metadata["created_at"])
        return created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)

    @staticmethod
    def _remove_entry(markdown_path: Path, metadata_path: Path) -> None:
        markdown_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".part",
                delete=False,
            ) as handle:
                handle.write(content)
                temp_path = Path(handle.name)
            os.replace(temp_path, path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
