"""浏览器 Skill 的单请求任务状态。

BrowserController 负责页面和 Playwright 状态；本模块只负责 Agent 层的任务约束：
单轮单动作、总动作上限、超时、连续失败保护和步骤审计。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from uuid import uuid4
import re

from brain.browser_security import (
    BrowserActionRisk,
    append_browser_audit,
    classify_browser_action,
    redact_browser_text,
)


BROWSER_TOOL_NAMES = frozenset({
    "browser_navigate", "browser_snapshot", "browser_click", "browser_fill",
    "browser_screenshot", "browser_press", "browser_scroll", "browser_wait",
    "browser_tabs", "browser_connect", "browser_disconnect",
})


@dataclass
class BrowserTaskState:
    """一次 Agent 请求内的浏览器任务状态。"""

    task_id: str = field(default_factory=lambda: f"browser_task_{uuid4().hex[:12]}")
    max_actions: int = 20
    max_seconds: float = 300.0
    max_consecutive_failures: int = 3
    started_at: float = field(default_factory=monotonic)
    status: str = "running"
    actions: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    round_index: int = 0
    round_actions: int = 0
    last_action: str = ""
    session_authorized: bool = False
    authorized_risk_levels: set[str] = field(default_factory=set)
    cancel_reason: str = ""
    _last_logged_status: str = field(default="", init=False, repr=False)
    steps: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._last_logged_status = self.status
        append_browser_audit({
            "task_id": self.task_id,
            "event": "started",
            "status": self.status,
            "max_actions": self.max_actions,
            "max_seconds": self.max_seconds,
        })

    @staticmethod
    def is_browser_tool(name: str) -> bool:
        return str(name or "") in BROWSER_TOOL_NAMES

    def begin_round(self) -> None:
        self.round_index += 1
        self.round_actions = 0
        self._check_limits()

    def admit(self, name: str) -> str | None:
        """在执行前检查该浏览器动作是否可以进入当前任务。"""
        if not self.is_browser_tool(name):
            return None
        self._check_limits()
        if self.status != "running":
            return self._blocked_message()
        if self.round_actions >= 1:
            return (
                "[BROWSER_ERROR] code=ONE_ACTION_PER_ROUND recoverable=true "
                "next=browser_snapshot\n"
                "每轮只执行一个浏览器主要动作；前一个动作已经返回了新快照，"
                "请根据新快照在下一轮继续。"
            )
        self.round_actions += 1
        self.actions += 1
        return None

    def risk_for(self, name: str, args: dict | None = None,
                 ref_info: dict | None = None) -> BrowserActionRisk:
        return classify_browser_action(name, args, ref_info)

    def needs_confirmation(self, risk: BrowserActionRisk) -> bool:
        if not risk.requires_confirmation:
            return False
        return not (
            self.session_authorized
            or risk.level in self.authorized_risk_levels
        )

    def approve(self, risk: BrowserActionRisk, remember: bool = False) -> None:
        if remember:
            self.session_authorized = True
            self.authorized_risk_levels.add(risk.level)

    def cancel(self, reason: str = "用户取消浏览器任务") -> None:
        if self.status == "running":
            self.cancel_reason = str(reason or "用户取消浏览器任务")[:120]
            self.status = "cancelled"
            self._emit_status_event_if_changed()

    def record(self, name: str, result: str, is_error: bool = False,
               args: dict | None = None, duration_ms: float | None = None) -> dict:
        """记录动作结果并更新失败熔断状态。"""
        result_text = str(result or "")
        failed = bool(is_error or any(marker in result_text for marker in (
            "[BROWSER_ERROR]", "浏览器导航失败", "点击失败", "填写失败",
            "按键失败", "滚动失败", "等待失败", "标签页操作失败",
            "等待超时", "未找到 ref=", "未找到 page_id=",
        )))
        self.last_action = str(name or "")
        if failed:
            self.failures += 1
            self.consecutive_failures += 1
        else:
            self.consecutive_failures = 0
        step = {
            "step": len(self.steps) + 1,
            "round": self.round_index,
            "tool": name,
            "ok": not failed,
            "result_preview": redact_browser_text(result_text, tool=name, max_chars=240),
            "actions_used": self.actions,
        }
        args = args or {}
        step["ref"] = str(args.get("ref", "")) or None
        step["snapshot_id"] = str(args.get("snapshot_id", "")) or None
        step["url"] = self._extract_value(result_text, "URL:")
        step["duration_ms"] = round(float(duration_ms), 1) if duration_ms is not None else None
        step["error_code"] = self._extract_error_code(result_text) if failed else None
        self.steps.append(step)
        append_browser_audit({
            "task_id": self.task_id,
            "event": "step",
            "step": step["step"],
            "round": self.round_index,
            "tool": name,
            "ok": not failed,
            "result_preview": step["result_preview"],
            "actions_used": self.actions,
            "ref": step["ref"],
            "snapshot_id": step["snapshot_id"],
            "url": step["url"],
            "duration_ms": step["duration_ms"],
            "error_code": step["error_code"],
        })
        self._check_limits()
        if self.status == "running" and self.consecutive_failures >= self.max_consecutive_failures:
            self.status = "failed"
        self._emit_status_event_if_changed()
        return step

    def complete(self) -> None:
        if self.status == "running":
            self.status = "completed"
        self._emit_status_event_if_changed()

    def summary(self) -> str:
        elapsed = max(0.0, monotonic() - self.started_at)
        return (
            f"task_id={self.task_id} status={self.status} actions={self.actions}/"
            f"{self.max_actions} failures={self.failures} elapsed={elapsed:.1f}s"
        )

    def stop_message(self) -> str:
        if self.status == "timed_out":
            return (
                "[BROWSER_ERROR] code=TASK_TIMEOUT recoverable=true\n"
                f"浏览器任务已运行超过 {self.max_seconds:.0f} 秒，已停止。{self.summary()}"
            )
        if self.status == "action_limit":
            return (
                "[BROWSER_ERROR] code=TASK_LIMIT_REACHED recoverable=true\n"
                f"浏览器任务已达到 {self.max_actions} 次动作上限，已停止。{self.summary()}"
            )
        if self.status == "failed":
            return (
                "[BROWSER_ERROR] code=CONSECUTIVE_FAILURES recoverable=true "
                "next=browser_snapshot\n"
                f"浏览器任务连续失败 {self.consecutive_failures} 次，已停止。{self.summary()}"
            )
        if self.status == "cancelled":
            return (
                "[BROWSER_ERROR] code=TASK_CANCELLED recoverable=true\n"
                f"浏览器任务已取消：{self.cancel_reason or '用户取消'}。{self.summary()}"
            )
        return ""

    def _check_limits(self) -> None:
        if self.status != "running":
            return
        if monotonic() - self.started_at >= self.max_seconds:
            self.status = "timed_out"
        elif self.actions >= self.max_actions:
            self.status = "action_limit"
        self._emit_status_event_if_changed()

    def _emit_status_event_if_changed(self) -> None:
        if self.status == self._last_logged_status:
            return
        self._last_logged_status = self.status
        event = {
            "task_id": self.task_id,
            "event": self.status,
            "status": self.status,
            "actions_used": self.actions,
            "failures": self.failures,
            "duration_ms": round(max(0.0, monotonic() - self.started_at) * 1000, 1),
        }
        if self.status == "cancelled":
            event["reason"] = redact_browser_text(self.cancel_reason, max_chars=160)
        append_browser_audit(event)

    @staticmethod
    def _extract_value(text: str, prefix: str) -> str | None:
        for line in str(text or "").splitlines():
            if line.strip().startswith(prefix):
                return redact_browser_text(line.split(":", 1)[1].strip(), max_chars=300)
        return None

    @staticmethod
    def _extract_error_code(text: str) -> str | None:
        match = re.search(r"\[BROWSER_ERROR\]\s+code=([A-Z0-9_]+)", str(text or ""))
        if match:
            return match.group(1)
        return "TOOL_ERROR"

    def _blocked_message(self) -> str:
        return self.stop_message() or (
            "[BROWSER_ERROR] code=TASK_STOPPED recoverable=false\n"
            f"浏览器任务已停止。{self.summary()}"
        )
