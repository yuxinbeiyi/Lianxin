# E:\Desktop\莲心AI\brain\stt_volcano.py
# 火山引擎语音识别 (v3) — WebSocket 二进制协议 + X-Api 鉴权
# 免费额度: 20,000 次（半年），超出后 ¥1~4.5/小时
# 文档: https://www.volcengine.com/docs/6561/1354869
#
# v3 API 使用 X-Api-App-Key + X-Api-Access-Key 鉴权（无需 HMAC 签名）
# 如果你的配置有 SECRET_KEY，会同时尝试 HMAC256 Signature 鉴权兼容 v2

import os
import json
import struct
import gzip
import base64
import hmac
import hashlib
import uuid
import asyncio
import logging
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger("lianxin.stt_volcano")

# ── v3 API 端点（一句话识别）──────────────────────────
# bigmodel_nostream: 流式输入，准确率优先（适合一句话识别）
_WS_URL = "wss://openspeech.bytedance.com/api/v2/asr"

SUCCESS_CODE = 1000

# ── 协议常量 ──────────────────────────────────────────

PROTOCOL_VERSION = 0b0001
DEFAULT_HEADER_SIZE = 0b0001

# Message Type
CLIENT_FULL_REQUEST = 0b0001
CLIENT_AUDIO_ONLY_REQUEST = 0b0010
SERVER_FULL_RESPONSE = 0b1001
SERVER_ACK = 0b1011
SERVER_ERROR_RESPONSE = 0b1111

# Message Type Specific Flags
NO_SEQUENCE = 0b0000
NEG_SEQUENCE = 0b0010

# Serialization
NO_SERIALIZATION = 0b0000
JSON = 0b0001

# Compression
NO_COMPRESSION = 0b0000
GZIP = 0b0001


def _get_config() -> dict:
    from config import (
        STT_VOLCANO_APPID,
        STT_VOLCANO_ACCESS_KEY,
        STT_VOLCANO_CLUSTER,
        STT_VOLCANO_SECRET_KEY,
    )
    return {
        "appid": os.environ.get("STT_VOLCANO_APPID", STT_VOLCANO_APPID),
        "access_key": os.environ.get("STT_VOLCANO_ACCESS_KEY", STT_VOLCANO_ACCESS_KEY),
        "cluster": os.environ.get("STT_VOLCANO_CLUSTER", STT_VOLCANO_CLUSTER) or "volcengine_input_common",
        "secret_key": os.environ.get("STT_VOLCANO_SECRET_KEY", STT_VOLCANO_SECRET_KEY),
    }


# ── 二进制协议帧 ─────────────────────────────────────

def _generate_header(
    message_type: int = CLIENT_FULL_REQUEST,
    message_type_specific_flags: int = NO_SEQUENCE,
    serial_method: int = JSON,
    compression_type: int = GZIP,
) -> bytes:
    header_size = DEFAULT_HEADER_SIZE
    return bytes([
        (PROTOCOL_VERSION << 4) | header_size,
        (message_type << 4) | message_type_specific_flags,
        (serial_method << 4) | compression_type,
        0x00,
    ])


def _build_frame(payload_json: str, msg_type: int = CLIENT_FULL_REQUEST,
                 serial_method: int = JSON, compression: int = GZIP) -> bytes:
    """构建完整二进制帧: header(4) + size(4) + payload(gzip)"""
    payload_bytes = payload_json.encode('utf-8')
    if compression == GZIP:
        payload_bytes = gzip.compress(payload_bytes)
    header = _generate_header(msg_type, NO_SEQUENCE, serial_method, compression)
    size = struct.pack('>I', len(payload_bytes))
    return header + size + payload_bytes


def _build_audio_frame(audio_chunk: bytes, is_last: bool = False) -> bytes:
    flags = NEG_SEQUENCE if is_last else NO_SEQUENCE
    payload_bytes = gzip.compress(audio_chunk)
    header = _generate_header(CLIENT_AUDIO_ONLY_REQUEST, flags, NO_SERIALIZATION, GZIP)
    size = struct.pack('>I', len(payload_bytes))
    return header + size + payload_bytes


