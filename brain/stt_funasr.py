"""
stt_funasr.py — FunASR SenseVoice-Small 语音识别封装
作为全双工语音的主力 STT 引擎（本地 GPU，免费无限次）
"""

import logging
import tempfile
import os
from typing import Optional

logger = logging.getLogger("lianxin.stt_funasr")

# 全局单例，首次调用时懒加载
_model = None
_load_attempted = False


def _load_model():
    """懒加载 SenseVoice-Small 模型（GPU 推理）。"""
    global _model, _load_attempted
    if _load_attempted:
        return _model
    _load_attempted = True

    try:
        from funasr import AutoModel
        logger.info("🔊 正在加载 FunASR SenseVoice-Small 模型…")
        _model = AutoModel(
            model="iic/SenseVoiceSmall",
            device="cuda:0",
            disable_pbar=True,
        )
        logger.info("✅ FunASR 模型加载完成")
    except ImportError:
        logger.warning("⚠️ FunASR 未安装，跳过 (pip install funasr)")
    except Exception as e:
        logger.warning(f"⚠️ FunASR 模型加载失败: {e}")

    return _model


def transcribe(wav_bytes: bytes, language: str = "zh") -> str:
    """使用 FunASR SenseVoice-Small 将 WAV 字节转录为文字。

    Args:
        wav_bytes: 16kHz 16bit mono WAV 音频字节
        language: 语言代码，默认 "zh"

    Returns:
        识别文本，失败返回空字符串
    """
    model = _load_model()
    if model is None:
        return ""

    # 写入临时文件（FunASR 需要文件路径）
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    try:
        tmp.write(wav_bytes)
        tmp.close()

        result = model.generate(
            input=tmp.name,
            language=language,
            use_itn=True,            # 逆文本正则化（数字/日期等）
            ban_emo_unk=True,        # 过滤未知情绪标签
        )
        if result and len(result) > 0:
            text = result[0].get("text", "").strip()
            # SenseVoice 有时会在文本前加情绪标签如 "<|HAPPY|>"，去掉
            if text.startswith("<|") and "|>" in text:
                tag_end = text.index("|>") + 2
                text = text[tag_end:].strip()
            return text

    except Exception as e:
        logger.warning(f"FunASR 转录失败: {e}")
        return ""
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

    return ""


def is_available() -> bool:
    """检测 FunASR 是否可用（模型已加载或可加载）。"""
    return _load_model() is not None
