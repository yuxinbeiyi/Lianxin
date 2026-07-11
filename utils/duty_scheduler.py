"""
DutyScheduler：统一后台职责调度器
- 用单一 60s master QTimer 替代 3 个独立 QTimer
- 每个 Duty 封装自己的设置读取、门控逻辑、Worker 构造
- 保持现有 Worker 类完全不变
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Callable

from PyQt5.QtCore import QObject, QTimer, pyqtSignal


# ═══════════════════════════════════════════════════════════════
# Data
# ═══════════════════════════════════════════════════════════════

@dataclass
class DutyStatus:
    name: str
    display_name: str
    enabled: bool = True
    is_running: bool = False
    last_fire_time: float = 0.0
    last_result: str = ""       # "success" | "skipped" | "failed" | ""
    last_result_text: str = ""
    run_count: int = 0
    success_count: int = 0
    fail_count: int = 0


@dataclass
class SchedulerState:
    now: float = 0.0
    paused: bool = False
    agent_busy: bool = False
    last_user_message_time: float = 0.0
    # references set by MainWindow
    proactive_scheduler: object = None
    reminder_manager: object = None
    global_settings: object = None
    heartbeat_config: dict = field(default_factory=dict)
    session_id: int = 0
    history_manager: object = None
    qq_bridge: object = None
    todo_manager: object = None
    agent: object = None
    chat_widget: object = None
    speak_func: Callable = None
    # observation helpers
    is_shoulder_available: Callable = None
    # proactive dialog reference for bilibili refresh
    proactive_dialog: object = None


# ═══════════════════════════════════════════════════════════════
# Abstract Base
# ═══════════════════════════════════════════════════════════════

class Duty(ABC):
    """单个后台职责的抽象基类。"""

    def __init__(self, name: str, display_name: str, tick_interval_seconds: int):
        self.name = name
        self.display_name = display_name
        self.tick_interval_seconds = tick_interval_seconds
        self._last_tick_time: float = 0.0
        self._worker = None
        self.status = DutyStatus(name=name, display_name=display_name)

    def on_tick(self, state: SchedulerState) -> bool:
        """主定时器回调。返回 True 表示本次有触发。"""
        self.status.enabled = self._check_enabled(state)
        if not self.status.enabled:
            return False
        if state.paused:
            return False
        elapsed = state.now - self._last_tick_time
        if elapsed < self.tick_interval_seconds:
            return False
        self._last_tick_time = state.now
        if self._should_fire(state):
            self._execute(state)
            return True
        return False

    def on_user_message(self, state: SchedulerState):
        """用户发送消息后的钩子（默认无操作）。"""

    def manual_trigger(self, state: SchedulerState, **kwargs):
        """调试触发，绕过所有门控。"""
        self._execute(state, **kwargs)

    # ── 子类必须实现 ──

    @abstractmethod
    def _check_enabled(self, state: SchedulerState) -> bool:
        """读取实时设置，判断是否启用。"""

    @abstractmethod
    def _should_fire(self, state: SchedulerState) -> bool:
        """判断此刻是否应执行。"""

    @abstractmethod
    def _create_worker(self, state: SchedulerState, **kwargs):
        """构造 QThread Worker 并返回。子类负责信号连接。"""

    # ── 内部 ──

    def _execute(self, state: SchedulerState, **kwargs):
        """执行职责：创建 Worker → 连接信号 → 启动。"""
        if self.status.is_running:
            return
        try:
            worker = self._create_worker(state, **kwargs)
            if worker is None:
                return
            self.status.is_running = True
            self.status.run_count += 1
            self.status.last_fire_time = state.now
            self._worker = worker
            self._wire_worker(worker)
            worker.start()
        except Exception:
            self.status.is_running = False

    @abstractmethod
    def _wire_worker(self, worker):
        """连接 Worker 信号到 Duty 的内部处理。"""


# ═══════════════════════════════════════════════════════════════
# DutyScheduler
# ═══════════════════════════════════════════════════════════════

class DutyScheduler(QObject):
    """统一后台职责调度器。"""

    # 结果信号（MainWindow 连接一次）
    proactive_response = pyqtSignal(str)              # message text
    proactive_error = pyqtSignal(str)                 # error text
    proactive_observation_text = pyqtSignal(str)      # observation description
    proactive_observation_image = pyqtSignal(str, str) # image_path, description

    slack_response = pyqtSignal(str)                  # message text
    slack_error = pyqtSignal(str)                     # error text

    heartbeat_response = pyqtSignal(str)              # reminder text
    heartbeat_silent = pyqtSignal()                   # nothing to report

    reminder_response = pyqtSignal(str)               # reminder text

    # 状态变化信号
    duty_started = pyqtSignal(str)                    # duty name
    duty_completed = pyqtSignal(str, str)             # duty name, result
    duty_failed = pyqtSignal(str, str)                # duty name, error
    status_changed = pyqtSignal(str, object)          # duty name, DutyStatus

    def __init__(self, parent=None):
        super().__init__(parent)
        self._duties: dict[str, Duty] = {}
        self._paused = False
        self._agent_busy = False
        self._last_user_message_time = 0.0

        self._master_timer = QTimer(self)
        self._master_timer.timeout.connect(self._tick)
        self._master_timer.setInterval(60_000)  # 60s

        # 状态引用（由 setup() 设置）
        self._proactive_scheduler = None
        self._reminder_manager = None
        self._global_settings = None
        self._session_id = 0
        self._history_manager = None
        self._qq_bridge = None
        self._todo_manager = None
        self._agent = None
        self._chat_widget = None
        self._speak_func = None
        self._is_shoulder_available = lambda: False
        self._proactive_dialog = None

    # ── 公开 API ──

    def setup(self, *, proactive_scheduler, reminder_manager, global_settings,
              session_id_func, history_manager_func, qq_bridge_func,
              todo_manager, agent, chat_widget, speak_func,
              is_shoulder_available=None, proactive_dialog=None):
        """设置调度器所需的外部引用。"""
        self._proactive_scheduler = proactive_scheduler
        self._reminder_manager = reminder_manager
        self._global_settings = global_settings
        self._session_id_func = session_id_func
        self._history_manager_func = history_manager_func
        self._qq_bridge_func = qq_bridge_func
        self._todo_manager = todo_manager
        self._agent = agent
        self._chat_widget = chat_widget
        self._speak_func = speak_func
        self._is_shoulder_available = is_shoulder_available or (lambda: False)
        self._proactive_dialog = proactive_dialog

    def register(self, duty: Duty):
        self._duties[duty.name] = duty

    def start(self):
        self._master_timer.start()

    def stop(self):
        self._master_timer.stop()
        for duty in self._duties.values():
            if duty._worker and duty._worker.isRunning():
                duty._worker.quit()
                duty._worker.wait(2000)

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def set_agent_busy(self, busy: bool):
        self._agent_busy = busy

    def on_user_message(self):
        self._last_user_message_time = time.monotonic()
        state = self._build_state()
        for duty in self._duties.values():
            duty.on_user_message(state)

    def get_all_statuses(self) -> list[DutyStatus]:
        return [d.status for d in self._duties.values()]

    def manual_trigger(self, name: str, **kwargs):
        duty = self._duties.get(name)
        if duty:
            state = self._build_state()
            duty.manual_trigger(state, **kwargs)

    # ── 内部 ──

    def _build_state(self) -> SchedulerState:
        return SchedulerState(
            now=time.monotonic(),
            paused=self._paused,
            agent_busy=self._agent_busy,
            last_user_message_time=self._last_user_message_time,
            proactive_scheduler=self._proactive_scheduler,
            reminder_manager=self._reminder_manager,
            global_settings=self._global_settings,
            heartbeat_config=self._get_heartbeat_config(),
            session_id=self._session_id_func() if self._session_id_func else 0,
            history_manager=self._history_manager_func() if self._history_manager_func else None,
            qq_bridge=self._qq_bridge_func() if self._qq_bridge_func else None,
            todo_manager=self._todo_manager,
            agent=self._agent,
            chat_widget=self._chat_widget,
            speak_func=self._speak_func,
            is_shoulder_available=self._is_shoulder_available,
            proactive_dialog=self._proactive_dialog,
        )

    @staticmethod
    def _get_heartbeat_config() -> dict:
        try:
            from config import get_heartbeat_config
            return get_heartbeat_config()
        except Exception:
            return {"enabled": True, "delay_minutes": 5,
                    "active_hours_start": "08:00", "active_hours_end": "23:00"}

    def _check_emotional_gate(self) -> bool:
        try:
            from brain.emotional import get_manager
            mgr = get_manager()
            if mgr.enabled and not mgr.proactive_allowed:
                return False
            return True
        except Exception:
            return True

    def _tick(self):
        state = self._build_state()
        for duty in self._duties.values():
            duty.on_tick(state)


# ═══════════════════════════════════════════════════════════════
# ProactiveDuty
# ═══════════════════════════════════════════════════════════════

class ProactiveDuty(Duty):
    """主动聊天 + 观察 + B站冲浪。"""

    def __init__(self):
        super().__init__("proactive", "主动聊天", tick_interval_seconds=300)

    def _check_enabled(self, state: SchedulerState) -> bool:
        ps = state.proactive_scheduler
        if ps is None:
            return False
        return ps.desktop_enabled or ps.qq_enabled

    def _should_fire(self, state: SchedulerState) -> bool:
        if state.agent_busy:
            return False
        ps = state.proactive_scheduler
        if ps is None:
            return False
        # 情感门控
        if not self._scheduler._check_emotional_gate():
            return False
        return ps.should_fire()

    def _create_worker(self, state: SchedulerState, **kwargs):
        from workers.proactive_worker import ProactiveWorker

        force_observe = kwargs.get("force_observe", "")
        ps = state.proactive_scheduler
        hm = state.history_manager

        if force_observe == "bilibili":
            worker = ProactiveWorker(hm, bilibili_mode=True)
        elif ps.bilibili_enabled and ps.should_surf_bilibili() and not force_observe:
            worker = ProactiveWorker(hm, bilibili_mode=True)
        else:
            observe_mode = force_observe or ps.should_observe()
            if observe_mode and state.is_shoulder_available():
                observe_mode = "shoulder_explore"
            last_obs = ps.get_last_observation()
            worker = ProactiveWorker(
                hm,
                observation_mode=observe_mode,
                last_observation=last_obs,
                camera_index=ps.camera_index,
                camera_wait=ps.camera_wait,
            )
        self._was_observation = (force_observe != "bilibili") and (not getattr(worker, '_bilibili_mode', False))
        return worker

    def _wire_worker(self, worker):
        scheduler = self._scheduler
        worker.response_ready.connect(self._on_response)
        worker.error_occurred.connect(self._on_error)
        worker.observation_text.connect(self._on_obs_text)
        worker.observation_image.connect(self._on_obs_image)

    def _on_response(self, text: str):
        self.status.is_running = False
        self.status.last_result = "success" if text else "skipped"
        self.status.success_count += 1
        self._scheduler.proactive_response.emit(text)

    def _on_error(self, err: str):
        self.status.is_running = False
        self.status.last_result = "failed"
        self.status.fail_count += 1
        self._scheduler.proactive_error.emit(err)

    def _on_obs_text(self, desc: str):
        self._scheduler.proactive_observation_text.emit(desc)

    def _on_obs_image(self, img_path: str, desc: str):
        self._scheduler.proactive_observation_image.emit(img_path, desc)

    # 子类需要访问 DutyScheduler —— 在 register 时注入
    @property
    def _scheduler(self):
        return self.__scheduler

    @_scheduler.setter
    def _scheduler(self, s):
        self.__scheduler = s


# ═══════════════════════════════════════════════════════════════
# SlackDuty
# ═══════════════════════════════════════════════════════════════

class SlackDuty(Duty):
    """摸鱼消息。仅在 ProactiveDuty 未触发时尝试。"""

    def __init__(self):
        super().__init__("slack", "摸鱼消息", tick_interval_seconds=300)

    def _check_enabled(self, state: SchedulerState) -> bool:
        ps = state.proactive_scheduler
        if ps is None:
            return False
        return ps._settings.get("slack_enabled", False)

    def _should_fire(self, state: SchedulerState) -> bool:
        if state.agent_busy:
            return False
        ps = state.proactive_scheduler
        if ps is None:
            return False
        if not self._scheduler._check_emotional_gate():
            return False
        # 仅在 proactive 未触发时尝试
        if ps.should_fire():
            return False
        return ps.should_slack_fire()

    def _create_worker(self, state: SchedulerState, **kwargs):
        from workers.slack_worker import SlackWorker
        force_action = kwargs.get("force_action", "")
        ps = state.proactive_scheduler
        action = force_action or ps.should_slack()
        if not action:
            return None
        context = self._build_context(action, state)
        self._current_action = action
        return SlackWorker(action, context)

    def _wire_worker(self, worker):
        worker.response_ready.connect(self._on_response)
        worker.error_occurred.connect(self._on_error)

    def _on_response(self, text: str):
        self.status.is_running = False
        self.status.last_result = "success"
        self.status.success_count += 1
        self._scheduler.slack_response.emit(text)

    def _on_error(self, err: str):
        self.status.is_running = False
        self.status.last_result = "failed"
        self.status.fail_count += 1
        self._scheduler.slack_error.emit(err)

    def _build_context(self, action: str, state: SchedulerState) -> str:
        """为摸鱼动作构建上下文（从 MainWindow._build_slack_context 迁移）。"""
        from datetime import datetime
        parts = []
        today = datetime.now().strftime("%Y-%m-%d")

        if action == "supplement_diary":
            try:
                from utils.diary import get_diary_by_date
                diary = get_diary_by_date(today)
                if diary:
                    parts.append(f"【今天的日记】\n{diary['content'][:500]}")
            except Exception:
                pass

        elif action == "review_old_diary":
            try:
                import random as _random
                from utils.diary import get_all_diaries
                diaries = get_all_diaries()
                if diaries:
                    old = _random.choice(diaries)
                    parts.append(f"【旧日记 - {old['date']}】\n{old['content'][:500]}")
            except Exception:
                pass

        elif action in ("search_old_topic", "random_question"):
            try:
                hm = state.history_manager
                if hm:
                    sessions = hm.get_sessions()
                    if sessions:
                        msgs = hm.get_messages(sessions[0]["id"])
                        recent = msgs[-30:] if len(msgs) > 30 else msgs
                        user_name = self._get_user_name()
                        lines = [f"{user_name if m['role'] == 'user' else '莲心'}：{m['content'][:200]}"
                                 for m in recent]
                        parts.append("【最近的对话】\n" + "\n".join(lines))
            except Exception:
                pass

        elif action == "remind_todo":
            try:
                tm = state.todo_manager
                if tm:
                    todos = tm.get_todos(completed=False)
                    if todos:
                        todo_lines = []
                        for t in todos[:5]:
                            if hasattr(t, 'due_date') and t.due_date:
                                todo_lines.append(f"- {t.title}（截止日期：{t.due_date}）")
                            else:
                                todo_lines.append(f"- {t.title}")
                        parts.append(f"【当前日期】{today}\n【未完成的待办】\n" + "\n".join(todo_lines))
            except Exception:
                pass

        elif action == "weather_chitchat":
            try:
                from config import get_qweather_config
                from brain.weather import get_user_city_from_memory, get_full_weather
                qw_cfg = get_qweather_config()
                api_key = qw_cfg.get("api_key", "").strip()
                if api_key:
                    city = get_user_city_from_memory()
                    if city:
                        weather_text = get_full_weather(city, api_key=api_key)
                        if weather_text and "错误" not in weather_text:
                            parts.append(f"【当前天气】\n{weather_text}")
            except Exception:
                pass

        elif action == "read_local_files":
            try:
                from utils.slack_utils import get_random_document
                doc = get_random_document()
                if doc:
                    parts.append(
                        f"【翻到的文件】\n文件名：{doc['name']}\n"
                        f"所在文件夹：{doc['folder']}\n大小：{doc['size_kb']} KB\n"
                        f"\n内容摘要：\n{doc['snippet']}"
                    )
            except Exception:
                pass

        elif action == "browser_history":
            try:
                from utils.slack_utils import get_browser_history_snippet
                history = get_browser_history_snippet()
                if history:
                    parts.append(f"【浏览器最近访问记录】\n{history}")
            except Exception:
                pass

        elif action in ("check_cpu_disk", "check_recycle_bin", "remind_rest",
                        "remind_water", "anniversary_remind", "next_song"):
            try:
                from utils.slack_utils import (
                    get_system_stats_snippet, get_recycle_bin_info,
                    get_rest_reminder_context, get_water_reminder_context,
                    get_anniversary_context, get_next_song_context,
                )
                builders = {
                    "check_cpu_disk": get_system_stats_snippet,
                    "check_recycle_bin": get_recycle_bin_info,
                    "remind_rest": get_rest_reminder_context,
                    "remind_water": get_water_reminder_context,
                    "anniversary_remind": get_anniversary_context,
                    "next_song": get_next_song_context,
                }
                fn = builders.get(action)
                if fn:
                    ctx = fn()
                    if ctx:
                        parts.append(ctx)
            except Exception:
                pass

        return "\n".join(parts)

    @staticmethod
    def _get_user_name() -> str:
        try:
            from utils.settings import get_settings
            return get_settings().user_name
        except Exception:
            return "主人"

    @property
    def _scheduler(self):
        return self.__scheduler

    @_scheduler.setter
    def _scheduler(self, s):
        self.__scheduler = s


# ═══════════════════════════════════════════════════════════════
# HeartbeatDuty
# ═══════════════════════════════════════════════════════════════

class HeartbeatDuty(Duty):
    """心跳自检：用户沉默 N 分钟后触发。"""

    def __init__(self):
        super().__init__("heartbeat", "心跳自检", tick_interval_seconds=60)
        self._reset_time: float = 0.0
        self._fired_since_reset = False

    def on_user_message(self, state: SchedulerState):
        self._reset_time = state.now
        self._fired_since_reset = False

    def _check_enabled(self, state: SchedulerState) -> bool:
        cfg = state.heartbeat_config
        return cfg.get("enabled", True)

    def _should_fire(self, state: SchedulerState) -> bool:
        if self._fired_since_reset:
            return False
        if self._reset_time == 0.0:
            return False
        cfg = state.heartbeat_config
        delay_minutes = cfg.get("delay_minutes", 5)
        elapsed_minutes = (state.now - self._reset_time) / 60.0
        if elapsed_minutes < delay_minutes:
            return False
        # 活跃时段检查
        from datetime import datetime
        now_str = datetime.now().strftime("%H:%M")
        start = cfg.get("active_hours_start", "08:00")
        end = cfg.get("active_hours_end", "23:00")
        if not (start <= now_str <= end):
            return False
        return True

    def _create_worker(self, state: SchedulerState, **kwargs):
        from workers.heartbeat_worker import HeartbeatWorker
        self._fired_since_reset = True
        return HeartbeatWorker(state.session_id)

    def _wire_worker(self, worker):
        worker.response_ready.connect(self._on_response)
        worker.finished_silent.connect(self._on_silent)

    def _on_response(self, text: str):
        self.status.is_running = False
        self.status.last_result = "success"
        self.status.success_count += 1
        self._scheduler.heartbeat_response.emit(text)

    def _on_silent(self):
        self.status.is_running = False
        self.status.last_result = "skipped"
        self._scheduler.heartbeat_silent.emit()

    @property
    def _scheduler(self):
        return self.__scheduler

    @_scheduler.setter
    def _scheduler(self, s):
        self.__scheduler = s


# ═══════════════════════════════════════════════════════════════
# SmartReminderDuty
# ═══════════════════════════════════════════════════════════════

class SmartReminderDuty(Duty):
    """智能提醒：1 分钟轮询到期的提醒。"""

    def __init__(self):
        super().__init__("smart_reminder", "智能提醒", tick_interval_seconds=60)
        self._deferred_reminders = None
        self._defer_timer: Optional[QTimer] = None

    def _check_enabled(self, state: SchedulerState) -> bool:
        return True  # 始终轮询，_should_fire 检查是否有到期提醒

    def _should_fire(self, state: SchedulerState) -> bool:
        if state.agent_busy:
            # 推迟到 agent 空闲时
            return False
        rm = state.reminder_manager
        if rm is None:
            return False
        due = rm.get_due_reminders()
        if not due:
            return False
        # 标记已触发（持久化到文件，避免重复提醒）
        for d in due:
            rm.mark_triggered(d["id"])
        # 构建提醒文本
        names = [d.get("name", d.get("title", "")) for d in due]
        self._pending_names = names
        return True

    def _create_worker(self, state: SchedulerState, **kwargs):
        from workers.smart_reminder_worker import SmartReminderWorker
        names = self._pending_names
        self._pending_names = []
        gs = state.global_settings
        use_smart = getattr(gs, 'global_smart_reminder', False) if gs else False
        if use_smart:
            combined = "、".join(names)
            return SmartReminderWorker(combined, is_combined=(len(names) > 1))
        else:
            # 不使用智能提醒，直接用模板
            return None  # 不需要 worker, _on_no_worker_needed 处理

    def _on_no_worker_needed(self):
        """不使用 LLM 生成时直接用模板文本。"""
        names = self._pending_names
        self._pending_names = []
        if len(names) == 1:
            text = f"⏰ 莲心提醒：{names[0]}（记得抽空完成哦）"
        else:
            text = f"⏰ 莲心提醒：有{len(names)}个事情需要你注意哦～"
        self.status.is_running = False
        self.status.last_result = "success"
        self.status.success_count += 1
        self._scheduler.reminder_response.emit(text)

    def _wire_worker(self, worker):
        worker.finished.connect(self._on_finished)

    def _on_finished(self, text: str):
        self.status.is_running = False
        self.status.last_result = "success"
        self.status.success_count += 1
        self._scheduler.reminder_response.emit(text)

    @property
    def _scheduler(self):
        return self.__scheduler

    @_scheduler.setter
    def _scheduler(self, s):
        self.__scheduler = s


# ═══════════════════════════════════════════════════════════════
# Registration helper
# ═══════════════════════════════════════════════════════════════

def _inject_scheduler(duty: Duty, scheduler: DutyScheduler):
    """注入 DutyScheduler 引用到 Duty，使其能发射信号。"""
    # 使用私有属性（见各 Duty 的 _scheduler property）
    duty._DutyScheduler_ref = scheduler


# 扩展 register 方法
def register_duty(scheduler: DutyScheduler, duty: Duty):
    duty._scheduler = scheduler
    scheduler.register(duty)