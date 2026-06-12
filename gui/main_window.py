"""
MainWindow：莲心AI 主窗口（Phase 4 — 含语音输入/输出）
"""

import webbrowser
import os
import ctypes
from ctypes import wintypes
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QMessageBox,QDialog,QTextEdit
)
from PyQt5.QtCore import Qt, QTimer, QAbstractNativeEventFilter
from PyQt5.QtGui import QFont
from pathlib import Path
from brain.agent import AgentCore
from utils.emotion_manager import parse_emotion_tag as _strip_emotion_tag
from voice.listener import VoiceListener
from voice.speaker  import VoiceSpeaker
from gui.character_widget import CharacterWidget
from gui.chat_widget       import ChatWidget
from gui.input_panel       import InputPanel
from gui.history_dialog    import HistoryDialog
from gui.proactive_dialog  import ProactiveDialog
from gui.settings_dialog   import SettingsDialog
from gui.pomodoro_dialog   import PomodoroDialog
from gui.api_config_dialog import ApiConfigDialog
from gui.alarm_dialog      import AlarmDialog
from gui.qq_settings_dialog import QqSettingsDialog
from gui.network_settings_dialog import NetworkSettingsDialog
from gui.capability_center import CapabilityCenter

from config import has_api_key, get_qq_bridge_config, get_heartbeat_config
from brain.decision import decide
from workers.agent_worker      import AgentWorker
from workers.voice_worker      import VoiceWorker, ModelLoader
from workers.speaker_worker    import SpeakerWorker
from workers.proactive_worker  import ProactiveWorker
from workers.heartbeat_worker import HeartbeatWorker
from workers.standby_worker    import StandbyWorker   # 不再需要 contains_end_phrase, strip_end_phrase
from utils.accompany_stats  import AccompanyStats

from utils.proactive_chat import ProactiveChatScheduler
from utils.settings import get_settings
from utils.pomodoro_stats import PomodoroStats
from utils.autostart import check_network
from utils.alarm_manager import AlarmManager, REPEAT_LABELS
from utils.todo_manager import TodoManager

from datetime import datetime
import ctypes
from ctypes import wintypes
import sys
import threading
import queue
from datetime import datetime
from PyQt5.QtCore import QThread, pyqtSignal
from utils.diary import init_diary_db, DiaryWorker, get_all_diaries
from gui.diary_dialog import DiaryDialog
from config import get_diary_config
from datetime import datetime
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QTime
import pygame
import random
from utils.sound import play_sound
import time
from utils.music_stats import MusicStats
from gui.note_dialog import NoteDialog
from utils.reminder_manager import ReminderManager
from gui.reminder_dialog import ReminderDialog
from workers.smart_reminder_worker import SmartReminderWorker
from utils.emotion_manager import parse_emotion_tag, get_random_emotion_image

# ── Galgame 模式 ────────────────────────────────────────────
from gui.galgame.tachie_window import TachieWindow
from gui.galgame.galgame_dialog import GalgameDialog
from gui.galgame.expression_manager import ExpressionManager

# ── Win32 全局热键 ───────────────────────────────────────────
WM_HOTKEY = 0x0312
_HOTKEY_ID = 1
user32 = ctypes.windll.user32


class _WinHotkeyFilter(QAbstractNativeEventFilter):
    """捕获 WM_HOTKEY 消息，桥接到 Qt 主线程。"""
    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def nativeEventFilter(self, eventType, message):
        if eventType in ('windows_generic_MSG', 'windows_dispatcher_MSG'):
            msg = ctypes.wintypes.MSG.from_address(int(message.__int__()))
            if msg.message == WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                self._callback()
                return True, 0
        return False, 0


_AUTOSTART_WELCOME = "嘿嘿~又睡了一觉，终于等到你开机了，我已经偷偷开机自启动了哦~"
_AUTOSTART_NET_INTERVAL_MS = 30 * 1000   # 每 30 秒检测一次网络
_AUTOSTART_NET_MAX_ATTEMPTS = 30         # 最多等 15 分钟（30 × 30s）


