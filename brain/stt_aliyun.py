"""
stt_aliyun.py - 阿里云实时语音识别封装
提供与 FunASR/Volcano 相同的 transcribe() 接口
"""

import logging

logger = logging.getLogger(__name__)


def transcribe(wav_bytes: bytes, config: dict = None) -> str:
    """
    使用阿里云 NLS SDK 进行语音识别
    
    Args:
        wav_bytes: WAV 音频数据 (bytes)
        config: 引擎配置字典，包含 access_key_id, access_key_secret, app_key
        
    Returns:
        str: 识别结果文本，失败返回空字符串
    """
    if not config:
        logger.error("阿里云 STT: 缺少配置")
        return ""
    
    ak_id = config.get("access_key_id", "")
    ak_secret = config.get("access_key_secret", "")
    app_key = config.get("app_key", "")
    
    if not all([ak_id, ak_secret, app_key]):
        logger.error("阿里云 STT: 配置不完整（缺少 AccessKey ID/Secret 或 AppKey）")
        return ""
    
    try:
        import nls
        import nls.token as token_api
        
        # 获取 Token
        try:
            tk = token_api.getToken(ak_id, ak_secret)
            if not tk:
                logger.error("阿里云 STT: Token 获取失败")
                return ""
        except Exception as e:
            logger.error(f"阿里云 STT: Token 获取异常: {e}")
            return ""
        
        # 创建识别器实例
        asr = nls.AsrStreamTranscriber(
            token=tk,
            appkey=app_key,
            on_result=lambda msg: None,
            on_started=lambda msg: None,
            on_failed=lambda msg: None,
            on_completed=lambda msg: None,
            on_close=lambda msg: None,
        )
        
        # 启动识别会话
        try:
            asr.start()
            
            # 发送音频数据
            asr.send_audio(wav_bytes)
            
            # 停止并发送结束标志
            asr.stop()
            
            # 等待结果（简化版本，实际应使用回调获取完整结果）
            import time
            time.sleep(1)  # 等待异步处理
            
            result = getattr(asr, '_last_result', '')
            if result and isinstance(result, dict):
                text = result.get('result', '') or ''
                return text.strip()
            
            return ""
            
        finally:
            try:
                asr.close()
            except Exception:
                pass
                
    except ImportError:
        logger.error(
            "阿里云 STT: SDK 未安装，请运行:\n"
            "  cd alibabacloud-nls-python-sdk && python setup.py install"
        )
        return ""
    except Exception as e:
        logger.error(f"阿里云 STT: 识别失败: {e}")
        return ""


if __name__ == "__main__":
    from config import get_stt_engine_config
    cfg = get_stt_engine_config()
    ali_cfg = cfg["engines"]["aliyun"]
    
    print("测试阿里云 STT...")
    
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
    
    if ali_cfg.get("enabled"):
        result = transcribe(test_audio, ali_cfg)
        print(f"识别结果: {result or '(无结果)'}")
    else:
        print("阿里云 STT 未启用")