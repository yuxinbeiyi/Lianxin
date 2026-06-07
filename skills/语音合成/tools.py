"""
语音合成技能工具 — GPT-SoVITS + Edge-TTS 回退。

提供 3 个 AI 可调用工具：
  - speak_voice: 合成语音并发送/播放
  - set_voice_mood: 设置默认情绪音色
  - list_voice_styles: 列出可用风格

QQ 端自动语音回复由 brain/audio_utils.py 透明接入，
桌面端播放由 voice/speaker.py 透明接入，
此模块只负责 AI 主动调用的显式语音工具。
"""

import importlib
import os
import tempfile
import threading
import time
import logging
import re

logger = logging.getLogger("voice_tools")

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "speak_voice",
            "description": (
                "将文字合成为语音并发送/播放。当用户要求用语音说话、念某段文字、"
                "发送语音消息时调用此工具。支持情绪音色选择："
                "casual（日常温柔）、tsundere（傲娇强势）、romantic（深情）、"
                "long（长句稳定）、angry（生气愤怒）、auto（根据文本自动匹配）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "要合成为语音的文字内容。重要：此内容必须是你最终回复的完整文字，确保语音朗读与消息框显示完全一致"
                    },
                    "mood": {
                        "type": "string",
                        "enum": ["auto", "casual", "tsundere", "romantic", "long", "angry"],
                        "description": "语音情绪/音色风格。auto=自动匹配。默认 auto。"
                    }
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_voice_mood",
            "description": (
                "设置当前会话的默认语音情绪/音色风格。设置后后续的语音合成都会使用此风格，"
                "除非当前会话内再次修改。可选：auto（自动匹配）、casual（日常温柔）、"
                "tsundere（傲娇强势）、romantic（深情）、long（长句稳定）、angry（生气愤怒）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mood": {
                        "type": "string",
                        "enum": ["auto", "casual", "tsundere", "romantic", "long", "angry"],
                        "description": "要设置的默认语音情绪风格"
                    }
                },
                "required": ["mood"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_voice_styles",
            "description": "列出所有可用的语音合成音色/情绪风格及其描述。当用户问'有哪些语音风格''可以用什么语气说话'时调用。",
            "parameters": {"type": "object", "properties": {}}
        }
    },
]


# ── 每会话状态（模块级变量，重启后重置为 auto） ─────────
_session_mood = "auto"
_last_spoken_text = ""  # 缓存最后被朗读的文字，供 main_window 同步到消息框
_stop_event = threading.Event()  # 停止信号，用户发新消息时触发


# ── 句子分割 + 流式合成 ──────────────────────────────────


def _split_into_sentences(text: str):
    """将文本按句末标点或换行分割为句子列表。"""
    if not text:
        return []
    parts = re.split(r'(?<=[。！？.!?])\s*|\n+', text)
    return [p.strip() for p in parts if p.strip()]


def _play_blocking(wav_path: str):
    """同步播放 WAV 文件，播放完成才返回。支持停止信号中断。"""
    try:
        import pygame
        if not pygame.mixer.get_init():
            pygame.init()
            pygame.mixer.init()
        sound = pygame.mixer.Sound(wav_path)
        channel = sound.play()
        if channel is not None:
            while channel.get_busy():
                if _stop_event.is_set():
                    channel.stop()
                    break
                time.sleep(0.05)
    except Exception as e:
        logger.warning(f"播放失败: {e}")


