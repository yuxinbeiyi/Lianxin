"""
VoiceSpeaker：Edge-TTS 语音合成 + pygame 播放
使用独立通道播放，避免与背景音乐冲突
"""

import asyncio
import os
import re
import tempfile
import edge_tts
import pygame


class VoiceSpeaker:
    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural"):
        self._voice = voice
        self._stop_flag = False
        self._ready = False
        self._current_channel = None   # 记录当前播放的通道

    def init_player(self):
        """初始化 pygame 播放器"""
        if not self._ready:
            if not pygame.get_init():
                pygame.init()
            pygame.mixer.init()
            self._ready = True

    # ── 文本清洗方法 ─────────────────────────────────
    def _clean_text_for_tts(self, text: str) -> str:
        """安全清洗：移除 Markdown、emoji、特殊符号，使 TTS 不读乱码。"""
        if not text:
            return ""

        # 1. Markdown 链接 [text](url) -> text
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
        # 2. 图片
        text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', '', text)
        # 3. 加粗斜体等（保留内部文字）
        text = re.sub(r'\*\*([^\*]+)\*\*', r'\1', text)
        text = re.sub(r'\*([^\*]+)\*', r'\1', text)
        text = re.sub(r'__([^_]+)__', r'\1', text)
        text = re.sub(r'~~([^~]+)~~', r'\1', text)
        # 4. 行内代码
        text = re.sub(r'`([^`]+)`', r'\1', text)
        # 5. 移除标题标记（行首的 #）
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        # 6. 移除代码块标记
        text = re.sub(r'```[\s\S]*?```', '', text)
        text = re.sub(r'~~~[\s\S]*?~~~', '', text)

        # 7. 移除所有 emoji（Unicode 表情符号区段）
        # 注意：范围不能覆盖 CJK 汉字区域（U+3400–U+9FFF）！
        text = re.sub(
            r'[\U0001F300-\U0001F9FF]'       # 杂项表情符号和补充表情符号
            r'|[\U0001FA70-\U0001FAFF]'       # 表情符号扩展 A
            r'|[\U00002702-\U000027B0]'       # 丁贝符
            r'|[\U0001F1E0-\U0001F1FF]'       # 区域标志（国旗）
            r'|[\U0000FE00-\U0000FE0F]'       # 变异选择器
            r'|[\U0000200D\U0000FE0F]'        # 零宽连接器
            r'|[❤️⭐✨💡🔥🎶🎵💤💢💦💨💫🌟]',  # 常见单个 emoji 补充
            '', text
        )
        # 8. 移除颜文字（括号包围的特殊符号组合，如 (｀・ω・´)）
        text = re.sub(r'[\(（\[［][\s\-＝=]*[｀´・ω∀∂⊙◎●○■□△▲▼☆★♪♫♬αβγδεθλμπσφψ]+[\s\-＝=]*[\)）\]］]', '', text)

        # 9. 删除 TTS 会逐字朗读的符号
        # 横线/短横 → 空格
        text = text.replace('——', '，')
        text = text.replace('–', '，')
        text = text.replace('—', '，')
        text = re.sub(r'(?<=[^\d])-(?=[^\d])', ' ', text)  # 非数字间的单独-号
        # 其他符号 → 移除或空格
        text = text.replace('_', ' ')
        text = text.replace('~', ' ')
        text = text.replace('|', ' ')
        text = re.sub(r'\\+', ' ', text)  # 反斜线
        text = text.replace('^', ' ')
        text = text.replace('@', ' at ')
        text = text.replace('&', ' and ')
        text = text.replace('+', ' plus ')
        text = text.replace('=', ' equals ')
        text = text.replace('#', ' ')
        text = text.replace('/', ' ')
        text = re.sub(r'\$\$?', ' ', text)  # 美元符号
        text = re.sub(r'%', ' percent ', text)

        # 10. 移除 URL
        text = re.sub(r'https?://[^\s,，。！？、\)）】]+', '', text)

        # 11. 规范化重复标点
        text = re.sub(r'！{2,}', '！', text)
        text = re.sub(r'？{2,}', '？', text)
        text = re.sub(r'。{2,}', '……', text)
        text = re.sub(r'，{2,}', '，', text)
        text = re.sub(r'~{2,}', ' ', text)

        # 12. 为括号内容增加停顿：右括号后不跟标点则加句号
        text = re.sub(r'\)(?![。！？,，])', '）。 ', text)

        # 13. 将换行符转换为句号
        text = re.sub(r'\n+', '。 ', text)

        # 14. 将连续多个空白字符压缩为一个空格
        text = re.sub(r'\s+', ' ', text).strip()

        # 15. 移除残留的 emoji 变异选择器/零宽字符
        text = text.replace('‍', '').replace('﻿', '').replace('​', '')

        # 16. 如果清洗后为空，返回一个空格（避免无声）
        if not text:
            return " "
        return text

    # ── 公开接口 ─────────────────────────────────────────────

    def speak(self, text: str):
        """合成并播放文字（阻塞直到播放完毕）。自动清洗文本。"""
        if not text or not text.strip():
            return
        
        cleaned_text = self._clean_text_for_tts(text)
        
        # 调试输出（正式使用可注释掉）
        #if cleaned_text != text:
            #print(f"[TTS] 原文: {text[:100]}")
            #print(f"[TTS] 清洗后: {cleaned_text[:100]}")
        
        if not cleaned_text.strip():
            print("[TTS] 清洗后文本为空，放弃朗读")
            return
        
        self._stop_flag = False
        self.init_player()

        tmp_path = self._synthesize(cleaned_text)
        if tmp_path and not self._stop_flag:
            self._play(tmp_path)
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def stop(self):
        """停止当前播放。"""
        self._stop_flag = True
        if self._current_channel:
            self._current_channel.stop()
            self._current_channel = None
        # 备用：停止所有通道？更简单：不处理其他通道

    # ── 内部方法 ─────────────────────────────────────────────

    def _synthesize(self, text: str) -> str | None:
        # 优先使用 TtsEngine（GPT-SoVITS）
        try:
            from brain.tts_engine import TtsEngine
            engine = TtsEngine()
            if engine.gpt_sovits_available:
                tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                tmp_path = tmp.name
                tmp.close()
                success = engine.synthesize_to_mp3(text, tmp_path)
                if success:
                    return tmp_path
        except Exception:
            pass

        # 回退：原 Edge-TTS 逻辑
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp_path = tmp.name
            tmp.close()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._async_synthesize(text, tmp_path))
            finally:
                loop.close()
            return tmp_path
        except Exception as e:
            print(f"[TTS合成出错] {e}")
            return None

    async def _async_synthesize(self, text: str, path: str):
        communicate = edge_tts.Communicate(text, self._voice)
        await communicate.save(path)

    def _play(self, path: str):
        try:
            # 加载为 Sound 对象，避免使用 music 通道
            sound = pygame.mixer.Sound(path)
            from utils.settings import get_settings
            volume = get_settings().tts_volume
            sound.set_volume(volume)
            # 查找空闲通道播放
            channel = pygame.mixer.find_channel()
            if channel is None:
                # 如果没有空闲通道，直接播放（可能会抢占其他音效，但概率低）
                sound.play()
                self._current_channel = None
            else:
                channel.play(sound)
                self._current_channel = channel
            # 等待播放结束
            while (self._current_channel and self._current_channel.get_busy()) or (not self._current_channel and pygame.mixer.get_busy()):
                if self._stop_flag:
                    if self._current_channel:
                        self._current_channel.stop()
                    else:
                        pygame.mixer.stop()
                    break
                pygame.time.wait(50)
        except Exception as e:
            print(f"[TTS播放出错] {e}")
        finally:
            self._current_channel = None