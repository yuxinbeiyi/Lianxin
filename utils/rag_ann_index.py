"""Persistent CPU ANN index for RAG memory embeddings.

SQLite remains the source of truth.  This module is only an optional,
rebuildable acceleration cache and never imports Torch or CUDA.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np

from utils.paths import get_user_data_dir

logger = logging.getLogger("lianxin.rag_ann")


class RagAnnIndex:
    FORMAT_VERSION = 1

    def __init__(self):
        self._lock = threading.RLock()
        self._index = None
        self._dimension = 0
        self._model_name = ""
        self._loaded = False
        self._available: bool | None = None
        self._load_error = ""

    @staticmethod
    def _config() -> dict:
        try:
            from config import get_rag_config
            return get_rag_config()
        except Exception:
            return {
                "rag_ann_enabled": True,
                "rag_ann_backend": "auto",
                "rag_ann_m": 16,
                "rag_ann_ef_construction": 160,
                "rag_ann_ef_search": 80,
            }

    @staticmethod
    def _paths() -> tuple[Path, Path]:
        root = get_user_data_dir() / "rag" / "index"
        return root / "memory_facts.hnsw", root / "memory_facts.meta.json"

    def _load_faiss(self):
        backend = self.backend_status().get("selected")
        if backend != "faiss_cpu":
            return None
        if self._available is False:
            return None

    def backend_status(self) -> dict:
        try:
            from utils.rag_vector_backend import choose_backend
            return choose_backend(self._config())
        except Exception as exc:
            logger.debug("RAG backend detection failed: %s", exc)
            return {"requested": "auto", "selected": "sqlite_scan",
                    "available": {}, "fallback": True, "error": str(exc)}
        try:
            import faiss
            self._available = True
            return faiss
        except Exception as exc:
            self._available = False
            self._load_error = str(exc)
            logger.info("RAG ANN unavailable; using SQLite vector fallback: %s", exc)
            return None

    def is_available(self) -> bool:
        if not bool(self._config().get("rag_ann_enabled", True)):
            return False
        with self._lock:
            return self._load_faiss() is not None

    def is_ready(self) -> bool:
        with self._lock:
            return self._loaded and self._index is not None

    def needs_build(self) -> bool:
        return self.is_available() and not self.is_ready()

    @staticmethod
    def ids_need_rebuild(index_ids: Iterable[int], database_ids: Iterable[int]) -> bool:
        """Return whether the persisted ANN ID set differs from SQLite."""
        return {int(value) for value in index_ids} != {int(value) for value in database_ids}

    def validate_ids(self, database_ids: Iterable[int]) -> dict:
        """Compare active SQLite IDs with the loaded ANN index without vectors."""
        with self._lock:
            if not self.is_ready():
                return {"status": "not_ready", "consistent": False,
                        "index_count": 0, "database_count": len(list(database_ids))}
            expected = {int(value) for value in database_ids}
            try:
                faiss = self._load_faiss()
                index_map = faiss.vector_to_array(self._index.id_map)
                actual = {int(value) for value in index_map.tolist()}
                consistent = not self.ids_need_rebuild(actual, expected)
                return {"status": "ok", "consistent": consistent,
                        "index_count": len(actual), "database_count": len(expected)}
            except Exception as exc:
                self._load_error = str(exc)
                return {"status": "failed", "consistent": False,
                        "index_count": 0, "database_count": len(expected),
                        "error": str(exc)}

    def _new_index(self, faiss, dimension: int):
        cfg = self._config()
        backend = str(cfg.get("rag_ann_backend", "auto") or "auto").lower()
        # hnswlib is intentionally optional.  The current supported local
        # backend is CPU FAISS HNSW; an explicit unsupported backend falls back
        # safely instead of failing application startup.
        if backend not in {"auto", "faiss", "faiss-cpu", "hnswlib"}:
            raise ValueError(f"unsupported RAG ANN backend: {backend}")
        base = faiss.IndexHNSWFlat(
            int(dimension),
            max(4, int(cfg.get("rag_ann_m", 16) or 16)),
            faiss.METRIC_INNER_PRODUCT,
        )
        base.hnsw.efConstruction = max(
            40, int(cfg.get("rag_ann_ef_construction", 160) or 160)
        )
        base.hnsw.efSearch = max(
            16, int(cfg.get("rag_ann_ef_search", 80) or 80)
        )
        return faiss.IndexIDMap2(base)

    @staticmethod
    def _atomic_json_write(path: Path, payload: dict) -> None:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)

    def _save_locked(self) -> None:
        if self._index is None:
            return
        faiss = self._load_faiss()
        if faiss is None:
            return
        index_path, meta_path = self._paths()
        index_path.parent.mkdir(parents=True, exist_ok=True)
        temp_index = index_path.with_suffix(index_path.suffix + ".tmp")
        faiss.write_index(self._index, str(temp_index))
        os.replace(temp_index, index_path)
        self._atomic_json_write(meta_path, {
            "format_version": self.FORMAT_VERSION,
            "backend": "faiss-cpu-hnsw",
            "model_name": self._model_name,
            "dimension": self._dimension,
            "ntotal": int(self._index.ntotal),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        })

    def load(self, *, dimension: int | None = None, model_name: str = "") -> bool:
        with self._lock:
            if self.is_ready():
                if dimension and self._dimension != int(dimension):
                    return False
                if model_name and self._model_name and self._model_name != model_name:
                    return False
                return True
            faiss = self._load_faiss()
            if faiss is None:
                return False
            index_path, meta_path = self._paths()
            if not index_path.is_file() or not meta_path.is_file():
                return False
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if int(meta.get("format_version", 0)) != self.FORMAT_VERSION:
                    return False
                saved_dimension = int(meta.get("dimension", 0))
                saved_model = str(meta.get("model_name", ""))
                if dimension and saved_dimension != int(dimension):
                    return False
                if model_name and saved_model and saved_model != model_name:
                    return False
                index = faiss.read_index(str(index_path))
                if int(index.d) != saved_dimension or saved_dimension <= 0:
                    return False
                self._index = index
                self._dimension = saved_dimension
                self._model_name = saved_model
                self._loaded = True
                return True
            except Exception as exc:
                self._load_error = str(exc)
                logger.warning("RAG ANN index load failed; will rebuild: %s", exc)
                return False

    def search(self, vector: np.ndarray, *, k: int, model_name: str = ""):
        """Return ``[(memory_id, approximate_score), ...]`` or None on fallback."""
        vector = np.asarray(vector, dtype=np.float32).reshape(1, -1)
        with self._lock:
            if not self.load(dimension=vector.shape[1], model_name=model_name):
                return None
            try:
                scores, ids = self._index.search(vector, max(1, int(k)))
                return [
                    (int(item_id), float(score))
                    for item_id, score in zip(ids[0], scores[0])
                    if int(item_id) > 0
                ]
            except Exception as exc:
                logger.warning("RAG ANN search failed; using SQLite fallback: %s", exc)
                return None

    def build_from_rows(
        self,
        rows: Iterable[tuple[int, bytes]],
        *,
        model_name: str,
    ) -> dict:
        """Build an index from ``(fact_id, embedding_blob)`` rows."""
        faiss = self._load_faiss()
        if faiss is None or not bool(self._config().get("rag_ann_enabled", True)):
            return {"status": "unavailable", "indexed": 0}
        vectors = []
        ids = []
        dimension = 0
        for fact_id, blob in rows:
            try:
                vector = np.frombuffer(blob, dtype=np.float32)
                if vector.size == 0:
                    continue
                if not dimension:
                    dimension = int(vector.size)
                if vector.size != dimension:
                    continue
                vectors.append(vector)
                ids.append(int(fact_id))
            except (TypeError, ValueError):
                continue
        with self._lock:
            if not vectors:
                self._index = None
                self._loaded = False
                self._dimension = 0
                self._model_name = model_name
                return {"status": "empty", "indexed": 0}
            matrix = np.ascontiguousarray(np.vstack(vectors), dtype=np.float32)
            index = self._new_index(faiss, dimension)
            index.add_with_ids(matrix, np.asarray(ids, dtype=np.int64))
            self._index = index
            self._dimension = dimension
            self._model_name = model_name
            self._loaded = True
            self._save_locked()
            return {"status": "success", "indexed": len(ids)}

    def add_rows(self, rows: Iterable[tuple[int, bytes]], *, model_name: str) -> dict:
        """Add newly embedded rows when an index is already available."""
        with self._lock:
            if not self.is_ready() or self._model_name and self._model_name != model_name:
                return {"status": "deferred", "indexed": 0}
            vectors = []
            ids = []
            for fact_id, blob in rows:
                vector = np.frombuffer(blob, dtype=np.float32)
                if vector.size != self._dimension:
                    continue
                vectors.append(vector)
                ids.append(int(fact_id))
            if not vectors:
                return {"status": "empty", "indexed": 0}
            matrix = np.ascontiguousarray(np.vstack(vectors), dtype=np.float32)
            id_array = np.asarray(ids, dtype=np.int64)
            try:
                self._index.remove_ids(id_array)
            except Exception:
                pass
            self._index.add_with_ids(matrix, id_array)
            self._save_locked()
            return {"status": "success", "indexed": len(ids)}


_index = RagAnnIndex()


def get_rag_ann_index() -> RagAnnIndex:
    return _index
