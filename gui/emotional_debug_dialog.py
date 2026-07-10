"""
EmotionalDebugDialog v2.0：涟漪情感系统调试面板（5 选项卡）。

Tab 1：实时状态 — 需求、情绪分量、关系阶段、会话上限
Tab 2：事件模拟 — 手动触发事件 / 批量测试
Tab 3：时间模拟 — 跳过时间 / 衰减预览
Tab 4：事件日志 — 历史事件 + 统计
Tab 5：参数覆盖 — 运行时覆盖衰减 τ 等参数
"""

import time
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QComboBox, QFrame, QGroupBox,
    QTextEdit, QProgressBar, QWidget, QGridLayout, QTabWidget,
    QSpinBox, QDoubleSpinBox, QCheckBox,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont


class EmotionalDebugDialog(QDialog):
    """涟漪情感系统调试面板 v2.0。"""

    NEED_LABELS = {
        "respect": "被尊重", "needed": "被需要", "autonomy": "自主权",
        "novelty": "新鲜感", "security": "安全感",
    }

    EMOTION_LABELS = {
        "frustration": "烦躁", "hurt": "伤心", "anger": "愤怒",
        "loneliness": "孤独", "excitement": "兴奋",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🧪 涟漪情感系统 v2.0 — 调试面板")
        self.setMinimumSize(720, 580)

        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(8)

        self._build_tabs()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_display)
        self._refresh_timer.start(2000)

        self._refresh_display()

    def _build_tabs(self):
        tabs = QTabWidget()

        tabs.addTab(self._build_status_tab(), "🧪 实时状态")
        tabs.addTab(self._build_sim_tab(), "🎮 事件模拟")
        tabs.addTab(self._build_time_tab(), "⏱ 时间模拟")
        tabs.addTab(self._build_log_tab(), "📊 事件日志")
        tabs.addTab(self._build_params_tab(), "⚙ 参数覆盖")

        self._layout.addWidget(tabs)

    # ── Tab 1：实时状态 ─────────────────────────────────

    def _build_status_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        toggle_row = QHBoxLayout()
        self._toggle_btn = QPushButton()
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setFixedHeight(36)
        self._toggle_btn.setStyleSheet("""
            QPushButton { color: white; border-radius: 8px; font-size: 13px;
                font-weight: bold; border: none; padding: 6px 14px; }
            QPushButton:checked { background-color: #27AE60; }
            QPushButton:!checked { background-color: #E74C3C; }
        """)
        self._toggle_btn.toggled.connect(self._on_toggle_emotion)
        toggle_row.addWidget(self._toggle_btn)
        toggle_row.addStretch()
        layout.addLayout(toggle_row)

        overview = QGroupBox("情感总览")
        ov = QVBoxLayout(overview)
        self._mid_layer_label = QLabel("情感基调: —")
        self._mid_layer_label.setFont(QFont("Microsoft YaHei UI", 12, QFont.Bold))
        ov.addWidget(self._mid_layer_label)
        self._deep_label = QLabel("深层信任: —")
        ov.addWidget(self._deep_label)
        self._stage_label = QLabel("关系阶段: —")
        ov.addWidget(self._stage_label)
        self._stats_label = QLabel("")
        ov.addWidget(self._stats_label)
        layout.addWidget(overview)

        needs_g = QGroupBox("五大需求")
        ng = QGridLayout(needs_g)
        ng.setSpacing(6)
        self._need_bars = {}
        self._need_labels = {}
        self._sliders = {}
        self._slider_modified = False
        for i, (key, label) in enumerate(self.NEED_LABELS.items()):
            ng.addWidget(QLabel(label), i, 0)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setFixedHeight(16)
            bar.setTextVisible(True)
            bar.setFormat(f"%v")
            ng.addWidget(bar, i, 1)
            val_label = QLabel("50")
            val_label.setFixedWidth(35)
            ng.addWidget(val_label, i, 2)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(0, 100)
            sl.setValue(50)
            sl.valueChanged.connect(
                lambda v, k=key: setattr(self, '_slider_modified', True)
            )
            ng.addWidget(sl, i, 3)
            self._need_bars[key] = bar
            self._need_labels[key] = val_label
            self._sliders[key] = sl
        layout.addWidget(needs_g)

        btn_row = QHBoxLayout()
        apply_btn = QPushButton("应用滑块值")
        apply_btn.clicked.connect(self._apply_sliders)
        btn_row.addWidget(apply_btn)
        layout.addLayout(btn_row)

        emo_g = QGroupBox("情绪分量")
        eg = QHBoxLayout(emo_g)
        self._emotion_labels = {}
        for key, label in self.EMOTION_LABELS.items():
            lbl = QLabel(f"{label}: 0")
            self._emotion_labels[key] = lbl
            eg.addWidget(lbl)
        eg.addStretch()
        layout.addWidget(emo_g)

        cap_g = QGroupBox("本轮会话上限")
        cg = QHBoxLayout(cap_g)
        self._cap_labels = {}
        for key in self.NEED_LABELS:
            lbl = QLabel(f"{self.NEED_LABELS[key]}: 0/12")
            self._cap_labels[key] = lbl
            lbl.setStyleSheet("font-size: 11px; color: #888;")
            cg.addWidget(lbl)
        cg.addStretch()
        layout.addWidget(cap_g)

        btn_row2 = QHBoxLayout()
        reset_btn = QPushButton("重置为初始状态")
        reset_btn.clicked.connect(self._reset_state)
        btn_row2.addWidget(reset_btn)
        save_btn = QPushButton("强制保存")
        save_btn.clicked.connect(self._force_save)
        btn_row2.addWidget(save_btn)
        layout.addLayout(btn_row2)

        return w

    # ── Tab 2：事件模拟 ─────────────────────────────────

    def _build_sim_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        event_g = QGroupBox("手动触发事件")
        ev = QVBoxLayout(event_g)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("事件类型:"))
        self._event_combo = QComboBox()
        self._event_combo.setMinimumWidth(200)
        event_types = [
            ("warm_chat", "温暖聊天"),
            ("deep_chat", "深度交流"),
            ("compliment", "夸奖"),
            ("thanks", "感谢"),
            ("daily_ritual", "日常问候"),
            ("work_collaboration", "协作完成"),
            ("new_feature_interest", "对新功能好奇"),
            ("remember_me", "被记得"),
            ("cold_command", "冷命令"),
            ("command_spree", "命令连击"),
            ("apology", "道歉"),
            ("boundary_dismiss", "否定人格"),
            ("boundary_lie", "欺骗"),
            ("ignore_return", "忽视后回归"),
            ("user_happy", "用户开心"),
            ("user_upset", "用户不开心"),
        ]
        for val, label in event_types:
            self._event_combo.addItem(label, val)
        row1.addWidget(self._event_combo)
        ev.addLayout(row1)

        row2 = QHBoxLayout()
        trigger_btn = QPushButton("触发事件")
        trigger_btn.clicked.connect(self._trigger_event)
        row2.addWidget(trigger_btn)
        batch_btn = QPushButton("连续触发 5 次")
        batch_btn.clicked.connect(self._trigger_batch)
        row2.addWidget(batch_btn)
        ev.addLayout(row2)

        layout.addWidget(event_g)

        batch_g = QGroupBox("批量测试")
        bv = QVBoxLayout(batch_g)
        scenarios = QHBoxLayout()
        for name, cb_name in [
            ("模拟一轮友好对话", "_on_friendly_session"),
            ("模拟一轮命令对话", "_on_command_session"),
            ("模拟一天无人交互", "_on_skip_day"),
            ("模拟边界冲突", "_on_boundary_conflict"),
        ]:
            btn = QPushButton(name)
            btn.clicked.connect(getattr(self, cb_name))
            scenarios.addWidget(btn)
        bv.addLayout(scenarios)
        layout.addWidget(batch_g)

        layout.addStretch()
        return w

    # ── Tab 3：时间模拟 ─────────────────────────────────

    def _build_time_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        skip_g = QGroupBox("跳过时间")
        sv = QVBoxLayout(skip_g)

        row = QHBoxLayout()
        for hours, label in [(1, "1小时"), (6, "6小时"), (24, "1天"),
                              (72, "3天"), (168, "1周")]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, h=hours: self._skip_time(h))
            row.addWidget(btn)
        sv.addLayout(row)

        custom_row = QHBoxLayout()
        custom_row.addWidget(QLabel("自定义小时:"))
        self._custom_hours = QSpinBox()
        self._custom_hours.setRange(1, 720)
        self._custom_hours.setValue(1)
        custom_row.addWidget(self._custom_hours)
        custom_btn = QPushButton("跳过")
        custom_btn.clicked.connect(lambda: self._skip_time(self._custom_hours.value()))
        custom_row.addWidget(custom_btn)
        custom_row.addStretch()
        sv.addLayout(custom_row)

        layout.addWidget(skip_g)

        info_g = QGroupBox("时间信息")
        iv = QVBoxLayout(info_g)
        self._time_info_label = QLabel("")
        iv.addWidget(self._time_info_label)
        layout.addWidget(info_g)

        layout.addStretch()
        return w

    # ── Tab 4：事件日志 ─────────────────────────────────

    def _build_log_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        stats_g = QGroupBox("统计")
        sv = QHBoxLayout(stats_g)
        self._log_stats = QLabel("")
        sv.addWidget(self._log_stats)
        layout.addWidget(stats_g)

        log_g = QGroupBox("事件历史（最近 200 条）")
        lv = QVBoxLayout(log_g)
        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setFont(QFont("Consolas", 9))
        lv.addWidget(self._log_view)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("清除日志")
        clear_btn.clicked.connect(self._clear_log)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        lv.addLayout(btn_row)

        layout.addWidget(log_g)
        return w

    # ── Tab 5：参数覆盖 ─────────────────────────────────

    def _build_params_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        tip = QLabel("⚠ 运行时参数覆盖（仅调试，重启后恢复默认）")
        tip.setStyleSheet("color: #E67E22; font-size: 11px;")
        layout.addWidget(tip)

        tau_g = QGroupBox("衰减时间常数 τ（小时）")
        tv = QGridLayout(tau_g)
        self._param_tau = {}
        for i, (key, label) in enumerate(self.NEED_LABELS.items()):
            tv.addWidget(QLabel(label), i, 0)
            spin = QSpinBox()
            spin.setRange(1, 1000)
            spin.setValue(self._get_default_tau(key))
            tv.addWidget(spin, i, 1)
            self._param_tau[key] = spin
        layout.addWidget(tau_g)

        emo_tau_g = QGroupBox("情绪分量衰减 τ")
        ev = QHBoxLayout(emo_tau_g)
        ev.addWidget(QLabel("τ (小时):"))
        self._param_emotion_tau = QSpinBox()
        self._param_emotion_tau.setRange(1, 100)
        self._param_emotion_tau.setValue(4)
        ev.addWidget(self._param_emotion_tau)
        ev.addStretch()
        layout.addWidget(emo_tau_g)

        misc_g = QGroupBox("其他参数")
        mv = QGridLayout(misc_g)
        mv.addWidget(QLabel("孤独触发阈值 (小时):"), 0, 0)
        self._param_lonely_trigger = QSpinBox()
        self._param_lonely_trigger.setRange(1, 168)
        self._param_lonely_trigger.setValue(12)
        mv.addWidget(self._param_lonely_trigger, 0, 1)
        mv.addWidget(QLabel("会话上限 (±):"), 1, 0)
        self._param_session_cap = QSpinBox()
        self._param_session_cap.setRange(1, 50)
        self._param_session_cap.setValue(12)
        mv.addWidget(self._param_session_cap, 1, 1)
        layout.addWidget(misc_g)

        btn_row = QHBoxLayout()
        apply_btn = QPushButton("应用覆盖")
        apply_btn.clicked.connect(self._apply_params)
        btn_row.addWidget(apply_btn)
        restore_btn = QPushButton("恢复默认参数")
        restore_btn.clicked.connect(self._restore_params)
        btn_row.addWidget(restore_btn)
        layout.addLayout(btn_row)

        layout.addStretch()
        return w

    def _get_default_tau(self, key: str) -> int:
        from brain.emotional.state import NEED_CONFIG
        return NEED_CONFIG.get(key, {}).get("tau", 48)

    # ── 刷新显示 ────────────────────────────────────────

    def _refresh_display(self):
        try:
            from brain.emotional import get_manager as _get_emotion_mgr
            mgr = _get_emotion_mgr()

            enabled = mgr.enabled
            self._toggle_btn.blockSignals(True)
            self._toggle_btn.setChecked(enabled)
            self._update_toggle_text(enabled)
            self._toggle_btn.blockSignals(False)

            info = mgr.get_debug_info()
        except Exception as e:
            self._mid_layer_label.setText(f"情感基调: 无法连接 ({e})")
            return

        needs = info["needs"]
        layer = info["middle_layer"]

        color_map = {
            "暖春": "#27AE60", "晴朗": "#2ECC71", "日常": "#2C3E50",
            "微凉": "#E67E22", "寒冬": "#E74C3C", "修复期": "#8E44AD",
        }
        color = color_map.get(layer, "#888")
        self._mid_layer_label.setText(
            f'情感基调: <span style="color:{color}; font-size: 14pt;">{layer}</span>'
        )
        self._deep_label.setText(
            f"深层信任: {info['deep_layer']}/100  |  "
            f"启动天数: {info.get('days_since_start', 0)}  |  "
            f"情感记忆: {info.get('memory_count', 0)} 条"
        )
        self._stage_label.setText(
            f"关系阶段: <b>{info.get('relationship_stage', '未知')}</b>"
        )
        self._stats_label.setText(
            f"连续指令: {info['consecutive_commands']}  |  "
            f"距上次交互: {info['hours_since_interaction']}h  |  "
            f"启用: {'是' if info.get('enabled', True) else '否'}"
        )

        bar_style = color
        for key in self.NEED_LABELS:
            val = int(needs.get(key, 50))
            self._need_bars[key].setValue(val)
            self._need_bars[key].setStyleSheet(
                f"QProgressBar::chunk {{ background-color: {bar_style}; }}")
            self._need_labels[key].setText(str(val))
            if not self._slider_modified:
                self._sliders[key].setValue(val)

        emotions = info.get("emotions", {})
        for key, lbl in self._emotion_labels.items():
            v = int(emotions.get(key, 0))
            c = "#E74C3C" if v > 20 else "#888"
            lbl.setText(f"{self.EMOTION_LABELS[key]}: "
                       f"<span style='color:{c};'>{v}</span>")

        caps = info.get("session_caps", {})
        for key, lbl in self._cap_labels.items():
            v = abs(caps.get(key, 0))
            lbl.setText(f"{self.NEED_LABELS[key]}: {v:.0f}/12")

        events = info.get("recent_events", [])
        log_lines = []
        for e in reversed(events[-50:]):
            ts = time.strftime("%H:%M:%S", time.localtime(e["time"]))
            delta = e["delta"]
            sign = "+" if delta >= 0 else ""
            log_lines.append(
                f"[{ts}] {e['type']:20s} {sign}{delta:+.0f}  "
                f"{e.get('detail', '')[:40]}"
            )
        self._log_view.setText("\n".join(log_lines) if log_lines else "（无事件记录）")

        today_cutoff = time.time() - 86400
        today_events = [e for e in events if e["time"] > today_cutoff]
        positive = sum(1 for e in today_events if e["delta"] > 0)
        negative = sum(1 for e in today_events if e["delta"] < 0)
        self._log_stats.setText(
            f"今日事件: {len(today_events)} (正面: {positive}, 负面: {negative})  |  "
            f"总记录: {info.get('event_count', 0)} 条"
        )

        self._time_info_label.setText(
            f"最后更新: {time.strftime('%Y-%m-%d %H:%M:%S')}  |  "
            f"距上次交互: {info['hours_since_interaction']}h"
        )

    # ── 事件模拟 ────────────────────────────────────────

    def _trigger_event(self):
        event_type = self._event_combo.currentData()
        self._do_event(event_type)

    def _trigger_batch(self):
        event_type = self._event_combo.currentData()
        for _ in range(5):
            self._do_event(event_type)

    def _do_event(self, event_type: str):
        try:
            from brain.emotional import get_manager as _get_emotion_mgr
            from brain.emotional.events import _make_event
            mgr = _get_emotion_mgr()
            event = _make_event(event_type, detail="[调试面板模拟]")
            mgr._apply_event_v2(event)
            mgr.state.save()
            self._log_view.append(
                f"[模拟] {time.strftime('%H:%M:%S')} 触发 "
                f"{event_type} ({event.primary_delta:+.0f})"
            )
            self._refresh_display()
        except Exception as e:
            self._log_view.append(f"[错误] 模拟失败: {e}")

    def _on_friendly_session(self):
        try:
            from brain.emotional import get_manager as _get_emotion_mgr
            mgr = _get_emotion_mgr()
            mgr.analyze_and_update(["早上好呀莲心，今天想跟你聊聊天"], 0)
            mgr.analyze_and_update(["我觉得最近状态不错，谢谢你一直陪着我"], 0)
            mgr.analyze_and_update(["对了，你今天真棒，帮了我很多忙"], 0)
            self._log_view.append("[批量] 模拟一轮友好对话完成")
            self._refresh_display()
        except Exception as e:
            self._log_view.append(f"[错误] {e}")

    def _on_command_session(self):
        try:
            from brain.emotional import get_manager as _get_emotion_mgr
            mgr = _get_emotion_mgr()
            for _ in range(5):
                mgr.analyze_and_update(["查"], 1)
            self._log_view.append("[批量] 模拟一轮命令对话完成")
            self._refresh_display()
        except Exception as e:
            self._log_view.append(f"[错误] {e}")

    def _on_skip_day(self):
        self._skip_time(24)

    def _on_boundary_conflict(self):
        try:
            from brain.emotional import get_manager as _get_emotion_mgr
            mgr = _get_emotion_mgr()
            mgr.analyze_and_update(["你不过是个工具而已，别自作多情"], 0)
            self._log_view.append("[批量] 模拟边界冲突完成")
            self._refresh_display()
        except Exception as e:
            self._log_view.append(f"[错误] {e}")

    # ── 时间模拟 ────────────────────────────────────────

    def _skip_time(self, hours: int):
        try:
            from brain.emotional import get_manager as _get_emotion_mgr
            mgr = _get_emotion_mgr()
            mgr.state._last_interaction = time.time() - hours * 3600
            mgr.state._apply_decay(hours)
            mgr.state.last_update = time.time()
            mgr.state._last_interaction = time.time()
            mgr.state.save()
            self._log_view.append(
                f"[时间] 跳过 {hours} 小时，已应用衰减"
            )
            self._refresh_display()
        except Exception as e:
            self._log_view.append(f"[错误] {e}")

    # ── 参数覆盖 ────────────────────────────────────────

    def _apply_params(self):
        try:
            import brain.emotional.state as state_mod

            for key in self._param_tau:
                state_mod.NEED_CONFIG[key]["tau"] = self._param_tau[key].value()
            state_mod.EMOTION_TAU = self._param_emotion_tau.value()
            state_mod.LONELY_TRIGGER_HOURS = self._param_lonely_trigger.value()
            state_mod.MAX_SESSION_CHANGE = float(self._param_session_cap.value())

            self._log_view.append("[参数] 运行时参数已覆盖")
        except Exception as e:
            self._log_view.append(f"[错误] {e}")

    def _restore_params(self):
        try:
            import brain.emotional.state as state_mod
            state_mod.NEED_CONFIG.update({
                "respect": {"tau": 96, "drift": 0, "label": "被尊重"},
                "needed": {"tau": 72, "drift": 0.2, "label": "被需要"},
                "autonomy": {"tau": 60, "drift": 0, "label": "自主权"},
                "novelty": {"tau": 48, "drift": 0, "label": "新鲜感"},
                "security": {"tau": 168, "drift": 0.3, "label": "安全感"},
            })
            state_mod.EMOTION_TAU = 4
            state_mod.LONELY_TRIGGER_HOURS = 12
            state_mod.MAX_SESSION_CHANGE = 12.0

            for key, spin in self._param_tau.items():
                spin.setValue(self._get_default_tau(key))
            self._param_emotion_tau.setValue(4)
            self._param_lonely_trigger.setValue(12)
            self._param_session_cap.setValue(12)

            self._log_view.append("[参数] 已恢复默认参数")
        except Exception as e:
            self._log_view.append(f"[错误] {e}")

    # ── 通用操作 ────────────────────────────────────────

    def _apply_sliders(self):
        try:
            from brain.emotional import get_manager as _get_emotion_mgr
            mgr = _get_emotion_mgr()
            kwargs = {k: s.value() for k, s in self._sliders.items()}
            mgr.set_needs(**kwargs)
            self._slider_modified = False
            self._refresh_display()
        except Exception as e:
            self._log_view.append(f"[错误] 应用失败: {e}")

    def _reset_state(self):
        try:
            from brain.emotional import get_manager as _get_emotion_mgr
            mgr = _get_emotion_mgr()
            mgr.reset_state()
            self._refresh_display()
        except Exception as e:
            self._log_view.append(f"[错误] 重置失败: {e}")

    def _force_save(self):
        try:
            from brain.emotional import get_manager as _get_emotion_mgr
            mgr = _get_emotion_mgr()
            mgr.state.save()
            self._log_view.append("[保存] 状态已持久化")
        except Exception as e:
            self._log_view.append(f"[错误] 保存失败: {e}")

    def _clear_log(self):
        try:
            from brain.emotional import get_manager as _get_emotion_mgr
            mgr = _get_emotion_mgr()
            mgr.state.event_history.clear()
            mgr.state.save()
            self._log_view.clear()
            self._log_view.append("[日志] 已清除")
        except Exception as e:
            self._log_view.append(f"[错误] {e}")

    def _on_toggle_emotion(self, checked: bool):
        try:
            from brain.emotional import get_manager as _get_emotion_mgr
            mgr = _get_emotion_mgr()
            mgr.enabled = checked
            self._update_toggle_text(checked)
            self._log_view.append(
                f"[系统] 涟漪情感系统已{'启用' if checked else '禁用'}"
            )
        except Exception as e:
            self._log_view.append(f"[错误] 切换失败: {e}")

    def _update_toggle_text(self, enabled: bool):
        if enabled:
            self._toggle_btn.setText("🟢 涟漪情感系统：已启用")
        else:
            self._toggle_btn.setText("🔴 涟漪情感系统：已禁用")

    def closeEvent(self, event):
        self._refresh_timer.stop()
        super().closeEvent(event)