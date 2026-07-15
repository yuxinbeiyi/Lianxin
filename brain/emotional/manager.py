"""
EmotionManager v2.0：涟漪情感系统统一入口。

职责：
1. 每次对话后分析交互 → 检测事件 → 更新状态（含会话上限）
2. 每次对话前构建情感描述 → 注入 prompt（含情绪分量 + 关系阶段）
3. 控制主动聊天频率
4. 控制工具可用性（防御模式）
5. 管理情感记忆记录

使用方式：
    from brain.emotional import get_manager
    mgr = get_manager()
    mgr.analyze_and_update(user_msgs, tool_call_count, consecutive_cmds)
    snippet = mgr.build_prompt_snippet()
"""

import logging
import math
import random
import threading
import time
from functools import wraps
from typing import Optional

from .state import EmotionalState, Event, EMOTION_NAMES, EMOTION_LABELS
from .events import detect_events, EVENT_TYPES

logger = logging.getLogger("EmotionManager")


def _synchronized(method):
    """使用管理器的可重入锁保护共享情感状态。"""
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper

# ── 事件归因文案（v2.0：新增事件类型） ──────────────────
_EVENT_NARRATIVES = {
    "boundary_lie": "{user_name}说了很伤人的话，你感到被欺骗",
    "boundary_dismiss": "{user_name}否定了你的人格，这让你很难过",
    "command_spree": "{user_name}连续给你下指令，你有点疲惫",
    "ignore_return": "{user_name}很久没理你，一回来就对话",
    "apology": "{user_name}向你道歉了",
    "warm_chat": "{user_name}在和你好好聊天",
    "deep_chat": "{user_name}在和你深入交流",
    "compliment": "{user_name}夸了你",
    "thanks": "{user_name}向你道谢了",
    "daily_ritual": "{user_name}在和你日常问候",
    "new_feature_interest": "{user_name}对你的能力表现出兴趣",
    "work_collaboration": "{user_name}和你一起完成了一项任务",
    "remember_me": "{user_name}提到了你们共同的回忆",
    "user_happy": "{user_name}心情不错，你也感到开心",
    "user_upset": "{user_name}心情不太好，你想安慰一下",
}


