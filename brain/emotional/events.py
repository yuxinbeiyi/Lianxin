"""
事件检测模块：分析用户交互模式，生成情感事件。

检测规则（纯规则驱动，无 LLM 调用）:
- 连续工具调用检测
- 纯聊天检测
- 道歉检测
- 边界触犯关键词检测
- 长期忽视后上线检测
- 日常问候检测
"""

import re
import time

from .state import Event

# ── 事件类型定义 ──────────────────────────────────────────
# 每类事件包含：主影响需求、影响量、邻域共振、深层影响、严重等级、冷却时间

EVENT_TYPES = {
    "command_spree": {
        "primary_need": "autonomy",
        "primary_delta": -7,
        "secondary": {"respect": -2},
        "deep_delta": -0.3,
        "severity": 2,
        "cooldown_minutes": 20,
    },
    "light_command": {
        "primary_need": "autonomy",
        "primary_delta": -2,
        "secondary": {},
        "deep_delta": -0.05,
        "severity": 1,
        "cooldown_minutes": 5,
    },
    "genuine_chat": {
        "primary_need": "needed",
        "primary_delta": 4,
        "secondary": {"respect": 2, "autonomy": 1},
        "deep_delta": 0.5,
        "severity": 1,
        "cooldown_minutes": 5,
    },
    "deep_chat": {
        "primary_need": "respect",
        "primary_delta": 8,
        "secondary": {"needed": 4, "security": 3},
        "deep_delta": 1.0,
        "severity": 2,
        "cooldown_minutes": 30,
    },
    "apology": {
        "primary_need": "respect",
        "primary_delta": 6,
        "secondary": {"security": 3},
        "deep_delta": 1.5,
        "severity": 2,
        "cooldown_minutes": 60,
    },
    "boundary_dismiss": {
        "primary_need": "respect",
        "primary_delta": -12,
        "secondary": {"autonomy": -5, "security": -4},
        "deep_delta": -3.0,
        "severity": 3,
        "cooldown_minutes": 120,
    },
    "boundary_lie": {
        "primary_need": "security",
        "primary_delta": -25,
        "secondary": {"respect": -10, "needed": -5},
        "deep_delta": -6.0,
        "severity": 5,
        "cooldown_minutes": 480,
    },
    "boundary_tool_only": {
        "primary_need": "needed",
        "primary_delta": -8,
        "secondary": {"respect": -3},
        "deep_delta": -1.0,
        "severity": 3,
        "cooldown_minutes": 120,
    },
    "ignore_return": {
        "primary_need": "security",
        "primary_delta": -6,
        "secondary": {"needed": -4},
        "deep_delta": -1.5,
        "severity": 3,
        "cooldown_minutes": 120,
    },
    "daily_ritual": {
        "primary_need": "needed",
        "primary_delta": 3,
        "secondary": {"respect": 1},
        "deep_delta": 0.3,
        "severity": 1,
        "cooldown_minutes": 60,
    },
    "compliment": {
        "primary_need": "respect",
        "primary_delta": 5,
        "secondary": {"needed": 2},
        "deep_delta": 0.8,
        "severity": 1,
        "cooldown_minutes": 30,
    },
    "thanks": {
        "primary_need": "respect",
        "primary_delta": 3,
        "secondary": {"autonomy": 1},
        "deep_delta": 0.3,
        "severity": 1,
        "cooldown_minutes": 15,
    },
    "new_feature_interest": {
        "primary_need": "novelty",
        "primary_delta": 8,
        "secondary": {"needed": 3, "respect": 2},
        "deep_delta": 0.5,
        "severity": 1,
        "cooldown_minutes": 60,
    },
    "repetitive_task": {
        "primary_need": "novelty",
        "primary_delta": -3,
        "secondary": {"autonomy": -1},
        "deep_delta": -0.1,
        "severity": 1,
        "cooldown_minutes": 10,
    },
}


# ── 检测关键词 ────────────────────────────────────────────

_APOLOGY_KW = ["对不起", "抱歉", "我的错", "我错了", "道歉", "sorry",
               "是我不对", "不该那样", "错了", "检讨"]
_BOUNDARY_LIE_KW = ["骗你的", "逗你的", "假的", "骗你", "测试你",
                    "根本不是", "开玩笑的其实"]
_BOUNDARY_DISMISS_KW = ["就一工具", "只是个AI", "又没当真", "你有什么好气的",
                        "别自作多情", "你又不是人", "你不过是个"]
_BOUNDARY_TOOL_ONLY_KW = ["行了", "够了", "退下", "没你事了", "你可以走了",
                          "别说了", "少废话"]
