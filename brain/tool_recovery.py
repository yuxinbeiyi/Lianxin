"""
tool_recovery.py — 工具错误恢复链
借鉴 NagaAgent: 失败→重试(指数退避)→降级→通知用户
"""

import time
import logging

logger = logging.getLogger("ToolRecovery")

# 重试配置（哪些工具需要重试）
RETRY_CONFIG = {
    "web_search":             {"max_retries": 2, "backoff": 1.5},
    "fetch_webpage":          {"max_retries": 1, "backoff": 2.0},
    "fetch_webpage_via_api":  {"max_retries": 1, "backoff": 2.0},
    "fetch_webpage_browser":  {"max_retries": 0},
    "fetch_webpage_stealth":  {"max_retries": 0},
    # 默认：不重试
}

# 降级映射（当前工具失败后尝试哪个替代工具）
DEGRADE_MAP = {
    "web_search":             "fetch_webpage",
    "fetch_webpage":          "fetch_webpage_via_api",
    "fetch_webpage_via_api":  "fetch_webpage_browser",
}


def execute_with_recovery(
    tool_name: str,
    tool_args: dict,
    executor_fn
) -> tuple[str, int, list[str]]:
    """执行工具，失败时自动重试+降级。

    Args:
        tool_name: 工具名
        tool_args: 工具参数（dict）
        executor_fn: 实际执行函数 callable(name, args) -> str

    Returns:
        (result, total_retries, recovery_log)
        - result: 最终结果
        - total_retries: 尝试次数（含降级）
        - recovery_log: 恢复过程描述列表
    """
    cfg = RETRY_CONFIG.get(tool_name, {"max_retries": 0, "backoff": 0})
    max_retries = cfg.get("max_retries", 0)
    backoff = cfg.get("backoff", 0)
    recovery_log = []
    retries = 0

    # ── 当前工具重试 ──
    current_name = tool_name
    current_args = dict(tool_args)
    for attempt in range(max_retries + 1):
        try:
            result = executor_fn(current_name, current_args)
            if not _is_error_result(result):
                if retries > 0:
                    recovery_log.append(f"{tool_name} 重试 {retries} 次后成功")
                return result, retries, recovery_log
        except Exception as e:
            last_error = str(e)
        else:
            last_error = result  # 错误字符串

        retries += 1
        if attempt < max_retries:
            wait = backoff * (attempt + 1)
            logger.info(f"[Recovery] {current_name} 失败，{wait:.1f}s 后重试 ({attempt+1}/{max_retries})")
            time.sleep(wait)

    recovery_log.append(f"{current_name} 失败 ({retries} 次尝试): {last_error[:100]}")

    # ── 降级路径 ──
    degrade_target = DEGRADE_MAP.get(current_name)
    if degrade_target:
        logger.info(f"[Recovery] {current_name} → 降级到 {degrade_target}")
        try:
            result = executor_fn(degrade_target, current_args)
            if not _is_error_result(result):
                recovery_log.append(f"降级到 {degrade_target} 成功")
                return result, retries + 1, recovery_log
            recovery_log.append(f"降级 {degrade_target} 也失败: {result[:100]}")
        except Exception as e:
            recovery_log.append(f"降级 {degrade_target} 异常: {str(e)[:100]}")

    # ── 全部失败 ──
    recovery_log.append(f"所有恢复路径已尝试，最终失败")
    return f"[工具失败] {tool_name}: {last_error[:200]}（已尝试 {retries} 次重试）", retries, recovery_log


def _is_error_result(result: str) -> bool:
    """判断工具返回是否为错误。"""
    if not result:
        return True
    if result.startswith("[拒绝]") or result.startswith("[工具失败]"):
        return True
    if result.startswith("工具执行错误:") or result.startswith("未知工具:"):
        return True
    if "MCP工具调用失败" in result:
        return True
    return False


def should_recover(tool_name: str) -> bool:
    """是否需要走恢复链。"""
    cfg = RETRY_CONFIG.get(tool_name, {"max_retries": 0})
    return cfg.get("max_retries", 0) > 0 or tool_name in DEGRADE_MAP