class MainWindow(QMainWindow):
    def __init__(self, autostart_mode: bool = False):
        super().__init__()
        self._autostart_mode = autostart_mode
        # 添加：窗口闪烁相关
        self._is_minimized = False  # 记录窗口是否最小化
        self._pending_arms_cross = False   # 是否需要播放抱胸动画
        # ── 核心模块 ──────────────────────────────────────────
        self._agent   = AgentCore()
        self._listener = VoiceListener(model_size="base", language="zh")
        self._speaker  = VoiceSpeaker(voice="zh-CN-XiaoxiaoNeural")

        # ── 陪伴统计模块 ──────────────────────────────────────
        self._accompany_stats = AccompanyStats()
        self._accompany_stats.start_session()   # 记录本次启动时间

        # ── 全局设置 ──────────────────────────────────────────
        self._global_settings = get_settings()

        # ── 工作线程句柄 ──────────────────────────────────────
        self._agent_worker:      AgentWorker      | None = None
        self._voice_worker:      VoiceWorker      | None = None
        self._speaker_worker:    SpeakerWorker    | None = None
        self._proactive_worker:  ProactiveWorker  | None = None
        self._ocr_worker = None
        self._is_recording = False
        self._speak_voice_used = False  # 标记本回合是否已调用了 speak_voice 工具

        # ── QQ 桥接 ──────────────────────────────────────────
        self._qq_bridge = None
        self._qq_bridge_auto_start = get_qq_bridge_config().get("auto_start", False)

        # ── 主动聊天调度器 ────────────────────────────────────
        self._proactive_scheduler = ProactiveChatScheduler()
        self._last_proactive_was_observation = False

        # ── 番茄钟模块 ────────────────────────────────────────
        self._pomodoro_dialog: PomodoroDialog | None = None
        self._pomodoro_stats = PomodoroStats()
        self._pomodoro_active = False  # 番茄钟是否运行中

        # ── 备忘本模块 ────────────────────────────────────────
        self.note_dialog = NoteDialog(None)
        # ── 闹钟模块 ──────────────────────────────────────────
        self._alarm_manager = AlarmManager()
        self._alarm_dialog: AlarmDialog | None = None
        self._alarm_timer = QTimer(self)
        self._alarm_timer.timeout.connect(self._check_alarms)
        self._alarm_timer.start(1000)  # 每秒检查一次

        # ── 倒计时模块（主窗口统一管理）───────────────────────
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._check_countdowns)
        self._countdown_timer.start(1000)

        # ── 待办清单模块（数据层，UI 无关部分）──────────────
        self._todo_manager = TodoManager()
        # 将同一实例注入工具层，确保 AI 工具和 UI 共享同一个 TodoManager，
        # 避免 tools.py 懒创建独立实例导致观察者无法收到通知。
        import brain.tools as _brain_tools
        _brain_tools._todo_manager = self._todo_manager

        # ── 待机模式（文件中转模式）──────────────────────────────────────────
        self._standby_state = "IDLE"              # IDLE / STANDBY
        self._is_waiting_for_response = False
        self._note_poll_timer = None
        self._note_timeout_timer = None
        self._note_file = None

        self._build_ui()
        import brain.tools as brain_tools
        brain_tools.set_music_control_callback(self._handle_music_control)
        brain_tools.set_music_info_callback(self._handle_music_info)
        brain_tools.set_note_refresh_callback(self.refresh_note_dialog_content)
        brain_tools.set_proactive_toggle_callback(self._proactive_scheduler.reload_settings)

        # 初始化 pygame 混音器（用于音乐播放）
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        # 初始化日记数据库
        init_diary_db()

        # 日记定时器
        self._diary_timer = QTimer(self)
        self._diary_timer.timeout.connect(self._on_diary_timer_timeout)
        self._setup_diary_timer()
        # ── 待办提醒定时器（须在 _build_ui 后，_chat_widget 已就绪）──
        self._todo_reminder_timer = QTimer(self)
        self._todo_reminder_timer.timeout.connect(self._check_overdue_todos)
        self._todo_reminder_timer.start(30 * 60 * 1000)  # 30分钟
        self._check_overdue_todos()  # 启动时立即检查一次

        # ── 初始化情感系统（涟漪） ─────────────────────────────
        try:
            from brain.emotional import get_manager as _get_emotion_mgr
            _get_emotion_mgr()  # 触发加载 + 时间衰减
            # 每 5 分钟更新一次时间衰减（孤独漂移）
            self._emotion_decay_timer = QTimer(self)
            self._emotion_decay_timer.timeout.connect(self._on_emotion_decay_tick)
            self._emotion_decay_timer.start(300_000)  # 5 分钟
        except Exception:
            pass

        self._show_greeting()
        self._preload_whisper()   # 后台预载 Whisper 模型
        self._preload_tts()       # 后台预热 TTS 引擎


        # ── 主动聊天定时器（每 5 分钟轮询一次）──────────────
        self._proactive_timer = QTimer(self)
        self._proactive_timer.timeout.connect(self._on_proactive_tick)
        self._proactive_timer.start(5 * 60 * 1000)   # 5 分钟

        # ── 心跳自检定时器（对话结束后 N 分钟触发，回顾遗漏事项）──
        self._heartbeat_check_timer = QTimer(self)
        self._heartbeat_check_timer.setSingleShot(True)
        self._heartbeat_check_timer.timeout.connect(self._on_heartbeat_check)
        self._heartbeat_check_worker: HeartbeatWorker | None = None

        # ── 主线程心跳看门狗（后台线程实时监控，卡顿时立即抓堆栈）──
        self._heartbeat_time = time.monotonic()
        self._heartbeat_frozen = False
        # 轻量定时器：仅更新时间戳（5 秒间隔）
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.timeout.connect(self._touch_heartbeat)
        self._heartbeat_timer.start(5000)
        # 后台监控线程：不依赖 Qt 事件循环，卡顿时能实时捕获堆栈
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()

        # 在 __init__ 中：
        self.reminder_manager = ReminderManager()
        self.reminder_timer = QTimer(self)
        self.reminder_timer.timeout.connect(self._check_reminders)
        self.reminder_timer.start(60000)  # 每分钟检查一次

        # ── Galgame 模式 ─────────────────────────────────────
        self._galgame_visible = False
        self._galgame_positioned = False  # 是否首次显示/已拖动过
        self._tachie_win: TachieWindow | None = None
        self._galgame_dialog: GalgameDialog | None = None
        self._expression_mgr = ExpressionManager(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
        )
        # 注册表情切换回调（供 set_expression 工具使用）
        import brain.tools as brain_tools
        brain_tools.set_expression_callback(self._on_galgame_expression)

        # ── 全局热键过滤器 + 注册热键（启动即生效） ──────────
        self._hotkey_filter = _WinHotkeyFilter(
            lambda: QTimer.singleShot(0, self._toggle_galgame)
        )
        from PyQt5.QtWidgets import QApplication
        QApplication.instance().installNativeEventFilter(self._hotkey_filter)
        self._setup_galgame_hotkey(register=True)

        # ── 首次运行：未配置 API Key 时自动弹出配置对话框 ───
        if not has_api_key():
            QTimer.singleShot(500, self._show_api_config)

        # ── QQ 桥接：配置为启用且开启自动启动时才自动连接 ────
        qq_cfg = get_qq_bridge_config()
        if qq_cfg.get("auto_start") and qq_cfg.get("qq_account"):
            QTimer.singleShot(1000, self._start_qq_bridge)

        # ── 开机自启动：启动网络检测轮询 ────────────────────
        self._autostart_net_attempts = 0
        self._autostart_net_timer: QTimer | None = None
        if self._autostart_mode:
            self._start_autostart_net_poll()
        self._stt_process = None   # 阿里云语音识别子进程

        # 音乐播放器变量区域
        self.playlist = []           # 音乐文件路径列表
        self.current_track_index = 0
        self.music_playing = False
        self.loop_mode = "list"          # list / one / random
        self.current_duration = 0        # 当前歌曲总时长（秒）
        self._progress_timer = None      # 用于更新进度的定时器
        self.current_offset = 0          # 当前歌曲播放起始偏移（秒），用于 seek
        self.current_position = 0        # 当前播放进度（秒）
        self._load_music_playlist()
        self._restore_music_state()
        self.music_stats = MusicStats()
        self.current_song_start_time = None

    def _handle_music_info(self, query_type: str) -> str:
        if query_type == "playlist":
            if not self.playlist:
                return "播放列表为空。"
            names = [p.stem for p in self.playlist]
            return "当前歌单：\n" + "\n".join(f"{i+1}. {name}" for i, name in enumerate(names))
        elif query_type == "status":
            if not self.playlist:
                return "未加载任何音乐。"
            status = "播放中" if self.music_playing else ("暂停" if not self.music_playing and self.current_position > 0 else "停止")
            current_name = self.playlist[self.current_track_index].stem if self.playlist else "无"
            current_pos = self.current_position
            total = self.current_duration
            return f"状态：{status}\n当前歌曲：{current_name}\n进度：{current_pos//60:02d}:{current_pos%60:02d} / {total//60:02d}:{total%60:02d}"
        elif query_type == "stats":
            total_hours = self.music_stats.get_total_hours()
            song_name, seconds = self.music_stats.get_most_played_song()
            if song_name:
                minutes = seconds // 60
                return f"累计听歌 {total_hours:.1f} 小时。\n最常听的歌曲：{song_name}，共 {minutes} 分钟。"
            else:
                return f"累计听歌 {total_hours:.1f} 小时。还没有积累出最常听的歌曲。"
        else:
            return "未知查询。"

    def _handle_music_control(self, action: str) -> str:
        if action == "play":
            self._on_music_play_pause()
            return "已开始播放音乐。"
        elif action == "pause":
            self._on_music_play_pause()
            return "已暂停音乐。"
        elif action == "next":
            self._next_track()
            return "已切换到下一首。"
        elif action == "prev":
            self._prev_track()
            return "已切换到上一首。"
        elif action == "loop":
            self._on_loop_mode_clicked()
            return "已切换循环模式。"
        elif action == "volume_up":
            new_val = min(100, self._char_widget.get_music_volume_slider().value() + 10)
            self._char_widget.get_music_volume_slider().setValue(new_val)
            return f"音量增加到 {new_val}%"
        elif action == "volume_down":
            new_val = max(0, self._char_widget.get_music_volume_slider().value() - 10)
            self._char_widget.get_music_volume_slider().setValue(new_val)
            return f"音量减小到 {new_val}%"
        else:
            return "不支持的操作。"

    def flash_taskbar(self, flash_count=3):
        """让任务栏图标闪烁（仅 Windows）"""
        if not sys.platform.startswith('win'):
            return
        
        try:
            # 定义 FLASHWINFO 结构体
            class FLASHWINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.UINT),
                    ("hwnd", wintypes.HWND),
                    ("dwFlags", wintypes.DWORD),
                    ("uCount", wintypes.UINT),
                    ("dwTimeout", wintypes.DWORD),
                ]
            
            # 闪烁标志
            FLASHW_TRAY = 0x00000002      # 闪烁任务栏按钮
            FLASHW_TIMERNOFG = 0x0000000C # 持续闪烁直到窗口被激活
            
            hwnd = int(self.winId())
            info = FLASHWINFO()
            info.cbSize = ctypes.sizeof(FLASHWINFO)
            info.hwnd = hwnd
            info.dwFlags = FLASHW_TRAY | FLASHW_TIMERNOFG
            info.uCount = flash_count     # 闪烁次数（0 表示持续闪烁）
            info.dwTimeout = 0            # 使用默认闪烁速度（约 1 秒一次）
            
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
        except Exception as e:
            print(f"闪烁任务栏失败: {e}")
    
    def stop_flash(self):
        """停止闪烁"""
        if not sys.platform.startswith('win'):
            return
        
        try:
            class FLASHWINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.UINT),
                    ("hwnd", wintypes.HWND),
                    ("dwFlags", wintypes.DWORD),
                    ("uCount", wintypes.UINT),
                    ("dwTimeout", wintypes.DWORD),
                ]
            
            hwnd = int(self.winId())
            info = FLASHWINFO()
            info.cbSize = ctypes.sizeof(FLASHWINFO)
            info.hwnd = hwnd
            info.dwFlags = 0  # 停止闪烁
            info.uCount = 0
            info.dwTimeout = 0
            
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
        except Exception:
            pass
    
    def changeEvent(self, event):
        """监听窗口状态变化（最小化/还原）"""
        if event.type() == event.WindowStateChange:
            if self.isMinimized():
                self._is_minimized = True
            else:
                if self._is_minimized:
                    self._is_minimized = False
                    self.stop_flash()  # 窗口还原时停止闪烁
        super().changeEvent(event)






    # ── 界面构建 ─────────────────────────────────────────────

    def _build_ui(self):
        # ── 设置主窗口背景图（半透明效果）────────────────────────
        self._set_background_image()

        self.setWindowTitle("莲心AI")
        icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "应用图标.jpg")
        if os.path.exists(icon_path):
            from PyQt5.QtGui import QIcon
            self.setWindowIcon(QIcon(icon_path))

        self.setMinimumSize(820, 600)
        self.resize(960, 680)

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 顶部栏：标题 + 历史按钮（半透明）
        top_bar = QWidget()
        top_bar.setFixedHeight(36)
        top_bar.setStyleSheet("background-color: rgba(236, 238, 255, 200); border-bottom: 1px solid rgba(216, 216, 238, 150);")
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(12, 0, 12, 0)

        app_label = QLabel("莲心AI")
        app_label.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        app_label.setStyleSheet("color: #5060DD;")
        top_bar_layout.addWidget(app_label)
        top_bar_layout.addStretch()

        self._btn_history = QPushButton("历史记录")
        self._btn_history.setFixedSize(72, 24)
        self._btn_history.setFont(QFont("Microsoft YaHei UI", 8))
        self._btn_history.setCursor(Qt.PointingHandCursor)
        self._btn_history.setStyleSheet("""
            QPushButton {
                background-color: #6C7BFF;
                color: white;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover  { background-color: #5A6AEE; }
            QPushButton:pressed{ background-color: #4A5ADE; }
        """)
        self._btn_history.clicked.connect(self._on_history_clicked)
        top_bar_layout.addWidget(self._btn_history)

        self._btn_new_chat = QPushButton("新建对话")
        self._btn_new_chat.setFixedSize(72, 24)
        self._btn_new_chat.setFont(QFont("Microsoft YaHei UI", 8))
        self._btn_new_chat.setCursor(Qt.PointingHandCursor)
        self._btn_new_chat.setStyleSheet("""
            QPushButton {
                background-color: #F0F0F8;
                color: #5060DD;
                border-radius: 6px;
                border: 1px solid #C8CCF0;
            }
            QPushButton:hover  { background-color: #E4E4F8; }
            QPushButton:pressed{ background-color: #D8D8EE; }
        """)
        self._btn_new_chat.clicked.connect(self._on_new_chat_clicked)
        top_bar_layout.addWidget(self._btn_new_chat)

        # 日记本按钮
        self._btn_diary = QPushButton("📔 日记本")
        self._btn_diary.setFixedSize(80, 24)
        self._btn_diary.setFont(QFont("Microsoft YaHei UI", 8))
        self._btn_diary.setCursor(Qt.PointingHandCursor)
        self._btn_diary.setStyleSheet("""
            QPushButton {
                background-color: #F0F0F8;
                color: #7A4A2A;
                border-radius: 6px;
                border: 1px solid #D8C8A0;
            }
            QPushButton:hover { background-color: #E8D8C0; }
        """)
        self._btn_diary.clicked.connect(self._open_diary_dialog)
        top_bar_layout.addWidget(self._btn_diary)

                # 备忘本按钮
        self._btn_note = QPushButton("📝 备忘本")
        self._btn_note.setFixedSize(80, 24)
        self._btn_note.setFont(QFont("Microsoft YaHei UI", 8))
        self._btn_note.setCursor(Qt.PointingHandCursor)
        self._btn_note.setStyleSheet("""
            QPushButton {
                background-color: #F0F0F8;
                color: #7A4A2A;
                border-radius: 6px;
                border: 1px solid #D8C8A0;
            }
            QPushButton:hover { background-color: #E8D8C0; }
        """)
        self._btn_note.clicked.connect(self._open_note_dialog)
        top_bar_layout.addWidget(self._btn_note)

        # 主动聊天按钮（带状态指示）
        self._btn_proactive = QPushButton("主动聊天 ○")
        self._btn_proactive.setFixedSize(96, 24)
        self._btn_proactive.setFont(QFont("Microsoft YaHei UI", 8))
        self._btn_proactive.setCursor(Qt.PointingHandCursor)
        self._btn_proactive.setToolTip("设置莲心主动发消息的时间和频率")
        self._btn_proactive.setStyleSheet("""
            QPushButton {
                background-color: #F0F0F8;
                color: #777777;
                border-radius: 6px;
                border: 1px solid #D8D8EE;
            }
            QPushButton:hover  { background-color: #E4E4F0; }
            QPushButton:pressed{ background-color: #D8D8E8; }
        """)
        self._btn_proactive.clicked.connect(self._on_proactive_clicked)
        top_bar_layout.addWidget(self._btn_proactive)

        # 心跳自检按钮（带状态指示）
        self._btn_heartbeat = QPushButton("心跳自检 ●")
        self._btn_heartbeat.setFixedSize(88, 24)
        self._btn_heartbeat.setFont(QFont("Microsoft YaHei UI", 8))
        self._btn_heartbeat.setCursor(Qt.PointingHandCursor)
        self._btn_heartbeat.setToolTip("对话结束后自动检查是否有遗漏的待办事项")
        self._btn_heartbeat.clicked.connect(self._on_heartbeat_btn_clicked)
        self._update_heartbeat_button()
        top_bar_layout.addWidget(self._btn_heartbeat)

        # QQ 聊天按钮（一键开关，状态由 _update_qq_bridge_button 维护）
        self._btn_qq_bridge = QPushButton("QQ聊天 ○")
        self._btn_qq_bridge.setFixedSize(84, 24)
        self._btn_qq_bridge.setFont(QFont("Microsoft YaHei UI", 8))
        self._btn_qq_bridge.setCursor(Qt.PointingHandCursor)
        self._btn_qq_bridge.setToolTip("开启后即可通过 QQ 小号与莲心聊天")
        self._btn_qq_bridge.clicked.connect(self._on_qq_bridge_clicked)
        self._update_qq_bridge_button()
        top_bar_layout.addWidget(self._btn_qq_bridge)

        # Galgame 窗口按钮
        self._galgame_btn = QPushButton("🎮 Galgame")
        self._galgame_btn.setFixedSize(86, 24)
        self._galgame_btn.setFont(QFont("Microsoft YaHei UI", 8))
        self._galgame_btn.setCursor(Qt.PointingHandCursor)
        self._galgame_btn.setToolTip("打开 Galgame 风格的角色立绘和对话窗口")
        self._galgame_btn.setStyleSheet("""
            QPushButton {
                background-color: #F0F0F8;
                color: #6C4A9A;
                border-radius: 6px;
                border: 1px solid #D0B8E8;
            }
            QPushButton:hover  { background-color: #E8D8F8; }
            QPushButton:pressed{ background-color: #D8C8EE; }
        """)
        self._galgame_btn.clicked.connect(self._toggle_galgame)
        top_bar_layout.addWidget(self._galgame_btn)

        self._btn_standby = QPushButton("🌙 待机")
        self._btn_standby.setFixedSize(72, 24)
        self._btn_standby.setFont(QFont("Microsoft YaHei UI", 8))
        self._btn_standby.setCursor(Qt.PointingHandCursor)
        self._btn_standby.setToolTip("待机模式：通过语音与小纸条交互")
        self._btn_standby.clicked.connect(self._on_standby_clicked)
        self._update_standby_button()
        top_bar_layout.addWidget(self._btn_standby)

        main_layout.addWidget(top_bar)

        # 上半：左栏（角色）+ 右栏（聊天）
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)

        self._char_widget = CharacterWidget()
        # 绑定功能区按钮
        self._char_widget.get_accompany_button().clicked.connect(self._on_accompany_clicked)

        self._char_widget.get_settings_button().clicked.connect(self._on_settings_clicked)
        self._char_widget.get_pomodoro_button().clicked.connect(self._on_pomodoro_clicked)
        self._char_widget.get_api_config_button().clicked.connect(self._show_api_config)
        self._char_widget.get_alarm_button().clicked.connect(self._on_alarm_clicked)
        self._char_widget.get_camera_button().clicked.connect(self._on_camera_capture)
        self._char_widget.get_emotion_button().clicked.connect(self._on_open_emotion_debug)
        self._char_widget.get_sound_button().clicked.connect(self._on_sound_settings)
        self._char_widget.get_memory_button().clicked.connect(self._on_memory_settings)
        self._char_widget.get_network_button().clicked.connect(self._show_network_settings)
        self._char_widget.get_capability_button().clicked.connect(self._show_capability_center)

        top_layout.addWidget(self._char_widget)

        self._chat_widget = ChatWidget()
        top_layout.addWidget(self._chat_widget)

        main_layout.addWidget(top_widget)

        # 下半：输入栏（全宽）
        self._input_panel = InputPanel()
        self._input_panel.message_submitted.connect(self._on_user_message)
        self._input_panel.voice_clicked.connect(self._on_voice_clicked)

        self._input_panel.enable_clear_button()  # 启用清空按钮
        self._input_panel.clear_clicked.connect(self._on_clear_note)  # 清空小纸条
        self._input_panel.image_submitted.connect(self._on_user_image)
        main_layout.addWidget(self._input_panel)


        # 音乐盒按钮连接
        self._char_widget.get_music_play_button().clicked.connect(self._on_music_play_pause)
        self._char_widget.get_music_prev_button().clicked.connect(self._prev_track)
        self._char_widget.get_music_next_button().clicked.connect(self._next_track)
        self._char_widget.get_music_volume_slider().valueChanged.connect(self._on_music_volume_changed)
        self._char_widget.get_open_music_folder_button().clicked.connect(self._open_music_list)
        self._char_widget.get_music_loop_button().clicked.connect(self._on_loop_mode_clicked)
        self._char_widget.get_music_progress().sliderReleased.connect(self._seek_to)
        # 初始化音量滑块值
        self._char_widget.get_music_volume_slider().setValue(int(self._global_settings.music_volume * 100))
        
    def _open_note_dialog(self):
        play_sound("MemoBook.mp3")
        if self.note_dialog is None:
            from gui.note_dialog import NoteDialog
            # 父窗口设为 None，使其独立于主窗口
            self.note_dialog = NoteDialog(None)
            self.note_dialog.destroyed.connect(self._on_note_dialog_destroyed)
            self.note_dialog.show()
        else:
            self.note_dialog.show()
            self.note_dialog.raise_()
            self.note_dialog.activateWindow()

    def _on_note_dialog_destroyed(self):
        self.note_dialog = None

    def refresh_note_dialog_content(self):
        """供工具调用，刷新备忘本显示的內容"""
        if self.note_dialog is not None:
            self.note_dialog.refresh_content()  


    def _set_background_image(self):
        """设置主窗口半透明背景图，所有子控件背景透明"""
        bg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "主界面背景图.jpg")
        if os.path.exists(bg_path):
            self.setStyleSheet(f"""
                QMainWindow {{
                    background-image: url("{bg_path.replace('\\', '/')}");
                    background-position: center;
                    background-repeat: no-repeat;
                    background-attachment: fixed;
                }}
            """)
            central = self.centralWidget()
            if central:
                central.setStyleSheet("background-color: rgba(0, 0, 0, 0); border: none;")
            self.setAttribute(Qt.WA_StyledBackground, True)
        else:
            self.setStyleSheet("background-color: #F0F2F7;")

    def _show_greeting(self):
        """启动时显示欢迎内容：有历史则回放最近30条，否则显示初次欢迎语。"""
        if self._agent.history:
            msgs = self._agent.get_history_manager().get_messages(self._agent._session_id)
            display = msgs[-30:]
            for m in display:
                if m["role"] == "user":
                    self._chat_widget.add_user_message(m["content"])
                else:
                    clean, _ = _strip_emotion_tag(m["content"])
                    self._chat_widget.add_ai_message(clean or m["content"])
            total = len(msgs)
            shown = len(display)
            self._chat_widget.add_system_tip(
                f"—— 已加载上次对话（显示最近 {shown} 条，共 {total} 条）——"
            )
        else:
            self._chat_widget.add_ai_message("让我看看...现实稳定锚就绪，坐标稳定...这里是莲心，收到请回复~")

    # ── Whisper 预加载 ───────────────────────────────────────

    def _preload_whisper(self):
        self._chat_widget.add_system_tip("正在后台加载语音识别模型，请稍候…")
        loader = ModelLoader(self._listener, self)
        loader.finished.connect(self._on_model_loaded)
        loader.failed.connect(self._on_model_failed)
        loader.start()
        self._model_loader = loader

    def _on_model_loaded(self):
        self._chat_widget.add_system_tip("语音识别模型已就绪，可点击 🎤 开始语音对话")
        self._input_panel.enable_voice_button()

    def _on_model_failed(self, err: str):
        self._chat_widget.add_system_tip(f"语音识别模型加载失败：{err}")

    def _preload_tts(self):
        """后台线程预热 TTS 引擎（GPT-SoVITS worker），缩短首次语音回复延迟。"""
        from config import get_tts_config
        cfg = get_tts_config()
        if not cfg.get("tts_warmup", True):
            return
        def _warmup():
            try:
                from brain.tts_engine import TtsEngine
                engine = TtsEngine()
                engine.warmup()
            except Exception:
                pass
        threading.Thread(target=_warmup, daemon=True).start()

    # ── 文字对话 ─────────────────────────────────────────────
    def _on_user_message(self, text: str, images: list = None):
        # 用户发消息 → 立即停止语音播放、重置语音标记
        try:
            from skills.语音合成.tools import stop_voice_playback
            stop_voice_playback()
        except Exception:
            pass
        self._speak_voice_used = False
        if images is None:
            images = []
        selected_tool = self._input_panel.get_selected_tool()
        if selected_tool is None:
            action_keywords = ["打开", "启动", "运行", "执行", "开启"]
            if any(kw in text for kw in action_keywords):
                text = "[重要：你必须调用相应工具来执行(比如open_app)，不要直接回复结果。]\n" + text
            diary_keywords = ["读日记", "日记里", "回忆一下日记", "看看日记", "日记写了什么", "读一下", "最近日记"]
            if any(kw in text for kw in diary_keywords):
                text = "[重要：你必须调用 read_diary 工具来获取日记内容，不要直接回答。]\n" + text
        if self._speaker_worker and self._speaker_worker.isRunning():
            self._speaker.stop()
        self._proactive_scheduler.notify_user_active()

        image_bubbles = []
        for img_path in images:
            bubble = self._chat_widget.add_user_image(img_path, ocr_text="分析中...")
            image_bubbles.append((img_path, bubble))

        if text.strip():
            self._chat_widget.add_user_message(text)

        self._set_thinking_state()

        if images:
            self._staged_image_results = {}
            self._staged_image_errors = {}
            self._staged_image_count = len(images)
            self._staged_text = text
            self._staged_selected_tool = selected_tool
            self._staged_bubbles = image_bubbles

            for i, (img_path, _) in enumerate(image_bubbles):
                worker = _ImageVisionWorker(img_path, self)
                worker.finished.connect(lambda desc, idx=i: self._on_staged_vision_done(idx, desc))
                worker.error.connect(lambda err, idx=i: self._on_staged_vision_error(idx, err))
                worker.start()
        else:
            self._agent_worker = AgentWorker(self._agent, text, self, forced_tool=selected_tool)
            self._agent_worker.response_ready.connect(self._on_ai_response)
            self._agent_worker.progress_update.connect(self._on_progress_update)
            self._agent_worker.tool_called.connect(self._on_tool_called)
            self._agent_worker.error_occurred.connect(self._on_error)
            self._agent_worker.start()
            self._input_panel.show_interrupt_bar(self._agent_worker)


        self._input_panel.clear_selection()

    def _on_staged_vision_done(self, idx: int, description: str):
        self._staged_image_results[idx] = description
        if len(self._staged_image_results) + len(self._staged_image_errors) >= self._staged_image_count:
            self._finish_staged_vision()

    def _on_staged_vision_error(self, idx: int, err: str):
        self._staged_image_errors[idx] = err
        if len(self._staged_image_results) + len(self._staged_image_errors) >= self._staged_image_count:
            self._finish_staged_vision()

    def _finish_staged_vision(self):
        self._chat_widget._hide_thinking()

        for i, (_, bubble) in enumerate(self._staged_bubbles):
            if i in self._staged_image_results:
                bubble.update_text(self._staged_image_results[i])
            elif i in self._staged_image_errors:
                bubble.update_text(f"分析失败: {self._staged_image_errors[i]}")

        context_parts = []
        for i, (_, _) in enumerate(self._staged_bubbles):
            if i in self._staged_image_results:
                context_parts.append(f"[用户发了一张图片，视觉分析结果如下]\n{self._staged_image_results[i]}")
            elif i in self._staged_image_errors:
                context_parts.append(f"[图片分析失败] {self._staged_image_errors[i]}")

        if self._staged_text.strip():
            context_parts.append(self._staged_text)

        full_context = "\n\n".join(context_parts)
        if not self._staged_text.strip():
            full_context += "\n\n请根据你看到的内容自然地回应，描述你看到了什么。"

        self._agent_worker = AgentWorker(self._agent, full_context, self, forced_tool=self._staged_selected_tool)
        self._agent_worker.response_ready.connect(self._on_ai_response)
        self._agent_worker.progress_update.connect(self._on_progress_update)
        self._agent_worker.tool_called.connect(self._on_tool_called)
        self._agent_worker.error_occurred.connect(self._on_error)
        self._agent_worker.start()
        self._input_panel.show_interrupt_bar(self._agent_worker)





    def _on_tool_called(self, tool_name: str):
        if tool_name == "speak_voice":
            self._speak_voice_used = True  # 标记已语音播报，后面不再重复播放
        self._chat_widget.show_thinking(tool_name)
        # 标记需要播放抱胸动画，等思考结束后再播放
        self._pending_arms_cross = random.random() < 0.03
        if self._galgame_visible and self._galgame_dialog:
            self._galgame_dialog.show_thinking()

    def _on_progress_update(self, text: str):
        """收到插话进度回复（流式文本不显示在聊天界面）。"""
        pass


    def _on_error(self, err: str):
        self._input_panel.set_enabled(True)
        self._input_panel.hide_interrupt_bar()
        self._chat_widget.add_system_tip(f"错误：{err}")


    def _on_ai_response(self, text: str):
        self._input_panel.hide_interrupt_bar()
        # 先结束思考（如果是非待机模式，会播放放下手机动画；如果是待机模式，则什么都不做）
        if self._standby_state != "STANDBY":
            # 非待机模式，使用原有的思考结束逻辑（等待打字动画结束）
            def after_thinking():
                if self._pending_arms_cross:
                    self._pending_arms_cross = False
                    self._char_widget.play_arms_cross(on_finished=lambda: self._continue_response(text))
                else:
                    self._continue_response(text)
            self._char_widget.stop_thinking(on_finished=after_thinking)
        else:
            # 待机模式下，直接触发说话动画（会等待当前倾听动画播放完）
            self._continue_response(text)



    def _continue_response(self, text: str):
        from utils.emotion_manager import get_random_emotion_image
        import random

        # text 已经是 agent 剥离标签后的干净文本
        display_text = text

        # 如果本回合 speak_voice 工具已播放语音，强制消息框内容与之匹配
        if self._speak_voice_used:
            try:
                from skills.语音合成.tools import _last_spoken_text
                if _last_spoken_text:
                    display_text = _last_spoken_text
            except Exception:
                pass

        # 播放音效
        play_sound("lianxinSend.mp3")

        # 发送文本消息到桌面聊天框
        self._chat_widget.add_ai_message(display_text)

        # 从 agent 获取本轮情绪（标签已在 agent.chat() 中剥离并存储）
        emotion = getattr(self._agent, '_last_emotion', None) if self._agent else None

        # ── 同步更新 Galgame 窗口（保持原有逻辑）──
        if self._galgame_visible and self._galgame_dialog:
            galgame_emotion = self._expression_mgr.match(display_text)
            self._galgame_dialog.show_reply(display_text)
            if self._tachie_win:
                img_path = self._expression_mgr.get_image_path(galgame_emotion)
                if img_path:
                    self._tachie_win.set_image(img_path)

        # ===== 发送表情包图片（概率触发） =====
        if emotion:
            prob = self._global_settings.emotion_probability
            if random.random() < prob:
                img_path = get_random_emotion_image(emotion)
                if img_path:
                    self._chat_widget.add_ai_image(img_path)

        # ===== 后续原有逻辑 =====
        self._set_idle_state()
        if self.isMinimized():
            self.flash_taskbar(flash_count=0)
        if self._global_settings.silent_mode:
            self._restart_listening()
        elif self._speak_voice_used:
            self._speak_voice_used = False  # 已由 speak_voice 工具播放，不再重复
            self._restart_listening()
        else:
            self._speaker_worker = SpeakerWorker(self._speaker, display_text, self)
            self._speaker_worker.speaking_started.connect(self._char_widget.set_talking)
            self._speaker_worker.speaking_finished.connect(self._char_widget.set_normal)
            self._speaker_worker.speaking_finished.connect(self._restart_listening)
            self._speaker_worker.start()



    def _on_error(self, error_msg: str):
        self._pending_arms_cross = False   # 重置标志
        self._chat_widget.add_ai_message(f"（出错了：{error_msg}）")
        self._set_idle_state()

    # ── Galgame 模式 ──────────────────────────────────────────

    def _toggle_galgame(self):
        """打开/关闭 Galgame 立绘+对话框窗口。"""
        if self._galgame_visible:
            self._hide_galgame()
        else:
            QTimer.singleShot(50, self._show_galgame)

    def _show_galgame(self):
        """显示 Galgame 窗口。"""
        if self._tachie_win is None:
            assets_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets"
            )
            self._tachie_win = TachieWindow(assets_dir)
            self._galgame_dialog = GalgameDialog()
            # 连接对话框发送信号
            self._galgame_dialog.message_submitted.connect(self._on_galgame_message)
            # 连接立绘拖拽 → 对话框跟随移动
            self._tachie_win.position_changed.connect(self._on_tachie_moved)
            # 连接立绘右键 → 切换对话框显示
            self._tachie_win.toggle_dialog_requested.connect(self._toggle_galgame_dialog)

        if not self._galgame_positioned:
            # 仅首次显示时放在桌面右上角附近
            screen = self.screen().availableGeometry()
            tx = screen.width() - self._tachie_win.width() - 40
            ty = screen.height() - self._tachie_win.height() - 80
            self._tachie_win.move(tx, ty)

            # 对话框在立绘左侧
            dx = tx - self._galgame_dialog.width() + 20
            dy = ty + 40
            self._galgame_dialog.move(dx, dy)
            self._galgame_positioned = True

        self._tachie_win.show()
        self._galgame_dialog.show()

        self._galgame_visible = True
        self._galgame_btn.setText("🎮 Galgame ●")

    def _hide_galgame(self):
        """隐藏 Galgame 窗口。"""
        if self._tachie_win:
            self._tachie_win.hide()
        if self._galgame_dialog:
            self._galgame_dialog.hide()
        self._galgame_visible = False
        self._galgame_btn.setText("🎮 Galgame")

    def _on_tachie_moved(self, tx: int, ty: int):
        """立绘拖拽时，对话框保持相对偏移跟随移动。"""
        self._galgame_positioned = True
        if self._galgame_dialog and self._galgame_dialog.isVisible():
            dx = tx - self._galgame_dialog.width() + 20
            dy = ty + 40
            self._galgame_dialog.move(dx, dy)

    def _toggle_galgame_dialog(self):
        """右键立绘：切换对话框显示/隐藏（不关闭立绘，记住上次位置）。"""
        if self._galgame_dialog:
            if self._galgame_dialog.isVisible():
                self._galgame_dialog.hide()
            else:
                self._galgame_dialog.show()


    def _on_galgame_message(self, text: str):
        """Galgame 对话框发送消息。"""
        self._chat_widget.add_user_message(text)
        self._send_user_text_to_agent(text)

    def _on_galgame_expression(self, emotion: str):
        """set_expression 工具回调：切换立绘表情。"""
        if self._galgame_visible and self._tachie_win:
            img_path = self._expression_mgr.get_image_path(emotion)
            if img_path:
                self._tachie_win.set_image(img_path)

    def _setup_galgame_hotkey(self, register: bool = True):
        """注册/注销全局热键 Ctrl+Alt+X（Win32 RegisterHotKey）。"""
        MOD_CONTROL = 0x0002
        MOD_ALT     = 0x0001
        VK_X        = 0x58
        try:
            if register:
                user32.RegisterHotKey(None, _HOTKEY_ID, MOD_CONTROL | MOD_ALT, VK_X)
            else:
                user32.UnregisterHotKey(None, _HOTKEY_ID)
        except Exception:
            pass

    # ── 语音输入 ─────────────────────────────────────────────

    def _on_voice_clicked(self):
        if self._is_recording:
            if self._voice_worker:
                self._voice_worker.stop()
            return
        self._is_recording = True
        self._input_panel.set_voice_recording()
        self._chat_widget.add_system_tip("🎤 正在录音，停顿后自动识别…")
        self._input_panel.hide_interrupt_bar()
        self._input_panel.set_enabled(False)
        self._voice_worker = VoiceWorker(self._listener, self)
        self._voice_worker.recording_stopped.connect(self._on_recording_stopped)
        self._voice_worker.text_ready.connect(self._on_voice_text)
        self._voice_worker.error_occurred.connect(self._on_voice_error)
        self._voice_worker.start()

    def _on_recording_stopped(self):
        self._is_recording = False
        self._input_panel.set_voice_idle()
        self._chat_widget.add_system_tip("识别中…")

    def _on_voice_text(self, text: str):
        self._input_panel.set_enabled(True)
        self._input_panel.set_text(text)
        if self._input_panel.is_auto_send_enabled():
            self._input_panel._on_send()

    def _on_voice_error(self, err: str):
        self._is_recording = False
        self._input_panel.set_voice_idle()
        self._input_panel.set_enabled(True)
        self._chat_widget.add_system_tip(f"语音识别失败：{err}")

    # ── TTS 播放 ─────────────────────────────────────────────

    def _speak(self, text: str):
        if self._global_settings.silent_mode:
            return
        self._speaker_worker = SpeakerWorker(self._speaker, text, self)
        self._speaker_worker.speaking_started.connect(self._char_widget.set_talking)
        self._speaker_worker.speaking_finished.connect(self._char_widget.set_normal)
        self._speaker_worker.start()

    # ── 状态管理 ─────────────────────────────────────────────

    def _set_thinking_state(self):
        self._input_panel.set_enabled(False)
        # 判断是否处于待机模式
        if self._standby_state == "STANDBY":
            # 待机模式下：不切换动画，只更新状态文字和聊天框提示
            self._char_widget.set_thinking_status()
            self._chat_widget.show_thinking()
        else:
            # 非待机模式：使用思考动画（拿起手机 -> 打字）
            self._char_widget.start_thinking()
            self._chat_widget.show_thinking()

    def _set_idle_state(self):
        self._char_widget.set_normal()
        self._input_panel.set_enabled(True)

    # ── 历史记录 ─────────────────────────────────────────────

    def _on_history_clicked(self):
        play_sound("ButtonAll.mp3")
        dlg = HistoryDialog(
            self._agent.get_history_manager(),
            current_session_id=self._agent._session_id,
            parent=self,
        )
        dlg.import_memory.connect(self._on_import_memory)
        dlg.exec_()
        self._ensure_valid_session()

    def _ensure_valid_session(self):
        mgr = self._agent.get_history_manager()
        sessions = mgr.get_sessions()
        ids = {s["id"] for s in sessions}
        if self._agent._session_id in ids:
            return
        if sessions:
            newest = sessions[0]
            self._agent._session_id = newest["id"]
            self._agent._session_titled = True
            raw = mgr.get_messages(newest["id"])
            self._agent.history = [{"role": m["role"], "content": m["content"]} for m in raw]
            self._chat_widget.clear_messages()
            for m in raw[-30:]:
                if m["role"] == "user":
                    self._chat_widget.add_user_message(m["content"])
                else:
                    clean, _ = _strip_emotion_tag(m["content"])
                    self._chat_widget.add_ai_message(clean or m["content"])
            self._chat_widget.add_system_tip("—— 当前会话已删除，已自动切换到最近的其他会话 ——")
        else:
            self._agent.new_session()
            self._chat_widget.clear_messages()
            self._chat_widget.add_ai_message("通讯设备正在启动...这里是助手莲心（埋头调试ing...）")

    def _on_new_chat_clicked(self):
        play_sound("ButtonAll.mp3")
        reply = QMessageBox.question(
            self, "新建对话",
            "当前对话已自动保存。\n确定要开启新对话吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        self._agent.new_session()
        self._chat_widget.clear_messages()
        self._chat_widget.add_ai_message("这里是助手莲心，现实稳定锚就绪，坐标稳定...收到请回复~")

    def _on_import_memory(self, session_id: int):
        msgs = self._agent.get_history_manager().get_messages(session_id)
        if not msgs:
            QMessageBox.information(self, "提示", "该会话暂无消息内容。")
            return
        total_chars = sum(len(m["content"]) for m in msgs)
        reply = QMessageBox.question(
            self, "导入记忆确认",
            f"即将导入历史会话共 {len(msgs)} 条消息（约 {total_chars} 字符）。\n"
            f"导入后将追加到当前对话上下文，是否确认？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        self._chat_widget.add_system_tip(f"—— 导入历史记忆（共 {len(msgs)} 条）——")
        mgr = self._agent.get_history_manager()
        for m in msgs:
            prefixed = f"[回顾] {m['content']}"
            self._agent.history.append({"role": m["role"], "content": prefixed})
            if m["role"] == "user":
                self._chat_widget.add_user_message(prefixed)
            else:
                self._chat_widget.add_ai_message(prefixed)
            mgr.save_message(self._agent._session_id, m["role"], prefixed)

    # ── 陪伴统计 ─────────────────────────────────────────────

    def _on_accompany_clicked(self):
        play_sound("ButtonAll.mp3")
        from gui.accompany_dialog import AccompanyDialog
        self._accompany_stats.reload()
        if not self._accompany_stats.has_first_meet_date():
            reply = QMessageBox.question(
                self,
                "设置初识日期",
                "检测到你还没有设置与莲心初次见面的日期！\n\n"
                "设置后可以计算「一起度过的第X天」哦~\n\n"
                "是否现在去设置？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                self._on_settings_clicked()
            return
        dlg = AccompanyDialog(self._accompany_stats, self.music_stats, self)
        dlg.dialog_closed.connect(self._on_accompany_dialog_closed)
        dlg.exec_()

    def _on_accompany_dialog_closed(self):
        duration_str = self._accompany_stats.get_current_formatted_duration()
        session_count = self._accompany_stats.get_stats()["session_count"]
        total_days = self._accompany_stats.get_total_days_since_first_meet()
        msg = f"原来你这家伙已经待在我身边长达{duration_str}，启动了{session_count}次，相识了{total_days}天了吗？好开心~(*´▽`*)" 
        self._agent.get_history_manager().save_message(
            self._agent._session_id, "assistant", f"[陪伴统计] {msg}"
        )
        self._chat_widget.add_ai_message(msg)
        self._speak(msg)

    # ── 开机自启动网络检测 ────────────────────────────────────

    def _start_autostart_net_poll(self):
        self._autostart_net_attempts = 0
        self._autostart_net_timer = QTimer(self)
        self._autostart_net_timer.timeout.connect(self._on_autostart_net_tick)
        QTimer.singleShot(5000, self._on_autostart_net_tick)
        self._autostart_net_timer.start(_AUTOSTART_NET_INTERVAL_MS)

    def _on_autostart_net_tick(self):
        self._autostart_net_attempts += 1
        if self._autostart_net_attempts > _AUTOSTART_NET_MAX_ATTEMPTS:
            self._stop_autostart_net_poll()
            return
        if not check_network():
            return
        self._stop_autostart_net_poll()
        # 删除日期检查，每次开机都播报
        self._chat_widget.add_ai_message(_AUTOSTART_WELCOME)
        self._speak(_AUTOSTART_WELCOME)
        if self.isMinimized():
            try:
                import ctypes
                hwnd = int(self.winId())
                class FLASHWINFO(ctypes.Structure):
                    _fields_ = [
                        ("cbSize",    ctypes.c_uint),
                        ("hwnd",      ctypes.c_void_p),
                        ("dwFlags",   ctypes.c_uint),
                        ("uCount",    ctypes.c_uint),
                        ("dwTimeout", ctypes.c_uint),
                    ]
                FLASHW_TRAY = 0x00000002
                FLASHW_TIMERNOFG = 0x0000000C
                info = FLASHWINFO(
                    cbSize=ctypes.sizeof(FLASHWINFO),
                    hwnd=hwnd,
                    dwFlags=FLASHW_TRAY | FLASHW_TIMERNOFG,
                    uCount=0,
                    dwTimeout=0,
                )
                ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
            except Exception:
                pass

    def _stop_autostart_net_poll(self):
        if self._autostart_net_timer:
            self._autostart_net_timer.stop()
            self._autostart_net_timer = None

    # ── API Key 配置 ──────────────────────────────────────────

    def _show_api_config(self):
        play_sound("ButtonAll.mp3")
        dlg = ApiConfigDialog(self)
        dlg.config_saved.connect(self._on_api_config_saved)
        dlg.exec_()
    
    def _on_sound_settings(self):
        from utils.sound import play_sound
        play_sound("ButtonAll.mp3")
        from gui.sound_settings_dialog import SoundSettingsDialog
        dlg = SoundSettingsDialog(self)
        dlg.exec_()

    def _on_memory_settings(self):
        from utils.sound import play_sound
        play_sound("ButtonAll.mp3")
        from gui.memory_settings_dialog import MemorySettingsDialog
        dlg = MemorySettingsDialog(self)
        dlg.exec_()

    def _show_network_settings(self):
        from utils.sound import play_sound
        play_sound("ButtonAll.mp3")
        dlg = NetworkSettingsDialog(self)
        dlg.config_saved.connect(self._on_api_config_saved)
        dlg.exec_()

    def _show_capability_center(self):
        from utils.sound import play_sound
        play_sound("ButtonAll.mp3")
        dlg = CapabilityCenter(self)
        dlg.exec_()

    def _on_api_config_saved(self):
        self._agent = AgentCore()
        self._chat_widget.add_system_tip("✅ 配置已更新，莲心已重新连接。")

        # QQ 桥接热重载（如果正在运行）
        if self._qq_bridge and self._qq_bridge.isRunning():
            self._qq_bridge.reload_bridge_config()

    # ── 全局设置 ─────────────────────────────────────────────

    def _on_settings_clicked(self):
        play_sound("ButtonAll.mp3")
        dlg = SettingsDialog(self)
        dlg.date_saved.connect(self._on_first_meet_date_saved)
        dlg.exec_()

    def _on_open_emotion_debug(self):
        """打开涟漪情感系统调试面板。"""
        play_sound("ButtonAll.mp3")
        from gui.emotional_debug_dialog import EmotionalDebugDialog
        dlg = EmotionalDebugDialog(self)
        dlg.exec_()

    def _on_first_meet_date_saved(self):
        self._accompany_stats.reload()
        self._chat_widget.add_system_tip("📅 初识日期已更新，陪伴统计已同步。")

    # ── 番茄钟 ─────────────────────────────────────────────

    def _on_pomodoro_clicked(self):
        play_sound("ButtonAll.mp3")
        if self._pomodoro_dialog is None:
            self._pomodoro_dialog = PomodoroDialog(self)
            self._pomodoro_dialog.proactive_message.connect(self._on_pomodoro_message)
            self._pomodoro_dialog.finished.connect(self._on_pomodoro_finished)
        self._pomodoro_active = True
        self._proactive_timer.stop()
        self._pomodoro_dialog.show()
        self._pomodoro_dialog.raise_()
        self._pomodoro_dialog.activateWindow()

    def _on_pomodoro_finished(self):
        self._pomodoro_active = False
        if self._proactive_scheduler.desktop_enabled or self._proactive_scheduler.qq_enabled:
            self._proactive_timer.start(5 * 60 * 1000)

    def _on_pomodoro_message(self, text: str):
        self._agent.get_history_manager().save_message(
            self._agent._session_id, "assistant", f"[番茄钟] {text}"
        )
        self._chat_widget.add_ai_message(text)
        self._speak(text)

    # ── 闹钟功能 ─────────────────────────────────────────────

    def _on_alarm_clicked(self):
        play_sound("ButtonAll.mp3")
        if self._alarm_dialog is None:
            self._alarm_dialog = AlarmDialog(self._alarm_manager, self, todo_manager=self._todo_manager)
            self._alarm_dialog.alarms_changed.connect(self._on_alarms_changed)
        self._alarm_dialog.show()
        self._alarm_dialog.raise_()
        self._alarm_dialog.activateWindow()

    def _check_alarms(self):
        due_alarms = self._alarm_manager.get_due_alarms()
        if due_alarms:
            print(f"[闹钟调试] 发现 {len(due_alarms)} 个闹钟: {[a.name for a in due_alarms]}")
        for alarm in due_alarms:
            self._on_alarm_triggered(alarm)

    def _on_alarm_triggered(self, alarm):
        self._alarm_manager.mark_fired(alarm.id)
        msg = f"⏰ {alarm.time_str} 了哦~「{alarm.name}」时间到啦！记得关闹钟！"
        self._agent.get_history_manager().save_message(
            self._agent._session_id, "assistant", f"[闹钟] {msg}"
        )
        self._chat_widget.add_ai_message(msg)
        self._speak(msg)
        repeat_text = REPEAT_LABELS.get(alarm.repeat, "仅一次")
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("⏰ 闹钟")
        msg_box.setText(f"「{alarm.name}」时间到啦！\n\n时间：{alarm.time_str}\n重复：{repeat_text}")
        msg_box.setIcon(QMessageBox.Information)
        snooze_btn = msg_box.addButton("再响5分钟", QMessageBox.AcceptRole)
        msg_box.addButton("关闭", QMessageBox.RejectRole)
        def on_button_clicked(btn):
            if btn == snooze_btn:
                from datetime import datetime, timedelta
                snooze_time = (datetime.now() + timedelta(minutes=5)).strftime("%H:%M")
                self._alarm_manager.add_alarm(
                    name=f"{alarm.name}(贪睡)",
                    time_str=snooze_time,
                    repeat="once"
                )
                self._chat_widget.add_system_tip(f"⏰ {alarm.name} 已推迟5分钟")
        msg_box.buttonClicked.connect(on_button_clicked)
        msg_box.show()

    def _on_alarms_changed(self):
        pass

    # ── 倒计时管理（主窗口统一处理）────────────────────────────

    def _check_countdowns(self):
        finished = self._alarm_manager.update_countdowns()
        for cd in finished:
            self._on_countdown_finished(cd.name, cd.total_seconds)

    def _on_countdown_finished(self, name: str, total_seconds: int):
        h = total_seconds // 3600
        m = (total_seconds % 3600) // 60
        s = total_seconds % 60
        duration_parts = []
        if h > 0:
            duration_parts.append(f"{h}小时")
        if m > 0 or h > 0:
            duration_parts.append(f"{m}分钟")
        duration_parts.append(f"{s}秒")
        duration_str = "".join(duration_parts)
        msg = f"⏰ 倒计时结束啦！「{name}」的{duration_str}已经过去啦~"
        self._agent.get_history_manager().save_message(
            self._agent._session_id, "assistant", f"[倒计时] {msg}"
        )
        self._chat_widget.add_ai_message(msg)
        self._speak(msg)

    def _on_diary_finished(self, success: bool, result: str):
        if success:
            self._chat_widget.add_system_tip(f"📔 莲心已写好 {result} 的日记")
            # 播放写完成音效
            try:
                if not pygame.mixer.get_init():
                    pygame.mixer.init()
                sound_path = Path(__file__).parent.parent / "assets" / "sound" / "write.mp3"
                if sound_path.exists():
                    pygame.mixer.Sound(str(sound_path)).play()
                else:
                    print(f"[写日记音效] 文件不存在: {sound_path}")
            except Exception as e:
                print(f"[写日记音效] 播放失败: {e}")
        else:
            self._chat_widget.add_system_tip(f"📔 日记生成失败：{result}")

    def _show_full_content(self, content):
        # 播放随机翻页音效
        try:
            # 确保 pygame.mixer 已初始化
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            sound_dir = Path(__file__).parent.parent / "assets" / "sound"
            page_files = ["page1.mp3", "page2.mp3"]
            selected = random.choice(page_files)
            sound_path = sound_dir / selected
            if sound_path.exists():
                pygame.mixer.Sound(str(sound_path)).play()
            else:
                print(f"[翻页音效] 文件不存在: {sound_path}")
        except Exception as e:
            print(f"[翻页音效] 播放失败: {e}")

        # 以下为原有弹窗代码（保持不变）
        dialog = QDialog(self)
        dialog.setWindowTitle("完整日记")
        dialog.setMinimumSize(500, 400)
        dialog.resize(550, 450)
        
        dialog.setStyleSheet("""
            QDialog {
                background-color: #FDF8F0;
            }
        """)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        
        text_edit = QTextEdit()
        text_edit.setPlainText(content)
        text_edit.setReadOnly(True)
        text_edit.setFont(QFont("Microsoft YaHei UI", 12))
        text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #FFF8F0;
                color: #4A2A1A;
                border: 1px solid #E8D8C0;
                border-radius: 8px;
                padding: 12px;
                font-size: 12pt;
            }
            QTextEdit:focus {
                border: 1px solid #D8C8A0;
            }
        """)
        layout.addWidget(text_edit)
        
        btn = QPushButton("关闭")
        btn.setFixedSize(80, 30)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #E8D8C0;
                color: #4A2A1A;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #D8C8A0;
            }
        """)
        btn.clicked.connect(dialog.accept)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(btn)
        layout.addLayout(btn_layout)
        
        dialog.exec_()


    def _check_overdue_todos(self):
        """检查过期待办并主动提醒"""
        overdue = self._todo_manager.get_overdue_todos()
        if not overdue:
            return
        # 最多提醒3条
        for todo in overdue[:3]:
            due_str = ""
            if todo.due_time:
                try:
                    dt = datetime.fromisoformat(todo.due_time)
                    due_str = f"（原定于{dt.strftime('%Y-%m-%d %H:%M')}）"
                except:
                    pass
            msg = f"⚠️ 过期待办提醒：{todo.title}{due_str}"
            self._agent.get_history_manager().save_message(
                self._agent._session_id, "assistant", f"[提醒] {msg}"
            )
            self._chat_widget.add_ai_message(msg)
            self._speak(msg)

    # ── 主动聊天 ─────────────────────────────────────────────

    def _on_proactive_clicked(self):
        play_sound("ButtonAll.mp3")
        dlg = ProactiveDialog(self._proactive_scheduler, self)
        dlg.debug_trigger.connect(self._on_proactive_debug)
        dlg.debug_observe_signal.connect(self._on_proactive_debug_observe)
        if dlg.exec_():
            self._update_proactive_button()

    def _update_proactive_button(self):
        if self._proactive_scheduler.desktop_enabled:
            self._btn_proactive.setText("主动聊天 ●")
            self._btn_proactive.setStyleSheet("""
                QPushButton {
                    background-color: #EDFFF2;
                    color: #34C759;
                    border-radius: 6px;
                    border: 1px solid #B0ECC4;
                }
                QPushButton:hover  { background-color: #D8F5E4; }
                QPushButton:pressed{ background-color: #C0EBD2; }
            """)
        else:
            self._btn_proactive.setText("主动聊天 ○")
            self._btn_proactive.setStyleSheet("""
                QPushButton {
                    background-color: #F0F0F8;
                    color: #777777;
                    border-radius: 6px;
                    border: 1px solid #D8D8EE;
                }
                QPushButton:hover  { background-color: #E4E4F0; }
                QPushButton:pressed{ background-color: #D8D8E8; }
            """)

    def _on_proactive_tick(self):
        if self._pomodoro_active:
            return
        if not self._proactive_scheduler.should_fire():
            return
        if self._proactive_worker and self._proactive_worker.isRunning():
            return
        # 快速预检是否要观察（最终决定在 worker 线程内），给用户一个提示
        if (self._proactive_scheduler.observe_enabled
                and self._proactive_scheduler.desktop_enabled):
            self._chat_widget.add_system_tip("莲心正在悄悄观察周围…")
        self._launch_proactive_message()

    def _on_proactive_debug(self):
        if self._proactive_worker and self._proactive_worker.isRunning():
            self._chat_widget.add_system_tip("主动消息正在生成中，请稍候…")
            return
        if not self._proactive_scheduler.debug_fire():
            self._chat_widget.add_system_tip("请先开启桌面或QQ主动聊天功能再使用调试。")
            return
        self._launch_proactive_message()

    def _on_proactive_debug_observe(self, mode: str):
        """调试观察：强制走截图/摄像头观察模式。"""
        if self._proactive_worker and self._proactive_worker.isRunning():
            self._chat_widget.add_system_tip("主动消息正在生成中，请稍候…")
            return
        if not self._proactive_scheduler.observe_enabled:
            self._chat_widget.add_system_tip("请先启用调皮观察功能再使用调试。")
            return
        self._chat_widget.add_system_tip(f"正在{mode}观察中…")
        self._launch_proactive_message(force_observe=mode)

    def _launch_proactive_message(self, force_observe: str = ""):
        """生成一条主动消息。force_observe 为 "screenshot"/"camera"/"shoulder_explore" 时强制走对应观察模式。"""
        observe_mode = force_observe or self._proactive_scheduler.should_observe()
        # 肩载设备在线时，优先使用 shoulder_explore 模式
        if observe_mode and self._is_shoulder_available():
            observe_mode = "shoulder_explore"
        last_obs = self._proactive_scheduler.get_last_observation()
        self._last_proactive_was_observation = bool(observe_mode)

        self._proactive_worker = ProactiveWorker(
            self._agent.get_history_manager(),
            observation_mode=observe_mode,
            last_observation=last_obs,
            camera_index=self._proactive_scheduler.camera_index,
            camera_wait=self._proactive_scheduler.camera_wait,
            parent=self,
        )
        self._proactive_worker.observation_text.connect(
            self._on_observation_result)
        self._proactive_worker.observation_image.connect(
            self._on_observation_image)
        self._proactive_worker.response_ready.connect(self._on_proactive_response)
        self._proactive_worker.error_occurred.connect(self._on_proactive_error)
        self._proactive_worker.start()

    def _on_observation_result(self, desc: str):
        """观察完成，保存描述用于短期记忆。"""
        if desc:
            self._proactive_scheduler.set_last_observation(desc)

    def _on_observation_image(self, img_path: str, desc: str):
        """收到观察图片和视觉描述，保存并显示在聊天界面。"""
        try:
            obs_dir = Path.home() / ".lianxin" / "observations"
            obs_dir.mkdir(parents=True, exist_ok=True)
            ts = int(time.monotonic() * 1000)
            ext = Path(img_path).suffix or ".png"
            dst = obs_dir / f"obs_{ts}{ext}"
            import shutil
            shutil.copy2(img_path, dst)

            # 清理旧观察图片：保留最近 50 张
            try:
                files = sorted(obs_dir.glob("obs_*"), key=lambda p: p.stat().st_mtime, reverse=True)
                for old in files[50:]:
                    old.unlink()
            except Exception:
                pass

            self._chat_widget.add_user_image(str(dst), desc[:80], desc)
        except Exception as e:
            self._chat_widget.add_system_tip(f"[观察图片显示失败: {e}]")

    def _on_proactive_response(self, text: str):
        """主动聊天回复"""
        self._proactive_scheduler.notify_fired()
        if not text:
            return

        # 桌面主动消息
        if self._proactive_scheduler.desktop_enabled:
            self._agent.get_history_manager().save_message(
                self._agent._session_id, "assistant", f"[主动] {text}"
            )
            self._chat_widget.add_ai_message(text)

            # 如果窗口最小化，闪烁任务栏图标
            if self.isMinimized():
                self.flash_taskbar(flash_count=0)

            self._speak(text)

        # QQ 主动消息（观察消息受 observe_send_to_qq 控制）
        send_to_qq = self._proactive_scheduler.qq_enabled
        if self._last_proactive_was_observation and not self._proactive_scheduler.observe_send_to_qq:
            send_to_qq = False
        if (send_to_qq
                and self._qq_bridge
                and self._qq_bridge.isRunning()):
            self._qq_bridge.send_to_owner(text)

    def _on_proactive_error(self, err: str):
        self._chat_widget.add_system_tip(f"主动消息生成失败：{err}")

    # ── 心跳自检 ─────────────────────────────────────────────

    def _reset_heartbeat_timer(self):
        """每次用户发消息时重置倒计时。"""
        cfg = get_heartbeat_config()
        if not cfg.get("enabled", True):
            return
        delay_ms = cfg.get("delay_minutes", 5) * 60 * 1000
        self._heartbeat_check_timer.start(delay_ms)

    def _on_emotion_decay_tick(self):
        """情感衰减计时器触发，更新孤独漂移等时间衰减。"""
        try:
            from brain.emotional import get_manager as _get_emotion_mgr
            _get_emotion_mgr().update_decay_only()
        except Exception:
            pass

    def _on_heartbeat_check(self):
        """心跳自检触发：检查活跃时段后启动 Worker。"""
        cfg = get_heartbeat_config()
        if not cfg.get("enabled", True):
            return
        # 检查活跃时段
        start_str = cfg.get("active_hours_start", "08:00")
        end_str = cfg.get("active_hours_end", "23:00")
        try:
            now = datetime.now().time()
            start = datetime.strptime(start_str, "%H:%M").time()
            end = datetime.strptime(end_str, "%H:%M").time()
            if not (start <= now <= end):
                return
        except Exception:
            pass

        if self._heartbeat_check_worker and self._heartbeat_check_worker.isRunning():
            return

        self._heartbeat_check_worker = HeartbeatWorker(self._agent._session_id)
        self._heartbeat_check_worker.response_ready.connect(self._on_heartbeat_response)
        self._heartbeat_check_worker.finished_silent.connect(self._on_heartbeat_finished_silent)
        self._heartbeat_check_worker.start()

    def _on_heartbeat_response(self, text: str):
        """心跳自检有提醒内容，显示给用户。"""
        self._agent.get_history_manager().save_message(
            self._agent._session_id, "assistant", f"[心跳提醒] {text}"
        )
        self._chat_widget.add_ai_message(text)
        if self.isMinimized():
            self.flash_taskbar(flash_count=0)
        self._speak(text)

    def _on_heartbeat_finished_silent(self):
        """心跳自检静默完成（无需提醒或失败）。"""

    def _on_heartbeat_btn_clicked(self):
        """切换心跳自检开关。"""
        from utils.sound import play_sound
        play_sound("ButtonAll.mp3")
        cfg = get_heartbeat_config()
        new_enabled = not cfg.get("enabled", True)
        from config import save_heartbeat_config
        save_heartbeat_config({**cfg, "enabled": new_enabled})
        self._update_heartbeat_button()
        if new_enabled:
            self._reset_heartbeat_timer()
            self._chat_widget.add_system_tip("心跳自检已开启，对话结束后会自动检查遗漏事项")
        else:
            self._heartbeat_check_timer.stop()
            self._chat_widget.add_system_tip("心跳自检已关闭")

    def _update_heartbeat_button(self):
        """更新心跳自检按钮样式。"""
        cfg = get_heartbeat_config()
        if cfg.get("enabled", True):
            self._btn_heartbeat.setText("心跳自检 ●")
            self._btn_heartbeat.setStyleSheet("""
                QPushButton {
                    background-color: #EDFFF2;
                    color: #34C759;
                    border-radius: 6px;
                    border: 1px solid #B0ECC4;
                }
                QPushButton:hover  { background-color: #D8F5E4; }
                QPushButton:pressed{ background-color: #C0EBD2; }
            """)
        else:
            self._btn_heartbeat.setText("心跳自检 ○")
            self._btn_heartbeat.setStyleSheet("""
                QPushButton {
                    background-color: #F0F0F8;
                    color: #777777;
                    border-radius: 6px;
                    border: 1px solid #D8D8EE;
                }
                QPushButton:hover  { background-color: #E4E4F0; }
                QPushButton:pressed{ background-color: #D8D8E8; }
            """)

    def _is_shoulder_available(self) -> bool:
        """检查肩载设备（ESP32-CAM）是否在线（通过 socket 探测）。"""
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            result = s.connect_ex(("192.168.43.251", 81))
            s.close()
            return result == 0
        except Exception:
            return False

    # ── 待机模式（文件中转模式）────────────────────────────────────────────

    def _on_standby_clicked(self):
        from utils.sound import play_sound
        play_sound("DaiJiMoShi.mp3")
        if self._standby_state == "IDLE":
            self._enter_standby()
        else:
            self._exit_standby()

    def _enter_standby(self):
        """开启待机模式：启动阿里云语音识别子进程"""
        if self._standby_state != "IDLE":
            return
        self._standby_state = "STANDBY"
        self._char_widget.enter_standby()
        self._is_waiting_for_response = False

        # 从配置获取小纸条文件路径
        from utils.settings import get_settings
        settings = get_settings()
        self._note_file = Path(settings.note_file_path)
        
        # 确保目录存在
        self._note_file.parent.mkdir(parents=True, exist_ok=True)
        self._note_file.write_text("", encoding="utf-8")

        # 启动阿里云语音识别子进程
        import subprocess
        self._stt_process = subprocess.Popen(
            ["python", "aliyun_stt.py"],
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        )

        # 启动轮询定时器
        self._note_poll_timer = QTimer(self)
        self._note_poll_timer.timeout.connect(self._check_note_file)
        self._note_poll_timer.start(2000)

        # 超时定时器
        self._note_timeout_timer = QTimer(self)
        self._note_timeout_timer.setSingleShot(True)
        self._note_timeout_timer.timeout.connect(self._on_note_timeout)

        self._update_standby_button()
        self._chat_widget.add_system_tip('—— 待机模式已开启，直接说话，说完请说「完毕」——')

    def _exit_standby(self):
        """关闭待机模式：终止阿里云子进程并停止监听"""
        self._standby_state = "IDLE"
        self._char_widget.exit_standby()
        
        # 终止子进程
        if self._stt_process:
            self._stt_process.terminate()
            self._stt_process = None
        
        # 停止定时器
        if self._note_poll_timer:
            self._note_poll_timer.stop()
        if self._note_timeout_timer:
            self._note_timeout_timer.stop()
        
        self._update_standby_button()
        self._chat_widget.add_system_tip("—— 待机模式已关闭 ——")

    def _update_standby_button(self):
        """根据当前待机状态更新顶部栏待机按钮样式"""
        is_active = self._standby_state == "STANDBY"
        if is_active:
            self._btn_standby.setText("🌙 待机 ●")
            self._btn_standby.setStyleSheet("""
                QPushButton {
                    background-color: #EEF0FF;
                    color: #5060DD;
                    border-radius: 6px;
                    border: 1px solid #C0C8F8;
                }
                QPushButton:hover  { background-color: #E4E8FF; }
                QPushButton:pressed{ background-color: #D8DCFF; }
            """)
        else:
            self._btn_standby.setText("🌙 待机")
            self._btn_standby.setStyleSheet("""
                QPushButton {
                    background-color: #F0F0F8;
                    color: #777777;
                    border-radius: 6px;
                    border: 1px solid #D8D8EE;
                }
                QPushButton:hover  { background-color: #E4E4F0; }
                QPushButton:pressed{ background-color: #D8D8E8; }
            """)

    def _check_note_file(self):
        """轮询检查小纸条.txt"""
        if self._is_waiting_for_response:
            return
        
        if not self._note_file or not self._note_file.exists():
            return
        
        content = self._note_file.read_text(encoding="utf-8").strip()
        if not content:
            return
        
        # 检测「完毕」关键词
        if "完毕" in content:
            # 取最后一个「完毕」，避免前面的空"完毕"吞掉后面的有效内容
            # 例："完毕。\n今天是几月几号完毕？" → query = "今天是几月几号"
            last_idx = content.rfind("完毕")
            query = content[:last_idx].replace("完毕", "")

            # 行级去重：Aliyun STT 的 on_sentence_end 可能对同一句话触发两次，
            # 导致内容重复写入小纸条。用 dict.fromkeys 保持顺序去重。
            lines = query.split("\n")
            deduped_lines = list(dict.fromkeys(lines))
            query = "\n".join(deduped_lines).strip()

            if query:
                self._is_waiting_for_response = True
                if hasattr(self, '_note_timeout_timer') and self._note_timeout_timer:
                    self._note_timeout_timer.stop()

                self._note_file.write_text("", encoding="utf-8")
                self._on_user_message(query)
            else:
                # 纯"完毕"不含有效内容，清空本次累积继续监听
                self._note_file.write_text("", encoding="utf-8")
                self._is_waiting_for_response = False
                if hasattr(self, '_note_timeout_timer') and self._note_timeout_timer:
                    self._note_timeout_timer.stop()
                self._chat_widget.add_system_tip("没有识别到内容，请重新说话")
        else:
            if hasattr(self, '_note_timeout_timer') and not self._note_timeout_timer.isActive():
                self._note_timeout_timer.start(30000)
                self._chat_widget.add_system_tip("🎤 正在收听，说完请说「完毕」")

    def _on_note_timeout(self):
        """用户 30 秒内没说「发送」，自动清空重新监听"""
        if self._standby_state != "STANDBY":
            return

        if self._note_file:
            self._note_file.write_text("", encoding="utf-8")

        self._is_waiting_for_response = False
        self._chat_widget.add_system_tip("⏰ 超时未收到「完毕」，已清空，请重新说话")
        
    def _restart_listening(self):
        """回复完成后，重新启动监听"""
        if self._standby_state != "STANDBY":
            return
        QTimer.singleShot(1000, self._actually_restart_listening)


    def _actually_restart_listening(self):
        if self._standby_state != "STANDBY":
            return
        if self._note_file:
            self._note_file.write_text("", encoding="utf-8")
        self._is_waiting_for_response = False
        # 轮询定时器已经在运行，无需额外操作
        self._chat_widget.add_system_tip("🎤 继续监听中，说完请说「完毕」")


    def _on_clear_note(self):
        """手动清空小纸条"""
        if self._note_file and self._note_file.exists():
            self._note_file.write_text("", encoding="utf-8")
            self._chat_widget.add_system_tip("🗑️ 已手动清空小纸条")


    # ── 图片视觉理解处理 ───────────────────────────────────────

    def _on_user_image(self, image_path: str):
        """处理用户粘贴或拖拽的图片 — 复制到托管目录后自动调用视觉理解 API"""
        # 复制到托管目录，确保聊天气泡不会因原图被删而失效
        managed = self._save_managed_image(image_path)
        display_path = managed or image_path
        self._chat_widget.add_user_image(display_path, ocr_text="🔍 分析中...")
        self._vision_image_worker = _ImageVisionWorker(display_path, self)
        self._vision_image_worker.finished.connect(lambda desc: self._on_vision_finished(display_path, desc))
        self._vision_image_worker.error.connect(self._on_vision_error)
        self._vision_image_worker.start()

    def _save_managed_image(self, src_path: str) -> str | None:
        """将图片复制到托管目录 ~/.lianxin/images/，保留最近 100 张。返回新路径，失败返回 None。"""
        try:
            img_dir = Path.home() / ".lianxin" / "images"
            img_dir.mkdir(parents=True, exist_ok=True)
            ts = int(time.monotonic() * 1000)
            ext = Path(src_path).suffix or ".png"
            dst = img_dir / f"img_{ts}{ext}"
            import shutil
            shutil.copy2(src_path, dst)
            # 清理旧图：保留最近 100 张
            try:
                files = sorted(img_dir.glob("img_*"), key=lambda p: p.stat().st_mtime, reverse=True)
                for old in files[100:]:
                    old.unlink()
            except Exception:
                pass
            return str(dst)
        except Exception:
            return None

    def _on_vision_finished(self, image_path: str, description: str):
        """视觉分析完成：更新图片气泡 + 将描述注入对话"""
        self._chat_widget._hide_thinking()
        # 移除旧的"分析中..."气泡
        last_index = self._chat_widget._layout.count() - 2
        if last_index >= 0:
            item = self._chat_widget._layout.takeAt(last_index)
            if item.widget():
                item.widget().deleteLater()
        summary = description[:100] + "..." if len(description) > 100 else description
        self._chat_widget.add_user_image(image_path, ocr_text=summary, full_text=description)

        context = f"[用户发了一张图片，视觉分析结果如下]\n{description}\n\n请根据你看到的内容自然地回应，描述你看到了什么。"
        self._send_user_text_to_agent(context, skip_bubble=True)

    def _on_vision_error(self, err: str):
        """视觉分析失败处理"""
        self._chat_widget.add_system_tip(f"图片分析失败：{err}")
        self._send_user_text_to_agent(f"[图片分析失败] {err}，请告知用户。", skip_bubble=True)

    def _send_user_text_to_agent(self, text: str, skip_bubble: bool = False):
        """内部方法：将文字作为用户消息发送给 AI，并可选择跳过添加用户气泡"""
        # 停止任何正在播放的语音
        try:
            from skills.语音合成.tools import stop_voice_playback
            stop_voice_playback()
        except Exception:
            pass
        self._speak_voice_used = False
        from brain.tools import set_diary_message_source
        set_diary_message_source(self._get_today_messages)
        from brain.intent_router import get_router
        route_result = get_router().route(text)
        is_chat = route_result.route == "chat"
        self._proactive_scheduler.notify_user_active()
        self._reset_heartbeat_timer()
        self._set_thinking_state()
        self._agent_worker = AgentWorker(self._agent, text, self, disable_tools=is_chat)
        self._last_route_result = route_result
        self._agent_worker.response_ready.connect(self._on_ai_response)
        self._agent_worker.progress_update.connect(self._on_progress_update)
        self._agent_worker.tool_called.connect(self._on_tool_called)
        self._agent_worker.error_occurred.connect(self._on_error)
        self._agent_worker.start()
        self._input_panel.show_interrupt_bar(self._agent_worker)



    # ── 窗口关闭 ─────────────────────────────────────────────

    def closeEvent(self, event):
        # 检查是否启用退出确认
        if self._global_settings.show_exit_confirmation:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("退出")
            msg_box.setText("诶！？不打算继续陪我一会儿了吗？(´ﾟдﾟ`)！")
            btn_yes = msg_box.addButton("待会儿见哦~", QMessageBox.YesRole)
            btn_no = msg_box.addButton("抱歉我手滑了！", QMessageBox.NoRole)
            msg_box.setDefaultButton(btn_no)
            msg_box.exec_()
            if msg_box.clickedButton() != btn_yes:
                msg = "噢耶！我就知道你想继续陪我！ヾ(*´∀ ˋ*)" 
                self._agent.get_history_manager().save_message(
                    self._agent._session_id, "assistant", f"[互动] {msg}"
                )
                self._chat_widget.add_ai_message(msg)
                self._speak(msg)
                event.ignore()
                return

        # ----- 新增：关闭前停止音乐并记录最后一次播放时长 -----
        if self.music_playing:
            self._stop_music()       # 该方法会统计当前歌曲播放时长并停止
        # -------------------------------------------------

        # 以下是原有关闭逻辑（确认退出时执行）
        self._accompany_stats.end_session()
        self._proactive_timer.stop()
        self._heartbeat_check_timer.stop()
        self._alarm_timer.stop()
        self._countdown_timer.stop()
        self._todo_reminder_timer.stop()
        self._stop_autostart_net_poll()
        self._save_music_state()
        if self._pomodoro_dialog:
            self._pomodoro_dialog.close()
        
        # ── 停止待机模式相关线程（新版）──
        if hasattr(self, '_note_poll_timer') and self._note_poll_timer:
            self._note_poll_timer.stop()
        if hasattr(self, '_note_timeout_timer') and self._note_timeout_timer:
            self._note_timeout_timer.stop()
        
        for worker in (self._agent_worker, self._voice_worker,
                    self._speaker_worker, self._proactive_worker):
            if worker and worker.isRunning():
                worker.quit()
                worker.wait(2000)

        self._speaker.stop()

        # ── 停止 QQ 桥接 ────────────────────────────────────
        if self._qq_bridge and self._qq_bridge.isRunning():
            self._qq_bridge.stop()
            self._qq_bridge.wait(3000)

        # ── 关闭 Galgame 窗口 ──────────────────────────────
        self._setup_galgame_hotkey(register=False)
        if self._tachie_win:
            self._tachie_win.close()
            self._tachie_win = None
        if self._galgame_dialog:
            self._galgame_dialog.close()
            self._galgame_dialog = None

        event.accept()



    def _on_camera_capture(self):
        play_sound("ButtonAll.mp3")
        """弹出摄像头预览对话框，拍照后直接进入 OCR 流程"""
        from gui.camera_dialog import CameraDialog
        dlg = CameraDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            img_path = dlg.get_photo_path()
            if img_path and os.path.exists(img_path):
                self._on_user_image(img_path)
            else:
                self._chat_widget.add_system_tip("拍照失败，未获取到图片")
        # 如果用户取消，什么都不做

    def _on_camera_photo_taken(self, image_path: str):
        if not image_path:
            self._chat_widget.add_system_tip("❌ 拍照失败，请检查摄像头是否已连接。")
            return
        # 直接复用现有的图片处理流程
        self._on_user_image(image_path)

    def _open_diary_dialog(self):
        play_sound("OpenDiary.mp3")
        dlg = DiaryDialog(None, main_window=self)
        dlg.diary_changed.connect(self._refresh_diary_display)
        dlg.exec_()

    def _refresh_diary_display(self):
        """刷新日记显示（预留）"""
        pass

    def regenerate_diary_by_date(self, date_str: str):
        """从设置对话框调用：手动重新生成指定日期的日记"""
        # 需要从对话历史中获取该日期的消息
        mgr = self._agent.get_history_manager()
        session_id = self._agent._session_id
        all_messages = mgr.get_messages(session_id)
        
        # 筛选指定日期的消息
        date_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in all_messages
            if m["timestamp"].startswith(date_str)
        ]
        
        if not date_messages:
            self._chat_widget.add_system_tip(f"未找到 {date_str} 的对话记录，无法生成日记。")
            return
        
        cfg = get_diary_config()
        max_messages = cfg.get("max_messages", 30)
        direction = cfg.get("direction", "latest")
        
        if direction == "earliest":
            selected = date_messages[:max_messages]
        else:
            selected = date_messages[-max_messages:] if len(date_messages) > max_messages else date_messages
        
        self._diary_worker = DiaryWorker(date_str, selected)
        self._diary_worker.finished.connect(self._on_diary_finished)
        self._diary_worker.start()

    def _has_today_diary(self) -> bool:
        from utils.diary import has_diary_for_date
        today_str = datetime.now().strftime("%Y-%m-%d")
        return has_diary_for_date(today_str)

    def _get_today_messages(self):
        today_str = datetime.now().strftime("%Y-%m-%d")
        mgr = self._agent.get_history_manager()
        session_id = self._agent._session_id
        all_messages = mgr.get_messages(session_id)
        today_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in all_messages
            if m["timestamp"].startswith(today_str)
        ]
        return today_messages

    def _write_diary_if_needed(self, force=False):
        """如果当天没有日记（或者force=True且确认覆盖），则生成日记"""
        if not force and self._has_today_diary():
            return
        
        today_messages = self._get_today_messages()
        if not today_messages:
            self._chat_widget.add_system_tip("今天没有对话记录，无法生成日记。")
            return
        
        cfg = get_diary_config()
        max_messages = cfg.get("max_messages", 30)
        direction = cfg.get("direction", "latest")
        
        if direction == "earliest":
            selected = today_messages[:max_messages]
        else:
            selected = today_messages[-max_messages:] if len(today_messages) > max_messages else today_messages
        
        today_str = datetime.now().strftime("%Y-%m-%d")
        self._diary_worker = DiaryWorker(today_str, selected)
        self._diary_worker.finished.connect(self._on_diary_finished)
        self._diary_worker.start()


    def _write_diary_now(self):
        play_sound("ButtonAll.mp3")
        if self._has_today_diary():
            reply = QMessageBox.question(
                self, "日记已存在",
                "今天已经有一篇日记了，是否重新生成？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        self._write_diary_if_needed(force=True)


    def _setup_diary_timer(self):
        """根据配置的定时时间，设置日记定时器（每天一次）"""
        cfg = get_diary_config()
        if not cfg.get("scheduled_enabled", True):
            self._diary_timer.stop()
            return
        target_time_str = cfg.get("scheduled_time", "23:55")
        target_time = QTime.fromString(target_time_str, "HH:mm")
        now = QTime.currentTime()
        # 计算距离目标时间还有多少毫秒
        msecs = now.msecsTo(target_time)
        if msecs < 0:  # 今天的时间已过，则改为明天
            msecs = 24 * 60 * 60 * 1000 + msecs
        
        self._diary_timer.start(msecs)
        # 注意：QTimer 单次触发后，我们在 _on_diary_timer_timeout 中会重新启动


    def _on_diary_timer_timeout(self):
        """定时时间到，尝试写日记（如果当天无日记）"""
        if not self._has_today_diary():
            self._write_diary_if_needed(force=False)
        # 重新设置第二天的定时
        self._setup_diary_timer()

    def _load_music_playlist(self):
        """扫描 assets/music/ 目录下的 mp3 文件"""
        music_dir = Path(__file__).parent.parent / "assets" / "music"
        if music_dir.exists():
            self.playlist = sorted(music_dir.glob("*.mp3"))
        else:
            self.playlist = []
        self._update_music_ui()

    def _update_music_ui(self):
        """更新音乐盒界面（播放按钮状态、歌名等）"""
        if not self.playlist:
            self._char_widget.get_music_play_button().setEnabled(False)
            self._char_widget.set_music_title("无音乐文件")
            return
        self._char_widget.get_music_play_button().setEnabled(True)
        if 0 <= self.current_track_index < len(self.playlist):
            title = self.playlist[self.current_track_index].stem
            self._char_widget.set_music_title(title)
        else:
            self._char_widget.set_music_title("未知")

    def _play_music(self, start_sec=0):
        if not self.playlist:
            return
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.load(str(self.playlist[self.current_track_index]))
        pygame.mixer.music.set_volume(self._global_settings.music_volume)
        pygame.mixer.music.play(start=start_sec)
        self.music_playing = True
        self.current_offset = start_sec
        self.current_position = start_sec
        self.current_song_start_time = time.time() - start_sec   # 记录开始时间（考虑偏移）
        self._char_widget.spectrum.set_playing(True)  
        self._char_widget.get_music_play_button().setIcon(self._char_widget.icon_pause)
        # 获取总时长
        try:
            from mutagen.mp3 import MP3 # type: ignore
            audio = MP3(str(self.playlist[self.current_track_index]))
            self.current_duration = int(audio.info.length)
        except:
            self.current_duration = 0
        self._update_time_display(start_sec)
        # 启动进度更新定时器
        self._progress_timer = QTimer(self)
        self._progress_timer.timeout.connect(self._update_progress)
        self._progress_timer.start(500)
        # 监听播放结束
        self._music_check_timer = QTimer(self)
        self._music_check_timer.timeout.connect(self._on_music_check)
        self._music_check_timer.start(500)

    def _stop_music(self):
    # 更新当前歌曲的播放时长（如果正在播放且已记录开始时间）
        if self.music_playing and self.current_song_start_time is not None:
            elapsed = int(time.time() - self.current_song_start_time)
            if elapsed > 0:
                self.music_stats.update_song(str(self.playlist[self.current_track_index]), elapsed)
        pygame.mixer.music.stop()
        self.music_playing = False
        self._char_widget.spectrum.set_playing(False) 
        self._char_widget.get_music_play_button().setIcon(self._char_widget.icon_play)
        if hasattr(self, '_music_check_timer'):
            self._music_check_timer.stop()

    def _on_music_check(self):
        if not pygame.mixer.music.get_busy() and self.music_playing:
            # 播放结束，计算本次播放时长
            if self.current_song_start_time is not None:
                elapsed = int(time.time() - self.current_song_start_time)
                if elapsed > 0:
                    self.music_stats.update_song(str(self.playlist[self.current_track_index]), elapsed)
            self._next_track()

    def _prev_track(self):
        play_sound("ButtonMusic.mp3")
        self._stop_music()
        if self.loop_mode == "random":
            import random
            self.current_track_index = random.randint(0, len(self.playlist)-1)
        else:
            self.current_track_index = (self.current_track_index - 1) % len(self.playlist) if self.playlist else 0
        self._update_music_ui()
        self._play_music()

    def _next_track(self):
        play_sound("ButtonMusic.mp3")
        self._stop_music()
        if self.loop_mode == "one":
            # 单曲循环：索引不变
            pass
        elif self.loop_mode == "random":
            # 随机播放
            import random
            self.current_track_index = random.randint(0, len(self.playlist)-1)
        else:
            # 列表循环
            self.current_track_index = (self.current_track_index + 1) % len(self.playlist) if self.playlist else 0
        self._update_music_ui()
        self._play_music()

    def _on_music_play_pause(self):
        play_sound("ButtonMusic.mp3")
        if not self.playlist:
            return
        if self.music_playing:
            self._pause_music()
        else:
            self._resume_music()

    def _resume_music(self):
        if not self.music_playing and self.playlist:
            pygame.mixer.music.unpause()
            self.music_playing = True
            self._char_widget.spectrum.set_playing(True)
            self._char_widget.get_music_play_button().setIcon(self._char_widget.icon_pause)

    def _pause_music(self):
        if self.music_playing:
            pygame.mixer.music.pause()
            self.music_playing = False
            self._char_widget.spectrum.set_playing(False)   
            self._char_widget.get_music_play_button().setIcon(self._char_widget.icon_play)


    def _on_music_volume_changed(self, value):
        vol = value / 100.0
        self._global_settings.music_volume = vol
        self._char_widget.spectrum.set_volume(vol) 
        # 确保 mixer 已初始化
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        # 只有当前有音乐播放或 mixer 已加载音乐时才设置音量，否则只保存数值
        try:
            pygame.mixer.music.set_volume(vol)
        except pygame.error:
            pass  # 如果还没有加载音乐，忽略错误

    def _restore_music_state(self):
        self.current_track_index = self._global_settings.music_playlist_index
        self._update_music_ui()
        if self._global_settings.music_is_playing and self.playlist:
            start_pos = self._global_settings.music_position
            # 确保位置不超过总时长（避免出错）
            if start_pos >= self.current_duration:
                start_pos = 0
            self._play_music(start_sec=start_pos)
        else:
            self.music_playing = False
            self._char_widget.get_music_play_button().setIcon(self._char_widget.icon_play)

    def _save_music_state(self):
        self._global_settings.music_playlist_index = self.current_track_index
        self._global_settings.music_is_playing = self.music_playing
        self._global_settings.music_position = self.current_position  # 保存进度

    def _open_music_list(self):
        play_sound("ButtonMusic.mp3")
        if not self.playlist:
            return
        from gui.music_list_dialog import MusicListDialog
        dlg = MusicListDialog(self.playlist, self.current_track_index, self)
        dlg.track_selected.connect(self._switch_to_track)
        dlg.order_changed.connect(self._reorder_playlist)   # 新增
        dlg.exec_()


    def _reorder_playlist(self, new_order):
        """当用户在音乐列表中拖拽排序后，更新主窗口的播放列表"""
        if not new_order:
            return
        # 保存当前正在播放的歌曲路径
        current_path = self.playlist[self.current_track_index] if self.playlist else None
        self.playlist = new_order
        # 更新索引
        if current_path in self.playlist:
            self.current_track_index = self.playlist.index(current_path)
        else:
            self.current_track_index = 0
        self._update_music_ui()
        # 如果正在播放，重新加载当前歌曲（保持播放状态）
        if self.music_playing:
            current_pos = self.current_position
            self._stop_music()
            self._play_music(start_sec=current_pos)
        else:
            self._char_widget.get_music_play_button().setIcon(self._char_widget.icon_play)

    def _switch_to_track(self, index):
        """切换到指定索引的歌曲"""
        if index == self.current_track_index:
            return
        self._stop_music()
        self.current_track_index = index
        self._update_music_ui()
        self._play_music()
        
    def _update_progress(self):
        if self.music_playing and pygame.mixer.music.get_busy():
            pos = self.current_offset + (pygame.mixer.music.get_pos() // 1000)
            if pos < 0:
                pos = 0
            self.current_position = pos   # 保存位置
            self._update_time_display(pos)
            if self.current_duration > 0:
                progress = int(pos / self.current_duration * 100)
                self._char_widget.get_music_progress().setValue(progress)
        else:
            if self._progress_timer:
                self._progress_timer.stop()

    def _update_time_display(self, current_sec):
        current_str = f"{current_sec // 60:02d}:{current_sec % 60:02d}"
        total_str = f"{self.current_duration // 60:02d}:{self.current_duration % 60:02d}"
        self._char_widget.get_time_label().setText(f"{current_str} / {total_str}")

    def _seek_to(self):
        value = self._char_widget.get_music_progress().value()
        if self.music_playing and self.current_duration > 0:
            target_sec = int(value / 100 * self.current_duration)
            was_playing = self.music_playing
            pygame.mixer.music.stop()
            pygame.mixer.music.play(start=target_sec)
            self.current_offset = target_sec   # 记录偏移
            if not was_playing:
                pygame.mixer.music.pause()
            else:
                self.music_playing = True
            self._update_time_display(target_sec)
            # 进度条值已在拖动时改变，无需再次 setValue

    def _on_loop_mode_clicked(self):
        play_sound("ButtonMusic.mp3")
        if self.loop_mode == "list":
            self.loop_mode = "one"
            self._char_widget.get_loop_button().setIcon(self._char_widget.icon_loop_one)
            self._char_widget.get_loop_button().setToolTip("循环模式: 单曲循环")
        elif self.loop_mode == "one":
            self.loop_mode = "random"
            self._char_widget.get_loop_button().setIcon(self._char_widget.icon_random)
            self._char_widget.get_loop_button().setToolTip("循环模式: 随机播放")
        else:
            self.loop_mode = "list"
            self._char_widget.get_loop_button().setIcon(self._char_widget.icon_loop)
            self._char_widget.get_loop_button().setToolTip("循环模式: 列表循环")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            self._on_music_play_pause()
        elif event.key() == Qt.Key_Left:
            self._prev_track()
        elif event.key() == Qt.Key_Right:
            self._next_track()
        else:
            super().keyPressEvent(event)

    def _open_reminder_dialog(self):
        play_sound("ButtonMusic.mp3")
        from gui.reminder_dialog import ReminderDialog
        dlg = ReminderDialog(self)
        dlg.show()

    def _touch_heartbeat(self):
        """轻量心跳：由 Qt 定时器每 5 秒调用一次，仅更新时间戳。"""
        self._heartbeat_time = time.monotonic()
        if self._heartbeat_frozen:
            self._heartbeat_frozen = False
            print(f"[看门狗] ✅ 主线程已恢复")

    def _watchdog_loop(self):
        """后台线程：轮询心跳时间戳，卡顿时实时抓取主线程调用堆栈。"""
        from PyQt5.QtWidgets import QApplication
        import traceback
        while True:
            time.sleep(1.0)
            elapsed = time.monotonic() - self._heartbeat_time
            if elapsed <= 7.0:
                continue
            # 如果当前有模态对话框打开，不误报冻结
            if QApplication.activeModalWidget() is not None:
                self._heartbeat_frozen = False
                self._heartbeat_time = time.monotonic()
                continue
            if not self._heartbeat_frozen:
                # 首次检测到卡顿，立即抓堆栈
                self._heartbeat_frozen = True
                for t in threading.enumerate():
                    if t.name == 'MainThread':
                        frame = sys._current_frames().get(t.ident)
                        if frame:
                            stacks = "".join(traceback.format_stack(frame))
                            print(f"[看门狗] ⚠️ 主线程已卡住 {elapsed:.1f} 秒！调用堆栈：\n{stacks}")
                        else:
                            print(f"[看门狗] ⚠️ 主线程已卡住 {elapsed:.1f} 秒（无法获取堆栈）")
                        break
            elif round(elapsed) % 30 == 0:
                # 长时间卡顿，每 30 秒再抓一次堆栈看有没有变化
                for t in threading.enumerate():
                    if t.name == 'MainThread':
                        frame = sys._current_frames().get(t.ident)
                        if frame:
                            stacks = "".join(traceback.format_stack(frame))
                            print(f"[看门狗] 🔴 仍在卡顿中 ({elapsed:.0f}s) 堆栈：\n{stacks}")
                        break

    def _check_reminders(self):
        due = self.reminder_manager.get_due_reminders()

        if not due:
            return

        # 提取所有提醒名称（最多5条，避免过长）
        reminder_names = [r["name"] for r in due[:5]]
        reminder_times = [r["time"] for r in due[:5]]

        if self._global_settings.global_smart_reminder:
            # 智能模式：将多个提醒名称用"、"连接，传递给合并版 Worker
            combined_names = "、".join(reminder_names)
            worker = SmartReminderWorker(combined_names, is_combined=True)   # 注意参数
            worker.finished.connect(self._on_smart_reminder_ready)
            worker.start()
        else:
            # 非智能模式：固定句式拼接
            if len(reminder_names) == 1:
                msg = f"⏰ 提醒：{reminder_names[0]}（{reminder_times[0]}）"
            else:
                items = [f"{name}（{time}）" for name, time in zip(reminder_names, reminder_times)]
                msg = f"⏰ 有几个提醒：{', '.join(items)}"
            self._chat_widget.add_ai_message(msg)
            self._speak(msg)

        # 将所有到期的提醒标记为已触发
        for r in due:
            self.reminder_manager.mark_triggered(r["id"])

    def _on_smart_reminder_ready(self, text: str):
        if self._agent_worker and self._agent_worker.isRunning():
            QTimer.singleShot(5000, lambda: self._do_reminder(text))
        else:
            self._do_reminder(text)

    def _do_reminder(self, text: str):
        self._chat_widget.add_ai_message(text)
        self._speak(text)

    # ── QQ 桥接 ─────────────────────────────────────────────

    def _on_qq_bridge_clicked(self):
        """点击 QQ聊天 按钮：打开 QQ 聊天面板（含桥接开关和参数设置）。"""
        play_sound("ButtonAll.mp3")
        self._heartbeat_time = time.monotonic()
        dlg = QqSettingsDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            if self._qq_bridge and self._qq_bridge.isRunning():
                self._qq_bridge.reload_timing_config()

    def _start_qq_bridge(self):
        """创建并启动 QQBridgeWorker"""
        if self._qq_bridge and self._qq_bridge.isRunning():
            return  # 已在运行，防止重复启动

        cfg = get_qq_bridge_config()
        if not cfg.get("qq_account"):
            QMessageBox.warning(self, "QQ聊天", "未配置 QQ 账号，请先在 user_config.json 中设置 qq_account。")
            return

        self._btn_qq_bridge.setText("QQ聊天 ◷")
        self._btn_qq_bridge.setStyleSheet("""
            QPushButton {
                background-color: #EEF0FF;
                color: #5060DD;
                border-radius: 6px;
                border: 1px solid #C0C8F8;
            }
            QPushButton:hover  { background-color: #E4E8FF; }
            QPushButton:pressed{ background-color: #D8DCFF; }
        """)

        from workers.qq_bridge_worker import QQBridgeWorker
        self._qq_bridge = QQBridgeWorker()

        # 注册 QQ 桥接到 tools 模块（供 send_file_to_qq 等工具使用）
        import brain.tools
        brain.tools._register_qq_bridge(self._qq_bridge)

        # QQ 桥接日志 → 后台打印线程（避免 print() 阻塞主线程触发的看门狗误报）
        self._qq_log_queue = queue.Queue()
        self._qq_log_thread = threading.Thread(
            target=self._qq_log_worker, daemon=True
        )
        self._qq_log_thread.start()
        self._qq_bridge.debug_log.connect(self._qq_log_queue.put_nowait)

        self._qq_bridge.connected.connect(self._on_qq_bridge_connected)
        self._qq_bridge.disconnected.connect(self._on_qq_bridge_disconnected)
        self._qq_bridge.error_occurred.connect(self._on_qq_bridge_error)
        self._qq_bridge.start()

    def _qq_log_worker(self):
        """独立线程：从队列中取出 QQ 桥接日志并输出到控制台。"""
        while True:
            msg = self._qq_log_queue.get()
            if msg is None:
                break
            print(f"[QQ桥接] {msg}")

    def _stop_qq_bridge(self):
        """停止 QQBridgeWorker"""
        if self._qq_bridge and self._qq_bridge.isRunning():
            self._qq_bridge.stop()
            self._qq_bridge.wait(3000)
        self._qq_bridge = None
        import brain.tools
        brain.tools._register_qq_bridge(None)
        self._chat_widget.add_system_tip("QQ 桥接已断开")
        self._update_qq_bridge_button()

    def _on_qq_bridge_connected(self):
        self._chat_widget.add_system_tip("✅ QQ 桥接已连接，可通过 QQ 与莲心聊天")
        self._btn_qq_bridge.setText("QQ聊天 ●")
        self._btn_qq_bridge.setStyleSheet("""
            QPushButton {
                background-color: #EDFFF2;
                color: #34C759;
                border-radius: 6px;
                border: 1px solid #B0ECC4;
            }
            QPushButton:hover  { background-color: #D8F5E4; }
            QPushButton:pressed{ background-color: #C0EBD2; }
        """)

    def _on_qq_bridge_disconnected(self, reason: str):
        self._chat_widget.add_system_tip(f"QQ 桥接已断开：{reason}")
        self._update_qq_bridge_button()

    def _on_qq_bridge_error(self, err: str):
        self._chat_widget.add_system_tip(f"⚠️ QQ 桥接错误：{err}")
        self._update_qq_bridge_button()

    def _on_qq_settings_clicked(self):
        """打开 QQ 聊天参数设置对话框。"""
        dlg = QqSettingsDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            if self._qq_bridge and self._qq_bridge.isRunning():
                self._qq_bridge.reload_timing_config()
                self._chat_widget.add_system_tip("✅ QQ 聊天参数已更新（即时生效）")

    def _update_qq_bridge_button(self):
        """根据 QQ 桥接状态更新按钮外观"""
        connected = self._qq_bridge is not None and self._qq_bridge.isRunning()
        if connected:
            self._btn_qq_bridge.setText("QQ聊天 ●")
            self._btn_qq_bridge.setStyleSheet("""
                QPushButton {
                    background-color: #EDFFF2;
                    color: #34C759;
                    border-radius: 6px;
                    border: 1px solid #B0ECC4;
                }
                QPushButton:hover  { background-color: #D8F5E4; }
                QPushButton:pressed{ background-color: #C0EBD2; }
            """)
        else:
            self._btn_qq_bridge.setText("QQ聊天 ○")
            self._btn_qq_bridge.setStyleSheet("""
                QPushButton {
                    background-color: #F0F0F8;
                    color: #777777;
                    border-radius: 6px;
                    border: 1px solid #D8D8EE;
                }
                QPushButton:hover  { background-color: #E4E4F0; }
                QPushButton:pressed{ background-color: #D8D8E8; }
            """)


class _ImageVisionWorker(QThread):
    """后台线程：调用视觉API理解图片内容。"""
    finished = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.image_path = image_path

    def run(self):
        try:
            from brain.vision import describe_image
            result = describe_image(self.image_path)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class CameraCaptureThread(QThread):
    finished = pyqtSignal(str)  # 返回图片路径或空字符串

    def run(self):
        from utils.camera import capture_from_camera
        path = capture_from_camera()
        self.finished.emit(path)