"""
Observation 模块：截图、摄像头抓拍、观察分析
截图用 PIL（零额外依赖），摄像头用 OpenCV。
所有函数在后台线程调用，不会阻塞 UI。
"""

import os
import tempfile
import time
from typing import Optional


def capture_screen() -> Optional[str]:
    """截取当前屏幕。返回临时 PNG 路径，失败返回 None。"""
    print("[观察-调试] capture_screen: 开始...")
    try:
        from PIL import ImageGrab
        print("[观察-调试] capture_screen: 调用 ImageGrab.grab()...")
        img = ImageGrab.grab()
        print(f"[观察-调试] capture_screen: 截屏成功, size={img.size}")
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        img.save(tmp, "PNG")
        tmp.close()
        print(f"[观察-调试] capture_screen: 保存到 {tmp.name}")
        return tmp.name
    except Exception as e:
        print(f"[观察] 截图失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def capture_camera(camera_index: int = 0, wait_seconds: int = 5) -> Optional[str]:
    """打开摄像头，等待 wait_seconds 秒（让画面稳定）后抓拍一张。
    返回临时 JPG 路径，失败返回 None。"""
    try:
        import cv2
    except ImportError:
        print("[观察] 需要 opencv-python，请执行: pip install opencv-python")
        return None

    cap = None
    try:
        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            print(f"[观察] 无法打开摄像头 index={camera_index}")
            return None

        # 预热 — 丢弃前几帧（自动曝光/白平衡稳定）
        for _ in range(15):
            cap.read()

        # 持续读取直到等待时间结束，然后抓一帧
        start = time.monotonic()
        while time.monotonic() - start < wait_seconds:
            cap.read()

        ret, frame = cap.read()
        if not ret or frame is None:
            print("[观察] 摄像头抓拍失败")
            return None

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        cv2.imwrite(tmp.name, frame)
        tmp.close()
        return tmp.name
    except Exception as e:
        print(f"[观察] 摄像头异常: {e}")
        return None
    finally:
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass


def analyze_observation(image_path: str, source_name: str = "截图") -> str:
    """分析观察到的画面，返回自然语言描述。"""
    print(f"[观察-调试] analyze_observation: {source_name}, path={image_path}")
    try:
        from brain.vision import describe_image
        prompt = (
            "请详细描述这张画面里的内容，包括人物动作、面部表情、"
            "屏幕显示内容、桌面环境等所有你观察到的细节。"
        )
        print("[观察-调试] analyze_observation: 调用 describe_image...")
        result = describe_image(image_path, prompt=prompt)
        print(f"[观察-调试] analyze_observation: 完成, len={len(result)}")
        return result
    except Exception as e:
        print(f"[观察-调试] analyze_observation: 失败 {e}")
        return f"[{source_name}分析失败: {e}]"