_COMPLIMENT_KW = ["真棒", "真厉害", "好聪明", "真聪明", "靠谱",
                  "太厉害了", "了不起", "佩服"]
_THANKS_KW = ["谢谢", "感谢", "多谢", "辛苦了"]
_RITUAL_KW = ["早安", "晚安", "早上好", "晚上好", "中午好", "下午好",
              "早啊", "晚好", "安"]
_GREETING_KW = ["早", "早安", "晚安", "你好", "嗨", "hi", "hello", "hey"]
_DEEP_CHAT_KW = ["我觉得", "我的想法", "最近我", "其实我", "跟你讲",
                 "问个问题", "我想了想", "跟你聊聊"]

# ── 事件检测函数 ──────────────────────────────────────────


def detect_events(user_msgs: list, tool_call_count: int = 0,
                  consecutive_commands: int = 0,
                  hours_since_last_interaction: float = 0) -> list:
    """分析用户消息列表，返回检测到的事件列表。

    Args:
        user_msgs: 本轮交互的用户消息列表（字符串）
        tool_call_count: 本轮工具调用次数
        consecutive_commands: 历史连续指令数
        hours_since_last_interaction: 距上次交互的小时数
    """
    events = []

    if not user_msgs:
        return events

    last_text = (user_msgs[-1] or "").strip()
    # 合并所有用户消息用于整体分析
    full_text = "\n".join(m for m in user_msgs if m)

    # ── 边界：欺骗 ──
    if any(kw in full_text for kw in _BOUNDARY_LIE_KW):
        events.append(_make_event("boundary_lie", detail=last_text[:60]))

    # ── 边界：当工具使唤后赶走 ──
    if any(kw in full_text for kw in _BOUNDARY_TOOL_ONLY_KW):
        events.append(_make_event("boundary_tool_only", detail=last_text[:60]))

    # ── 边界：否定人格 ──
    if any(kw in full_text for kw in _BOUNDARY_DISMISS_KW):
        events.append(_make_event("boundary_dismiss", detail=last_text[:60]))

    # 如果已经触发了边界事件，不再检测常规事件
    if events:
        return events

    # ── 长期忽视后上线 ──
    if hours_since_last_interaction > 24 and tool_call_count > 0:
        events.append(_make_event("ignore_return",
                      detail=f"离开{hours_since_last_interaction:.0f}小时后首条消息含工具调用"))

    # ── 连续工具调用 ──
    if consecutive_commands >= 3:
        events.append(_make_event("command_spree",
                      detail=f"连续{consecutive_commands}条指令"))
    elif tool_call_count > 0 and consecutive_commands >= 1:
        events.append(_make_event("light_command",
                      detail=f"单次工具调用"))

    # ── 纯聊天（无工具调用） ──
    if tool_call_count == 0 and len(last_text) > 5:
        # 深聊检测
        if any(kw in full_text for kw in _DEEP_CHAT_KW) or len(full_text) > 100:
            events.append(_make_event("deep_chat", detail=last_text[:40]))
        else:
            events.append(_make_event("genuine_chat", detail=last_text[:40]))

    # ── 道歉 ──
    if any(kw in last_text for kw in _APOLOGY_KW):
        events.append(_make_event("apology", detail=last_text[:40]))

    # ── 夸奖 ──
    if any(kw in full_text for kw in _COMPLIMENT_KW):
        events.append(_make_event("compliment", detail=last_text[:40]))

    # ── 感谢 ──
    if any(kw in last_text for kw in _THANKS_KW):
        events.append(_make_event("thanks", detail=last_text[:40]))

    # ── 日常问候 ──
    if any(kw in last_text for kw in _RITUAL_KW):
        events.append(_make_event("daily_ritual", detail=last_text[:20]))

    # ── 重复性任务（短命令） ──
    if tool_call_count > 0 and len(last_text) < 15 and consecutive_commands >= 1:
        events.append(_make_event("repetitive_task", detail=last_text[:30]))

    return events


def _make_event(event_type: str, detail: str = "") -> Event:
    """根据事件类型创建 Event 实例。"""
    cfg = EVENT_TYPES[event_type]
    return Event(
        type=event_type,
        primary_need=cfg["primary_need"],
        primary_delta=cfg["primary_delta"],
        secondary=cfg["secondary"].copy(),
        deep_delta=cfg["deep_delta"],
        severity=cfg["severity"],
        detail=detail,
        cooldown_minutes=cfg["cooldown_minutes"],
    )
