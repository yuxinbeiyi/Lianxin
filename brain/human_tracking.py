"""
Human Tracking (人体跟踪) 状态管理器。
QQ 发送【跟踪】人 → 莲心启动人体跟踪 → ESP32 推流 → PC 本地 Pose 推理 → 舵机跟随。

状态机: idle → tracking ⇄ scanning → exit
"""

import time
import threading
from collections import deque


class TrackState:
    IDLE = "idle"
    TRACKING = "tracking"
    SCANNING = "scanning"


class TrackManager:
    """线程安全的人体跟踪状态管理器。"""

    def __init__(self):
        self._state = TrackState.IDLE
        self._lock = threading.Lock()
        self._qq_bridge = None
        self._last_cmd_time = time.time()
        self._idle_timeout = 300  # 5 分钟

        # 有界帧队列（maxlen=2，自动丢弃旧帧）
        self._frame_queue = deque(maxlen=2)
        self._frame_lock = threading.Lock()

        # 扫描状态
        self._scan_dir = 1       # 1=右扫, -1=左扫
        self._scan_pan_min = 30
        self._scan_pan_max = 150
        self._scan_step = 10     # 每步度数
        self._scan_interval = 0.5  # 每步间隔秒

        # 协调
        self._receiver_running = False
        self._detector_running = False

    # ── 状态读写 ──────────────────────────────

    @property
    def is_active(self):
        with self._lock:
            return self._state != TrackState.IDLE

    @property
    def state(self):
        with self._lock:
            return self._state

    def set_qq_bridge(self, bridge):
        self._qq_bridge = bridge

    def refresh_cmd_time(self):
        with self._lock:
            self._last_cmd_time = time.time()

    def check_idle_timeout(self) -> bool:
        with self._lock:
            return (time.time() - self._last_cmd_time) > self._idle_timeout

    # ── 状态转换 ──────────────────────────────

    def activate(self):
        with self._lock:
            self._state = TrackState.TRACKING
            self._last_cmd_time = time.time()
            self._frame_queue.clear()

    def deactivate(self):
        with self._lock:
            self._state = TrackState.IDLE
            self._frame_queue.clear()

    def enter_scanning(self):
        with self._lock:
            if self._state == TrackState.TRACKING:
                self._state = TrackState.SCANNING

    def enter_tracking(self):
        with self._lock:
            if self._state == TrackState.SCANNING:
                self._state = TrackState.TRACKING

    @property
    def is_scanning(self):
        with self._lock:
            return self._state == TrackState.SCANNING

    # ── 帧队列 ────────────────────────────────

    def push_frame(self, frame):
        """推入帧（自动丢弃旧帧当队列满）。"""
        with self._frame_lock:
            self._frame_queue.append(frame)

    def pop_frame(self):
        """取出最新帧。返回 None 如果队列空。"""
        with self._frame_lock:
            if self._frame_queue:
                return self._frame_queue.popleft()
            return None

    def clear_frames(self):
        with self._frame_lock:
            self._frame_queue.clear()

    # ── Worker 生命周期 ────────────────────────

    @property
    def receiver_running(self):
        with self._lock:
            return self._receiver_running

    @receiver_running.setter
    def receiver_running(self, v: bool):
        with self._lock:
            self._receiver_running = v

    @property
    def detector_running(self):
        with self._lock:
            return self._detector_running

    @detector_running.setter
    def detector_running(self, v: bool):
        with self._lock:
            self._detector_running = v

    # ── 退出通知 ───────────────────────────────

    def notify_exit(self, reason: str):
        """安全退出：停用状态、通知 QQ。"""
        self.deactivate()
        if self._qq_bridge:
            try:
                self._qq_bridge.send_to_owner(
                    f"{reason}\n人体跟踪已退出～(｡•́︿•̀｡)"
                )
            except Exception:
                pass


# ── 单例工厂 ─────────────────────────────────────

_track_manager = None
_track_lock = threading.Lock()


def get_track_manager() -> TrackManager:
    global _track_manager
    if _track_manager is None:
        with _track_lock:
            if _track_manager is None:
                _track_manager = TrackManager()
    return _track_manager
