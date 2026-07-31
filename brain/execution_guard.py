"""Prevent final answers from claiming external work that did not succeed."""

from __future__ import annotations

import re
from typing import Iterable


def _succeeded(audit: Iterable[dict], names: set[str]) -> bool:
    return any(
        item.get("name") in names and not item.get("is_error", False)
        for item in audit
    )


def validate_execution_claims(content: str, request_text: str, audit: Iterable[dict],
                              *, capabilities: Iterable[str] = (), mode: str = "") -> str:
    """Replace only high-risk unsupported completion claims with an honest result.

    This deliberately does not police ordinary opinions or conversational wording.
    It is limited to web/file/memory/configuration operations the user explicitly asked for.
    """
    text = str(content or "")
    request = str(request_text or "")
    events = list(audit or ())
    capability_set = set(capabilities or ())

    if re.search(r"(?:搜索|联网|查最新|查一下|资料|新闻)", request):
        claims = re.search(r"(?:我|已经|刚刚).{0,10}(?:搜索|查到|检索|浏览)", text)
        if claims and not _succeeded(events, {"web_search", "fetch_webpage"}):
            return "我这次没有成功取得联网检索结果，所以不能把内容说成已经查到。"

    if re.search(r"(?:读取|打开|查看|分析).{0,16}(?:文件|文档|pdf|docx|路径)", request, re.I):
        claims = re.search(r"(?:已经|我已|刚刚).{0,12}(?:读取|打开|查看|分析)", text)
        if claims and not _succeeded(events, {"read_file", "read_file_chunk", "read_file_lines"}):
            return "我这次没有成功读取到目标文件，不能假装已经看过它。"

    if re.search(r"(?:保存|写入|修改|编辑|创建).{0,16}(?:文件|记忆|配置|设置)", request):
        claims = re.search(r"(?:已经|我已|刚刚).{0,12}(?:保存|写入|修改|编辑|创建|启用|停用)", text)
        if claims and not _succeeded(events, {
            "write_file", "edit_file", "save_memory", "update_memory", "delete_memory",
            "request_enable_tool",
        }):
            return "这项修改没有成功执行，因此我不能把它说成已经保存或生效。"

    # A memory lookup can identify the city, but it cannot establish live weather.
    if "weather" in capability_set:
        weather_facts = re.search(
            r"(?:\d+\s*(?:℃|度)|降水|雷阵雨|暴雨|大雨|中雨|小雨|晴转|阴转|[东南西北]风)",
            text,
        )
        if weather_facts and not _succeeded(events, {"get_weather"}):
            return "我已取得地点相关的记忆，但本轮没有成功查询实时天气，不能直接给出温度、降雨或风力结论。"

    if mode == "TASK_DISCOVERY" or "web_search" in capability_set:
        search_claim = re.search(r"(?:我|已经|刚刚|这次).{0,12}(?:搜了一圈|搜索了|检索到|查到)", text)
        if search_claim and not _succeeded(events, {"web_search", "fetch_webpage"}):
            return "本轮没有成功完成联网检索，不能把内容说成是刚刚搜索到的结果。"

    return text
