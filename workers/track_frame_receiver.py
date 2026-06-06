"""
TrackFrameReceiver：人体跟踪帧接收线程。
连接 relay → 发送 track_start → 循环接收 JPEG 帧 → 解码入队。
"""

import asyncio
import time

import cv2
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from brain.hardware_bridge import HardwareBridge
from brain.human_tracking import get_track_manager


class TrackFrameReceiver(QThread):
    """独立 QThread：接收 ESP32 推流帧，解码后推入有界队列。"""

    error_occurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bridge = None
        self._loop = None

    def run(self):
        manager = get_track_manager()
        self._bridge = HardwareBridge()

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        if not self._loop.run_until_complete(self._bridge.connect_persistent()):
            manager.notify_exit("连接肩载设备失败")
            self.error_occurred.emit("连接失败")
            return

        # 启动 ESP32 推流
        resp = self._loop.run_until_complete(
            self._bridge._send_cmd("track_start", timeout_sec=10)
        )
        if resp is None:
            manager.notify_exit("启动跟踪推流失败")
            self.error_occurred.emit("track_start 失败")
            self._cleanup()
            return

        manager.receiver_running = True
        print("[track-recv] 帧接收已启动")

        try:
            while manager.is_active:
                try:
                    data = self._loop.run_until_complete(
                        asyncio.wait_for(self._bridge.ws.recv(), timeout=5.0)
                    )
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break

                if isinstance(data, bytes) and len(data) > 100:
                    frame = cv2.imdecode(
                        np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR
                    )
                    if frame is not None:
                        manager.push_frame(frame)
        except Exception as e:
            self.error_occurred.emit(f"接收异常: {e}")
        finally:
            self._cleanup()

    def _cleanup(self):
        manager = get_track_manager()
        if self._loop and self._bridge:
            try:
                self._loop.run_until_complete(
                    self._bridge._send_cmd("track_stop", timeout_sec=3)
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
        manager.receiver_running = False
        print("[track-recv] 已停止")
