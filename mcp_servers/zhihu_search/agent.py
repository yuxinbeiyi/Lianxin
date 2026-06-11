# mcp_servers/zhihu_search/agent.py
# -*- coding: utf-8 -*-
"""知乎搜索 MCP 服务 — 桥接知乎开放平台官方 MCP over SSE

连接到知乎官方 MCP SSE 端点，实现工具调用转发。
API 鉴权由本服务完成，用户只需在配置中填入 Access Secret。
"""

import json
import time
import requests
from typing import Any, Dict, List, Optional

# 将项目根目录纳入 sys.path，确保可以导入 brain.mcp
import sys
from pathlib import Path
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from brain.mcp.mcp_agent_base import MCPAgentBase
from config import get_zhihu_config


class ZhihuSearchMCPService(MCPAgentBase):
    """知乎搜索 MCP 服务"""

    service_name = "global_search"
    display_name = "知乎全网搜索"
    description = "知乎全网搜索 + 热榜查询，来自知乎开放平台"
    version = "1.0.0"
    author = "知乎开放平台"
    icon = "🎓"

    def __init__(self):
        super().__init__()

        cfg = get_zhihu_config()
        self._access_secret = cfg.get("access_secret", "").strip()
        if not self._access_secret:
            print("[MCP] 知乎搜索: 未配置 Access Secret，跳过加载")
            self._connected = False
            return

        self._sse_url = "https://developer.zhihu.com/api/mcp/global_search/v1/sse"
        self._message_url: Optional[str] = None
        self._session_id: Optional[str] = None
        self._connected = False
        self._request_id = 0

        try:
            self._connect()
            if self._connected:
                self._initialize_session()
        except Exception as e:
            print(f"[MCP] 知乎搜索连接失败: {e}")
            self._connected = False

    def _register_tools(self):
        """注册知乎全网搜索工具 — LLM 可见的工具列表"""
        self._add_tool(
            "global_search",
            "知乎全网搜索，覆盖全站文章、问答、话题",
            {
                "query": {"type": "string", "description": "搜索关键词，如 人工智能发展趋势"},
                "count": {"type": "integer", "description": "返回条数，默认 5"},
            },
            required=["query"],
        )
        self._add_tool(
            "zhihu_hot_list",
            "获取知乎实时热榜，返回当前热度最高的内容",
            {"count": {"type": "integer", "description": "返回热榜条数，默认 10"}},
        )

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_secret}",
            "X-Request-Timestamp": str(int(time.time())),
            "Content-Type": "application/json",
        }

    def _connect(self) -> bool:
        """建立 SSE 连接，获取 sessionId 和 message 地址"""
        if not self._access_secret:
            return False

        # SSE 连接，读取第一条 endpoint 事件
        headers = self._get_headers()
        headers["Accept"] = "text/event-stream"

        response = requests.get(
            self._sse_url,
            headers=headers,
            stream=True,
            timeout=30,
        )
        response.raise_for_status()

        # 读取第一条 event: endpoint
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("event: endpoint"):
                continue
            if line.startswith("data: "):
                data = line[6:]
                self._message_url = f"https://developer.zhihu.com{data}"
                if "sessionId=" in data:
                    self._session_id = data.split("sessionId=")[-1]
                self._connected = True
                break

        response.close()
        return self._connected

    def _initialize_session(self):
        """发送 MCP initialize 握手，激活会话"""
        try:
            result = self._request("initialize", {
                "protocolVersion": "2024-11-05",
                "clientInfo": {
                    "name": "lianxin-ai",
                    "version": "1.0.0",
                },
                "capabilities": {},
            })
            print(f"[MCP] 知乎搜索 MCP 会话已初始化")
        except json.decoder.JSONDecodeError:
            # 知乎 MCP over SSE：initialize 返回空 body 视为成功
            # 实际响应通过 SSE 事件流推送
            print(f"[MCP] 知乎搜索 MCP 会话已初始化（空 body 正常响应）")
        except Exception as e:
            print(f"[MCP] 知乎搜索初始化失败: {e}")
            self._connected = False

    def _request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """发送 JSON-RPC 请求到 MCP 服务"""
        if not self._connected or not self._message_url:
            return {"status": "error", "message": "未连接到知乎 MCP 服务"}

        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        resp = requests.post(
            self._message_url,
            headers=self._get_headers(),
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        text = resp.text.strip()
        if not text:
            # 空响应 — 知乎 MCP 的 initialize 会返回空 body，视为成功
            return {}
        data = resp.json()
        return data.get("result", data)

    async def handle_call(self, tool_name: str, arguments: dict) -> str:
        """处理工具调用"""
        if not self._connected:
            return json.dumps({
                "status": "error",
                "message": "知乎搜索服务未连接，请检查 Access Secret 配置",
            }, ensure_ascii=False)

        try:
            result = self._request("tools/call", {
                "name": tool_name,
                "arguments": arguments,
            })
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": f"知乎搜索调用失败: {str(e)}",
            }, ensure_ascii=False)