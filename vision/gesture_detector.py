"""
GestureDetector：MediaPipe 手势识别封装
"""
import os
import numpy as np
from collections import deque
from mediapipe.tasks.python.vision import HandLandmarkerOptions, HandLandmarker as MPHandLandmarker
from mediapipe.tasks.python import BaseOptions, vision
from mediapipe import Image, ImageFormat

_MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")


def _load_bytes(filename):
    with open(os.path.join(_MODELS_DIR, filename), "rb") as f:
        return f.read()


class GestureDetector:
    """手势识别，使用 MediaPipe HandLandmarker"""

    def __init__(self):
        opts = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_buffer=_load_bytes("hand_landmarker.task")),
            running_mode=vision.RunningMode.IMAGE,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._hl = MPHandLandmarker.create_from_options(opts)
        self._closed = False

        # 手腕历史位置（用于招手检测）
        self._wrist_history = deque(maxlen=15)  # 最近15帧的手腕x坐标
        self._wave_direction_changes = 0  # 方向变化次数
        self._last_wrist_dx = 0  # 上次手腕移动方向
        self._wave_frames_since_last = 0  # 距上次招手确认的帧数

    def detect(self, frame: np.ndarray):
        """检测手势，返回手势类型字符串或 None。"""
        mp_image = Image(image_format=ImageFormat.SRGB, data=frame)
        result = self._hl.detect(mp_image)

        if not result.hand_landmarks:
            self._wrist_history.clear()
            self._wave_direction_changes = 0
            self._last_wrist_dx = 0
            self._wave_frames_since_last += 1
            return None

        # 分析第一只手
        landmarks = result.hand_landmarks[0]
        wrist = landmarks[0]  # 手腕关键点

        self._wrist_history.append(wrist.x)
        self._wave_frames_since_last += 1

        # 连续3帧没有挥手才重置计数
        if self._wave_frames_since_last > 3:
            self._wave_direction_changes = 0

        # 检测招手：手腕在水平方向来回摆动
        if len(self._wrist_history) >= 5:
            if self._is_waving():
                self._wave_frames_since_last = 0
                return "wave"

        return None

    def _is_waving(self):
        """基于手腕运动检测招手"""
        positions = list(self._wrist_history)
        dx_sum = 0

        for i in range(1, len(positions)):
            dx = positions[i] - positions[i - 1]
            # 检测方向变化（忽略微小抖动）
            if abs(dx) > 0.008:  # 有效移动阈值
                if (dx > 0) != (self._last_wrist_dx > 0):
                    self._wave_direction_changes += 1
                    self._last_wrist_dx = dx
                dx_sum += abs(dx)

        # 挥手条件：至少3次方向变化 + 足够的总位移
        if self._wave_direction_changes >= 3 and dx_sum > 0.04:
            self._wave_direction_changes = 0
            self._last_wrist_dx = 0
            return True

        return False

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._hl.close()
        except Exception:
            pass
        self._hl = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
