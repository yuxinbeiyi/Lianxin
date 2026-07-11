"""
stt_funasr.py — FunASR SenseVoice-Small 语音识别封装
作为全双工语音的主力 STT 引擎（本地 GPU，免费无限次）
"""

import os
import sys
import logging
import tempfile
from typing import Optional

# ── 必须在 import funasr 之前设置 ──
os.environ.setdefault("TQDM_DISABLE", "1")

logger = logging.getLogger("lianxin.stt_funasr")

# 抑制 ModelScope Hub 每次启动的下载校验日志
for _name in ("modelscope", "modelscope_hub", "modelscope_hub.download",
              "funasr"):
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

    # 抑制 funasr import 时的 print() 和 modelscope 的 warnings
    import warnings as _w
    _w.simplefilter("ignore")
    _saved_stdout = sys.stdout
    sys.stdout = open(os.devnull, "w")

    try:
        from funasr import AutoModel
    finally:
        sys.stdout.close()
        sys.stdout = _saved_stdout

    try:
        from config import resolve_device, get_device_preference
        dev = resolve_device("funasr")

        # 抑制 transformers 加载远程代码时的 No module named 'model' 警告（无害）
        import warnings
        warnings.filterwarnings("ignore", message=".*Loading remote code failed.*")

        logger.info(f"🔊 正在加载 FunASR SenseVoice-Small 模型 ({dev})…")
        _model = AutoModel(
            model="iic/SenseVoiceSmall",
            device=dev,
            disable_pbar=True,
            disable_update=True,
            trust_remote_code=True,
        )
        logger.info(f"✅ FunASR 模型加载完成 ({dev})")
    except ImportError:
        logger.warning("⚠️ FunASR 未安装，跳过 (pip install funasr)")
    except Exception as e:
        # auto 模式下加载失败，尝试 CPU 回退
        if get_device_preference("funasr") == "auto":
            try:
                logger.warning(f"⚠️ {dev} 加载失败，回退 CPU…")
                _model = AutoModel(
                    model="iic/SenseVoiceSmall",
                    device="cpu",
                    disable_pbar=True,
                    disable_update=True,
                    trust_remote_code=True,
                )
                logger.info("✅ FunASR 模型加载完成 (CPU 回退)")
            except Exception as e2:
                logger.warning(f"⚠️ FunASR CPU 回退也失败: {e2}")
        else:
            logger.warning(f"⚠️ FunASR 模型加载失败 ({dev}): {e}")

    return _model


def transcribe(wav_bytes: bytes, language: str = "zh") -> str:
    """使用 FunASR SenseVoice-Small 将 WAV 字节转录为文字。

    Args:
        wav_bytes: 16kHz 16bit mono WAV 音频字节
        language: 语言代码，默认 "zh"

    Returns:
        识别文本，失败返回空字符串
    """
    import time as _time
    _t0 = _time.time()
    model = _load_model()
    _t1 = _time.time()
    if model is None:
        return ""

    # 写入临时文件（FunASR 需要文件路径）
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    try:
        tmp.write(wav_bytes)
        tmp.close()
        _t2 = _time.time()

        result = model.generate(
            input=tmp.name,
            language=language,
            use_itn=True,            # 逆文本正则化（数字/日期等）
            ban_emo_unk=True,        # 过滤未知情绪标签
        )
        _t3 = _time.time()
        logger.info(f"⏱ FunASR 耗时: 加载={_t1-_t0:.1f}s, 写入={_t2-_t1:.2f}s, 推理={_t3-_t2:.1f}s, 总计={_t3-_t0:.1f}s")
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
    """预热模型：在后台线程加载，不阻塞启动。

    外层 try/except 确保即使 GPU/CUDA 硬崩溃也能安全降级，
    不会拖垮整个进程。
    """
    import threading
    def _load():
        try:
            logger.info("🔥 后台预热 FunASR 模型…")
            m = _load_model()
            if m:
                logger.info("🔥 FunASR 预热完成")
            else:
                logger.warning("⚠️ FunASR 预热返回 None，语音识别可能不可用")
        except Exception as e:
            logger.warning(f"⚠️ FunASR 预热失败: {e}")
    t = threading.Thread(target=_load, daemon=True)
    t.start()