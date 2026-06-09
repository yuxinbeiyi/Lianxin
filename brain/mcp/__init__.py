# brain/mcp/__init__.py
"""莲心AI MCP 子系统 — 统一工具协议支持

提供两类 MCP 服务接入：
- local  : 本地 Python Agent，从 mcp_servers/ 目录加载
- external: 外部 MCP Server，通过 stdio 子进程连接（兼容社区标准）
"""

from brain.mcp.mcp_agent_base import MCPAgentBase, ToolDefinition
from brain.mcp.mcp_registry import (
    scan_mcp_services,
    get_all_mcp_tool_definitions,
    get_mcp_agent,
    is_mcp_tool,
)
from brain.mcp.mcp_manager import get_mcp_manager
from brain.mcp.mcp_bridge import execute_mcp_tool, wrap_as_sync
