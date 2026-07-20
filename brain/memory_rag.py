"""
memory_rag.py — 记忆向量检索 (RAG)
sentence-transformers 本地 embedding → 语义搜索 → 注入聊天气泡
"""

import logging
import threading
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

import os as _os
_os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


def _ensure_torch_fsdp_compat():
    """torch 2.5.1 移除了 torch.distributed.fsdp，sentence-transformers 依赖它。
    要求在主线程先调用 _preload_torch() 完成 torch 初始化，避免子线程 access violation。"""
    import sys as _sys
    import types as _types

    _fsdp = _types.ModuleType("torch.distributed.fsdp")
    _fsdp.FullyShardedDataParallel = type("FullyShardedDataParallel", (), {})
    _fsdp.ShardingStrategy = type("ShardingStrategy", (), {
        "FULL_SHARD": 1, "SHARD_GRAD_OP": 2, "NO_SHARD": 3, "HYBRID_SHARD": 4, "_HYBRID_SHARD_ZERO2": 5
    })
    _fsdp.StateDictType = type("StateDictType", (), {
        "FULL_STATE_DICT": 1, "LOCAL_STATE_DICT": 2, "SHARDED_STATE_DICT": 3
    })

    if "torch.distributed" in _sys.modules:
        _dist = _sys.modules["torch.distributed"]
        if not hasattr(_dist, "fsdp"):
            _dist.fsdp = _fsdp
    else:
        _dist = _types.ModuleType("torch.distributed")
        _dist.fsdp = _fsdp
        _dist.is_available = lambda: False
        _dist.is_initialized = lambda: False
        _dist.init_process_group = lambda **kw: None
        _dist.get_rank = lambda: -1
        _dist.get_world_size = lambda: 1
        _sys.modules["torch.distributed"] = _dist
        _sys.modules["torch.distributed.fsdp"] = _fsdp


