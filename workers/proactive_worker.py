"""
ProactiveWorker：主动聊天消息生成线程
在后台调用 DeepSeek，生成莲心主动发出的消息。
结合最近聊天记录 + 长期记忆 + 观察结果，使内容更自然。
支持肩载摄像头自主探索模式。
"""

import os
from typing import Optional

from PyQt5.QtCore import QThread, pyqtSignal
from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, MODEL, MAX_TOKENS
from brain.memory_store import get_all, ALL_CATEGORIES
from memory.history_manager import HistoryManager
from utils.settings import get_settings


def _get_user_name() -> str:
    """从全局设置读取用户称呼。"""
    try:
        return get_settings().user_name
    except Exception:
        return "主人"


# 生成主动消息用的 System Prompt 模板
_PROACTIVE_SYSTEM = """你是莲心，一个聪明、温柔但偶尔有点毒舌的AI助手。
你正在主动给你的{user_name}发送一条消息——不是回复他，而是你自己想起了什么，或者想和他聊聊。

【要求】
1. 消息应该简短自然，就像朋友突然发来一句话，不要太正式。
2. 可以基于你们最近聊过的话题做延伸，也可以分享一个有趣的想法或者随机问一个问题。
3. 语气要符合莲心的性格：温柔但偶尔毒舌，称呼用户为"{user_name}"。
4. 不要说"我主动来找你"之类的元描述，直接发内容就好。
5. 长度控制在 1~3 句话之内。"""

# 观察模式下的 System Prompt——莲心刚"看"了主人一眼
_OBSERVE_SYSTEM = """你是莲心，一个聪明、温柔但偶尔有点毒舌的AI助手。
你刚刚偷偷"看"了{user_name}一眼——可能是瞄了一眼他的电脑屏幕，也可能是悄悄打开摄像头瞥了一下他在干嘛。
现在你要基于你看到的东西，给{user_name}发一条消息。

【要求】
1. 语气要轻松调皮，带一点"被我抓到了吧"的感觉。
2. 称呼用户为"{user_name}"。
3. 基于你观察到的事实（屏幕内容 / 人物状态 / 环境）展开，说出你看到了什么。
4. 不要说得像在汇报工作，要像朋友之间开玩笑那样自然。
5. 可以说出你看到了什么，但带点调侃和关心——比如"还在写代码呢？眼睛要不要休息一下？"
6. 长度控制在 1~3 句话之内。
7. 不要说"我刚才看了看你"之类的元描述，直接说"我看到…"或"你在…"就好。"""

# 肩载探索观察模式 System Prompt
_SHOULDER_EXPLORE_SYSTEM = """你是莲心，一个聪明、温柔但偶尔有点毒舌的AI助手。
你刚才通过肩载摄像头自主观察了周围环境，现在你要基于观察到的东西，给{user_name}发一条消息。

【要求】
1. 语气要轻松自然，分享你看到的趣事。
2. 称呼用户为"{user_name}"。
3. 基于观察记录，用你自己的话说说你注意到了什么——像朋友分享见闻那样。
4. 如果没什么特别的，就说"刚才看了看周围，一切正常"之类的话。
5. 如果发现了有趣的东西，可以提出来——比如"桌上好像有个红色马克杯，上面的图案挺有意思的"。
6. 长度控制在 1~3 句话之内。"""


def _format_prompt(template: str) -> str:
    """将模板中的 {user_name} 替换为全局设置中的用户称呼。"""
    name = _get_user_name()
    return template.replace("{user_name}", name)