def _synthesize_stream(sentences, mood):
    """后台线程：逐句合成 + 流水线播放。支持停止信号中断。"""
    import queue as _queue
    from brain.tts_engine import TtsEngine

    synth_queue = _queue.Queue(maxsize=1)
    engine = TtsEngine()
    temp_files = []

    def producer():
        for i, sentence in enumerate(sentences):
            if _stop_event.is_set():
                break
            if not sentence.strip():
                continue
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f"_s{i}.wav")
            tmp_path = tmp.name
            tmp.close()
            temp_files.append(tmp_path)

            try:
                ok = engine.synthesize(sentence, tmp_path, mood=mood)
                if ok:
                    # 带超时的 put，避免停止信号下发后 producer 阻塞
                    while not _stop_event.is_set():
                        try:
                            synth_queue.put(("audio", tmp_path), timeout=0.3)
                            break
                        except _queue.Full:
                            continue
                else:
                    while not _stop_event.is_set():
                        try:
                            synth_queue.put(("error", None), timeout=0.3)
                            break
                        except _queue.Full:
                            continue
            except Exception as e:
                logger.warning(f"句子{i+1}合成失败: {e}")
                while not _stop_event.is_set():
                    try:
                        synth_queue.put(("error", None), timeout=0.3)
                        break
                    except _queue.Full:
                        continue
        synth_queue.put(("done", None))

    prod = threading.Thread(target=producer, daemon=True)
    prod.start()

    # Consumer：依次播放，每句音频就绪后立即播放
    while True:
        try:
            msg_type, data = synth_queue.get(timeout=0.5)
        except _queue.Empty:
            if _stop_event.is_set():
                break
            continue
        if msg_type == "done":
            break
        elif msg_type == "audio":
            if _stop_event.is_set():
                break
            _play_blocking(data)

    prod.join()

    # 清理临时文件
    for f in temp_files:
        try:
            os.unlink(f)
        except Exception:
            pass


# ── 工具实现 ──────────────────────────────────────────────

def _speak_voice(text: str, mood: str = "auto") -> str:
    """合成语音并发送/播放。多句文本自动启用流式合成。"""
    global _session_mood, _last_spoken_text

    if not text or not text.strip():
        return "语音文本为空"

    # 清除之前可能的停止信号，开始新回合的语音合成
    _stop_event.clear()
    _last_spoken_text = text  # 缓存被朗读的文字，供主界面同步消息框内容

    # 选择最终情绪
    effective_mood = mood if mood != "auto" else _session_mood
    if effective_mood == "auto":
        effective_mood = None  # 让引擎自动匹配

    # 分割句子，判断是否启用流式
    sentences = _split_into_sentences(text)

    if len(sentences) <= 1:
        # ── 单句：快速路径（现有逻辑） ─────────────────
        wav_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        wav_path = wav_temp.name
        wav_temp.close()

        try:
            from brain.tts_engine import TtsEngine
            engine = TtsEngine()

            success = engine.synthesize(text, wav_path, mood=effective_mood)
            if not success:
                return "语音合成失败，请稍后再试。"

            engine_name = engine.engine_name
            return _play_desktop(wav_path, engine_name)
        except Exception as e:
            return f"语音合成失败: {e}"
        finally:
            try:
                os.unlink(wav_path)
            except Exception:
                pass
    else:
        # ── 多句：流式合成，后台流水线播放 ─────────────
        threading.Thread(
            target=_synthesize_stream,
            args=(sentences, effective_mood),
            daemon=True,
        ).start()
        return f"语音合成中（共{len(sentences)}句），将逐句播放，请稍候..."


def _set_voice_mood(mood: str) -> str:
    """设置会话默认情绪。"""
    global _session_mood
    valid = ["auto", "casual", "tsundere", "romantic", "long", "angry"]
    if mood not in valid:
        return f"无效的语音风格：{mood}。可选：{'、'.join(valid)}"
    _session_mood = mood
    label = {
        "auto": "自动匹配",
        "casual": "日常温柔",
        "tsundere": "傲娇",
        "romantic": "深情",
        "long": "长句稳定",
        "angry": "生气",
    }.get(mood, mood)
    return f"语音风格已设为：{label}（{mood}）"


