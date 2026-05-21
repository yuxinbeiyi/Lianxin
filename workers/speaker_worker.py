"""
SpeakerWorker：后台线程，负责 TTS 合成与播放
"""

from PyQt5.QtCore import QThread, pyqtSignal
from voice.speaker import VoiceSpeaker


class SpeakerWorker(QThread):
    speaking_started  = pyqtSignal()   # 开始播放
    speaking_finished = pyqtSignal()   # 播放结束

    def __init__(self, speaker: VoiceSpeaker, text: str, parent=None):
        super().__init__(parent)
        self._speaker = speaker
        self._text    = text

    def run(self):
        self.speaking_started.emit()
        self._speaker.speak(self._text)
        self.speaking_finished.emit()

    def stop(self):
        self._speaker.stop()
