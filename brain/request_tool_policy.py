"""单次请求的工具边界。

这一层只回答两个问题：当前请求允许模型看到哪些工具，以及某次实际调用
是否得到了用户授权。它不依赖模型自行理解权限，因此可作为最终代码防线。
"""

from __future__ import annotations

import re
from typing import Iterable


URL_RE = re.compile(r"https?://[^\s<>\]\[\)（）。]+", re.IGNORECASE)

NETWORK_READ_TOOLS = {
    "web_search", "fetch_webpage", "fetch_webpage_via_api",
    "fetch_webpage_stealth", "fetch_webpage_browser",
}
URL_FETCH_TOOLS = {"fetch_webpage"}

_NETWORK_CODE_RE = re.compile(
    r"\b(?:requests?|urllib|httpx|aiohttp|socket)\b|https?://",
    re.IGNORECASE,
)

_EXPLICIT_CHANGE_WORDS = (
    "添加", "新增", "删除", "移除", "修改", "更新", "设置", "配置",
    "启用", "开启", "禁用", "停用", "关闭", "取消使用", "调整", "排序", "恢复默认",
    "add", "delete", "remove", "change", "enable", "disable", "reset",
)

_MEMORY_SAVE_WORDS = (
    "记住", "记下来", "保存到长期记忆", "存入长期记忆", "写入长期记忆",
    "save this memory", "remember this",
)


def network_change_requested(text: str) -> bool:
    value = str(text or "").lower()
    has_context = any(token in value for token in (
        "联网", "网络工具", "搜索工具", "抓取工具", "知乎搜索", "tavily", "firecrawl",
    ))
    return has_context and any(token in value for token in _EXPLICIT_CHANGE_WORDS)


def requires_verified_web_content(text: str) -> bool:
    value = str(text or "").lower()
    return bool(extract_urls(value)) or any(token in value for token in (
        "核实正文", "核验正文", "核实原文", "核验原文", "打开原文", "读取正文",
        "抓取正文", "看完正文", "verify the article", "fetch the page",
    ))


def _event_succeeded(event: dict, name: str | None = None) -> bool:
    if name and event.get("name") != name:
        return False
    if event.get("is_error") or event.get("authorized") is False:
        return False
    result = str(event.get("result", "")).lower()
    return not any(token in result for token in (
        "失败", "不可用", "被阻止", "没有返回", "error", "failed", "timeout",
    ))


def has_successful_tool_call(audit: Iterable[dict] | None, names: set[str]) -> bool:
    return any(
        event.get("name") in names and _event_succeeded(event)
        for event in (audit or [])
    )


def has_successful_network_change(audit: Iterable[dict] | None) -> bool:
    return any(
        event.get("name") == "configure_network_tools"
        and str(event.get("args", {}).get("action", "status")).lower() != "status"
        and _event_succeeded(event)
        for event in (audit or [])
    )


def extract_urls(text: str) -> list[str]:
    """提取请求中的 HTTP(S) URL，并保持原始顺序去重。"""
    urls = [
        value.rstrip(".,!?;:'\"，！？；：")
        for value in URL_RE.findall(str(text or ""))
    ]
    return list(dict.fromkeys(value for value in urls if value))


def is_external_lookup_request(text: str) -> bool:
    """是否属于不应被本地文件/RAG 抢占的外部信息请求。"""
    value = str(text or "").lower()
    return bool(extract_urls(value)) or any(token in value for token in (
        "联网", "上网", "网页", "搜索一下", "查一下最新", "最新消息",
        "最新新闻", "实时", "官网", "web search", "search online",
    ))


def request_tool_allowlist(text: str) -> set[str] | None:
    """URL 请求使用严格读取白名单；普通请求返回 ``None``。"""
    if extract_urls(text):
        return set(URL_FETCH_TOOLS) | {"get_current_time"}
    return None


def filter_definitions_for_request(definitions: Iterable[dict], text: str) -> list[dict]:
    """在工具定义注入前应用请求级白名单。"""
    definitions = list(definitions)
    allowed = request_tool_allowlist(text)
    if allowed is None:
        return definitions
    return [
        item for item in definitions
        if item.get("function", {}).get("name", "") in allowed
    ]


def authorize_tool_call(name: str, args: dict, request_text: str,
                        audit: Iterable[dict] | None = None) -> tuple[bool, str]:
    """执行前进行确定性授权，返回 ``(允许, 给模型的原因)``。"""
    request = str(request_text or "")
    lowered = request.lower()

    allowed = request_tool_allowlist(request)
    if allowed is not None and name not in allowed:
        return False, (
            f"本轮是 URL 阅读请求，已阻止无关工具 {name}。"
            "请仅使用 fetch_webpage 获取该 URL 的正文。"
        )

    if (name in NETWORK_READ_TOOLS and network_change_requested(request)
            and not has_successful_network_change(audit)):
        return False, "请先成功完成本轮联网工具配置变更，再执行搜索或网页读取。"

    if name in {"read_file", "read_file_chunk", "read_file_lines"}:
        path = str(args.get("path", ""))
        if extract_urls(path):
            return False, "URL 不是本地文件，请改用 fetch_webpage。"

    if name == "run_python_code" and _NETWORK_CODE_RE.search(str(args.get("code", ""))):
        return False, "禁止用 Python 绕过联网工具路由；请改用 web_search 或 fetch_webpage。"

    if name == "bilibili_add_tag":
        has_bilibili_context = any(token in lowered for token in ("b站", "哔哩哔哩", "bilibili"))
        has_change_intent = any(token in lowered for token in _EXPLICIT_CHANGE_WORDS) or "关注" in lowered
        if not (has_bilibili_context and has_change_intent):
            return False, "添加 B 站兴趣标签会修改用户数据，但用户本轮没有明确授权。"

    if name == "configure_network_tools":
        has_network_context = any(token in lowered for token in (
            "联网", "网络工具", "搜索工具", "抓取工具", "知乎搜索", "tavily", "firecrawl",
        ))
        has_change_intent = any(token in lowered for token in _EXPLICIT_CHANGE_WORDS)
        action = str(args.get("action", "status")).lower()
        if action != "status" and not (has_network_context and has_change_intent):
            return False, "修改联网工具配置需要用户在本轮明确提出启停、排序或恢复默认。"

    if name == "save_memory" and not any(token in lowered for token in _MEMORY_SAVE_WORDS):
        return False, "写入长期记忆需要用户在本轮明确要求‘记住’或‘保存到长期记忆’。"

    if name in {"update_memory", "delete_memory", "review_memory_conflict"}:
        has_memory_context = "记忆" in lowered
        has_change_intent = any(token in lowered for token in _EXPLICIT_CHANGE_WORDS)
        if not (has_memory_context and has_change_intent):
            return False, "修改长期记忆需要用户在本轮明确提出相应操作。"

    return True, ""