def _parse_response(data: bytes) -> Optional[str]:
    """解析服务端响应帧，提取识别文本。"""
    if len(data) < 4:
        return None

    header_size = data[0] & 0x0f
    message_type = data[1] >> 4
    message_compression = data[2] & 0x0f
    serialization_method = data[2] >> 4
    payload = data[header_size * 4:]

    if message_type == SERVER_ACK:
        return None

    if message_type == SERVER_ERROR_RESPONSE:
        if len(payload) >= 8:
            err_code = int.from_bytes(payload[:4], 'big', signed=False)
            payload_size = int.from_bytes(payload[4:8], 'big', signed=False)
            msg_data = payload[8:8 + payload_size]
            if message_compression == GZIP:
                try:
                    msg_data = gzip.decompress(msg_data)
                except Exception:
                    pass
            try:
                err = json.loads(msg_data.decode('utf-8'))
                logger.warning(f"☁️ 火山错误: code={err_code}, msg={err.get('message', err)}")
            except Exception:
                logger.warning(f"☁️ 火山错误: code={err_code}, raw={msg_data[:300]}")
        return None

    if message_type == SERVER_FULL_RESPONSE:
        if len(payload) < 4:
            return None
        payload_size = int.from_bytes(payload[:4], 'big', signed=True)
        payload_msg = payload[4:4 + payload_size]
        if message_compression == GZIP:
            try:
                payload_msg = gzip.decompress(payload_msg)
            except Exception:
                pass
        if serialization_method == JSON:
            try:
                parsed = json.loads(payload_msg.decode('utf-8'))
            except Exception:
                return None

            # 服务端可能返回数组（转录结果列表）或对象
            if isinstance(parsed, list):
                texts = []
                for item in parsed:
                    if isinstance(item, dict):
                        r = item.get("result") or item
                        if isinstance(r, list):
                            # result 是数组: [{"text": "..."}]
                            for sub in r:
                                if isinstance(sub, dict):
                                    t = sub.get("text", "")
                                    if t:
                                        texts.append(t.strip())
                        elif isinstance(r, dict):
                            t = r.get("text", "")
                            if t:
                                texts.append(t.strip())
                        elif isinstance(r, str):
                            texts.append(r.strip())
                return "".join(texts) or None

            # dict 形式的标准响应
            if not isinstance(parsed, dict):
                logger.warning(f"☁️ [DEBUG] 意外响应类型: {type(parsed).__name__}, 内容={str(parsed)[:300]}")
                return None
            code = parsed.get("code", -1)
            if code != SUCCESS_CODE:
                # code 1013 = "no valid speech" — 用户没说话，静默即可，不打印警告刷屏
                if code == 1013:
                    logger.debug(f"☁️ 火山 v2: 未检测到语音 (code=1013)")
                else:
                    logger.warning(f"☁️ 火山返回: code={code}, msg={parsed.get('message', '')}")
                return None
            r = parsed.get("result", {})
            if isinstance(r, list):
                # result 是数组: [{"text": "..."}]
                texts = [item.get("text", "") for item in r if isinstance(item, dict)]
                return "".join(texts).strip() or None
            # result 是对象: {"text": "..."}
            text = r.get("text", "")
            if text:
                return text.strip()
            utterances = r.get("utterances", [])
            if utterances:
                texts = [u.get("text", "") for u in utterances if u.get("text")]
                return "".join(texts).strip()
    return None


def _is_request_accepted(data: bytes) -> bool:
    """检查服务器对 Full Client Request 的响应是 ACK 还是错误，错误时打印完整详情。"""
    if len(data) < 4:
        return False
    header_size = data[0] & 0x0f
    message_type = data[1] >> 4
    message_compression = data[2] & 0x0f
    serialization_method = data[2] >> 4
    payload = data[header_size * 4:]

    if message_type == SERVER_ACK:
        return True

    if message_type == SERVER_ERROR_RESPONSE:
        if len(payload) >= 8:
            err_code = int.from_bytes(payload[:4], 'big', signed=False)
            payload_size = int.from_bytes(payload[4:8], 'big', signed=False)
            msg_data = payload[8:8 + payload_size]
            if message_compression == GZIP:
                try:
                    msg_data = gzip.decompress(msg_data)
                except Exception:
                    pass
            try:
                err = json.loads(msg_data.decode('utf-8'))
                logger.warning(f"☁️ 火山拒绝: code={err_code}, "
                              f"detail={json.dumps(err, ensure_ascii=False)[:500]}")
            except Exception:
                logger.warning(f"☁️ 火山拒绝: code={err_code}, raw={msg_data[:300]}")
        return False

    if message_type == SERVER_FULL_RESPONSE:
        if len(payload) >= 4:
            payload_size = int.from_bytes(payload[:4], 'big', signed=True)
            payload_msg = payload[4:4 + payload_size]
            if message_compression == GZIP:
                try:
                    payload_msg = gzip.decompress(payload_msg)
                except Exception:
                    pass
            if serialization_method == JSON:
                try:
                    result = json.loads(payload_msg.decode('utf-8'))
                    code = result.get("code", -1)
                    if code == SUCCESS_CODE:
                        return True  # 服务端接受请求，可以继续发送音频
                    logger.warning(f"☁️ 火山拒绝: code={code}, "
                                  f"detail={json.dumps(result, ensure_ascii=False)[:500]}")
                except Exception:
                    logger.warning(f"☁️ 火山拒绝: payload={payload_msg[:300]}")
        return False
    return False


# ── 鉴权方法 ─────────────────────────────────────────

