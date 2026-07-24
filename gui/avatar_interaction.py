"""头像拍一拍互动：独立于正常聊天队列的轻量异步控制器。"""
import random
import time
from datetime import datetime
from PyQt5.QtCore import QObject, QThread, pyqtSignal

from config import get_chat_avatar_config


_FALLBACKS = [
    "你是不是又开始摸鱼了？怎么突然拍我？",
    "拍完就想跑？这一下我可记住了。",
    "呦，这不是雨心博士吗？今天怎么突然想起拍我了？",
    "谁允许你摸我头的……不过这次先算了。",
    "我刚才还在认真想事情，差点被你拍散了。",
    "嗯，这一下收到了。你今天心情还好吗？",
]

_HEADPAT_FALLBACKS = [
    "嗯……轻一点嘛，不过这次就原谅你了。",
    "被你摸到了。今天可以稍微陪你久一点。",
    "好啦好啦，摸完记得继续陪我说话。",
]


class AvatarInteractionWorker(QThread):
    response_ready = pyqtSignal(str)
    failed = pyqtSignal()

    def __init__(self, agent, prompt, parent=None):
        super().__init__(parent)
        self.agent = agent
        self.prompt = prompt

    def run(self):
        # 拍一拍不写入正常会话，但必须走真实 LLM 链路。部分网关会把
        # API 错误包装成普通字符串，因此不能只判断返回值是否为空。
        try:
            from brain.agent import AgentCore

            class _EphemeralHistory:
                def update_title(self, *args, **kwargs):
                    return None
                def save_message(self, *args, **kwargs):
                    return 0
                def get_latest_compression_snapshot(self, *args, **kwargs):
                    return None

            last_error = None
            for attempt in range(1, 4):
                try:
                    isolated = AgentCore(
                        disable_tools=True,
                        track_emotion=False,
                        owner_scope=False,
                        source_channel="avatar_interaction",
                    )
                    isolated.history = []
                    isolated._session_titled = True
                    isolated._conversation_summary = ""
                    isolated._history_mgr = _EphemeralHistory()
                    nonce = int(time.time() * 1000) % 1000000
                    prompt = (
                        f"{self.prompt}\n本次互动编号：{nonce}。"
                        "请结合当前情境重新组织措辞，不要复用常见固定台词。"
                    )
                    text = (isolated.chat(prompt, disable_tools=True) or "").strip()
                    lowered = text.lower()
                    error_markers = (
                        "api", "调用失败", "请求失败", "服务异常", "网络异常",
                        "no user query", "authenticationerror", "connection slots",
                    )
                    if text and not any(marker in lowered for marker in error_markers):
                        print(f"[拍一拍] LLM 动态回应成功 attempt={attempt}, len={len(text)}", flush=True)
                        self.response_ready.emit(text[:180])
                        return
                    last_error = text or "LLM 返回空文本"
                    print(f"[拍一拍] LLM 未生成有效文本 attempt={attempt}: {last_error}", flush=True)
                except Exception as exc:
                    last_error = exc
                    print(f"[拍一拍] LLM 调用异常 attempt={attempt}: {exc}", flush=True)
                if attempt < 3:
                    time.sleep(0.8 * attempt)
            print(f"[拍一拍] 动态回复最终失败，转入备用回应: {last_error}", flush=True)
        except Exception as exc:
            print(f"[拍一拍] 动态回复初始化失败，转入备用回应: {exc}", flush=True)
        self.failed.emit()


