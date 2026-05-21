"""
QQ 桥接音频工具：SILK ↔ WAV 转换、Whisper STT、Edge-TTS。

所有模块懒加载，首次使用时才导入对应依赖。
"""

import io
import os
import tempfile
import wave
from pathlib import Path
from typing import Optional


# ── 常量 ──────────────────────────────────────────────────

SILK_SAMPLE_RATE = 24000  # QQ 语音固定采样率
SILK_BITRATE = 20000      # QQ 语音码率
SILK_CHANNELS = 1         # 单声道
SILK_SAMPLE_WIDTH = 2     # 16-bit


# ══════════════════════════════════════════════════════════
# SILK ↔ PCM / WAV
# ══════════════════════════════════════════════════════════

def silk_to_wav(silk_path: str, wav_path: str, sample_rate: int = SILK_SAMPLE_RATE):
    """SILK 文件 → WAV 文件。失败时抛出异常。"""
    import pysilk
    with open(silk_path, "rb") as f_in:
        with io.BytesIO() as buf:
            pysilk.decode(f_in, buf, sample_rate)
            pcm_data = buf.getvalue()
    if not pcm_data:
        raise ValueError("pysilk.decode 返回空数据")
    _pcm_to_wav(pcm_data, wav_path, sample_rate)


def wav_to_silk(wav_path: str, silk_path: str,
                sample_rate: int = SILK_SAMPLE_RATE,
                bitrate: int = SILK_BITRATE):
    """WAV 文件 → SILK 文件。末尾补 100ms 静音防截断。"""
    import pysilk
    pcm_data = _wav_to_pcm(wav_path)
    # 补 100ms 静音，避免 pysilk 最后半帧被吞
    pad_samples = sample_rate // 10  # 100ms
    pcm_data += b'\x00' * (pad_samples * SILK_SAMPLE_WIDTH)
    with io.BytesIO(pcm_data) as f_in:
        with open(silk_path, "wb") as f_out:
            pysilk.encode(f_in, f_out, sample_rate, bitrate)


def _pcm_to_wav(pcm_bytes: bytes, wav_path: str,
                sample_rate: int = SILK_SAMPLE_RATE,
                channels: int = SILK_CHANNELS,
                sample_width: int = SILK_SAMPLE_WIDTH):
    """裸 PCM → WAV 文件。"""
    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)


def _wav_to_pcm(wav_path: str) -> bytes:
    """WAV 文件 → 裸 PCM 字节。"""
    with wave.open(wav_path, "rb") as wf:
        return wf.readframes(wf.getnframes())


# ══════════════════════════════════════════════════════════
# Whisper STT（语音 → 文字）
# ══════════════════════════════════════════════════════════

_whisper_model = None
_whisper_device = "cpu"


def _add_nvidia_dll_dirs_to_path():
    """将 site-packages/nvidia/*/{bin,lib} 目录加入 PATH，使 CUDA DLL 可被加载。"""
    import os, site
    dirs = set()
    for site_dir in site.getsitepackages():
        nv = os.path.join(site_dir, "nvidia")
        if not os.path.isdir(nv):
            continue
        for entry in os.listdir(nv):
            for sub in ("bin", "lib"):
                dll_dir = os.path.join(nv, entry, sub)
                if os.path.isdir(dll_dir):
                    dirs.add(dll_dir)
    if dirs:
        existing = os.environ.get("PATH", "")
        for d in dirs:
            if d not in existing:
                existing = d + os.pathsep + existing
        os.environ["PATH"] = existing


def _ensure_cublas():
    """确保 cuBLAS DLL 可加载，必要时自动 pip 安装。"""
    import ctypes

    # 先尝试把已安装的 nvidia 包 DLL 目录加入 PATH
    _add_nvidia_dll_dirs_to_path()
    try:
        ctypes.CDLL("cublas64_12.dll")
        return True
    except OSError:
        pass

    # DLL 缺失 → 通过 pip 安装 nvidia-cublas-cu12
    import subprocess, sys
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install",
             "nvidia-cublas-cu12", "--quiet", "--no-warn-script-location"],
            timeout=120,
        )
        import importlib
        importlib.invalidate_caches()
        # 安装后再把 DLL 目录加入 PATH
        _add_nvidia_dll_dirs_to_path()
        try:
            ctypes.CDLL("cublas64_12.dll")
            return True
        except OSError:
            return False
    except Exception:
        return False


