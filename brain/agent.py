"""
AgentCore：莲心AI 的大脑（LiteLLM 统一网关 + Function Calling）
使用 LiteLLM 统一接入 DeepSeek / Anthropic / Ollama 等多种模型。
"""

import json
import re
import time
import threading
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os as _os
_os.environ.setdefault("LITELLM_LOG", "ERROR")  # 抑制 litellm 导入时的 WARNING
import litellm
litellm.set_verbose = False
litellm.suppress_debug_info = True  # 关闭 "Give Feedback" stderr 输出
from config import (
    get_api_config, get_base_prompt, get_local_base_prompt,
    get_core_system_policy, get_user_name, get_qq_bridge_config,
    get_qq_timing_config, get_memory_config, get_graph_config,
)
from brain.tools import TOOL_DEFINITIONS, execute_tool, set_cross_session_context
from brain.skill_manager import get_active_tool_definitions, get_active_knowledge
from brain.tool_router import filter_builtin_tools, build_tool_catalog, match_categories, detect_tool_request, CATEGORY_ORDER
from brain.graph_memory import (
    build_extraction_prompt,
    ALL_CATEGORIES,
)
from brain.graph_memory import add_fact as _memory_add
from memory.history_manager import HistoryManager
from brain.context_compressor import (
    build_fallback_summary,
    compact_summary_text,
    compact_tool_result,
    contains_textual_tool_protocol,
    extract_input_tokens,
    format_messages_for_summary,
    memory_persistence_directive,
    merge_summaries_bounded,
    prune_stale_tool_outputs,
    select_history_window,
)
from pathlib import Path
from brain.mcp import get_all_mcp_tool_definitions


logger = logging.getLogger("Agent")

_RESPONSE_FORMAT_POLICY = """【重要 — 回复格式要求】
在每次回复的末尾，必须单独一行用【表情：XXX】输出当前情绪。这是硬性要求。
例如：「好的～今天天气真不错！【表情：开心】」

情绪只能从以下列表选择：
开心、伤心、好奇吃惊、夸奖害羞、生气不满、得意、默认、抱歉、开玩笑、思考认真、调用工具

如果情绪不在列表中，输出【表情：默认】。不要创造列表外的情绪。"""

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
_MEMORY_WRITE_TOOLS = {"save_memory", "update_memory"}

def _get_group_lock(group: str) -> threading.Lock:
    if group not in _resource_locks:
        with _resource_init_lock:
            if group not in _resource_locks:
                _resource_locks[group] = threading.Lock()
    return _resource_locks[group]


# ── Prompt 调试转储 ─────────────────────────────────────

def _dump_prompt_debug(messages: list, all_tools: list,
                       iteration: int, total_chars: int, tool_count: int):
    """将完整 prompt 转储到 logs/prompt_dump.json，便于排查模型收到的实际内容。
    每次覆盖写入，避免磁盘膨胀。
    """
    import json as _json
    from pathlib import Path as _Path
    dump_path = _Path(__file__).parent.parent / "logs" / "prompt_dump.json"
    dump_path.parent.mkdir(parents=True, exist_ok=True)

    # 工具摘要（只保留名称+描述，不输出完整 schema）
    tool_summary = []
    for t in all_tools:
        fn = t.get("function", {})
        tool_summary.append({
            "name": fn.get("name", "?"),
            "desc": (fn.get("description", "") or "")[:80],
        })

    dump = {
        "_meta": {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "iteration": iteration,
            "message_count": len(messages),
            "total_chars": total_chars,
            "tool_count": tool_count,
            "est_tokens": total_chars // 2,  # 粗估：中文约2字符/token
        },
        "tools": tool_summary,
        "messages": [],
    }

    for i, m in enumerate(messages):
        role = m.get("role", "?")
        content = m.get("content", "")
        # 截断过长内容
        display = content[:3000] + ("…[截断]" if len(content) > 3000 else "")
        dump["messages"].append({
            "index": i,
            "role": role,
            "chars": len(content),
            "content": display,
        })

    dump_path.write_text(_json.dumps(dump, ensure_ascii=False, indent=2),
                         encoding="utf-8")


