# -*- coding: utf-8 -*-
"""
阿里云实时语音识别 - 官方 SDK 版（线程安全版本，使用 threading.Event）
"""

import time
import threading
import json
import sounddevice as sd
import numpy as np
import nls
from nls.token import getToken
from config import get_aliyun_stt_config
from utils.settings import get_settings

# ========== 录音参数 ==========
SAMPLE_RATE = 16000
CHUNK_SIZE = 6400
SILENCE_THRESHOLD = 0.01
SILENCE_DURATION = 0.8
MAX_RECORD_SECONDS = 5

# 从配置获取小纸条文件路径
_settings = get_settings()
OUTPUT_FILE = _settings.note_file_path

# 确保目录存在
from pathlib import Path
Path(OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)

# 线程安全的事件标志
stop_event = threading.Event()


class MyCallback:
    def __init__(self):
        self.error_event = threading.Event()
        self.error_message = ""

    def on_sentence_end(self, message, *args):
        try:
            if isinstance(message, str):
                data = json.loads(message)
            else:
                data = message
            result = data.get("payload", {}).get("result", "")
            if result:
                print(f"[识别] {result}")
                with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                    f.write(result + "\n")
        except Exception as e:
            print(f"处理句子结束事件出错: {e}")

    def on_start(self, message, *args):
        print("识别会话已建立")

    def on_completed(self, message, *args):
        print("识别会话正常结束")

    def on_error(self, message, *args):
        print(f"识别错误: {message}")
        # 检测限流错误
        if "TOO_MANY_REQUESTS" in str(message) or "40000005" in str(message):
            print("检测到限流错误，将等待30秒后重连...")
            self.error_event.set()
            self.error_message = "rate_limit"

    def on_close(self, *args):
        print("连接已关闭")


def record_and_send(transcriber, stop_event):
    """录音并发送音频数据，使用 stop_event 控制退出"""
    silence_limit = int(SILENCE_DURATION * SAMPLE_RATE / CHUNK_SIZE)
    max_chunks = int(MAX_RECORD_SECONDS * SAMPLE_RATE / CHUNK_SIZE)

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, blocksize=CHUNK_SIZE, dtype="int16") as stream:
        while not stop_event.is_set():
            chunks = []
            silent_chunks = 0
            active = False

            for _ in range(max_chunks):
                if stop_event.is_set():
                    break
                data, _ = stream.read(CHUNK_SIZE)
                rms = np.sqrt(np.mean(data.astype(np.float64) ** 2))
                if rms > SILENCE_THRESHOLD:
                    active = True
                    silent_chunks = 0
                    chunks.append(data.tobytes())
                elif active:
                    chunks.append(data.tobytes())
                    silent_chunks += 1
                    if silent_chunks >= silence_limit:
                        break

            if chunks:
                audio_bytes = b"".join(chunks)
                for i in range(0, len(audio_bytes), CHUNK_SIZE):
                    if stop_event.is_set():
                        break
                    chunk = audio_bytes[i:i+CHUNK_SIZE]
                    transcriber.send_audio(chunk)
                    time.sleep(0.01)
            else:
                time.sleep(0.2)


def run_recognizer(stop_event):
    """运行一次识别会话，返回是否因限流而退出"""
    cfg = get_aliyun_stt_config()
    access_key_id = cfg.get("access_key_id", "").strip()
    access_key_secret = cfg.get("access_key_secret", "").strip()
    app_key = cfg.get("app_key", "").strip()

    if not (access_key_id and access_key_secret and app_key):
        print("错误：请在 API 配置中完整填写阿里云语音识别的 AccessKey ID、Secret 和 AppKey")
        return False

    print("正在获取 Token...")
    token = getToken(access_key_id, access_key_secret)
    if not token:
        print("获取 Token 失败，请检查 AccessKey 权限")
        return False
    print("Token 获取成功")

    callback = MyCallback()
    transcriber = nls.NlsSpeechTranscriber(
        url="wss://nls-gateway-cn-shanghai.aliyuncs.com/ws/v1",
        token=token,
        appkey=app_key,
        on_sentence_end=callback.on_sentence_end,
        on_start=callback.on_start,
        on_completed=callback.on_completed,
        on_error=callback.on_error,
        on_close=callback.on_close
    )

    print("正在启动识别服务...")
    transcriber.start(
        aformat="pcm",
        sample_rate=SAMPLE_RATE,
        enable_intermediate_result=False,
        enable_punctuation_prediction=True,
        enable_inverse_text_normalization=True
    )

    print(f"📝 小纸条文件：{OUTPUT_FILE}")
    print("🎤 开始监听，请说话...（按 Ctrl+C 退出）")

    send_thread = threading.Thread(target=record_and_send, args=(transcriber, stop_event))
    send_thread.daemon = True
    send_thread.start()

    # 等待退出信号或错误事件
    while not stop_event.is_set():
        if callback.error_event.is_set():
            callback.error_event.clear()
            transcriber.stop()
            return True  # 需要重连
        time.sleep(0.5)

    transcriber.stop()
    return False


def main():
    """主函数，包含重连循环"""
    global stop_event

    retry_count = 0
    while not stop_event.is_set():
        need_retry = run_recognizer(stop_event)
        if need_retry:
            retry_count += 1
            wait_time = min(30 * retry_count, 120)  # 30s, 60s, 90s, 120s
            print(f"限流触发，等待 {wait_time} 秒后重连...")
            # 分段等待，以便能响应 stop_event
            for _ in range(wait_time):
                if stop_event.is_set():
                    break
                time.sleep(1)
        else:
            break

    print("识别服务已完全停止")


if __name__ == "__main__":
    main()