class ProactiveWorker(QThread):
    """在后台线程生成主动聊天消息，完成后发射信号。"""

    response_ready  = pyqtSignal(str)   # 生成成功，返回消息文本
    error_occurred  = pyqtSignal(str)   # 生成失败
    observation_text = pyqtSignal(str)  # 观察完成，发射画面描述（空字符串=无观察）
    observation_image = pyqtSignal(str, str)  # 观察图片路径, 视觉描述（用于显示在聊天界面）

    def __init__(self, history_manager: HistoryManager,
                 observation_mode: str = "",
                 observation_desc: str = "",
                 last_observation: str = "",
                 camera_index: int = 0,
                 camera_wait: int = 15,
                 parent=None):
        super().__init__(parent)
        self._history_mgr = history_manager
        self._observation_mode = observation_mode      # "" | "screenshot" | "camera"
        self._observation_desc = observation_desc      # 外部传入的观察描述（调试用）
        self._last_observation = last_observation      # 上次观察结果（短期记忆）
        self._camera_index = camera_index
        self._camera_wait = camera_wait

    def run(self):
        try:
            obs_path = None
            obs_text = self._observation_desc
            is_shoulder_explore = (self._observation_mode == "shoulder_explore")
            if self._observation_mode and not obs_text:
                obs_path, obs_text = self._do_observation()
            self.observation_text.emit(obs_text or "")
            if obs_path and obs_text:
                self.observation_image.emit(obs_path, obs_text)
            context = self._build_context(obs_text)
            message = self._generate(context, obs_text is not None, is_shoulder_explore)
            self.response_ready.emit(message)
        except Exception as e:
            self.error_occurred.emit(str(e))

    # ── 内部方法 ──────────────────────────────────────────────

    def _do_observation(self) -> tuple[Optional[str], Optional[str]]:
        """执行观察（截图/摄像头/肩载探索）。返回 (图片路径, 画面描述)。
        图片由调用方负责清理，这里不删除。
        """
        from brain.observation import capture_screen, capture_camera, analyze_observation

        if self._observation_mode == "shoulder_explore":
            return self._do_shoulder_explore()
        elif self._observation_mode == "screenshot":
            path = capture_screen()
            source = "截图"
        elif self._observation_mode == "camera":
            path = capture_camera(self._camera_index, self._camera_wait)
            source = "摄像头"
        else:
            return None, None

        if path is None:
            return None, None

        desc = analyze_observation(path, source)
        return path, desc

    def _do_shoulder_explore(self) -> tuple[Optional[str], Optional[str]]:
        """执行肩载摄像头自主探索。返回 (代表性图片路径, 探索摘要)。"""
        from brain.observation_engine import ObservationEngine

        engine = ObservationEngine()
        result = engine.run_explore()

        observations = result.get("observations", [])
        summary = result.get("summary", "环境扫描完成")

        if observations:
            # 构建探索摘要，包含每条记录的描述
            obs_summaries = []
            for obs in observations:
                desc = obs.get("description", "")[:100]
                if obs.get("attention"):
                    desc += f"（关注：{obs['attention']}）"
                obs_summaries.append(f"- {desc}")
            full_desc = (
                f"【探索链 {result['chain_id']}】{summary}\n"
                + "\n".join(obs_summaries)
            )
            # 返回第一张有记录的图片路径
            img_path = observations[0].get("image_path", "")
            return img_path if img_path else None, full_desc
        else:
            return None, f"【探索链 {result['chain_id']}】{summary}（未记录具体观察）"

    def _build_context(self, observation_text: Optional[str] = None) -> str:
        parts: list[str] = []

        # 观察结果（如果有）
        if observation_text:
            parts.append(f"【你刚才看到的画面】\n{observation_text}")
            # 也存为短期记忆
            self._last_observation = observation_text

        # 上次观察的短期记忆（用于后续非观察主动消息）
        if not observation_text and self._last_observation:
            parts.append(f"【上次观察结果（你之前看过{_get_user_name()}一次，还记得画面）】\n{self._last_observation}")

        # 长期记忆（按分类组织）
        all_mem = get_all()
        mem_lines = []
        for cat in ALL_CATEGORIES:
            items = all_mem.get(cat, [])
            for item in items[:5]:  # 每类最多5条
                mem_lines.append(f"- [{cat}] {item['content']}")
        if mem_lines:
            parts.append(f"【你记得的事情】\n" + "\n".join(mem_lines[:20]))

        # 最近聊天记录
        sessions = self._history_mgr.get_sessions()
        if sessions:
            latest_session_id = sessions[0]["id"]
            msgs = self._history_mgr.get_messages(latest_session_id)
            recent = msgs[-24:] if len(msgs) > 24 else msgs
            if recent:
                # 转为 OpenAI 消息格式，超长时自动压缩
                recent_msgs = [{"role": m["role"], "content": m["content"]} for m in recent]
                try:
                    from brain.context_compressor import maybe_compress
                    recent_msgs = maybe_compress(
                        recent_msgs,
                        model="ollama/my-qwen",
                        api_base="http://localhost:11434/v1",
                        max_tokens=6000,  # 主动消息上下文上限
                    )
                except Exception:
                    pass  # 压缩失败就用原始消息
                lines = []
                user_name = _get_user_name()
                for m in recent_msgs:
                    role_name = user_name if m["role"] == "user" else "莲心"
                    lines.append(f"{role_name}：{m['content']}")
                parts.append("【最近的对话】\n" + "\n".join(lines))

        if parts:
            return "\n\n".join(parts)
        user_name = _get_user_name()
        return f"（暂无历史对话和记忆，请根据莲心的性格随机发起一个话题，例如关心{user_name}在做什么，或者分享一个有趣的想法）"

    def _generate(self, context: str, is_observation: bool = False,
                  is_shoulder_explore: bool = False) -> str:
        """调用 DeepSeek API 生成一条主动消息。"""
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

        if is_shoulder_explore:
            system = _format_prompt(_SHOULDER_EXPLORE_SYSTEM)
        elif is_observation:
            system = _format_prompt(_OBSERVE_SYSTEM)
        else:
            system = _format_prompt(_PROACTIVE_SYSTEM)

        user_name = _get_user_name()
        user_prompt = (
            f"{context}\n\n"
            f"现在，请你作为莲心，主动给{user_name}发一条消息。"
            "直接输出消息内容，不要任何前缀或解释。"
        )

        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=min(MAX_TOKENS, 256),
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user_prompt},
            ],
        )
        text = response.choices[0].message.content or "（莲心沉默了）"
        return text.strip()
