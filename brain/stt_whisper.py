"""
stt_whisper.py - OpenAI Whisper 语音识别封装
提供与 FunASR/Volcano 相同的 transcribe() 接口
"""

import logging

logger = logging.getLogger(__name__)

# 全局模型缓存（避免重复加载）
_model_cache = {}
_current_config = {}


def transcribe(wav_bytes: bytes, config: dict = None) -> str:
    """
    使用 OpenAI Whisper 进行语音识别
    
    Args:
        wav_bytes: WAV 音频数据 (bytes)
        config: 引擎配置字典，包含 model_size, language, device
        
    Returns:
        str: 识别结果文本，失败返回空字符串
    """
    if not config:
        logger.error("Whisper: 缺少配置")
        return ""
    
    global _model_cache, _current_config
    
    model_size = config.get("model_size", "base")
    language = config.get("language", "zh")
    device = config.get("device", "auto")
    
    # 检查是否需要重新加载模型（配置改变时）
    cache_key = f"{model_size}_{device}"
    need_reload = (
        cache_key not in _model_cache or 
        _current_config.get(cache_key) != (model_size, device)
    )
    
    try:
        import whisper
        import numpy as np
        import io, wave
        
        # 加载或复用模型
        if need_reload:
            logger.info(f"🔧 Whisper: 加载 {model_size} 模型到 {device}...")
            model = whisper.load_model(model_size, device=device)
            _model_cache[cache_key] = model
            _current_config[cache_key] = (model_size, device)
        else:
            model = _model_cache[cache_key]
        
        # 将 WAV bytes 转换为 numpy 数组
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, 'rb') as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()
            
            audio_data = wf.readframes(n_frames)
            
            # 转换为 numpy 数组
            if sampwidth == 2:
                audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
            elif sampwidth == 4:
                audio_np = np.frombuffer(audio_data, dtype=np.int32).astype(np.float32) / 2147483648.0
            else:
                raise ValueError(f"不支持的采样宽度: {sampwidth}")
            
            # 如果是立体声，转为单声道
            if n_channels > 1:
                audio_np = audio_np.reshape(-1, n_channels).mean(axis=1)
        
        # 执行识别
        kwargs = {
            "fp16": False  # Windows 兼容性更好
        }
        if language:
            kwargs["language"] = language
        
        result = model.transcribe(audio_np, **kwargs)
        text = result.get("text", "").strip()
        
        return text
        
    except ImportError:
        logger.error(
            "Whisper: 未安装，请运行:\n"
            "  pip install openai-whisper"
        )
        return ""
    except Exception as e:
        logger.error(f"Whisper: 识别失败: {e}")
        return ""


def clear_cache():
    """清除模型缓存（释放内存）"""
    global _model_cache, _current_config
    count = len(_model_cache)
    _model_cache.clear()
    _current_config.clear()
    logger.info(f"🔧 Whisper: 已清除 {count} 个模型缓存")


if __name__ == "__main__":
    from config import get_stt_engine_config
    cfg = get_stt_engine_config()
    whisper_cfg = cfg["engines"]["whisper"]
    
    print("测试 Whisper STT...")
    
    # 生成测试音频
    import numpy as np
    import io, wave
    sample_rate = 16000
    samples = np.zeros(sample_rate, dtype=np.float32)
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes((samples * 32767).astype(np.int16).tobytes())
    
    test_audio = buf.getvalue()
    
    if whisper_cfg.get("enabled"):
        print(f"使用模型: {whisper_cfg.get('model_size', 'base')}")
        result = transcribe(test_audio, whisper_cfg)
        print(f"识别结果: {result or '(无结果)'}")
        
        clear_cache()
    else:
        print("Whisper 未启用")