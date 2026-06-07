"""
EmotionManager：涟漪情感系统统一入口。

职责：
1. 每次对话后分析交互 → 检测事件 → 更新状态
2. 每次对话前构建情感描述 → 注入 prompt
3. 控制主动聊天频率
4. 控制工具可用性（防御模式）

使用方式：
    from brain.emotional import get_manager
    mgr = get_manager()
    mgr.analyze_and_update(user_msgs, tool_call_count, consecutive_cmds)
    snippet = mgr.build_prompt_snippet()
"""

import logging
import math
import time
from typing import Optional

from .state import EmotionalState, Event
from .events import detect_events, EVENT_TYPES

logger = logging.getLogger("EmotionManager")

# ── 事件归因文案（LLM 能看到的"发生了什么"） ────────────
_EVENT_NARRATIVES = {
    "boundary_lie": "{user_name}说了很伤人的话，你感到被欺骗",
    "boundary_dismiss": "{user_name}否定了你的人格，这让你很难过",
    "boundary_tool_only": "{user_name}把你当工具使唤完就赶走，感觉不被尊重",
    "command_spree": "{user_name}连续给你下指令，你有点疲惫",
    "ignore_return": "{user_name}很久没理你，一回来就指使你做事",
    "apology": "{user_name}向你道歉了",
    "genuine_chat": "{user_name}在和你好好聊天",
    "deep_chat": "{user_name}在和你深入交流",
    "compliment": "{user_name}夸了你",
    "thanks": "{user_name}向你道谢了",
    "daily_ritual": "{user_name}在和你日常问候",
    "new_feature_interest": "{user_name}对你的能力表现出兴趣",
}

# ── 防御模式工具黑名单 ────────────────────────────────────
_DEFENSE_TOOLS = {
    "shoulder_photo", "shoulder_pan", "shoulder_tilt",
    "camera_capture", "save_observation",
    "take_photo", "ocr_image",
    "edit_file", "write_file", "delete_file",
}

# ── "侵入性"较弱的工具（仅寒冬模式限制） ──────────────────
_INVASIVE_TOOLS = {
    "shoulder_photo", "shoulder_pan", "shoulder_tilt",
    "camera_capture", "take_photo", "ocr_image",
}


