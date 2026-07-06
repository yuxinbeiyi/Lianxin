# E:\Desktop\莲心AI\brain\stt_volcano.py
# 火山引擎一句话识别 (v2) — WebSocket 二进制协议
# 基于官方 streaming_asr_demo.py 实现
# 免费额度: 20,000 次（半年），超出后 ¥1~4.5/小时
#
# 鉴权方式（二选一，自动判断）:
#   Token 鉴权:   Authorization: Bearer; {token}
#   Signature 鉴权: Authorization: HMAC256; access_token="{token}"; mac="{sig}"; h="Custom"
#
#   config.py 中:
#     STT_VOLCANO_APPID       — 应用 ID
#     STT_VOLCANO_ACCESS_KEY  — 应用令牌 (token)，如果为空则用 SECRET_KEY 做签名鉴权
#     STT_VOLCANO_SECRET_KEY  — 签名鉴权密钥（token 鉴权时不需要）

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
from io import BytesIO
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger("lianxin.stt_volcano")

# ── 协议常量（来自官方 demo）─────────────────────────

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
POS_SEQUENCE = 0b0001
NEG_SEQUENCE = 0b0010

# Serialization
NO_SERIALIZATION = 0b0000
JSON = 0b0001

# Compression
NO_COMPRESSION = 0b0000
GZIP = 0b0001

# ── 端点 ─────────────────────────────────────────────

_WS_URL = "wss://openspeech.bytedance.com/api/v2/asr"
SUCCESS_CODE = 1000


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
        "cluster": os.environ.get("STT_VOLCANO_CLUSTER", STT_VOLCANO_CLUSTER),
        "secret_key": os.environ.get("STT_VOLCANO_SECRET_KEY", STT_VOLCANO_SECRET_KEY),
    }


# ── 二进制协议帧 ─────────────────────────────────────

def _generate_header(
    message_type: int = CLIENT_FULL_REQUEST,
    message_type_specific_flags: int = NO_SEQUENCE,
    serial_method: int = JSON,
    compression_type: int = GZIP,
) -> bytes:
    """构建 4 字节二进制协议头 (v2 format)。"""
    header_size = DEFAULT_HEADER_SIZE
    return bytes([
        (PROTOCOL_VERSION << 4) | header_size,
        (message_type << 4) | message_type_specific_flags,
        (serial_method << 4) | compression_type,
        0x00,  # reserved
    ])


def _build_full_request_frame(payload_json: str) -> bytes:
    """构建 Full Client Request 帧: header(4) + size(4) + payload(gzip)"""
    payload_bytes = gzip.compress(payload_json.encode('utf-8'))
    header = _generate_header(CLIENT_FULL_REQUEST, NO_SEQUENCE, JSON, GZIP)
    size = struct.pack('>I', len(payload_bytes))
    return header + size + payload_bytes


def _build_audio_frame(audio_chunk: bytes, is_last: bool = False) -> bytes:
    """构建 Audio Only Request 帧: header(4) + size(4) + payload(gzip)"""
    flags = NEG_SEQUENCE if is_last else NO_SEQUENCE
    header = _generate_header(CLIENT_AUDIO_ONLY_REQUEST, flags, NO_SERIALIZATION, GZIP)
    payload_bytes = gzip.compress(audio_chunk)
    size = struct.pack('>I', len(payload_bytes))
    return header + size + payload_bytes


def _parse_response(data: bytes) -> Optional[str]:
    """解析服务端响应帧，提取识别文本。

    返回 None 表示无文本（ACK/中间结果），返回 str 为最终文本。
    """
    if len(data) < 4:
        return None

    header_size = data[0] & 0x0f
    message_type = data[1] >> 4
    message_compression = data[2] & 0x0f
    serialization_method = data[2] >> 4

    payload = data[header_size * 4:]

    if message_type == SERVER_ACK:
        return None  # ACK，无文本

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
                logger.warning(f"☁️ 火山返回错误: code={err_code}, msg={err.get('message', err)}")
            except Exception:
                logger.warning(f"☁️ 火山返回错误: code={err_code}, raw={msg_data[:300]}")
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
                result = json.loads(payload_msg.decode('utf-8'))
            except Exception:
                return None

            code = result.get("code", -1)
            if code != SUCCESS_CODE:
                logger.warning(f"☁️ 火山返回: code={code}, msg={result.get('message', '')}, "
                              f"detail={json.dumps(result, ensure_ascii=False)[:500]}")
                return None

            r = result.get("result", {})
            text = r.get("text", "")
            if text:
                return text.strip()

            # 尝试 utterances
            utterances = r.get("utterances", [])
            if utterances:
                texts = [u.get("text", "") for u in utterances if u.get("text")]
                return "".join(texts).strip()

    return None


# ── 鉴权 ─────────────────────────────────────────────

def _token_auth(token: str) -> dict:
    """Token 鉴权（最简单）。"""
    return {'Authorization': f'Bearer; {token}'}


def _signature_auth(ws_url: str, token: str, secret: str,
                    binary_request: bytes) -> dict:
    """Signature 鉴权 — 对请求签名并返回完整请求头。

    根据官方 demo，需要:
      1. 发送 Custom: auth_custom 请求头
      2. 签名时把 Custom 头也纳入计算
      3. Authorization 中的 h= 字段指向参与签名的头列表
    """
    url_parse = urlparse(ws_url)

    # 构建签名输入字符串: HTTP 请求行 + 参与签名的头
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

    # 返回完整请求头（含 Custom + Authorization）
    return {
        'Custom': 'auth_custom',
        'Authorization': (
            f'HMAC256; access_token="{token}"; '
            f'mac="{mac.decode("utf-8")}"; h="{auth_headers}"'
        ),
    }


