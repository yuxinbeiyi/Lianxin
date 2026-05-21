"""
PomodoroDialog：番茄钟专注功能对话框
支持专注时长设置、倒计时、休息时长、统计显示
"""

import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QGroupBox, QFrame, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QFontMetrics, QPixmap, QPainter

from utils.pomodoro_stats import PomodoroStats


class TimeSpinBox(QSpinBox):
    """自定义时间滚轮控件（0-99）"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRange(0, 99)
        self.setWrapping(True)
        self.setFixedSize(50, 40)
        self.setAlignment(Qt.AlignCenter)
        self.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
        self.setStyleSheet("""
            QSpinBox {
                background-color: rgba(240, 242, 247, 200);
                border: 2px solid #D8D8EE;
                border-radius: 8px;
                color: #3A3A5C;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 16px;
            }
        """)


class PomodoroDialog(QDialog):
    """番茄钟对话框"""

    # 主动发消息的信号（传给主窗口）
    proactive_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stats = PomodoroStats()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._current_phase = "idle"  # idle, focusing, resting
        self._remaining_seconds = 0
        self._focus_seconds = 0  # 本次专注设定的秒数（用于统计）
        self._is_premature_end = False

        self.setWindowTitle("🍅 番茄钟 - 莲心专注助手")
        self.setMinimumSize(400, 450)
        self.resize(520, 560)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setModal(False)
        # 注意：不要在这里设置背景色，否则会覆盖背景图

        self._build_ui()
        self._update_stats_display()
        self._update_ui_state()
        self._set_background_image()  # 设置背景图（放在最后）

    def _set_background_image(self):
        """设置番茄钟对话框背景图（通过 paintEvent 以低透明度绘制，避免太抢眼）"""
        bg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets", "番茄钟背景图.jpg"
        )
        if os.path.exists(bg_path):
            self._bg_pixmap = QPixmap(bg_path)
        else:
            self._bg_pixmap = None

        # 对话框底色 + 子控件底色（纯色，背景图由 paintEvent 绘制在下层）
        self.setStyleSheet("""
            QDialog {
                background-color: #F5F5FA;
            }
            QDialog > * {
                background-color: rgba(255, 255, 255, 210);
            }
        """)
        self.setAttribute(Qt.WA_StyledBackground, True)

    def paintEvent(self, event):
        """在对话框底色之上、子控件之下绘制低透明度背景图。"""
        super().paintEvent(event)
        if getattr(self, "_bg_pixmap", None) and not self._bg_pixmap.isNull():
            painter = QPainter(self)
            painter.setOpacity(0.25)   # 调节此值控制背景图浓淡（0.0全透明~1.0不透明）
            scaled = self._bg_pixmap.scaled(
                self.size(),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            x = (self.width()  - scaled.width())  // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            painter.end()

    # ── 界面构建 ─────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # 标题
        title = QLabel("🍅 番茄钟")
        title.setFont(QFont("Microsoft YaHei UI", 18, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #FF6B6B; background: transparent;")
        layout.addWidget(title)

        # 统计信息区域
        stats_frame = QFrame()
        stats_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(240, 242, 247, 200);
                border-radius: 12px;
                border: 1px solid rgba(224, 224, 232, 150);
            }
        """)
        stats_layout = QVBoxLayout(stats_frame)
        stats_layout.setContentsMargins(16, 12, 16, 12)

        self._stats_label = QLabel()
        self._stats_label.setFont(QFont("Microsoft YaHei UI", 10))
        self._stats_label.setAlignment(Qt.AlignCenter)
        self._stats_label.setStyleSheet("color: #6C7BFF; background: transparent;")
        stats_layout.addWidget(self._stats_label)

        layout.addWidget(stats_frame)

        # 倒计时显示区域
        self._countdown_label = QLabel("00:00:00")
        self._countdown_label.setFont(QFont("Consolas", 42, QFont.Bold))
        self._countdown_label.setAlignment(Qt.AlignCenter)
        self._countdown_label.setStyleSheet("color: #FF6B6B; background: transparent; padding: 20px;")
        self._countdown_label.setVisible(False)
        layout.addWidget(self._countdown_label)

        # 当前阶段标签
        self._phase_label = QLabel("⏳ 待机中")
        self._phase_label.setFont(QFont("Microsoft YaHei UI", 12))
        self._phase_label.setAlignment(Qt.AlignCenter)
        self._phase_label.setStyleSheet("color: #888888; background: transparent;")
        self._phase_label.setVisible(False)
        layout.addWidget(self._phase_label)

        # ── 专注时长设置区域 ──
        focus_group = QGroupBox("专注时长设置")
        focus_group.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        focus_group.setStyleSheet("""
            QGroupBox {
                background-color: rgba(255, 255, 255, 200);
                border: 1px solid #D8D8EE;
                border-radius: 10px;
                margin-top: 10px;
                padding-top: 10px;
                color: #5060DD;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
        """)
        focus_layout = QVBoxLayout(focus_group)

        # 时间滚轮行
        time_row = QHBoxLayout()
        time_row.setAlignment(Qt.AlignCenter)
        time_row.setSpacing(8)

        self._hour_spin = TimeSpinBox()
        self._min_spin = TimeSpinBox()
        self._sec_spin = TimeSpinBox()

        hour_label = QLabel("时")
        min_label = QLabel("分")
        sec_label = QLabel("秒")
        for lbl in (hour_label, min_label, sec_label):
            lbl.setFont(QFont("Microsoft YaHei UI", 10))
            lbl.setStyleSheet("color: #555555; background: transparent;")

        time_row.addWidget(self._hour_spin)
        time_row.addWidget(hour_label)
        time_row.addWidget(self._min_spin)
        time_row.addWidget(min_label)
        time_row.addWidget(self._sec_spin)
        time_row.addWidget(sec_label)
        focus_layout.addLayout(time_row)

        # 提示文字
        tip_label = QLabel("💡 专注时长建议设置 25-50 分钟")
        tip_label.setFont(QFont("Microsoft YaHei UI", 8))
        tip_label.setAlignment(Qt.AlignCenter)
        tip_label.setStyleSheet("color: #AAAAAA; background: transparent;")
        focus_layout.addWidget(tip_label)

        layout.addWidget(focus_group)

        # ── 休息时长设置区域 ──
        rest_group = QGroupBox("休息时长设置")
        rest_group.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        rest_group.setStyleSheet("""
            QGroupBox {
                background-color: rgba(255, 255, 255, 200);
                border: 1px solid #D8D8EE;
                border-radius: 10px;
                margin-top: 10px;
                padding-top: 10px;
                color: #5060DD;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
        """)
        rest_layout = QVBoxLayout(rest_group)

        rest_time_row = QHBoxLayout()
        rest_time_row.setAlignment(Qt.AlignCenter)
        rest_time_row.setSpacing(8)

        self._rest_hour_spin = TimeSpinBox()
        self._rest_min_spin = TimeSpinBox()
        self._rest_sec_spin = TimeSpinBox()

        rest_hour_label = QLabel("时")
        rest_min_label = QLabel("分")
        rest_sec_label = QLabel("秒")

        rest_time_row.addWidget(self._rest_hour_spin)
        rest_time_row.addWidget(rest_hour_label)
        rest_time_row.addWidget(self._rest_min_spin)
        rest_time_row.addWidget(rest_min_label)
        rest_time_row.addWidget(self._rest_sec_spin)
        rest_time_row.addWidget(rest_sec_label)
        rest_layout.addLayout(rest_time_row)

        # 休息时长提示
        rest_tip_label = QLabel("💡 休息时长建议设置 5-15 分钟")
        rest_tip_label.setFont(QFont("Microsoft YaHei UI", 8))
        rest_tip_label.setAlignment(Qt.AlignCenter)
        rest_tip_label.setStyleSheet("color: #AAAAAA; background: transparent;")
        rest_layout.addWidget(rest_tip_label)

        layout.addWidget(rest_group)

        # ── 控制按钮区域 ──
        control_row = QHBoxLayout()
        control_row.setSpacing(12)

        self._start_btn = QPushButton("▶ 开始专注")
        self._start_btn.setFixedHeight(42)
        self._start_btn.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        self._start_btn.setCursor(Qt.PointingHandCursor)
        self._start_btn.setStyleSheet("""
            QPushButton {
                background-color: #6C7BFF;
                color: white;
                border-radius: 21px;
                border: none;
            }
            QPushButton:hover { background-color: #5A6AEE; }
            QPushButton:pressed { background-color: #4A5ADE; }
        """)
        self._start_btn.clicked.connect(self._on_start_clicked)

        self._end_btn = QPushButton("⏹ 提前结束")
        self._end_btn.setFixedHeight(42)
        self._end_btn.setFont(QFont("Microsoft YaHei UI", 11))
        self._end_btn.setCursor(Qt.PointingHandCursor)
        self._end_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9500;
                color: white;
                border-radius: 21px;
                border: none;
            }
            QPushButton:hover { background-color: #E08600; }
            QPushButton:pressed { background-color: #C07600; }
        """)
        self._end_btn.clicked.connect(self._on_end_clicked)

        self._skip_rest_btn = QPushButton("⏩ 跳过休息")
        self._skip_rest_btn.setFixedHeight(42)
        self._skip_rest_btn.setFont(QFont("Microsoft YaHei UI", 11))
        self._skip_rest_btn.setCursor(Qt.PointingHandCursor)
        self._skip_rest_btn.setStyleSheet("""
            QPushButton {
                background-color: #34C759;
                color: white;
                border-radius: 21px;
                border: none;
            }
            QPushButton:hover { background-color: #2DA84D; }
            QPushButton:pressed { background-color: #258F42; }
        """)
        self._skip_rest_btn.clicked.connect(self._on_skip_rest_clicked)
        self._skip_rest_btn.setVisible(False)

        # 全屏按钮
        self._fullscreen_btn = QPushButton("🖥 全屏")
        self._fullscreen_btn.setFixedHeight(42)
        self._fullscreen_btn.setFont(QFont("Microsoft YaHei UI", 11))
        self._fullscreen_btn.setCursor(Qt.PointingHandCursor)
        self._fullscreen_btn.setStyleSheet("""
            QPushButton {
                background-color: #8E8E93;
                color: white;
                border-radius: 21px;
                border: none;
            }
            QPushButton:hover { background-color: #7A7A7E; }
            QPushButton:pressed { background-color: #6C6C70; }
        """)
        self._fullscreen_btn.clicked.connect(self._toggle_fullscreen)

        control_row.addWidget(self._start_btn)
        control_row.addWidget(self._end_btn)
        control_row.addWidget(self._skip_rest_btn)
        control_row.addWidget(self._fullscreen_btn)
        layout.addLayout(control_row)

        # 关闭窗口按钮
        close_btn = QPushButton("关闭窗口")
        close_btn.setFixedHeight(36)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(240, 240, 248, 200);
                color: #888888;
                border-radius: 18px;
                border: 1px solid #D8D8EE;
            }
            QPushButton:hover { background-color: rgba(228, 228, 240, 200); }
        """)
        close_btn.clicked.connect(self._on_close_clicked)

        layout.addStretch()
        layout.addWidget(close_btn)

    # ── 辅助方法 ─────────────────────────────────────────────

    def _get_focus_seconds(self) -> int:
        """获取专注时长设置（秒）"""
        return (self._hour_spin.value() * 3600 +
                self._min_spin.value() * 60 +
                self._sec_spin.value())

    def _get_rest_seconds(self) -> int:
        """获取休息时长设置（秒）"""
        return (self._rest_hour_spin.value() * 3600 +
                self._rest_min_spin.value() * 60 +
                self._rest_sec_spin.value())

    def _format_time(self, seconds: int) -> str:
        """格式化时间显示 HH:MM:SS"""
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _update_stats_display(self):
        """更新统计信息显示"""
        stats = self._stats.get_stats()
        duration_str = self._stats.get_formatted_duration()
        sessions = stats["total_sessions"]
        self._stats_label.setText(
            f"📊 你已经在莲心的监督下完成了 {duration_str} 的专注工作学习了耶！"
            f" 累计专注 {sessions} 次！真棒~(ﾉ≧∀≦)ﾉ"
        )

    def _update_ui_state(self):
        """根据当前阶段更新界面元素"""
        is_idle = (self._current_phase == "idle")
        is_focusing = (self._current_phase == "focusing")
        is_resting = (self._current_phase == "resting")

        # 设置区域可见性
        self._hour_spin.setEnabled(is_idle)
        self._min_spin.setEnabled(is_idle)
        self._sec_spin.setEnabled(is_idle)
        self._rest_hour_spin.setEnabled(is_idle)
        self._rest_min_spin.setEnabled(is_idle)
        self._rest_sec_spin.setEnabled(is_idle)

        # 按钮可见性
        self._start_btn.setVisible(is_idle)
        self._end_btn.setVisible(is_focusing or is_resting)
        self._skip_rest_btn.setVisible(is_resting)

        # 倒计时和阶段标签可见性
        self._countdown_label.setVisible(not is_idle)
        self._phase_label.setVisible(not is_idle)

    # ── 全屏切换 ─────────────────────────────────────────

    def _toggle_fullscreen(self):
        """切换全屏模式"""
        if self.isFullScreen():
            self.showNormal()
            self._fullscreen_btn.setText("🖥 全屏")
            self._fullscreen_btn.setStyleSheet("""
                QPushButton {
                    background-color: #8E8E93;
                    color: white;
                    border-radius: 21px;
                    border: none;
                }
                QPushButton:hover { background-color: #7A7A7E; }
                QPushButton:pressed { background-color: #6C6C70; }
            """)
        else:
            self.showFullScreen()
            self._fullscreen_btn.setText("✖ 退出全屏")
            self._fullscreen_btn.setStyleSheet("""
                QPushButton {
                    background-color: #FF3B30;
                    color: white;
                    border-radius: 21px;
                    border: none;
                }
                QPushButton:hover { background-color: #E0302A; }
                QPushButton:pressed { background-color: #C02822; }
            """)

    def keyPressEvent(self, event):
        """按 ESC 键退出全屏"""
        if event.key() == Qt.Key_Escape and self.isFullScreen():
            self._toggle_fullscreen()
        else:
            super().keyPressEvent(event)

    # ── 计时器逻辑 ─────────────────────────────────────────

    def _start_focus(self):
        """开始专注计时"""
        focus_seconds = self._get_focus_seconds()
        if focus_seconds < 60:
            QMessageBox.warning(self, "提示", "专注时长至少需要设置 1 分钟（60秒）！")
            return

        self._current_phase = "focusing"
        self._remaining_seconds = focus_seconds
        self._focus_seconds = focus_seconds
        self._is_premature_end = False

        self._countdown_label.setText(self._format_time(self._remaining_seconds))
        self._phase_label.setText("🍅 专注中... 加油！")
        self._phase_label.setStyleSheet("color: #FF6B6B; background: transparent;")

        self._timer.start(1000)
        self._update_ui_state()

    def _start_rest(self):
        """开始休息计时"""
        rest_seconds = self._get_rest_seconds()
        if rest_seconds <= 0:
            # 没有休息时长，直接完成整个番茄钟
            self._current_phase = "idle"
            self._timer.stop()
            self._countdown_label.clear()
            self._phase_label.clear()
            self._update_ui_state()
            # 发送完成消息（可自定义）
            complete_msg = "🎉 番茄钟完成！你真棒！"
            self.proactive_message.emit(complete_msg)
            return

        self._current_phase = "resting"
        self._remaining_seconds = rest_seconds
        self._is_premature_end = False

        self._countdown_label.setText(self._format_time(self._remaining_seconds))
        self._phase_label.setText("☕ 休息中... 放松一下")
        self._phase_label.setStyleSheet("color: #34C759; background: transparent;")

        self._timer.start(1000)
        self._update_ui_state()

    def _on_tick(self):
        """每秒触发一次"""
        if self._remaining_seconds <= 0:
            self._timer.stop()
            self._on_phase_complete()
            return

        self._remaining_seconds -= 1
        self._countdown_label.setText(self._format_time(self._remaining_seconds))

    def _on_phase_complete(self):
        """当前阶段完成"""
        if self._current_phase == "focusing":
            # 专注完成：累加统计，发送鼓励消息
            self._stats.add_completed_session(self._focus_seconds)
            self._update_stats_display()

            # 发送鼓励消息（100%触发）
            encourage_msg = "🎉 恭喜完成了一次专注时长！持之以恒，天道酬勤，是通往成功的要素之一！(ﾉ≧∀≦)ﾉ"
            self.proactive_message.emit(encourage_msg)

            # 自动开始休息
            self._start_rest()

        elif self._current_phase == "resting":
            self._on_rest_complete()

    def _on_rest_complete(self):
        """休息完成"""
        self._current_phase = "idle"
        self._timer.stop()
        self._countdown_label.clear()
        self._phase_label.clear()
        self._update_ui_state()

        # 发送休息结束提醒消息
        rest_msg = "休息好了吗？休息好了的话，就继续开始接下来的任务吧~加油哦！(*´∀`*)"
        self.proactive_message.emit(rest_msg)

    # ── 按钮事件 ───────────────────────────────────────────

    def _on_start_clicked(self):
        """开始专注按钮"""
        self._start_focus()

    def _on_end_clicked(self):
        """提前结束按钮"""
        if self._current_phase == "focusing":
            # 弹窗确认
            reply = QMessageBox.question(
                self,
                "确认提前结束",
                "是否放弃当前专注计时？\n（专注次数不会累加，专注时长会计入总时长）",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._is_premature_end = True
                # 提前结束：专注时长累加（按实际经过的时间），专注次数不累加
                elapsed = self._focus_seconds - self._remaining_seconds
                if elapsed > 0:
                    self._stats.add_completed_session(elapsed)
                    self._update_stats_display()
                self._timer.stop()
                self._current_phase = "idle"
                self._update_ui_state()
                # 发送吐槽消息
                complaint_msg = "唉，你这家伙要专注点才行啊！(｀へ´)"
                self.proactive_message.emit(complaint_msg)

        elif self._current_phase == "resting":
            reply = QMessageBox.question(
                self,
                "确认提前结束",
                "是否放弃当前休息计时？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._timer.stop()
                self._current_phase = "idle"
                self._update_ui_state()
                # 发送吐槽消息
                complaint_msg = "休息都不好好休息，快去放松一下！(╯°□°)╯"
                self.proactive_message.emit(complaint_msg)

    def _on_skip_rest_clicked(self):
        """跳过休息按钮"""
        reply = QMessageBox.question(
            self,
            "确认跳过休息",
            "确定要跳过休息吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self._timer.stop()
            self._current_phase = "idle"
            self._update_ui_state()
            # 发送跳过休息的特殊消息
            skip_msg = "呦？不需要休息吗？好吧...那继续加油吧！(｀・ω・´)"
            self.proactive_message.emit(skip_msg)

    def _on_close_clicked(self):
        """关闭窗口按钮"""
        if self._current_phase != "idle":
            reply = QMessageBox.question(
                self,
                "确认关闭",
                "番茄钟仍在进行中，关闭窗口不会停止计时。\n是否继续关闭？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.hide()
        else:
            self.hide()

    def closeEvent(self, event):
        """重写关闭事件"""
        if self._current_phase != "idle":
            reply = QMessageBox.question(
                self,
                "确认关闭",
                "番茄钟仍在进行中，关闭窗口不会停止计时。\n是否继续关闭？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()