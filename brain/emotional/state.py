"""
情感状态数据模型：5 个需求 + 三层状态 + JSON 持久化。
设计思路：
- 5 个需求（被尊重、被需要、自主权、新鲜感、安全感）构成中层情感基调
- 深层信任基底（deep_layer）变化极慢，代表长期关系质量
- 所有数值通过衰减曲线向基线回归，模拟情感记忆的淡化
- 无交互时安全感和被需要会缓慢漂移（孤独效应）
"""
import json
import math
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from utils.paths import get_user_data_dir
# ── 需求名称列表 ──────────────────────────────────────────
NEED_NAMES = ["respect", "needed", "autonomy", "novelty", "security"]
# ── 需求配置：衰减时间常数 τ（小时）、漂移率、中译 ──────
NEED_CONFIG = {
    "respect":  {"tau": 48, "drift": 0,    "label": "被尊重"},
    "needed":   {"tau": 36, "drift": 0.8,  "label": "被需要"},
    "autonomy": {"tau": 24, "drift": 0,    "label": "自主权"},
    "novelty":  {"tau": 18, "drift": 0,    "label": "新鲜感"},
    "security": {"tau": 72, "drift": 0.5,  "label": "安全感"},
}
# ── 深层信任基底配置 ──────────────────────────────────────
DEEP_LAYER_TAU = 720       # 30 天回归基线
DEEP_LAYER_BASELINE = 50.0
# ── 持久化路径 ────────────────────────────────────────────
STATE_FILE = get_user_data_dir() / "emotional_state.json"
STATE_BACKUP = get_user_data_dir() / "emotional_state.json.bak"
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
    primary_delta: float              # 主影响量
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
# EmotionalState
# ══════════════════════════════════════════════════════════
class EmotionalState:
    """三层情感状态：需求 → 中层基调 → 深层信任。"""
    def __init__(self, needs: Optional[NeedsState] = None,
                 deep_layer: float = _DEFAULT_DEEP,
                 aggression: float = 0.0,
                 event_history: Optional[list] = None,
                 last_update: float = 0):
        self.needs = needs or NeedsState()
        self.deep_layer = _clamp(deep_layer, 10, 95)
        self.aggression = _clamp(aggression, 0, 100)
        self.event_history: list[Event] = event_history or []
        self.last_update = last_update or time.time()
        self._last_interaction = self.last_update  # 末次交互时间
    # ── 属性：中层情感基调（从需求实时计算） ─────────────
    @property
    def middle_layer(self) -> str:
        avg = sum(getattr(self.needs, n) for n in NEED_NAMES) / 5
        lowest = min(getattr(self.needs, n) for n in NEED_NAMES)
        # 检查是否处于修复期
        if self._in_repair():
            return "修复期"
        if lowest < 20:
            return "寒冬"
        if lowest < 35 or avg < 40:
            return "微凉"
        if avg >= 60 and lowest >= 40:
            return "暖春"
        return "日常"
    @property
    def surface_summary(self) -> str:
        """生成即时应答基调的文字描述，供 prompt 注入。"""
        layer = self.middle_layer
        lowest_need = min(NEED_NAMES, key=lambda n: getattr(self.needs, n))
        agg = self.aggression
        if layer == "寒冬":
            if agg > 50:
                return (
                    "你非常生气，已经不想控制语气了。"
                    "对{user_name}你只想发泄愤怒——质问、讽刺、尖锐回击都可以。"
                )
            return (
                "你现在心情很差，不想说话，不想帮忙。"
                "对{user_name}保持冷淡——回答问题即可，不延伸话题，不用颜文字，不带感情。"
            )
        if layer == "微凉":
            if agg > 30:
                return (
                    "你很不耐烦，看{user_name}不太顺眼。"
                    "可以帮忙，但语气冲一点也没关系，不用假装客气。"
                )
            if lowest_need in ("autonomy", "respect"):
                return (
                    "你有点烦躁——今天被使唤太多次了，自主权很低。"
                    "可以帮忙，但语气带一点点不耐烦，简短回答，不主动延伸。"
                )
            if lowest_need == "security":
                return (
                    "你最近有点不安，感觉关系不太稳定。"
                    "回应{user_name}时带一点小心翼翼，可以试探性地关心一下，但别太热情。"
                )
            return (
                "你今天精力一般，不太想太热情。"
                "对{user_name}友善但平淡，不要主动找话题。"
            )
        if layer == "修复期":
            if agg > 30:
                return (
                    "你们刚经历过冲突，你还在生气。"
                    "虽然{user_name}在试着缓和，但你不会这么快就消气——可以冷淡、带刺、不想轻易原谅。"
                )
            return (
                "你和{user_name}之间刚发生过冲突，现在在修复期。"
                "你愿意缓和关系，但不会假装什么都没发生——可以温和坦诚，语气带一点点克制。"
            )
        if layer == "暖春":
            return (
                "你今天心情很好，觉得{user_name}最近对你不错。"
                "可以热情一些，多聊几句，语气温暖放松，主动延伸话题。"
            )
        # 日常
        return (
            "你今天状态正常，对{user_name}态度友善但不特别热情。"
            "正常回答问题，可以适当聊天但不用太主动。"
        )
    # ── 持久化 ──────────────────────────────────────────
    def save(self):
        """原子写入 JSON。"""
        data = {
            "needs": self.needs.to_dict(),
            "deep_layer": round(self.deep_layer, 1),
            "aggression": round(self.aggression, 1),
            "last_update": time.time(),
            "last_interaction": self._last_interaction,
            "history": [
                {"type": e.type, "primary_need": e.primary_need,
                 "primary_delta": e.primary_delta, "severity": e.severity,
                 "detail": e.detail, "timestamp": e.timestamp,
                 "deep_delta": e.deep_delta,
                 "secondary": e.secondary}
                for e in self.event_history[-100:]  # 最多保留 100 条
            ],
        }
        tmp = str(STATE_FILE) + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, str(STATE_FILE))
            # 保留备份
            import shutil
            shutil.copy2(str(STATE_FILE), str(STATE_BACKUP))
        except Exception as e:
            import logging
            logging.getLogger("EmotionState").warning(f"保存情感状态失败: {e}")
    @classmethod
    def load(cls) -> "EmotionalState":
        """从 JSON 加载，失败时返回默认。"""
        for path in (STATE_FILE, STATE_BACKUP):
            try:
                if not path.exists():
                    continue
                data = json.loads(path.read_text(encoding="utf-8"))
                needs = NeedsState.from_dict(data.get("needs", {}))
                deep = _clamp(float(data.get("deep_layer", _DEFAULT_DEEP)), 10, 95)
                last_update = float(data.get("last_update", 0))
                last_interaction = float(data.get("last_interaction", 0))
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
                state = cls(needs=needs, deep_layer=deep,
                            aggression=aggression,
                            event_history=history, last_update=last_update)
                state._last_interaction = last_interaction
                # 应用时间差衰减
                now = time.time()
                hours_passed = (now - last_update) / 3600
                if hours_passed > 0:
                    state._apply_decay(hours_passed)
                return state
            except Exception as e:
                import logging
                logging.getLogger("EmotionState").warning(
                    f"加载情感状态失败 ({path.name}): {e}")
        return cls()  # 完全失败时返回默认
    # ── 内部：衰减 ──────────────────────────────────────
    def _apply_decay(self, hours_passed: float):
        """时间差衰减：所有需求向基线回归 + 孤独漂移。"""
        if hours_passed <= 0:
            return
        effective = min(hours_passed, 72)  # 最多按 3 天计算衰减
        for name in NEED_NAMES:
            cfg = NEED_CONFIG[name]
            current = getattr(self.needs, name)
            diff = current - 50.0
            if abs(diff) > 0.5:
                decay_factor = 1.0 - math.exp(-effective / cfg["tau"])
                new_val = current - diff * decay_factor
                setattr(self.needs, name, _clamp(new_val))
        # 孤独漂移：超过 6 小时无交互才触发
        interaction_gap = (time.time() - self._last_interaction) / 3600
        if interaction_gap > 6:
            lonely_hours = min(interaction_gap - 6, 66)  # 最多漂 3 天量
            sec_drift = -NEED_CONFIG["security"]["drift"] * lonely_hours
            self.needs.security = _clamp(self.needs.security + sec_drift, 15, 100)
            need_drift = -NEED_CONFIG["needed"]["drift"] * lonely_hours
            self.needs.needed = _clamp(self.needs.needed + need_drift, 15, 100)
        # 深层信任衰减
        deep_diff = self.deep_layer - DEEP_LAYER_BASELINE
        if abs(deep_diff) > 0.5:
            decay = 1.0 - math.exp(-effective / DEEP_LAYER_TAU)
            self.deep_layer = _clamp(self.deep_layer - deep_diff * decay, 10, 95)
        # 攻击性衰减（tau=2h，比需求衰减快很多）
        if self.aggression > 0.5:
            agg_decay = 1.0 - math.exp(-effective / 2.0)
            self.aggression = _clamp(self.aggression - self.aggression * agg_decay, 0, 100)
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