class AgentCore:
    def __init__(self, session_id: int = None, user_desc: str = None,
                 disable_tools: bool = False, track_emotion: bool = True,
                 source_channel: str = "desktop", participant_id: str = "",
                 owner_scope: bool = True):
        
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
        else:  # deepseek / 自定义 OpenAI 兼容 API
            from config import normalize_model_for_litellm
            base_url = cfg.get("base_url", "https://api.deepseek.com")
            self._model      = normalize_model_for_litellm(cfg["model"], base_url)
            self._max_tokens = cfg["max_tokens"]
            self._api_base   = base_url
            self._api_key    = cfg["api_key"]

        self._disable_tools = disable_tools
        # 工具权限和情感跟踪是两个独立维度。纯聊天可以禁用工具，
        # 但仍应让问候、道歉、夸奖等真实互动影响情感状态。
        self._track_emotion = track_emotion
        self._source_channel = source_channel
        self._participant_id = str(participant_id)
        self._owner_scope = bool(owner_scope)
        self._last_emotion = None     # 本轮回复的情绪标签（供 GUI 选图用）
        self._last_raw_response = None  # 本轮回复原始文本（含标签）
        self._last_reasoning = None    # 本轮回复的 COT 推理链
        self._last_reply_time = None   # 上次回复时间（用于自适应时间精度缓存）
        # 对话历史（OpenAI messages 格式）

        # 对话历史（OpenAI messages 格式）
        self.history: list[dict] = []

        # 会话历史持久化
        self._history_mgr = HistoryManager()
        self._history_mgr.sync_legacy_channel_maps()
        self._last_reply_time = self._load_last_reply_time()


        # ── 自动记忆提取跟踪（从配置读取） ──────────────────
        self._extraction_counter = 0   # 对话轮次计数
        self._last_extraction_idx = 0  # history 中已提取到哪条消息
        self._extraction_inflight = False
        self._extraction_lock = threading.Lock()
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
            self._history_mgr.update_session_metadata(
                session_id, channel=source_channel,
                participant_id=self._participant_id, owner_scope=self._owner_scope,
            )
        else:
            # 非桌面端必须创建独立会话，禁止复用最后一个桌面会话。
            if source_channel != "desktop":
                self._session_id = self._history_mgr.new_session(
                    channel=source_channel, participant_id=self._participant_id,
                    owner_scope=self._owner_scope,
                )
                self._session_titled = False
            else:
                # 桌面端按最后活动时间恢复，而不是按 session id/创建时间恢复。
                qq_ids = _get_qq_session_ids()
                last_id = self._history_mgr.get_latest_session_id(
                    channel="desktop", owner_only=True,
                    exclude_session_ids=qq_ids,
                )
                if last_id is not None:
                    self._session_id = last_id
                    raw_msgs = self._history_mgr.get_messages(last_id)
                    self.history = [
                        {"role": m["role"], "content": m["content"]}
                        for m in raw_msgs
                    ]
                    self._session_titled = True
                else:
                    self._session_id = self._history_mgr.new_session(
                        channel="desktop", owner_scope=True,
                    )
                    self._session_titled = False

        # 已恢复的历史不应再次进入自动提取队列。
        self._last_extraction_idx = len(self.history)
        self._session_memory_writes_blocked = self._derive_memory_write_policy()
        self._request_memory_writes_blocked = self._session_memory_writes_blocked

        # 旧 Prompt 保留为人格系统关闭或故障时的一键回退路径。
        self._system_prompt = self._build_system_prompt_once()
        self._user_desc = user_desc or ""
        self._last_persona_key = None
        self._persona_transition_remaining = 0

        # ── 加载上一会话的压缩摘要 ──────────────────────────
        self._prev_session_summary = self._load_previous_session_summary()

        # ── 会话内滑动窗口摘要（Token 优化，仅云端模式生效） ──
        self._conversation_summary = ""
        self._summarized_history_idx = 0
        self._last_input_tokens = 0
        self._restore_context_snapshot()

        # ── 用户上下文：让 AI 知道当前在跟谁说话 ───────────────

        if self._user_desc:
            self._system_prompt += f"\n\n【当前对话对象】\n{self._user_desc}"

        # ── 情绪标签最终提醒（云端模式，放在 system prompt 最末尾） ──
        if not self._use_local:
            self._system_prompt += f"\n\n{_RESPONSE_FORMAT_POLICY}"

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
            on_progress=None,
            response_guard=None) -> str:
        """
        处理用户消息并返回 AI 回复。

        参数:
            disable_tools:     True 表示此轮不走工具调用，纯聊天模式。
            interrupt_queue:   queue.Queue | None，用户中途插话的消息队列。
            on_interrupt:      callable(msg) -> str，处理插话的 LLM 回调。
            on_progress:       callable(text)，报告进度回复的回调。
            response_guard:    callable() -> bool，False 时丢弃已过期回复且不写入历史。
        """
        # 用户明确拒绝长期记忆写入时，由代码层执行权限边界，而非仅依赖 Prompt。
        self._request_memory_writes_blocked = self._update_memory_write_policy(
            user_message
        )

        # 清除上次探索留存的观察数据，防止脏数据导致"探索被截断"误报
        try:
            from brain.observation_store import clear_latest_chain
            clear_latest_chain()
        except Exception:
            pass

        # 每轮请求只获取一次不可变人格快照。后续工具循环始终复用该快照，
        # 即使用户此时在界面切换人格，也只影响下一条新请求。
        persona_snapshot, persona_transition = self._prepare_persona_request()

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
                                                      on_round_start=on_round_start,
                                                      persona_snapshot=persona_snapshot,
                                                      persona_transition=persona_transition)


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

        # 跨线程渠道可在生成期间收到更新请求。旧回复不应进入对话历史，
        # 否则用户没看到的内容会污染下一轮上下文与记忆提取。
        if response_guard is not None and not response_guard():
            self._last_emotion = None
            self._last_raw_response = None
            return ""

        # ── 情感系统：分析本轮交互 ────────────────────────────
        if self._track_emotion:
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
        if self._request_memory_writes_blocked:
            # 防止用户稍后恢复写入后，自动提取器回头处理被明确排除的消息。
            self._last_extraction_idx = len(self.history)
        elif self._auto_extract:
            self._extraction_counter += 1
            if self._extraction_counter >= self._extract_interval:
                self._extraction_counter = 0
                self._trigger_auto_extraction()

        # ── Checklist 提取（后台执行，对话结束后回顾待办）────
        if not effective_disable and len(self.history) >= 4:
            self._trigger_checklist_extraction()

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
        with self._extraction_lock:
            if self._extraction_inflight:
                return
            start_idx = self._last_extraction_idx
            end_idx = len(self.history)
            recent = list(self.history[start_idx:end_idx])
            if len(recent) < 3:
                return
            self._extraction_inflight = True

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
                with self._extraction_lock:
                    self._last_extraction_idx = max(self._last_extraction_idx, end_idx)
                    self._extraction_inflight = False
                return

            classification_ok = False
            graph_ok = False
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
                        _memory_add(
                            content, cat, source="auto_extracted",
                            source_session_id=self._session_id,
                            source_channel=self._source_channel,
                        )
                        added += 1
                classification_ok = True
            except Exception:
                pass

            # ── 五元组图记忆提取（独立 try，失败不影响分类提取） ──
            if self._graph_enabled and self._auto_extract_quintuples:
                try:
                    from brain.quintuple_extractor import extract_and_store_with_config
                    extract_and_store_with_config(text, self._model, self._api_key, self._api_base)
                    graph_ok = True
                except Exception as e:
                    import logging
                    logging.getLogger("Agent").warning(f"五元组提取失败: {e}")

            with self._extraction_lock:
                graph_required = self._graph_enabled and self._auto_extract_quintuples
                if classification_ok and (not graph_required or graph_ok):
                    self._last_extraction_idx = max(self._last_extraction_idx, end_idx)
                self._extraction_inflight = False

        threading.Thread(target=_do_extract, daemon=True).start()

    def _trigger_checklist_extraction(self):
        """对话结束后在后台提取待办事项（借鉴 NagaAgent DogTag）。"""
        if self._use_local:
            return
        recent = self.history[-20:]
        lines = []
        for msg in recent:
            role = "用户" if msg.get("role") == "user" else "莲心"
            content = msg.get("content", "")
            if content and len(content) > 5:
                lines.append(f"[{role}]: {content[:300]}")
        if len(lines) < 4:
            return

        conversation_text = "\n".join(lines)

        try:
            from brain.checklist_extractor import run_checklist_async
            import brain.tools as _bt
            tm = getattr(_bt, '_todo_manager', None)
            cb = getattr(self, '_checklist_callback', None)
            run_checklist_async(
                conversation_text,
                api_key=self._api_key,
                api_base=self._api_base,
                model=self._model,
                todo_manager=tm,
                callback=cb,
            )
        except Exception:
            pass

    def clear_history(self):
        """清除当次会话的内存历史（数据库记录保留）。"""
        self.history = []
        self._conversation_summary = ""
        self._summarized_history_idx = 0
        self._last_input_tokens = 0
        self._last_persona_key = None
        self._persona_transition_remaining = 0
    def remove_message_by_content(self, content: str) -> bool:
        """从内存历史中删除匹配内容的消息。"""
        content = content.strip()
        for i, msg in enumerate(self.history):
            if msg.get("content", "").strip() == content:
                self.history.pop(i)
                if i < self._summarized_history_idx:
                    # 删除发生在已摘要范围内时，旧摘要已无法精确对应原历史。
                    self._conversation_summary = ""
                    self._summarized_history_idx = 0
                return True
        return False
    def new_session(self):
        """开启全新会话：重置内存历史，在数据库创建新 session。"""
        previous_session_id = self._session_id
        self.history = []
        self._session_id = self._history_mgr.new_session(
            channel=self._source_channel,
            participant_id=self._participant_id,
            owner_scope=self._owner_scope,
        )
        self._session_titled = False
        self._conversation_summary = ""
        self._summarized_history_idx = 0
        self._last_input_tokens = 0
        self._last_reply_time = None
        self._last_extraction_idx = 0
        self._prev_session_summary = self._build_session_handoff(previous_session_id)
        self._last_persona_key = None
        self._persona_transition_remaining = 0
        self._session_memory_writes_blocked = False
        self._request_memory_writes_blocked = False



    def get_history_manager(self) -> HistoryManager:
        """返回历史管理器（供 GUI 历史对话框使用）。"""
        return self._history_mgr

    def get_history_summary(self) -> str:
        rounds = len([m for m in self.history if m["role"] == "user"])
        return f"当前对话共 {rounds} 轮"

    def _derive_memory_write_policy(self) -> bool:
        """从已恢复历史中重建会话级长期记忆写入策略。"""
        blocked = False
        for message in self.history:
            if message.get("role") != "user":
                continue
            directive = memory_persistence_directive(message.get("content", ""))
            if directive == "block_session":
                blocked = True
            elif directive == "allow":
                blocked = False
        return blocked

    def _update_memory_write_policy(self, user_message: str) -> bool:
        directive = memory_persistence_directive(user_message)
        if directive == "allow":
            self._session_memory_writes_blocked = False
        elif directive == "block_session":
            self._session_memory_writes_blocked = True
        return bool(
            getattr(self, "_session_memory_writes_blocked", False)
            or directive == "block_request"
        )

    def _prepare_persona_request(self):
        """取得本轮快照，并生成最多持续两轮的隐藏人格过渡说明。"""
        try:
            from brain.persona import get_persona_manager
            snapshot = get_persona_manager().get_snapshot()
        except Exception as exc:
            logger.warning("读取人格快照失败，回退旧 Prompt: %s", exc)
            self._last_persona_key = None
            self._persona_transition_remaining = 0
            return None, ""

        if not snapshot.enabled:
            self._last_persona_key = None
            self._persona_transition_remaining = 0
            return snapshot, ""

        key = (snapshot.profile.id, snapshot.revision)
        if key != getattr(self, "_last_persona_key", None):
            has_old_reply = any(msg.get("role") == "assistant" for msg in self.history)
            self._persona_transition_remaining = 2 if has_old_reply else 0
            self._last_persona_key = key

        if getattr(self, "_persona_transition_remaining", 0) <= 0:
            return snapshot, ""

        first_round = self._persona_transition_remaining == 2
        self._persona_transition_remaining -= 1
        name = snapshot.profile.assistant_name
        if first_round:
            transition = (
                f"【人格切换 — 内部指令】\n当前人格已经切换为“{name}”。\n"
                "从本轮开始，以当前人格档案为身份与表达方式的最高依据。"
                "此前对话、会话摘要、跨端上下文和长期记忆只用于保留客观事实、任务进度与用户偏好；"
                "其中旧助手的名称、口头禅、语气、性格和行为方式均不再具有指导作用。"
                "不要主动向用户解释人格切换，除非用户明确询问。"
            )
        else:
            transition = (
                f"【人格切换强化 — 内部指令】\n继续严格使用“{name}”的人格设定。"
                "保留历史事实，但不要模仿旧人格的表达方式。"
            )
        return snapshot, transition

    def _build_request_system_messages(self, persona_snapshot):
        """为本轮构建 System 消息；禁用或异常时完整返回旧 Prompt。"""
        if persona_snapshot is None or not persona_snapshot.enabled:
            return [{"role": "system", "content": self._system_prompt}]

        try:
            from brain.persona import PersonaPromptComposer
            scene_parts = []
            if self._user_desc:
                scene_parts.append(f"【当前对话对象】\n{self._user_desc}")
            if not self._use_local:
                scene_parts.append(_RESPONSE_FORMAT_POLICY)
            compiled = PersonaPromptComposer.compose(
                persona_snapshot,
                user_name=get_user_name(),
                core_policy="" if self._use_local else get_core_system_policy(),
                scene_policy="\n\n".join(scene_parts),
            )
            return compiled.as_messages()
        except Exception as exc:
            logger.warning("编排人格 Prompt 失败，回退旧 Prompt: %s", exc)
            return [{"role": "system", "content": self._system_prompt}]

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
        """为新空会话加载最近活跃的同一用户会话交接信息。"""
        if not self._owner_scope:
            return None
        try:
            # 恢复已有会话时，其自身 history 已包含上下文，无需额外注入。
            if self.history:
                return None
            previous_id = self._history_mgr.get_latest_session_id(
                channel=self._source_channel, owner_only=self._owner_scope,
                exclude_session_ids={self._session_id},
            )
            if previous_id is None:
                return None
            return self._build_session_handoff(previous_id)
        except Exception:
            return None

    def _build_session_handoff(self, session_id: int) -> str | None:
        """构建带真实时间和来源的轻量会话交接上下文。"""
        session = self._history_mgr.get_session(session_id)
        if not session:
            return None
        summary = (session.get("summary") or "").strip()
        msgs = self._history_mgr.get_messages(session_id, limit=12)
        if not summary and not msgs:
            return None
        lines = [
            "【上一段会话交接】",
            f"来源：{session.get('channel', 'desktop')}；最后活动：{session.get('updated_at', '')}",
        ]
        if summary:
            lines.append(f"摘要：{summary}")
        for msg in msgs[-6:]:
            speaker = "用户" if msg.get("role") == "user" else "莲心"
            content = (msg.get("content") or "").strip()[:240]
            if content:
                lines.append(f"[{msg.get('timestamp', '')} {speaker}] {content}")
        lines.append("以上仅用于承接最近会话；涉及更早内容时应查询会话历史。")
        return "\n".join(lines)

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

            # 自动承接只使用近期跨端记录；更早内容由显式历史搜索处理。
            last_timestamp = msgs[-1].get("timestamp", "")
            try:
                last_dt = datetime.strptime(last_timestamp, "%Y-%m-%d %H:%M:%S")
                if (datetime.now() - last_dt).days >= 7:
                    return None
            except (TypeError, ValueError):
                return None

            lines = []
            for m in msgs:
                speaker = "你" if m["role"] == "assistant" else "用户"
                content = m["content"][:200]
                lines.append(f"[{m.get('timestamp', '')}] {speaker}：{content}")

            print(f"[跨端记忆] ✓ {source_name} session_id={target_id}，注入 {len(msgs)} 条")
            return (
                f"【以下是你和用户在{source_name}最近的对话记录——这是实际发生过的对话，不是参考信息】\n"
                + "\n".join(lines)
                + f"\n【以上为{source_name}近期记录。请严格依据时间判断新旧；用户未询问跨端内容时不要优先于当前端记录。】"
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
            if (getattr(self, "_request_memory_writes_blocked", False)
                    and name in _MEMORY_WRITE_TOOLS):
                result = "用户已明确禁止写入长期记忆，本次调用被代码层阻止。"
                print(f"  [权限边界] 已阻止长期记忆写入: {name}", flush=True)
                messages.append({
                    "role": "tool", "tool_call_id": tc.id, "content": result,
                })
                if on_tool_result:
                    on_tool_result(name, result, True, 0.0)
                continue
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
                continue
            # 跨轮次去重：同一工具+同一参数在整个循环中只能调用一次
            if call_key in self._loop_tool_call_history:
                print(f"  [去重] 跳过重复调用: {name}（参数与之前完全相同）", flush=True)
                messages.append({
                    "role": "tool", "tool_call_id": tc.id,
                    "content": (
                        f"⛔ 你已用完全相同的参数调用过 {name}，结果不会改变。"
                        "请换一种方法或工具，或者基于已有信息直接回复。"
                    ),
                })
                continue
            self._last_tool_call_key = call_key
            self._loop_tool_call_history.add(call_key)
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
        pool = ThreadPoolExecutor(max_workers=max_workers)
        futures = []
        try:
            # 无锁工具 → 线程池并发
            for item in lock_free:
                futures.append(pool.submit(_run_one, item))
            # 池兼容组（如 db_write）→ 线程池内组间并行、组内串行
            for grp, items in pool_groups.items():
                futures.append(pool.submit(_run_group, grp, items))

            TOOL_TIMEOUT = 120  # 单个工具最长执行 2 分钟
            for f in futures:
                try:
                    f.result(timeout=TOOL_TIMEOUT)
                except Exception as e:
                    print(f"[工具超时] {e}", flush=True)
        finally:
            pool.shutdown(wait=False)
        # 线程亲和组 → 调用线程上逐组串行（池已关闭，调用线程空闲）
        for grp in _THREAD_AFFINE_GROUPS:
            items = groups.get(grp)
            if items:
                _run_group(grp, items)

        # ── 第四遍：结果注入 messages（保持原始顺序）────────
        for i, item in enumerate(parsed):
            result = results[i]
            if result is not None:
                cfg = get_memory_config()
                messages.append({
                    "role": "tool",
                    "tool_call_id": item["tc"].id,
                    "content": compact_tool_result(
                        result, cfg.get("tool_result_max_chars", 12_000)
                    ),
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
                    input_tokens = extract_input_tokens(getattr(chunk, "usage", None))
                    if input_tokens:
                        self._last_input_tokens = input_tokens
                    choices = getattr(chunk, "choices", None)
                    if not choices:
                        continue
                    delta = choices[0].delta

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
                    fr = getattr(choices[0], "finish_reason", None)
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

    def _restore_context_snapshot(self) -> None:
        """恢复当前会话的最近压缩快照；不可信游标会被安全忽略。"""
        try:
            snapshot = self._history_mgr.get_latest_compression_snapshot(
                self._session_id
            )
            if not snapshot:
                return
            covered = int(snapshot.get("covered_message_count", 0))
            summary = str(snapshot.get("summary", "")).strip()
            if not summary or covered <= 0 or covered > len(self.history):
                logger.warning(
                    "忽略无效上下文快照: session=%s covered=%s history=%s",
                    self._session_id, covered, len(self.history),
                )
                return
            max_chars = get_memory_config().get("context_summary_max_chars", 4_000)
            self._conversation_summary = compact_summary_text(summary, max_chars)
            self._summarized_history_idx = covered
            logger.info("已恢复上下文快照: %s 条消息", covered)
            print(
                f"[上下文快照] 已恢复: session={self._session_id}, "
                f"覆盖{covered}条, 摘要{len(self._conversation_summary)}字",
                flush=True,
            )
        except Exception as exc:
            logger.warning("恢复上下文快照失败，使用完整历史: %s", exc)

    def _apply_history_window(self, persona_snapshot=None):
        """应用完整 turn 边界、实际 token 触发和可恢复的增量摘要。"""
        cfg = get_memory_config()
        history = self.history
        if not cfg.get("enable_conversation_summary", True):
            return None, list(history)

        covered = min(
            max(0, int(getattr(self, "_summarized_history_idx", 0))),
            len(history),
        )
        selection = select_history_window(
            history,
            keep_turns=cfg.get("context_keep_loops", 8),
            trigger_turns=cfg.get("context_summary_trigger", 12),
            last_input_tokens=getattr(self, "_last_input_tokens", 0),
            token_threshold=cfg.get("context_summary_token_threshold", 80_000),
            force=bool(self._conversation_summary and covered),
        )
        if not selection.should_compress and not self._conversation_summary:
            return None, list(history)

        target_covered = max(covered, selection.covered_message_count)
        pending = history[covered:target_covered]
        batch_size = max(1, int(cfg.get("context_summary_batch_messages", 6)))
        summary_max_chars = cfg.get("context_summary_max_chars", 4_000)

        # 未积累到安全批次时不推进游标，原消息继续进入 prompt。
        if len(pending) >= batch_size:
            chunk_summary = self._generate_history_summary(pending)
            if not chunk_summary:
                chunk_summary = build_fallback_summary(
                    pending, max_chars=summary_max_chars
                )
            if self._conversation_summary:
                self._conversation_summary = self._merge_summaries(
                    self._conversation_summary, chunk_summary
                )
            else:
                self._conversation_summary = chunk_summary
            self._summarized_history_idx = target_covered
            covered = target_covered

            try:
                profile = getattr(persona_snapshot, "profile", None)
                snapshot_id = self._history_mgr.save_compression_snapshot(
                    self._session_id,
                    self._conversation_summary,
                    covered,
                    covered_user_turns=sum(
                        1 for m in history[:covered] if m.get("role") == "user"
                    ),
                    model=self._model,
                    persona_id=getattr(profile, "id", ""),
                    persona_revision=getattr(persona_snapshot, "revision", 0),
                    trigger=selection.trigger,
                    input_tokens=getattr(self, "_last_input_tokens", 0),
                )
                print(
                    f"[上下文快照] 已保存: id={snapshot_id}, "
                    f"覆盖{covered}条, 摘要{len(self._conversation_summary)}字, "
                    f"触发={selection.trigger}",
                    flush=True,
                )
            except Exception as exc:
                logger.warning("保存上下文快照失败（本轮摘要仍可用）: %s", exc)

        summary = None
        if self._conversation_summary:
            summary = (
                f"【对话历史摘要 — 前 {covered} 条消息已压缩】\n"
                f"{self._conversation_summary}"
            )
        return summary, list(history[covered:])

    def _stream_summary_text(self, messages: list[dict], max_tokens: int = 500) -> str | None:
        """使用与主聊天相同的流式协议获取摘要正文，但不覆盖聊天 token 统计。"""
        response = litellm.completion(
            model=self._model,
            max_tokens=max_tokens,
            messages=messages,
            api_key=self._api_key,
            api_base=self._api_base,
            stream=True,
            timeout=30,
        )
        parts: list[str] = []
        for chunk in response:
            choices = (
                chunk.get("choices") if isinstance(chunk, dict)
                else getattr(chunk, "choices", None)
            )
            if not choices:
                continue
            choice = choices[0]
            delta = (
                choice.get("delta") if isinstance(choice, dict)
                else getattr(choice, "delta", None)
            )
            if delta is None:
                continue
            content = (
                delta.get("content") if isinstance(delta, dict)
                else getattr(delta, "content", None)
            )
            if content:
                parts.append(str(content))
        result = "".join(parts).strip()
        return result or None

    def _generate_history_summary(self, history_chunk: list[dict]) -> str | None:
        """将一段对话历史压缩为简洁摘要（调用 LLM）。"""
        transcript = format_messages_for_summary(history_chunk)
        if not transcript:
            return None

        max_chars = get_memory_config().get("context_summary_max_chars", 4_000)

        try:
            result = self._stream_summary_text(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是一个对话摘要助手。将以下对话压缩为一段简洁摘要（200字以内）。"
                            "只保留：讨论主题、已确认事实、用户偏好、重要决策、"
                            "进行中任务、未解决问题和必要的情绪状态。"
                            "摘要必须人格中立，不继承助手名称、口头禅、语气或人设。"
                            "省略无信息量的寒暄，用第三人称叙述。"
                        ),
                    },
                    {"role": "user", "content": transcript},
                ]
            )
            if result:
                result = compact_summary_text(result, max_chars)
                print(
                    f"[上下文摘要] 模型摘要成功: {len(history_chunk)}条 → {len(result)}字",
                    flush=True,
                )
                return result
            print("[上下文摘要] 模型未返回正文，启用确定性降级", flush=True)
            return None
        except Exception as exc:
            logger.warning("生成历史摘要失败，将使用确定性降级摘要: %s", exc)
            print(f"[上下文摘要] 生成失败，启用确定性降级: {exc}", flush=True)
            return None

    def _merge_summaries(self, old_summary: str, new_summary: str) -> str:
        """将新旧两段摘要合并为一段（调用 LLM）。"""
        max_chars = get_memory_config().get("context_summary_max_chars", 4_000)
        try:
            result = self._stream_summary_text(
                [
                    {
                        "role": "system",
                        "content": (
                            "将以下两段对话摘要合并为一段简洁摘要（400字以内），去重。"
                            "保留已确认事实、用户偏好、决策、待办和未解决问题；"
                            "保持人格中立，不继承助手的名称、语气或口头禅。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"旧摘要：\n{old_summary}\n\n新摘要：\n{new_summary}",
                    },
                ]
            )
            if result:
                result = compact_summary_text(result, max_chars)
                print(f"[上下文摘要] 滚动合并成功: {len(result)}字", flush=True)
                return result
            print("[上下文摘要] 合并未返回正文，使用有界降级", flush=True)
        except Exception as exc:
            logger.warning("合并历史摘要失败，使用有界降级: %s", exc)
            print(f"[上下文摘要] 合并失败，使用有界降级: {exc}", flush=True)
        return merge_summaries_bounded(old_summary, new_summary, max_chars)


    def _function_calling_loop(self, on_tool_call=None, on_tool_result=None, forced_tool: str = None,
                               disable_tools: bool = False,
                               interrupt_queue=None, on_interrupt=None,
                               on_progress=None, user_message: str = "",
                               on_round_start=None, persona_snapshot=None,
                               persona_transition: str = "") -> str:

       
        _t0 = time.time()
        messages = self._build_request_system_messages(persona_snapshot)
        _text_protocol_retry_count = 0

        def _guarded_progress(text: str):
            """流式阶段即阻止内部工具协议进入界面。"""
            if not on_progress:
                return
            stripped = str(text or "").lstrip()
            if stripped.startswith("<") or contains_textual_tool_protocol(text):
                return
            on_progress(text)

        # ── 注入实时时间信息（自适应精度：间隔>15分钟用分钟级，否则小时级） ──
        messages.append(self._build_realtime_message())

        current_user_turns = sum(1 for m in self.history if m.get("role") == "user")
        if self._prev_session_summary and current_user_turns <= 4:
            messages.append({"role": "system", "content": self._prev_session_summary})

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
                    if persona_snapshot is not None and persona_snapshot.enabled:
                        _emotion_snippet += (
                            "\n情感只能在当前激活人格允许的表达范围内体现；"
                            "不得改变当前人格的身份、语言风格或行为边界。"
                        )
                    messages.append({"role": "system", "content": _emotion_snippet})
            except Exception:
                pass

        # 注入跨端记忆上下文（有则加，无则忽略；本地模式跳过）
        if not self._use_local:
            cross_ctx = self._get_cross_session_context()
            if cross_ctx:
                messages.append({"role": "system", "content": cross_ctx})

        # ── 注入 System Prompt 技能模块（渐进式披露） ──
        # 必须在对话历史之前注入，避免 AI 误认为用户消息附带了技能说明书
        last_user_msg = ""
        if not self._use_local:
            for msg in reversed(self.history):
                if msg.get("role") == "user":
                    last_user_msg = msg.get("content", "")
                    break
            if last_user_msg:
                try:
                    from skills._提示词指南 import get_matching_modules
                    modules = get_matching_modules(last_user_msg)
                    if modules:
                        messages.append({"role": "system", "content": modules})
                except Exception:
                    pass

        # ── 技能知识注入：分层设计 ──
        # 第一层（始终注入）：紧凑摘要，LLM 知道有哪些能力但不烧 token
        # 第二层（按需注入）：用户消息匹配关键词时才注入完整 SKILL.md
        try:
            from brain.skill_manager import get_active_skill_summary, get_matching_knowledge
            summary = get_active_skill_summary()
            if summary:
                messages.append({"role": "system", "content": (
                    "【你的能力清单 — 严格保密，禁止主动提及】\n"
                    "以下是你的后台能力摘要，仅供判断是否需要调用工具时查阅。\n"
                    "⚠️ 禁止在对话中主动提起这些能力名称，除非用户明确要求。\n\n"
                    + summary
                )})
            # 按需注入完整知识
            _msg_for_match = last_user_msg if last_user_msg else user_message
            full_knowledge = get_matching_knowledge(_msg_for_match)
            if full_knowledge:
                messages.append({"role": "system", "content": (
                    "【相关能力详细说明】\n"
                    "用户当前话题与你以下能力相关，请参考详细说明来正确使用工具：\n\n"
                    + full_knowledge
                )})
        except Exception:
            pass

        # ── 记忆 RAG 注入：向量检索相关长期记忆 ──
        if not self._use_local:
            try:
                from brain.memory_rag import search_similar, format_rag_context
                memories = search_similar(
                    last_user_msg if last_user_msg else user_message,
                    top_k=3, threshold=0.5
                )
                if memories:
                    rag_text = format_rag_context(memories)
                    messages.append({"role": "system", "content": rag_text})
            except Exception:
                pass

            # ── 图谱发现自动注入：遍历"用户"节点，发现关联实体和关系 ──
            try:
                from brain.graph_memory import get_graph_summary_for_user
                graph_summary = get_graph_summary_for_user(depth=2)
                if graph_summary:
                    messages.append({"role": "system", "content": graph_summary})
            except Exception:
                pass

        # 人格过渡提示放在所有事实型上下文之后、历史消息之前，利用近因效应
        # 阻断旧名称、旧口头禅和旧表达方式对新人格的模仿诱导。
        if persona_transition:
            messages.append({"role": "system", "content": persona_transition})

        # ── 对话历史：云端模式滑动窗口 + 摘要压缩 ──────
        # 必须在所有 system 注入之后，确保用户消息是最后一条非 system 消息
        if self._use_local:
            messages.extend(self.history[-20:])
        else:
            summary_text, recent_history = self._apply_history_window(persona_snapshot)
            if summary_text:
                messages.append({"role": "system", "content": summary_text})
            messages.extend(recent_history)

        # ── 工具按需注入：核心常驻 + 领域匹配 + 目录摘要 ──
        if self._use_local:
            all_tools = []
            loaded_categories = set()
        else:
            skill_tools = get_active_tool_definitions()
            mcp_tools = get_all_mcp_tool_definitions()

            # 按用户消息关键词匹配领域
            _msg_for_match = last_user_msg if last_user_msg else user_message
            loaded_categories = match_categories(_msg_for_match)

            # 筛选内置工具：核心 + 命中领域
            filtered_builtin = filter_builtin_tools(TOOL_DEFINITIONS, _msg_for_match)
            # 技能/MCP 工具按需注入（不默认加载，模型主动点名后才注入）
            all_tools = filtered_builtin

            # 用户禁用的工具过滤
            from config import get_builtin_tool_config
            builtin_cfg = get_builtin_tool_config()
            disabled_tool_names = {name for name, enabled in builtin_cfg.items() if not enabled}
            runtime_disabled_names = set(disabled_tool_names)
            if getattr(self, "_request_memory_writes_blocked", False):
                runtime_disabled_names.update(_MEMORY_WRITE_TOOLS)
            if runtime_disabled_names:
                all_tools = [
                    t for t in all_tools
                    if t.get("function", {}).get("name", "") not in runtime_disabled_names
                ]

            # 注入工具目录（技能/MCP 标为 📋，模型主动点名后才注入）
            _skill_names = [t.get("function", {}).get("name", "?") for t in skill_tools]
            _mcp_names = [t.get("function", {}).get("name", "?") for t in mcp_tools]
            catalog_text = build_tool_catalog(
                loaded_categories,
                skill_tool_names=_skill_names if _skill_names else None,
                mcp_tool_names=_mcp_names if _mcp_names else None,
                disabled_tool_names=runtime_disabled_names,
            )
            messages.append({"role": "system", "content": catalog_text})


        # ── 长期记忆说明（必须在对话历史之前注入） ────────────
        if getattr(self, "_request_memory_writes_blocked", False):
            messages.append({
                "role": "system",
                "content": (
                    "【长期记忆权限】用户已明确禁止向长期记忆写入内容。"
                    "本轮不得调用 save_memory 或 update_memory；"
                    "可以正常使用当前会话上下文回答。"
                ),
            })
        else:
            messages.append({
                "role": "system",
                "content": (
                    "【长期记忆】\n"
                    "相关记忆已自动注入上方消息中，你无需主动搜索。\n"
                    "仅在用户明确说\"你还记得XXX吗\"\"我之前说过XXX\"\"帮我查一下记忆\"时才调用 search_graph_memory。\n"
                    "用户说\"记住XXX\"时调用 save_memory 保存。"
                )
            })

        # ── 防幻觉提醒（最后一条 system 消息，利用近因效应） ──
        if not disable_tools:
            messages.append({
                "role": "system",
                "content": (
                    "【本轮铁律】收到文件查找/搜索/系统操作类请求时，"
                    "必须先调用工具获取真实结果再回复。禁止凭猜测编造任何文件名、路径或数据。"
                )
            })

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
                    if contains_textual_tool_protocol(content):
                        print("[协议防泄漏] 纯文本模式检测到伪工具调用，已拦截", flush=True)
                        if retry < 1:
                            messages.append({
                                "role": "system",
                                "content": (
                                    "上一条输出包含内部工具调用标签，已被系统丢弃。"
                                    "当前禁止调用工具；只用自然语言回答用户，"
                                    "不得输出任何 tool_call、function 或 parameter 标签。"
                                ),
                            })
                            continue
                        return "（检测到异常的内部工具协议，已阻止其显示。请重新发送消息。）"
                    self._last_reasoning = reasoning if reasoning else None
                    return content or "（莲心没有说话）"
                except Exception as e:
                    if retry < 1:
                        import time as _time
                        _time.sleep(1.5)
                        continue
                    return f"（API 调用失败：{e}）"


        MAX_ITERATIONS = 20          # 绝对安全上限，正常不会触发
        SOFT_LIMIT = 8               # 第N轮：让模型自评估进度
        URGENT_LIMIT = 15            # 第N轮：强制收尾提示（必须在3轮内完成）
        TODO_CHECK_INTERVAL = 6      # 每N轮检查一次进度
        DEAD_LOOP_THRESHOLD = 3      # 连续相同结果N次判定为死循环

        iteration = 0
        last_round_summaries: list[str] = []   # 最近N轮工具结果摘要
        last_round_fingerprints: list[str] = []  # 最近N轮工具调用指纹（只对比调用，不受结果变化干扰）
        _full_tools_injected = False           # 防止工具激活无限重试
        _soft_limit_triggered = False          # 自评估提示只发一次
        _urgent_limit_triggered = False        # 收尾提示只发一次

        # ── 三层熔断器状态 ──
        _content_drought_count = 0           # 连续无文本回复计数
        _same_tool_streak_name = None        # 当前连续同工具名
        _same_tool_streak_count = 0          # 连续同工具计数
        _last_round_tool_sets: list[str] = []  # 最近N轮的工具名集合
        _force_text_response = False         # 下一轮强制 tool_choice="none"
        self._loop_tool_call_history: set = set()  # 本循环中所有 (工具名, 参数序列化) 的集合
        CONTENT_DROUGHT_MAX = 3              # 连续无文本N轮→熔断
        SAME_TOOL_STORM_MAX = 3              # 同工具连续N轮→强制干预
        NO_PROGRESS_MAX = 3                  # 工具名集合连续相同N轮→熔断
        SEARCH_FATIGUE_MAX = 4               # 连续搜索/读取N轮→强制收尾

        _search_fatigue_count = 0            # 连续搜索轮计数
        _SEARCH_READ_TOOLS = {
            "search_files_everything", "search_graph_memory", "search_conversation_history",
            "search_cross_session",
            "search_code", "glob_files", "list_directory",
            "read_file", "read_file_chunk", "read_file_lines",
            "get_file_info_everything", "grep_file", "web_search",
        }

        # ── 复杂度判断：用户消息超过80字视为复杂任务 ──
        is_complex = len(self.history[-1]["content"]) > 80 if self.history else False

        while iteration < MAX_ITERATIONS:
            iteration += 1
            _prompt_build_started = _t0 if iteration == 1 else time.time()

            if self._cancel_event.is_set():
                print("  [循环终止] 收到取消信号", flush=True)
                return "（任务已被取消）"

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

            # ── 分层收尾提示（动态评估，不硬截断） ──
            # 第8轮：让模型自评估是否需要继续
            if iteration >= SOFT_LIMIT and not _soft_limit_triggered:
                _soft_limit_triggered = True
                messages.append({
                    "role": "system",
                    "content": (
                        "【进度评估 — 第{iteration}轮】\n"
                        "你已经执行了{iteration}轮工具调用。请判断：\n"
                        "- 当前任务还需要几轮才能完成？如果接近完成，请直接给出最终回答。\n"
                        "- 如果确实还需要更多轮次，请继续调用工具，但尽量高效推进。"
                    ).format(iteration=iteration),
                })
            # 第15轮：强制收尾
            if iteration >= URGENT_LIMIT and not _urgent_limit_triggered:
                _urgent_limit_triggered = True
                messages.append({
                    "role": "system",
                    "content": (
                        "【收尾提示 — 第{iteration}轮】\n"
                        "已接近最大工具调用次数({max_iter}轮)。\n"
                        "请必须在3轮内完成当前任务，基于已有信息给出最终回答。\n"
                        "不要再调用非必需工具，用最精炼的方式总结即可。"
                    ).format(iteration=iteration, max_iter=MAX_ITERATIONS),
                })
            # 最后3轮：强制收尾（与旧逻辑兼容）
            elif iteration >= MAX_ITERATIONS - 3 and not _urgent_limit_triggered:
                messages.append({
                    "role": "system",
                    "content": (
                        "已接近最大工具调用次数上限。"
                        "请立刻基于已有信息给出最终回答，不要再调用工具。"
                        "如果内容较多，用最精炼的方式总结即可，不要展开长篇大论。"
                    ),
                })


            # 确定 tool_choice（熔断器可强制设为 "none"）
            forcing_text_response = bool(_force_text_response)
            if forcing_text_response:
                tool_choice = "none"
                _force_text_response = False
            elif forced_tool and forced_tool in [t["function"]["name"] for t in all_tools]:
                tool_choice = {"type": "function", "function": {"name": forced_tool}}
            else:
                tool_choice = "auto"

            # 同一请求中的旧工具结果会快速膨胀；只压缩 content，保留调用配对。
            _tool_cfg = get_memory_config()
            messages = prune_stale_tool_outputs(
                messages,
                keep_recent=_tool_cfg.get("tool_result_keep_recent", 4),
                latest_max_chars=_tool_cfg.get("tool_result_max_chars", 12_000),
                stale_max_chars=_tool_cfg.get("stale_tool_result_max_chars", 2_400),
            )

            # 诊断：打印 system prompt 构建耗时和大小
            _t1 = time.time()
            _total_chars = sum(len(m.get("content", "")) for m in messages)
            _tool_count = len(all_tools)
            print(f"[诊断] 第{iteration}轮 prompt 构建: {_t1 - _prompt_build_started:.1f}s, "
                  f"{len(messages)}条消息, {_total_chars}字符, {_tool_count}个工具", flush=True)

            # ── Prompt 调试转储 ──
            try:
                from config import get_debug_config
                if get_debug_config().get("dump_prompt", False):
                    _dump_prompt_debug(messages, all_tools, iteration,
                                       _total_chars, _tool_count)
            except Exception:
                pass

            try:
                _api_start = time.time()
                print("  [等待] 正在等待 API 响应...", flush=True)
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
                content, reasoning, stream_tool_calls, finish = self._collect_stream(
                    stream, on_chunk=_guarded_progress
                )
                _api_elapsed = time.time() - _api_start
                _content_len = len(content) if content else 0
                print(f"[诊断] 第{iteration}轮 API 完成: {_api_elapsed:.1f}s, "
                      f"回复{_content_len}字, finish={finish}", flush=True)
            except Exception as e:
                error_msg = str(e).lower()
                is_retryable = any(kw in error_msg for kw in [
                    "timeout", "connection", "getaddrinfo", "name or service not known",
                    "rate limit", "server", "500", "502", "503", "504",
                    "connection reset", "broken pipe", "eof",
                ])
                if is_retryable and iteration < 3:
                    if self._cancel_event.is_set():
                        print(f"[API重试] 第{iteration}轮收到取消信号，终止重试", flush=True)
                        return "（响应超时，任务已取消。请重新发送消息。）"
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
                if contains_textual_tool_protocol(content):
                    _text_protocol_retry_count += 1
                    print(
                        "[协议防泄漏] 检测到正文伪工具调用，已丢弃并请求安全收尾",
                        flush=True,
                    )
                    if _text_protocol_retry_count <= 1:
                        _force_text_response = True
                        messages.append({
                            "role": "system",
                            "content": (
                                "【协议纠错】上一条输出把工具调用写成了普通文本，"
                                "该内容已被系统丢弃且不会执行。工具调用阶段已经结束。"
                                "现在必须仅根据已有工具结果生成最终自然语言回答；"
                                "禁止输出 <tool_call>、<function>、<parameter>、JSON调用或代码块。"
                            ),
                        })
                        continue
                    return (
                        "（工具结果已经取得，但模型连续输出了异常的内部调用协议。"
                        "系统已阻止其显示，请让我重新总结现有结果。）"
                    )
                # 工具激活重试：模型暗示需要未加载的工具（仅触发一次）
                if (not self._use_local and not _full_tools_injected
                        and detect_tool_request(content or "")):
                    _full_tools_injected = True
                    print("[工具激活] 检测到模型需要未激活工具，全量注入重试", flush=True)
                    loaded_categories = set(CATEGORY_ORDER)  # 全部激活
                    all_tools = TOOL_DEFINITIONS + skill_tools + mcp_tools
                    if runtime_disabled_names:
                        all_tools = [t for t in all_tools
                                     if t.get("function", {}).get("name", "") not in runtime_disabled_names]
                    # 替换最后一条目录消息为全量激活版（技能/MCP 也标 ✅）
                    catalog_text = build_tool_catalog(
                        loaded_categories,
                        skill_tool_names=_skill_names if _skill_names else None,
                        mcp_tool_names=_mcp_names if _mcp_names else None,
                        disabled_tool_names=runtime_disabled_names,
                        skill_mcp_active=True,
                    )
                    for i in range(len(messages) - 1, -1, -1):
                        if messages[i].get("content", "").startswith("【工具目录】"):
                            messages[i] = {"role": "system", "content": catalog_text}
                            break
                    continue
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

                # ── 死循环检测（结果对比） ────────────
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

                # ── 死循环检测（调用指纹对比） ──────────
                # 对比工具调用指纹而非结果文本，避免 get_current_time 等时间变化工具干扰
                _round_fingerprint = "|".join(sorted(
                    f"{tc.function.name}({tc.function.arguments})"
                    for tc in fake_tool_calls
                ))
                last_round_fingerprints.append(_round_fingerprint)
                if len(last_round_fingerprints) > DEAD_LOOP_THRESHOLD:
                    last_round_fingerprints.pop(0)

                _dead_loop_by_result = (
                    len(last_round_summaries) >= DEAD_LOOP_THRESHOLD
                    and last_round_summaries[0]
                    and len(set(last_round_summaries)) == 1
                )
                _dead_loop_by_fingerprint = (
                    len(last_round_fingerprints) >= DEAD_LOOP_THRESHOLD
                    and _round_fingerprint
                    and len(set(last_round_fingerprints)) == 1
                )

                if _dead_loop_by_result or _dead_loop_by_fingerprint:
                    _reason = "连续相同结果" if _dead_loop_by_result else "连续相同工具调用"
                    print(f"  [死循环检测] {_reason}，连续{DEAD_LOOP_THRESHOLD}轮，强制终止",
                          flush=True)
                    _force_text_response = True
                    messages.append({
                        "role": "system",
                        "content": (
                            "检测到连续多轮返回相同结果，判定为死循环。"
                            "下一轮你必须停止调用工具，基于已有信息直接给出最终回答。"
                        ),
                    })

                # ── 三层熔断器检测 ──────────────────────
                _has_content = bool(content and content.strip())

                if not _has_content:
                    _content_drought_count += 1
                else:
                    _content_drought_count = 0

                _this_tool_names = sorted(tc.function.name for tc in fake_tool_calls)
                if _this_tool_names:
                    _first_tool = _this_tool_names[0]
                    if _first_tool == _same_tool_streak_name:
                        _same_tool_streak_count += 1
                    else:
                        _same_tool_streak_name = _first_tool
                        _same_tool_streak_count = 1

                _tool_set_key = "|".join(_this_tool_names)
                _last_round_tool_sets.append(_tool_set_key)
                if len(_last_round_tool_sets) > NO_PROGRESS_MAX:
                    _last_round_tool_sets.pop(0)
                _no_progress = (
                    len(_last_round_tool_sets) >= NO_PROGRESS_MAX
                    and _tool_set_key
                    and len(set(_last_round_tool_sets)) == 1
                )

                _breaker_reason = ""

                # ── 搜索疲劳检测：连续多轮全部是搜索/读取类工具 ──
                _all_search_read = (
                    _this_tool_names
                    and all(t in _SEARCH_READ_TOOLS for t in _this_tool_names)
                )
                if _all_search_read:
                    _search_fatigue_count += 1
                else:
                    _search_fatigue_count = 0

                if _content_drought_count >= CONTENT_DROUGHT_MAX:
                    _breaker_reason = f"连续{CONTENT_DROUGHT_MAX}轮无文本回复"
                    _content_drought_count = 0
                elif _same_tool_streak_count >= SAME_TOOL_STORM_MAX:
                    _breaker_reason = f"同一工具 [{_same_tool_streak_name}] 连续调用{_same_tool_streak_count}轮"
                    _same_tool_streak_count = 0
                elif _no_progress:
                    _breaker_reason = f"连续{NO_PROGRESS_MAX}轮工具集合无变化"
                    _last_round_tool_sets.clear()
                    _same_tool_streak_count = 0
                elif _search_fatigue_count >= SEARCH_FATIGUE_MAX:
                    _breaker_reason = f"连续{SEARCH_FATIGUE_MAX}轮都在搜索/读取，无实质产出"
                    _search_fatigue_count = 0

                if _breaker_reason:
                    print(f"  [熔断器] {_breaker_reason}，下一轮强制 tool_choice=none", flush=True)
                    _force_text_response = True
                    messages.append({
                        "role": "system",
                        "content": (
                            f"检测到{_breaker_reason}，判定为陷入循环。"
                            "下一轮你必须停止调用工具，基于已有信息直接给出最终回答。"
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
