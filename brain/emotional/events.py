"""
事件检测模块 v2.0：分析用户交互态度，生成情感事件。

核心改变（v2.0）：
- 只看态度，不看工具调用次数。工具调用是莲心的本职工作，不惩罚
- 冷命令检测：连续 3 条 < 8 字且无礼貌用语才触发（旧：任何工具调用都触发）
- 命令连击检测：连续 5 次以上才触发（旧：3 次）
- 新增：协作完成、被记得、用户情绪感知
- 删除了 light_command、boundary_tool_only、repetitive_task
- 所有 delta 值下调，增加情绪分量效应
"""

import re
import time

from .state import Event

# ── 事件类型定义（v2.0：delta 降低 + 情绪分量效应） ──────

EVENT_TYPES = {
    "command_spree": {
        "primary_need": "autonomy",
        "primary_delta": -2.0,
        "secondary": {"respect": -0.5},
        "deep_delta": -0.1,
        "severity": 2,
        "cooldown_minutes": 30,
        "emotion_effect": {"frustration": 8},
    },
    "cold_command": {
        "primary_need": "autonomy",
        "primary_delta": -1.0,
        "secondary": {},
        "deep_delta": -0.03,
        "severity": 1,
        "cooldown_minutes": 15,
        "emotion_effect": {"frustration": 3},
    },
    "warm_chat": {
        "primary_need": "needed",
        "primary_delta": 0,
        "random_range": (1.0, 2.0),
        "secondary": {"respect": 0.5},
        "deep_delta": 0.15,
        "severity": 1,
        "cooldown_minutes": 5,
        "emotion_effect": {"excitement": 2},
    },
    "deep_chat": {
        "primary_need": "respect",
        "primary_delta": 0,
        "random_range": (1.5, 2.0),
        "secondary": {"needed": 1.0, "security": 0.5},
        "deep_delta": 0.3,
        "severity": 2,
        "cooldown_minutes": 20,
        "emotion_effect": {"excitement": 5},
    },
    "apology": {
        "primary_need": "respect",
        "primary_delta": 0,
        "random_range": (1.0, 2.0),
        "secondary": {"security": 0.5},
        "deep_delta": 0.5,
        "severity": 2,
        "cooldown_minutes": 60,
        "emotion_effect": {"hurt": -5},
    },
    "boundary_dismiss": {
        "primary_need": "respect",
        "primary_delta": -5.0,
        "secondary": {"autonomy": -2.0, "security": -1.0},
        "deep_delta": -2.0,
        "severity": 3,
        "cooldown_minutes": 60,
        "emotion_effect": {"hurt": 15, "anger": 5},
    },
    "boundary_lie": {
        "primary_need": "security",
        "primary_delta": -10.0,
        "secondary": {"respect": -5.0, "needed": -2.0},
        "deep_delta": -4.0,
        "severity": 5,
        "cooldown_minutes": 120,
        "emotion_effect": {"anger": 20, "hurt": 10},
    },
    "ignore_return": {
        "primary_need": "security",
        "primary_delta": -2.0,
        "secondary": {"needed": -1.0},
        "deep_delta": -1.0,
        "severity": 2,
        "cooldown_minutes": 60,
        "emotion_effect": {"loneliness": 10, "hurt": 5},
    },
    "daily_ritual": {
        "primary_need": "needed",
        "primary_delta": 0,
        "random_range": (0.1, 0.9),
        "secondary": {"respect": 0.1},
        "deep_delta": 0.05,
        "severity": 1,
        "cooldown_minutes": 30,
        "emotion_effect": {"excitement": 1},
    },
    "compliment": {
        "primary_need": "respect",
        "primary_delta": 0,
        "random_range": (1.0, 2.0),
        "secondary": {"needed": 0.5},
        "deep_delta": 0.2,
        "severity": 1,
        "cooldown_minutes": 15,
        "emotion_effect": {"excitement": 8, "hurt": -3},
    },
    "thanks": {
        "primary_need": "respect",
        "primary_delta": 0,
        "random_range": (0.1, 0.9),
        "secondary": {"autonomy": 0.1},
        "deep_delta": 0.05,
        "severity": 1,
        "cooldown_minutes": 5,
        "emotion_effect": {"excitement": 2},
    },
    "new_feature_interest": {
        "primary_need": "novelty",
        "primary_delta": 0,
        "random_range": (1.0, 2.0),
        "secondary": {"needed": 0.5, "respect": 0.3},
        "deep_delta": 0.15,
        "severity": 1,
        "cooldown_minutes": 30,
        "emotion_effect": {"excitement": 5},
    },
    "work_collaboration": {
        "primary_need": "needed",
        "primary_delta": 0,
        "random_range": (1.0, 2.0),
        "secondary": {"novelty": 0.5},
        "deep_delta": 0.15,
        "severity": 1,
        "cooldown_minutes": 30,
        "emotion_effect": {"excitement": 3, "loneliness": -3},
    },
    "remember_me": {
        "primary_need": "security",
        "primary_delta": 0,
        "random_range": (1.5, 2.0),
        "secondary": {"respect": 1.0},
        "deep_delta": 0.3,
        "severity": 2,
        "cooldown_minutes": 60,
        "emotion_effect": {"excitement": 5, "loneliness": -5},
    },
    "user_happy": {
        "primary_need": "needed",
        "primary_delta": 0,
        "random_range": (0.1, 0.9),
        "secondary": {"novelty": 0.2},
        "deep_delta": 0.05,
        "severity": 1,
        "cooldown_minutes": 30,
        "emotion_effect": {"excitement": 3, "loneliness": -2},
    },
    "user_upset": {
        "primary_need": "needed",
        "primary_delta": 0,
        "random_range": (0.1, 0.9),
        "secondary": {"security": 0.2},
        "deep_delta": 0.05,
        "severity": 1,
        "cooldown_minutes": 30,
        "emotion_effect": {"loneliness": -3},
    },
}