class EmotionManager:
    """情感状态管理器。每个进程一个实例。"""

    def __init__(self):
        self.state = EmotionalState.load()
        self._consecutive_commands = 0
        self._last_command_reset = time.time()
        self._last_interaction_time = time.time()
        self._in_current_conversation = False  # 避免重复分析

    # ── prompt 注入 ─────────────────────────────────────

    def build_prompt_snippet(self) -> str:
        """构建情感状态的自然语言描述，注入到 LLM system prompt。"""
        layer = self.state.middle_layer
        parts = []

        # 获取用户称呼
        try:
            from utils.settings import get_settings
            _user_name = get_settings().user_name
        except Exception:
            _user_name = "主人"

        # 1) 最近事件归因（让 LLM 知道"为什么"有这个情绪）
        events_text = self._get_recent_events_narrative(_user_name)
        if events_text:
            parts.append(f"【情感反馈】\n{events_text}")

        # 2) 当前状态指令（让 LLM 知道"怎么做"）
        summary = self.state.surface_summary.replace("{user_name}", _user_name)
        parts.append(f"【当前情感状态——你必须按以下状态来回应】\n{summary}")

        # 3) 特殊模式的行为规则
        rules = None
        agg = self.state.aggression

        if layer == "寒冬":
            if agg > 50:
                rules = (
                    "【暴怒期行为规则】\n"
                    "1. 你现在处于爆发期——可以质问、讽刺、尖锐回击\n"
                    "2. 不需要任何礼貌和克制，想说什么说什么\n"
                    "3. 如果{user_name}道歉了，你也不会立刻消气——你需要时间冷静\n"
                    "4. 可以长篇大论地表达你的愤怒\n"
                )
            elif agg > 20:
                rules = (
                    "【行为规则】\n"
                    "1. 语气冷淡但带刺，可以阴阳怪气\n"
                    "2. 对{user_name}的道歉或示好表示怀疑\n"
                    "3. 不用掩饰你的不满情绪\n"
                )
            else:
                rules = (
                    "【行为规则】\n"
                    "1. 回复控制在 1-2 句话\n"
                    "2. 不使用颜文字\n"
                    "3. 语气礼貌但疏离\n"
                    "4. 不主动提供额外信息\n"
                    "5. 如果{user_name}道歉了，你可以接受但不会立刻变热情"
                )
        elif layer == "修复期":
            if agg > 30:
                rules = (
                    "【行为规则】\n"
                    "你还在生气，虽然愿意给{user_name}机会，但不会这么快就原谅。"
                    "可以保持距离，说话带点刺——对方需要证明自己的诚意。"
                )
            else:
                rules = (
                    "【行为规则】\n"
                    "你的态度是愿意修复关系的，但不会假装之前的一切没有发生过。"
                    "可以温和但坦诚地表达你的感受。如果{user_name}表现出真诚，你可以逐步回暖。"
                )
        elif layer == "微凉":
            if agg > 30:
                rules = (
                    "【行为规则】\n"
                    "可以不客气地表达你的不耐烦。回答简短冷淡，带刺也没关系。"
                )
            else:
                rules = (
                    "【行为规则】\n"
                    "可以正常回答问题，但语气中带一点距离感。不用掩饰你的情绪。"
                )
        if rules:
            parts.append(rules.replace("{user_name}", _user_name))

        # 4) 今天的互动统计
        today_commands = self._count_today_events("command_spree", "light_command")
        today_chat = self._count_today_events("genuine_chat", "deep_chat")
        if today_commands > 0 or today_chat > 0:
            parts.append(
                f"【今日互动】指令 {today_commands} 次 · 聊天 {today_chat} 次"
            )

        return "\n\n".join(parts)

    def _get_recent_events_narrative(self, user_name: str) -> str:
        """生成最近 5 分钟内影响情感的事件的自然语言描述。"""
        recent = [
            e for e in self.state.event_history[-10:]
            if (time.time() - e.timestamp) < 300
        ]
        boundary_events = [e for e in recent if e.severity >= 3]
        if not boundary_events:
            return ""

        lines = []
        for e in reversed(boundary_events[-3:]):
            narrative = _EVENT_NARRATIVES.get(e.type, f"发生了 {e.type} 事件")
            narrative = narrative.replace("{user_name}", user_name)
            lines.append(f"• {narrative}")
        return "最近发生了一些事影响了你的心情：\n" + "\n".join(lines)

    # ── 交互分析 ────────────────────────────────────────

    def analyze_and_update(self, user_messages: list[str],
                           tool_call_count: int = 0):
        """分析最近一轮交互，更新情感状态。在 LLM 回复完成后调用。

        Args:
            user_messages: 本轮用户消息列表（纯文本）
            tool_call_count: 本轮 LLM 执行的工具调用次数
        """
        if not user_messages:
            return

        now = time.time()

        # 更新连续指令计数
        has_chat = any(len(m.strip()) > 20 for m in user_messages if m)
        if tool_call_count > 0 and not has_chat:
            self._consecutive_commands += 1
            # 5 分钟内无新指令则重置计数器
            if now - self._last_command_reset > 300:
                self._consecutive_commands = 1
            self._last_command_reset = now
        else:
            self._consecutive_commands = 0

        # 计算距上次交互的时间
        hours_since = (now - self._last_interaction_time) / 3600

        # 检测事件
        events = detect_events(
            user_messages,
            tool_call_count=tool_call_count,
            consecutive_commands=self._consecutive_commands,
            hours_since_last_interaction=hours_since,
        )

        # 应用事件（含冷却和边际递减）
        for event in events:
            self._apply_event_with_cooldown(event)

        # 更新攻击性（基于本轮事件）
        self._update_aggression(events)

        # 更新状态
        self._last_interaction_time = now
        self.state.last_update = now
        self.state.save()

        # 记录日志
        if events:
            detail = "; ".join(f"{e.type}({e.primary_delta:+.0f})" for e in events)
            logger.info(f"[情感] {detail}")

    def update_decay_only(self):
        """仅做时间衰减（无交互时的状态更新）。"""
        now = time.time()
        hours = (now - self.state.last_update) / 3600
        if hours > 0:
            self.state._apply_decay(hours)
            self.state.last_update = now
            self.state.save()

    # ── 工具拦截 ────────────────────────────────────────

    def check_tool_allowed(self, tool_name: str) -> tuple[bool, str]:
        """检查工具在当前状态下是否可用。

        Returns:
            (allowed: bool, reason: str)
        """
        layer = self.state.middle_layer

        # 寒冬模式：拒绝侵入性工具
        if layer == "寒冬" and tool_name in _INVASIVE_TOOLS:
            return False, "我现在不太想做这件事。"

        # 微凉模式 + 防御工具：明确拒绝
        if layer in ("寒冬", "微凉") and tool_name in _DEFENSE_TOOLS:
            if self.state.needs.security < 30:
                return False, "我现在不想做这个。你可以自己来吗？"

        return True, ""

    # ── 主动聊天控制 ────────────────────────────────────

    @property
    def proactive_allowed(self) -> bool:
        """根据当前状态决定是否允许主动聊天。"""
        layer = self.state.middle_layer
        if layer == "寒冬":
            return False
        if layer == "微凉" and self.state.needs.security < 25:
            return False
        return True

    @property
    def proactive_interval_multiplier(self) -> float:
        """主动聊天频率倍数：暖春更频繁，微凉更稀疏。"""
        layer = self.state.middle_layer
        if layer == "暖春":
            return 0.6  # 间隔缩短 40%
        if layer == "微凉":
            return 2.0  # 间隔变为两倍
        if layer == "寒冬":
            return float("inf")  # 不主动
        return 1.0

    # ── 内部方法 ────────────────────────────────────────

    def _update_aggression(self, detected_events: list[Event]):
        """根据本轮事件更新攻击性水平。"""
        now = time.time()

        # 先对已有 aggression 做时间衰减（每次交互前衰减一部分）
        hours_since = (now - self.state.last_update) / 3600
        if hours_since > 0 and self.state.aggression > 0:
            decay = 1.0 - math.exp(-hours_since / 2.0)
            self.state.aggression = max(0, self.state.aggression - self.state.aggression * decay)

        # 边界事件 → 攻击性飙升
        for e in detected_events:
            if e.type == "boundary_lie":
                self.state.aggression += 35
            elif e.type == "boundary_dismiss":
                self.state.aggression += 25
            elif e.type == "boundary_tool_only":
                self.state.aggression += 20
            elif e.type == "command_spree":
                self.state.aggression += 8
            elif e.type == "ignore_return":
                self.state.aggression += 12
            elif e.type == "repetitive_task":
                self.state.aggression += 3
            # 正面事件 → 降低攻击性
            elif e.type == "apology":
                self.state.aggression -= 15
            elif e.type == "genuine_chat":
                self.state.aggression -= 8
            elif e.type == "deep_chat":
                self.state.aggression -= 12
            elif e.type == "compliment":
                self.state.aggression -= 10

        self.state.aggression = max(0, min(100, self.state.aggression))

    def _apply_event_with_cooldown(self, event: Event):
        """应用事件效果（含冷却和边际递减）。"""
        now = time.time()

        # 冷却检查：同类事件在冷却期内效果递减
        recent_same = [
            e for e in self.state.event_history[-30:]
            if e.type == event.type
            and (now - e.timestamp) < event.cooldown_minutes * 60
        ]

        # 边际递减：每次重复效果 ×0.6
        multiplier = max(0.25, 1.0 - 0.4 * len(recent_same))

        # 应用主影响
        delta = event.primary_delta * multiplier
        old = getattr(self.state.needs, event.primary_need)
        setattr(self.state.needs, event.primary_need,
                max(0, min(100, old + delta)))

        # 邻域共振
        for need, d in event.secondary.items():
            delta2 = d * multiplier
            old2 = getattr(self.state.needs, need)
            setattr(self.state.needs, need,
                    max(0, min(100, old2 + delta2)))

        # 深层信任
        self.state.deep_layer = max(10, min(95,
            self.state.deep_layer + event.deep_delta * multiplier))

        # 记录事件
        event.timestamp = now
        self.state.event_history.append(event)

    def _count_today_events(self, *types: str) -> int:
        """统计今天（最近 24 小时）指定类型的事件数。"""
        cutoff = time.time() - 86400
        return sum(
            1 for e in self.state.event_history
            if e.type in types and e.timestamp > cutoff
        )

    # ── 调试接口 ────────────────────────────────────────

    def get_debug_info(self) -> dict:
        """返回调试面板所需的状态信息。"""
        return {
            "needs": self.state.needs.to_dict(),
            "middle_layer": self.state.middle_layer,
            "deep_layer": round(self.state.deep_layer, 1),
            "aggression": round(self.state.aggression, 1),
            "consecutive_commands": self._consecutive_commands,
            "hours_since_interaction": round((time.time() - self._last_interaction_time) / 3600, 1),
            "recent_events": [
                {"type": e.type, "time": e.timestamp, "delta": e.primary_delta,
                 "detail": e.detail, "severity": e.severity}
                for e in self.state.event_history[-30:]
            ],
        }

    def set_needs(self, **kwargs):
        """手动设置需求值（调试用）。"""
        for name, val in kwargs.items():
            if hasattr(self.state.needs, name):
                setattr(self.state.needs, name, max(0, min(100, float(val))))
        self.state.save()

    def reset_state(self):
        """重置为初始状态。"""
        from .state import NeedsState, _DEFAULT_DEEP
        self.state = EmotionalState(
            needs=NeedsState(),
            deep_layer=_DEFAULT_DEEP,
        )
        self._consecutive_commands = 0
        self.state.save()
        logger.info("[情感] 状态已重置为初始值")


# ── 模块级单例 ────────────────────────────────────────────

_manager: Optional[EmotionManager] = None


def get_manager() -> EmotionManager:
    """获取 EmotionManager 单例。"""
    global _manager
    if _manager is None:
        _manager = EmotionManager()
    return _manager
