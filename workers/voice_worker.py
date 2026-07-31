"""
VoiceWorker：后台线程，负责麦克风录音 + Whisper 识别
ModelLoader：后台线程，预加载 Whisper 模型（避免首次点击卡顿）
"""

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from voice.listener import VoiceListener


class ModelLoader(QThread):
    """启动时在后台静默加载 Whisper 模型。"""
    finished = pyqtSignal()
    failed   = pyqtSignal(str)

    def __init__(self, listener: VoiceListener, parent=None):
        super().__init__(parent)
        self._listener = listener

    def run(self):
        try:
            self._listener.load_model()
            self.finished.emit()
        except Exception as e:
            self.failed.emit(str(e))


class VoiceWorker(QThread):
    """录音 + 识别，完成后把文字发送给主线程。"""
    recording_started = pyqtSignal()       # 开始录音
    recording_stopped = pyqtSignal()       # 录音结束（开始识别）
    text_ready        = pyqtSignal(str)    # 识别完成，返回文字
    error_occurred    = pyqtSignal(str)    # 出错

    def __init__(self, listener: VoiceListener, parent=None):
        super().__init__(parent)
        self._listener = listener

    def run(self):
        try:
            import time as _time
            self.recording_started.emit()
            _t0 = _time.time()
            audio = self._listener.record()
            _t1 = _time.time()
            self.recording_stopped.emit()       # 录音结束，开始识别
            print(f"[语音] 录音耗时 {_t1-_t0:.1f}s, 音频长度 {len(audio)/16000:.1f}s", flush=True)

            if len(audio) == 0:
                self.error_occurred.emit("未检测到声音，请靠近麦克风再试")
                return

            text = self._listener.transcribe(audio)
            _t2 = _time.time()
            print(f"[语音] 识别耗时 {_t2-_t1:.1f}s, 总计 {_t2-_t0:.1f}s", flush=True)
            if text:
                self.text_ready.emit(text)
            else:
                self.error_occurred.emit("未能识别到内容，请重试")
        except Exception as e:
            self.recording_stopped.emit()
            self.error_occurred.emit(str(e))

    def stop(self):
        self._listener.stop()