"""Backend selection for local RAG vector indexes.

This layer deliberately keeps backend discovery separate from Torch and from
the SQLite source of truth.  A backend that is unavailable is never allowed
to prevent lexical or exact SQLite retrieval.
"""

from __future__ import annotations

import importlib.util


def availability() -> dict[str, bool]:
    return {
        "faiss_cpu": importlib.util.find_spec("faiss") is not None,
        "sqlite_vec": importlib.util.find_spec("sqlite_vec") is not None,
    }


def choose_backend(config: dict | None = None) -> dict:
    cfg = config or {}
    requested = str(cfg.get("rag_ann_backend", "auto") or "auto").lower()
    available = availability()
    aliases = {
        "faiss": "faiss_cpu",
        "faiss-cpu": "faiss_cpu",
        "hnswlib": "faiss_cpu",  # compatibility with the existing setting
        "sqlite-vec": "sqlite_vec",
        "sqlite_vec": "sqlite_vec",
    }
    if requested == "auto":
        selected = "faiss_cpu" if available["faiss_cpu"] else (
            "sqlite_vec" if available["sqlite_vec"] else "sqlite_scan"
        )
    else:
        selected = aliases.get(requested, "sqlite_scan")
        if not available.get(selected, False):
            selected = "sqlite_scan"
    return {
        "requested": requested,
        "selected": selected,
        "available": available,
        "fallback": selected == "sqlite_scan",
    }
