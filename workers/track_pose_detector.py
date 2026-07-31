"""
TrackPoseDetector：人体姿态检测 + 舵机控制线程。
从帧队列取帧 → MediaPipe Pose 推理 → 算人体中心偏移 → 发舵机命令。
"""

import asyncio
import time

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from brain.hardware_bridge import HardwareBridge
from brain.human_tracking import get_track_manager, TrackState
from vision.gesture_detector import _load_bytes

# MediaPipe
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    PoseLandmarker,
    PoseLandmarkerOptions,
    RunningMode,
)
from mediapipe import Image, ImageFormat

# ── 跟踪参数 ──────────────────────────────────────────

DEAD_ZONE = 40           # 死区（像素）
GAIN = 0.08              # 比例增益（像素 → 角度）
CMD_INTERVAL = 0.2       # 舵机命令最小间隔（秒）
MAX_LOST_FRAMES = 10     # 连续丢失帧数 → 进入扫描
PAN_MIN, PAN_MAX = 20, 150
TILT_MIN, TILT_MAX = 20, 130

# 扫描参数
SCAN_STEP = 10           # 每步度数
SCAN_INTERVAL = 0.5      # 每步间隔秒


class TrackPoseDetector(QThread):
    """独立 QThread：Pose 推理 + 舵机控制。"""

    cycle_completed = pyqtSignal(str)
    mode_exited = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._detector = None
        self._bridge = None
        self._loop = None
        self._pan, self._tilt = 90, 45
        self._lost_frames = 0
        self._last_cmd_time = 0
        # 扫描方向
        self._scan_dir = 1

    def run(self):
        manager = get_track_manager()

        try:
            opts = PoseLandmarkerOptions(
                base_options=BaseOptions(
                    model_asset_buffer=_load_bytes("pose_landmarker_lite.task")
                ),
                running_mode=RunningMode.IMAGE,
                num_poses=1,
                min_pose_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._detector = PoseLandmarker.create_from_options(opts)
        except Exception as e:
            manager.notify_exit(f"姿态检测模型加载失败：{e}")
            return

        self._bridge = HardwareBridge()
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        if not self._loop.run_until_complete(self._bridge.connect_persistent()):
            manager.notify_exit("PoseDetector 连接肩载设备失败")
            return

        manager.detector_running = True
        print("[track-pose] 姿态检测已启动")

        try:
            self._detection_loop()
        except Exception as e:
            manager.notify_exit(f"人体跟踪异常退出：{e}")
        finally:
            self._center_gimbal()
            self._cleanup()

    # ════════════════════════════════════════════════════════
    # 主循环
    # ════════════════════════════════════════════════════════

    def _detection_loop(self):
        manager = get_track_manager()

        while manager.is_active:
            frame = manager.pop_frame()
            if frame is None:
                time.sleep(0.05)
                continue

            h, w = frame.shape[:2]

            # Pose 推理
            try:
                mp_image = Image(image_format=ImageFormat.SRGB, data=frame)
                result = self._detector.detect(mp_image)
            except Exception:
                continue

            if result.pose_landmarks and len(result.pose_landmarks) > 0:
                # 找到人体 → 退出扫描，进入跟踪
                self._lost_frames = 0
                if manager.state == TrackState.SCANNING:
                    manager.enter_tracking()

                landmarks = result.pose_landmarks[0]

                # 身体中心 = 双肩中点 + 双髋中点 → 取平均
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

                # 偏移
                dx = cx - w / 2
                dy = cy - h / 2

                # 死区 + 比例控制
                self._apply_control(dx, dy)
            else:
                self._lost_frames += 1
                if self._lost_frames >= MAX_LOST_FRAMES:
                    manager.enter_scanning()

            # 扫描模式
            if manager.is_scanning:
                self._scan_step()

            # 超时检查
            if manager.check_idle_timeout():
                manager.notify_exit("人体跟踪已超时（5分钟无消息），自动退出啦～")
                break

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
            self._send_servo()

    def _can_send_cmd(self) -> bool:
        return (time.time() - self._last_cmd_time) >= CMD_INTERVAL

    def _send_servo(self):
        cmd = f"servo {self._pan} {self._tilt}"
        try:
            self._loop.run_until_complete(self._bridge.send_cmd_tracking(cmd))
            self._last_cmd_time = time.time()
        except Exception:
            pass

    # ════════════════════════════════════════════════════════
    # 扫描
    # ════════════════════════════════════════════════════════

    def _scan_step(self):
        if not self._can_send_cmd():
            return
        self._pan += self._scan_dir * SCAN_STEP
        if self._pan >= self._scan_pan_max:
            self._pan = self._scan_pan_max
            self._scan_dir = -1
        elif self._pan <= self._scan_pan_min:
            self._pan = self._scan_pan_min
            self._scan_dir = 1
        self._send_servo()

    @property
    def _scan_pan_min(self):
        return PAN_MIN + 10

    @property
    def _scan_pan_max(self):
        return PAN_MAX - 10

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
        if self._loop and self._bridge:
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
        print("[track-pose] 已停止")
