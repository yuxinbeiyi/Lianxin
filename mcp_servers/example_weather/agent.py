# mcp_servers/example_weather/agent.py
"""天气时间 MCP 服务 — 示例实现

这是一个最小化的 MCP Agent 示例，演示如何：
1. 继承 MCPAgentBase
2. 在 _register_tools() 中注册工具
3. 实现 handle_call() 方法

实际使用时替换 _simulate_call() 为真实的 API 调用。
"""

import json
from datetime import datetime

# 将项目根目录纳入 sys.path，确保可以导入 brain.mcp
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from brain.mcp.mcp_agent_base import MCPAgentBase


class WeatherTimeAgent(MCPAgentBase):
    service_name = "weather_time"
    display_name = "天气时间服务"
    description = "查询天气、预报和时间信息"
    version = "1.0.0"
    author = "lianxin-community"
    icon = "🌤️"

    def _register_tools(self):
        self._add_tool(
            "today_weather",
            "查询今日天气。city 格式为'省 市'如'湖北 武汉'，不传则自动识别。",
            {
                "city": {
                    "type": "string",
                    "description": "城市名，格式：省 市。留空自动识别。",
                }
            },
        )

        self._add_tool(
            "forecast_weather",
            "查询未来天气预报（3天）。参数同 today_weather。",
            {
                "city": {
                    "type": "string",
                    "description": "城市名，格式：省 市。留空自动识别。",
                }
            },
        )

        self._add_tool(
            "get_time",
            "获取当前系统时间。无需参数。",
            {},
        )

    async def handle_call(self, tool_name: str, arguments: dict) -> str:
        city = arguments.get("city", "本地")

        if tool_name == "today_weather":
            result = await self._simulate_call("today_weather", city)
        elif tool_name == "forecast_weather":
            result = await self._simulate_call("forecast_weather", city)
        elif tool_name == "get_time":
            result = await self._get_current_time(city)
        else:
            result = {"status": "error", "message": f"未知工具: {tool_name}"}

        return json.dumps(result, ensure_ascii=False)

    async def _get_current_time(self, city: str) -> dict:
        now = datetime.now()
        return {
            "status": "success",
            "message": f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')}",
            "data": {
                "time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "weekday": ["一", "二", "三", "四", "五", "六", "日"][
                    now.weekday()
                ],
                "city": city,
            },
        }

    async def _simulate_call(self, action: str, city: str) -> dict:
        """模拟 API 调用 — 替换为真实的天气 API"""
        return {
            "status": "success",
            "message": f"{city}天气查询成功（示例数据）",
            "data": {
                "city": city,
                "weather": "晴",
                "temperature": "25°C",
                "humidity": "60%",
                "wind": "东北风 3级",
                "tip": "这是示例数据。请将 _simulate_call() 替换为真实的天气 API 调用。",
            },
        }
