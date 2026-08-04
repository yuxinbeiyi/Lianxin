"""网页研究与浏览器交互复合任务的本地状态机。

这个模块只负责顺序与安全边界，不直接发起网络请求，也不替代任何现有
工具。这样普通的 ``web_search``、``fetch_webpage`` 和浏览器任务仍然
可以单独运行，而“先搜索再打开/阅读”会拥有可验证的交接点。
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field


WEB_RESEARCH_TOOLS = {"web_search", "fetch_webpage"}
_BROWSER_TOOLS = {
    "browser_navigate", "browser_snapshot", "browser_click", "browser_fill",
    "browser_press", "browser_scroll", "browser_wait", "browser_tabs",
    "browser_screenshot", "browser_connect", "browser_disconnect",
}


def detect_web_research_mode(text: str) -> tuple[str, bool] | None:
    """返回 ``(mode, takeover)``，无法识别时返回 ``None``。

    ``open_browser`` 表示搜索后把候选 URL 交给浏览器；``read_page`` 表示
    搜索后读取原始网页正文。接管本机浏览器只在用户明确说接管/CDP时启用。
    """
    value = str(text or "")
    if not re.search(r"(?:搜|搜索|查找|检索|联网搜索|上网搜索)", value):
        return None
    if not re.search(r"(?:然后|之后|随后|并|再|搜到后|搜索后)", value):
        return None
    if not re.search(
        r"(?:打开|访问|进入|浏览器|接管|点击|操控|操作|查看|读取|阅读|总结)",
        value,
        re.IGNORECASE,
    ):
        return None
    takeover = bool(re.search(r"(?:接管|CDP|已经打开的浏览器|已打开的浏览器)", value, re.I))
    read_page = bool(re.search(
        r"(?:查看正文|读取正文|阅读原文|读取|阅读|总结页面|总结网页|打开后(?:看看|阅读|总结))",
        value,
        re.I,
    ))
    return ("read_page" if read_page and not takeover else "open_browser", takeover)


@dataclass
class WebResearchTaskState:
    """可审计的两阶段网页任务状态。"""

    mode: str = "open_browser"
    takeover: bool = False
    task_id: str = field(default_factory=lambda: f"web_research_{uuid.uuid4().hex[:10]}")
    phase: str = "search"
    search_count: int = 0
    handoff_count: int = 0
    connected: bool = False
    retry_count: int = 0
    steps: list[dict] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    @classmethod
    def from_request(cls, text: str) -> "WebResearchTaskState | None":
        detected = detect_web_research_mode(text)
        if not detected:
            return None
        mode, takeover = detected
        return cls(mode=mode, takeover=takeover)

    @property
    def status(self) -> str:
        return self.phase

    @property
    def completed(self) -> bool:
        return self.phase == "completed"

    @property
    def expected_tool(self) -> str | None:
        if self.phase == "search":
            return "web_search"
        if self.phase == "handoff":
            if self.takeover and not self.connected:
                return "browser_connect"
            return "fetch_webpage" if self.mode == "read_page" else "browser_navigate"
        return None

    def begin_round(self) -> None:
        """预留给循环调度器的钩子，当前状态机不需要额外计数。"""

    def admit(self, name: str) -> str | None:
        """返回拒绝原因；返回 ``None`` 表示允许执行。"""
        expected = self.expected_tool
        if expected and name != expected:
            if self.phase == "search":
                return "[WEB_RESEARCH_ORDER] 复合网页任务必须先调用 web_search 获取候选来源。"
            return f"[WEB_RESEARCH_HANDOFF] 搜索已完成，下一步必须调用 {expected} 完成交接。"
        if self.phase == "browser" and name in WEB_RESEARCH_TOOLS:
            return "[WEB_RESEARCH_ORDER] 浏览器交互阶段请使用浏览器工具，不要重新搜索或抓取。"
        if self.phase == "completed":
            return "[WEB_RESEARCH_DONE] 复合网页任务已经完成。"
        return None

    def record(self, name: str, result: str, *, is_error: bool = False) -> None:
        self.steps.append({
            "tool": name,
            "phase": self.phase,
            "ok": not is_error,
            "preview": str(result or "")[:300],
            "at": time.time(),
        })
        normalized = str(result or "").lower()
        if is_error or any(token in normalized for token in (
            "搜索失败", "抓取失败", "调用失败", "tool error", "timeout", "error:",
        )):
            return
        if self.phase == "search" and name == "web_search":
            self.search_count += 1
            self.phase = "handoff"
            return
        if self.phase == "handoff":
            expected = self.expected_tool
            if self.takeover and name == "browser_connect" and not self.connected:
                self.connected = True
                return
            if name == expected:
                self.handoff_count += 1
                self.phase = "browser" if self.mode == "open_browser" else "completed"
            return
        if self.phase == "browser" and name == "browser_disconnect":
            self.phase = "completed"

    def next_prompt(self) -> str:
        if self.phase == "search":
            return (
                "复合网页任务尚未开始交接。请先调用 web_search，获取带原始链接的搜索证据；"
                "不要只用文字承诺‘我去搜索’。"
            )
        if self.phase == "handoff":
            expected = self.expected_tool or "fetch_webpage"
            if self.mode == "read_page":
                return (
                    "搜索证据已经返回。请从结果中选择最相关的原始链接，"
                    f"立即调用 {expected} 读取正文，再基于正文回答；不要把摘要冒充原文。"
                )
            if self.takeover:
                if not self.connected:
                    return (
                        "搜索证据已经返回。用户要求接管已打开的浏览器，"
                        "现在必须先调用 browser_connect。"
                    )
                return (
                    "浏览器已经接管成功。请从搜索证据中选择最相关的原始链接，"
                    "立即调用 browser_navigate 打开它，随后用 browser_snapshot 验证页面。"
                )
            return (
                "搜索证据已经返回。请从结果中选择最相关的原始链接，"
                "立即调用 browser_navigate 打开它，随后用 browser_snapshot 验证页面。"
            )
        return "复合网页任务已完成，请仅依据已执行工具的真实结果作答。"

    def stop_message(self) -> str:
        if self.phase == "completed":
            return "网页研究任务已完成。"
        return f"网页研究任务未完成（当前阶段：{self.phase}），不能把计划当成执行结果。"
