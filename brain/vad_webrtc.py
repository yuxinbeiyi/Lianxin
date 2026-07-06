# E:\Desktop\莲心AI\brain\vad_webrtc.py
# WebRTC VAD 语音活动检测器
# 替代 Silero VAD，零模型文件，零路径依赖，纯 pip 安装
# pip install webrtcvad

import io
import struct
import threading
import logging
from typing import Optional, Callable

logger = logging.getLogger("lianxin.vad_webrtc")


def _safe_call(fn, *args):
    """跨线程安全调用回调。"""
    try:
        fn(*args)
    except Exception:
        pass


class WebRTCVADWorker(threading.Thread):
    """后台线程：持续监听麦克风，用 WebRTC VAD 实时检测语音活动。

    回调:
        on_voice_start()        — 用户开始说话
        on_voice_end(wav_bytes) — 用户说完，返回完整 WAV 字节
        on_volume(float)        — 实时音量 0.0~1.0（供 UI 波形）
    """

    SAMPLE_RATE = 16000
    FRAME_MS = 20
    CHUNK_SIZE = SAMPLE_RATE * FRAME_MS // 1000  # 320 samples

    def __init__(self,
                 input_device_index: Optional[int] = None,
                 on_voice_start: Optional[Callable] = None,
                 on_voice_end: Optional[Callable] = None,
                 on_volume: Optional[Callable] = None,
                 vad_aggressiveness: int = 3):
        super().__init__(daemon=True)
        self.input_device_index = input_device_index
        self._on_voice_start = on_voice_start
        self._on_voice_end = on_voice_end
        self._on_volume = on_volume

        self._running = False
        self._vad = None

        # ── VAD 参数 ─────────────────────────────────
        self.vad_aggressiveness = vad_aggressiveness  # 0~3，越大越严格（3=只认清晰语音）
        self.speech_start_frames = 5    # 连续 5 帧语音 → 开始说话（100ms）
        self.silence_end_frames = 100   # 连续 100 帧静音 → 判定说完（2 秒）
        self.max_speech_frames = 750    # 单次最长 750 帧 → 强制截断（15 秒）
        self.min_volume = 0.04          # 音量阈值：低于此值跳过 VAD（过滤风扇噪音/TTS 回声）
        self.min_speech_frames = 15     # 最少 15 帧有效语音（300ms）— 低于此值的噪音段被丢弃

    # ── 加载 VAD ────────────────────────────────────

    def _load_vad(self) -> bool:
        try:
            import webrtcvad  # type: ignore
            self._vad = webrtcvad.Vad(self.vad_aggressiveness)
            logger.info("✅ WebRTC VAD 就绪")
            return True
        except ImportError:
            logger.error("❌ webrtcvad 未安装，请执行: pip install webrtcvad")
            return False
        except Exception as e:
            logger.error(f"❌ WebRTC VAD 初始化失败: {e}")
            return False

    # ── 主循环 ──────────────────────────────────────

    def run(self):
        if not self._load_vad():
            return

        self._running = True
        import pyaudio  # type: ignore

        p = pyaudio.PyAudio()

        if self.input_device_index is not None:
            try:
                info = p.get_device_info_by_index(self.input_device_index)
                logger.info(f"🎧 使用: [{self.input_device_index}] {info.get('name')}")
            except Exception:
                self.input_device_index = None

        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.SAMPLE_RATE,
            input=True,
            input_device_index=self.input_device_index,
            frames_per_buffer=self.CHUNK_SIZE,
        )
        logger.info("🎙️ WebRTC VAD 麦克风监听已启动")

        try:
            speaking = False
            silence_frames = 0
            speech_frames = 0      # 在 speech_start 阶段统计连续语音帧
            total_speech_frames = 0  # 整个语音段中的有效语音帧数
            frames = []
            speech_onset_volumes = []  # 记录语音开始阶段的音量，用于斜坡检测

            while self._running:
                try:
                    data = stream.read(self.CHUNK_SIZE, exception_on_overflow=False)
                except Exception:
                    continue

                # 音量计算
                max_val = 0
                for i in range(0, len(data), 2):
                    val = abs(struct.unpack_from('<h', data, i)[0])
                    if val > max_val:
                        max_val = val
                vol = max_val / 32768.0

                if self._on_volume:
                    _safe_call(self._on_volume, vol)

                # 音量阈值：低于阈值直接判为非语音（过滤风扇噪音/TTS 回声）
                if vol < self.min_volume:
                    is_speech = False
                else:
                    is_speech = self._vad.is_speech(data, self.SAMPLE_RATE)

                if is_speech:
                    if not speaking:
                        speech_frames += 1
                        frames.append(data)
                        speech_onset_volumes.append(vol)
                        if speech_frames >= self.speech_start_frames:
                            # 斜坡检测：语音开始阶段音量中位值过低？→ 噪音误触发，丢弃
                            onset_median = sorted(speech_onset_volumes)[len(speech_onset_volumes) // 2]
                            if onset_median < self.min_volume * 0.6:
                                # 音量从极低→正常，是噪音/风扇启动，非真人语音
                                frames = []
                                speech_frames = 0
                                speech_onset_volumes = []
                                continue
                            speaking = True
                            total_speech_frames = speech_frames
                            speech_frames = 0
                            silence_frames = 0
                            _safe_call(self._on_voice_start)
                    else:
                        silence_frames = 0
                        total_speech_frames += 1
                        frames.append(data)
                else:
                    if speaking:
                        frames.append(data)
                        silence_frames += 1

                        if (silence_frames >= self.silence_end_frames
                                or len(frames) >= self.max_speech_frames):
                            speaking = False
                            # 最短语音时长检查：有效语音帧太少？→ 丢弃（噪音误触发）
                            if total_speech_frames < self.min_speech_frames:
                                frames = []
                                silence_frames = 0
                                speech_frames = 0
                                total_speech_frames = 0
                                speech_onset_volumes = []
                                continue
                            wav_bytes = self._frames_to_wav(frames)
                            _safe_call(self._on_voice_end, wav_bytes)
                            frames = []
                            silence_frames = 0
                            speech_frames = 0
                            total_speech_frames = 0
                            speech_onset_volumes = []

        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()
            logger.info("🎙️ WebRTC VAD 麦克风已关闭")

    # ── 工具方法 ────────────────────────────────────

    def _frames_to_wav(self, frames: list) -> bytes:
        data = b''.join(frames)
        buf = io.BytesIO()

        # WAV header
        buf.write(b'RIFF')
        buf.write(struct.pack('<I', 36 + len(data)))
        buf.write(b'WAVE')
        buf.write(b'fmt ')
        buf.write(struct.pack('<I', 16))           # chunk size
        buf.write(struct.pack('<H', 1))            # PCM
        buf.write(struct.pack('<H', 1))            # mono
        buf.write(struct.pack('<I', self.SAMPLE_RATE))
        buf.write(struct.pack('<I', self.SAMPLE_RATE * 2))  # byte rate
        buf.write(struct.pack('<H', 2))            # block align
        buf.write(struct.pack('<H', 16))           # bits per sample
        buf.write(b'data')
        buf.write(struct.pack('<I', len(data)))
        buf.write(data)

        return buf.getvalue()

    def stop(self):
        self._running = False