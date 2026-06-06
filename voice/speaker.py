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

    # ── 文本清洗方法（保持不变）─────────────────────────────────
    def _clean_text_for_tts(self, text: str) -> str:
        """安全清洗：移除 Markdown 语法、预定义表情符号、希腊字母 ω，
        并为描述性括号内容增加停顿（句号），将换行转换为句号。"""
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
        
        # 6. 移除常见会导致 TTS 乱读的表情符号（仅移除明确列表中的）
        common_emojis = [
            '✨', '🌟', '⭐', '💡', '❤️', '🧡', '💛', '💚', '💙', '💜', '🖤', '🤍', '🤎',
            '😀', '😃', '😄', '😁', '😆', '😅', '😂', '🤣', '😊', '😇', '🙂', '🙃', '😉',
            '😌', '😍', '🥰', '😘', '😗', '😙', '😚', '😋', '😛', '😝', '😜', '🤪', '🤨',
            '🧐', '🤓', '😎', '🤩', '🥳', '😏', '😒', '😞', '😔', '😟', '😕', '🙁', '☹️',
            '😣', '😖', '😫', '😩', '🥺', '😢', '😭', '😤', '😠', '😡', '🤬', '🤯', '😳',
            '🥵', '🥶', '😱', '😨', '😰', '😥', '😓', '🤗', '🤔', '🤭', '🤫', '🤥', '😶',
            '😐', '😑', '😬', '🙄', '😯', '😦', '😧', '😮', '😲', '🥱', '😴', '🤤', '😪',
            '😵', '🤐', '🥴', '🤢', '🤮', '🤧', '😷', '🤒', '🤕', '🤑', '🤠', '😈', '👿',
            '👹', '👺', '🤡', '💩', '👻', '💀', '☠️', '👽', '👾', '🤖', '🎃', '😺', '😸',
            '😹', '😻', '😼', '😽', '🙀', '😿', '😾', '🙈', '🙉', '🙊'
        ]
        for emoji in common_emojis:
            text = text.replace(emoji, '')
        
        # 7. 删除希腊字母 ω 和 Ω（不读出）
        text = text.replace('ω', '').replace('Ω', '')
        
        # 8. 为括号描述性内容增加停顿：将右括号（后面不跟标点）替换为“）。”
        text = re.sub(r'\)(?![。！？])', '）。 ', text)
        
        # 9. 将换行符转换为句号（增加停顿）
        text = re.sub(r'\n+', '。 ', text)
        
        # 10. 将连续多个空白字符压缩为一个空格
        text = re.sub(r'\s+', ' ', text).strip()
        
        # 11. 如果清洗后为空，返回一个空格（避免无声）
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