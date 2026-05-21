"""
CharacterWidget：莲心角色图像显示区域
支持状态机驱动的动画切换（待机/思考/说话/待机模式/自定义表情）
使用 GIF 动图循环播放，支持序列动画和事件触发。
"""

import os
from pathlib import Path
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QIcon
# 导入动画状态机
from gui.animation_state_machine import AnimationStateMachine

# 状态定义（用于兼容旧接口）
STATE_NORMAL   = "normal"
STATE_THINKING = "thinking"
STATE_TALKING  = "talking"

# 各状态对应的显示文字和颜色
STATE_CONFIG = {
    STATE_NORMAL:   ("● 待机中",  "#6C7BFF"),
    STATE_THINKING: ("● 思考中",  "#FF9500"),
    STATE_TALKING:  ("● 说话中",  "#34C759"),
}


class CharacterWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(400)
        self._assets_dir = Path(__file__).parent.parent / "assets"
        self._gif_dir = self._assets_dir / "GIF"
        self._current_state = STATE_NORMAL
        self._previous_mode = "normal"
        self._playing_arms_cross = False
        self._arms_cross_speech_pending = False
        # 加载自定义图标
        icons_dir = self._assets_dir / "icons"
        self.icon_play = QIcon(str(icons_dir / "play.png"))
        self.icon_pause = QIcon(str(icons_dir / "pause.png"))
        self.icon_prev = QIcon(str(icons_dir / "prev.png"))
        self.icon_next = QIcon(str(icons_dir / "next.png"))
        self.icon_list = QIcon(str(icons_dir / "list.png"))   # 新增：用于文件夹按钮
        self.icon_loop = QIcon(str(icons_dir / "loop.png"))      # 列表循环
        self.icon_loop_one = QIcon(str(icons_dir / "loop2.png")) # 单曲循环（需准备图标）
        self.icon_random = QIcon(str(icons_dir / "random.png"))  # 随机播放（需准备图标）


        self._build_ui()

        config_path = self._assets_dir / "animation_config.json"
        self.anim_machine = AnimationStateMachine(
            label=self._gif_label,
            config_path=str(config_path),
            assets_dir=str(self._gif_dir)
        )
        self.anim_machine.state_changed.connect(self._on_state_changed)
        self.anim_machine.set_mode("normal")
        self._update_status_label(STATE_NORMAL)

    def _build_ui(self):
        self.setStyleSheet("background-color: rgba(232, 235, 245, 180); border-right: 1px solid rgba(208, 212, 232, 150);")

        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignCenter)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 24, 16, 24)

        # 头像向右移动（可调整间距）
        gif_container = QHBoxLayout()
        gif_container.addSpacing(50)
        self._gif_label = QLabel()
        self._gif_label.setFixedSize(270, 480)
        self._gif_label.setAlignment(Qt.AlignCenter)
        self._gif_label.setStyleSheet("""
            QLabel {
                background-color: rgba(240, 242, 250, 200);
                border-radius: 16px;
                border: 2px solid rgba(200, 204, 238, 150);
            }
        """)
        gif_container.addWidget(self._gif_label)
        main_layout.addLayout(gif_container)

        self._state_label = QLabel("● 待机中")
        self._state_label.setAlignment(Qt.AlignCenter)
        self._state_label.setFont(QFont("Microsoft YaHei UI", 9))
        self._state_label.setStyleSheet("color: #6C7BFF; background: transparent;")
        main_layout.addWidget(self._state_label)

        # ========== 音乐盒控件（自定义图标，多行布局） ==========
        music_bar = QWidget()
        music_bar.setStyleSheet("""
            background-color: rgba(60, 60, 70, 220);
            border-radius: 20px;
            margin: 6px 8px;
            padding: 8px;
        """)
        music_main_layout = QVBoxLayout(music_bar)
        music_main_layout.setSpacing(8)
        music_main_layout.setContentsMargins(12, 8, 12, 8)

        # 第一行：播放控制按钮（使用图标）
        row1 = QHBoxLayout()
        row1.setSpacing(15)
        row1.setAlignment(Qt.AlignCenter)

        # 上一首
        self._btn_prev = QPushButton()
        self._btn_prev.setFixedSize(44, 44)
        self._btn_prev.setIcon(self.icon_prev)
        self._btn_prev.setIconSize(self._btn_prev.size())
        self._btn_prev.setCursor(Qt.PointingHandCursor)
        self._btn_prev.setStyleSheet("""
            QPushButton {
                background-color: rgba(240,240,240,0.9);
                border-radius: 22px;
                border: 1px solid #aaa;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
                border: 1px solid #6C7BFF;
            }
        """)
        row1.addWidget(self._btn_prev)

        # 播放/暂停
        self._btn_play_pause = QPushButton()
        self._btn_play_pause.setFixedSize(54, 54)
        self._btn_play_pause.setIcon(self.icon_play)
        self._btn_play_pause.setIconSize(self._btn_play_pause.size())
        self._btn_play_pause.setCursor(Qt.PointingHandCursor)
        self._btn_play_pause.setStyleSheet("""
            QPushButton {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                                  stop:0 #6C7BFF, stop:1 #4A5ADE);
                border-radius: 27px;
                border: none;
            }
            QPushButton:hover {
                background-color: #5A6AEE;
            }
        """)
        row1.addWidget(self._btn_play_pause)

        # 下一首
        self._btn_next = QPushButton()
        self._btn_next.setFixedSize(44, 44)
        self._btn_next.setIcon(self.icon_next)
        self._btn_next.setIconSize(self._btn_next.size())
        self._btn_next.setCursor(Qt.PointingHandCursor)
        self._btn_next.setStyleSheet("""
            QPushButton {
                background-color: rgba(240,240,240,0.9);
                border-radius: 22px;
                border: 1px solid #aaa;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
                border: 1px solid #6C7BFF;
            }
        """)
        row1.addWidget(self._btn_next)

        # 循环模式按钮
        self._btn_loop = QPushButton()
        self._btn_loop.setFixedSize(36, 36)
        self._btn_loop.setIcon(self.icon_loop)
        self._btn_loop.setIconSize(self._btn_loop.size())
        self._btn_loop.setCursor(Qt.PointingHandCursor)
        self._btn_loop.setToolTip("循环模式: 列表循环")
        self._btn_loop.setStyleSheet("""
            QPushButton {
                background-color: rgba(240,240,240,0.9);
                border-radius: 18px;
                border: 1px solid #aaa;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
                border: 1px solid #6C7BFF;
            }
        """)
        row1.addWidget(self._btn_loop)

        music_main_layout.addLayout(row1)

        # 第二行：进度条 + 时间标签
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.setContentsMargins(0, 0, 0, 0)

        self._music_progress = QSlider(Qt.Horizontal)
        self._music_progress.setRange(0, 100)
        self._music_progress.setValue(0)
        self._music_progress.setCursor(Qt.PointingHandCursor)
        self._music_progress.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #A0A0A8;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #C0C0FF;
                width: 10px;
                margin: -4px 0;
                border-radius: 5px;
            }
        """)
        row2.addWidget(self._music_progress, 1)

        self._time_label = QLabel("00:00 / 00:00")
        self._time_label.setFont(QFont("Microsoft YaHei UI", 8))
        self._time_label.setStyleSheet("color: #E0E0E0;")
        self._time_label.setAlignment(Qt.AlignCenter)
        row2.addWidget(self._time_label)

        music_main_layout.addLayout(row2)

        # 第三行：频谱跳动条
        from gui.spectrum_widget import SpectrumWidget
        self.spectrum = SpectrumWidget()
        music_main_layout.addWidget(self.spectrum)

        # 第四行：音量控制 + 歌名 + 文件夹按钮
        row4 = QHBoxLayout()
        row4.setSpacing(10)
        row4.setAlignment(Qt.AlignVCenter)

        self._music_volume_icon = QLabel("🔊")
        self._music_volume_icon.setFont(QFont("Segoe UI Emoji", 10))
        self._music_volume_icon.setCursor(Qt.PointingHandCursor)
        self._music_volume_icon.mousePressEvent = self._on_volume_icon_click
        row4.addWidget(self._music_volume_icon)

        self._music_volume_slider = QSlider(Qt.Horizontal)
        self._music_volume_slider.setRange(0, 100)
        self._music_volume_slider.setFixedWidth(80)
        self._music_volume_slider.setCursor(Qt.PointingHandCursor)
        self._music_volume_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #A0A0A8;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #C0C0FF;
                width: 10px;
                margin: -4px 0;
                border-radius: 5px;
            }
        """)
        row4.addWidget(self._music_volume_slider)

        self._music_title_label = QLabel("未导入音乐")
        self._music_title_label.setFont(QFont("Microsoft YaHei UI", 8))
        self._music_title_label.setStyleSheet("color: #E0E0E0;")
        self._music_title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._music_title_label.setWordWrap(False)
        self._music_title_label.setMinimumWidth(100)
        row4.addWidget(self._music_title_label, 1)

        self._btn_open_music_folder = QPushButton()
        self._btn_open_music_folder.setFixedSize(36, 36)
        self._btn_open_music_folder.setIcon(self.icon_list)
        self._btn_open_music_folder.setIconSize(self._btn_open_music_folder.size())
        self._btn_open_music_folder.setCursor(Qt.PointingHandCursor)
        self._btn_open_music_folder.setToolTip("打开音乐列表")
        self._btn_open_music_folder.setStyleSheet("""
            QPushButton {
                background-color: rgba(220,220,230,0.9);
                border-radius: 18px;
                border: 1px solid rgba(255,255,255,0.3);
            }
            QPushButton:hover {
                background-color: rgba(240,240,255,1.0);
            }
        """)
        row4.addWidget(self._btn_open_music_folder)

        music_main_layout.addLayout(row4)

        main_layout.addWidget(music_bar)

        # ========== 功能按钮区域（可滚动） ==========
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        btn_container = QWidget()
        btn_layout = QVBoxLayout(btn_container)
        btn_layout.setSpacing(8)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        self._btn_accompany = self._create_button("📊 陪伴时长统计")
        self._btn_balance   = self._create_button("💰 余额查询")
        self._btn_settings  = self._create_button("⚙️ 全局设置")
        self._btn_pomodoro  = self._create_button("🍅 番茄钟")
        self._btn_api_config = self._create_button("🔑 API Key 配置", color="#FF9500")
        self._btn_alarm      = self._create_button("⏰ 闹钟功能")
        self._btn_todo       = self._create_button("✅ 待办清单")
        self._btn_camera     = self._create_button("📷 拍照OCR")
        self._btn_vision     = self._create_button("👁 视觉", color="#FF68A8")

        btn_layout.addWidget(self._btn_accompany)
        btn_layout.addWidget(self._btn_balance)
        btn_layout.addWidget(self._btn_settings)
        btn_layout.addWidget(self._btn_pomodoro)
        btn_layout.addWidget(self._btn_api_config)
        btn_layout.addWidget(self._btn_alarm)
        btn_layout.addWidget(self._btn_todo)
        btn_layout.addWidget(self._btn_camera)
        btn_layout.addWidget(self._btn_vision)
        btn_layout.addStretch()

        scroll.setWidget(btn_container)
        main_layout.addWidget(scroll)

    def _create_button(self, text: str, color: str = "#6C7BFF") -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(32)
        btn.setFont(QFont("Microsoft YaHei UI", 9))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border-radius: 16px;
                border: none;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background-color: {self._darken_color(color)};
            }}
            QPushButton:pressed {{
                background-color: {self._darken_color(color, 20)};
            }}
        """)
        return btn

    @staticmethod
    def _darken_color(color: str, percent: int = 10) -> str:
        if color == "#6C7BFF":
            return "#5A6AEE"
        elif color == "#FF9500":
            return "#E08600"
        return color

    # ========== 音乐盒控件获取方法 ==========
    def get_music_play_button(self):
        return self._btn_play_pause

    def get_music_prev_button(self):
        return self._btn_prev

    def get_music_next_button(self):
        return self._btn_next

    def get_music_volume_slider(self):
        return self._music_volume_slider

    def get_music_volume_icon(self):
        return self._music_volume_icon

    def get_music_title_label(self):
        return self._music_title_label

    def get_open_music_folder_button(self):
        return self._btn_open_music_folder

    def get_loop_button(self):
        return self._btn_loop

    def get_music_loop_button(self):
        return self._btn_loop

    def get_music_progress(self):   
        return self._music_progress

    def get_time_label(self):
        return self._time_label

    def set_music_title(self, title: str):
        # 显示省略号处理：限制最大显示字符数（根据字体宽度估算，这里简单用长度）
        max_len = 20  # 根据你的控件宽度调整
        if len(title) > max_len:
            display_title = title[:max_len] + "..."
            self._music_title_label.setToolTip(title)   # 悬停显示完整
        else:
            display_title = title
            self._music_title_label.setToolTip("")
        self._music_title_label.setText(display_title)

    def _on_volume_icon_click(self, event):
        current = self._music_volume_slider.value()
        if current > 0:
            self._muted_volume = current
            self._music_volume_slider.setValue(0)
        else:
            if hasattr(self, '_muted_volume'):
                self._music_volume_slider.setValue(self._muted_volume)
            else:
                self._music_volume_slider.setValue(50)

    # ========== 动画控制方法（保持不变） ==========
    def set_talking(self):
        if self._playing_arms_cross:
            self._arms_cross_speech_pending = True
            return
        self.anim_machine.trigger_event("speak_start")
        self._update_status_label(STATE_TALKING)

    def set_normal(self):
        if self._playing_arms_cross:
            return
        self.anim_machine.trigger_event("speak_end")
        self.anim_machine.trigger_event("think_end")
        self._update_status_label(STATE_NORMAL)

    def set_thinking(self):
        self.start_thinking()

    def start_thinking(self):
        if self._playing_arms_cross:
            return
        self._previous_mode = self.anim_machine.current_mode
        self.anim_machine.set_mode("thinking")
        self._update_status_label(STATE_THINKING)

    def stop_thinking(self, on_finished=None):
        if self._playing_arms_cross:
            return
        if self.anim_machine.current_mode == "thinking":
            self.anim_machine.trigger_event("stop_thinking")
            QTimer.singleShot(2000, lambda: self._restore_after_thinking(on_finished))
        else:
            self._restore_after_thinking(on_finished)

    def _restore_after_thinking(self, on_finished=None):
        prev = getattr(self, '_previous_mode', 'normal')
        self.anim_machine.set_mode(prev)
        self._update_status_label(STATE_NORMAL)
        if on_finished:
            on_finished()

    def set_thinking_status(self):
        if self._playing_arms_cross:
            return
        self._update_status_label(STATE_THINKING)

    def set_normal_status(self):
        if self._playing_arms_cross:
            return
        self._update_status_label(STATE_NORMAL)

    def _on_state_changed(self, state_name: str):
        if self.anim_machine.current_mode == "standby" and state_name == "normal_idle":
            self.anim_machine.set_mode("normal")
            self._update_status_label(STATE_NORMAL)

    def play_arms_cross(self, on_finished=None):
        if self._playing_arms_cross:
            return
        self._playing_arms_cross = True
        self._arms_cross_speech_pending = False
        self._previous_arms_cross_mode = self.anim_machine.current_mode
        self.anim_machine.set_mode("arms_cross")
        try:
            cfg = self.anim_machine.config["modes"]["arms_cross"]["states"]
            dur1 = cfg["cross_start"]["duration"]
            dur2 = cfg["cross_end"]["duration"]
            total_duration = int((dur1 + dur2) * 1000)
        except:
            total_duration = 10000
        QTimer.singleShot(total_duration, lambda: self._restore_after_arms_cross(on_finished))

    def _restore_after_arms_cross(self, on_finished=None):
        prev = getattr(self, '_previous_arms_cross_mode', 'normal')
        self.anim_machine.set_mode(prev)
        self._playing_arms_cross = False
        if self._arms_cross_speech_pending:
            self._arms_cross_speech_pending = False
            self.anim_machine.trigger_event("speak_start")
            self._update_status_label(STATE_TALKING)
        else:
            if prev == "normal":
                self._update_status_label(STATE_NORMAL)
            elif prev == "standby":
                self._update_status_label(STATE_NORMAL)
        if on_finished:
            on_finished()

    def enter_standby(self):
        if self._playing_arms_cross:
            return
        self.anim_machine.set_mode("standby")

    def exit_standby(self):
        if self._playing_arms_cross:
            return
        self.anim_machine.trigger_event("standby_end")

    def set_arms_cross(self):
        self.play_arms_cross()

    def set_normal_mode(self):
        if self._playing_arms_cross:
            return
        self.anim_machine.set_mode("normal")

    def set_vision_mode(self):
        if self._playing_arms_cross:
            return
        self._previous_mode = self.anim_machine.current_mode
        self.anim_machine.set_mode("vision")

    def exit_vision_mode(self):
        if self._playing_arms_cross:
            return
        prev = getattr(self, '_previous_mode', 'normal')
        self.anim_machine.set_mode(prev)

    def wave_seen(self):
        self.anim_machine.trigger_event("wave_seen")

    def smile_seen(self):
        self.anim_machine.trigger_event("smile_seen")

    def get_accompany_button(self):
        return self._btn_accompany

    def get_balance_button(self):
        return self._btn_balance

    def get_settings_button(self):
        return self._btn_settings

    def get_pomodoro_button(self):
        return self._btn_pomodoro

    def get_api_config_button(self):
        return self._btn_api_config

    def get_alarm_button(self):
        return self._btn_alarm

    def get_todo_button(self):
        return self._btn_todo

    def get_camera_button(self):
        return self._btn_camera

    def get_vision_button(self):
        return self._btn_vision

    def _update_status_label(self, state: str):
        text, color = STATE_CONFIG.get(state, ("● 待机中", "#6C7BFF"))
        self._state_label.setText(text)
        self._state_label.setStyleSheet(f"color: {color}; background: transparent;")