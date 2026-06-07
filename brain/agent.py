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
from brain.memory_store import (
    build_extraction_prompt,
    ALL_CATEGORIES,
)
from brain.graph_memory import add_fact as _memory_add
from memory.history_manager import HistoryManager
from pathlib import Path

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
    except Exception:
        pass
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
        # 每次实例化都从文件读取最新配置，支持热重载
        cfg = get_api_config()
        self._use_local = cfg.get("use_local", False)
        self._api_format = cfg.get("api_format", "openai")
        if self._use_local:
            self._model      = f"ollama/{cfg.get('local_model_name', 'my-deepseek')}"
            self._max_tokens = min(cfg["max_tokens"], 2048)
            self._api_base   = cfg.get("local_base_url", "http://localhost:11434/v1")
        else:
            model = cfg["model"]
            if "/" not in model:  # litellm 需要 provider 前缀
                model = f"deepseek/{model}"
            self._model      = model
            self._max_tokens = cfg["max_tokens"]
            self._api_base   = cfg["base_url"]
        self._api_key = cfg["api_key"] if not self._use_local else "ollama"

        self._disable_tools = disable_tools
        self._last_emotion = None     # 本轮回复的情绪标签（供 GUI 选图用）
        self._last_raw_response = None  # 本轮回复原始文本（含标签）
        self._last_reasoning = None    # 本轮回复的 COT 推理链
        # 对话历史（OpenAI messages 格式）
        self.history: list[dict] = []

        # 会话历史持久化
        self._history_mgr = HistoryManager()

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
            forced_tool: str = None,
            disable_tools: bool = False) -> str:
        """
        处理用户消息并返回 AI 回复。

        参数:
            disable_tools: True 表示此轮不走工具调用，纯聊天模式。
                           用于三层架构中的角色扮演层（Roleplay）。
                           覆盖实例化时的 disable_tools 设置。
        """
        # 清除上次探索留存的观察数据，防止脏数据导致"探索被截断"误报
        try:
            from brain.observation_store import clear_latest_chain
            clear_latest_chain()
        except Exception:
            pass

        # 原有代码...
        self.history.append({"role": "user", "content": user_message})
        if not self._session_titled:
            title = user_message.strip()[:20]
            self._history_mgr.update_title(self._session_id, title)
            self._session_titled = True
        self._history_mgr.save_message(self._session_id, "user", user_message)

        effective_disable = disable_tools or self._disable_tools or self._use_local
        response_text = self._function_calling_loop(on_tool_call, on_tool_result, forced_tool, effective_disable)

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

        # 防御性过滤：确保没有任何残留的【表情：XXX】泄漏到显示文本
        display_response = re.sub(
            r"[【［\[]表情[：:]\s*[^】\]］\]]*[】\]］\]]?", "", display_response
        ).strip()
        display_response = re.sub(r'\n\s*\n', '\n', display_response).strip()

        # 防御性过滤：移除所有 emoji 表情符号（显示文本也不展示）
        display_response = re.sub(
            r'[\U0001F000-\U0001FFFF]'
            r'|[\U00002702-\U000027B0]'
            r'|[\U000024C2-\U0001F251]'
            r'|[\U0001F600-\U0001F64F]'
            r'|[\U0001F300-\U0001F5FF]'
            r'|[\U0001F680-\U0001F6FF]'
            r'|[\U0001F1E0-\U0001F1FF]'
            r'|[\U00002700-\U000027BF]',
            '', display_response
        ).strip()

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
                    timeout=30,
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
                    from brain.quintuple_extractor import extract_and_store
                    extract_and_store(text)
                except Exception:
                    pass

        threading.Thread(target=_do_extract, daemon=True).start()

    def clear_history(self):
        """清除当次会话的内存历史（数据库记录保留）。"""
        self.history = []

    def new_session(self):
        """开启全新会话：重置内存历史，在数据库创建新 session。"""
        self.history = []
        self._session_id = self._history_mgr.new_session()
        self._session_titled = False

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
            if self._use_local or _ollama_available():
                summary = compress_previous_session(
                    history_text,
                    model="ollama/my-qwen",
                    api_base=self._api_base if self._use_local else "http://localhost:11434/v1",
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

        def _run_one(item: dict):
            """执行单个工具调用（在 worker 线程内）。"""
            _set_ctx(self._session_id, self._history_mgr)
            name, args = item["name"], item["args"]
            if on_tool_call:
                on_tool_call(name, args)
            print(f"\n  [工具调用] {name}({json.dumps(args, ensure_ascii=False)})", flush=True)
            result = _exec(name, args)
            preview = result[:200].replace("\n", " ") + ("..." if len(result) > 200 else "")
            print(f"  [工具结果] {name} → {preview}\n", flush=True)
            if on_tool_result:
                on_tool_result(name, result)
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

    def _function_calling_loop(self, on_tool_call=None, on_tool_result=None, forced_tool: str = None, disable_tools: bool = False) -> str:
        messages = [{"role": "system", "content": self._system_prompt}]

        # ── 注入实时时间信息 ────────────────────────────────
        now = datetime.now()
        weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday = weekday_names[now.weekday()]
        date_str = now.strftime("%Y年%m月%d日")
        time_str = now.strftime("%H:%M:%S")
        lunar_info = self._get_lunar_info(now)
        holiday_info = self._get_holiday_info(now)
        realtime = f"【实时时间】\n公历：{date_str} {time_str} {weekday}"
        if lunar_info:
            realtime += f"\n农历：{lunar_info}"
        if holiday_info:
            realtime += f"\n{holiday_info}"
        if not self._use_local:
            realtime += "\n注意：涉及时间、日期、节气、节日相关的问题时，必须先调用 get_current_time 工具获取最新信息，不要依赖记忆或猜测。"
        messages.append({"role": "system", "content": realtime})

        # 注入跨端记忆上下文（有则加，无则忽略；本地模式跳过）
        if not self._use_local:
            cross_ctx = self._get_cross_session_context()
            if cross_ctx:
                messages.append({"role": "system", "content": cross_ctx})

        # 本地模式只保留最近 10 轮对话，避免上下文溢出
        if self._use_local:
            messages.extend(self.history[-20:])
        else:
            messages.extend(self.history)

        # 合并核心工具 + 已激活技能的自定义工具（本地模式跳过）
        if self._use_local:
            all_tools = []
        else:
            skill_tools = get_active_tool_definitions()
            all_tools = TOOL_DEFINITIONS + skill_tools

        # 注入已激活技能的知识内容（本地模式跳过）
        if not self._use_local:
            skill_knowledge = get_active_knowledge()
            if skill_knowledge:
                messages.append({
                    "role": "system",
                    "content": "【以下是你当前已激活的技能知识】\n" + "\n\n".join(skill_knowledge)
                })

        # ── 禁用工具模式：直接纯文本对话，不走工具循环 ──────
        if disable_tools:
            try:
                response = litellm.completion(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    messages=messages,
                    api_key=self._api_key,
                    api_base=self._api_base,
                    timeout=30,
                )
            except Exception as e:
                return f"（API 调用失败：{e}）"
            self._last_reasoning = getattr(response.choices[0].message, "reasoning_content", None)
            return response.choices[0].message.content or "（莲心没有说话）"

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
                "  1. 使用 search_memory 按关键词（和可选分类）来查找记忆\n"
                "  2. 使用 save_memory 保存新的事实，可指定分类（会立刻生效）\n"
                "  3. 使用 update_memory 更新已过时的事实（会立刻生效）\n"
                "  4. 使用 delete_memory 删除不需要的事实（会立刻生效）\n"
                "  5. 使用 list_memories 查看全部记忆内容\n"
                "\n"
                "【知识图谱记忆】（五元组图记忆，存实体之间的关联关系）\n"
                "  6. 使用 search_graph_memory 搜索实体间的关联，如\"A(人物)—[喜欢]→B(物品)\"\n"
                "     适用于：\"我和X有什么关系\"、\"谁喜欢Y\"、\"我之前提过什么Z\"\n"
                "  7. 使用 query_connected_entities 查找与某实体间接关联的所有关系\n"
                "     适用于：\"这个项目用了哪些技术\"、\"和X相关的所有信息\"\n"
                "  8. 使用 delete_graph_entity 删除图记忆中的实体及其所有关联边\n"
                "     适用于：删除错误或测试数据（不可恢复）"
            )
        })


        # ── 运行时压缩：长对话自动压缩早期消息 ────────────
        if not self._use_local and len(messages) > 30:
            try:
                compress_model = "ollama/my-qwen"
                compress_base = "http://localhost:11434/v1"
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

        max_iterations = 10
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            # 确定 tool_choice
            tool_choice = "auto"
            if forced_tool and forced_tool in [t["function"]["name"] for t in all_tools]:
                tool_choice = {"type": "function", "function": {"name": forced_tool}}
            try:
                response = litellm.completion(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    tools=all_tools if all_tools else None,
                    tool_choice=tool_choice,
                    messages=messages,
                    api_key=self._api_key,
                    api_base=self._api_base,
                    timeout=30,
                )
            except Exception as e:
                return f"（API 调用失败：{e}）"

            choice = response.choices[0]
            # 捕获 COT 推理链（DeepSeek-R1 等推理模型）
            reasoning = getattr(choice.message, "reasoning_content", None)
            if reasoning:
                self._last_reasoning = reasoning

            if choice.finish_reason == "stop":
                return choice.message.content or "（莲心没有说话）"
            elif choice.finish_reason == "tool_calls":
                messages.append(choice.message)
                self._execute_tool_calls_parallel(
                    choice.message.tool_calls,
                    messages,
                    on_tool_call=on_tool_call,
                    on_tool_result=on_tool_result,
                )
                if forced_tool:
                    forced_tool = None
            else:
                return f"（意外停止: {choice.finish_reason}）"

        # 检查是否有观察记录产生
        try:
            from brain.observation_store import get_latest_chain_id, get_chain
            chain_id = get_latest_chain_id()
            if chain_id:
                records = get_chain(chain_id)
                if records:
                    lines = [f"探索被截断（达到最大调用次数），但已记录 {len(records)} 条观察："]
                    for r in records[-5:]:
                        lines.append(f"- {r['description'][:120]}")
                    return "\n".join(lines)
        except Exception:
            pass
        return "（达到最大工具调用次数，请重试）"
        

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
                    timeout=30,
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
            "，": ",", "“": '"', "”": '"',
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