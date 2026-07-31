# brain/mcp/mcp_bridge.py
"""MCP 桥接层 — 连接 MCP 工具与莲心 Function Calling 系统"""

import asyncio
import concurrent.futures
from typing import Optional


async def execute_mcp_tool(tool_name: str, arguments: dict) -> Optional[str]:
    """MCP 工具异步执行入口

    如果 tool_name 以 mcp__ 开头，路由到 MCP Manager；
    否则返回 None，调用方应走原有执行路径。
    """
    if not tool_name.startswith("mcp__"):
        return None

    from brain.mcp.mcp_manager import get_mcp_manager

    manager = get_mcp_manager()
    return await manager.call(tool_name, arguments)


def wrap_as_sync(tool_name: str, arguments: dict, timeout: int = 60) -> str:
    """同步包装 — 在 ThreadPoolExecutor 中桥接异步 MCP 调用

    莲心现有的 _execute_tool_calls_parallel 在 ThreadPoolExecutor 中执行，
    本函数将异步的 MCP 调用包装为同步，使其可以无缝嵌入现有执行流程。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(execute_mcp_tool(tool_name, arguments))

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run_in_new_loop, tool_name, arguments)
        return future.result(timeout=timeout)


def _run_in_new_loop(tool_name: str, arguments: dict) -> str:
    """在新线程的事件循环中执行异步 MCP 调用"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(execute_mcp_tool(tool_name, arguments))
        if result is None:
            return f'{{"status": "error", "message": "非MCP工具: {tool_name}"}}'
        return result
    finally:
        loop.close()