def _preload_torch():
    """在 MAIN THREAD 上预加载 torch，避免子线程中触发 Windows access violation。
    必须在任何后台线程尝试使用 torch 之前调用。"""
    import sys as _sys
    try:
        import torch
        # 尝试加载 torch.distributed —— 即使失败也不影响
        try:
            import torch.distributed
        except Exception:
            pass
        return True
    except Exception as e:
        logger.warning("torch 预加载失败: %s", e)
        return False

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
            from config import resolve_device
            _model = SentenceTransformer(_model_name, device=resolve_device("rag"))
            logger.info("Embedding model ready")
        except ImportError:
            logger.warning("sentence-transformers not installed, RAG disabled")
        except Exception as e:
            err_str = str(e).lower()
            # hf-mirror.com 不稳定时自动回退官方 HuggingFace Hub
            if "hf-mirror" in err_str or "504" in err_str or "502" in err_str or \
               "timeout" in err_str or "connection" in err_str or "reset" in err_str:
                logger.warning(f"hf-mirror.com 下载失败，切换官方源重试: {e}")
                _saved = _os.environ.get("HF_ENDPOINT", "")
                _os.environ["HF_ENDPOINT"] = "https://huggingface.co"
                try:
                    _model = SentenceTransformer(_model_name, device=resolve_device("rag"))
                    logger.info("Embedding model ready (via official HuggingFace)")
                except Exception as e2:
                    logger.warning(f"Embedding model load failed (mirror & official 均失败): {e2}")
                finally:
                    if _saved:
                        _os.environ["HF_ENDPOINT"] = _saved
                    else:
                        _os.environ.pop("HF_ENDPOINT", None)
            else:
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
    track_access: bool = True,
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
        if _load_attempted:
            logger.debug("RAG search skipped: model unavailable (load previously attempted)")
        return []

    q_vec = embed(query)
    if q_vec is None:
        return []

    try:
        from brain.graph_memory import _get_conn
        conn = _get_conn()

        if category:
            rows = conn.execute(
                """SELECT id, content, category, source, strength, embedding,
                          created_at, updated_at, source_channel, quality_score,
                          review_status, access_count
                   FROM memory_facts
                   WHERE embedding IS NOT NULL AND category = ? AND status='active'
                   ORDER BY strength DESC""",
                (category,)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, content, category, source, strength, embedding,
                          created_at, updated_at, source_channel, quality_score,
                          review_status, access_count
                   FROM memory_facts
                   WHERE embedding IS NOT NULL AND status='active'
                   ORDER BY strength DESC"""
            ).fetchall()

        if not rows:
            return []

        evidence_counts = {
            int(row["fact_id"]): int(row["evidence_count"])
            for row in conn.execute(
                """SELECT fact_id, COUNT(*) AS evidence_count
                   FROM memory_fragments WHERE status='active' GROUP BY fact_id"""
            ).fetchall()
        }

        # 批量计算余弦相似度
        results = []
        for r in rows:
            emb = r["embedding"]
            if emb is None:
                continue
            mem_vec = np.frombuffer(emb, dtype=np.float32)
            sim = float(np.dot(q_vec, mem_vec))
            if sim >= threshold:
                timestamp = r["updated_at"] or r["created_at"] or ""
                recency = 0.0
                try:
                    age_days = max(0, (datetime.now() - datetime.strptime(
                        timestamp, "%Y-%m-%d %H:%M:%S"
                    )).days)
                    recency = max(0.0, 1.0 - age_days / 180.0)
                except (TypeError, ValueError):
                    pass
                strength_score = min(max(int(r["strength"] or 1), 1), 5) / 5.0
                quality_score = min(1.0, max(0.0, float(r["quality_score"] or 0.5)))
                combined = (
                    sim * 0.75 + quality_score * 0.10
                    + recency * 0.10 + strength_score * 0.05
                )
                results.append((combined, {
                    "memory_id": r["id"],
                    "content": r["content"],
                    "category": r["category"],
                    "source": r["source"],
                    "strength": r["strength"],
                    "semantic_similarity": sim,
                    "updated_at": timestamp,
                    "source_channel": r["source_channel"],
                    "evidence_count": evidence_counts.get(int(r["id"]), 0),
                    "quality_score": quality_score,
                    "review_status": r["review_status"] or "normal",
                    "access_count": int(r["access_count"] or 0),
                }))

        results.sort(key=lambda x: x[0], reverse=True)
        ranked = results[:top_k]
        try:
            from brain.memory_conflicts import get_fact_relations
            for _score, memory in ranked:
                memory["fact_relations"] = get_fact_relations(memory["memory_id"])
        except Exception:
            pass
        if track_access and ranked:
            try:
                from brain.memory_quality import record_memory_access
                record_memory_access([memory["memory_id"] for _score, memory in ranked])
            except Exception:
                pass
        return ranked

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
    results = search_similar(
        content, top_k=1, threshold=threshold, category=category,
        track_access=False,
    )
    return results[0] if results else None


def format_rag_context(memories: list[tuple[float, dict]]) -> str:
    """将检索到的记忆格式化为 LLM 可读的提示文本。"""
    if not memories:
        return ""
    lines = ["【你可能记得的相关信息】"]
    for sim, mem in memories:
        source = mem.get("source_channel") or mem.get("source") or "unknown"
        updated = mem.get("updated_at") or "时间未知"
        semantic = mem.get("semantic_similarity", sim)
        lines.append(
            f"· [记忆#{mem.get('memory_id', '?')}] {mem['content']} "
            f"(语义相关:{semantic:.0%}, 更新:{updated}, 来源:{source}, "
            f"证据:{mem.get('evidence_count', 0)}条, "
            f"质量:{float(mem.get('quality_score', 0.5)):.0%})"
        )
        for relation in mem.get("fact_relations", []):
            if relation.get("relation") != "contradicts":
                continue
            memory_id = int(mem.get("memory_id", 0) or 0)
            if int(relation.get("source_fact_id", 0)) == memory_id:
                other_id = relation.get("target_fact_id")
                other_content = relation.get("target_content", "")
            else:
                other_id = relation.get("source_fact_id")
                other_content = relation.get("source_content", "")
            lines.append(
                f"  ⚠ 与记忆#{other_id}存在已识别的语义矛盾：{other_content}。"
                "不得擅自选择其中一条，应保留不确定性或向用户确认。"
            )
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
                """SELECT id, content FROM memory_facts
                   WHERE embedding IS NULL AND status='active'"""
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
                    """UPDATE memory_facts SET embedding = ?,
                       embedding_model='BAAI/bge-small-zh-v1.5', embedding_version=1
                       WHERE id = ?""",
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
        if _model is not None:
            logger.info("RAG embedding model warmed up successfully")
        else:
            logger.warning("RAG embedding model warmup failed or unavailable")
    t = threading.Thread(target=_load, daemon=True)
    t.start()
