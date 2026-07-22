"""头像拍一拍互动：独立于正常聊天队列的轻量异步控制器。"""
import random
import time
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


class AvatarInteractionWorker(QThread):
    response_ready = pyqtSignal(str)
    failed = pyqtSignal()

    def __init__(self, agent, prompt, parent=None):
        super().__init__(parent)
        self.agent = agent
        self.prompt = prompt

    def run(self):
        try:
            # 复用莲心完整 AgentCore 链路：人格、情绪提示、流式请求和内置重试。
            # 使用隔离的临时历史管理器，拍一拍不会写入正常聊天历史。
            from brain.agent import AgentCore

            class _EphemeralHistory:
                def update_title(self, *args, **kwargs):
                    return None
                def save_message(self, *args, **kwargs):
                    return 0
                def get_latest_compression_snapshot(self, *args, **kwargs):
                    return None

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
            text = isolated.chat(self.prompt, disable_tools=True)
            text = (text or "").strip()
            if text:
                self.response_ready.emit(text[:180])
                return
        except Exception as exc:
            print(f"[拍一拍] 动态回复请求失败，使用备用回应: {exc}", flush=True)
        self.failed.emit()


class AvatarInteractionController(QObject):
    thinking_started = pyqtSignal(str)
    response_ready = pyqtSignal(str, bool)  # text, 是否反拍
    interaction_blocked = pyqtSignal(str)

    def __init__(self, agent, stats, parent=None):
        super().__init__(parent)
        self.agent = agent
        self.stats = stats
        self._worker = None
        self._busy = False
        self._last_trigger_ms = 0
        self._tap_streak = 0
        self._last_tap_at = 0.0

    def _emotion_context(self):
        values = {}
        try:
            from brain.emotional import get_manager
            state = get_manager().state
            values = {
                "情绪基调": round(float(state.valence), 2),
                "唤醒度": round(float(state.arousal), 2),
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
        return max(0.08, min(0.68, probability))

    def trigger(self, role="assistant"):
        cfg = get_chat_avatar_config()
        if not cfg.get("interactions_enabled", True):
            self.interaction_blocked.emit("头像互动已在设置中关闭")
            return
        if role not in ("assistant", "user"):
            return
        self._last_role = role
        now = time.monotonic()
        if now - self._last_tap_at > 8:
            self._tap_streak = 0
        self._tap_streak += 1
        self._last_tap_at = now
        # 使用单实例忙碌门控，避免连续双击堆积多个模型请求。
        if self._busy:
            self.interaction_blocked.emit("莲心正在想刚才这一拍怎么回应")
            return
        self._busy = True
        interaction_type = "user_tap" if role == "assistant" else "user_self_tap"
        self.stats.record_avatar_interaction(interaction_type, "tap" if role == "assistant" else "self_tap")
        print(f"[拍一拍] 互动开始 role={role}, dynamic={cfg.get('dynamic_response', True)}", flush=True)
        self.thinking_started.emit(random.choice([
            "莲心揉了揉刚才被拍的地方……",
            "莲心正在决定要不要反击……",
            "莲心想了一下该怎么回应你……",
        ]))
        context = self._emotion_context()
        action_text = "用户刚刚双击拍了拍你的头像。" if role == "assistant" else "用户刚刚双击拍了拍自己的头像。"
        prompt = (
            f"{action_text}请以莲心当前的人格自然回应这件事，"
            "只回复1到2句口语化短句，可以吐槽、撒娇、害羞、反击或关心。"
            "不要提到系统、模型、提示词、事件日志，不要调用工具，不要输出标签，"
            "不要重复固定句式。\n"
            f"当前拍击连续次数：{self._tap_streak}\n"
            f"当前情绪与关系数据：{context}\n"
            "这些数据只用于调整语气，不要在回复中直接复述数值。"
        )
        if not cfg.get("dynamic_response", True):
            self._finish(random.choice(_FALLBACKS))
            return
        self._worker = AvatarInteractionWorker(self.agent, prompt, self)
        self._worker.response_ready.connect(self._finish)
        self._worker.failed.connect(lambda: self._finish(random.choice(_FALLBACKS)))
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _finish(self, text):
        if not self._busy:
            return
        cfg = get_chat_avatar_config()
        context = self._emotion_context()
        counter = bool(cfg.get("counter_tap", True)) and random.random() < self._counter_probability(context)
        # 用户拍自己的头像时，不触发莲心的反拍动作。
        if getattr(self, "_last_role", "assistant") == "user":
            counter = False
        if counter:
            self.stats.record_avatar_interaction("counter_tap", "counter")
        self._busy = False
        print(f"[拍一拍] 动态回应完成 counter_tap={counter}, len={len(text.strip())}", flush=True)
        self.response_ready.emit(text.strip() or random.choice(_FALLBACKS), counter)
        self._worker = None
