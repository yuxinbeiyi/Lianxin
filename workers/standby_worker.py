"""
StandbyWorker：待机模式后台监听线程
持续录音 + 识别，检测到唤醒词后停止并发射信号。
"""

import time
from PyQt5.QtCore import QThread, pyqtSignal
from voice.listener import VoiceListener


# ── 唤醒词变体（含常见谐音误识别）──────────────────────────────
_WAKE_WORDS = [
    "莲心在吗", "莲心在么", "莲心在嘛","在吗"
    "连心在吗", "连心在么", "连心在嘛","你好","您好","泥好",
    "链心在吗", "恋心在吗",
    "莲心莲心", "连心连心",
    "莲心",    "连心",
]

# ── 结束语变体（含常见谐音误识别）──────────────────────────────
_END_PHRASES = [
    "回答结束", "好的结束", "结束回答", "發鬆",
    "回答完毕", "就这些",  "提交","发送","發送",
]


# ── 公共工具函数（供 main_window 导入使用）───────────────────────

def contains_wake_word(text: str) -> bool:
    """判断文本是否含有唤醒词（含谐音变体）。"""
    t = text.strip().replace(" ", "")
    return any(w in t for w in _WAKE_WORDS)


def contains_end_phrase(text: str) -> bool:
    """判断文本是否含有结束语（含谐音变体）。"""
    t = text.strip().replace(" ", "")
    return any(p in t for p in _END_PHRASES)


def strip_end_phrase(text: str) -> str:
    """去掉文本中的结束语，返回干净的问题内容。"""
    t = text.strip()
    for p in _END_PHRASES:
        t = t.replace(p, "")
    return t.strip()


# ── StandbyWorker ────────────────────────────────────────────────

class StandbyWorker(QThread):
    """
    待机监听线程。
    循环执行：录一段音 → Whisper 识别 → 检测唤醒词。
    检测到唤醒词后发射 wake_detected 信号并退出线程。
    """
    wake_detected = pyqtSignal()

    def __init__(self, listener: VoiceListener, parent=None):
        super().__init__(parent)
        self._listener = listener
        self._running  = False

    def run(self):
        self._running = True
        while self._running:
            try:
                audio = self._listener.record(
                    silence_threshold=0.02,  # 略高于普通录音，减少环境噪音误触
                    silence_seconds=1.0,      # 停顿 1 秒即视为说话结束
                    max_seconds=6.0,          # 每段最长 6 秒，快速进入下一轮
                )
                if not self._running:
                    break
                if len(audio) == 0:
                    continue                  # 本轮无声音，继续下一轮
                text = self._listener.transcribe(audio)
                if not self._running:
                    break
                if contains_wake_word(text):
                    self.wake_detected.emit()
                    break
            except Exception:
                if self._running:
                    time.sleep(0.3)           # 出错后稍等再重试

    def stop(self):
        """外部停止：结束循环并强制中断当前录音。"""
        self._running = False
        self._listener.stop()
