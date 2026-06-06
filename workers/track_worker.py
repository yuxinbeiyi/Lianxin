"""
TrackWorker：人体跟踪统一线程。
单条 WebSocket 长连接完成：推流启动 → 收 JPEG 帧 → MediaPipe Pose 推理 → 舵机跟随。
"""

import asyncio
import time

import cv2
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from brain.hardware_bridge import HardwareBridge
from brain.human_tracking import get_track_manager, TrackState
from vision.gesture_detector import _load_bytes

from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    PoseLandmarker,
    PoseLandmarkerOptions,
    RunningMode,
)
from mediapipe import Image, ImageFormat

# ── 跟踪参数 ──────────────────────────────────────────

DEAD_ZONE = 40
GAIN = 0.06              # 降低增益，减少抖动
CMD_INTERVAL = 0.3       # 舵机命令间隔延长到 300ms
MAX_LOST_FRAMES = 15     # 提高丢失容忍
MIN_DETECT_STREAK = 3    # 连续检测到 N 帧后才开始跟踪
PAN_MIN, PAN_MAX = 20, 150
TILT_MIN, TILT_MAX = 20, 130

# 扫描参数
SCAN_STEP = 7             # 扫描步长（度）
SCAN_INTERVAL = 0.5       # 扫描步间隔（秒）
STREAM_RESTART_TIMEOUTS = 8  # 连续超时 N 次后尝试重启 ESP32 推流


def _log(msg: str):
    print(msg, flush=True)


