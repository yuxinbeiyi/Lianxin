
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
import time
import queue
import threading
import logging
from typing import Optional, Callable

from brain.vad_webrtc import WebRTCVADWorker

logger = logging.getLogger("VoiceDuplex")

# ── 状态常量 ──────────────────────────────────────────
STATE_STOPPED    = "STOPPED"
STATE_LISTENING  = "LISTENING"
STATE_PROCESSING = "PROCESSING"


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

        # 后台预热 FunASR 模型（不阻塞聆听）
        try:
            from brain.stt_funasr import warmup
            warmup()
        except Exception:
            pass

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

            # 过滤无效转录：空文本、纯标签、过短（1-2字几乎肯定是噪音）
            t = (transcript or "").strip()
            if not t or len(t) <= 1:
                self._set_state(STATE_LISTENING)
                continue
            # 过滤纯 FunASR 标签残余（防御性检查，stt_funasr 已处理）
            if t.startswith("<|") or t in ("。", "，", "？", "！"):
                self._set_state(STATE_LISTENING)
                continue

            logger.info(f"📝 转录: {transcript}")
            if self._on_transcript:
                _safe_call(self._on_transcript, transcript)
            self._set_state(STATE_LISTENING)

    def _transcribe(self, wav_bytes: bytes) -> str:
        """语音转文字：FunASR 本地主力 → 火山引擎云端备份。"""
        import time as _time

        # 调试录音（保存到用户数据目录，而非 Desktop）
        from utils.paths import get_user_data_dir
        debug_dir = get_user_data_dir() / "voice_debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        debug_path = str(debug_dir / f"lianxin_debug_{int(_time.time())}.wav")
        try:
            with open(debug_path, "wb") as f:
                f.write(wav_bytes)
            # 保留最近 10 个录音文件
            try:
                files = sorted(debug_dir.glob("lianxin_debug_*.wav"),
                              key=lambda p: p.stat().st_mtime, reverse=True)
                for old in files[10:]:
                    old.unlink()
            except Exception:
                pass
        except Exception:
            pass

        # ── 第1优先级：FunASR 本地 GPU（免费，低延迟，中文最优）──
        try:
            from brain.stt_funasr import transcribe as funasr_transcribe
            result = funasr_transcribe(wav_bytes)
            if result and result.strip():
                logger.info(f"🎯 FunASR: {result}")
                return result
        except Exception as e:
            logger.debug(f"FunASR 不可用: {e}")

        # ── 第2优先级：火山引擎云端（付费，网络依赖）─────────
        try:
            from brain.stt_volcano import transcribe as cloud_transcribe
            result = cloud_transcribe(wav_bytes)
            if result and result.strip():
                logger.info(f"☁️ 火山引擎: {result}")
                return result
        except Exception as e:
            logger.debug(f"火山引擎不可用: {e}")

        logger.debug("所有 STT 引擎均未返回结果")
        return ""