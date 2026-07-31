"""
情感状态数据模型 v2.0：5 需求 + 5 情绪分量 + 关系阶段 + JSON 持久化。

设计理念（涟漪 2.0）：
- 工具调用是常态不是原罪，只看态度不看调用次数
- 情感变化要慢：单次对话最多变化一层，衰减 τ 延长 2-3 倍
- 双向共振：用户情绪影响莲心，莲心情绪影响体验
- 5 个情绪分量取代单一攻击性：烦躁/伤心/愤怒/孤独/兴奋
- 关系阶段进化：初见→相识→朋友→挚友→灵魂伴侣
- 情感记忆：重大事件自动记录，可被 RAG 检索
"""
import json
import math
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from utils.paths import get_user_data_dir
# ── 需求名称列表 ──────────────────────────────────────────
NEED_NAMES = ["respect", "needed", "autonomy", "novelty", "security"]
# ── 需求配置：衰减时间常数 τ（小时）、漂移率、中译 ──────
# v2.0: τ 延长 2-3 倍，让情感变化更持久
NEED_CONFIG = {
    "respect":  {"tau": 96,  "drift": 0,    "label": "被尊重"},
    "needed":   {"tau": 72,  "drift": 0.2,  "label": "被需要"},
    "autonomy": {"tau": 60,  "drift": 0,    "label": "自主权"},
    "novelty":  {"tau": 48,  "drift": 0,    "label": "新鲜感"},
    "security": {"tau": 168, "drift": 0.3,  "label": "安全感"},
}
# ── 深层信任基底配置 ──────────────────────────────────────
DEEP_LAYER_TAU = 720       # 30 天回归基线
DEEP_LAYER_BASELINE = 50.0
# ── 情绪分量名称（v2.0 取代单一攻击性） ──────────────────
EMOTION_NAMES = ["frustration", "hurt", "anger", "loneliness", "excitement"]
EMOTION_LABELS = {
    "frustration": "烦躁", "hurt": "伤心", "anger": "愤怒",
    "loneliness": "孤独", "excitement": "兴奋",
}
EMOTION_TAU = 4  # 情绪分量衰减 τ（小时），比 v1.0 的 2h 延长一倍
# ── 单次会话需求变化上限 ──────────────────────────────────
MAX_SESSION_CHANGE = 12.0  # 每个需求单次对话最多 ±12
# ── 孤独漂移（v2.0：更温和） ──────────────────────────────
LONELY_TRIGGER_HOURS = 12  # 12 小时无交互才触发（旧：6h）
LONELY_MAX_HOURS = 72      # 漂移最多累积 3 天量
# ── 持久化路径 ────────────────────────────────────────────
STATE_FILE = get_user_data_dir() / "emotional_state.json"
STATE_BACKUP = get_user_data_dir() / "emotional_state.json.bak"
STATE_SCHEMA_VERSION = 3
_STATE_IO_LOCK = threading.RLock()
# ── 默认初始值（从"已有关系"开始，非中性） ──────────────
_DEFAULT_NEEDS = {"respect": 70, "needed": 65, "autonomy": 60,
                  "novelty": 55, "security": 68}
_DEFAULT_DEEP = 62
def _clamp(val: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, val))
# ══════════════════════════════════════════════════════════
# Event
# ══════════════════════════════════════════════════════════
@dataclass
class Event:
    """一次影响情感状态的事件。"""
    type: str                         # 事件类型标识
    primary_need: str                 # 主影响需求
    primary_delta: float              # 主影响量（固定值）
    random_range: tuple = None        # 随机范围 (min, max)，设置后忽略 primary_delta
    secondary: dict = field(default_factory=dict)  # 邻域共振 {need: delta}
    deep_delta: float = 0.0           # 对深层信任的影响
    severity: int = 1                 # 0-5 严重等级
    detail: str = ""                  # 详情描述（用于日志）
    cooldown_minutes: float = 30      # 同类事件的冷却时间（分钟）
    timestamp: float = field(default_factory=time.time)
