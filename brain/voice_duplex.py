
"""
全双工语音模块 — VAD + STT 前端
将语音转为文字后交给主窗口 AgentWorker 统一处理（LLM + TTS + 气泡）

核心理念:
  全双工: 一直监听麦克风，用户随时开口 → 思考中立刻打断

组件:
  WebRTCVADWorker    — 后台线程，持续监听麦克风，WebRTC VAD 实时检测语音/静音
  VoiceDuplexManager — VAD → STT → 交给主窗口（不做 LLM，不做 TTS）

状态流转:
  STOPPED ──start()──→ LISTENING ──VAD检测声音──→ (思考中打断)
      ↑                    ↑                          │
      │                    │              用户说完 (VAD静音 2s)
      │                    │                          ↓
      │                    │                   PROCESSING
      │                    │                   转录语音 → 交主窗口
      │                    │                          │
      │                    └────────── 主窗口处理 ────→ 气泡 + LLM + TTS
      │                                                │
      └──────────── stop() ────────────────────────────┘
"""

import os
import sys
import time
import queue
import threading
import logging
import tempfile
from typing import Optional, Callable

from brain.vad_webrtc import WebRTCVADWorker

logger = logging.getLogger("VoiceDuplex")

# ── 状态常量 ──────────────────────────────────────────
STATE_STOPPED    = "STOPPED"
STATE_LISTENING  = "LISTENING"
STATE_PROCESSING = "PROCESSING"

# ── Whisper 经典幻觉过滤 ──────────────────────────────
# 当 VAD 触发但实际没有有效语音时，Whisper 会脑补这些常见短语
_WHISPER_HALLUCINATIONS = {
    "谢谢", "感谢", "谢谢观看", "謝謝觀看", "谢谢收看", "感謝觀看",
    "谢谢大家", "谢谢观赏", "感謝收看", "感谢观看", "感谢收看",
    "Thank you", "Thanks", "Thank you for watching",
    "订阅", "点赞", "关注", "转发",
    "一首", "一首歌", "music", "Music",
}

# 状态中文标签
STATE_LABELS = {
    STATE_STOPPED:    "待机",
    STATE_LISTENING:  "聆听中",
    STATE_PROCESSING: "思考中",
}

def _safe_call(fn, *args):
    try:
        fn(*args)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════
# VoiceDuplexManager
# ═══════════════════════════════════════════════════════

