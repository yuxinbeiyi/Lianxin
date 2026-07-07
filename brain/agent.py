"""
AgentCore：莲心AI 的大脑（LiteLLM 统一网关 + Function Calling）
使用 LiteLLM 统一接入 DeepSeek / Anthropic / Ollama 等多种模型。
"""

import json
import re
import threading
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os as _os
_os.environ.setdefault("LITELLM_LOG", "ERROR")  # 抑制 litellm 导入时的 WARNING
import litellm
litellm.set_verbose = False
litellm.suppress_debug_info = True  # 关闭 "Give Feedback" stderr 输出
from config import get_api_config, get_base_prompt, get_local_base_prompt, get_qq_bridge_config, get_qq_timing_config, get_memory_config, get_graph_config
from brain.tools import TOOL_DEFINITIONS, execute_tool, set_cross_session_context
from brain.skill_manager import get_active_tool_definitions, get_active_knowledge
from brain.graph_memory import (
    build_extraction_prompt,
    ALL_CATEGORIES,
)
from brain.graph_memory import add_fact as _memory_add
from memory.history_manager import HistoryManager
from pathlib import Path
from brain.mcp import get_all_mcp_tool_definitions


logger = logging.getLogger("Agent")

# 跨端设备切换标记
_SIDE_MARKER_PATH = Path(__file__).parent.parent / "memory" / "last_active_side.json"
_side_lock = threading.Lock()


def _get_qq_session_ids() -> set:
    """返回 QQ 桥接占用的所有 session_id 集合，桌面端应避开这些 session。"""
    try:
        map_path = Path(__file__).parent.parent / "memory" / "qq_session_map.json"
        if map_path.exists():
            data = json.loads(map_path.read_text(encoding="utf-8"))
            return set(int(v) for v in data.values())
    except Exception as e:
        import logging
        logging.getLogger("Agent").warning(f"五元组提取失败: {e}")
    return set()


# ── 工具资源分组（共享资源的工具必须串行执行） ──────────────────
# 未列出的工具无资源锁，可自由并行
_RESOURCE_GROUPS = {
    # 浏览器（共享 BrowserController 单例）
    "browser_navigate": "browser",
    "browser_snapshot": "browser",
    "browser_click": "browser",
    "browser_fill": "browser",
    "browser_screenshot": "browser",
    "fetch_webpage_browser": "browser",
    # SQLite 写入（共享数据库连接）
    "save_memory": "db_write",
    "update_memory": "db_write",
    "delete_memory": "db_write",
    "delete_graph_entity": "db_write",
    # 肩部硬件（共享 ESP32 WebSocket）
    "shoulder_photo": "hardware",
    "shoulder_pan": "hardware",
    "shoulder_tilt": "hardware",
    "shoulder_servo": "hardware",
    "shoulder_center": "hardware",
    "shoulder_status": "hardware",
    "shoulder_temp": "hardware",
    "start_shoulder_explore": "hardware",
    "start_observation_mode": "hardware",
    "stop_observation_mode": "hardware",
    "shoulder_observe": "hardware",
}
_resource_locks: dict[str, threading.Lock] = {}
_resource_init_lock = threading.Lock()

# 需要线程亲和性的资源组（浏览器 Playwright / 硬件 event loop）
# 这些组必须在调用线程上执行，不能进入 ThreadPoolExecutor
_THREAD_AFFINE_GROUPS = {"browser", "hardware"}

def _get_group_lock(group: str) -> threading.Lock:
    if group not in _resource_locks:
        with _resource_init_lock:
            if group not in _resource_locks:
                _resource_locks[group] = threading.Lock()
    return _resource_locks[group]


