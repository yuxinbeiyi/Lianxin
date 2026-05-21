import cv2
import tempfile
import os
from config import get_camera_config, save_camera_config

def capture_from_camera(device_index: int = None) -> str:
    if device_index is None:
        cfg = get_camera_config()
        device_index = cfg.get("device_index", 0)
    cap = cv2.VideoCapture(device_index)
    if not cap.isOpened():
        # 尝试备用索引
        for i in range(5):  # 尝试0-4
            if i == device_index:
                continue
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                device_index = i
                # 保存新的可用索引（可选）
                cfg = get_camera_config()
                cfg["device_index"] = i
                save_camera_config(cfg)
                break
        else:
            return ""
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return ""
    fd, path = tempfile.mkstemp(suffix='.jpg', prefix='lianxin_cam_')
    os.close(fd)
    cv2.imwrite(path, frame)
    return path

# 兼容旧导入（如果其他地方 from utils.camera import Camera）
class Camera:
    """照相机类，提供 capture 和 capture_image 两个方法"""
    @staticmethod
    def capture():
        return capture_from_camera()

    @staticmethod
    def capture_image():
        return capture_from_camera()