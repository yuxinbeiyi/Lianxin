"""
FaceDetector：MediaPipe 人脸检测 + 表情分析封装
"""
import os
import numpy as np
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.vision import (
    FaceDetectorOptions,
    FaceDetector as MPFaceDetector,
    FaceLandmarkerOptions,
    FaceLandmarker as MPFaceLandmarker,
)
from mediapipe.tasks.python import BaseOptions
from mediapipe import Image, ImageFormat

_MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")


def _load_bytes(filename):
    with open(os.path.join(_MODELS_DIR, filename), "rb") as f:
        return f.read()


class FaceDetector:
    """人脸检测 + 表情分析，使用 MediaPipe BlazeFace + FaceLandmarker"""

    def __init__(self):
        # 快速人脸检测（用于发现/消失）
        fd_opts = FaceDetectorOptions(
            base_options=BaseOptions(model_asset_buffer=_load_bytes("blaze_face_short_range.tflite")),
            min_detection_confidence=0.6,
        )
        self._fd = MPFaceDetector.create_from_options(fd_opts)

        # 面部关键点（用于微笑检测）
        fl_opts = FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_buffer=_load_bytes("face_landmarker.task")),
            running_mode=vision.RunningMode.IMAGE,
        )
        self._fl = MPFaceLandmarker.create_from_options(fl_opts)

        self._closed = False
        self._smile_history = []  # 微笑历史帧
        self._frame_count = 0

    def detect(self, frame: np.ndarray):
        """检测帧中人脸，返回 [(bbox, keypoints)]"""
        mp_image = Image(image_format=ImageFormat.SRGB, data=frame)
        result = self._fd.detect(mp_image)
        faces = []
        for d in result.detections:
            bbox = d.bounding_box  # (origin_x, origin_y, width, height)
            keypoints = d.keypoints  # 6 keypoints (eyes, nose, mouth)
            faces.append((bbox, keypoints))
        return faces

    def detect_with_landmarks(self, frame: np.ndarray):
        """检测帧中的人脸关键点（468点），用于表情分析。每3帧调用一次。"""
        self._frame_count += 1
        faces = self.detect(frame)
        if not faces:
            return []

        mp_image = Image(image_format=ImageFormat.SRGB, data=frame)
        result = self._fl.detect(mp_image)

        face_data = []
        for i, landmarks in enumerate(result.face_landmarks):
            if i < len(faces):
                bbox, keypoints = faces[i]
            else:
                bbox, keypoints = None, None
            smile_score = self._calc_smile(landmarks)
            face_data.append({
                "bbox": bbox,
                "keypoints": keypoints,
                "landmarks": landmarks,
                "smile_score": smile_score,
            })

        # 微笑防抖：需要连续3帧微笑才确认
        if face_data:
            score = face_data[0]["smile_score"]
            self._smile_history.append(score)
            if len(self._smile_history) > 5:
                self._smile_history.pop(0)
        else:
            self._smile_history = []

        return face_data

    @property
    def smile_stable(self):
        """微笑是否稳定（连续多帧）"""
        if len(self._smile_history) < 3:
            return False
        return all(s > 0.5 for s in self._smile_history[-3:])

    @staticmethod
    def _calc_smile(landmarks):
        """基于唇部关键点计算微笑得分"""
        # 左嘴角: 61, 右嘴角: 291, 上唇中: 13, 下唇中: 14
        left = np.array([landmarks[61].x, landmarks[61].y])
        right = np.array([landmarks[291].x, landmarks[291].y])
        top = np.array([landmarks[13].x, landmarks[13].y])
        bottom = np.array([landmarks[14].x, landmarks[14].y])

        mouth_width = np.linalg.norm(right - left)
        mouth_height = np.linalg.norm(bottom - top)

        if mouth_height < 1e-6:
            return 0.0

        # 微笑时嘴角向外拉、张嘴高度相对小 → ratio大
        # 正常时 ratio ≈ 1.5-2.5, 微笑时 ≈ 3.0-6.0
        ratio = mouth_width / mouth_height
        score = min(1.0, max(0.0, (ratio - 1.5) / 4.5))
        return score

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._fd.close()
        except Exception:
            pass
        try:
            self._fl.close()
        except Exception:
            pass
        self._fd = None
        self._fl = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
