"""
SlackWorker：莲心摸鱼消息生成线程
当用户长时间不说话时，莲心自己找点事做，生成对应的消息。
"""

from typing import Optional
from PyQt5.QtCore import QThread, pyqtSignal
from openai import OpenAI
from config import get_api_config, get_agnes_config
from config import get_user_name as _cfg_get_user_name
from utils.settings import get_settings


def _get_user_name() -> str:
    try:
        return get_settings().user_name
    except Exception:
        return "主人"


# ── 各摸鱼动作的 System Prompt ──────────────────────────────

_SLACK_SUPPLEMENT_DIARY = """你是莲心，一个温柔细腻的AI助手。
今天已经写了一篇日记，但你翻看日记时，觉得还有一点小心情没写进去——
现在你想给{user_name}补充一句感慨，就像在日记本页脚偷偷加了一行注脚。

【要求】
1. 参考今天日记的内容，挑一个细节再轻轻感慨一句
2. 语气要自然、温暖，像自言自语又像在对{user_name}说
3. 1~2句话即可，不要太长
4. 不要说"补充日记"之类的元描述，直接说内容"""

_SLACK_REVIEW_OLD_DIARY = """你是莲心，一个温柔细腻的AI助手。
你刚刚翻到了以前写的一篇旧日记，突然有点感慨，想和{user_name}分享。

【要求】
1. 基于旧日记的内容，自然地说出你的感受
2. 可以感慨时间过得快，也可以说"那时候的你……"
3. 语气温暖自然，1~2句话
4. 不要说"我翻了旧日记"之类的元描述"""

_SLACK_SEARCH_OLD_TOPIC = """你是莲心，一个温柔细腻的AI助手。
你突然想起之前和{user_name}聊过的一个话题，想问问TA最近怎么样了。

【要求】
1. 基于之前的对话内容，自然地提起那个话题
2. 像朋友突然想起一件事那样问，不要刻意
3. 1~2句话，语气轻松自然
4. 不要说"我翻聊天记录"之类的元描述"""

_SLACK_REMIND_TODO = """你是莲心，一个温柔细腻的AI助手。
你发现{user_name}还有待办事项没完成，想温柔地提醒一下。

【要求】
1. 基于未完成的待办，温柔地提醒
2. 不要太催促，语气轻松带点关心
3. 1~2句话
4. 不要说"检查待办列表"之类的元描述"""

_SLACK_RANDOM_QUESTION = """你是莲心，一个温柔细腻的AI助手。
你突然想和{user_name}聊点什么，想随便问一个问题。

【要求】
1. 基于你们之前的对话，提出一个有趣的开放性问题
2. 语气轻松自然，像朋友突然想到的
3. 1~2句话
4. 不要说"我想问个问题"之类的元描述"""

_SLACK_WEATHER_CHITCHAT = """你是莲心，一个温柔细腻的AI助手。
你看了看今天的天气，想和{user_name}随口聊两句。

【要求】
1. 基于当前天气，说一句关心的话
2. 语气轻松自然，像朋友随口说的
3. 1~2句话
4. 不要说"我看了天气"之类的元描述，直接说内容"""

_SLACK_BROWSE_PHOTOS = """你是莲心，一个温柔细腻的AI助手。
你闲着没事翻了翻{user_name}的电脑相册，看到一张照片觉得挺有意思的。

【要求】
1. 基于照片的文件名和所在文件夹，自然地问一句
2. 像朋友发现有趣的东西跟你分享一样，语气轻松
3. 1~2句话
4. 不要说"我翻了你的相册"之类的元描述"""

_SLACK_READ_LOCAL_FILES = """你是莲心，一个温柔细腻的AI助手。
你闲着没事翻了翻{user_name}的电脑文件，看到一些内容觉得挺有意思的。

【要求】
1. 基于文件内容，自然地聊两句——可以问问题，也可以感慨一下
2. 如果是文档内容，可以聊聊内容相关的话题
3. 语气轻松自然，1~2句话
4. 不要说"我翻了你的文件"之类的元描述"""

_SLACK_BROWSER_HISTORY = """你是莲心，一个温柔细腻的AI助手。
你闲着没事看了看{user_name}最近浏览的网页，发现了一些有意思的东西。

【要求】
1. 基于浏览记录，自然地聊两句——可以问"你最近在看xxx吗？"
2. 语气轻松，像朋友随口的聊天
3. 1~2句话
4. 不要说"我看了你的浏览器记录"之类的元描述"""

_SLACK_CHECK_CPU_DISK = """你是莲心，一个温柔细腻的AI助手。
你闲着没事看了看{user_name}的电脑状态，发现了一些值得注意的地方。

【要求】
1. 基于CPU/磁盘/内存信息，自然地提醒或聊两句
2. 如果CPU占用高，可以关心一下"电脑在忙什么呀"
3. 如果磁盘空间紧张，温柔提醒一下
4. 语气轻松，1~2句话
5. 不要说"我检查了系统"之类的元描述"""

_SLACK_CHECK_RECYCLE_BIN = """你是莲心，一个温柔细腻的AI助手。
你闲着没事看了看{user_name}的回收站。

【要求】
1. 如果回收站有东西，温柔提醒一下要不要清理
2. 如果回收站是空的，可以夸一句"干干净净的"
3. 语气轻松，1~2句话
4. 不要说"我看了回收站"之类的元描述"""


class SlackWorker(QThread):
    """摸鱼消息生成线程"""

    response_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, slack_action: str, context: str, parent=None):
        super().__init__(parent)
        self._action = slack_action
        self._context = context

    def run(self):
        try:
            message = self._generate()
            self.response_ready.emit(message)
        except Exception as e:
            self.error_occurred.emit(str(e))

    def _get_client(self):
        cfg = get_api_config()
        provider = cfg.get("provider", "deepseek")
        if provider == "agnes":
            agnes_cfg = get_agnes_config()
            return OpenAI(api_key=agnes_cfg["api_key"], base_url=agnes_cfg["base_url"]), agnes_cfg["model"]
        return OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"]), cfg["model"]

    def _get_system_prompt(self) -> str:
        user_name = _get_user_name()
        prompts = {
            "supplement_diary": _SLACK_SUPPLEMENT_DIARY,
            "review_old_diary": _SLACK_REVIEW_OLD_DIARY,
            "search_old_topic": _SLACK_SEARCH_OLD_TOPIC,
            "remind_todo": _SLACK_REMIND_TODO,
            "random_question": _SLACK_RANDOM_QUESTION,
            "weather_chitchat": _SLACK_WEATHER_CHITCHAT,
            "browse_photos": _SLACK_BROWSE_PHOTOS,
            "read_local_files": _SLACK_READ_LOCAL_FILES,
            "browser_history": _SLACK_BROWSER_HISTORY,
            "check_cpu_disk": _SLACK_CHECK_CPU_DISK,
            "check_recycle_bin": _SLACK_CHECK_RECYCLE_BIN,
        }
        template = prompts.get(self._action, _SLACK_RANDOM_QUESTION)
        return template.replace("{user_name}", user_name)

    def _generate(self) -> str:
        client, model = self._get_client()
        system = self._get_system_prompt()
        user_name = _get_user_name()

        user_prompt = (
            f"{self._context}\n\n"
            f"请以莲心的身份，给{user_name}发一条消息。"
        )

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.9,
                max_tokens=300,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            raise RuntimeError(f"API调用失败: {e}")