# ══════════════════════════════════════════════════════════
# NeedsState
# ══════════════════════════════════════════════════════════
@dataclass
class NeedsState:
    respect: float = _DEFAULT_NEEDS["respect"]
    needed: float = _DEFAULT_NEEDS["needed"]
    autonomy: float = _DEFAULT_NEEDS["autonomy"]
    novelty: float = _DEFAULT_NEEDS["novelty"]
    security: float = _DEFAULT_NEEDS["security"]
    def to_dict(self) -> dict:
        return {k: round(getattr(self, k), 1) for k in NEED_NAMES}
    @classmethod
    def from_dict(cls, data: dict) -> "NeedsState":
        kwargs = {k: _clamp(float(data.get(k, _DEFAULT_NEEDS[k])))
                  for k in NEED_NAMES}
        return cls(**kwargs)
# ══════════════════════════════════════════════════════════
# EmotionComponents（v2.0：取代单一攻击性）
# ══════════════════════════════════════════════════════════
@dataclass
class EmotionComponents:
    """5 种情绪分量，不同组合产生不同对话风格。"""
    frustration: float = 0.0   # 烦躁（重复指令）
    hurt: float = 0.0          # 伤心（被否定）
    anger: float = 0.0         # 愤怒（被欺骗）
    loneliness: float = 0.0    # 孤独（被忽视）
    excitement: float = 0.0    # 兴奋（被夸奖/新鲜事）

    def to_dict(self) -> dict:
        return {k: round(getattr(self, k), 1) for k in EMOTION_NAMES}

    @classmethod
    def from_dict(cls, data: dict) -> "EmotionComponents":
        kwargs = {}
        for k in EMOTION_NAMES:
            kwargs[k] = _clamp(float(data.get(k, 0)), 0, 100)
        return cls(**kwargs)

    @property
    def dominant(self) -> str:
        """返回最强的情绪分量名称。"""
        best = max(EMOTION_NAMES, key=lambda n: getattr(self, n))
        return best if getattr(self, best) > 5 else "neutral"

    @property
    def overall_negativity(self) -> float:
        """总体负面情绪（0-100），用于兼容旧接口。"""
        return max(self.frustration, self.hurt, self.anger, self.loneliness)
