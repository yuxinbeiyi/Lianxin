"""
stt_funasr.py — FunASR SenseVoice-Small 语音识别封装
作为全双工语音的主力 STT 引擎（本地 GPU，免费无限次）
"""

import os
import logging
import tempfile
from typing import Optional

# ── 必须在 import funasr 之前设置 ──
os.environ.setdefault("TQDM_DISABLE", "1")

logger = logging.getLogger("lianxin.stt_funasr")

# 抑制 ModelScope Hub 每次启动的下载校验日志
for _name in ("modelscope", "modelscope_hub", "modelscope_hub.download"):
    logging.getLogger(_name).setLevel(logging.WARNING)

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
            disable_update=True,        # 跳过每次启动的版本检查
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
            # 去掉所有 SenseVoice 标签: <|HAPPY|>, <|NEUTRAL|>, <|Speech|>, <|withitn|> 等
            import re as _re
            text = _re.sub(r'<\|[^|>]+\|>', '', text).strip()
            # 过滤：仅剩标点/单字=静音/噪音
            if not text or len(text) <= 1:
                return ""
            if _re.fullmatch(r'[\s。，、；：？！…\.\,\;\:\?\!]+', text):
                return ""
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


def warmup():
    """预热模型：在后台线程加载，不阻塞启动。"""
    import threading
    def _load():
        logger.info("🔥 后台预热 FunASR 模型…")
        m = _load_model()
        if m:
            logger.info("🔥 FunASR 预热完成")
    t = threading.Thread(target=_load, daemon=True)
    t.start()
