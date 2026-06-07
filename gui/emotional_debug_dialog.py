"""
EmotionalDebugDialog：涟漪情感系统调试面板。

功能：
- 实时显示 5 个需求值和情感基调
- 查看最近事件时间线
- 手动调节需求值（滑块）
- 模拟触发事件
- 重置/保存/加载
"""

import time
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QComboBox, QFrame, QGroupBox,
    QTextEdit, QProgressBar, QWidget, QGridLayout,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont


class EmotionalDebugDialog(QDialog):
    """涟漪情感系统调试面板。"""

    NEED_LABELS = {
        "respect": "被尊重",
        "needed": "被需要",
        "autonomy": "自主权",
        "novelty": "新鲜感",
        "security": "安全感",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🧪 涟漪情感系统 — 调试面板")
        self.setMinimumSize(640, 600)

        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(12)

        self._build_ui()

        # 实时刷新定时器（每 2 秒刷新一次显示）
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_display)
        self._refresh_timer.start(2000)

        self._refresh_display()

    def _build_ui(self):
        # ── 状态总览 ──────────────────────────────────────
        overview_group = QGroupBox("当前状态")
        overview_layout = QVBoxLayout(overview_group)

        self._mid_layer_label = QLabel("情感基调: —")
        self._mid_layer_label.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        overview_layout.addWidget(self._mid_layer_label)

        self._deep_label = QLabel("深层信任基底: —")
        overview_layout.addWidget(self._deep_label)

        self._aggression_label = QLabel("攻击性: —")
        overview_layout.addWidget(self._aggression_label)

        self._stats_label = QLabel("")
        overview_layout.addWidget(self._stats_label)

        self._layout.addWidget(overview_group)

        # ── 需求进度条 ──────────────────────────────────────
        needs_group = QGroupBox("需求状态（实时）")
        needs_layout = QGridLayout(needs_group)
        needs_layout.setSpacing(8)

        self._need_bars = {}
        self._need_labels = {}
        row = 0
        for key, label in self.NEED_LABELS.items():
            name_label = QLabel(label)
            name_label.setFixedWidth(60)
            needs_layout.addWidget(name_label, row, 0)

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setFixedHeight(18)
            bar.setTextVisible(True)
            bar.setFormat(f"{key}: %v")
            needs_layout.addWidget(bar, row, 1)

            val_label = QLabel("50")
            val_label.setFixedWidth(40)
            needs_layout.addWidget(val_label, row, 2)

            self._need_bars[key] = bar
            self._need_labels[key] = val_label
            row += 1

        self._layout.addWidget(needs_group)

        # ── 手动干预 ──────────────────────────────────────
        control_group = QGroupBox("手动干预")
        control_layout = QVBoxLayout(control_group)

        slider_row = QGridLayout()
        self._sliders = {}
        row = 0
        for key, label in self.NEED_LABELS.items():
            slider_row.addWidget(QLabel(label), row, 0)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(50)
            slider.setFixedWidth(200)
            val_lbl = QLabel("50")
            val_lbl.setFixedWidth(30)
            slider.valueChanged.connect(
                lambda v, k=key, lbl=val_lbl: lbl.setText(str(v))
            )
            slider_row.addWidget(slider, row, 1)
            slider_row.addWidget(val_lbl, row, 2)
            self._sliders[key] = slider
            row += 1

        control_layout.addLayout(slider_row)

        btn_row = QHBoxLayout()
        apply_btn = QPushButton("应用到莲心")
        apply_btn.clicked.connect(self._apply_sliders)
        btn_row.addWidget(apply_btn)

        reset_btn = QPushButton("重置为初始状态")
        reset_btn.clicked.connect(self._reset_state)
        btn_row.addWidget(reset_btn)

        save_btn = QPushButton("强制保存")
        save_btn.clicked.connect(self._force_save)
        btn_row.addWidget(save_btn)

        control_layout.addLayout(btn_row)
        self._layout.addWidget(control_group)

        # ── 事件模拟 ──────────────────────────────────────
        sim_group = QGroupBox("模拟事件")
        sim_layout = QHBoxLayout(sim_group)

        self._event_combo = QComboBox()
        event_types = [
            ("command_spree", "命令连发"),
            ("genuine_chat", "真诚聊天"),
            ("apology", "道歉"),
            ("boundary_lie", "欺骗（等级5）"),
            ("boundary_dismiss", "否定人格"),
            ("ignore_return", "忽视后上线"),
            ("compliment", "夸奖"),
        ]
        for val, label in event_types:
            self._event_combo.addItem(label, val)
        sim_layout.addWidget(self._event_combo)

        trigger_btn = QPushButton("触发事件")
        trigger_btn.clicked.connect(self._trigger_event)
        sim_layout.addWidget(trigger_btn)

        sim_layout.addStretch()
        self._layout.addWidget(sim_group)

        # ── 事件日志 ──────────────────────────────────────
        log_group = QGroupBox("最近事件")
        log_layout = QVBoxLayout(log_group)

        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumHeight(150)
        self._log_view.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self._log_view)

        self._layout.addWidget(log_group)

        # ── 提示 ──────────────────────────────────────────
        tip = QLabel(
            "⚠ 调试面板的修改会实时影响莲心的情感状态。\n"
            "「应用到莲心」将滑块值直接写入需求系统。"
        )
        tip.setStyleSheet("color: #E74C3C; font-size: 11px; padding: 4px;")
        self._layout.addWidget(tip)

    def _refresh_display(self):
        """从 EmotionManager 读取最新状态并刷新 UI。"""
        try:
            from brain.emotional import get_manager as _get_emotion_mgr
            mgr = _get_emotion_mgr()
            info = mgr.get_debug_info()
        except Exception as e:
            self._mid_layer_label.setText(f"情感基调: 无法连接 ({e})")
            return

        needs = info["needs"]
        layer = info["middle_layer"]
        deep = info["deep_layer"]

        # 情感基调
        color_map = {
            "暖春": "#27AE60", "日常": "#2C3E50",
            "微凉": "#E67E22", "寒冬": "#E74C3C", "修复期": "#8E44AD",
        }
        color = color_map.get(layer, "#888")
        self._mid_layer_label.setText(
            f'情感基调: <span style="color:{color}">{layer}</span>'
        )
        self._deep_label.setText(
            f"深层信任基底: {deep}/100"
        )
        agg = info.get("aggression", 0)
        agg_style = ""
        if agg > 50:
            agg_style = ' style="color: #E74C3C; font-weight: bold;"'
        elif agg > 20:
            agg_style = ' style="color: #E67E22;"'
        self._aggression_label.setText(
            f'攻击性: <span{agg_style}>{agg}</span>/100'
        )
        self._stats_label.setText(
            f"连续指令: {info['consecutive_commands']} | "
            f"距上次交互: {info['hours_since_interaction']} 小时"
        )

        # 需求进度条
        color_css = {
            "暖春": """
            QProgressBar::chunk { background-color: #27AE60; }
        """, "日常": """
            QProgressBar::chunk { background-color: #3498DB; }
        """, "微凉": """
            QProgressBar::chunk { background-color: #E67E22; }
        """, "寒冬": """
            QProgressBar::chunk { background-color: #E74C3C; }
        """, "修复期": """
            QProgressBar::chunk { background-color: #8E44AD; }
        """}
        bar_style = color_css.get(layer, "")

        for key in self.NEED_LABELS:
            val = int(needs.get(key, 50))
            bar = self._need_bars[key]
            bar.setValue(val)
            bar.setStyleSheet(bar_style)
            self._need_labels[key].setText(str(val))
            # 滑块同步（只在用户未拖拽时刷新）
            if not self._sliders[key].isSliderDown():
                self._sliders[key].setValue(val)

        # 事件日志
        events = info.get("recent_events", [])
        log_lines = []
        for e in reversed(events[-20:]):
            ts = time.strftime("%H:%M", time.localtime(e["time"]))
            delta = e["delta"]
            sign = "+" if delta >= 0 else ""
            log_lines.append(
                f"[{ts}] {e['type']:20s}  {sign}{delta:+.0f}  "
                f"({e.get('detail', '')[:30]})"
            )
        self._log_view.setText("\n".join(log_lines) if log_lines else "（无事件记录）")

    def _apply_sliders(self):
        """将滑块值应用到 EmotionManager。"""
        try:
            from brain.emotional import get_manager as _get_emotion_mgr
            mgr = _get_emotion_mgr()
            kwargs = {k: s.value() for k, s in self._sliders.items()}
            mgr.set_needs(**kwargs)
            self._refresh_display()
        except Exception as e:
            self._log_view.append(f"[错误] 应用失败: {e}")

    def _reset_state(self):
        """重置情感状态到初始值。"""
        try:
            from brain.emotional import get_manager as _get_emotion_mgr
            mgr = _get_emotion_mgr()
            mgr.reset_state()
            self._refresh_display()
        except Exception as e:
            self._log_view.append(f"[错误] 重置失败: {e}")

    def _force_save(self):
        """强制保存当前状态。"""
        try:
            from brain.emotional import get_manager as _get_emotion_mgr
            mgr = _get_emotion_mgr()
            mgr.state.save()
            self._log_view.append("[保存] 状态已持久化")
        except Exception as e:
            self._log_view.append(f"[错误] 保存失败: {e}")

    def _trigger_event(self):
        """触发选中的模拟事件。"""
        try:
            from brain.emotional import get_manager as _get_emotion_mgr
            from brain.emotional.events import _make_event
            mgr = _get_emotion_mgr()
            event_type = self._event_combo.currentData()
            event = _make_event(event_type, detail="[调试面板模拟]")
            mgr._apply_event_with_cooldown(event)
            mgr.state.save()
            self._log_view.append(
                f"[模拟] 触发 {event_type} ({event.primary_delta:+.0f})"
            )
            self._refresh_display()
        except Exception as e:
            self._log_view.append(f"[错误] 模拟失败: {e}")

    def closeEvent(self, event):
        self._refresh_timer.stop()
        super().closeEvent(event)
