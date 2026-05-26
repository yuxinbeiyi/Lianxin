"""
Observation Mode (观察模式) 状态管理器。
莲心主动持续观察周围环境：转头→拍照→分析→发QQ→循环。
包含状态管理、费用追踪、QQ限速、闲置检测等功能。
"""

import json
import time
import threading
from pathlib import Path
from datetime import date


_COST_DATA_PATH = Path.home() / ".lianxin" / "observation_cost.json"

# ── 全局状态 ─────────────────────────────────────────────

_observation_state = None
_state_lock = threading.Lock()


def get_observation_state():
    global _observation_state
    if _observation_state is None:
        with _state_lock:
            if _observation_state is None:
                _observation_state = ObservationModeState()
    return _observation_state


# ── 费用追踪 ─────────────────────────────────────────────

class CostTracker:
    """每日观察模式 SiliconFlow 视觉 API 费用追踪。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        if _COST_DATA_PATH.exists():
            try:
                data = json.loads(_COST_DATA_PATH.read_text(encoding="utf-8"))
                if data.get("date") == date.today().isoformat():
                    self._daily_calls = data.get("daily_calls", 0)
                    self._daily_cost = data.get("daily_estimated_cost", 0.0)
                    self._user_overrode = data.get("user_overrode_today", False)
                    return
            except Exception:
                pass
        self._reset()

    def _reset(self):
        self._daily_calls = 0
        self._daily_cost = 0.0
        self._user_overrode = False

    def _save(self):
        _COST_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        _COST_DATA_PATH.write_text(json.dumps({
            "date": date.today().isoformat(),
            "daily_calls": self._daily_calls,
            "daily_estimated_cost": round(self._daily_cost, 2),
            "user_overrode_today": self._user_overrode,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def record_call(self, estimated_cost: float = 0.015):
        """记录一次视觉 API 调用。默认 0.015 元/次估算。"""
        with self._lock:
            self._daily_calls += 1
            self._daily_cost += estimated_cost
            self._save()

    def is_over_limit(self, limit: float = 5.0) -> bool:
        """是否超限。如果用户今日已手动覆盖，返回 False。"""
        with self._lock:
            if self._user_overrode:
                return False
            return self._daily_cost >= limit

    def user_overrode(self):
        """用户手动重启后调用，当日不再因费用退出。"""
        with self._lock:
            self._user_overrode = True
            self._save()

    @property
    def today_summary(self) -> str:
        with self._lock:
            return f"今日已观察{self._daily_calls}次，费用约 ¥{self._daily_cost:.2f}"


# ── QQ 限速 ──────────────────────────────────────────────

class RateLimiter:
    """QQ 消息限速器：每分钟最多 N 张图片。"""

    def __init__(self, max_per_minute: int = 2):
        self._max = max_per_minute
        self._timestamps: list[float] = []
        self._lock = threading.Lock()

    def can_send(self) -> bool:
        now = time.time()
        with self._lock:
            self._timestamps = [t for t in self._timestamps if now - t < 60]
            return len(self._timestamps) < self._max

    def record_send(self):
        with self._lock:
            self._timestamps.append(time.time())

    def wait_time(self) -> float:
        """还需要等多久才能发下一张（秒）。"""
        now = time.time()
        with self._lock:
            if len(self._timestamps) < self._max:
                return 0.0
            oldest = min(self._timestamps)
            return max(0.0, oldest + 60 - now)


# ── 循环频率限制 ─────────────────────────────────────────

class CycleRateLimiter:
    """观察模式循环频率限制：每分钟最多 N 个完整观察周期。"""

    def __init__(self, max_per_minute: int = 2):
        self._max = max_per_minute
        self._cycle_times: list[float] = []
        self._lock = threading.Lock()

    def can_start_cycle(self) -> bool:
        """检查是否可以开始新一轮完整观察。"""
        now = time.time()
        with self._lock:
            self._cycle_times = [t for t in self._cycle_times if now - t < 60]
            return len(self._cycle_times) < self._max

    def record_cycle(self):
        """记录一次完成的观察周期。"""
        with self._lock:
            self._cycle_times.append(time.time())

    def time_until_next_slot(self) -> float:
        """距离下一个可用周期槽还有多少秒。"""
        now = time.time()
        with self._lock:
            self._cycle_times = [t for t in self._cycle_times if now - t < 60]
            if len(self._cycle_times) < self._max:
                return 0.0
            oldest = min(self._cycle_times)
            return max(0.0, oldest + 60 - now)

    @property
    def next_slot_in(self) -> float:
        """当前周期数已满时返回等待秒数，否则返回0。"""
        return self.time_until_next_slot()


# ── 状态管理器 ────────────────────────────────────────────

class ObservationModeState:
    """线程安全的观察模式状态管理器，协调 Worker 和 QQ Bridge 间的通信。"""

    def __init__(self):
        self._active = False
        self._pending_messages: list[dict] = []
        self._last_user_msg_time = time.time()
        self._lock = threading.Lock()
        self._idle_timeout = 1800  # 30 分钟
        # 协调事件
        self._pending_event = threading.Event()   # Worker 用它等待 pending 消息
        self._resume_event = threading.Event()    # QQ Bridge 处理完消息后通知 Worker 继续
        self._processing = False                  # 是否正在处理用户消息
        # 外部注入
        self._qq_bridge = None

    def set_qq_bridge(self, bridge):
        self._qq_bridge = bridge

    # ── 读写状态 ──

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._active

    def activate(self):
        with self._lock:
            self._active = True
            self._last_user_msg_time = time.time()
            self._pending_messages.clear()
        self._pending_event.clear()
        self._resume_event.set()  # 确保 Worker 不会被阻塞

    def deactivate(self):
        with self._lock:
            self._active = False
            self._pending_messages.clear()
        self._resume_event.set()  # 让 Worker 从等待中退出

    # ── pending 消息队列 ──

    def enqueue_message(self, msg: dict):
        """QQ Bridge 调用：用户消息排队，等当前观察循环完成后再处理。"""
        with self._lock:
            self._pending_messages.append(msg)
            self._last_user_msg_time = time.time()
        self._pending_event.set()

    def drain_pending(self) -> list[dict]:
        """Worker 调用：取走所有待处理消息。"""
        with self._lock:
            msgs = self._pending_messages.copy()
            self._pending_messages.clear()
            return msgs

    @property
    def has_pending(self) -> bool:
        with self._lock:
            return len(self._pending_messages) > 0

    # ── Worker <-> QQ Bridge 协调 ──

    def wait_for_pending_or_timeout(self, timeout: float = 3.0) -> bool:
        """Worker 调用：等待 pending 消息到来或超时。
        返回 True 表示有 pending 消息需要处理。
        """
        self._pending_event.wait(timeout)
        if self._pending_event.is_set():
            self._pending_event.clear()
            return self.has_pending
        return False

    def notify_processing_started(self):
        """Worker 调用：通知外部处理器可以开始处理消息了。"""
        self._processing = True
        self._resume_event.clear()

    def notify_processing_done(self):
        """QQ Bridge 调用：通知 Worker 消息已处理完毕，可以继续循环。"""
        self._processing = False
        self._resume_event.set()

    def wait_resume(self) -> bool:
        """Worker 调用：等待消息处理完毕。返回 False 表示观察模式已退出。"""
        self._resume_event.wait()
        self._resume_event.clear()
        return self._active

    # ── 闲置检测 ──

    def check_idle_and_exit(self) -> bool:
        """检查闲置超时。超时则自动停用并通知。返回 True 表示已超时退出。"""
        with self._lock:
            if not self._active:
                return False
            elapsed = time.time() - self._last_user_msg_time
            if elapsed > self._idle_timeout:
                self._active = False
                if self._qq_bridge:
                    try:
                        self._qq_bridge.send_to_owner(
                            "30分钟没见到主人说话了，我先退出【观察模式】歇一会儿哦～\n"
                            "【观察模式】已退出～(｡•́︿•̀｡)"
                        )
                    except Exception:
                        pass
                return True
            return False

    def refresh_user_activity(self):
        with self._lock:
            self._last_user_msg_time = time.time()


# ── 便捷工厂 ─────────────────────────────────────────────

def get_cost_tracker() -> CostTracker:
    return CostTracker()


def get_rate_limiter() -> RateLimiter:
    return RateLimiter(max_per_minute=2)