# ── 异步核心 ──────────────────────────────────────────

def _is_request_accepted(data: bytes) -> bool:
    """检查服务器对 Full Client Request 的响应是 ACK（接受）还是错误。

    返回 True=可以继续发送音频，False=服务器拒绝请求。
    错误详情会被解析并记录到日志（Fix: 不再静默丢弃）。
    """
    if len(data) < 4:
        return False

    header_size = data[0] & 0x0f
    message_type = data[1] >> 4
    message_compression = data[2] & 0x0f
    serialization_method = data[2] >> 4
    payload = data[header_size * 4:]

    # ACK → 接受
    if message_type == SERVER_ACK:
        return True

    # 错误响应 → 解析并打印完整错误，然后拒绝
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
                logger.warning(f"☁️ 火山引擎拒绝请求: code={err_code}, "
                              f"detail={json.dumps(err, ensure_ascii=False)[:500]}")
            except Exception:
                logger.warning(f"☁️ 火山引擎拒绝请求: code={err_code}, raw={msg_data[:300]}")
        else:
            logger.warning(f"☁️ 火山引擎拒绝请求: 响应不足8字节")
        return False

    # Full Response (含 error code) → 拒绝
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
                    logger.warning(f"☁️ 火山引擎拒绝请求: code={result.get('code', '?')}, "
                                  f"msg={result.get('message', '')}, "
                                  f"detail={json.dumps(result, ensure_ascii=False)[:500]}")
                except Exception:
                    logger.warning(f"☁️ 火山引擎拒绝请求: payload={payload_msg[:300]}")
        return False

    return False

async def _transcribe_async(wav_bytes: bytes) -> str:
    """异步 WebSocket 语音识别。"""
    cfg = _get_config()
    if not cfg["appid"]:
        logger.warning("☁️ 火山引擎未配置 AppID")
        return ""

    token = cfg["access_key"]

    if not token:
        logger.warning("☁️ 火山引擎未配置 AccessKey/Token")
        return ""

    cluster = cfg.get("cluster", "") or "volcengine_input_common"

    try:
        import websockets  # type: ignore
    except ImportError:
        logger.warning("☁️ websockets 未安装")
        return ""

    reqid = str(uuid.uuid4())

    request_params = {
        'app': {
            'appid': cfg["appid"],
            'cluster': cluster,
            'token': token,
        },
        'user': {
            'uid': 'lianxin_user'
        },
        'request': {
            'reqid': reqid,
            'nbest': 1,
            'workflow': 'audio_in,resample,partition,vad,fe,decode,itn,nlu_punctuate',
            'show_language': False,
            'show_utterances': False,
            'result_type': 'single',
            'sequence': 1,
        },
        'audio': {
            'format': 'wav',
            'rate': 16000,
            'language': 'zh-CN',
            'bits': 16,
            'channel': 1,
            'codec': 'raw',
        },
    }

    # 构建 Full Client Request 帧
    full_request_frame = _build_full_request_frame(
        json.dumps(request_params, ensure_ascii=False)
    )

    # 鉴权：有 SecretKey 走签名鉴权（适用于 AK/SK 凭证），否则走 Token 鉴权
    secret = cfg.get("secret_key", "")
    if secret:
        logger.info("🔑 火山引擎鉴权: Signature 签名鉴权 (AK/SK)")
        auth_headers = _signature_auth(_WS_URL, token, secret, full_request_frame)
    else:
        logger.info("🔑 火山引擎鉴权: Token 鉴权 (Bearer)")
        auth_headers = _token_auth(token)

    try:
        async with websockets.connect(
            _WS_URL,
            additional_headers=auth_headers,
            max_size=1000000000,
            ping_interval=None,
            close_timeout=5,
        ) as ws:
            # 1. 发送 Full Client Request
            await ws.send(full_request_frame)

            # 2. 检查服务器是否接受请求（ACK = 可以继续，error = 退出）
            res = await ws.recv()
            if not _is_request_accepted(res):
                logger.warning("☁️ 火山引擎拒绝请求，已退出")
                return ""

            # 3. 发送 Audio Only（gzip 压缩）
            audio_frame = _build_audio_frame(wav_bytes, is_last=True)
            await ws.send(audio_frame)

            # 4. 接收最终结果
            result_text = ""
            try:
                res = await asyncio.wait_for(ws.recv(), timeout=15)
                text = _parse_response(res)
                if text:
                    result_text = text
            except asyncio.TimeoutError:
                logger.warning("☁️ 火山转录超时（等待结果）")

            if result_text:
                logger.info(f"☁️ 火山转录: {result_text}")
                return result_text
            else:
                logger.info("☁️ 火山转录: 空结果")
                return ""

    except asyncio.TimeoutError:
        logger.warning("☁️ 火山转录连接超时")
        return ""
    except Exception as e:
        logger.warning(f"☁️ 火山转录失败: {e}")
        return ""


# ── 同步公开接口 ──────────────────────────────────────

def transcribe(wav_bytes: bytes, language: str = "zh-CN") -> str:
    """使用火山引擎一句话识别将 WAV 转为文字。

    Args:
        wav_bytes: 16kHz 16bit mono WAV 字节（含 RIFF 头）
        language: 语言代码，默认 zh-CN

    Returns:
        识别文本，失败返回空字符串
    """
    cfg = _get_config()
    if not cfg["appid"]:
        return ""

    try:
        # 没有运行中的事件循环 → 直接 asyncio.run
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_transcribe_async(wav_bytes))

        # 已有事件循环（如 Qt）→ 在新线程中运行
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
