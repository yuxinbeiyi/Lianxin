# mcp_servers/zhihu_search/agent.py
# -*- coding: utf-8 -*-
"""知乎全网搜索 MCP 服务 — 基于知乎开放平台 REST API

直接调用 REST 接口，避免 MCP over SSE 会话问题。
API 鉴权：Authorization: Bearer <access_secret>
所有请求都带 X-Request-Timestamp，符合官方要求。
"""

import json
import time
import requests
from typing import Any, Dict

# 将项目根目录纳入 sys.path，确保可以导入
import sys
from pathlib import Path
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from brain.mcp.mcp_agent_base import MCPAgentBase
from config import get_zhihu_config


class ZhihuSearchMCPService(MCPAgentBase):
    """知乎全网搜索 MCP 服务"""

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
            return

        self._base_url = "https://developer.zhihu.com/api/v1/content"

    def _register_tools(self):
        """注册工具 — 和 REST API 对齐参数"""
        self._add_tool(
            "global_search",
            "知乎全网搜索，覆盖全站文章、问答、话题，支持高级过滤语法",
            {
                "query": {"type": "string", "description": "搜索关键词（2-100字）"},
                "count": {"type": "integer", "description": "返回条数，1-20，默认 10"},
                "filter": {"type": "string", "description": "高级过滤表达式，如 host==\"zhihu.com\" AND publish_time>=1778494631"},
                "search_db": {"type": "string", "description": "索引库选择：all/realtime/static，默认 all"},
            },
            required=["query"],
        )
        self._add_tool(
            "zhihu_hot_list",
            "获取知乎实时热榜，返回当前热度最高的内容",
            {"count": {"type": "integer", "description": "返回热榜条数，默认 10"}},
        )

    def _get_headers(self) -> Dict[str, str]:
        """请求头，严格按官方要求：Bearer + X-Request-Timestamp"""
        return {
            "Authorization": f"Bearer {self._access_secret}",
            "X-Request-Timestamp": str(int(time.time())),
            "Content-Type": "application/json",
        }

    async def handle_call(self, tool_name: str, arguments: dict) -> str:
        """REST API 直接调用，没有 SSE 会话问题"""
        if not self._access_secret:
            return json.dumps({
                "status": "error",
                "message": "知乎搜索未配置 Access Secret",
            }, ensure_ascii=False)

        try:
            if tool_name == "global_search":
                result = self._call_global_search(arguments)
            elif tool_name == "zhihu_hot_list":
                result = self._call_hot_list(arguments)
            else:
                result = {"status": "error", "message": f"未知工具: {tool_name}"}

            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            print(f"[MCP] 知乎搜索异常: {e}")
            return json.dumps({
                "status": "error",
                "message": f"知乎搜索调用失败: {str(e)}",
            }, ensure_ascii=False)

    def _call_global_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """调用知乎全网搜索 REST API"""
        url = f"{self._base_url}/global_search"
        params = {"Query": args.get("query", "")}
        if "count" in args:
            params["Count"] = args["count"]
        if "filter" in args and args["filter"]:
            params["Filter"] = args["filter"]
        if "search_db" in args and args["search_db"]:
            params["SearchDb"] = args["search_db"]

        resp = requests.get(
            url,
            params=params,
            headers=self._get_headers(),
            timeout=30,
        )
        if not resp.ok:
            print(f"[MCP] 知乎搜索 {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
        return resp.json()

    def _call_hot_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """调用知乎热榜 REST API"""
        url = f"{self._base_url}/hot_list"
        count = args.get("count", 10)
        params = {"Count": count}

        resp = requests.get(
            url,
            params=params,
            headers=self._get_headers(),
            timeout=30,
        )
        if not resp.ok:
            print(f"[MCP] 知乎热榜 {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
        return resp.json()