"""
stt_aliyun.py - 阿里云实时语音识别封装
提供与 FunASR/Volcano 相同的 transcribe() 接口
"""

import io
import json
import logging
import time
import wave

logger = logging.getLogger(__name__)


def _extract_result(message: str) -> str:
    """从 NLS SDK 回调 JSON 中取出识别文本。"""
    try:
        data = json.loads(message or "{}")
    except (TypeError, json.JSONDecodeError):
        return ""
    payload = data.get("payload") or {}
    return str(payload.get("result") or payload.get("text") or "").strip()


def _wav_to_pcm(wav_bytes: bytes) -> bytes:
    """将 VAD 生成的 16kHz/16bit/单声道 WAV 转为 NLS 需要的原始 PCM。"""
    if not wav_bytes:
        return b""
    # 为兼容直接传入 PCM 的调用方，只解析 RIFF/WAVE 数据。
    if not wav_bytes.startswith(b"RIFF"):
        return wav_bytes

    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        if wav.getnchannels() != 1:
            raise ValueError("阿里云 STT 仅支持单声道音频")
        if wav.getsampwidth() != 2:
            raise ValueError("阿里云 STT 需要 16bit PCM 音频")
        if wav.getframerate() != 16000:
            raise ValueError("阿里云 STT 需要 16000Hz 音频")
        return wav.readframes(wav.getnframes())


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
        
        transcriber_cls = getattr(nls, "NlsSpeechTranscriber", None)
        if transcriber_cls is None:
            logger.error(
                "阿里云 STT: SDK 版本不兼容，缺少 NlsSpeechTranscriber"
            )
            return ""

        pcm_data = _wav_to_pcm(wav_bytes)
        if not pcm_data:
            return ""

        sentence_results = []
        last_partial = [""]
        callback_errors = []

        def on_sentence_end(message, *_args):
            text = _extract_result(message)
            if text:
                sentence_results.append(text)

        def on_result_changed(message, *_args):
            text = _extract_result(message)
            if text:
                last_partial[0] = text

        def on_completed(message, *_args):
            # 某些服务版本会在 completed 中附带最终文本。
            text = _extract_result(message)
            if text and text not in sentence_results:
                sentence_results.append(text)

        def on_error(message, *_args):
            callback_errors.append(str(message))

        # 创建官方 SDK 实时识别器实例
        asr = transcriber_cls(
            token=tk,
            appkey=app_key,
            on_start=lambda _msg, *_args: None,
            on_sentence_end=on_sentence_end,
            on_result_changed=on_result_changed,
            on_error=on_error,
            on_completed=on_completed,
            on_close=lambda *_args: None,
        )

        stopped = False
        # 启动识别会话
        try:
            asr.start(
                aformat="pcm",
                sample_rate=16000,
                ch=1,
                enable_intermediate_result=True,
                enable_punctuation_prediction=True,
                enable_inverse_text_normalization=True,
                timeout=10,
            )

            # 官方 SDK 建议每次发送 20ms PCM：16kHz * 2 bytes * 20ms = 640 bytes。
            for offset in range(0, len(pcm_data), 640):
                chunk = pcm_data[offset:offset + 640]
                if chunk:
                    asr.send_audio(chunk)
                    if offset + 640 < len(pcm_data):
                        time.sleep(0.01)

            # stop() 会等待 TranscriptionCompleted，无需再固定 sleep。
            asr.stop(timeout=15)
            stopped = True
        finally:
            if not stopped:
                try:
                    asr.shutdown()
                except Exception:
                    pass

        if callback_errors:
            logger.warning("阿里云 STT 回调报错: %s", callback_errors[-1][:300])

        if sentence_results:
            return "".join(sentence_results).strip()
        return last_partial[0].strip()
                
    except ImportError as e:
        logger.error(
            "阿里云 STT: SDK 导入失败 (%s)，请运行:\n"
            "  cd alibabacloud-nls-python-sdk && python setup.py install",
            e,
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
