"""
VoiceListener：麦克风录音 + 静音检测VAD + Whisper语音识别
"""

import numpy as np
import sounddevice as sd


class VoiceListener:
    SAMPLE_RATE = 16000
    CHUNK_SIZE  = 1024

    def __init__(self, model_size: str = "base", language: str = "zh"):
        self._model_size = model_size
        self._language   = language
        self._model      = None       # 懒加载，首次使用时载入
        self._stop_flag  = False

    # ── 模型加载 ─────────────────────────────────────────────

    def load_model(self):
        """加载 Whisper 模型（首次约需 5-15 秒，之后缓存）。"""
        if self._model is not None:
            return
        import os
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        from faster_whisper import WhisperModel
        self._model = WhisperModel(
            self._model_size,
            device="cpu",
            compute_type="int8",
        )

    # ── 录音 ─────────────────────────────────────────────────

    def record(self,
               silence_threshold: float = 0.015,
               silence_seconds:   float = 1.5,
               max_seconds:       float = 30.0) -> np.ndarray:
        """
        从麦克风录音，检测到持续静音后自动停止。
        返回 float32 numpy 数组（16kHz 单声道）。
        """
        self._stop_flag = False
        chunks: list[np.ndarray] = []
        silent_chunks = 0
        active = False

        silence_limit = int(silence_seconds * self.SAMPLE_RATE / self.CHUNK_SIZE)
        max_chunks    = int(max_seconds     * self.SAMPLE_RATE / self.CHUNK_SIZE)

        with sd.InputStream(
            samplerate=self.SAMPLE_RATE,
            channels=1,
            blocksize=self.CHUNK_SIZE,
            dtype="float32",
        ) as stream:
            while len(chunks) < max_chunks and not self._stop_flag:
                chunk, _ = stream.read(self.CHUNK_SIZE)
                rms = float(np.sqrt(np.mean(chunk ** 2)))

                if rms > silence_threshold:
                    active = True
                    silent_chunks = 0
                    chunks.append(chunk.copy())
                elif active:
                    chunks.append(chunk.copy())
                    silent_chunks += 1
                    if silent_chunks >= silence_limit:
                        break   # 足够长的静音 → 结束录音

        if not chunks:
            return np.array([], dtype=np.float32)
        return np.concatenate(chunks, axis=0).flatten()

    def stop(self):
        """外部强制停止录音。"""
        self._stop_flag = True

    # ── 转录 ─────────────────────────────────────────────────

    def transcribe(self, audio: np.ndarray) -> str:
        """将音频数组转为文字（调用前确保已 load_model）。"""
        if len(audio) == 0:
            return ""
        if self._model is None:
            self.load_model()
        segments, _ = self._model.transcribe(
            audio,
            language=self._language,
            beam_size=5,
        )
        return "".join(s.text for s in segments).strip()
