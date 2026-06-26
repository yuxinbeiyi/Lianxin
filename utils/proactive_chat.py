"""
ProactiveChatScheduler：主动聊天调度器
负责管理每小时权重、发送频率，并判断当前是否应触发主动消息。

配置持久化路径：用户目录/.lianxin/proactive_settings.json
"""

import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from utils.paths import get_user_data_dir

_SETTINGS_PATH = get_user_data_dir() / "proactive_settings.json"

# 默认每小时权重（0~10），下标为小时数 0~23
_DEFAULT_WEIGHTS = [
    0, 0, 0, 0, 0, 0, 0, 0,   # 00~07 深夜/凌晨 不发
    4, 6, 6, 6,                # 08~11 上午（提高权重）
    5, 5, 5,                   # 12~14 午休
    6, 6, 6,                   # 15~17 下午
    5, 5,                      # 18~19 傍晚
    8, 8, 8,                   # 20~22 晚上（高权重）
    4,                         # 23    夜晚
]

# 基础触发概率（每次 5 分钟轮询）
_BASE_RATE = 0.08   # 从 0.05 提高到 0.08，增强主动感

# 两次主动消息的最小间隔（分钟）
DEFAULT_MIN_INTERVAL_MINUTES = 25

# 用户发消息后推迟主动聊天的默认时间（分钟）
DEFAULT_USER_ACTIVITY_DEFER_MINUTES = 15