class AgentCore:
    def __init__(self, session_id: int = None, user_desc: str = None, disable_tools: bool = False):
        
        self._cancel_event = threading.Event()

        # 每次实例化都从文件读取最新配置，支持热重载
        cfg = get_api_config()
        self._provider = cfg.get("provider", "deepseek")  # "deepseek" | "agnes" | "local"
        self._api_format = cfg.get("api_format", "openai")
        self._use_local = (self._provider == "local")  # 兼容旧代码引用
        if self._provider == "agnes":
            from config import get_agnes_config
            agnes_cfg = get_agnes_config()
            self._model      = f"openai/{agnes_cfg['model']}"
            self._max_tokens = cfg["max_tokens"]
            self._api_base   = agnes_cfg["base_url"]
            self._api_key    = agnes_cfg["api_key"]
        elif self._provider == "local":
            self._model      = f"ollama/{cfg.get('local_model_name', 'my-deepseek')}"
            self._max_tokens = min(cfg["max_tokens"], 2048)
            self._api_base   = cfg.get("local_base_url", "http://localhost:11434/v1")
            self._api_key    = "ollama"
        else:  # deepseek
            model = cfg["model"]
            if "/" not in model:  # litellm 需要 provider 前缀
                model = f"deepseek/{model}"
            self._model      = model
            self._max_tokens = cfg["max_tokens"]
            self._api_base   = cfg["base_url"]
            self._api_key    = cfg["api_key"]

        self._disable_tools = disable_tools
        self._last_emotion = None     # 本轮回复的情绪标签（供 GUI 选图用）
        self._last_raw_response = None  # 本轮回复原始文本（含标签）
        self._last_reasoning = None    # 本轮回复的 COT 推理链
        self._last_reply_time = None   # 上次回复时间（用于自适应时间精度缓存）
        # 对话历史（OpenAI messages 格式）

        # 对话历史（OpenAI messages 格式）
        self.history: list[dict] = []

        # 会话历史持久化
        self._history_mgr = HistoryManager()
        self._last_reply_time = self._load_last_reply_time()


        # ── 自动记忆提取跟踪（从配置读取） ──────────────────
        self._extraction_counter = 0   # 对话轮次计数
        self._last_extraction_idx = 0  # history 中已提取到哪条消息
        try:
            mem_cfg = get_memory_config()
            self._auto_extract = mem_cfg.get("auto_extract", True)
            self._extract_interval = mem_cfg.get("extract_interval", 6)
            self._extract_msg_count = mem_cfg.get("extract_message_count", 20)
        except Exception:
            self._auto_extract = True
            self._extract_interval = 6
            self._extract_msg_count = 20

        # ── 五元组图记忆配置 ──────────────────────────────────────
        try:
            graph_cfg = get_graph_config()
            self._graph_enabled = graph_cfg.get("graph_enabled", True)
            self._auto_extract_quintuples = graph_cfg.get("auto_extract_quintuples", True)
        except Exception:
            self._graph_enabled = True
            self._auto_extract_quintuples = True

        # 初始化图记忆表（延迟导入，首次启动时建表）
        if self._graph_enabled:
            try:
                from brain.graph_memory import _init_tables, _get_conn
                _init_tables(_get_conn())
            except Exception:
                pass

        if session_id is not None:
            # ── 指定了 session_id：加载该会话（用于 QQ 桥接等多会话场景）
            self._session_id = session_id
            raw_msgs = self._history_mgr.get_messages(session_id)
            self.history = [
                {"role": m["role"], "content": m["content"]}
                for m in raw_msgs
            ]
            self._session_titled = True
        else:
            # ── 未指定：沿用现有逻辑，恢复上次全局会话或新建
            # 注意：如果上次会话是 QQ 桥接专用会话，桌面端不应加载它
            # 否则桌面端会混入 QQ 聊天记录，且两边同时读写同一 session 会加剧锁冲突
            qq_ids = _get_qq_session_ids()
            last_id = self._history_mgr.get_last_session_id()
            if last_id is not None and last_id not in qq_ids:
                self._session_id = last_id
                raw_msgs = self._history_mgr.get_messages(last_id)
                self.history = [
                    {"role": m["role"], "content": m["content"]}
                    for m in raw_msgs
                ]
                self._session_titled = True
            else:
                # 无历史会话 或 最后一个会话是 QQ 桥接会话：新建桌面专用会话
                self._session_id = self._history_mgr.new_session()
                self._session_titled = False

        # 启动时构建完整的 System Prompt（包含时间和记忆，只做一次）
        self._system_prompt = self._build_system_prompt_once()

        # ── 加载上一会话的压缩摘要 ──────────────────────────
        self._prev_session_summary = self._load_previous_session_summary()
        if self._prev_session_summary:
            self._system_prompt += f"\n\n{self._prev_session_summary}"

        # ── 会话内滑动窗口摘要（Token 优化，仅云端模式生效） ──
        self._conversation_summary = ""
        self._summarized_history_idx = 0

        # ── 用户上下文：让 AI 知道当前在跟谁说话 ───────────────

        if user_desc:
            self._system_prompt += f"\n\n【当前对话对象】\n{user_desc}"

        # ── 情绪标签最终提醒（云端模式，放在 system prompt 最末尾） ──
        if not self._use_local:
            self._system_prompt += """

【重要 — 回复格式要求】
在每次回复的末尾，必须单独一行用【表情：XXX】输出当前情绪。这是硬性要求。
例如：「好的～今天天气真不错！【表情：开心】」

情绪只能从以下列表选择：
开心、伤心、好奇吃惊、夸奖害羞、生气不满、得意、默认、抱歉、开玩笑、思考认真、调用工具

如果情绪不在列表中，输出【表情：默认】。不要创造列表外的情绪。"""

    # ── 对外接口 ─────────────────────────────────────────────

    @property
    def last_emotion(self) -> str | None:
        """本轮回复的情绪标签（供 GUI 选 Live2D 表情）。"""
        return self._last_emotion

    @property
    def last_reasoning(self) -> str | None:
        """本轮回复的 COT 推理链（供 GUI 展示思考过程）。"""
        return self._last_reasoning

    def chat(self, user_message: str,
            on_tool_call=None, on_tool_result=None,
            on_round_start=None,
            forced_tool: str = None,
            disable_tools: bool = False,
            interrupt_queue=None,
            on_interrupt=None,
            on_progress=None) -> str:
        """
        处理用户消息并返回 AI 回复。

        参数:
            disable_tools:     True 表示此轮不走工具调用，纯聊天模式。
            interrupt_queue:   queue.Queue | None，用户中途插话的消息队列。
            on_interrupt:      callable(msg) -> str，处理插话的 LLM 回调。
            on_progress:       callable(text)，报告进度回复的回调。
        """
        # 清除上次探索留存的观察数据，防止脏数据导致"探索被截断"误报
        try:
            from brain.observation_store import clear_latest_chain
            clear_latest_chain()
        except Exception:
            pass

        # 清除上次会话的普通草稿本笔记（持久笔记不受影响）
        try:
            from brain.notebook import get_notebook
            nb = get_notebook()
            persisted = {k: n for k, n in nb.get_all().items() if n.persist}
            nb._store.clear()
            nb._store.update(persisted)
        except Exception:
            pass

        self.history.append({"role": "user", "content": user_message})
        if not self._session_titled:
            title = user_message.strip()[:20]
            self._history_mgr.update_title(self._session_id, title)
            self._session_titled = True
        self._history_mgr.save_message(self._session_id, "user", user_message)

        effective_disable = disable_tools or self._disable_tools or self._use_local
        response_text = self._function_calling_loop(on_tool_call, on_tool_result, forced_tool,
                                                      effective_disable, interrupt_queue,
                                                      on_interrupt, on_progress, user_message,
                                                      on_round_start=on_round_start)


        # ── 剥离情绪标签：只存/显示干净文本，情绪通过属性传递 ──
        from utils.emotion_manager import parse_emotion_tag, infer_emotion_from_text
        clean_response, emotion = parse_emotion_tag(response_text)
        # fallback：LLM 未输出标签时，从文字内容推断情绪
        if not emotion:
            emotion = infer_emotion_from_text(response_text)
        if clean_response:
            display_response = clean_response
        elif emotion:
            # 整条回复只有标签没有文字 → 返回空字符串，避免标签泄露
            display_response = ""
        else:
            # 没有标签 → 原样返回
            display_response = response_text
        self._last_emotion = emotion  # 供 GUI 读取，用于选图
        self._last_raw_response = response_text  # 保留以备他用

        # ── 情感系统：分析本轮交互 ────────────────────────────
        if not effective_disable:
            try:
                from brain.emotional import get_manager as _get_emotion_mgr
                # 统计本轮工具调用次数
                _tool_count = 0
                for _m in reversed(self.history):
                    if _m.get("role") == "assistant" and "tool_calls" in _m:
                        _tool_count += len(_m["tool_calls"])
                    elif _m.get("role") == "user":
                        break
                _get_emotion_mgr().analyze_and_update(
                    [user_message], tool_call_count=_tool_count
                )
            except Exception:
                pass

        # 重要：history 存原始文本（含标签），让 LLM 在后续对话中看到自己的情绪标签，强化行为
        self.history.append({"role": "assistant", "content": response_text})
        # 数据库存干净文本（供 GUI 展示和会话恢复时读取）
        self._history_mgr.save_message(self._session_id, "assistant", display_response)

        # ── 自动记忆提取（后台执行，间隔由配置决定） ────────
        if self._auto_extract and not effective_disable:
            self._extraction_counter += 1
            if self._extraction_counter >= self._extract_interval:
                self._extraction_counter = 0
                self._trigger_auto_extraction()

        # 防御性过滤：确保没有任何残留的表情标签泄漏到显示文本
        display_response = re.sub(
            r"(?:[【［\[]|\*\*)表情[：:]\s*[^】\]］\]\*]*(?:[】\]］\]]|\*\*)?", "", display_response
        ).strip()
        display_response = re.sub(r'\n\s*\n', '\n', display_response).strip()

        # 防御性过滤：移除所有 emoji 表情符号（显示文本也不展示）
        # 注意：范围不能覆盖 CJK 汉字区域（U+3400–U+9FFF）！
        display_response = re.sub(
            r'[\U0001F300-\U0001F9FF]'       # 杂项表情符号和补充表情符号
            r'|[\U0001FA70-\U0001FAFF]'       # 表情符号扩展 A
            r'|[\U00002702-\U000027B0]'       # 丁贝符
            r'|[\U0001F1E0-\U0001F1FF]'       # 区域标志（国旗）
            r'|[\U0000FE00-\U0000FE0F]'       # 变异选择器
            r'|[❤️⭐✨💡🔥🎶🎵💤💢💦💨💫🌟]',  # 常见单个
            '', display_response
        ).strip()

        self._last_reply_time = datetime.now()
        return display_response  # 返回干净文本，不含标签和 emoji


    def _trigger_auto_extraction(self):
        """在后台线程中自动提取记忆（不阻塞对话）。本地模型跳过（不擅长 JSON 格式化输出）。"""
        if self._use_local:
            return
        start_idx = self._last_extraction_idx
        recent = self.history[start_idx:]
        if len(recent) < 3:
            return

        def _do_extract():
            # 构建对话文本（分类提取和五元组提取共用）
            target = recent[-self._extract_msg_count:]
            lines = []
            for msg in target:
                role = "用户" if msg.get("role") == "user" else "莲心"
                content = msg.get("content", "")
                if content:
                    lines.append(f"[{role}]: {content}")
            text = "\n".join(lines)
            if len(text) < 30:
                return

            # ── 分类记忆提取（独立 try，失败不影响五元组提取） ──
            try:
                prompt = build_extraction_prompt(text)
                response = litellm.completion(
                    model=self._model,
                    messages=[
                        {"role": "system",
                         "content": "你是一个专业的记忆提取助手，从对话中提取值得长期记住的信息。"},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    api_key=self._api_key,
                    api_base=self._api_base,
                    timeout=90,
                )
                raw = response.choices[0].message.content or "{}"
                result = json.loads(raw)
                memories = result.get("memories", [])

                added = 0
                for mem in memories:
                    cat = mem.get("category", "knowledge")
                    content = mem.get("content", "").strip()
                    if content and cat in ALL_CATEGORIES:
                        _memory_add(content, cat, source="auto_extracted")
                        added += 1

                if added > 0:
                    self._last_extraction_idx = len(self.history)
            except Exception:
                pass

            # ── 五元组图记忆提取（独立 try，失败不影响分类提取） ──
            if self._graph_enabled and self._auto_extract_quintuples:
                try:
                    from brain.quintuple_extractor import extract_and_store_with_config
                    extract_and_store_with_config(text, self._model, self._api_key, self._api_base)
                except Exception as e:
                    import logging
                    logging.getLogger("Agent").warning(f"五元组提取失败: {e}")

        threading.Thread(target=_do_extract, daemon=True).start()

    def clear_history(self):
        """清除当次会话的内存历史（数据库记录保留）。"""
        self.history = []
    def remove_message_by_content(self, content: str) -> bool:
        """从内存历史中删除匹配内容的消息。"""
        content = content.strip()
        for i, msg in enumerate(self.history):
            if msg.get("content", "").strip() == content:
                self.history.pop(i)
                return True
        return False
    def new_session(self):
        """开启全新会话：重置内存历史，在数据库创建新 session。"""
        self.history = []
        self._session_id = self._history_mgr.new_session()
        self._session_titled = False
        self._conversation_summary = ""
        self._summarized_history_idx = 0
        self._last_reply_time = None



    def get_history_manager(self) -> HistoryManager:
        """返回历史管理器（供 GUI 历史对话框使用）。"""
        return self._history_mgr

    def get_history_summary(self) -> str:
        rounds = len([m for m in self.history if m["role"] == "user"])
        return f"当前对话共 {rounds} 轮"

    # ── System Prompt 构建（启动时执行一次）──────────────────

    def _build_system_prompt_once(self) -> str:
        """
        构建完整的 System Prompt，包含：
        1. 基础人格设定
        2. 当前时间信息（公历 + 农历 + 节假日）
        3. 长期记忆（从文件读取）

        只在启动时执行一次，整个运行期间不变。
        本地模式使用精简 prompt，去除工具调用等复杂指令。
        """
        if self._use_local:
            base_prompt = get_local_base_prompt()
        else:
            base_prompt = get_base_prompt()

        # 获取当前时间信息（启动时）
        now = datetime.now()
        weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday = weekday_names[now.weekday()]
        date_str = now.strftime("%Y年%m月%d日")
        time_str = now.strftime("%H:%M:%S")

        # 农历信息（尝试获取）
        lunar_info = self._get_lunar_info(now)

        # 节假日信息（尝试获取）
        holiday_info = self._get_holiday_info(now)

        # 构建时间信息块
        time_block = f"【当前时间（启动时）】\n公历：{date_str} {time_str} {weekday}"
        if lunar_info:
            time_block += f"\n农历：{lunar_info}"
        if holiday_info:
            time_block += f"\n{holiday_info}"
        time_block += "\n\n注意：以上时间信息是程序启动时记录的。每次对话前会注入实时时间信息，请以实时信息为准。"

        # 组合完整 prompt
        if self._use_local:
            full_prompt = f"{base_prompt}\n\n{time_block}"
        else:
            full_prompt = f"{base_prompt}\n\n{time_block}"

        return full_prompt

    def _load_previous_session_summary(self) -> str | None:
        """加载上一会话的压缩摘要。使用本地小模型压缩，失败静默跳过。"""
        if self._use_local:
            return None
        try:
            # 获取上一个不同 session_id 的会话
            sessions = self._history_mgr.get_sessions()
            if len(sessions) < 2:
                return None
            # 找到当前 session 的前一个
            prev = None
            for s in sessions:
                if s["id"] == self._session_id and prev is not None:
                    break
                if s["id"] != self._session_id:
                    prev = s
            if prev is None:
                return None

            msgs = self._history_mgr.get_messages(prev["id"], limit=40)
            if not msgs or len(msgs) < 6:
                return None

            lines = []
            for m in msgs:
                role = "用户" if m["role"] == "user" else "莲心"
                content = m["content"][:300]
                if content.strip():
                    lines.append(f"[{role}]: {content}")
            history_text = "\n".join(lines)

            from brain.context_compressor import compress_previous_session, _ollama_available
            summary = None
            # 快速检测 Ollama 是否可用，不可用则跳过压缩
            if self._use_local and _ollama_available():
                summary = compress_previous_session(
                    history_text,
                    model="ollama/my-qwen",
                    api_base=self._api_base,
                )
                if summary:
                    logger.info(f"[记忆] 已加载上一会话摘要 (session {prev['id']} → {self._session_id})")
            return summary
        except Exception:
            return None

    def _get_lunar_info(self, dt: datetime) -> str:
        """获取农历日期信息。"""
        try:
            from zhdate import ZhDate
            lunar = ZhDate.from_datetime(dt)
            month_str = f"闰{lunar.lunar_month}月" if lunar.is_leap else f"{lunar.lunar_month}月"
            return f"{lunar.lunar_year}年{month_str}{lunar.lunar_day}日"
        except ImportError:
            return ""
        except Exception:
            return ""

    def _get_holiday_info(self, dt: datetime) -> str:
        """获取节假日信息。"""
        try:
            import chinese_calendar as cc
            date = dt.date()
            if cc.is_holiday(date):
                holiday_name = cc.get_holiday_detail(date)[0]
                if holiday_name:
                    return f"今天是法定节假日：{holiday_name}"
                else:
                    return "今天是法定节假日"
            else:
                # 周末信息
                weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
                weekday = weekday_names[dt.weekday()]
                if weekday in ["星期六", "星期日"]:
                    return f"今天是{weekday}（周末）"
                return ""
        except ImportError:
            return ""
        except Exception:
            return ""

    # ── 跨端记忆共享 ─────────────────────────────────────────

    def _get_cross_session_context(self) -> str | None:
        """
        读取另一端（桌面端↔QQ主人端）的最近聊天记录，作为上下文注入。
        使 QQ 端的莲心知道桌面端聊了什么，反之亦然。
        仅在检测到设备切换时注入，同端连续聊天不重复注入。
        """
        try:
            qq_map_path = Path(__file__).parent.parent / "memory" / "qq_session_map.json"
            if not qq_map_path.exists():
                return None

            # 设备切换检测：只有切换了端才注入
            if not self._check_side_switch():
                return None

            data = json.loads(qq_map_path.read_text(encoding="utf-8"))
            if not data:
                return None

            qq_ids = {int(v) for v in data.values()}

            # 判断当前会话是桌面端还是 QQ 端
            current_is_qq = self._session_id in qq_ids
            target_id = None
            source_name = ""

            if current_is_qq:
                # QQ 端 → 找桌面端会话（最新的非 QQ session）
                sessions = self._history_mgr.get_sessions()
                for s in sessions:
                    if s["id"] not in qq_ids:
                        target_id = s["id"]
                        break
                source_name = "桌面端"
                if target_id is None:
                    return None
            else:
                # 桌面端 → 找主人 QQ 会话
                cfg = get_qq_bridge_config()
                owner_qq = cfg.get("owner_qq", "")
                if not owner_qq:
                    return None
                owner_key = f"qq_private_{owner_qq}"
                if owner_key not in data:
                    return None
                target_id = int(data[owner_key])
                source_name = "QQ端"

            if target_id == self._session_id:
                return None

            limit = get_qq_timing_config().get("cross_session_context_limit", 6)
            msgs = self._history_mgr.get_messages(target_id, limit=limit)
            if not msgs:
                return None

            lines = []
            for m in msgs:
                speaker = "你" if m["role"] == "assistant" else "用户"
                content = m["content"][:200]
                lines.append(f"{speaker}：{content}")

            print(f"[跨端记忆] ✓ {source_name} session_id={target_id}，注入 {len(msgs)} 条")
            return (
                f"【以下是你和用户在{source_name}最近的对话记录——这是实际发生过的对话，不是参考信息】\n"
                + "\n".join(lines)
                + f"\n【以上为{source_name}对话记录，当用户问的问题与这些记录相关时，应优先使用这些记录中的信息回答】"
            )
        except Exception as e:
            print(f"[跨端记忆] 获取失败: {e}")
            return None

    # ── 设备切换检测 ─────────────────────────────────────────

    def _get_current_side(self) -> str | None:
        """判断当前会话属于哪一端：'qq' 或 'desktop'。"""
        try:
            map_path = Path(__file__).parent.parent / "memory" / "qq_session_map.json"
            if not map_path.exists():
                return None
            data = json.loads(map_path.read_text(encoding="utf-8"))
            qq_ids = {int(v) for v in data.values()}
            return "qq" if self._session_id in qq_ids else "desktop"
        except Exception:
            return None

    def _check_side_switch(self) -> bool:
        """检查是否发生了设备切换。切换了 → 应注入跨端记忆。"""
        current = self._get_current_side()
        if current is None:
            return False

        with _side_lock:
            last = None
            try:
                if _SIDE_MARKER_PATH.exists():
                    data = json.loads(_SIDE_MARKER_PATH.read_text(encoding="utf-8"))
                    last = data.get("side")
            except Exception:
                pass

            # 更新标记
            _SIDE_MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
            _SIDE_MARKER_PATH.write_text(
                json.dumps({"side": current, "updated_at": datetime.now().isoformat()}, ensure_ascii=False),
                encoding="utf-8"
            )

            return last is None or last != current

    # ── 自适应时间精度缓存 ───────────────────────────────────

    def _load_last_reply_time(self):
        try:
            conn = self._history_mgr._conn()
            row = conn.execute(
                "SELECT timestamp FROM messages WHERE role='assistant' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row and row[0]:
                return datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
        return None

    def _build_realtime_message(self) -> dict:
        now = datetime.now()

        if self._last_reply_time is not None:
            diff = (now - self._last_reply_time).total_seconds()
            use_minute = diff > 15 * 60
        else:
            use_minute = True

        weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday = weekday_names[now.weekday()]
        date_str = now.strftime("%Y年%m月%d日")
        time_str = now.strftime("%H:%M") if use_minute else now.strftime("%H:00")

        lunar_info = self._get_lunar_info(now)
        holiday_info = self._get_holiday_info(now)

        realtime = f"【实时时间】\n公历：{date_str} {time_str} {weekday}"
        if lunar_info:
            realtime += f"\n农历：{lunar_info}"
        if holiday_info:
            realtime += f"\n{holiday_info}"
        if not self._use_local:
            realtime += "\n注意：涉及时间、日期、节气、节日相关的问题时，必须先调用 get_current_time 工具获取最新信息，不要依赖记忆或猜测。"
        return {"role": "system", "content": realtime}

    # ── 日记智能回忆 ──────────────────────────────────────────

    def _should_search_diary(self, user_message: str) -> int:
        """判断是否需要搜索日记，返回 0=不搜, 1=关键词搜, 2=近期回顾"""

        LEVEL1_TRIGGERS = [
            "上次", "之前", "那天", "还记得", "你记得", "说过",
            "聊过", "以前", "过去", "曾经", "不是说过", "不是聊过"
        ]
        LEVEL2_PATTERNS = [
            r"最近怎么样", r"最近如何", r"最近过得",
            r"这几天怎么样", r"这几天如何", r"这周怎么样",
            r"最近发生了什么", r"最近有啥.*事", r"最近有没有.*事",
            r"最近.*变化", r"最近.*新鲜"
        ]

        # Level 1: 回忆触发词匹配
        if any(t in user_message for t in LEVEL1_TRIGGERS):
            return 1

        # Level 2: 时间词 + 状态询问匹配
        for pat in LEVEL2_PATTERNS:
            if re.search(pat, user_message):
                return 2

        return 0

    def _build_diary_context(self, level: int, user_message: str) -> dict | None:
        """搜索日记并构建上下文消息，无结果返回 None"""
        from utils.diary import search_diaries_by_keyword, get_recent_diaries

        if level == 1:
            # Level 1: 去掉触发词后，整句当关键词搜
            LEVEL1_TRIGGERS = [
                "上次", "之前", "那天", "还记得", "你记得", "说过",
                "聊过", "以前", "过去", "曾经", "不是说过", "不是聊过"
            ]
            kw = user_message
            for t in LEVEL1_TRIGGERS:
                kw = kw.replace(t, "")
            kw = kw.strip()
            if not kw:
                kw = user_message.strip()
            diaries = search_diaries_by_keyword(kw, limit=3)
            if not diaries:
                return None
            title = "【日记回忆】你在日记中记录过这些相关内容：\n"
        elif level == 2:
            # Level 2: 最近 7 天日记
            diaries = get_recent_diaries(limit=7)
            if not diaries:
                return None
            title = "【日记回忆】最近一周你写的日记：\n"
        else:
            return None

        lines = [title]
        for d in diaries:
            content = d["content"]
            if len(content) > 150:
                content = content[:150] + "..."
            lines.append(f"- {d['date']}: {content}")

        return {"role": "system", "content": "\n".join(lines)}

    # ── 内部实现 ─────────────────────────────────────────────



    def _execute_tool_calls_parallel(self, tool_calls, messages, on_tool_call=None, on_tool_result=None):
        """资源感知的工具并行执行。

        同一轮 LLM 返回的多个工具调用按资源组分类：
        - 无锁工具 → ThreadPoolExecutor 并发执行
        - 同组工具 → 组内串行（持锁排队），不同组间并行
        """
        from brain.tools import execute_tool as _exec, set_cross_session_context as _set_ctx

        # ── 第一遍：解析参数，检查重复 ──────────────────────
        parsed: list[dict] = []
        for tc in tool_calls:
            name = tc.function.name
            raw_args = tc.function.arguments or "{}"
            args = self._extract_json_args(raw_args)
            if not args and raw_args.strip() and raw_args.strip() not in ("{}", "[]"):
                logger.warning(f"[ToolLoop] 参数解析失败: {name}({raw_args[:100]})")
                messages.append({
                    "role": "tool", "tool_call_id": tc.id,
                    "content": f"参数解析失败，原始参数: {raw_args}。请修正 JSON 格式后重试。",
                })
                continue

            call_key = (name, json.dumps(args, ensure_ascii=False, sort_keys=True))
            last_key = getattr(self, "_last_tool_call_key", None)
            if call_key == last_key:
                logger.warning(f"[ToolLoop] 重复工具调用: {name}，终止循环")
                messages.append({
                    "role": "tool", "tool_call_id": tc.id,
                    "content": "工具重复调用已终止。请基于已有信息给出回复。",
                })
                # 不 return，只标记跳过 - 其余工具继续执行
                continue
            self._last_tool_call_key = call_key
            parsed.append({"tc": tc, "name": name, "args": args})

        if not parsed:
            return

        # ── 第二遍：按资源组分类 ────────────────────────────
        lock_free: list[dict] = []          # 无资源锁，可自由并行
        groups: dict[str, list[dict]] = {}   # 资源组 → 排队项

        for item in parsed:
            group = _RESOURCE_GROUPS.get(item["name"])
            if group is None:
                lock_free.append(item)
            else:
                groups.setdefault(group, []).append(item)

        # 结果收集（保持原始顺序）
        n = len(parsed)
        results = [None] * n
        parsed_order = {id(item["tc"]): i for i, item in enumerate(parsed)}

        import time as _perf_time
        def _run_one(item: dict):
            """执行单个工具调用（在 worker 线程内）。"""
            _set_ctx(self._session_id, self._history_mgr)
            name, args = item["name"], item["args"]
            if on_tool_call:
                on_tool_call(name, args)
            t0 = _perf_time.perf_counter()
            is_error = False
            try:
                print(f"\n  [工具调用] {name}({json.dumps(args, ensure_ascii=False)})", flush=True)
                if name == "run_shell":
                    args["cancel_event"] = self._cancel_event
                result = _exec(name, args)

                preview = result[:200].replace("\n", " ") + ("..." if len(result) > 200 else "")
                print(f"  [工具结果] {name} → {preview}\n", flush=True)
            except Exception as e:
                result = f"工具执行错误: {e}"
                is_error = True
                print(f"  [工具错误] {name} → {e}\n", flush=True)
            elapsed_ms = (_perf_time.perf_counter() - t0) * 1000
            if on_tool_result:
                on_tool_result(name, result, is_error, elapsed_ms)
            idx = parsed_order[id(item["tc"])]
            results[idx] = result

        def _run_group(group: str, items: list[dict]):
            """串行执行同一资源组的工具。"""
            lock = _get_group_lock(group)
            with lock:
                for item in items:
                    _run_one(item)

        # ── 第三遍：并行调度 ────────────────────────────────
        # 线程亲和组（browser/hardware）→ 调用线程串行执行
        # 原因：Playwright 要求在创建浏览器的同一线程操作，ESP32 也有 event loop 线程亲和
        pool_groups: dict[str, list[dict]] = {}
        for grp, items in groups.items():
            if grp not in _THREAD_AFFINE_GROUPS:
                pool_groups[grp] = items

        max_workers = min(8, len(parsed)) if len(parsed) > 0 else 1
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            # 无锁工具 → 线程池并发
            for item in lock_free:
                pool.submit(_run_one, item)
            # 池兼容组（如 db_write）→ 线程池内组间并行、组内串行
            for grp, items in pool_groups.items():
                pool.submit(_run_group, grp, items)
        # 线程亲和组 → 调用线程上逐组串行（池已关闭，调用线程空闲）
        for grp in _THREAD_AFFINE_GROUPS:
            items = groups.get(grp)
            if items:
                _run_group(grp, items)

        # ── 第四遍：结果注入 messages（保持原始顺序）────────
        for i, item in enumerate(parsed):
            result = results[i]
            if result is not None:
                messages.append({
                    "role": "tool",
                    "tool_call_id": item["tc"].id,
                    "content": result,
                })
    def _collect_stream(self, response, on_chunk=None, max_retries=2):
        """收集 litellm 流式响应，拼接成完整 message 对象。

        参数:
            response:  litellm 流式迭代器
            on_chunk:  可选回调 on_chunk(text_so_far)，用于实时进度报告
            max_retries: 流中断时的最大重试次数

        返回:
            (content, reasoning, tool_calls_dict, finish_reason)
            - content:      完整文本内容 (str | None)
            - reasoning:    深度思考链 (str | None)
            - tool_calls:   list[dict] | None，格式 [{"id":..., "function":{"name":..., "arguments":...}}]
            - finish_reason: "stop" | "tool_calls" | "length" | "error"

        异常:
            不再向上抛出异常，所有错误都通过 finish_reason="error" 返回。
        """
        full_content = ""
        full_reasoning = ""
        tool_parts: dict[int, dict] = {}  # index → {id, name, arguments}
        has_tool_calls = False
        final_finish = "stop"
        retry_count = 0

        while retry_count <= max_retries:
            try:
                for chunk in response:
                    delta = chunk.choices[0].delta

                    # 1) 深度思考（DeepSeek-R1）
                    rc = getattr(delta, "reasoning_content", None)
                    if rc is not None:
                        full_reasoning += rc

                    # 2) 文本增量
                    if delta.content is not None:
                        full_content += delta.content
                        if on_chunk:
                            on_chunk(full_content)

                    # 3) 工具调用增量
                    tc_list = getattr(delta, "tool_calls", None)
                    if tc_list:
                        has_tool_calls = True

                        for tc_delta in tc_list:
                            idx = tc_delta.index
                            if idx not in tool_parts:
                                tool_parts[idx] = {
                                    "id": tc_delta.id or "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""}
                                }
                            if tc_delta.id:
                                tool_parts[idx]["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    tool_parts[idx]["function"]["name"] += tc_delta.function.name
                                if tc_delta.function.arguments:
                                    tool_parts[idx]["function"]["arguments"] += tc_delta.function.arguments

                    # 4) 结束原因（最后一个 chunk 才有）
                    fr = getattr(chunk.choices[0], "finish_reason", None)
                    if fr is not None:
                        final_finish = fr

                break  # 正常完成，跳出重试循环

            except Exception as e:
                retry_count += 1
                if retry_count <= max_retries and (full_content or has_tool_calls):
                    import time
                    print(f"[流中断] 重试 {retry_count}/{max_retries}: {e}", flush=True)
                    time.sleep(1.0 * retry_count)
                    continue
                elif full_content or has_tool_calls:
                    print(f"[流中断] 已达最大重试次数，返回已收集内容", flush=True)
                    final_finish = "stop"
                    break
                else:
                    print(f"[流中断] 无内容可返回: {e}", flush=True)
                    return "", None, None, "error"

        if has_tool_calls and not tool_parts:
            has_tool_calls = False
        finish = "tool_calls" if has_tool_calls else final_finish
        tool_calls = [tc for _, tc in sorted(tool_parts.items())] if has_tool_calls else None
        print(f"[DEBUG] _collect_stream 返回: content={bool(full_content)}, finish={final_finish}")
        return full_content, full_reasoning, tool_calls, finish

    # ── 滑动窗口 + 摘要压缩 ────────────────────────────────

    from config import get_memory_config
    _mem_cfg = get_memory_config()
    _WINDOW_SIZE = _mem_cfg.get("context_window_size", 20)
    _SUMMARY_TRIGGER = _mem_cfg.get("summary_trigger_threshold", 30)
    _ENABLE_SUMMARY = _mem_cfg.get("enable_conversation_summary", True)
    def _apply_history_window(self):
        """对 self.history 应用滑动窗口截断 + 早期摘要压缩。

        仅在云端模式调用。

        Returns:
            (summary_text, recent_messages)
            - summary_text: 为 None 或待注入的 system 消息文本
            - recent_messages: 最近窗口内的完整历史消息列表
        """
        cfg = get_memory_config()
        window_size = cfg.get("context_window_size", 20)
        trigger = cfg.get("summary_trigger_threshold", 30)
        enable_summary = cfg.get("enable_conversation_summary", True)

        history = self.history
        if not enable_summary or len(history) <= trigger:
            return None, list(history)
        keep_start = max(0, len(history) - window_size)
        # 增量摘要：只对上次摘要后新增的溢出部分调用 LLM
        new_overflow = history[self._summarized_history_idx:keep_start]
        if len(new_overflow) >= 10:
            chunk_summary = self._generate_history_summary(new_overflow)
            if self._conversation_summary and chunk_summary:
                # 合并新旧摘要
                self._conversation_summary = self._merge_summaries(
                    self._conversation_summary, chunk_summary
                )
            else:
                self._conversation_summary = chunk_summary or self._conversation_summary
            self._summarized_history_idx = keep_start

        summary = None
        if self._conversation_summary:
            omitted = self._summarized_history_idx
            summary = (
                f"【对话历史摘要 — 前 {omitted} 条消息已压缩】\n"
                f"{self._conversation_summary}"
            )

        return summary, list(history[keep_start:])

    def _generate_history_summary(self, history_chunk: list[dict]) -> str | None:
        """将一段对话历史压缩为简洁摘要（调用 LLM）。"""
        lines = []
        for m in history_chunk:
            role = "用户" if m["role"] == "user" else "莲心"
            content = m.get("content", "")
            if len(content) > 400:
                content = content[:400] + "…"
            if content.strip():
                lines.append(f"{role}：{content}")

        if not lines:
            return None

        transcript = "\n".join(lines)

        try:
            response = litellm.completion(
                model=self._model,
                max_tokens=300,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个对话摘要助手。将以下对话压缩为一段简洁摘要（200字以内）。"
                            "只保留：讨论主题、用户个人情况、重要决策、进行中任务。"
                            "省略寒暄、闲聊、情绪表达。用第三人称叙述。"
                        ),
                    },
                    {"role": "user", "content": transcript},
                ],
                api_key=self._api_key,
                api_base=self._api_base,
                timeout=20,
            )
            result = response.choices[0].message.content
            return result.strip() if result else None
        except Exception:
            return f"（早期对话，含 {len(history_chunk)} 条消息）"

    def _merge_summaries(self, old_summary: str, new_summary: str) -> str:
        """将新旧两段摘要合并为一段（调用 LLM）。"""
        try:
            response = litellm.completion(
                model=self._model,
                max_tokens=300,
                messages=[
                    {
                        "role": "system",
                        "content": "将以下两段对话摘要合并为一段简洁摘要（200字以内），去重，保持第三人称。",
                    },
                    {
                        "role": "user",
                        "content": f"旧摘要：\n{old_summary}\n\n新摘要：\n{new_summary}",
                    },
                ],
                api_key=self._api_key,
                api_base=self._api_base,
                timeout=20,
            )
            result = response.choices[0].message.content
            return result.strip() if result else f"{old_summary}\n{new_summary}"
        except Exception:
            return f"{old_summary}\n{new_summary}"


    def _function_calling_loop(self, on_tool_call=None, on_tool_result=None, forced_tool: str = None,
                               disable_tools: bool = False,
                               interrupt_queue=None, on_interrupt=None,
                               on_progress=None, user_message: str = "",
                               on_round_start=None) -> str:

       
        messages = [{"role": "system", "content": self._system_prompt}]

        # ── 注入实时时间信息（自适应精度：间隔>15分钟用分钟级，否则小时级） ──
        messages.append(self._build_realtime_message())

        # ── 日记智能回忆：命中触发词自动搜索注入 ──────────────
        if not self._use_local:
            level = self._should_search_diary(user_message) # type: ignore
            if level > 0:
                diary_msg = self._build_diary_context(level, user_message) # type: ignore
                if diary_msg:
                    messages.append(diary_msg)

        # ── 注入情感状态（涟漪系统） ──────────────────────────

        if not self._use_local:
            try:
                from brain.emotional import get_manager as _get_emotion_mgr
                _emotion_snippet = _get_emotion_mgr().build_prompt_snippet()
                if _emotion_snippet:
                    messages.append({"role": "system", "content": _emotion_snippet})
            except Exception:
                pass

        # 注入跨端记忆上下文（有则加，无则忽略；本地模式跳过）
        if not self._use_local:
            cross_ctx = self._get_cross_session_context()
            if cross_ctx:
                messages.append({"role": "system", "content": cross_ctx})

        # ── 对话历史：云端模式滑动窗口 + 摘要压缩 ──────
        if self._use_local:
            messages.extend(self.history[-20:])
        else:
            summary_text, recent_history = self._apply_history_window()
            if summary_text:
                messages.append({"role": "system", "content": summary_text})
            messages.extend(recent_history)

        # 合并核心工具 + 已激活技能的自定义工具（本地模式跳过）
        if self._use_local:
            all_tools = []
        else:
            skill_tools = get_active_tool_definitions()
            mcp_tools = get_all_mcp_tool_definitions()
            all_tools = TOOL_DEFINITIONS + skill_tools + mcp_tools

            # 串联过滤：按用户内置工具配置过滤禁用的工具
            from config import get_builtin_tool_config
            builtin_cfg = get_builtin_tool_config()
            disabled_tool_names = {name for name, enabled in builtin_cfg.items() if not enabled}
            if disabled_tool_names:
                all_tools = [
                    t for t in all_tools
                    if t.get("function", {}).get("name", "") not in disabled_tool_names
                ]


        # ── 注入 System Prompt 技能模块（渐进式披露） ──
        if not self._use_local:
            # 从历史中提取最新用户消息
            last_user_msg = ""
            for msg in reversed(self.history):
                if msg.get("role") == "user":
                    last_user_msg = msg.get("content", "")
                    break
            if last_user_msg:
                try:
                    from skills._prompt_guides import get_matching_modules
                    modules = get_matching_modules(last_user_msg)
                    if modules:
                        messages.append({"role": "system", "content": modules})
                except Exception:
                    pass


        # ── 禁用工具模式：直接纯文本对话，不走工具循环 ──────
        if disable_tools:
            for retry in range(2):
                try:
                    stream = litellm.completion(
                        model=self._model,
                        max_tokens=self._max_tokens,
                        messages=messages,
                        api_key=self._api_key,
                        api_base=self._api_base,
                        stream=True,
                        stream_options={"include_usage": True},
                        timeout=120,
                    )
                    content, reasoning, _, finish = self._collect_stream(stream)
                    if finish == "error" and retry < 1:
                        import time as _time
                        _time.sleep(1.5)
                        continue
                    self._last_reasoning = reasoning if reasoning else None
                    return content or "（莲心没有说话）"
                except Exception as e:
                    if retry < 1:
                        import time as _time
                        _time.sleep(1.5)
                        continue
                    return f"（API 调用失败：{e}）"


        # ── 长期记忆说明（仅在走工具路径时注入） ────────────
        messages.append({
            "role": "system",
            "content": (
                "【关于你的长期记忆】\n"
                "你的长期记忆存储在本地知识库中，按分类组织，不会自动加载到 system prompt 中。\n"
                "记忆分为以下分类：\n"
                "  profile — 个人档案（姓名、外貌、性格、背景故事等稳定信息）\n"
                "  preferences — 偏好（喜欢的音乐、游戏、食物等）\n"
                "  events — 事件（过去发生的事、经历、计划）\n"
                "  knowledge — 知识（路径配置、工作原理、规则等事实）\n"
                "  behaviors — 行为模式（沟通风格、习惯、互动偏好）\n"
                "  skills — 技能（你学会的能力、工具使用经验）\n"
                "当用户询问关于个人信息、过去说过的话、偏好等需要回忆的内容时：\n"
                "  1. 优先使用 search_graph_memory 统一搜索（同时返回分类事实 + 实体关系）\n"
                "     例：问\"我之前说过喜欢什么音乐\" → search_graph_memory(keywords:['音乐','喜欢'])\n"
                "     例：问\"莲心AI用了哪些技术\" → search_graph_memory(keywords:['莲心AI','技术'])\n"
                "  2. 若统一搜索不够精确，再用 search_memory 按关键词+分类精确搜索\n"
                "  3. 使用 save_memory 保存新事实，可指定分类（会立刻生效）\n"
                "  4. 使用 update_memory 更新已过时的事实（会立刻生效）\n"
                "  5. 使用 delete_memory 删除不需要的事实（会立刻生效）\n"
                "  6. 使用 list_memories 查看全部记忆内容\n"
                "\n"
                "【实体关系查询】（当问题明确涉及实体间关系时额外使用）\n"
                "  7. 使用 query_connected_entities 多跳遍历查找间接关联\n"
                "     例：\"我的朋友们都住在哪里\" → query_connected_entities('我', depth=2)\n"
                "     例：\"和莲心AI项目相关的所有信息\" → query_connected_entities('莲心AI', depth=2)\n"
                "  8. 使用 add_graph_edge 手动添加实体关系（如从分类记忆中提取出关系后写入图）\n"
                "  9. 使用 delete_graph_entity 删除错误实体及其关联边（不可恢复）\n"
                "  10. 使用 remove_graph_edge 删除指定关系边"

            )
        })


        # ── 运行时压缩：长对话自动压缩早期消息 ────────────
        if self._use_local and len(messages) > 30:
            try:
                compress_model = "ollama/my-qwen"
                compress_base = self._api_base
                from brain.context_compressor import maybe_compress
                # 从 messages 中找出非 system 消息进行压缩检查
                non_system = [m for m in messages if m.get("role") != "system"]
                if len(non_system) > 20:
                    compressed = maybe_compress(non_system, model=compress_model, api_base=compress_base)
                    # 重建 messages：保留 system 消息 + 压缩后的结果
                    system_msgs = [m for m in messages if m.get("role") == "system"]
                    messages = system_msgs + compressed
            except Exception:
                pass

        MAX_ITERATIONS = 50          # 安全网，正常不会触发
        TODO_CHECK_INTERVAL = 6      # 每N轮检查一次进度
        DEAD_LOOP_THRESHOLD = 3      # 连续相同结果N次判定为死循环

        iteration = 0
        last_round_summaries: list[str] = []   # 最近N轮工具结果摘要

        # ── 复杂度判断：用户消息超过80字视为复杂任务 ──
        is_complex = len(self.history[-1]["content"]) > 80 if self.history else False

        while iteration < MAX_ITERATIONS:
            iteration += 1
            if on_round_start:
                on_round_start(iteration)

            # ── Todo 规划（第1轮，复杂任务） ──
            if iteration == 1 and is_complex and not self._use_local:
                messages.append({
                    "role": "system",
                    "content": (
                        "【任务规划】\n"
                        "这是一个较复杂的任务。请先规划执行步骤，按步骤稳步推进。\n"
                        "每完成一步，根据结果判断是否需要继续。任务完成就直接给出最终回答。\n"
                        "如果某个工具返回错误，分析原因后尝试其他方法，不要反复用相同参数重试。"
                    ),
                })

            # ── 接近安全网上限时才软提示 ──
            if iteration >= MAX_ITERATIONS - 3:
                messages.append({
                    "role": "system",
                    "content": (
                        "已接近最大工具调用次数上限。"
                        "请立刻基于已有信息给出最终回答，不要再调用工具。"
                        "如果内容较多，用最精炼的方式总结即可，不要展开长篇大论。"
                    ),
                })


            # 确定 tool_choice
            tool_choice = "auto"
            if forced_tool and forced_tool in [t["function"]["name"] for t in all_tools]:
                tool_choice = {"type": "function", "function": {"name": forced_tool}}
            try:
                stream = litellm.completion(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    tools=all_tools if all_tools else None,
                    tool_choice=tool_choice,
                    messages=messages,
                    api_key=self._api_key,
                    api_base=self._api_base,
                    stream=True,
                    stream_options={"include_usage": True},
                    timeout=120,
                )
                content, reasoning, stream_tool_calls, finish = self._collect_stream(stream, on_chunk=on_progress)
            except Exception as e:
                error_msg = str(e).lower()
                is_retryable = any(kw in error_msg for kw in [
                    "timeout", "connection", "getaddrinfo", "name or service not known",
                    "rate limit", "server", "500", "502", "503", "504",
                    "connection reset", "broken pipe", "eof",
                ])
                if is_retryable and iteration < 3:
                    import time as _time
                    delay = 1.5 * (iteration + 1)
                    print(f"[API重试] 第{iteration}轮失败，{delay:.1f}秒后重试: {e}", flush=True)
                    _time.sleep(delay)
                    continue
                return f"（API 调用失败：{e}）"

            if finish == "error":
                return "（莲心的网络好像不太稳定，稍等一下再试试吧~）"

            if reasoning:
                self._last_reasoning = reasoning

            if finish == "stop" or finish == "length":
                return content or "（莲心没有说话）"
            elif finish == "tool_calls":
                from types import SimpleNamespace
                # 外层用 dict（兼容 messages 列表中其他代码的 .get() 访问）
                # 内层 tool_calls 用 SimpleNamespace（兼容 _execute_tool_calls_parallel 属性访问）
                fake_tool_calls = [
                    SimpleNamespace(
                        id=tc["id"],
                        type=tc.get("type", "function"),
                        function=SimpleNamespace(
                            name=tc["function"]["name"],
                            arguments=tc["function"]["arguments"],
                        ),
                    )
                    for tc in stream_tool_calls
                ]
                fake_msg = {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": tc.get("type", "function"),
                            "function": {
                                "name": tc["function"]["name"],
                                "arguments": tc["function"]["arguments"],
                            },
                        }
                        for tc in stream_tool_calls
                    ],

                }
                if reasoning:
                    fake_msg["reasoning_content"] = reasoning

                messages.append(fake_msg)
                self._execute_tool_calls_parallel(
                    fake_tool_calls,

                    messages,
                    on_tool_call=on_tool_call,
                    on_tool_result=on_tool_result,
                )

                if forced_tool:
                    forced_tool = None

                # ── 死循环检测 ────────────────────────────

                # ── 死循环检测 ────────────────────────────
                prev_msg_count = len(messages) - len(fake_tool_calls)

                new_summaries = []
                for m in messages[prev_msg_count:]:
                    if m.get("role") == "tool":
                        new_summaries.append(m.get("content", "")[:80])
                if new_summaries:
                    round_summary = "|".join(sorted(new_summaries))
                    last_round_summaries.append(round_summary)
                    if len(last_round_summaries) > DEAD_LOOP_THRESHOLD:
                        last_round_summaries.pop(0)

                if len(last_round_summaries) >= DEAD_LOOP_THRESHOLD and last_round_summaries[0]:
                    if len(set(last_round_summaries)) == 1:
                        print(f"  [死循环检测] 连续{DEAD_LOOP_THRESHOLD}轮相同结果，强制终止",
                              flush=True)
                        messages.append({
                            "role": "system",
                            "content": (
                                "⚠️ 检测到连续多轮返回相同结果，可能陷入循环。"
                                "请停止调用工具，基于已有信息直接给出最终回答。"
                            ),
                        })

                # ── 进度检查（复杂任务每N轮确认一次） ──────
                if is_complex and iteration % TODO_CHECK_INTERVAL == 0 and iteration > 1:
                    messages.append({
                        "role": "system",
                        "content": (
                            f"【进度检查 — 第{iteration}轮】"
                            "请评估当前任务完成度。已完成就直接回答，未完成就继续调用工具。"
                        ),
                    })

                # ── 中途插话检查 ───────────────────────────

                if interrupt_queue and on_interrupt and on_progress and not disable_tools:
                    try:
                        interrupt_msg = interrupt_queue.get_nowait()
                    except Exception:
                        interrupt_msg = None
                    if interrupt_msg:
                        self._cancel_event.set()
                        print(f"  [插话] 用户: {interrupt_msg}", flush=True)
                        try:
                            reply = on_interrupt(interrupt_msg)
                        except Exception as e:
                            reply = f"（插话处理异常: {e}）"
                        print(f"  [插话回复] {reply}", flush=True)
                        on_progress(reply)
                        if "[终止]" in reply:
                            return "（任务已取消）"
                        self._cancel_event.clear() 
            else:
                return f"（意外停止: {finish}）"

        return "（任务过于复杂，已达到工具调用上限。请尝试拆分为更小的任务分步完成。）"
        

    def _call_api_with_retry(self, messages, max_retries=3, initial_delay=1.0):
        """带重试机制的 API 调用，仅用于非工具调用的纯文本请求（如日记生成）。"""
        import time
        last_exception = None
        delay = initial_delay
        for attempt in range(max_retries):
            try:
                response = litellm.completion(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    messages=messages,
                    api_key=self._api_key,
                    api_base=self._api_base,
                    timeout=90,
                )
                return response
            except Exception as e:
                last_exception = e
                print(f"[重试] API 调用失败 (尝试 {attempt+1}/{max_retries}): {e}")
                error_msg = str(e).lower()
                is_retryable = any(keyword in error_msg for keyword in [
                    "timeout", "connection", "rate limit", "server", "500", "502", "503", "504"
                ])
                if not is_retryable and attempt < max_retries - 1:
                    if attempt == 0:
                        is_retryable = True
                    else:
                        break
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    delay *= 2
                else:
                    break
        raise last_exception


    @staticmethod
    def _extract_text(content) -> str:
        if isinstance(content, str):
            return content.strip()
        return str(content)

    # ── Tool Loop 健壮化辅助 ──────────────────────────────

    @staticmethod
    def _normalize_fullwidth_json(text: str) -> str:
        """将常见全角 JSON 字符归一化为 ASCII。"""
        if not text:
            return text
        return text.translate(str.maketrans({
            "ｊ": "{", "ｋ": "}", "：": ":",
            "“": "'", "”": "'",
            "‘": "'", "’": "'",
            "［": "[", "］": "]",
        }))

    @staticmethod
    def _extract_json_args(raw_args: str) -> dict:
        """多层尝试解析 JSON arguments。"""
        if not raw_args or not raw_args.strip():
            return {}
        text = raw_args.strip()

        # 1. 直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2. 全角归一化后解析
        normalized = AgentCore._normalize_fullwidth_json(text)
        if normalized != text:
            try:
                return json.loads(normalized)
            except json.JSONDecodeError:
                pass

        # 3. 花括号深度匹配提取
        start = text.find("{")
        if start >= 0:
            depth = 0
            for i in range(start, len(text)):
                ch = text[i]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            pass
                        normed = AgentCore._normalize_fullwidth_json(text[start:i + 1])
                        if normed != text[start:i + 1]:
                            try:
                                return json.loads(normed)
                            except json.JSONDecodeError:
                                pass
                        break

        # 4. 全角花括号匹配
        full_start = text.find("ｊ")
        if full_start >= 0:
            depth = 0
            for i in range(full_start, len(text)):
                ch = text[i]
                if ch in ("ｊ", "{"):
                    depth += 1
                elif ch in ("ｋ", "}"):
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(AgentCore._normalize_fullwidth_json(text[full_start:i + 1]))
                        except json.JSONDecodeError:
                            pass
                        break

        return {}