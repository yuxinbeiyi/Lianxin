"""
VisionWorker：摄像头视觉识别线程
持续从摄像头读取帧，检测人脸、表情和手势，通过信号通知主窗口。
"""
import time
import cv2
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from vision.face_detector import FaceDetector
from vision.gesture_detector import GestureDetector


class VisionWorker(QThread):
    face_appeared = pyqtSignal()
    face_disappeared = pyqtSignal()
    smile_detected = pyqtSignal(float)  # 微笑置信度 0.0-1.0
    wave_detected = pyqtSignal()
    error_occurred = pyqtSignal(str)

    LANDMARK_INTERVAL = 3  # 每3帧做一次关键点分析
    GESTURE_INTERVAL = 2   # 每2帧做一次手势检测

    def __init__(self, camera_index=0, parent=None):
        super().__init__(parent)
        self._camera_index = camera_index
        self._running = False
        self._face_detector = None
        self._gesture_detector = None

        # 冷却计时
        self._last_face_appeared_time = 0
        self._last_face_disappeared_time = 0
        self._last_smile_time = 0
        self._last_wave_time = 0
        self._face_appeared_frames = 0
        self._face_lost_frames = 0

    # ── 冷却常量 ──
    FACE_APPEARED_COOLDOWN = 10.0
    FACE_DISAPPEARED_COOLDOWN = 5.0
    SMILE_COOLDOWN = 12.0
    WAVE_COOLDOWN = 8.0
    FACE_STABLE_FRAMES = 5
    FACE_LOST_FRAMES = 8

    def run(self):
        self._running = True
        self._face_detector = FaceDetector()
        self._gesture_detector = GestureDetector()

        cap = cv2.VideoCapture(self._camera_index)
        if not cap.isOpened():
            self.error_occurred.emit(f"无法打开摄像头（索引 {self._camera_index}），请检查摄像头是否连接。")
            self._close_detectors()
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)

        face_present = False
        frame_index = 0
        now = time.time()

        self._last_face_appeared_time = now
        self._last_face_disappeared_time = 0
        self._last_smile_time = now
        self._last_wave_time = now

        try:
            while self._running:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.05)
                    continue

                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frame_index += 1
                now = time.time()

                # 快速人脸检测（每帧）
                faces = self._face_detector.detect(frame)

                if faces:
                    self._face_appeared_frames += 1
                    self._face_lost_frames = 0

                    if not face_present and self._face_appeared_frames >= self.FACE_STABLE_FRAMES:
                        if now - self._last_face_appeared_time >= self.FACE_APPEARED_COOLDOWN:
                            face_present = True
                            self._last_face_appeared_time = now
                            self.face_appeared.emit()

                    # 每N帧做一次表情分析
                    if frame_index % self.LANDMARK_INTERVAL == 0 and face_present:
                        face_data = self._face_detector.detect_with_landmarks(frame)
                        if face_data:
                            smile_score = face_data[0]["smile_score"]
                            if self._face_detector.smile_stable:
                                if smile_score > 0.6 and now - self._last_smile_time >= self.SMILE_COOLDOWN:
                                    self._last_smile_time = now
                                    self.smile_detected.emit(smile_score)

                    # 每N帧做一次手势检测
                    if frame_index % self.GESTURE_INTERVAL == 0 and face_present:
                        gesture = self._gesture_detector.detect(frame)
                        if gesture == "wave" and now - self._last_wave_time >= self.WAVE_COOLDOWN:
                            self._last_wave_time = now
                            self.wave_detected.emit()

                else:
                    self._face_lost_frames += 1
                    self._face_appeared_frames = 0

                    if face_present and self._face_lost_frames >= self.FACE_LOST_FRAMES:
                        if now - self._last_face_disappeared_time >= self.FACE_DISAPPEARED_COOLDOWN:
                            face_present = False
                            self._last_face_disappeared_time = now
                            self.face_disappeared.emit()

                # 约 30fps
                time.sleep(0.03)

        except Exception as e:
            self.error_occurred.emit(f"视觉识别异常：{e}")
        finally:
            cap.release()
            self._close_detectors()

    def _close_detectors(self):
        if self._face_detector:
            self._face_detector.close()
        if self._gesture_detector:
            self._gesture_detector.close()

    def stop(self):
        self._running = False