def _get_whisper_model(model_size: str = "medium"):
    """懒加载 faster-whisper 模型。优先加载本地或 HuggingFace 缓存目录。"""
    global _whisper_model, _whisper_device
    if _whisper_model is not None:
        return _whisper_model

    import os as _os
    _os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

    # 确保 CUDA 运行时库可用
    _ensure_cublas()

    from faster_whisper import WhisperModel

    # 查找已下载的模型路径
    model_path = model_size  # 默认让 faster-whisper 自己找
    base_dir = _os.path.dirname(__file__)

    # 1) 项目本地 models/whisper-{size}/
    local_dir = _os.path.abspath(_os.path.join(base_dir, "..", "models", f"whisper-{model_size}"))
    if _os.path.isdir(local_dir) and _os.path.isfile(_os.path.join(local_dir, "model.bin")):
        model_path = local_dir
    else:
        # 2) HuggingFace 系统缓存目录
        hf_cache = _os.path.join(_os.path.expanduser("~"), ".cache", "huggingface", "hub")
        hf_model_dir = _os.path.join(hf_cache, f"models--Systran--faster-whisper-{model_size}", "snapshots")
        if _os.path.isdir(hf_model_dir):
            for snap in _os.listdir(hf_model_dir):
                snap_dir = _os.path.join(hf_model_dir, snap)
                if _os.path.isfile(_os.path.join(snap_dir, "model.bin")):
                    model_path = snap_dir
                    break

    # GPU 优先
    for dev, ct in [("cuda", "float16"), ("cpu", "int8")]:
        try:
            _whisper_model = WhisperModel(model_path, device=dev, compute_type=ct)
            _whisper_device = dev
            break
        except Exception:
            continue

    if _whisper_model is None:
        _whisper_model = WhisperModel(model_path, device="cpu", compute_type="int8")
    return _whisper_model


def transcribe(wav_path: str, language: str = "zh") -> str:
    """WAV 文件 → 文字。返回空字符串表示未识别到内容。"""
    model = _get_whisper_model()
    segments, _ = model.transcribe(wav_path, language=language, beam_size=5)
    return "".join(s.text for s in segments).strip()


# ══════════════════════════════════════════════════════════
# Edge-TTS（文字 → 语音 WAV）
# ══════════════════════════════════════════════════════════

def tts_to_wav(text: str, wav_path: str, voice: str = "zh-CN-XiaoxiaoNeural"):
    """文字 → TTS 语音文件（WAV 24000Hz 单声道 16bit）。

    Edge-TTS 输出 MP3 → pydub 解码转 WAV → 写入 wav_path。
    """
    import asyncio
    import edge_tts
    from pydub import AudioSegment

    mp3_path = wav_path + ".mp3"
    try:
        asyncio.run(edge_tts.Communicate(text, voice).save(mp3_path))
        audio = AudioSegment.from_mp3(mp3_path)
        audio = audio.set_frame_rate(24000).set_channels(1).set_sample_width(2)
        audio.export(wav_path, format="wav")
    finally:
        for p in (mp3_path,):
            try:
                os.unlink(p)
            except Exception:
                pass


# ══════════════════════════════════════════════════════════
# 格式检测
# ══════════════════════════════════════════════════════════

def detect_format(file_path: str) -> str:
    """检测音频文件格式（通过魔数）。返回 silk / amr / wav / unknown。"""
    with open(file_path, "rb") as f:
        header = f.read(16)
    if header.startswith(b"#!SILK_V3"):
        return "silk"
    if header.startswith(b"#!AMR"):
        return "amr"
    if header.startswith(b"RIFF"):
        return "wav"
    return "unknown"


