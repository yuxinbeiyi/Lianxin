"""
意图路由器 — 用小模型做意图分类，替换写死的正则匹配。

策略：
- 策略A (默认)：用本地 Ollama 小模型（my-qwen）做一次性意图分类
- 策略B (fallback)：回退到 brain/decision.py 的正则逻辑

输出 RouteResult：route(chat/agent) + needed_tools + tool_choice
"""

import json
import logging
from collections import namedtuple
from typing import Optional

import litellm
litellm.set_verbose = False

from config import get_api_config

logger = logging.getLogger("IntentRouter")

RouteResult = namedtuple("RouteResult", [
    "route",          # "chat" | "agent"
    "needed_tools",   # [工具名列表] or []
    "needed_skills",  # [技能名列表] or []
    "tool_choice",    # str | None — 强制调用的工具名
])

# ── 工具摘要缓存 ──
_cached_tool_summaries: Optional[str] = None


def invalidate_tool_cache():
    """技能变更时清除工具列表缓存。"""
    global _cached_tool_summaries
    _cached_tool_summaries = None


def _build_tool_summaries() -> str:
    """构建路由 prompt 中使用的工具名+描述列表。"""
    global _cached_tool_summaries
    if _cached_tool_summaries is not None:
        return _cached_tool_summaries

    lines = []
    try:
        from brain.tools import TOOL_DEFINITIONS
        for t in TOOL_DEFINITIONS:
            fn = t["function"]
            name = fn["name"]
            desc = fn.get("description", "")
            # 取描述第一句
            short = desc.split("。")[0] if desc else name
            lines.append(f"- {name}: {short}")
    except Exception as e:
        logger.warning(f"构建工具摘要失败: {e}")

    try:
        from brain.skill_manager import _skill_registry
        if _skill_registry:
            lines.append("\n## 技能")
            for name, info in _skill_registry.items():
                desc = info.get("description", "")[:60]
                lines.append(f"- {name}: {desc}")
    except Exception:
        pass

    _cached_tool_summaries = "\n".join(lines)
    return _cached_tool_summaries


# ── 路由 prompt ──

_ROUTER_SYSTEM = """你是莲心AI的意图路由器。分析用户消息，判断它属于闲聊还是需要调用工具/技能。

输出严格的JSON格式，不要输出任何额外文本。"""

_ROUTER_TEMPLATE = """可用工具和技能：
{tool_list}

用户消息："{user_input}"

请输出JSON：
{{
  "route": "chat" 或 "agent",
  "needed_tools": ["需要的工具名"],
  "tool_choice": "如果用户明确要求某个工具则填工具名，否则null"
}}

判断规则：
- chat: 纯闲聊、打招呼、情感表达、简单问答（不需要任何工具）
- agent: 需要操作（拍照、搜索记忆、提醒、写文件、打开应用、查天气、查时间、OCR等）
- needed_tools: 用得到的具体工具名，不确定就全列出来
- tool_choice: 用户说"打开记事本"→"open_application"，用户说"拍照"→"shoulder_photo"，否则null"""


class IntentRouter:
    """轻量意图路由器"""

    def __init__(self):
        cfg = get_api_config()
        self._router_model = (cfg.get("router_model") or "").strip()
        self._use_llm_router = bool(self._router_model)
        self._local_base_url = cfg.get("local_base_url", "http://localhost:11434/v1")

    def route(self, user_input: str) -> RouteResult:
        """对用户消息进行意图路由。"""
        if not user_input or not user_input.strip():
            return RouteResult("chat", [], [], None)

        if self._use_llm_router:
            result = self._route_with_llm(user_input)
            if result is not None:
                return result
            logger.info("LLM 路由失败，回退到规则路由")

        return self._route_with_rules(user_input)

    def _route_with_llm(self, user_input: str) -> Optional[RouteResult]:
        """用小模型做意图分类。失败返回 None。"""
        tool_list = _build_tool_summaries() or "（工具列表未加载）"
        prompt = _ROUTER_TEMPLATE.format(
            tool_list=tool_list,
            user_input=user_input,
        )
        try:
            response = litellm.completion(
                model=f"ollama/{self._router_model}",
                messages=[
                    {"role": "system", "content": _ROUTER_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                api_base=self._local_base_url,
                api_key="ollama",
                temperature=0.1,
                max_tokens=200,
                timeout=10,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)

            route = data.get("route", "chat")
            if route not in ("chat", "agent"):
                route = "chat"

            needed_tools = data.get("needed_tools", [])
            if not isinstance(needed_tools, list):
                needed_tools = []

            needed_skills = data.get("needed_skills", [])
            if not isinstance(needed_skills, list):
                needed_skills = []

            tool_choice = data.get("tool_choice")
            if tool_choice and not isinstance(tool_choice, str):
                tool_choice = None

            logger.info(f"[Router] route={route}, tools={needed_tools}, tool_choice={tool_choice}")
            return RouteResult(route, needed_tools, needed_skills, tool_choice)

        except Exception as e:
            logger.warning(f"[Router] LLM 路由异常: {e}")
            return None

    def _route_with_rules(self, user_input: str) -> RouteResult:
        """回退到规则路由 (decision.py)。"""
        from brain.decision import decide
        result = decide(user_input)
        return RouteResult(result, [], [], None)


# ── 全局单例 ──

_router: Optional[IntentRouter] = None


def get_router() -> IntentRouter:
    """获取路由器单例。"""
    global _router
    if _router is None:
        _router = IntentRouter()
    return _router