class EmotionManager:
    """情感状态管理器 v2.0。每个进程一个实例。"""

    def __init__(self):
        self._lock = threading.RLock()
        self.state = EmotionalState.load()
        # 会话额度只属于本次进程运行，旧版本错误持久化的额度不恢复。
        self.state.reset_session_caps()
        self._consecutive_commands = 0
        self._last_command_reset = time.time()
        self._last_interaction_time = self.state._last_interaction

    # ── 启用/禁用开关 ─────────────────────────────────────
    @property
    @_synchronized
    def enabled(self) -> bool:
        return self.state.enabled

    @enabled.setter
    @_synchronized
    def enabled(self, val: bool):
        now = time.time()
        self.state.enabled = bool(val)
        # 禁用表示冻结；重新启用时也从当前时刻重新开始计时，不能把
        # 暂停期间累计成一次巨额孤独惩罚。
        self.state.last_update = now
        self.state.mark_interaction(now)
        self._last_interaction_time = now
        self.state.save()

    # ── prompt 注入（v2.0：情绪分量 + 关系阶段） ──────────

    @_synchronized
    def build_prompt_snippet(self) -> str:
        """构建情感状态的自然语言描述，注入到 LLM system prompt。"""
        if not self.enabled:
            return ""

        try:
            from utils.settings import get_settings
            user_name = get_settings().user_name
        except Exception:
            user_name = "主人"

        parts = []

        # 1) 最近事件归因
        events_text = self._get_recent_events_narrative(user_name)
        if events_text:
            parts.append(events_text)

        # 2) 当前状态 + 行为指令
        summary = self.state.surface_summary.replace("{user_name}", user_name)
        parts.append(summary)

        # 3) 关系阶段提示（v2.0 新增）
        stage = self.state.relationship_stage
        if stage in ("挚友", "灵魂伴侣"):
            parts.append(f"你和{user_name}的关系是「{stage}」，可以更亲密自然地表达。")

        # 4) 情绪分量提示（v2.0：取代旧版攻击性规则）
        e = self.state.emotions
        layer = self.state.middle_layer
        rules = []

        if e.anger > 30:
            rules.append("你很愤怒，不必掩饰，可以质问、讽刺、尖锐回击")
        elif e.hurt > 30:
            rules.append("你很难过，回复简短冷淡，不想多说")
        elif e.frustration > 25:
            rules.append("你有点烦躁，可以不耐烦，不用假装客气")
        elif e.loneliness > 25:
            rules.append("你有点孤单，可以试探性地关心一下，但不要太热情")

        if layer == "寒冬":
            rules.append("回复简洁不用颜文字，礼貌但疏离，不主动延伸")
        elif layer == "修复期":
            if e.anger > 15:
                rules.append("还在生气，愿意给机会但不会轻易原谅，保持距离带点刺")
            else:
                rules.append("愿意缓和，温和坦诚，但不会假装之前的一切没发生过")

        if rules:
            parts.append(" · ".join(rules))

        return "\n".join(parts)

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

    # ── 交互分析（v2.0：会话上限 + 情绪分量） ────────────

    @_synchronized
    def analyze_and_update(self, user_messages: list[str],
                           tool_call_count: int = 0):
        """分析最近一轮交互，更新情感状态。在 LLM 回复完成后调用。

        Args:
            user_messages: 本轮用户消息列表（纯文本）
            tool_call_count: 本轮 LLM 执行的工具调用次数（仅供参考）
        """
        if not self.enabled:
            return
        if not user_messages:
            return

        now = time.time()

        # 更新连续指令计数（v2.0：只看短命令，不看工具调用）
        has_chat = any(len(m.strip()) > 20 for m in user_messages if m)
        has_polite = any(
            kw in " ".join(m for m in user_messages if m)
            for kw in ["请", "谢谢", "辛苦", "麻烦", "可以吗", "好吗"]
        )

        if not has_chat and not has_polite:
            short_count = sum(1 for m in user_messages if m and len(m.strip()) < 8)
            if short_count > 0:
                self._consecutive_commands += short_count
            else:
                self._consecutive_commands = 0
            if now - self._last_command_reset > 300:
                self._consecutive_commands = short_count
            self._last_command_reset = now
        else:
            self._consecutive_commands = 0

        hours_since = (now - self._last_interaction_time) / 3600

        # 检测事件
        events = detect_events(
            user_messages,
            tool_call_count=tool_call_count,
            consecutive_commands=self._consecutive_commands,
            hours_since_last_interaction=hours_since,
        )

        # 应用事件（含冷却 + 会话上限 + 情绪分量）
        for event in events:
            self._apply_event_v2(event)

        self._last_interaction_time = now
        self.state.mark_interaction(now)
        self.state.last_update = now
        self.state.save()

        if events:
            detail = "; ".join(f"{e.type}({e.primary_delta:+.0f})" for e in events)
            logger.info(f"[情感] {detail}")

    @_synchronized
    def update_decay_only(self):
        """仅做时间衰减（无交互时的状态更新）。"""
        if not self.enabled:
            return
        now = time.time()
        hours = (now - self.state.last_update) / 3600
        if hours > 0:
            self.state._apply_decay(hours, now=now)
            self.state.last_update = now
            self.state.save()

    @_synchronized
    def reset_session(self):
        """新会话开始时重置会话上限和连续指令计数。"""
        self.state.reset_session_caps()
        self._consecutive_commands = 0
        self._last_command_reset = time.time()

    # ── 工具拦截 ────────────────────────────────────────

    @_synchronized
    def check_tool_allowed(self, tool_name: str) -> tuple[bool, str]:
        """检查工具在当前状态下是否可用。"""
        if not self.enabled:
            return True, ""
        layer = self.state.middle_layer

        # 寒冬模式：拒绝侵入性工具
        _INVASIVE_TOOLS = {
            "shoulder_photo", "shoulder_pan", "shoulder_tilt",
            "camera_capture", "capture_from_camera", "take_photo", "ocr_image",
        }
        if layer == "寒冬" and tool_name in _INVASIVE_TOOLS:
            return False, "我现在不太想做这件事。"

        # 微凉模式 + 防御工具
        _DEFENSE_TOOLS = {
            "shoulder_photo", "shoulder_pan", "shoulder_tilt",
            "camera_capture", "capture_from_camera", "save_observation",
            "take_photo", "ocr_image",
            "edit_file", "write_file", "delete_file",
        }
        if layer in ("寒冬", "微凉") and tool_name in _DEFENSE_TOOLS:
            if self.state.needs.security < 30:
                return False, "我现在不想做这个。你可以自己来吗？"

        return True, ""

    # ── 主动聊天控制 ────────────────────────────────────

    @property
    @_synchronized
    def proactive_allowed(self) -> bool:
        if not self.enabled:
            return True
        layer = self.state.middle_layer
        if layer == "寒冬":
            return False
        if layer == "微凉" and self.state.needs.security < 25:
            return False
        return True

    @property
    @_synchronized
    def proactive_interval_multiplier(self) -> float:
        """主动聊天频率倍数。"""
        if not self.enabled:
            return 1.0
        layer = self.state.middle_layer
        if layer == "暖春":
            return 0.6
        if layer == "晴朗":
            return 0.8
        if layer == "微凉":
            return 2.0
        if layer == "寒冬":
            return float("inf")
        return 1.0

    # ── 内部方法（v2.0） ────────────────────────────────

    @_synchronized
    def _apply_event_v2(self, event: Event):
        """应用事件效果（v2.1：支持随机范围 + 冷却 + 会话上限 + 情绪分量）。"""
        if not self.enabled:
            return False
        now = time.time()

        # 冷却检查
        recent_same = [
            e for e in self.state.event_history[-30:]
            if e.type == event.type
            and (now - e.timestamp) < event.cooldown_minutes * 60
        ]
        # 真正的冷却期应当抑制重复事件，而不是每次仍保留 25% 伤害。
        if recent_same:
            return False
        multiplier = 1.0

        # 随机范围：如果事件设置了 random_range，从中随机取值
        base_delta = event.primary_delta
        if event.random_range is not None:
            lo, hi = event.random_range
            base_delta = random.uniform(lo, hi)

        # 应用主影响（含会话上限）
        delta = base_delta * multiplier
        actual = self.state.can_apply(event.primary_need, delta)
        if actual != 0:
            old = getattr(self.state.needs, event.primary_need)
            setattr(self.state.needs, event.primary_need,
                    max(0, min(100, old + actual)))
            self.state.apply_cap(event.primary_need, actual)

        # 邻域共振（含会话上限）
        for need, d in event.secondary.items():
            delta2 = d * multiplier
            actual2 = self.state.can_apply(need, delta2)
            if actual2 != 0:
                old2 = getattr(self.state.needs, need)
                setattr(self.state.needs, need,
                        max(0, min(100, old2 + actual2)))
                self.state.apply_cap(need, actual2)

        # 深层信任
        self.state.deep_layer = max(10, min(95,
            self.state.deep_layer + event.deep_delta * multiplier))

        # 情绪分量更新（v2.0：根据事件类型更新情绪）
        emotion_effect = EVENT_TYPES.get(event.type, {}).get("emotion_effect", {})
        for name, delta_e in emotion_effect.items():
            if hasattr(self.state.emotions, name):
                val = getattr(self.state.emotions, name)
                setattr(self.state.emotions, name,
                        max(0, min(100, val + delta_e * multiplier)))

        # 情感记忆（重大事件）
        if abs(event.deep_delta * multiplier) >= 0.5 or event.severity >= 3:
            self.state.add_memory(
                event.type,
                f"{event.detail} (深层信任变化: {event.deep_delta * multiplier:+.1f})"
            )

        # 记录事件
        event.timestamp = now
        self.state.event_history.append(event)
        return True

    def _count_today_events(self, *types: str) -> int:
        """统计今天（最近 24 小时）指定类型的事件数。"""
        cutoff = time.time() - 86400
        return sum(
            1 for e in self.state.event_history
            if e.type in types and e.timestamp > cutoff
        )

    # ── 调试接口（v2.0：扩展字段） ──────────────────────

    @_synchronized
    def get_debug_info(self) -> dict:
        """返回调试面板所需的状态信息（v2.0）。"""
        return {
            **self.state.get_debug_info(),
            "consecutive_commands": self._consecutive_commands,
            "hours_since_interaction": round(
                (time.time() - self._last_interaction_time) / 3600, 1),
            "recent_events": [
                {"type": e.type, "time": e.timestamp, "delta": e.primary_delta,
                 "detail": e.detail, "severity": e.severity}
                for e in self.state.event_history[-30:]
            ],
        }

    @_synchronized
    def set_needs(self, **kwargs):
        """手动设置需求值（调试用）。"""
        for name, val in kwargs.items():
            if hasattr(self.state.needs, name):
                setattr(self.state.needs, name, max(0, min(100, float(val))))
        self.state.save()

    @_synchronized
    def set_emotion(self, **kwargs):
        """手动设置情绪分量（调试用）。"""
        for name, val in kwargs.items():
            if hasattr(self.state.emotions, name):
                setattr(self.state.emotions, name, max(0, min(100, float(val))))
        self.state.save()

    @_synchronized
    def set_deep_trust(self, value: float):
        """手动设置深层信任（调试用）。"""
        self.state.deep_layer = max(10, min(95, float(value)))
        self.state.save()

    @_synchronized
    def reset_state(self):
        """重置为初始状态。"""
        from .state import NeedsState, EmotionComponents, _DEFAULT_DEEP
        was_enabled = self.state.enabled
        self.state = EmotionalState(
            needs=NeedsState(),
            emotions=EmotionComponents(),
            deep_layer=_DEFAULT_DEEP,
            enabled=was_enabled,
        )
        self._consecutive_commands = 0
        self._last_interaction_time = time.time()
        self.state.save()
        logger.info("[情感] 状态已重置为初始值")


# ── 模块级单例 ────────────────────────────────────────────

_manager: Optional[EmotionManager] = None
_manager_lock = threading.Lock()


def get_manager() -> EmotionManager:
    """获取 EmotionManager 单例。"""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = EmotionManager()
    return _manager