class TrackWorker(QThread):
    """单线程：收帧 + Pose 推理 + 舵机控制，共用一条 WebSocket。"""

    mode_exited = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._detector = None
        self._bridge = None
        self._loop = None
        self._pan, self._tilt = 90, 45
        self._lost_frames = 0
        self._consec_timeouts = 0    # 连续超时计数
        self._detect_streak = 0      # 连续检测到人的帧数
        self._last_cmd_time = 0
        self._last_scan_time = 0     # 上次扫描步时间
        self._scan_dir = 1
        self._frame_count = 0

    def run(self):
        manager = get_track_manager()

        # ── 加载 Pose 模型 ──────────────────────────
        try:
            opts = PoseLandmarkerOptions(
                base_options=BaseOptions(
                    model_asset_buffer=_load_bytes("pose_landmarker_lite.task")
                ),
                running_mode=RunningMode.IMAGE,
                num_poses=1,
                min_pose_detection_confidence=0.3,
                min_tracking_confidence=0.3,
            )
            self._detector = PoseLandmarker.create_from_options(opts)
        except Exception as e:
            manager.notify_exit(f"姿态检测模型加载失败：{e}")
            return

        # ── 连接 relay ──────────────────────────────
        self._bridge = HardwareBridge()
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        if not self._loop.run_until_complete(self._bridge.connect_persistent()):
            manager.notify_exit("人体跟踪连接肩载设备失败")
            return

        # ── Pre-flight：确认 ESP32 在线 ────────────
        _log("[track] 检测 ESP32 是否在线...")
        esp32_online = False
        for attempt in range(5):
            status = self._loop.run_until_complete(
                self._bridge._send_cmd("status", timeout_sec=5)
            )
            if status and "free_heap" in str(status):
                _log(f"[track] ESP32 在线 (attempt {attempt + 1})")
                esp32_online = True
                break
            _log(f"[track] ESP32 未响应，{2}s 后重试 ({attempt + 1}/5)...")
            time.sleep(2)

        if not esp32_online:
            manager.notify_exit("ESP32 不在线，请检查肩载设备是否通电、WiFi 是否连接")
            self._cleanup()
            return

        # ── 先 stop 再 start，确保 ESP32 状态干净 ──
        _log("[track] 重置 ESP32 推流状态...")
        self._loop.run_until_complete(
            self._bridge.send_cmd_tracking("track_stop")
        )
        time.sleep(0.5)

        # ── 启动 ESP32 推流 ─────────────────────────
        _log("[track] 正在启动 ESP32 推流...")
        resp = self._loop.run_until_complete(
            self._bridge._send_cmd("track_start", timeout_sec=10)
        )
        if resp is None:
            manager.notify_exit("启动跟踪推流失败（ESP32 无响应）")
            self._cleanup()
            return

        _log(f"[track] ESP32 响应: {resp}")
        if '"error"' in str(resp) or 'unknown cmd' in str(resp):
            manager.notify_exit(
                f"ESP32 固件不支持跟踪模式，请重新烧录最新固件\n（响应: {resp}）"
            )
            self._cleanup()
            return

        manager.detector_running = True
        _log("[track] 人体跟踪已启动，进入主循环")

        try:
            self._tracking_loop()
        except Exception as e:
            manager.notify_exit(f"人体跟踪异常退出：{e}")
        finally:
            self._center_gimbal()
            self._cleanup()

    # ════════════════════════════════════════════════════════
    # 主循环
    # ════════════════════════════════════════════════════════

    def _tracking_loop(self):
        manager = get_track_manager()
        _log("[track] 主循环开始，等待接收帧...")

        while manager.is_active:
            # ── 收帧 ────────────────────────────────
            try:
                data = self._loop.run_until_complete(
                    asyncio.wait_for(self._bridge.ws.recv(), timeout=5.0)
                )
                self._consec_timeouts = 0  # 收到数据，重置超时计数
            except asyncio.TimeoutError:
                self._consec_timeouts += 1
                self._lost_frames += 1
                if self._consec_timeouts == 1:
                    _log("[track] 警告：5 秒未收到帧")
                if self._consec_timeouts >= STREAM_RESTART_TIMEOUTS:
                    _log("[track] 连续 8 次超时，尝试重启 ESP32 推流...")
                    self._restart_stream()
                    self._consec_timeouts = 0
                if self._lost_frames >= MAX_LOST_FRAMES:
                    if manager.state != TrackState.SCANNING:
                        _log("[track] 进入扫描模式")
                        manager.enter_scanning()
                        self._last_scan_time = 0  # 立即开始第一步扫描
                if manager.is_scanning:
                    self._do_scan_if_ready()
                continue
            except Exception as e:
                _log(f"[track] WebSocket 接收异常: {e}")
                break

            # ── 跳过文本消息 ──────────────────────
            if isinstance(data, str):
                continue
            if not isinstance(data, bytes) or len(data) <= 100:
                continue

            self._frame_count += 1

            frame = cv2.imdecode(
                np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR
            )
            if frame is None:
                continue

            # 首帧保存
            if self._frame_count == 1:
                cv2.imwrite("E:/Desktop/Claude/track_first_frame.jpg", frame)
                h0, w0 = frame.shape[:2]
                _log(f"[track] 首帧已保存: {w0}x{h0} → E:/Desktop/Claude/track_first_frame.jpg")

            # OpenCV BGR → MediaPipe RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w = frame.shape[:2]

            # ── Pose 推理 ───────────────────────────
            try:
                mp_image = Image(image_format=ImageFormat.SRGB, data=frame_rgb)
                result = self._detector.detect(mp_image)
            except Exception:
                continue

            if result.pose_landmarks and len(result.pose_landmarks) > 0:
                self._detect_streak += 1
                self._lost_frames = 0
                self._consec_timeouts = 0

                # 退出扫描模式
                if manager.state == TrackState.SCANNING:
                    _log("[track] 扫描中检测到人体，退出扫描模式")
                    manager.enter_tracking()

                landmarks = result.pose_landmarks[0]

                l_shoulder = landmarks[11]
                r_shoulder = landmarks[12]
                l_hip = landmarks[23]
                r_hip = landmarks[24]

                shoulder_cx = (l_shoulder.x + r_shoulder.x) / 2 * w
                shoulder_cy = (l_shoulder.y + r_shoulder.y) / 2 * h
                hip_cx = (l_hip.x + r_hip.x) / 2 * w
                hip_cy = (l_hip.y + r_hip.y) / 2 * h

                cx = (shoulder_cx + hip_cx) / 2
                cy = (shoulder_cy + hip_cy) / 2

                dx = cx - w / 2
                dy = cy - h / 2

                if self._frame_count % 10 == 1:
                    _log(f"[track] #{self._frame_count} 检出(连续{self._detect_streak}帧) "
                         f"中心=({cx:.0f},{cy:.0f}) 偏移=({dx:+.0f},{dy:+.0f}) "
                         f"舵机=({self._pan},{self._tilt})")

                # 连续检测到足够帧后才开始控制舵机
                if self._detect_streak >= MIN_DETECT_STREAK:
                    self._apply_control(dx, dy)
            else:
                if self._detect_streak > 0:
                    self._detect_streak = 0
                self._lost_frames += 1
                if self._lost_frames >= MAX_LOST_FRAMES:
                    if manager.state != TrackState.SCANNING:
                        _log(f"[track] 连续 {MAX_LOST_FRAMES} 帧无人，进入扫描模式")
                        manager.enter_scanning()
                        self._last_scan_time = 0

            # ── 扫描 ────────────────────────────────
            if manager.is_scanning:
                self._do_scan_if_ready()

            # ── 超时 ────────────────────────────────
            if manager.check_idle_timeout():
                manager.notify_exit("人体跟踪已超时（5分钟无消息），自动退出啦～")
                break

    # ════════════════════════════════════════════════════════
    # 推流重启
    # ════════════════════════════════════════════════════════

    def _restart_stream(self):
        """尝试重启 ESP32 推流（当连续超时时调用）。"""
        try:
            self._loop.run_until_complete(
                self._bridge.send_cmd_tracking("track_stop")
            )
            time.sleep(0.5)
            resp = self._loop.run_until_complete(
                self._bridge._send_cmd("track_start", timeout_sec=10)
            )
            if resp and '"track"' in str(resp):
                _log("[track] ESP32 推流已重启")
            else:
                _log(f"[track] ESP32 推流重启失败: {resp}")
        except Exception as e:
            _log(f"[track] 推流重启异常: {e}")

    # ════════════════════════════════════════════════════════
    # 控制算法
    # ════════════════════════════════════════════════════════

    def _apply_control(self, dx: float, dy: float):
        if not self._can_send_cmd():
            return

        moved = False
        if abs(dx) > DEAD_ZONE:
            self._pan = max(PAN_MIN, min(PAN_MAX,
                int(self._pan - dx * GAIN)))
            moved = True
        if abs(dy) > DEAD_ZONE:
            self._tilt = max(TILT_MIN, min(TILT_MAX,
                int(self._tilt + dy * GAIN)))
            moved = True

        if moved:
            _log(f"[track] 舵机 → pan={self._pan} tilt={self._tilt}")
            self._send_servo()

    def _can_send_cmd(self) -> bool:
        return (time.time() - self._last_cmd_time) >= CMD_INTERVAL

    def _send_servo(self):
        cmd = f"servo {self._pan} {self._tilt}"
        try:
            self._loop.run_until_complete(self._bridge.send_cmd_tracking(cmd))
            self._last_cmd_time = time.time()
        except Exception as e:
            _log(f"[track] 舵机命令发送失败: {e}")

    # ════════════════════════════════════════════════════════
    # 扫描（间隔控制，避免晃动太快）
    # ════════════════════════════════════════════════════════

    def _do_scan_if_ready(self):
        """按时间间隔执行扫描步。"""
        now = time.time()
        if now - self._last_scan_time < SCAN_INTERVAL:
            return
        self._last_scan_time = now

        self._pan += self._scan_dir * SCAN_STEP
        if self._pan >= PAN_MAX:
            self._pan = PAN_MAX
            self._scan_dir = -1
        elif self._pan <= PAN_MIN:
            self._pan = PAN_MIN
            self._scan_dir = 1
        _log(f"[track] 扫描 → pan={self._pan}")
        self._send_servo()

    # ════════════════════════════════════════════════════════
    # 清理
    # ════════════════════════════════════════════════════════

    def _center_gimbal(self):
        if self._loop and self._bridge:
            try:
                self._loop.run_until_complete(
                    self._bridge.send_cmd_tracking("servo 90 45")
                )
            except Exception:
                pass

    def _cleanup(self):
        manager = get_track_manager()
        _log("[track] 正在清理...")
        if self._loop and self._bridge:
            try:
                self._loop.run_until_complete(
                    self._bridge.send_cmd_tracking("track_stop")
                )
            except Exception:
                pass
            try:
                self._loop.run_until_complete(self._bridge.disconnect())
            except Exception:
                pass
            try:
                self._loop.close()
            except Exception:
                pass
        if self._detector:
            try:
                self._detector.close()
            except Exception:
                pass
        manager.detector_running = False
        self.mode_exited.emit("done")
        _log(f"[track] 已停止（共接收 {self._frame_count} 帧）")