class VoiceDuplexManager:
    """全双工语音管理器 — 只做 VAD + STT，转录后交给主窗口。

    用法:
        manager = VoiceDuplexManager(
            on_transcript=lambda t: print(f"你说: {t}"),
            on_state_change=lambda s: print(STATE_LABELS[s]),
        )
        manager.start()
        ...
        manager.stop()
    """

    def __init__(self,
                 on_state_change: Optional[Callable] = None,
                 on_transcript: Optional[Callable] = None,
                 on_voice_start_ui: Optional[Callable] = None,
                 input_device_index: Optional[int] = None):
        self._on_state_change = on_state_change
        self._on_transcript   = on_transcript
        self._input_device_index = input_device_index
        self._on_voice_start_ui = on_voice_start_ui
        self._state = STATE_STOPPED
        self._vad_worker: Optional[WebRTCVADWorker] = None

        self._audio_queue   = queue.Queue()
        self._lock = threading.Lock()
        self._vad_paused = False
        self._vad_cooldown_until = 0.0

    # ── 状态 ──────────────────────────────────────────

    @property
    def state(self) -> str:
        return self._state

    def _set_state(self, new: str):
        if new != self._state:
            old = self._state
            self._state = new
            logger.info(f"状态: {STATE_LABELS.get(old, old)} → {STATE_LABELS.get(new, new)}")
            if self._on_state_change:
                _safe_call(self._on_state_change, new)

    # ── 中断 ──────────────────────────────────────────

    def interrupt(self):
        """打断当前操作。"""
        if self._state == STATE_STOPPED:
            return
        logger.info("🛑 中断！")
        self._set_state(STATE_LISTENING)

    # ── TTS 协同（由主窗口在 TTS 播放前后调用）────────────
    def pause_vad(self):
        """暂停 VAD 处理：TTS 播放期间丢弃所有麦克风音频，防止回声循环。"""
        with self._lock:
            self._vad_paused = True
            # 清除队列中可能已有的 TTS 回声
            while not self._audio_queue.empty():
                try:
                    self._audio_queue.get_nowait()
                except queue.Empty:
                    break

    def resume_vad(self, cooldown: float = 2.0):
        """恢复 VAD 处理：TTS 结束后延迟 cooldown 秒才接受音频（防止延迟的 TTS 回声帧）。"""
        with self._lock:
            self._vad_paused = False
            self._vad_cooldown_until = time.time() + cooldown

    # ── VAD 回调 ──────────────────────────────────────
    def _on_voice_start(self):
        if self._on_voice_start_ui:
            _safe_call(self._on_voice_start_ui)
        # 思考中打断，说话中（TTS 播放）不打断防回声
        if self._state == STATE_PROCESSING:
            self.interrupt()

    def _on_voice_end(self, wav_bytes: bytes):
        with self._lock:
            if self._vad_paused:
                return  # TTS 播放中 → 丢弃麦克风拾取的 TTS 回声
            if time.time() < self._vad_cooldown_until:
                return  # TTS 刚结束 → 冷却期内丢弃延迟的 TTS 回声帧
        self._audio_queue.put(wav_bytes)

    # ── 启动/停止 ─────────────────────────────────────

    def start(self):
        if self._vad_worker is not None:
            return

        self._vad_worker = WebRTCVADWorker(
            input_device_index=self._input_device_index,
            on_voice_start=self._on_voice_start,
            on_voice_end=self._on_voice_end,
        )
        self._vad_worker.start()
        self._set_state(STATE_LISTENING)

        # STT 处理线程（只转录，不做 LLM/TTS）
        threading.Thread(target=self._process_loop, daemon=True).start()
        logger.info("✅ 全双工语音已启动")

    def stop(self):
        self._set_state(STATE_STOPPED)

        if self._vad_worker:
            self._vad_worker.stop()
            self._vad_worker = None

        logger.info("🛑 全双工语音已停止")

    # ── 处理循环（STT → 交给主窗口）────────────────────

    def _process_loop(self):
        while self._state != STATE_STOPPED:
            try:
                wav_bytes = self._audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if self._state == STATE_STOPPED:
                break

            self._set_state(STATE_PROCESSING)
            transcript = self._transcribe(wav_bytes)

            if not transcript or not transcript.strip():
                self._set_state(STATE_LISTENING)
                continue

            logger.info(f"📝 转录: {transcript}")
            if self._on_transcript:
                _safe_call(self._on_transcript, transcript)
            self._set_state(STATE_LISTENING)

    def _is_hallucination(self, text: str) -> bool:
        """检查转录文本是否为 Whisper 幻觉（TTS 回声/静音被误识别）。"""
        t = text.strip()
        if not t:
            return True
        if len(t) <= 1:  # 单字几乎肯定是幻觉
            return True
        if t in _WHISPER_HALLUCINATIONS:
            return True
        return False

    def _transcribe(self, wav_bytes: bytes) -> str:
        import time as _time
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        try:
            tmp.write(wav_bytes)
            tmp.close()
            # 调试录音
            debug_path = os.path.join(os.path.expanduser("~"), "Desktop",
                                      f"lianxin_debug_{int(_time.time())}.wav")
            with open(debug_path, "wb") as f:
                f.write(wav_bytes)
            logger.info(f"💾 调试录音已保存: {debug_path}")

            # 优先火山云端
            from brain.stt_volcano import transcribe as cloud_transcribe
            result = cloud_transcribe(wav_bytes)
            if result:
                return result

            # 回退本地 Faster-Whisper
            from brain.audio_utils import transcribe as local_transcribe
            result = local_transcribe(tmp.name, language="zh").strip()
            logger.info(f"📝 本地转录: {result}")

            # 过滤 Whisper 幻觉（"謝謝觀看"、"谢谢"等常见脑补）
            if self._is_hallucination(result):
                logger.info(f"🗑️ 过滤幻觉: {result}")
                return ""

            return result
        except Exception as e:
            logger.warning(f"转录失败: {e}")
            return ""
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass