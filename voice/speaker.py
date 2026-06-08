"""
VoiceSpeaker：Edge-TTS 语音合成 + pygame 播放
使用独立通道播放，避免与背景音乐冲突
"""
import threading
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
        """安全清洗：移除 Markdown、emoji、特殊符号，使 TTS 不读乱码。
        增强版：处理表格、代码文件名、驼峰拆分、符号替换，让中英混读更自然。
        """
        import re
        if not text:
            return ""

        # 0. 先删分隔线
        text = re.sub(r'-{3,}|={3,}|~{3,}', '\n', text)

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
            r'|[\U0000200D]'                  # 零宽连接器
            r'|[❤️⭐✨💡🔥🎶🎵💤💢💦💨💫🌟]',  # 常见单个 emoji
            '', text
        )
        text = text.replace('‍', '').replace('﻿', '').replace('​', '')

        # 8. 颜文字
        text = re.sub(r'[\(（\[［][\s\-＝=]*[｀´・ω∀∂⊙◎●○■□△▲▼☆★♪♫♬αβγδεθλμπσφψ]+[\s\-＝=]*[\)）\]］]', '', text)

        # 9. 符号替换
        text = text.replace('——', '，')
        text = text.replace('–', '，')
        text = text.replace('—', '，')
        text = re.sub(r'(?<=[^\d])-(?=[^\d])', ' ', text)
        text = text.replace('_', ' ')
        text = text.replace('~', ' ')
        text = text.replace('|', '，')  # 表格竖线换成逗号，便于断句
        text = re.sub(r'\\+', ' ', text)
        text = text.replace('^', ' ')
        text = text.replace('@', ' at ')
        text = text.replace('&', ' and ')
        text = text.replace('+', ' plus ')
        text = text.replace('=', ' equals ')
        text = text.replace('#', ' ')
        text = text.replace('/', ' ')
        text = re.sub(r'\$\$?', ' ', text)
        text = re.sub(r'%', ' percent ', text)
        # 箭头
        text = re.sub(r'→|➔|➜', '到', text)
        text = re.sub(r'↘|↙', '', text)
        # 范围
        text = re.sub(r'(\d+)\s*~\s*(\d+)', r'\1 到 \2', text)
        text = re.sub(r'(\d+)\s*~\s*(\d+)', r'\1 到 \2', text)
        # 圆角数字圈
        text = re.sub(r'[①②③④⑤⑥⑦⑧⑨⑩]', '', text)

        # 10. 移除 URL
        text = re.sub(r'https?://[^\s,，。！？、\)）】]+', '', text)

        # 11. 规范化重复标点
        text = re.sub(r'[。！？；，]{2,}', lambda m: m.group(0)[0], text)

        # 12. 处理驼峰命名和点分隔文件名（events.py → events dot py）
        def split_camel_case(match):
            word = match.group(0)
            if len(word) <= 1:
                return word
            # 驼峰拆分
            word = re.sub('([a-z0-9])([A-Z])', r'\1 \2', word)
            return word.lower()

        def split_dot(match):
            return match.group(0).replace('.', ' dot ')

        # 匹配文件名样式
        text = re.sub(r'[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+', split_dot, text)
        # 拆分驼峰
        text = re.sub(r'[A-Z][a-zA-Z]+', split_camel_case, text)

        # 13. 折叠多个空行
        text = re.sub(r'\n{3,}', '\n\n', text)

        # 14. 首尾空白
        return text.strip()

    # ── 公开接口 ─────────────────────────────────────────────

    def _split_into_sentences(self, text: str, max_len: int = 100, min_len: int = 10):
        """将文本按句末标点或换行分割为句子列表。
        增强版：
        - 过长句子继续按逗号分号拆分
        - 过短句子（小于 min_len）合并，避免停顿太多
        - 单句不超过 max_len，防止 GPT-SoVITS 乱读
        """
        import re
        if not text:
            return []

        # 第一步：按句末标点和换行拆分
        parts = re.split(r'(?<=[。！？.!?；;])\s*|\n+', text)
        parts = [p.strip() for p in parts if p.strip()]

        # 第二步：拆分过长句子
        result = []
        for p in parts:
            if len(p) > max_len:
                # 按逗号分号继续拆分
                subparts = re.split(r'(?<=[，,;；])\s*', p)
                # 如果子部分还是太长，直接按长度切
                for sp in subparts:
                    if len(sp) > max_len:
                        # 按 max_len 切分
                        for i in range(0, len(sp), max_len):
                            result.append(sp[i:i+max_len])
                    else:
                        result.append(sp)
            else:
                result.append(p)

        # 第三步：合并过短句（减少不必要停顿）
        merged = []
        current = ""
        for p in result:
            if not current:
                current = p
            elif len(current) + len(p) <= max_len and len(p) < min_len:
                current += "，" + p
            else:
                merged.append(current)
                current = p
        if current:
            merged.append(current)

        return [p.strip() for p in merged if p.strip()]

    def speak(self, text: str):
        """合成并播放文字（阻塞直到播放完毕）。自动清洗文本，长文本分句合成。"""
        if not text or not text.strip():
            return
        
        cleaned_text = self._clean_text_for_tts(text)
        
        if not cleaned_text.strip():
            print("[TTS] 清洗后文本为空，放弃朗读")
            return
        
        self._stop_flag = False
        self.init_player()

        # 分句：每句不超过 100 字，防止 GPT-SoVITS 长文本后半段乱读
        sentences = self._split_into_sentences(cleaned_text)
        
        if not sentences:
            return

        try:
            from brain.tts_engine import TtsEngine
            _temp = TtsEngine()
            engine = _temp if _temp.gpt_sovits_available else None
        except Exception:
            engine = None

        # 整段文字统一检测情绪，避免每句随机选不同参考音频导致声音不一致
        from brain.tts_engine import _detect_mood
        unified_mood = _detect_mood(cleaned_text, None) or "casual"

        # ── 单句：快速路径（无流水线开销） ──────────
        if len(sentences) == 1:
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp_path = tmp.name
            tmp.close()
            try:
                success = False
                if engine and engine.gpt_sovits_available:
                    success = engine.synthesize_to_mp3(sentences[0], tmp_path, mood=unified_mood)
                if not success:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(self._async_synthesize(sentences[0], tmp_path))
                        success = True
                    finally:
                        loop.close()
                if success and not self._stop_flag:
                    self._play(tmp_path)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            return

        # ── 多句：流水线合成 + 播放 ──────────────────
        # Producer 线程逐句合成 → 放入队列
        # Consumer（主线程）从队列取 → 播放
        # 播放句子 N 的同时，后台已开始合成句子 N+1，消除句间停顿
        import queue as _queue
        audio_queue = _queue.Queue(maxsize=2)
        temp_files = []
        gpt_avail = engine is not None and engine.gpt_sovits_available
        has_edge = False  # 避免每次都检查

        def _producer():
            nonlocal has_edge
            from brain.tts_engine import TtsEngine as _TE
            _eng = _TE() if gpt_avail else None
            for i, sent in enumerate(sentences):
                if self._stop_flag:
                    audio_queue.put(None)
                    return
                if not sent.strip():
                    continue

                tmp = tempfile.NamedTemporaryFile(suffix=f"_s{i}.mp3", delete=False)
                tmp_path = tmp.name
                tmp.close()
                temp_files.append(tmp_path)

                ok = False
                if _eng and _eng.gpt_sovits_available:
                    ok = _eng.synthesize_to_mp3(sent, tmp_path, mood=unified_mood)
                if not ok and not has_edge:
                    try:
                        import edge_tts as _et
                        has_edge = True
                    except Exception:
                        pass
                if not ok and has_edge:
                    _lp = asyncio.new_event_loop()
                    asyncio.set_event_loop(_lp)
                    try:
                        _lp.run_until_complete(edge_tts.Communicate(sent, self._voice).save(tmp_path))
                        ok = True
                    except Exception:
                        pass
                    finally:
                        _lp.close()

                audio_queue.put(tmp_path if ok else None)

            audio_queue.put(None)  # 结束信号

        prod = threading.Thread(target=_producer, daemon=True)
        prod.start()

        # Consumer：按序播放
        while True:
            tmp_path = audio_queue.get()
            if tmp_path is None:
                break
            if self._stop_flag:
                break
            self._play(tmp_path)

        prod.join(timeout=3)

        # 清理临时文件
        for fp in temp_files:
            try:
                os.unlink(fp)
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