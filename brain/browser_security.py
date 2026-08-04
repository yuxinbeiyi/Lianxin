"""浏览器自动化的风险分级、会话授权和脱敏工具。

这个模块只处理“是否需要用户确认”和“日志/界面应该显示什么”，不参与
Playwright 的实际操作。这样浏览器控制器、AgentCore 和 GUI 可以分别测试。
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


LOW_RISK_TOOLS = {
    "browser_navigate", "browser_snapshot", "browser_screenshot",
    "browser_scroll", "browser_wait", "browser_disconnect",
}
MEDIUM_RISK_TOOLS = {"browser_fill", "browser_press"}
HIGH_RISK_KEYWORDS = (
    "提交", "发送", "删除", "移除", "上传", "支付", "付款", "购买", "下单",
    "发布", "确认", "转账", "提现", "授权", "登录", "退出", "注销",
    "submit", "send", "delete", "remove", "upload", "pay", "purchase",
    "checkout", "publish", "confirm", "transfer", "withdraw", "login", "logout",
)
SENSITIVE_WORDS = (
    "密码", "口令", "验证码", "token", "secret", "cookie", "密钥", "api_key",
    "access_key", "private_key", "authorization", "password", "otp",
)

_SENSITIVE_QUERY_KEYS = re.compile(
    r"^(?:token|access_token|refresh_token|code|key|api[_-]?key|secret|password|auth|session|ticket|sig|signature)$",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_LONG_SECRET_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_./+=-]{32,}(?![A-Za-z0-9])")
_USER_PATH_RE = re.compile(r"([A-Za-z]:[\\/]+Users[\\/])[^\\/\s]+", re.IGNORECASE)


@dataclass(frozen=True)
class BrowserActionRisk:
    tool: str
    level: str
    reason: str
    requires_confirmation: bool


def _ref_text(ref_info: dict[str, Any] | None) -> str:
    if not ref_info:
        return ""
    return " ".join(
        str(ref_info.get(key, ""))
        for key in ("name", "text", "placeholder", "type", "id", "role")
    ).strip()


def classify_browser_action(name: str, args: dict[str, Any] | None = None,
                            ref_info: dict[str, Any] | None = None) -> BrowserActionRisk:
    """给浏览器动作分级。

    读取、滚动和等待默认低风险；填写普通搜索框是中风险；
    涉及提交、发送、删除、上传、支付、登录等语义的动作必须确认。
    """
    name = str(name or "")
    args = args or {}
    text = f"{_ref_text(ref_info)} {args.get('key', '')} {args.get('url', '')}".lower()
    if name == "browser_connect":
        return BrowserActionRisk(name, "high", "接管已打开浏览器可能暴露当前页面和登录状态", True)
    if name in LOW_RISK_TOOLS:
        return BrowserActionRisk(name, "low", "读取或浏览页面", False)
    if name == "browser_tabs":
        action = str(args.get("action", "list") or "list").lower()
        if action == "close":
            return BrowserActionRisk(name, "high", "关闭浏览器标签页可能丢失未提交内容", True)
        return BrowserActionRisk(name, "low", "查看或切换浏览器标签页", False)
    if name == "browser_click":
        if any(word in text for word in HIGH_RISK_KEYWORDS):
            return BrowserActionRisk(name, "high", "该控件可能会提交、发送、删除或产生外部影响", True)
        return BrowserActionRisk(name, "medium", "点击页面控件", False)
    if name == "browser_fill":
        ref_text = _ref_text(ref_info).lower()
        value = str(args.get("text", ""))
        sensitive = any(word in f"{ref_text} {value}" for word in SENSITIVE_WORDS)
        password_field = bool(ref_info and str(ref_info.get("type", "")).lower() == "password")
        if sensitive or password_field:
            return BrowserActionRisk(name, "high", "输入内容可能包含密码、验证码或其他敏感信息", True)
        return BrowserActionRisk(name, "medium", "向网页输入文字", False)
    if name == "browser_press":
        key = str(args.get("key", "")).lower()
        if key in {"enter", "return"} and any(word in text for word in HIGH_RISK_KEYWORDS):
            return BrowserActionRisk(name, "high", "按键可能提交表单或发送内容", True)
        return BrowserActionRisk(name, "medium", "向网页发送按键", False)
    return BrowserActionRisk(name, "medium", "执行浏览器交互动作", False)


def redact_url(value: str) -> str:
    """隐藏 URL 查询串中的凭据，同时保留域名和普通参数。"""
    value = str(value or "")
    try:
        parts = urlsplit(value)
        if not parts.query:
            return value
        pairs = []
        for key, val in parse_qsl(parts.query, keep_blank_values=True):
            pairs.append((key, "[REDACTED]" if _SENSITIVE_QUERY_KEYS.match(key) else val))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))
    except Exception:
        return value


def redact_browser_text(value: Any, *, tool: str = "", max_chars: int | None = None) -> str:
    """用于 GUI 预览和日志的浏览器文本脱敏。"""
    text = str(value or "")
    if tool == "browser_fill":
        text = f"[已脱敏输入，长度={len(text)}]"
    else:
        text = _USER_PATH_RE.sub(r"\1<user>", text)
        text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
        text = _LONG_SECRET_RE.sub("[REDACTED_TOKEN]", text)
        text = re.sub(r"(?i)(password|passwd|token|secret|api[_-]?key|authorization)\s*[:=]\s*[^\s,;]+",
                      r"\1=[REDACTED]", text)
    if max_chars is not None and len(text) > max_chars:
        text = text[: max(0, max_chars - 3)] + "..."
    return text


def redact_browser_args(name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    result = copy.deepcopy(args or {})
    if name == "browser_fill" and "text" in result:
        value = str(result.get("text") or "")
        result["text"] = f"[REDACTED length={len(value)}]"
    if "url" in result:
        result["url"] = redact_url(result.get("url", ""))
    return result


def append_browser_audit(event: dict[str, Any]) -> None:
    """写入脱敏 JSONL 审计，不抛出异常影响正常任务。"""
    try:
        from brain.browser_task_log import append_event
        append_event(event)
    except Exception:
        pass