class AvatarInteractionController(QObject):
    thinking_started = pyqtSignal(str)
    response_ready = pyqtSignal(str, bool)  # text, 是否反拍
    interaction_blocked = pyqtSignal(str)
    interaction_accepted = pyqtSignal(str, str, str)  # action, target, source

    def __init__(self, agent, stats, parent=None):
        super().__init__(parent)
        self.agent = agent
        self.stats = stats
        self._worker = None
        self._busy = False
        self._last_trigger_ms = 0
        self._tap_streak = 0
        self._last_tap_at = 0.0
        self._cooldown_seconds = float(get_chat_avatar_config().get("tap_cooldown_seconds", 1.5) or 1.5)
        self._recent_events = []
        self._last_action = "tap"
        self._last_source = "user"
        self._fallback_used = False

    def _time_context(self):
        hour = datetime.now().hour
        if hour >= 23 or hour < 6:
            return "深夜"
        today = datetime.now().strftime("%m-%d")
        try:
            if self.stats.get_first_meet_date() == datetime.now().strftime("%Y-%m-%d"):
                return "相识纪念日"
        except Exception:
            pass
        solar = {"01-01": "元旦", "02-14": "情人节", "05-20": "特别日期",
                 "10-01": "国庆节", "12-25": "圣诞节"}
        return solar.get(today, "普通日期")

    def _remember_event(self, action, actor, target, source):
        now = time.time()
        self._recent_events.append({
            "at": now, "action": action, "actor": actor,
            "target": target, "source": source,
            "context": self._time_context(), "streak": self._tap_streak,
        })
        self._recent_events = [e for e in self._recent_events if now - e["at"] <= 300][-5:]

    def recent_context(self):
        """返回给下一轮正常聊天的短期互动上下文。"""
        now = time.time()
        self._recent_events = [e for e in self._recent_events if now - e["at"] <= 300]
        if not self._recent_events:
            return ""
        lines = []
        for event in self._recent_events[-3:]:
            actor = "用户" if event["actor"] == "user" else "莲心"
            target = "用户" if event["target"] == "user" else "莲心"
            action = "拍了拍" if event["action"] == "tap" else "摸了摸"
            lines.append(f"{actor}{action}{target}（{event['context']}，连续第{event['streak']}次）")
        return (
            "【最近头像互动】\n" + "；".join(lines) +
            "。如果用户提到刚才的互动，请自然承认并延续，不要否认动作，也不要讨论自己是否有实体身体。"
        )

    def _emotion_context(self):
        values = {}
        try:
            from brain.emotional import get_manager
            state = get_manager().state
            values = {
                "情绪基调": round(float(state.valence), 2),
                "唤醒度": round(float(state.arousal), 2),
                "骄傲": round(float(state.pride), 2),
                "防御感": round(float(state.guardedness), 2),
                "连接需求": round(float(state.connection), 2),
                "沉浸度": round(float(state.immersion), 2),
                "信任": round(float(state.trust), 2),
                "亲密度": round(float(state.intimacy), 2),
            }
        except Exception:
            pass
        try:
            from brain.persona.runtime import active_assistant_name
            values["当前人格名称"] = active_assistant_name()
        except Exception:
            values["当前人格名称"] = "莲心"
        try:
            values["上一轮情绪标签"] = str(getattr(self.agent, "_last_emotion", "") or "默认")
        except Exception:
            pass
        return values

    def _counter_probability(self, context):
        probability = 0.28
        probability += max(0.0, context.get("亲密度", 0.5) - 0.5) * 0.45
        probability += max(0.0, context.get("情绪基调", 0.0)) * 0.12
        probability -= max(0.0, context.get("防御感", 0.0) - 0.35) * 0.28
        probability += min(0.18, max(0, self._tap_streak - 1) * 0.06)
        if self._time_context() == "深夜":
            probability -= 0.08
        elif self._time_context() in ("相识纪念日", "元旦", "情人节", "特别日期", "国庆节", "圣诞节"):
            probability += 0.08
        return max(0.08, min(0.68, probability))

    def trigger(self, role="assistant", action="tap", source="user"):
        cfg = get_chat_avatar_config()
        if not cfg.get("interactions_enabled", True):
            self.interaction_blocked.emit("头像互动已在设置中关闭")
            return False
        if role not in ("assistant", "user"):
            return False
        self._last_role = role
        now_ms = time.monotonic() * 1000
        if self._last_trigger_ms and now_ms - self._last_trigger_ms < self._cooldown_seconds * 1000:
            self.interaction_blocked.emit("互动冷却中，请稍等一下")
            return False
        # 使用单实例忙碌门控，避免连续双击堆积多个模型请求。
        if self._busy:
            self.interaction_blocked.emit("莲心正在想刚才这一拍怎么回应")
            return False
        now = time.monotonic()
        if now - self._last_tap_at > 8:
            self._tap_streak = 0
        self._tap_streak += 1
        self._last_tap_at = now
        self._busy = True
        self._last_trigger_ms = now_ms
        self._last_action = action
        self._last_source = source
        target = role
        actor = "user" if source == "user" else "assistant"
        interaction_type = "user_tap" if action == "tap" and actor == "user" and target == "assistant" else (
            "user_self_tap" if action == "tap" and target == "user" and actor == "user" else (
                "assistant_tap_user" if action == "tap" else (
                    "user_headpat" if actor == "user" else "assistant_headpat_user")))
        self._remember_event(action, actor, "user" if target == "user" else "assistant", source)
        self.stats.record_avatar_detail(
            interaction_type, actor=actor, target="user" if target == "user" else "assistant",
            source=source, reaction=action, streak=self._tap_streak,
            context={"time": self._time_context()})
        self.interaction_accepted.emit(action, target, source)
        print(f"[拍一拍] 互动开始 role={role}, dynamic={cfg.get('dynamic_response', True)}", flush=True)
        self.thinking_started.emit(random.choice([
            "莲心揉了揉刚才被拍的地方……",
            "莲心正在决定要不要反击……",
            "莲心想了一下该怎么回应你……",
        ]))
        context = self._emotion_context()
        if action == "headpat" and source == "assistant":
            action_text = "你刚刚主动温柔地摸了摸用户的头像。"
        elif action == "headpat":
            action_text = "用户刚刚温柔地摸了摸你的头像。"
        elif source == "assistant":
            action_text = "你刚刚主动拍了拍用户的头像。"
        else:
            action_text = "用户刚刚双击拍了拍你的头像。" if role == "assistant" else "用户刚刚双击拍了拍自己的头像。"
        prompt = (
            f"{action_text}请以莲心当前的人格自然回应这件事，"
            "只回复1到2句口语化短句，可以吐槽、撒娇、害羞、反击或关心。"
            "不要提到系统、模型、提示词、事件日志，不要调用工具，不要输出标签，"
            "不要重复固定句式。\n"
            f"互动动作：{action}；当前时间语境：{self._time_context()}。\n"
            f"当前拍击连续次数：{self._tap_streak}\n"
            f"当前情绪与关系数据：{context}\n"
            "这些数据只用于调整语气，不要在回复中直接复述数值。"
        )
        if not cfg.get("dynamic_response", True):
            self._fallback_used = True
            choices = _HEADPAT_FALLBACKS if action == "headpat" else _FALLBACKS
            self._finish(random.choice(choices))
            return True
        self._fallback_used = False
        self._worker = AvatarInteractionWorker(self.agent, prompt, self)
        self._worker.response_ready.connect(self._finish)
        self._worker.failed.connect(self._finish_fallback)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()
        return True

    def _finish_fallback(self):
        self._fallback_used = True
        choices = _HEADPAT_FALLBACKS if self._last_action == "headpat" else _FALLBACKS
        self._finish(random.choice(choices))

    def _finish(self, text):
        if not self._busy:
            return
        cfg = get_chat_avatar_config()
        context = self._emotion_context()
        counter = self._last_action == "tap" and self._last_role == "assistant" and bool(cfg.get("counter_tap", True)) and random.random() < self._counter_probability(context)
        # 用户拍自己的头像时，不触发莲心的反拍动作。
        if getattr(self, "_last_role", "assistant") == "user":
            counter = False
        if counter:
            self.stats.record_avatar_detail(
                "counter_tap", actor="assistant", target="user", source="counter",
                reaction="counter", streak=self._tap_streak,
                context={"time": self._time_context()})
        self._busy = False
        try:
            self.stats.record_avatar_outcome(llm=not self._fallback_used, fallback=self._fallback_used)
        except Exception:
            pass
        print(f"[拍一拍] 动态回应完成 counter_tap={counter}, len={len(text.strip())}", flush=True)
        choices = _HEADPAT_FALLBACKS if self._last_action == "headpat" else _FALLBACKS
        self.response_ready.emit(text.strip() or random.choice(choices), counter)
        self._worker = None

    def trigger_outbound(self, action="tap"):
        """莲心主动对用户头像执行动作。"""
        return self.trigger(role="user", action=action, source="assistant")

    def trigger_headpat(self, role="assistant", source="user"):
        return self.trigger(role=role, action="headpat", source=source)