def _amr_to_wav(amr_path: str, wav_path: str, sample_rate: int = 16000):
    """AMR 文件 → WAV 文件（通过 pydub + ffmpeg），默认 16kHz 对齐 Whisper。"""
    from pydub import AudioSegment
    audio = AudioSegment.from_file(amr_path, format="amr")
    audio = audio.set_frame_rate(sample_rate).set_channels(1).set_sample_width(2)
    audio.export(wav_path, format="wav")

# ── 繁→简转换 ───────────────────────────────────────────

_simplifier = None

def _to_simplified(text: str) -> str:
    """繁体中文 → 简体中文。懒加载 opencc。"""
    global _simplifier
    if _simplifier is None:
        try:
            from opencc import OpenCC
            _simplifier = OpenCC("t2s")
        except ImportError:
            # 自动安装
            import subprocess, sys
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install",
                     "opencc-python-reimplemented", "--quiet", "--no-warn-script-location"],
                    timeout=60,
                )
                from opencc import OpenCC
                _simplifier = OpenCC("t2s")
            except Exception:
                return text  # 安装失败则原样返回
    try:
        return _simplifier.convert(text)
    except Exception:
        return text


# ══════════════════════════════════════════════════════════
# 便捷函数：音频 → 文字 / 文字 → SILK
# ══════════════════════════════════════════════════════════

def convert_voice_to_text(audio_path: str, debug_log=None) -> str:
    """音频文件 → 文字。自动检测 SILK / AMR / WAV 格式并转换。"""
    fmt = detect_format(audio_path)
    wav_tmp = audio_path + ".wav"
    last_err = None

    try:
        if fmt == "amr":
            if debug_log:
                debug_log("[音频] 检测到 AMR 格式，用 pydub 转换")
            try:
                _amr_to_wav(audio_path, wav_tmp)
                if debug_log:
                    debug_log("[音频] AMR→WAV 完成")
                text = transcribe(wav_tmp)
                if debug_log:
                    debug_log(f"[音频] Whisper 转录: {text[:100] if text else '(空)'}")
                if text:
                    return _to_simplified(text)
            except Exception as e:
                last_err = e
            raise last_err or RuntimeError("AMR 转录失败")

        # SILK / unknown：原有多采样率回退逻辑
        _SAMPLE_RATES = (24000, 16000, 8000)
        for sr in _SAMPLE_RATES:
            try:
                silk_to_wav(audio_path, wav_tmp, sample_rate=sr)
            except Exception as e:
                last_err = e
                continue
            if debug_log:
                debug_log(f"[音频] SILK→WAV ({sr}Hz) 完成")
            try:
                text = transcribe(wav_tmp)
                if debug_log:
                    debug_log(f"[音频] Whisper 转录: {text[:100] if text else '(空)'}")
                if text:
                    return _to_simplified(text)
            except Exception as e:
                last_err = e
                continue
        raise last_err or RuntimeError("所有采样率尝试均失败")
    finally:
        for p in (wav_tmp,):
            try:
                os.unlink(p)
            except Exception:
                pass


def convert_text_to_voice(text: str, silk_path: str, debug_log=None) -> bool:
    """完整链路：TTS → WAV → SILK。成功返回 True。"""
    wav_tmp = silk_path + ".wav"
    try:
        tts_to_wav(text, wav_tmp)
        if debug_log:
            debug_log(f"[音频] TTS 完成: {text[:50]}... -> {wav_tmp}")
        wav_to_silk(wav_tmp, silk_path)
        if debug_log:
            debug_log(f"[音频] WAV→SILK 完成: {silk_path}")
        return True
    except Exception as e:
        print(f"[音频] 转换失败: {e}")  # print 兜底，防限频吞掉
        if debug_log:
            debug_log(f"[音频] 转换失败: {e}")
        return False
    finally:
        for p in (wav_tmp,):
            try:
                os.unlink(p)
            except Exception:
                pass
