"""
memory_rag.py — 记忆向量检索 (RAG)
sentence-transformers 本地 embedding → 语义搜索 → 注入聊天气泡
"""

import logging
import threading
from typing import TYPE_CHECKING, Optional

import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

import os as _os
_os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


def _ensure_torch_fsdp_compat():
    """torch 2.5.1 移除了 torch.distributed.fsdp，sentence-transformers 依赖它。
    仅在需要加载模型时才调用，避免未安装 sentence-transformers 时也拖慢启动。"""
    import torch.distributed as _dist
    if not hasattr(_dist, "fsdp"):
        import types as _types
        _fsdp = _types.ModuleType("torch.distributed.fsdp")
        _fsdp.FullyShardedDataParallel = type("FullyShardedDataParallel", (), {})
        _fsdp.ShardingStrategy = type("ShardingStrategy", (), {
            "FULL_SHARD": 1, "SHARD_GRAD_OP": 2, "NO_SHARD": 3, "HYBRID_SHARD": 4, "_HYBRID_SHARD_ZERO2": 5
        })
        _fsdp.StateDictType = type("StateDictType", (), {
            "FULL_STATE_DICT": 1, "LOCAL_STATE_DICT": 2, "SHARDED_STATE_DICT": 3
        })
        _dist.fsdp = _fsdp

logger = logging.getLogger("MemoryRAG")

# 全局单例
_model: Optional["SentenceTransformer"] = None
_model_name = "BAAI/bge-small-zh-v1.5"  # 96MB, 中文优化, 512维
_load_attempted = False


def _get_model():
    """懒加载 embedding 模型（首次调用约 5 秒下载）。"""
    global _model, _load_attempted
    if _model is None and not _load_attempted:
        _load_attempted = True
        _ensure_torch_fsdp_compat()
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {_model_name}")
            _model = SentenceTransformer(_model_name, device="cpu")
            logger.info("Embedding model ready")
        except ImportError:
            logger.warning("sentence-transformers not installed, RAG disabled")
        except Exception as e:
            logger.warning(f"Embedding model load failed: {e}")
        return None
    return _model


def embed(text: str) -> Optional[np.ndarray]:
    """将文本编码为归一化向量。返回 None 表示模型不可用。"""
    model = _get_model()
    if model is None:
        return None
    try:
        vec = model.encode(text, normalize_embeddings=True)
        return vec.astype(np.float32)
    except Exception as e:
        logger.debug(f"Embed failed: {e}")
        return None


def embed_bytes(text: str) -> Optional[bytes]:
    """编码为 bytes（用于 SQLite BLOB 存储）。"""
    vec = embed(text)
    if vec is None:
        return None
    return vec.tobytes()


def search_similar(
    query: str,
    top_k: int = 3,
    threshold: float = 0.5,
    category: str = None,
) -> list[tuple[float, dict]]:
    """向量语义搜索与 query 最相似的记忆。

    Args:
        query: 查询文本（通常是用户最后一条消息）
        top_k: 返回条数
        threshold: 最低相似度阈值 (0~1)
        category: 可选，限制分类

    Returns:
        [(相似度, 记忆dict), ...] 按相似度降序
    """
    model = _get_model()
    if model is None:
        return []

    q_vec = embed(query)
    if q_vec is None:
        return []

    try:
        from brain.graph_memory import _get_conn
        conn = _get_conn()

        if category:
            rows = conn.execute(
                """SELECT id, content, category, source, strength, embedding
                   FROM memory_facts
                   WHERE embedding IS NOT NULL AND category = ?
                   ORDER BY strength DESC""",
                (category,)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, content, category, source, strength, embedding
                   FROM memory_facts
                   WHERE embedding IS NOT NULL
                   ORDER BY strength DESC"""
            ).fetchall()

        if not rows:
            return []

        # 批量计算余弦相似度
        results = []
        for r in rows:
            emb = r["embedding"]
            if emb is None:
                continue
            mem_vec = np.frombuffer(emb, dtype=np.float32)
            sim = float(np.dot(q_vec, mem_vec))
            if sim >= threshold:
                results.append((sim, {
                    "content": r["content"],
                    "category": r["category"],
                    "source": r["source"],
                    "strength": r["strength"],
                }))

        results.sort(key=lambda x: x[0], reverse=True)
        return results[:top_k]

    except Exception as e:
        logger.debug(f"RAG search failed: {e}")
        return []


def find_similar_memory(
    content: str,
    category: str = None,
    threshold: float = 0.85,
) -> Optional[tuple[float, dict]]:
    """查找与 content 语义相近的已有记忆（用于去重合并）。
    返回最相似的那条 (相似度, 记忆dict) 或 None。"""
    results = search_similar(content, top_k=1, threshold=threshold, category=category)
    return results[0] if results else None


def format_rag_context(memories: list[tuple[float, dict]]) -> str:
    """将检索到的记忆格式化为 LLM 可读的提示文本。"""
    if not memories:
        return ""
    lines = ["【你可能记得的相关信息】"]
    for sim, mem in memories:
        lines.append(f"· {mem['content']} (相关度:{sim:.0%})")
    return "\n".join(lines)


def reindex_all_facts():
    """后台线程：为所有没有 embedding 的记忆补建向量。"""
    def _run():
        model = _get_model()
        if model is None:
            return
        try:
            from brain.graph_memory import _get_conn
            conn = _get_conn()
            rows = conn.execute(
                "SELECT id, content FROM memory_facts WHERE embedding IS NULL"
            ).fetchall()
            if not rows:
                return
            logger.info(f"Reindexing {len(rows)} memories...")
            vecs = model.encode(
                [r["content"] for r in rows],
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            for r, vec in zip(rows, vecs):
                conn.execute(
                    "UPDATE memory_facts SET embedding = ? WHERE id = ?",
                    (vec.astype(np.float32).tobytes(), r["id"])
                )
            conn.commit()
            logger.info(f"Reindexed {len(rows)} memories")
        except Exception as e:
            logger.warning(f"Reindex failed: {e}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def warmup():
    """后台预热 embedding 模型（启动时调用）。"""
    def _load():
        _get_model()
    t = threading.Thread(target=_load, daemon=True)
    t.start()