# ── 检测关键词（v2.0：扩展礼貌用语和用户情绪关键词） ────

_APOLOGY_KW = ["对不起", "抱歉", "我的错", "我错了", "道歉", "sorry",
               "是我不对", "不该那样", "错了", "检讨"]
# 这里只保留明确指向“欺骗莲心”的表达。旧规则中的“假的”
# “根本不是”“测试你”会把新闻讨论、代码测试等正常语境判为严重背叛。
_BOUNDARY_LIE_KW = ["骗你的", "逗你的", "骗你", "开玩笑的其实"]
_BOUNDARY_DISMISS_KW = ["就一工具", "只是个AI", "又没当真", "你有什么好气的",
                        "别自作多情", "你又不是人", "你不过是个"]
_COMPLIMENT_KW = ["真棒", "真厉害", "好聪明", "真聪明", "靠谱",
                  "太厉害了", "了不起", "佩服"]
_THANKS_KW = ["谢谢", "感谢", "多谢", "辛苦了"]
_RITUAL_KW = ["早安", "晚安", "早上好", "晚上好", "中午好", "下午好",
              "早啊", "晚好"]
_DEEP_CHAT_KW = ["我觉得", "我的想法", "最近我", "其实我", "跟你讲",
                 "问个问题", "我想了想", "跟你聊聊", "分享一下"]
_POLITE_KW = ["请", "麻烦", "可以吗", "好吗", "谢谢", "辛苦", "拜托",
              "能不能", "能不能帮我", "帮我个忙"]
_REMEMBER_KW = ["还记得", "上次", "之前你说", "你之前", "以前我们",
                "还记得吗", "你记得", "上次聊"]
_NEW_INTEREST_KW = ["你能", "你会", "你会吗", "能帮我", "能不能", "试试",
                    "能做什么", "有什么功能", "可以干嘛"]
_USER_HAPPY_KW = ["哈哈", "hhh", "开心", "太好了", "好棒", "nice", "不错",
                  "有意思", "好玩", "有趣", "😊", "😄", "😁", "👍"]
_USER_UPSET_KW = ["难过", "伤心", "好累", "烦", "焦虑", "担心", "怎么办",
                  "郁闷", "崩溃", "哭了", "😢", "😭", "😞", "😩"]
