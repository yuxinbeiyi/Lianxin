"""
QQ 聊天面板：桥接开关 + 参数设置。
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QDoubleSpinBox, QSpinBox, QPushButton,
    QCheckBox, QFrame,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from config import get_qq_timing_config, save_qq_timing_config


class QqSettingsDialog(QDialog):
    """QQ 聊天面板：桥接开关 + 定时参数设置。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mw = parent  # MainWindow 引用
        self.setWindowTitle("QQ 聊天")
        self.setMinimumSize(440, 480)
        self.resize(460, 520)

        self._config = get_qq_timing_config()
        self._build_ui()
        self._load_config()
        self._refresh_bridge_section()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        # ── QQ 桥接开关 ──────────────────────────────────────
        bridge_frame = QFrame()
        bridge_frame.setFrameShape(QFrame.StyledPanel)
        bridge_frame.setStyleSheet("QFrame { background-color: #F8F9FF; border-radius: 8px; }")
        bridge_layout = QHBoxLayout(bridge_frame)

        self._bridge_status = QLabel("QQ 桥接: 未连接")
        self._bridge_status.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        bridge_layout.addWidget(self._bridge_status)

        bridge_layout.addStretch()

        self._btn_bridge_toggle = QPushButton("连接")
        self._btn_bridge_toggle.setFixedSize(80, 30)
        self._btn_bridge_toggle.setStyleSheet("""
            QPushButton {
                background-color: #6C7BFF;
                color: white;
                border-radius: 6px;
                border: none;
                font-weight: bold;
            }
            QPushButton:hover  { background-color: #5A6AEE; }
        """)
        self._btn_bridge_toggle.clicked.connect(self._on_bridge_toggle)
        bridge_layout.addWidget(self._btn_bridge_toggle)

        layout.addWidget(bridge_frame)

        # ── 自动启动 ────────────────────────────────────────
        self._auto_start_cb = QCheckBox("启动莲心时自动连接 QQ 桥接")
        from config import get_qq_bridge_config
        self._auto_start_cb.setChecked(get_qq_bridge_config().get("auto_start", False))
        self._auto_start_cb.stateChanged.connect(self._on_auto_start_changed)
        layout.addWidget(self._auto_start_cb)

        # ── 回复速度 ────────────────────────────────────────
        grp_reply = QGroupBox("回复速度")
        grp_layout = QVBoxLayout(grp_reply)
        grp_layout.setSpacing(14)
        grp_layout.setContentsMargins(12, 16, 12, 12)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("思考延迟"))
        self._think_min = QDoubleSpinBox()
        self._think_min.setRange(0.5, 30.0)
        self._think_min.setSingleStep(0.5)
        self._think_min.setSuffix(" 秒")
        row1.addWidget(self._think_min)
        row1.addWidget(QLabel("~"))
        self._think_max = QDoubleSpinBox()
        self._think_max.setRange(0.5, 30.0)
        self._think_max.setSingleStep(0.5)
        self._think_max.setSuffix(" 秒")
        row1.addWidget(self._think_max)
        row1.addStretch()
        grp_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("打字速度"))
        self._speed_min = QSpinBox()
        self._speed_min.setRange(10, 999)
        self._speed_min.setSuffix(" 字/分钟")
        row2.addWidget(self._speed_min)
        row2.addWidget(QLabel("~"))
        self._speed_max = QSpinBox()
        self._speed_max.setRange(10, 999)
        self._speed_max.setSuffix(" 字/分钟")
        row2.addWidget(self._speed_max)
        row2.addStretch()
        grp_layout.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("最短回复间隔"))
        self._min_interval = QDoubleSpinBox()
        self._min_interval.setRange(0.5, 30.0)
        self._min_interval.setSingleStep(0.5)
        self._min_interval.setSuffix(" 秒")
        row3.addWidget(self._min_interval)
        row3.addStretch()
        grp_layout.addLayout(row3)

        layout.addWidget(grp_reply)

        # ── 分段发送 ────────────────────────────────────────
        grp_seg = QGroupBox("分段发送")
        seg_layout = QVBoxLayout(grp_seg)
        seg_layout.setSpacing(14)
        seg_layout.setContentsMargins(12, 16, 12, 12)

        row4 = QHBoxLayout()
        row4.addWidget(QLabel("分段阈值"))
        self._seg_min = QSpinBox()
        self._seg_min.setRange(20, 500)
        self._seg_min.setSingleStep(10)
        self._seg_min.setSuffix(" 字")
        row4.addWidget(self._seg_min)
        row4.addWidget(QLabel("~"))
        self._seg_max = QSpinBox()
        self._seg_max.setRange(20, 500)
        self._seg_max.setSingleStep(10)
        self._seg_max.setSuffix(" 字")
        row4.addWidget(self._seg_max)
        row4.addStretch()
        seg_layout.addLayout(row4)

        row5 = QHBoxLayout()
        row5.addWidget(QLabel("段间间隔"))
        self._seg_interval_min = QDoubleSpinBox()
        self._seg_interval_min.setRange(1.0, 60.0)
        self._seg_interval_min.setSingleStep(0.5)
        self._seg_interval_min.setSuffix(" 秒")
        row5.addWidget(self._seg_interval_min)
        row5.addWidget(QLabel("~"))
        self._seg_interval_max = QDoubleSpinBox()
        self._seg_interval_max.setRange(1.0, 60.0)
        self._seg_interval_max.setSingleStep(0.5)
        self._seg_interval_max.setSuffix(" 秒")
        row5.addWidget(self._seg_interval_max)
        row5.addStretch()
        seg_layout.addLayout(row5)

        layout.addWidget(grp_seg)

        # ── 全局限制 ────────────────────────────────────────
        grp_global = QGroupBox("全局限制")
        g_layout = QVBoxLayout(grp_global)
        g_layout.setSpacing(14)
        g_layout.setContentsMargins(12, 16, 12, 12)

        row6 = QHBoxLayout()
        row6.addWidget(QLabel("全局发送间隔"))
        self._global_min = QDoubleSpinBox()
        self._global_min.setRange(1.0, 120.0)
        self._global_min.setSingleStep(0.5)
        self._global_min.setSuffix(" 秒")
        row6.addWidget(self._global_min)
        row6.addWidget(QLabel("~"))
        self._global_max = QDoubleSpinBox()
        self._global_max.setRange(1.0, 120.0)
        self._global_max.setSingleStep(0.5)
        self._global_max.setSuffix(" 秒")
        row6.addWidget(self._global_max)
        row6.addStretch()
        g_layout.addLayout(row6)

        row7 = QHBoxLayout()
        row7.addWidget(QLabel("主人每日上限"))
        self._owner_limit = QSpinBox()
        self._owner_limit.setRange(5, 500)
        self._owner_limit.setSuffix(" 条")
        row7.addWidget(self._owner_limit)
        row7.addStretch()
        g_layout.addLayout(row7)

        row8 = QHBoxLayout()
        row8.addWidget(QLabel("其他用户上限"))
        self._other_limit = QSpinBox()
        self._other_limit.setRange(1, 200)
        self._other_limit.setSuffix(" 条")
        row8.addWidget(self._other_limit)
        row8.addStretch()
        g_layout.addLayout(row8)

        # ── 跨端记忆 ──
        row9 = QHBoxLayout()
        row9.addWidget(QLabel("跨端参考条数"))
        self._cross_limit = QSpinBox()
        self._cross_limit.setRange(0, 50)
        self._cross_limit.setSuffix(" 条")
        self._cross_limit.setToolTip("桌面端⇔QQ端互相参考的最近聊天条数（0=关闭跨端记忆）")
        row9.addWidget(self._cross_limit)
        row9.addWidget(QLabel("（0=关闭跨端记忆）"))
        row9.addStretch()
        g_layout.addLayout(row9)

        # ── 语音回复开关 ──
        row10 = QHBoxLayout()
        row10.addWidget(QLabel("语音回复"))
        self._voice_cb = QCheckBox("收到语音或用【语音】前缀时以语音回复")
        row10.addWidget(self._voice_cb)
        row10.addStretch()
        g_layout.addLayout(row10)

        layout.addWidget(grp_global)

        # ── 按钮 ────────────────────────────────────────────
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._btn_default = QPushButton("恢复默认")
        self._btn_default.setFixedSize(80, 28)
        self._btn_default.clicked.connect(self._on_default)
        btn_layout.addWidget(self._btn_default)

        self._btn_cancel = QPushButton("取消")
        self._btn_cancel.setFixedSize(60, 28)
        self._btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self._btn_cancel)

        self._btn_apply = QPushButton("立即生效")
        self._btn_apply.setFixedSize(80, 28)
        self._btn_apply.setStyleSheet("""
            QPushButton {
                background-color: #6C7BFF;
                color: white;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover  { background-color: #5A6AEE; }
            QPushButton:pressed{ background-color: #4A5ADE; }
        """)
        self._btn_apply.clicked.connect(self._on_apply)
        btn_layout.addWidget(self._btn_apply)

        layout.addLayout(btn_layout)

    def _load_config(self):
        """将配置值加载到控件中。"""
        self._think_min.setValue(self._config["think_delay_min"])
        self._think_max.setValue(self._config["think_delay_max"])
        self._speed_min.setValue(self._config["type_speed_min"])
        self._speed_max.setValue(self._config["type_speed_max"])
        self._min_interval.setValue(self._config["min_reply_interval"])
        self._seg_min.setValue(self._config["segment_threshold_min"])
        self._seg_max.setValue(self._config["segment_threshold_max"])
        self._seg_interval_min.setValue(self._config["segment_interval_min"])
        self._seg_interval_max.setValue(self._config["segment_interval_max"])
        self._global_min.setValue(self._config["global_send_interval_min"])
        self._global_max.setValue(self._config["global_send_interval_max"])
        self._owner_limit.setValue(self._config["daily_limit_owner"])
        self._other_limit.setValue(self._config["daily_limit_other"])
        self._cross_limit.setValue(self._config.get("cross_session_context_limit", 6))

        # 从桥接配置加载语音回复开关
        from config import get_qq_bridge_config
        bridge_cfg = get_qq_bridge_config()
        self._voice_cb.setChecked(bridge_cfg.get("voice_reply_enabled", True))

    def _collect_config(self) -> dict:
        """从控件收集当前值并返回配置字典。"""
        return {
            "think_delay_min": self._think_min.value(),
            "think_delay_max": self._think_max.value(),
            "type_speed_min": self._speed_min.value(),
            "type_speed_max": self._speed_max.value(),
            "min_reply_interval": self._min_interval.value(),
            "segment_threshold_min": self._seg_min.value(),
            "segment_threshold_max": self._seg_max.value(),
            "segment_interval_min": self._seg_interval_min.value(),
            "segment_interval_max": self._seg_interval_max.value(),
            "global_send_interval_min": self._global_min.value(),
            "global_send_interval_max": self._global_max.value(),
            "daily_limit_owner": self._owner_limit.value(),
            "daily_limit_other": self._other_limit.value(),
            "cross_session_context_limit": self._cross_limit.value(),
        }

    def _on_default(self):
        """恢复默认值。"""
        from config import _QQ_TIMING_DEFAULTS
        self._config = dict(_QQ_TIMING_DEFAULTS)
        self._load_config()
        self._voice_cb.setChecked(True)  # 语音回复默认开启

    def _on_apply(self):
        """保存配置并关闭对话框。"""
        config = self._collect_config()
        save_qq_timing_config(config)

        # 同时保存语音回复开关到桥接配置
        from config import get_qq_bridge_config, save_qq_bridge_config
        bridge_cfg = get_qq_bridge_config()
        bridge_cfg["voice_reply_enabled"] = self._voice_cb.isChecked()
        save_qq_bridge_config(bridge_cfg)

        self.accept()

    def _on_bridge_toggle(self):
        """启动/停止 QQ 桥接。"""
        if self._mw._qq_bridge and self._mw._qq_bridge.isRunning():
            self._mw._stop_qq_bridge()
        else:
            self._mw._start_qq_bridge()
        self._refresh_bridge_section()

    def _refresh_bridge_section(self):
        """刷新桥接状态显示。"""
        if self._mw._qq_bridge and self._mw._qq_bridge.isRunning():
            self._bridge_status.setText("QQ 桥接: ● 已连接")
            self._bridge_status.setStyleSheet("color: #34C759;")
            self._btn_bridge_toggle.setText("断开")
            self._btn_bridge_toggle.setStyleSheet("""
                QPushButton {
                    background-color: #FF6B6B;
                    color: white;
                    border-radius: 6px;
                    border: none;
                    font-weight: bold;
                }
                QPushButton:hover  { background-color: #EE5A5A; }
            """)
        else:
            self._bridge_status.setText("QQ 桥接: ○ 未连接")
            self._bridge_status.setStyleSheet("color: #999999;")
            self._btn_bridge_toggle.setText("连接")
            self._btn_bridge_toggle.setStyleSheet("""
                QPushButton {
                    background-color: #6C7BFF;
                    color: white;
                    border-radius: 6px;
                    border: none;
                    font-weight: bold;
                }
                QPushButton:hover  { background-color: #5A6AEE; }
            """)

    def _on_auto_start_changed(self):
        """保存自动启动设置到持久化配置。"""
        from config import get_qq_bridge_config, save_qq_bridge_config
        cfg = get_qq_bridge_config()
        cfg["auto_start"] = self._auto_start_cb.isChecked()
        save_qq_bridge_config(cfg)
        self._mw._qq_bridge_auto_start = self._auto_start_cb.isChecked()
