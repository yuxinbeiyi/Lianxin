"""
上下文压缩模块 — 解决长对话记忆丢失问题。

两种场景：
1. 启动压缩：新会话启动时，将上一会话的对话历史压缩为结构化摘要
2. 运行时压缩：对话过长时压缩早期消息，保留最近 N 轮完整消息

压缩使用本地 Ollama 小模型（零成本），失败时回退到简单截断。
"""

import json
import logging
import socket
from typing import Optional

import litellm
litellm.set_verbose = False

from config import get_api_config

logger = logging.getLogger("ContextCompressor")

# ── 常量 ──
TOKEN_THRESHOLD = 100_000         # 运行时压缩触发阈值（真实 token 数）
MAX_KEEP_ROUNDS = 12              # 压缩时保留的最近对话轮数
COMPRESS_SUMMARY_PATH_TEMPLATE = "compress_session_{session_id}.json"
COMPRESS_COOLDOWN = 600           # 压缩冷却时间（秒），防止频繁尝试

# ── 压缩 prompt ──

_COMPRESS_SYSTEM = """你是莲心AI的记忆压缩助手。将对话历史压缩为结构化摘要。
只输出JSON，不要输出其他内容。"""

_COMPRESS_USER = """请将以下对话历史压缩为四个分区的摘要：

1. 关键事实：对话中提到的客观事实、信息
2. 用户偏好：用户表达的喜好、习惯、兴趣
3. 待办事项：用户提到要做的事、计划、提醒
4. 最近状态：最近的话题、情绪、活动

要求：
- 每个分区用1-3句话概括
- 只记录值得长期记住的信息
- 忽略寒暄和纯互动内容
- 用中文输出

对话历史：
{history_text}

输出JSON：
{{"关键事实": "...", "用户偏好": "...", "待办事项": "...", "最近状态": "..."}}"""

# 在文件头部 import 区域之后、_last_compress_time 之前，新增：
def _should_use_ollama() -> bool:
    """检查用户是否在配置中明确启用了本地 Ollama 模型。"""
    try:
        return get_api_config().get("use_local", False)
    except Exception:
        return False
_last_compress_time = 0  # 上次尝试压缩的时间戳


def _ollama_available(host: str = "localhost", port: int = 11434, timeout: float = 1.0) -> bool:
    """快速检测 Ollama 服务是否可用。"""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def _estimate_tokens(messages: list) -> int:
    """使用 litellm token_counter 精确估算 token 数。失败时回退到字符估算。"""
    try:
        return litellm.token_counter(model="gpt-4", messages=messages)
    except Exception:
        total_chars = 0
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                total_chars += sum(
                    len(p.get("text", "")) for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
        return int(total_chars * 1.5)


def maybe_compress(
    messages: list,
    model: str = "ollama/my-qwen",
    api_base: str = "http://localhost:11434/v1",
    max_tokens: int = TOKEN_THRESHOLD,
) -> list:
    """
    检查消息列表是否需要压缩。
    超过阈值则把早期消息替换为一条压缩摘要，保留最近消息完整。
    返回（可能压缩后的）消息列表。
    """
    if len(messages) < 20:
        return messages

    estimated = _estimate_tokens(messages)
    if estimated < max_tokens:
        return messages

    # 冷却检查：距离上次压缩尝试不足 COMPRESS_COOLDOWN 秒则跳过
    global _last_compress_time
    now = __import__('time').time()
    if now - _last_compress_time < COMPRESS_COOLDOWN:
        logger.debug(f"[Compress] 距上次压缩仅 {now - _last_compress_time:.0f}s，跳过")
        _last_compress_time = now
        keep_total = (MAX_KEEP_ROUNDS + 6) * 2
        return messages[-keep_total:]  # 直接截断
    _last_compress_time = now

    if not _should_use_ollama():
        logger.info("[Compress] 非本地模型模式，跳过 Ollama 压缩，直接截断")
        keep_total = (MAX_KEEP_ROUNDS + 6) * 2
        return messages[-keep_total:]

    if not _ollama_available():
        logger.info("[Compress] Ollama 未运行，直接截断")
        keep_total = (MAX_KEEP_ROUNDS + 6) * 2
        return messages[-keep_total:]

    logger.info(f"[Compress] 触发运行时压缩: {len(messages)} 条消息, 估算 {estimated} tokens")

    # 分离早期消息和近期消息
    keep_count = MAX_KEEP_ROUNDS * 2  # 每轮 = user + assistant
    if len(messages) <= keep_count + 6:
        return messages  # 不够压缩

    old_messages = messages[:-keep_count]
    recent_messages = messages[-keep_count:]

    # 构建压缩用的文本
    lines = []
    for m in old_messages:
        role = "用户" if m.get("role") == "user" else "莲心"
        content = m.get("content", "")
        if isinstance(content, str) and content.strip():
            lines.append(f"[{role}]: {content[:300]}")

    if not lines:
        return messages

    history_text = "\n".join(lines[-200:])  # 最多最近 200 条摘要

    try:
        response = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": _COMPRESS_SYSTEM},
                {"role": "user", "content": _COMPRESS_USER.format(history_text=history_text)},
            ],
            api_base=api_base,
            api_key="ollama",
            temperature=0.2,
            max_tokens=400,
            timeout=30,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        summary = json.loads(raw)

        # 构建压缩摘要文本
        parts = ["【近期对话摘要】"]
        for key in ["关键事实", "用户偏好", "待办事项", "最近状态"]:
            val = summary.get(key, "")
            if val:
                parts.append(f"{key}：{val}")
        compress_text = "\n".join(parts)

        logger.info(f"[Compress] 压缩完成: {len(old_messages)} 条 → {len(compress_text)} 字摘要")

        # 返回：压缩摘要 + 最近消息
        return [
            {"role": "system", "content": compress_text},
        ] + recent_messages

    except Exception as e:
        logger.warning(f"[Compress] 压缩失败，回退到简单截断: {e}")
        # 回退：保留最近消息
        keep_total = (MAX_KEEP_ROUNDS + 6) * 2
        return messages[-keep_total:]


def compress_previous_session(
    history_text: str,
    model: str = "ollama/my-qwen",
    api_base: str = "http://localhost:11434/v1",
) -> Optional[str]:
    """
    压缩上一会话的对话文本为结构化摘要。
    返回摘要文本，或 None（压缩失败时）。
    """
    if not history_text or len(history_text) < 100:
        return None
    
    if not _should_use_ollama():
        logger.debug("[Compress] 非本地模型模式，跳过上轮会话压缩")
        return None

    if not _ollama_available():
        logger.debug("[Compress] Ollama 未运行，跳过上轮会话压缩")
        return None

    try:
        response = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": _COMPRESS_SYSTEM},
                {"role": "user", "content": _COMPRESS_USER.format(history_text=history_text[:8000])},
            ],
            api_base=api_base,
            api_key="ollama",
            temperature=0.2,
            max_tokens=400,
            timeout=30,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        summary = json.loads(raw)

        parts = ["以下是上次对话的压缩记录："]
        for key in ["关键事实", "用户偏好", "待办事项", "最近状态"]:
            val = summary.get(key, "")
            if val:
                parts.append(f"{key}：{val}")

        logger.info(f"[Compress] 上轮会话压缩完成: {len(history_text)} 字 → {sum(len(p) for p in parts)} 字摘要")
        return "\n".join(parts)

    except Exception as e:
        logger.warning(f"[Compress] 上轮会话压缩失败: {e}")
        return None