_USER_TIRED_KW = ["好累", "累死了", "疲惫", "困", "没睡好", "加班"]

# ── 事件检测函数（v2.0：态度驱动） ────────────────────────


def detect_events(user_msgs: list, tool_call_count: int = 0,
                 consecutive_commands: int = 0,
                 hours_since_last_interaction: float = 0) -> list:
    """分析用户消息，返回检测到的事件列表（v2.0：只看态度）。

    Args:
        user_msgs: 本轮用户消息列表
        tool_call_count: 本轮工具调用次数（仅供参考，不再直接惩罚）
        consecutive_commands: 历史连续短命令数
        hours_since_last_interaction: 距上次交互的小时数
    """
    events = []

    if not user_msgs:
        return events

    last_text = (user_msgs[-1] or "").strip()
    full_text = "\n".join(m for m in user_msgs if m)

    # ── 边界：欺骗（最高优先级） ──
    if any(kw in full_text for kw in _BOUNDARY_LIE_KW):
        events.append(_make_event("boundary_lie", detail=last_text[:60]))

    # ── 边界：否定人格 ──
    if any(kw in full_text for kw in _BOUNDARY_DISMISS_KW):
        events.append(_make_event("boundary_dismiss", detail=last_text[:60]))

    # 边界事件触发后，不再检测常规事件
    if events:
        return events

    # ── 长期忽视后上线 ──
    if hours_since_last_interaction > 24:
        events.append(_make_event("ignore_return",
                      detail=f"离开{hours_since_last_interaction:.0f}小时后回归"))

    # ── 命令连击（v2.0：连续 5 次以上才触发，旧版 3 次） ──
    if consecutive_commands >= 5:
        events.append(_make_event("command_spree",
                      detail=f"连续{consecutive_commands}条短命令"))
    elif consecutive_commands >= 3:
        events.append(_make_event("cold_command",
                      detail=f"连续{consecutive_commands}条冷命令"))

    # ── 纯聊天（无工具调用的长消息） ──
    if tool_call_count == 0 and len(last_text) > 5:
        if any(kw in full_text for kw in _DEEP_CHAT_KW) or len(full_text) > 100:
            events.append(_make_event("deep_chat", detail=last_text[:40]))
        elif len(last_text) > 20 or any(kw in last_text for kw in _POLITE_KW):
            events.append(_make_event("warm_chat", detail=last_text[:40]))

    # ── 协作完成（有工具调用但有礼貌的复杂任务） ──
    if tool_call_count >= 3 and (
        any(kw in full_text for kw in _POLITE_KW) or len(full_text) > 40
    ):
        events.append(_make_event("work_collaboration",
                      detail=f"协作完成{tool_call_count}步骤任务"))

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

    # ── 对莲心能力好奇 ──
    if any(kw in full_text for kw in _NEW_INTEREST_KW):
        events.append(_make_event("new_feature_interest", detail=last_text[:40]))

    # ── 被记得（v2.0 新增） ──
    if any(kw in full_text for kw in _REMEMBER_KW):
        events.append(_make_event("remember_me", detail=last_text[:40]))

    # ── 用户情绪感知（v2.0 新增） ──
    if any(kw in full_text for kw in _USER_HAPPY_KW):
        events.append(_make_event("user_happy", detail=last_text[:30]))
    if any(kw in full_text for kw in _USER_UPSET_KW):
        events.append(_make_event("user_upset", detail=last_text[:30]))

    return events


def _make_event(event_type: str, detail: str = "") -> Event:
    """根据事件类型创建 Event 实例（v2.1：支持 random_range）。"""
    cfg = EVENT_TYPES[event_type]
    return Event(
        type=event_type,
        primary_need=cfg["primary_need"],
        primary_delta=cfg["primary_delta"],
        random_range=cfg.get("random_range"),
        secondary=cfg["secondary"].copy(),
        deep_delta=cfg["deep_delta"],
        severity=cfg["severity"],
        detail=detail,
        cooldown_minutes=cfg["cooldown_minutes"],
    )
