# brain/mcp/mcp_manager.py
"""MCP 管理器 — 统一工具调用路由"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger("MCPManager")


class MCPManager:
    """MCP 管理器单例"""

    def __init__(self):
        self._initialized = False

    def initialize(self, mcp_dir: str = None):
        """启动时初始化：扫描并注册所有 MCP 服务"""
        if self._initialized:
            return
        from brain.mcp.mcp_registry import scan_mcp_services

        registered = scan_mcp_services(mcp_dir)
        if registered:
            print(
                f"[MCP] 初始化完成，已注册 {len(registered)} 个服务: {registered}"
            )
        else:
            print("[MCP] 初始化完成，未发现 MCP 服务（目录为空或不存在）")
        self._initialized = True

    async def call(self, tool_name: str, arguments: dict) -> str:
        """统一调用入口

        根据 tool_name 的 mcp__{service}__{tool} 前缀路由到对应 Agent。
        """
        from brain.mcp.mcp_registry import is_mcp_tool, get_mcp_agent

        service = is_mcp_tool(tool_name)
        if not service:
            return '{"status": "error", "message": "未找到MCP服务: ' + tool_name + '"}'

        agent = get_mcp_agent(service)
        if not agent:
            return '{"status": "error", "message": "MCP服务未加载: ' + service + '"}'

        pure_name = tool_name.split("__", 2)[-1]

        try:
            result = await agent.handle_call(pure_name, arguments)
            return result
        except Exception as e:
            logger.error(f"[MCP] 调用失败: {tool_name} → {e}")
            return '{"status": "error", "message": "MCP调用失败: ' + str(e) + '"}'

    def get_services_info(self) -> List[Dict]:
        from brain.mcp.mcp_registry import MCP_REGISTRY, MANIFEST_CACHE

        result = []
        for name, agent in MCP_REGISTRY.items():
            manifest = MANIFEST_CACHE.get(name, {})
            tool_count = len(getattr(agent, "_tools", []))
            result.append(
                {
                    "name": name,
                    "display_name": manifest.get("displayName", name),
                    "description": manifest.get("description", ""),
                    "version": manifest.get("version", "1.0.0"),
                    "author": manifest.get("author", ""),
                    "tool_count": tool_count,
                    "icon": getattr(agent, "icon", ""),
                }
            )
        return result

    def format_services_prompt(self) -> str:
        services = self.get_services_info()
        if not services:
            return ""

        lines = ["", "【可用的 MCP 外部服务】"]
        lines.append("以下工具以 mcp__ 开头，调用方式与普通工具完全相同：")
        lines.append("")
        for svc in services:
            icon = svc["icon"] + " " if svc["icon"] else ""
            lines.append(f"- {icon}**{svc['display_name']}** ({svc['name']})")
            lines.append(f"  {svc['description']}")
            lines.append(f"  提供 {svc['tool_count']} 个工具")
            lines.append("")
        return "\n".join(lines)

    def shutdown(self):
        from brain.mcp.mcp_registry import unload_all

        unload_all()
        self._initialized = False


_manager: Optional[MCPManager] = None


def get_mcp_manager() -> MCPManager:
    global _manager
    if _manager is None:
        _manager = MCPManager()
    return _manager
