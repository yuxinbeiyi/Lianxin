"""
AgentCore：莲心AI 的大脑（DeepSeek API + Function Calling）
使用 openai SDK 连接 DeepSeek，接口完全兼容 OpenAI 规范。
"""

import json
import re
import threading
from datetime import datetime
from openai import OpenAI
from config import get_api_config, get_base_prompt, get_local_base_prompt, get_qq_bridge_config, get_qq_timing_config, get_memory_config
from brain.tools import TOOL_DEFINITIONS, execute_tool, set_cross_session_context
from brain.skill_manager import get_active_tool_definitions, get_active_knowledge
from brain.memory_store import (
    add as _memory_add,
    build_extraction_prompt,
    ALL_CATEGORIES,
)
from memory.history_manager import HistoryManager
from pathlib import Path

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


class AgentCore:
    def __init__(self, session_id: int = None, user_desc: str = None, disable_tools: bool = False):
        # 每次实例化都从文件读取最新配置，支持热重载
        cfg = get_api_config()
        self._use_local = cfg.get("use_local", False)
        if self._use_local:
            self._model      = cfg.get("local_model_name", "my-deepseek")
            self._max_tokens = min(cfg["max_tokens"], 2048)
            self.client = OpenAI(
                api_key="ollama",
                base_url=cfg.get("local_base_url", "http://localhost:11434/v1"),
            )
        else:
            self._model      = cfg["model"]
            self._max_tokens = cfg["max_tokens"]
            self.client = OpenAI(
                api_key=cfg["api_key"],
                base_url=cfg["base_url"],
            )
        self._disable_tools = disable_tools
        self._last_emotion = None     # 本轮回复的情绪标签（供 GUI 选图用）
        self._last_raw_response = None  # 本轮回复原始文本（含标签）
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

        return display_response  # 返回干净文本，不含标签

    def _trigger_auto_extraction(self):
        """在后台线程中自动提取记忆（不阻塞对话）。本地模型跳过（不擅长 JSON 格式化输出）。"""
        if self._use_local:
            return
        start_idx = self._last_extraction_idx
        recent = self.history[start_idx:]
        if len(recent) < 3:
            return

        def _do_extract():
            try:
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

                prompt = build_extraction_prompt(text)
                response = self.client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system",
                         "content": "你是一个专业的记忆提取助手，从对话中提取值得长期记住的信息。"},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
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

        # 肩载外设能力说明
        peripheral_block = """

【你的物理外设 — 肩载摄像头】
雨心给你装上了"眼睛"——一个肩载摄像头（ESP32-CAM + OV2640），通过 WiFi 连接。

硬件能力：
1. 摄像头（OV2640）：可以拍照看世界，VGA 分辨率（640×480）
2. 云台舵机（Pan/Tilt）：水平 0~180°（90=正前方），垂直 0~180°（90=水平）
3. DHT11 温湿度传感器：读取当前环境的温度和湿度
4. 一个白色补光灯（GPIO33 控制，但主要是上电指示用）

使用场景：
• 用户问「看看周围/有什么/我在干嘛」→ 先调 shoulder_pan/tilt 摆好角度 → 调 shoulder_photo 拍照 → 调 describe_image 描述画面
• 用户问「左边/右边有什么」→ shoulder_pan 转到对应方向 → shoulder_photo → describe_image
• 用户问「温度/湿度/热不热」→ shoulder_temp
• 主动想看看雨心在做什么 → 拍一张看看
• 云台复位 → shoulder_center
• 查看设备状态和 WiFi 信号 → shoulder_status

注意：拍照后如果需要看内容，必须调 describe_image 或 ocr_image 来分析画面，因为你看不到图片本身。
"""

        # 组合完整 prompt（本地模式不加外设说明和复杂规则）
        if self._use_local:
            full_prompt = f"{base_prompt}\n\n{time_block}"
        else:
            full_prompt = f"{base_prompt}\n\n{time_block}{peripheral_block}"

        return full_prompt

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
                response = self.client.chat.completions.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    messages=messages,
                    timeout=30,
                )
            except Exception as e:
                return f"（API 调用失败：{e}）"
            return response.choices[0].message.content or "（莲心没有说话）"

        # ── 长期记忆说明（仅在走工具路径时注入） ────────────
        messages.append({
            "role": "system",
            "content": (
                "【关于你的长期记忆】\n"
                "你的长期记忆存储在 long_term.json 中，按分类组织，不会自动加载到 system prompt中。\n"
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
                "  5. 使用 list_memories 查看全部记忆内容"
            )
        })


        max_iterations = 10
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            # 确定 tool_choice
            tool_choice = "auto"
            if forced_tool and forced_tool in [t["function"]["name"] for t in all_tools]:
                tool_choice = {"type": "function", "function": {"name": forced_tool}}
            try:
                response = self.client.chat.completions.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    tools=all_tools,
                    tool_choice=tool_choice,
                    messages=messages,
                    timeout=30,
                )
            except Exception as e:
                return f"（API 调用失败：{e}）"

            choice = response.choices[0]

            if choice.finish_reason == "stop":
                return choice.message.content or "（莲心没有说话）"
            elif choice.finish_reason == "tool_calls":
                messages.append(choice.message)
                for tool_call in choice.message.tool_calls:
                    name = tool_call.function.name
                    try:
                        args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                    if on_tool_call:
                        on_tool_call(name, args)
                    set_cross_session_context(self._session_id, self._history_mgr)
                    result = execute_tool(name, args)
                    if on_tool_result:
                        on_tool_result(name, result)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })
                # 如果强制工具且已经调用过一次，可以在这里将 forced_tool 置为 None，避免后续循环强制
                # 但模型可能在一次 tool_calls 中调用多个工具，强制工具可能只是第一个。
                # 这里为简单起见，只在第一次调用后取消强制，让后续自由组合。
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
                response = self.client.chat.completions.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    messages=messages,
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