"""请求模式、强信号路由与渐进式能力发现。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class RequestMode(str, Enum):
    CHAT_LIGHT = "CHAT_LIGHT"
    CHAT_MEMORY = "CHAT_MEMORY"
    TASK_DIRECT = "TASK_DIRECT"
    TASK_DISCOVERY = "TASK_DISCOVERY"
    TASK_CONTINUATION = "TASK_CONTINUATION"


CAPABILITY_TO_TOOLS: dict[str, set[str]] = {
    "memory_read": {"search_graph_memory", "search_conversation_history", "search_cross_session"},
    "memory_write": {"save_memory", "update_memory", "delete_memory", "review_memory_conflict"},
    "time": {"get_current_time"},
    "web_search": {"web_search"},
    "web_fetch": {"fetch_webpage"},
    "file_read": {"read_file", "read_file_chunk", "read_file_lines", "search_files_everything"},
    "file_write": {"write_file", "edit_file"},
    "code": {"search_code", "code_structure", "code_goto_def", "code_find_refs", "code_diagnostics",
             "run_python_code", "run_command", "run_shell", "git_status"},
    "office": {"read_excel", "write_excel", "copy_excel_content", "write_docx", "format_document"},
    "image": {"ocr_image", "ocr_batch", "describe_image", "capture_from_camera", "capture_desktop",
              "generate_image", "generate_video"},
    "system": {"open_app", "get_clipboard", "send_file_to_qq", "plan_tasks", "delegate_task", "track_tasks"},
    "todo": {"add_todo", "list_todos", "complete_todo"},
    "weather": {"get_weather", "set_user_city"},
    "bilibili": {"bilibili_search", "bilibili_add_tag", "bilibili_list_tags"},
    "time_capsule": {"read_diary", "write_diary"},
    "embodied": {"navigate_to_marker", "move_snake", "cancel_embodied_task", "get_embodied_status"},
}

CAPABILITY_DESCRIPTIONS = {
    "memory_read": "读取已确认的长期记忆或历史会话",
    "memory_write": "按用户明确要求写入或修改长期记忆",
    "time": "查询精确日期、时间、农历或节日",
    "web_search": "搜索实时网络资料",
    "web_fetch": "读取指定网页正文",
    "file_read": "查找并读取本地文件",
    "file_write": "创建或修改本地文件",
    "code": "分析、运行、修改或测试代码",
    "office": "处理 Word、Excel 等办公文档",
    "image": "识别、理解或生成图像媒体",
    "system": "操作应用、剪贴板或执行复杂任务",
    "todo": "管理待办清单",
    "weather": "查询实时天气",
    "bilibili": "搜索或管理 B 站内容",
    "time_capsule": "读取或写入时间胶囊日记",
    "embodied": "在莲心虚拟世界中导航、移动或查询贪吃蛇执行状态",
}

_URL_RE = re.compile(r"https?://\S+", re.I)
_WINDOWS_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|\\\\)[^\n\r\t]+")
_FILE_EXT_RE = re.compile(r"\.(?:pdf|docx?|xlsx?|pptx?|md|txt|csv|json|py|js|ts|html|log)\b", re.I)
_CONTINUATION_RE = re.compile(r"^(?:那就|就按|继续|接着|再试|换一个|第二个|用它|开始吧|执行吧|试试)")
_NEGATED_SEARCH_RE = re.compile(r"(?:不想|不用|不要|别|停止|取消).{0,4}(?:搜|查|联网|上网)")
_SOCIAL_RE = re.compile(
    r"^(?:早安|早上好|上午好|中午好|下午好|晚上好|晚安|你好|嗨|哈喽|莲心|在吗|"
    r"谢谢|辛苦了|抱抱|想你了|我回来了|你怎么样|今天心情怎么样)[呀啊哦呢嘛吗~～！!。,.， ]*$"
)


@dataclass(frozen=True)
class RequestRoute:
    mode: RequestMode
    capabilities: frozenset[str] = frozenset()
    reason: str = ""

    @property
    def tool_names(self) -> set[str]:
        names: set[str] = set()
        for capability in self.capabilities:
            names.update(CAPABILITY_TO_TOOLS.get(capability, set()))
        return names

    @property
    def is_light(self) -> bool:
        return self.mode == RequestMode.CHAT_LIGHT

    @property
    def uses_memory_context(self) -> bool:
        return self.mode == RequestMode.CHAT_MEMORY or "memory_read" in self.capabilities


@dataclass
class ToolSessionState:
    active: bool = False
    capabilities: set[str] = field(default_factory=set)
    opened_tool_names: set[str] = field(default_factory=set)
    denied_enablements: set[str] = field(default_factory=set)
    last_intent: str = ""

    def begin(self, route: RequestRoute, message: str) -> None:
        if route.mode != RequestMode.TASK_CONTINUATION:
            self.capabilities.clear()
            self.opened_tool_names.clear()
            self.denied_enablements.clear()
        self.active = route.mode in {
            RequestMode.TASK_DIRECT, RequestMode.TASK_DISCOVERY, RequestMode.TASK_CONTINUATION,
        }
        self.capabilities.update(route.capabilities)
        self.opened_tool_names.update(route.tool_names)
        self.last_intent = str(message or "")[:500]


def _looks_like_action(text: str) -> bool:
    return bool(re.search(
        r"(?:帮我|请你|能不能|可以帮|替我|给我|需要你|想让你|麻烦你|怎么查|如何找|"
        r"找一下|看看有没有|有没有人|外面怎么|处理一下|做一个|弄一下)", text
    ))


def _recent_text(messages: Iterable[dict]) -> str:
    """Return a bounded transcript used only for follow-up intent detection."""
    return "\n".join(
        str(item.get("content", ""))[:600]
        for item in list(messages or ())[-6:]
        if isinstance(item, dict)
    )


def _is_city_recall_for_weather(text: str, recent_messages: Iterable[dict]) -> bool:
    """Recognize a short memory follow-up that supplies a city for a weather ask."""
    if not re.search(r"(?:城市|哪[个里]|所在地|住在|地方)", text):
        return False
    return bool(re.search(r"(?:天气|气温|温度|下雨|降水|预报)", _recent_text(recent_messages)))


def classify_request(message: str, *, recent_messages: Iterable[dict] = (),
                     forced_tool: str | None = None,
                     session_state: ToolSessionState | None = None) -> RequestRoute:
    text = str(message or "").strip()
    lowered = text.lower()
    if forced_tool:
        capabilities = {
            capability for capability, names in CAPABILITY_TO_TOOLS.items()
            if forced_tool in names
        }
        return RequestRoute(
            RequestMode.TASK_DIRECT, frozenset(capabilities), "用户从界面手动指定工具"
        )

    if session_state and session_state.active and _CONTINUATION_RE.search(text):
        return RequestRoute(
            RequestMode.TASK_CONTINUATION,
            frozenset(session_state.capabilities),
            "承接上一轮尚未结束的工具任务",
        )

    if any(token in lowered for token in ("时间胶囊", "日记", "共同书页")) and any(
        token in lowered for token in ("记得", "昨天", "前天", "查看", "读", "写", "日记")
    ):
        caps = {"time_capsule"}
        if any(token in lowered for token in ("记得", "回忆", "之前")):
            caps.add("memory_read")
        return RequestRoute(RequestMode.CHAT_MEMORY, frozenset(caps), "时间胶囊或日记回忆")

    if re.search(r"(?:记得|还记得|之前说过|以前聊过|回忆|昨天.*说|前天.*说)", text):
        if _is_city_recall_for_weather(text, recent_messages):
            return RequestRoute(
                RequestMode.TASK_DIRECT,
                frozenset({"memory_read", "weather"}),
                "回忆地点并延续近期天气查询",
            )
        return RequestRoute(RequestMode.CHAT_MEMORY, frozenset({"memory_read"}), "明确回忆历史")
    if re.search(r"(?:请|帮我|你要)?记住|保存到长期记忆|删掉.{0,8}记忆|修改.{0,8}记忆", text):
        return RequestRoute(RequestMode.TASK_DIRECT, frozenset({"memory_write"}), "明确修改长期记忆")

    capabilities: set[str] = set()
    reasons: list[str] = []
    if _URL_RE.search(text):
        capabilities.add("web_fetch")
        reasons.append("包含 URL")
    if _WINDOWS_PATH_RE.search(text) or _FILE_EXT_RE.search(text):
        capabilities.add("file_read")
        reasons.append("包含文件路径或扩展名")
        if re.search(r"(?:修改|编辑|写入|保存|创建|新建|覆盖)", text):
            capabilities.add("file_write")
        if re.search(r"\.(?:docx?|xlsx?|pptx?|csv)\b", text, re.I):
            capabilities.add("office")
    if re.search(r"(?:几点|几号|星期几|周几|农历|节气|什么日期|距离.{0,12}(?:多久|几天))", text):
        capabilities.add("time")
        reasons.append("明确精确时间问题")
    weather_question = re.search(
        r"(?:查|看|告诉我|预报|今天|明天|后天|现在|当地|外面|北京|上海|广州|深圳|杭州|成都|重庆|武汉|西安)"
        r".{0,8}(?:天气|气温|温度|会下雨|会下雪|空气质量)|"
        r"(?:天气|气温|温度|空气质量).{0,8}(?:怎么样|如何|多少|预报|查询|查一下|会不会)",
        text,
    )
    if weather_question:
        capabilities.add("weather")
        reasons.append("明确天气问题")
    if not _NEGATED_SEARCH_RE.search(text) and (
        re.search(r"(?:联网搜索|上网搜索|搜一下|帮我搜|搜索.{0,10}(?:新闻|资料|信息)|查最新|最新新闻|实时消息)", text)
        or re.search(r"(?:给出|附上|提供).{0,5}(?:来源|链接)", text)
    ):
        capabilities.add("web_search")
        reasons.append("明确联网搜索或来源要求")
    if re.search(r"(?:这段代码|代码块|函数|脚本|仓库|git |commit|单元测试|调试|修复.{0,8}(?:bug|代码)|运行.{0,8}(?:代码|脚本))", lowered):
        capabilities.add("code")
        reasons.append("明确代码任务")
    if re.search(r"(?:待办|todo|提醒我|加入清单)", lowered):
        capabilities.add("todo")
        reasons.append("明确待办任务")
    if re.search(r"(?:b站|哔哩哔哩|bilibili)", lowered):
        capabilities.add("bilibili")
        reasons.append("明确 B 站任务")
    if any(token in lowered for token in (
        "坦克", "贪吃蛇", "虚拟世界", "地图标记", "食物", "标记的位置", "标记点", "前往标记", "到达标记",
        "左转", "右转", "急停", "取消任务",
    )):
        capabilities.add("embodied")
        reasons.append("虚拟世界具身任务")

    if capabilities:
        return RequestRoute(RequestMode.TASK_DIRECT, frozenset(capabilities), "；".join(reasons))
    if _SOCIAL_RE.fullmatch(text) or (len(text) <= 18 and not _looks_like_action(text)):
        return RequestRoute(RequestMode.CHAT_LIGHT, frozenset(), "短问候或日常交流")
    if _looks_like_action(text) and not _NEGATED_SEARCH_RE.search(text):
        return RequestRoute(RequestMode.TASK_DISCOVERY, frozenset(), "存在操作意图但领域不确定")
    return RequestRoute(RequestMode.CHAT_LIGHT, frozenset(), "无外部能力强信号，先按纯文本交流")


def normalize_capabilities(values: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for value in values or ():
        key = str(value or "").strip().lower()
        if key in CAPABILITY_TO_TOOLS and key not in normalized:
            normalized.append(key)
    return normalized[:3]


def format_capability_result(capabilities: Iterable[str]) -> str:
    selected = normalize_capabilities(capabilities)
    if not selected:
        return "没有识别到可开放的能力。请改用自然语言回答，或用更准确的能力类别重试一次。"
    lines = ["已为当前任务开放以下能力："]
    for key in selected:
        lines.append(f"- {key}：{CAPABILITY_DESCRIPTIONS[key]}")
    lines.append("请立即使用已开放的真实工具继续任务，不要只描述调用计划。")
    return "\n".join(lines)


REQUEST_TOOLS_DEFINITION = {
    "type": "function",
    "function": {
        "name": "request_tools",
        "description": (
            "纯文本不足以完成当前任务时，按语义申请最多三个能力类别。"
            "闲聊不要调用；申请后必须继续执行真实工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "description": "准备完成的具体任务。"},
                "capabilities": {
                    "type": "array", "items": {"type": "string", "enum": sorted(CAPABILITY_TO_TOOLS)},
                    "maxItems": 3,
                },
                "reason": {"type": "string", "description": "为什么纯文本不足。"},
            },
            "required": ["intent", "capabilities", "reason"],
        },
    },
}