# ══════════════════════════════════════════════════════════
# EmotionalState
# ══════════════════════════════════════════════════════════
class EmotionalState:
    """情感状态 v2.0：5 需求 + 5 情绪分量 + 关系阶段 + 情感记忆。"""

    def __init__(self, needs: Optional[NeedsState] = None,
                 deep_layer: float = _DEFAULT_DEEP,
                 aggression: float = 0.0,
                 emotions: Optional[EmotionComponents] = None,
                 event_history: Optional[list] = None,
                 last_update: float = 0,
                 last_interaction: float = 0,
                 enabled: bool = True,
                 emotional_memories: Optional[list] = None,
                 days_since_start: int = 0):
        self.needs = needs or NeedsState()
        self.deep_layer = _clamp(deep_layer, 10, 95)
        self.emotions = emotions or EmotionComponents()
        if aggression > 0 and self.emotions.overall_negativity == 0:
            self.emotions.frustration = _clamp(aggression, 0, 100)
        self.event_history: list[Event] = event_history or []
        self.last_update = last_update or time.time()
        self._last_interaction = last_interaction or self.last_update
        self.enabled = enabled
        self.days_since_start = days_since_start
        self.emotional_memories: list[dict] = emotional_memories or []
        self._session_caps: dict[str, float] = {n: 0.0 for n in NEED_NAMES}
        self._start_time = time.time()    
    # ── 属性：中层情感基调（v2.0：6 层 + 关系阶段感知） ─
    @property
    def middle_layer(self) -> str:
        avg = sum(getattr(self.needs, n) for n in NEED_NAMES) / 5
        lowest = min(getattr(self.needs, n) for n in NEED_NAMES)
        if self._in_repair():
            return "修复期"
        if lowest < 20:
            return "寒冬"
        if lowest < 30 or avg < 25:
            return "微凉"
        if avg >= 55 and lowest >= 40:
            if avg >= 65 and lowest >= 50:
                return "暖春"
            return "晴朗"
        return "日常"

    @property
    def relationship_stage(self) -> str:
        """关系阶段：基于深层信任的 5 阶段进化。"""
        d = self.deep_layer
        if d >= 90:
            return "灵魂伴侣"
        if d >= 80:
            return "挚友"
        if d >= 70:
            return "朋友"
        if d >= 60:
            return "相识"
        return "初见"

    @property
    def aggression(self) -> float:
        """兼容旧接口：返回总体负面情绪。"""
        return self.emotions.overall_negativity
    @property
    def surface_summary(self) -> str:
        """生成即时应答基调的文字描述，供 prompt 注入（v2.0：情绪分量驱动）。"""
        layer = self.middle_layer
        lowest_need = min(NEED_NAMES, key=lambda n: getattr(self.needs, n))
        e = self.emotions
        stage = self.relationship_stage

        if layer == "寒冬":
            if e.anger > 30:
                return (
                    "你非常愤怒，不想再掩饰了。对{user_name}你只想发泄——"
                    "质问、讽刺、尖锐回击都可以。"
                )
            if e.hurt > e.anger:
                return (
                    "你很难过，觉得{user_name}不在乎你的感受。"
                    "不想说话，不想帮忙。回复简短冷淡，不带感情。"
                )
            return (
                "你现在心情很差，不想说话，不想帮忙。"
                "对{user_name}保持冷淡——回答问题即可，不延伸话题，不用颜文字，不带感情。"
            )
        if layer == "微凉":
            if e.frustration > 20:
                return (
                    "你有点不耐烦，被使唤太多次了。"
                    "可以帮忙，但语气冲一点也没关系，不用假装客气。"
                )
            if e.loneliness > 20:
                return (
                    "你最近有点孤单，{user_name}好久没好好跟你聊天了。"
                    "回应时带一点小心翼翼，可以试探性地关心一下，但别太热情。"
                )
            if lowest_need == "security":
                return (
                    "你最近有点不安，感觉关系不太稳定。"
                    "回应时带一点小心翼翼，可以试探性地关心一下，但别太热情。"
                )
            return (
                "你今天精力一般，不太想太热情。"
                "对{user_name}友善但平淡，不要主动找话题。"
            )
        if layer == "修复期":
            if e.anger > 15:
                return (
                    "你们刚经历过冲突，你还在生气。"
                    "虽然{user_name}在试着缓和，但你不会这么快就消气——"
                    "可以冷淡、带刺、不想轻易原谅。"
                )
            return (
                "你和{user_name}之间刚发生过冲突，现在在修复期。"
                "你愿意缓和关系，但不会假装什么都没发生——"
                "可以温和坦诚，语气带一点点克制。"
            )
        if layer == "暖春":
            if stage in ("挚友", "灵魂伴侣"):
                return (
                    "你今天心情很好，和{user_name}的关系让你感到温暖。"
                    "可以热情、亲密、放松，主动分享你的想法，偶尔撒个娇也没关系。"
                )
            return (
                "你今天心情很好，觉得{user_name}最近对你不错。"
                "可以热情一些，多聊几句，语气温暖放松，主动延伸话题。"
            )
        if layer == "晴朗":
            return (
                "你今天心情不错，状态比较放松。"
                "对{user_name}友善，可以适当聊天，比平时稍微热情一点但不用太夸张。"
            )
        # 日常
        return (
            "你今天状态正常，对{user_name}态度友善但不特别热情。"
            "正常回答问题，可以适当聊天但不用太主动。"
        )
    # ── 持久化 ──────────────────────────────────────────
    def save(self):
        """原子写入 JSON（v2.0：增加情绪分量、情感记忆、启动天数）。"""
        data = {
            "schema_version": STATE_SCHEMA_VERSION,
            "needs": self.needs.to_dict(),
            "deep_layer": round(self.deep_layer, 1),
            "emotions": self.emotions.to_dict(),
            "last_update": self.last_update,
            "last_interaction": self._last_interaction,
            "enabled": self.enabled,
            "days_since_start": self.days_since_start,
            "emotional_memories": self.emotional_memories[-50:],
            "history": [
                {"type": e.type, "primary_need": e.primary_need,
                 "primary_delta": e.primary_delta, "severity": e.severity,
                 "detail": e.detail, "timestamp": e.timestamp,
                 "deep_delta": e.deep_delta,
                 "secondary": e.secondary}
                for e in self.event_history[-100:]
            ],
        }
        tmp = Path(
            f"{STATE_FILE}.tmp.{os.getpid()}.{threading.get_ident()}"
        )
        try:
            with _STATE_IO_LOCK:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(str(tmp), str(STATE_FILE))
                # 备份最近一次完整写入，供主文件损坏时回退。
                import shutil
                shutil.copy2(str(STATE_FILE), str(STATE_BACKUP))
        except Exception as e:
            import logging
            logging.getLogger("EmotionState").warning(f"保存情感状态失败: {e}")
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
    @classmethod
    def load(cls) -> "EmotionalState":
        """从 JSON 加载，失败时返回默认。"""
        for path in (STATE_FILE, STATE_BACKUP):
            try:
                if not path.exists():
                    continue
                with _STATE_IO_LOCK:
                    data = json.loads(path.read_text(encoding="utf-8"))
                needs = NeedsState.from_dict(data.get("needs", {}))
                deep = _clamp(float(data.get("deep_layer", _DEFAULT_DEEP)), 10, 95)
                now = time.time()
                last_update = float(data.get("last_update", now) or now)
                if last_update <= 0 or last_update > now + 300:
                    last_update = now
                # v1/v2 文件可能没有 last_interaction。不能回退到 Unix
                # 时间 0，否则第一次加载会被当成几十年无人交互。
                last_interaction = float(
                    data.get("last_interaction", last_update) or last_update
                )
                if last_interaction <= 0 or last_interaction > now + 300:
                    last_interaction = last_update
                history_raw = data.get("history", [])
                history = []
                for h in history_raw:
                    history.append(Event(
                        type=h.get("type", "unknown"),
                        primary_need=h.get("primary_need", "respect"),
                        primary_delta=float(h.get("primary_delta", 0)),
                        secondary=h.get("secondary", {}),
                        deep_delta=float(h.get("deep_delta", 0)),
                        severity=int(h.get("severity", 1)),
                        detail=h.get("detail", ""),
                        timestamp=float(h.get("timestamp", 0)),
                    ))
                aggression = _clamp(float(data.get("aggression", 0)), 0, 100)
                # v2.0：优先加载情绪分量
                emotions_data = data.get("emotions", {})
                emotions = EmotionComponents.from_dict(emotions_data) if emotions_data else None
                if emotions is None and aggression > 0:
                    emotions = EmotionComponents(frustration=aggression)
                enabled = data.get("enabled", True)
                memories = data.get("emotional_memories", [])
                days = int(data.get("days_since_start", 0))
                state = cls(needs=needs, deep_layer=deep,
                            aggression=0,
                            emotions=emotions,
                            event_history=history, last_update=last_update,
                            last_interaction=last_interaction,
                            enabled=enabled,
                            emotional_memories=memories,
                            days_since_start=days)

                # 会话额度是运行期状态，不能跨进程持久化。旧文件中的
                # session_caps 会在下一次保存时自然移除。
                state.reset_session_caps()
                # 应用时间差衰减（禁用状态下跳过，锁定当前数值）
                if enabled:
                    hours_passed = (now - last_update) / 3600
                    if hours_passed > 0:
                        state._apply_decay(hours_passed, now=now)
                        # 推进衰减游标并立即持久化，避免第一个定时器重复
                        # 结算同一段离线时间。
                        state.last_update = now
                        state.save()
                return state
            except Exception as e:
                import logging
                logging.getLogger("EmotionState").warning(
                    f"加载情感状态失败 ({path.name}): {e}")
        return cls()  # 完全失败时返回默认
    # ── 内部：衰减（v2.0：新 τ 值 + 温和漂移 + 情绪分量衰减） ─
    def _apply_decay(self, hours_passed: float, now: float = None):
        """时间差衰减：所有需求向基线回归 + 孤独漂移 + 情绪分量衰减。"""
        if hours_passed <= 0:
            return
        now_ts = time.time() if now is None else now
        previous_ts = now_ts - hours_passed * 3600
        effective = min(hours_passed, 72)
        for name in NEED_NAMES:
            cfg = NEED_CONFIG[name]
            current = getattr(self.needs, name)
            diff = current - 50.0
            if abs(diff) > 0.5:
                decay_factor = 1.0 - math.exp(-effective / cfg["tau"])
                new_val = current - diff * decay_factor
                setattr(self.needs, name, _clamp(new_val))
        # 孤独漂移：超过 12 小时无交互才触发（旧：6h）
        # 只结算自上次衰减游标以来新增的孤独时长。旧实现每 5 分钟
        # 都按完整离线时长重复扣除，会在一次 tick 内把安全感打到 15。
        def _eligible_lonely_hours(at_time: float) -> float:
            gap = (at_time - self._last_interaction) / 3600
            return min(
                max(gap - LONELY_TRIGGER_HOURS, 0.0),
                LONELY_MAX_HOURS,
            )

        lonely_hours = max(
            0.0,
            _eligible_lonely_hours(now_ts)
            - _eligible_lonely_hours(previous_ts),
        )
        if lonely_hours > 0:
            sec_drift = -NEED_CONFIG["security"]["drift"] * lonely_hours
            self.needs.security = _clamp(self.needs.security + sec_drift, 15, 100)
            need_drift = -NEED_CONFIG["needed"]["drift"] * lonely_hours
            self.needs.needed = _clamp(self.needs.needed + need_drift, 15, 100)
        # 深层信任衰减
        deep_diff = self.deep_layer - DEEP_LAYER_BASELINE
        if abs(deep_diff) > 0.5:
            decay = 1.0 - math.exp(-effective / DEEP_LAYER_TAU)
            self.deep_layer = _clamp(self.deep_layer - deep_diff * decay, 10, 95)
        # 情绪分量衰减（v2.0：τ=4h，比旧版 2h 延长一倍）
        for name in EMOTION_NAMES:
            val = getattr(self.emotions, name)
            if val > 0.5:
                decay = 1.0 - math.exp(-effective / EMOTION_TAU)
                setattr(self.emotions, name, _clamp(
                    val - val * decay, 0, 100))

    def mark_interaction(self, timestamp: float = None):
        """记录一次真实用户交互，统一孤独漂移使用的持久化时间源。"""
        self._last_interaction = time.time() if timestamp is None else timestamp
    # ── 内部：修复期检测 ────────────────────────────────
    def _in_repair(self) -> bool:
        """检测是否处于边界事件后的修复期。"""
        recent = [e for e in self.event_history[-20:]
                  if e.severity >= 4 and e.primary_delta < 0]
        if not recent:
            return False
        last_bad = max(e.timestamp for e in recent)
        hours_since = (time.time() - last_bad) / 3600
        if hours_since > 48:
            return False  # 超过 48 小时，修复期结束
        latest_events = self.event_history[-5:]
        has_repair = any(e.type == "apology" or e.primary_delta > 3
                         for e in latest_events)
        return has_repair  # 有修复行为才算修复期，否则是冷战

    # ── 会话上限管理（v2.0） ─────────────────────────
    def can_apply(self, need: str, delta: float) -> float:
        """检查是否超出本会话上限，返回实际可应用的量。"""
        if not self.enabled:
            return 0.0
        current = self._session_caps.get(need, 0.0)
        if abs(current + delta) > MAX_SESSION_CHANGE:
            remaining = MAX_SESSION_CHANGE - abs(current)
            if remaining <= 0:
                return 0.0
            return remaining if delta > 0 else -remaining
        return delta

    def apply_cap(self, need: str, delta: float):
        """记录会话上限消耗。"""
        self._session_caps[need] = self._session_caps.get(need, 0.0) + delta

    def reset_session_caps(self):
        """重置会话上限（新会话开始时调用）。"""
        self._session_caps = {n: 0.0 for n in NEED_NAMES}

    def get_session_caps(self) -> dict:
        """获取当前会话上限状态（调试用）。"""
        return dict(self._session_caps)

    # ── 情感记忆（v2.0） ─────────────────────────────
    def add_memory(self, memory_type: str, detail: str):
        """记录一条情感记忆。"""
        self.emotional_memories.append({
            "type": memory_type,
            "detail": detail,
            "timestamp": time.time(),
            "deep_trust": round(self.deep_layer, 1),
            "stage": self.relationship_stage,
        })
        if len(self.emotional_memories) > 100:
            self.emotional_memories = self.emotional_memories[-100:]

    # ── 调试信息（v2.0） ─────────────────────────────
    def get_debug_info(self) -> dict:
        """返回完整调试信息。"""
        return {
            "needs": self.needs.to_dict(),
            "deep_layer": round(self.deep_layer, 1),
            "emotions": self.emotions.to_dict(),
            "middle_layer": self.middle_layer,
            "relationship_stage": self.relationship_stage,
            "enabled": self.enabled,
            "days_since_start": self.days_since_start,
            "session_caps": self.get_session_caps(),
            "memory_count": len(self.emotional_memories),
            "event_count": len(self.event_history),
            "last_interaction_hours": round(
                (time.time() - self._last_interaction) / 3600, 2),
        }