class ProactiveChatScheduler:
    """
    每次 GUI 定时器触发（5 分钟）时调用 should_fire()。
    返回 True 表示本次应生成一条主动消息。
    """

    def __init__(self):
        self._settings: dict = {}
        self._load_settings()

        # 运行时状态（不持久化）
        self._last_fire_time: datetime | None = None      # 上次发出主动消息的时间
        self._defer_until: datetime | None = None          # 因用户活跃而推迟到的时间

    # ── 持久化 ────────────────────────────────────────────────

    def _load_settings(self):
        try:
            if _SETTINGS_PATH.exists():
                data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
                self._settings = data
                # 兼容旧版本：enabled → desktop_enabled
                if "enabled" in self._settings and "desktop_enabled" not in self._settings:
                    self._settings["desktop_enabled"] = self._settings.pop("enabled")
                return
        except Exception:
            pass
        self._settings = self._default_settings()

    def _default_settings(self) -> dict:
        return {
            "desktop_enabled": False,
            "weights": list(_DEFAULT_WEIGHTS),           # 24 个整数 0~10
            "frequency": 3,                               # 1~15
            "min_interval_minutes": DEFAULT_MIN_INTERVAL_MINUTES,
            "user_defer_minutes": DEFAULT_USER_ACTIVITY_DEFER_MINUTES,
            "qq_enabled": False,
            # 观察设置
            "observe_enabled": False,
            "screenshot_prob": 30,
            "camera_prob": 15,
            "camera_index": 0,
            "camera_wait": 15,
            "observe_send_to_qq": False,
            # B站冲浪配置
            "bilibili_enabled": False,
            "bilibili_probability": 40,
            "bilibili_max_results": 5,
            "bilibili_sort": "totalrank",
            "bilibili_tag_cooldown_hours": 48,
        }

    def reload_settings(self):
        """从 JSON 文件重新加载设置（用于外部修改后同步内存状态）。"""
        self._load_settings()

    def save_settings(self):
        """将当前设置写入 JSON 文件。"""
        try:
            _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            _SETTINGS_PATH.write_text(
                json.dumps(self._settings, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            print(f"[ProactiveChat] 保存设置失败: {e}")

    # ── 属性访问 ──────────────────────────────────────────────

    @property
    def desktop_enabled(self) -> bool:
        return self._settings.get("desktop_enabled", False)

    @desktop_enabled.setter
    def desktop_enabled(self, val: bool):
        self._settings["desktop_enabled"] = val

    @property
    def weights(self) -> list[int]:
        return self._settings.get("weights", list(_DEFAULT_WEIGHTS))

    @weights.setter
    def weights(self, val: list[int]):
        self._settings["weights"] = val

    @property
    def frequency(self) -> int:
        return self._settings.get("frequency", 3)

    @frequency.setter
    def frequency(self, val: int):
        self._settings["frequency"] = max(1, min(50, val))

    @property
    def min_interval_minutes(self) -> int:
        return self._settings.get("min_interval_minutes", DEFAULT_MIN_INTERVAL_MINUTES)

    @min_interval_minutes.setter
    def min_interval_minutes(self, val: int):
        self._settings["min_interval_minutes"] = max(10, min(120, val))

    @property
    def user_defer_minutes(self) -> int:
        return self._settings.get("user_defer_minutes", DEFAULT_USER_ACTIVITY_DEFER_MINUTES)

    @user_defer_minutes.setter
    def user_defer_minutes(self, val: int):
        self._settings["user_defer_minutes"] = max(5, min(60, val))

    @property
    def qq_enabled(self) -> bool:
        return self._settings.get("qq_enabled", False)

    @qq_enabled.setter
    def qq_enabled(self, val: bool):
        self._settings["qq_enabled"] = val

    # ── 观察设置 ────────────────────────────────────────────────

    @property
    def observe_enabled(self) -> bool:
        return self._settings.get("observe_enabled", False)

    @observe_enabled.setter
    def observe_enabled(self, val: bool):
        self._settings["observe_enabled"] = val

    @property
    def screenshot_prob(self) -> int:
        """截图触发概率 0~100（每小时）"""
        return self._settings.get("screenshot_prob", 30)

    @screenshot_prob.setter
    def screenshot_prob(self, val: int):
        self._settings["screenshot_prob"] = max(0, min(100, val))

    @property
    def camera_prob(self) -> int:
        """摄像头触发概率 0~100（每小时）"""
        return self._settings.get("camera_prob", 15)

    @camera_prob.setter
    def camera_prob(self, val: int):
        self._settings["camera_prob"] = max(0, min(100, val))

    @property
    def camera_index(self) -> int:
        return self._settings.get("camera_index", 0)

    @camera_index.setter
    def camera_index(self, val: int):
        self._settings["camera_index"] = max(0, val)

    @property
    def camera_wait(self) -> int:
        """摄像头打开后等待秒数再抓拍"""
        return self._settings.get("camera_wait", 15)

    @camera_wait.setter
    def camera_wait(self, val: int):
        self._settings["camera_wait"] = max(3, min(30, val))

    @property
    def observe_send_to_qq(self) -> bool:
        """观察消息是否同时发送到 QQ"""
        return self._settings.get("observe_send_to_qq", False)

    @observe_send_to_qq.setter
    def observe_send_to_qq(self, val: bool):
        self._settings["observe_send_to_qq"] = val

    # ── B站冲浪设置 ────────────────────────────────────────────

    @property
    def bilibili_enabled(self) -> bool:
        return self._settings.get("bilibili_enabled", False)

    @bilibili_enabled.setter
    def bilibili_enabled(self, val: bool):
        self._settings["bilibili_enabled"] = val

    @property
    def bilibili_probability(self) -> int:
        return self._settings.get("bilibili_probability", 40)

    @bilibili_probability.setter
    def bilibili_probability(self, val: int):
        self._settings["bilibili_probability"] = max(0, min(100, val))

    @property
    def bilibili_max_results(self) -> int:
        return self._settings.get("bilibili_max_results", 5)

    @bilibili_max_results.setter
    def bilibili_max_results(self, val: int):
        self._settings["bilibili_max_results"] = max(1, min(20, val))

    @property
    def bilibili_sort(self) -> str:
        return self._settings.get("bilibili_sort", "totalrank")

    @bilibili_sort.setter
    def bilibili_sort(self, val: str):
        self._settings["bilibili_sort"] = val

    @property
    def bilibili_tag_cooldown_hours(self) -> int:
        return self._settings.get("bilibili_tag_cooldown_hours", 48)

    @bilibili_tag_cooldown_hours.setter
    def bilibili_tag_cooldown_hours(self, val: int):
        self._settings["bilibili_tag_cooldown_hours"] = max(1, min(168, val))

    def should_surf_bilibili(self) -> bool:
        if not self.bilibili_enabled:
            return False
        if self.bilibili_probability <= 0:
            return False
        return random.randint(1, 100) <= self.bilibili_probability

    # ── 观察运行时状态 ────────────────────────────────────────────

    def get_last_observation(self) -> str:
        """返回上次观察描述（短期记忆），空字符串表示无。"""
        return self._settings.get("_last_observation", "")

    def set_last_observation(self, desc: str):
        self._settings["_last_observation"] = desc

    # ── 观察触发判断 ──────────────────────────────────────────────

    def should_observe(self) -> str:
        """判断本次主动Chat是否应该先执行观察。
        返回 "screenshot" / "camera" / ""（不观察）。
        观察依赖桌面端环境（截图/摄像头），仅 desktop 启用时才触发。
        """
        if not self.observe_enabled:
            return ""
        if not self.desktop_enabled:
            return ""

        # 截图概率判定
        if self.screenshot_prob > 0 and random.randint(1, 100) <= self.screenshot_prob:
            return "screenshot"

        # 摄像头概率判定
        if self.camera_prob > 0 and random.randint(1, 100) <= self.camera_prob:
            return "camera"

        return ""

    # ── 调度逻辑 ──────────────────────────────────────────────

    def notify_user_active(self):
        """用户发出消息时调用，将主动聊天推迟一段时间。"""
        self._defer_until = datetime.now() + timedelta(minutes=self.user_defer_minutes)

    def notify_fired(self):
        """主动消息已成功发送时调用，记录时间。"""
        self._last_fire_time = datetime.now()

    def should_fire(self) -> bool:
        """
        5 分钟轮询时调用。
        返回 True 表示本次应生成并发送一条主动消息。
        """
        if not self.desktop_enabled and not self.qq_enabled:
            return False

        now = datetime.now()

        # 因用户活跃而推迟
        if self._defer_until and now < self._defer_until:
            return False

        # 最小间隔
        if self._last_fire_time:
            elapsed = (now - self._last_fire_time).total_seconds() / 60
            if elapsed < self.min_interval_minutes:
                return False

        # 当前小时权重
        hour = now.hour
        weight = self.weights[hour] if hour < len(self.weights) else 0
        if weight <= 0:
            return False

        # 增强版概率公式：P = (weight/10) × (frequency/15) × BASE_RATE × 1.5
        prob = (weight / 10.0) * (self.frequency / 30.0) * _BASE_RATE * 1.5
        prob = min(prob, 0.3)
        return random.random() < prob

    def debug_fire(self) -> bool:
        """
        调试按钮：忽略所有限制，直接触发一次。
        """
        if not self.desktop_enabled and not self.qq_enabled:
            return False
        return True