def _list_voice_styles() -> str:
    """列出可用语音风格。"""
    try:
        from brain.tts_engine import TtsEngine
        styles = TtsEngine.list_ref_styles()
    except Exception:
        styles = []

    if not styles:
        return "当前没有可用的语音风格（使用默认 Edge-TTS 标准音色）。如需定制声线，请配置 GPT-SoVITS 并添加参考音频。"

    lines = ["可用的语音合成风格："]
    for s in styles:
        lang_status = ""
        if s.get("file_count", 0) > 0:
            lang_status = f"（{s['file_count']}个参考音频）"
        lines.append(f"- {s['label']}（{s['mood']}）{lang_status}")
        if s.get("description"):
            lines.append(f"  └ {s['description']}")

    # 附加引擎状态
    try:
        from brain.tts_engine import TtsEngine
        engine = TtsEngine()
        lines.append("")
        if engine.gpt_sovits_available:
            lines.append(f"当前引擎：GPT-SoVITS（声音克隆已启用）")
        else:
            lines.append(f"当前引擎：Edge-TTS（标准云端发音）")
            lines.append("提示：配置 GPT-SoVITS 后可启用声音克隆和情绪表达")
    except Exception:
        pass

    return "\n".join(lines)


# ── 发送/播放辅助 ─────────────────────────────────────────

def _send_via_qq(qq_worker, wav_path: str, text: str, engine_name: str) -> str:
    """通过 QQ 桥接发送语音消息。"""
    try:
        from brain.audio_utils import wav_to_silk
        import base64

        silk_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".silk")
        silk_path = silk_temp.name
        silk_temp.close()

        try:
            wav_to_silk(wav_path, silk_path)

            with open(silk_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("ascii")

            # 通过 OneBot 发送语音消息
            owner_qq = getattr(qq_worker, "_owner_qq", 0)
            if not owner_qq:
                return f"语音已生成（{engine_name}），但未检测到 QQ 主人账号"

            qq_worker._send_onebot_action("send_msg", {
                "message_type": "private",
                "user_id": owner_qq,
                "message": [
                    {"type": "record", "data": {"file": f"base64://{b64_data}"}}
                ],
            })
            return f"语音已发送到 QQ（{engine_name}引擎）"
        finally:
            try:
                os.unlink(silk_path)
            except Exception:
                pass
    except ImportError:
        return f"语音已生成（{engine_name}），但 pysilk 不可用，无法转换语音格式"
    except Exception as e:
        return f"语音已生成（{engine_name}），但 QQ 发送失败: {e}"


def _play_desktop(wav_path: str, engine_name: str) -> str:
    """通过 pygame 在桌面端播放语音。"""
    try:
        import pygame
        if not pygame.mixer.get_init():
            pygame.init()
            pygame.mixer.init()

        sound = pygame.mixer.Sound(wav_path)
        channel = pygame.mixer.find_channel()
        if channel:
            channel.play(sound)
        else:
            sound.play()

        # 等待播放结束（非阻塞）
        threading.Thread(target=_wait_playback, daemon=True).start()
        return f"语音已播放（{engine_name}引擎）"
    except Exception as e:
        return f"语音已生成（{engine_name}），但播放失败: {e}"


def _wait_playback():
    """等待 pygame 播放结束（后台线程）。"""
    import pygame
    timeout = 60  # 最多等 60 秒
    interval = 0.1
    waited = 0
    while waited < timeout:
        if not pygame.mixer.get_busy():
            break
        time.sleep(interval)
        waited += interval


def stop_voice_playback():
    """停止当前正在播放的语音。供 main_window 在用户发新消息时调用。"""
    _stop_event.set()
    try:
        import pygame
        if pygame.mixer.get_init():
            pygame.mixer.stop()
    except Exception:
        pass


TOOL_EXECUTORS = {
    "speak_voice": lambda inp: _speak_voice(
        text=inp["text"],
        mood=inp.get("mood", "auto"),
    ),
    "set_voice_mood": lambda inp: _set_voice_mood(inp["mood"]),
    "list_voice_styles": lambda inp: _list_voice_styles(),
}
