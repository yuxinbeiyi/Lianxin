# brain/mcp/mcp_agent_base.py
"""MCP Agent 基类 — 定义本地 MCP 服务必须实现的接口"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ToolDefinition:
    """单个工具的完整定义 — 同时满足 OpenAI Function Calling 和 MCP manifest 格式"""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict,
        required: list = None,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.required = required or []

    def to_openai_format(self, service_name: str) -> dict:
        """转为 OpenAI Function Calling 格式"""
        return {
            "type": "function",
            "function": {
                "name": f"mcp__{service_name}__{self.name}",
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required,
                },
            },
        }


class MCPAgentBase(ABC):
    """MCP Agent 基类

    所有本地 MCP 服务需继承此类，在 _register_tools() 中注册工具。
    每个 MCP 服务 = 一个 Agent 实例 + 一组 ToolDefinition

    示例:
        class WeatherAgent(MCPAgentBase):
            service_name = "weather"
            display_name = "天气服务"

            def _register_tools(self):
                self._add_tool(
                    "today_weather",
                    "查询今日天气",
                    {"city": {"type": "string", "description": "城市名"}},
                    required=["city"],
                )

            async def handle_call(self, tool_name, arguments):
                return await self._weather_api(arguments["city"])
    """

    service_name: str = ""
    display_name: str = ""
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    icon: str = ""

    def __init__(self):
        self._tools: List[ToolDefinition] = []
        self._register_tools()

    def _register_tools(self):
        """子类重写：用 self._add_tool() 注册工具"""
        pass

    def _add_tool(
        self,
        name: str,
        description: str,
        parameters: dict,
        required: list = None,
    ):
        """便捷方法：注册一个工具"""
        self._tools.append(ToolDefinition(name, description, parameters, required))

    @abstractmethod
    async def handle_call(self, tool_name: str, arguments: dict) -> str:
        """处理工具调用 — 子类必须实现

        Args:
            tool_name: 纯工具名（不含 mcp__{service}__ 前缀）
            arguments: LLM 传来的参数字典

        Returns:
            工具执行结果字符串（建议 JSON 格式）
        """
        ...

    def get_tool_definitions_openai(self) -> list:
        """获取所有工具的 OpenAI Function Calling 格式"""
        return [t.to_openai_format(self.service_name) for t in self._tools]

    def get_tool_names(self) -> list:
        """获取工具全名列表"""
        return [f"mcp__{self.service_name}__{t.name}" for t in self._tools]

    async def handle_handoff(self, task: dict) -> str:
        """兼容娜迦风格的统一入口（用于 MCP Manager 路由）

        task 应包含:
            tool_name: 纯工具名
            其余字段作为 arguments 传入 handle_call
        """
        tool_name = task.pop("tool_name", "")
        return await self.handle_call(tool_name, task)

    def cleanup(self):
        """清理资源（子类可重写）"""
        pass
