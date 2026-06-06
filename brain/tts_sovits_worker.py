"""
GPT-SoVITS 合成辅助脚本 — 由 TtsEngine 通过子进程调用。

两种模式：
  1. CLI 模式（默认）：python worker.py <text> <ref_wav> <output> [mood]
  2. 持久模式：python worker.py --persistent
     从 stdin 读取 JSON 请求，处理后输出 JSON 到 stdout。

持久模式下模型只加载一次，避免反复加载模型的时间开销。
"""
import sys
import json
import os
import random
import re

import numpy as np
import scipy.io.wavfile


def _detect_language(text: str) -> str:
    """自动检测文本语言。优先级：中文 > 日文 > 英文。"""
    if re.search(r'[一-鿿]', text):
        return "中文"
    if re.search(r'[぀-ゟ゠-ヿ]', text):
        return "日文"
    if re.search(r'[a-zA-Z]{3,}', text):
        return "英文"
    return "中文"


def _normalize_audio(audio, target_peak: int = 25000):
    """音量归一化。"""
    original_max = np.max(np.abs(audio))
    if original_max > 0 and original_max < 10000:
        gain = target_peak / original_max
        audio_float = audio.astype(np.float32) * gain
        audio_float = np.clip(audio_float, -32768, 32767).astype(np.int16)
        audio = audio_float
    return audio


def synthesize(gs_path: str, text: str, ref_wav: str, output_path: str,
               mood_hint: str = None, sample_steps: int = 16) -> dict:
    """执行一次 GPT-SoVITS 合成，返回 {"success": bool, "output": str, "error": str}。"""
    # 重定向 stdout → stderr，避免 GPT-SoVITS 日志污染 JSON 输出
    _orig_stdout = sys.stdout
    sys.stdout = sys.stderr

    from GPT_SoVITS.inference_webui import get_tts_wav

    # 参考音频路径
    ref_path = ref_wav if os.path.isfile(ref_wav) else ""
    if not ref_path:
        # 扫描技能目录中的参考音频
        ref_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            os.pardir, "skills", "语音合成", "ref_wavs"
        )
        ref_dir = os.path.abspath(ref_dir)
        candidates = []
        if os.path.isdir(ref_dir):
            for root, _dirs, files in os.walk(ref_dir):
                for f in files:
                    if f.endswith(".wav"):
                        candidates.append(os.path.join(root, f))
        if not candidates:
            sys.stdout = _orig_stdout
            return {"success": False, "error": "无参考音频"}
        ref_path = random.choice(candidates)

    text_lang = _detect_language(text)

    params = {
        "ref_wav_path": ref_path,
        "prompt_text": "",
        "prompt_language": "中文",
        "text": text,
        "text_language": text_lang,
        "how_to_cut": "不切",
        "top_k": 5,
        "top_p": 0.9,
        "temperature": 0.7,
        "ref_free": True,
        "speed": 1.0,
        "if_freeze": False,
        "inp_refs": None,
        "sample_steps": sample_steps,
        "if_sr": False,
        "pause_second": 0.3,
    }

    gen = get_tts_wav(**params)
    saved = False
    for item in gen:
        if isinstance(item, tuple) and len(item) == 2:
            sr, audio = item
            audio = _normalize_audio(audio)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            scipy.io.wavfile.write(output_path, sr, audio)
            saved = True

    # 恢复 stdout 输出 JSON
    sys.stdout = _orig_stdout

    if saved:
        return {"success": True, "output": output_path}
    else:
        return {"success": False, "error": "GPT-SoVITS 未生成音频"}


def main():
    gs_path = os.environ.get("GPT_SOVITS_PATH", "")
    if not gs_path:
        print(json.dumps({"error": "环境变量 GPT_SOVITS_PATH 未设置"}), flush=True)
        return 1

    # ── 路径设置 ─────────────────────────────────────────────
    os.chdir(gs_path)
    sys.path.insert(0, gs_path)
    sovits_dir = os.path.join(gs_path, "GPT_SoVITS")
    if os.path.isdir(sovits_dir):
        sys.path.insert(0, sovits_dir)

    is_persistent = "--persistent" in sys.argv

    if is_persistent:
        # ── 持久模式：从 stdin 读取 JSON 请求，模型只加载一次 ──
        # 首次调用会触发模型加载
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                text = req.get("text", "")
                if not text.strip():
                    result = {"success": False, "error": "text 为空"}
                else:
                    result = synthesize(
                        gs_path, text,
                        req.get("ref_wav", ""),
                        req.get("output_path", ""),
                        req.get("mood"),
                        sample_steps=req.get("sample_steps", 16),
                    )
            except Exception as e:
                result = {"success": False, "error": str(e)}
            print(json.dumps(result), flush=True)
    else:
        # ── CLI 模式：一次合成 ─────────────────────────────────
        if len(sys.argv) < 4:
            print(json.dumps({"error": "参数不足: text ref_wav output_path [mood]"}), flush=True)
            return 1

        text = sys.argv[1]
        ref_wav_arg = sys.argv[2]
        output_path = sys.argv[3]
        mood_hint = sys.argv[4] if len(sys.argv) > 4 else None

        result = synthesize(gs_path, text, ref_wav_arg, output_path, mood_hint)
        print(json.dumps(result), flush=True)
        return 0 if result.get("success") else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