def _token_auth(token: str) -> dict:
    """v2 Token 鉴权。"""
    return {'Authorization': f'Bearer; {token}'}


def _signature_auth(ws_url: str, token: str, secret: str,
                    binary_request: bytes) -> dict:
    """v2 HMAC256 签名鉴权。"""
    url_parse = urlparse(ws_url)
    auth_headers = 'Custom'
    header_values = {'Custom': 'auth_custom'}
    input_str = f'GET {url_parse.path} HTTP/1.1\n'
    for h in auth_headers.split(','):
        input_str += f'{header_values[h]}\n'
    input_data = bytearray(input_str, 'utf-8')
    input_data += binary_request
    mac = base64.urlsafe_b64encode(
        hmac.new(secret.encode('utf-8'), input_data, digestmod=hashlib.sha256).digest()
    )
    return {
        'Custom': 'auth_custom',
        'Authorization': (
            f'HMAC256; access_token="{token}"; '
            f'mac="{mac.decode("utf-8")}"; h="{auth_headers}"'
        ),
    }


# ── 异步核心 ──────────────────────────────────────────


async def _try_v2(wav_bytes: bytes, cfg: dict) -> str:
    """尝试 v2 API（兼容旧版）。"""
    token = cfg["access_key"]
    cluster = cfg.get("cluster", "") or "volcengine_input_common"
    secret = cfg.get("secret_key", "")
    if not token:
        return ""

    request_params = {
        'app': {
            'appid': cfg["appid"],
            'cluster': cluster,
            'token': token,
        },
        'user': {'uid': 'lianxin_user'},
        'request': {
            'reqid': str(uuid.uuid4()),
            'nbest': 1,
            'workflow': 'audio_in,resample,partition,vad,fe,decode,itn,nlu_punctuate',
            'show_utterances': False,
            'result_type': 'single',
            'sequence': 1,
        },
        'audio': {
            'format': 'wav', 'rate': 16000, 'language': 'zh-CN',
            'bits': 16, 'channel': 1, 'codec': 'raw',
        },
    }

    full_request_frame = _build_frame(json.dumps(request_params, ensure_ascii=False),
                                      CLIENT_FULL_REQUEST, JSON, GZIP)

    # 鉴权重试：先 Token，再 Signature
    auth_methods = [("Token", _token_auth(token))]
    if secret:
        auth_methods.append(("Signature", _signature_auth(_WS_URL, token, secret, full_request_frame)))

    try:
        import websockets
    except ImportError:
        return ""

    for auth_name, auth_headers in auth_methods:
        try:
            async with websockets.connect(
                _WS_URL,
                additional_headers=auth_headers,
                max_size=1000000000,
                ping_interval=None,
                close_timeout=5,
            ) as ws:
                await ws.send(full_request_frame)
                res = await ws.recv()
                if not _is_request_accepted(res):
                    continue
                await ws.send(_build_audio_frame(wav_bytes, is_last=True))
                try:
                    res = await asyncio.wait_for(ws.recv(), timeout=15)
                    text = _parse_response(res)
                    return text or ""
                except asyncio.TimeoutError:
                    return ""
        except Exception as e:
            continue
    return ""


async def _transcribe_async(wav_bytes: bytes) -> str:
    """异步语音识别：仅 v2 API（Token 鉴权）。

    使用应用级 Token（STT_VOLCANO_ACCESS_KEY）直接鉴权，
    不需要 SecretKey 签名。
    """
    cfg = _get_config()
    if not cfg["appid"]:
        logger.warning("☁️ 火山引擎未配置 AppID")
        return ""
    if not cfg["access_key"]:
        logger.warning("☁️ 火山引擎未配置 AccessKey/Token")
        return ""

    result = await _try_v2(wav_bytes, cfg)
    if result:
        return result

    # 静默失败是正常的（用户没说话、环境噪音等），不打印配置警告
    return ""


# ── 同步公开接口 ──────────────────────────────────────

def transcribe(wav_bytes: bytes, language: str = "zh-CN") -> str:
    """使用火山引擎语音识别将 WAV 转为文字。

    Args:
        wav_bytes: 16kHz 16bit mono WAV 字节
        language: 语言代码

    Returns:
        识别文本，失败返回空字符串
    """
    cfg = _get_config()
    if not cfg["appid"] or not cfg["access_key"]:
        return ""

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_transcribe_async(wav_bytes))

        import concurrent.futures
        import threading
        future: concurrent.futures.Future = concurrent.futures.Future()

        def _run_in_thread():
            try:
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                result = new_loop.run_until_complete(_transcribe_async(wav_bytes))
                new_loop.close()
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)

        t = threading.Thread(target=_run_in_thread, daemon=True)
        t.start()
        return future.result(timeout=30)

    except Exception as e:
        logger.warning(f"☁️ 火山转录异常: {e}")
        return ""
