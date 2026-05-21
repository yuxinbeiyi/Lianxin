"""
ListeningWorker：持续录音 + Whisper 识别，结果追加到小纸条
"""

import time
import numpy as np
import sounddevice as sd
from pathlib import Path
from PyQt5.QtCore import QThread, pyqtSignal
from voice.listener import VoiceListener


class ListeningWorker(QThread):
    """持续录音并识别，将识别结果追加到指定文件"""

    def __init__(self, listener: VoiceListener, note_file_path: str, parent=None):
        super().__init__(parent)
        self._listener = listener
        self._note_file = Path(note_file_path)
        self._running = True
        self.SAMPLE_RATE = 16000
        self.CHUNK_SIZE = 1024
        self.silence_threshold = 0.02      # 静音阈值
        self.silence_seconds = 1.0         # 静音多久后结束录音
        self.max_seconds = 6.0             # 最长录音时间

    def run(self):
        while self._running:
            try:
                audio = self._record_until_silence()
                if len(audio) == 0:
                    time.sleep(0.1)
                    continue

                text = self._listener.transcribe(audio)
                if text:
                    # 追加到小纸条（带换行）
                    with open(self._note_file, "a", encoding="utf-8") as f:
                        f.write(text + "\n")
                    print(f"[听写] 识别: {text}")
            except Exception as e:
                print(f"[听写] 错误: {e}")

    def _record_until_silence(self) -> np.ndarray:
        """录音直到检测到静音，返回音频数据"""
        chunks = []
        silent_chunks = 0
        active = False
        silence_limit = int(self.silence_seconds * self.SAMPLE_RATE / self.CHUNK_SIZE)
        max_chunks = int(self.max_seconds * self.SAMPLE_RATE / self.CHUNK_SIZE)

        with sd.InputStream(
            samplerate=self.SAMPLE_RATE,
            channels=1,
            blocksize=self.CHUNK_SIZE,
            dtype="float32",
        ) as stream:
            while len(chunks) < max_chunks and self._running:
                chunk, _ = stream.read(self.CHUNK_SIZE)
                rms = float(np.sqrt(np.mean(chunk ** 2)))

                if rms > self.silence_threshold:
                    active = True
                    silent_chunks = 0
                    chunks.append(chunk.copy())
                elif active:
                    chunks.append(chunk.copy())
                    silent_chunks += 1
                    if silent_chunks >= silence_limit:
                        break

        if not chunks:
            return np.array([], dtype=np.float32)
        return np.concatenate(chunks, axis=0).flatten()

    def stop(self):
        """停止线程"""
        self._running = False
        self._listener.stop()