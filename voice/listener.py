"""
VoiceListener：麦克风录音 + 静音检测VAD + FunASR语音识别
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
        """预热 FunASR 模型（后台线程调用，不阻塞 UI）。"""
        try:
            from brain.stt_funasr import warmup
            warmup()
        except Exception:
            pass

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
        """将音频数组转为文字。FunASR GPU 主力 → 火山引擎云端备份。"""
        if len(audio) == 0:
            return ""

        # numpy float32 → 16-bit PCM WAV bytes
        import io
        import wave as _wave
        buf = io.BytesIO()
        with _wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.SAMPLE_RATE)
            # clamp to int16 range
            samples = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
            w.writeframes(samples.tobytes())
        wav_bytes = buf.getvalue()

        # ── 第1优先级：FunASR 本地 GPU ──
        try:
            from brain.stt_funasr import transcribe as funasr_transcribe
            result = funasr_transcribe(wav_bytes)
            if result and result.strip():
                return result
        except Exception:
            pass

        # ── 第2优先级：火山引擎云端 ──
        try:
            from brain.stt_volcano import transcribe as cloud_transcribe
            result = cloud_transcribe(wav_bytes)
            if result and result.strip():
                return result
        except Exception:
            pass

        return ""
