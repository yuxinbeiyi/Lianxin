"""
ProactiveDialog：主动聊天 + 调皮观察 设置界面
使用 QTabWidget 分离两个功能区域。
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QCheckBox, QGroupBox, QScrollArea,
    QWidget, QSizePolicy, QFrame, QSpinBox,
    QTabWidget, QComboBox, QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont
import os

from utils.proactive_chat import ProactiveChatScheduler


# 24 小时标签
_HOUR_LABELS = [f"{h:02d}:00" for h in range(24)]

# 权重颜色（0=灰, 1-3=蓝, 4-6=橙, 7-10=红）
def _weight_color(w: int) -> str:
    if w == 0:   return "#CCCCCC"
    if w <= 3:   return "#6C7BFF"
    if w <= 6:   return "#FF9500"
    return "#FF3B30"


class _HourRow(QWidget):
    """单行小时权重控件：标签 + 滑块 + 数字显示。"""

    value_changed = pyqtSignal(int, int)

    def __init__(self, hour: int, initial_weight: int, parent=None):
        super().__init__(parent)
        self._hour = hour
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        time_lbl = QLabel(_HOUR_LABELS[hour])
        time_lbl.setFixedWidth(44)
        time_lbl.setFont(QFont("Microsoft YaHei UI", 8))
        time_lbl.setStyleSheet("color: #555555;")
        layout.addWidget(time_lbl)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 10)
        self._slider.setValue(initial_weight)
        self._slider.setFixedHeight(18)
        self._slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #E0E0E8;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                width: 14px;
                height: 14px;
                margin: -5px 0;
                background: #6C7BFF;
                border-radius: 7px;
            }
            QSlider::sub-page:horizontal {
                background: #6C7BFF;
                border-radius: 2px;
            }
        """)
        self._slider.valueChanged.connect(self._on_value_changed)
        layout.addWidget(self._slider, 1)

        self._val_lbl = QLabel(str(initial_weight))
        self._val_lbl.setFixedWidth(20)
        self._val_lbl.setFont(QFont("Microsoft YaHei UI", 8, QFont.Bold))
        self._val_lbl.setAlignment(Qt.AlignCenter)
        self._update_val_label(initial_weight)
        layout.addWidget(self._val_lbl)

    def _on_value_changed(self, val: int):
        self._update_val_label(val)
        self.value_changed.emit(self._hour, val)

    def _update_val_label(self, val: int):
        self._val_lbl.setText(str(val))
        self._val_lbl.setStyleSheet(f"color: {_weight_color(val)};")

    def get_value(self) -> int:
        return self._slider.value()

    def set_value(self, val: int):
        self._slider.setValue(val)


class ProactiveDialog(QDialog):
    """主动聊天 + 调皮观察 设置对话框（双选项卡）。"""

    debug_trigger = pyqtSignal()
    debug_observe_signal = pyqtSignal(str)

    def __init__(self, scheduler: ProactiveChatScheduler, parent=None):
        super().__init__(parent)
        self._scheduler = scheduler
        self._hour_rows: list[_HourRow] = []

        self.setWindowTitle("主动聊天设置")
        self.resize(520, 680)
        self.setMinimumSize(460, 480)
        self.setModal(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background-color: #F8F8FC;")

        self._build_ui()
        self._load_from_scheduler()

        # 概率定时器（每分钟更新）
        self._prob_timer = QTimer(self)
        self._prob_timer.timeout.connect(self._update_current_prob)
        self._prob_timer.start(60 * 1000)
        self._update_current_prob()

    # ── 界面构建 ──────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(16, 16, 16, 16)

        # 标题 + 描述
        title = QLabel("主动聊天设置")
        title.setFont(QFont("Microsoft YaHei UI", 13, QFont.Bold))
        title.setStyleSheet("color: #3A3A5C;")
        root.addWidget(title)

        desc = QLabel("莲心会在设定的时间段内随机主动给你发消息。")
        desc.setFont(QFont("Microsoft YaHei UI", 9))
        desc.setStyleSheet("color: #777777;")
        root.addWidget(desc)

        # ── 选项卡 ──
        tab = QTabWidget()
        tab.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #D8D8EE;
                border-radius: 6px;
                background: #F8F8FC;
            }
            QTabBar::tab {
                background: #ECEEF6;
                color: #555555;
                padding: 6px 20px;
                font-size: 9pt;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #F8F8FC;
                color: #3A3A5C;
                font-weight: bold;
                border-bottom: 2px solid #6C7BFF;
            }
        """)
        root.addWidget(tab, 1)

        # ────── Tab 1: 主动聊天 ──────
        chat_tab = QWidget()
        chat_layout = QVBoxLayout(chat_tab)
        chat_layout.setSpacing(8)
        chat_layout.setContentsMargins(8, 8, 8, 8)

        self._build_chat_tab(chat_layout)
        tab.addTab(chat_tab, "主动聊天")

        # ────── Tab 2: 调皮观察 ──────
        obs_tab = QWidget()
        obs_layout = QVBoxLayout(obs_tab)
        obs_layout.setSpacing(8)
        obs_layout.setContentsMargins(8, 8, 8, 8)

        self._build_observe_tab(obs_layout)
        tab.addTab(obs_tab, "调皮观察")

        # ── 底部按钮 ──
        btn_row = QHBoxLayout()

        self._btn_debug = QPushButton("立即触发（调试）")
        self._btn_debug.setFixedHeight(34)
        self._btn_debug.setFont(QFont("Microsoft YaHei UI", 9))
        self._btn_debug.setCursor(Qt.PointingHandCursor)
        self._btn_debug.setStyleSheet("""
            QPushButton {
                background-color: #FF9500;
                color: white;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover  { background-color: #E08600; }
            QPushButton:pressed{ background-color: #C07600; }
            QPushButton:disabled{ background-color: #CCCCCC; }
        """)
        self._btn_debug.clicked.connect(self._on_debug_trigger)
        btn_row.addWidget(self._btn_debug)

        btn_row.addStretch()

        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedSize(72, 34)
        btn_cancel.setFont(QFont("Microsoft YaHei UI", 9))
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #F0F0F8;
                color: #555555;
                border-radius: 8px;
                border: 1px solid #D8D8EE;
            }
            QPushButton:hover { background-color: #E4E4F0; }
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_save = QPushButton("保存")
        btn_save.setFixedSize(72, 34)
        btn_save.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.setStyleSheet("""
            QPushButton {
                background-color: #6C7BFF;
                color: white;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover  { background-color: #5A6AEE; }
            QPushButton:pressed{ background-color: #4A5ADE; }
        """)
        btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(btn_save)

        root.addLayout(btn_row)

    # ────────── 主动聊天选项卡 ─────────────────────────────

    def _build_chat_tab(self, layout: QVBoxLayout):
        # 桌面主动聊天开关
        toggle_row = QHBoxLayout()
        toggle_lbl = QLabel("启用桌面主动聊天")
        toggle_lbl.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        toggle_lbl.setStyleSheet("color: #3A3A5C;")
        toggle_row.addWidget(toggle_lbl)
        toggle_row.addStretch()
        self._enable_cb = QCheckBox()
        self._enable_cb.setFixedSize(20, 20)
        toggle_row.addWidget(self._enable_cb)
        layout.addLayout(toggle_row)

        # QQ 主动聊天开关
        qq_row = QHBoxLayout()
        qq_lbl = QLabel("启用QQ主动聊天")
        qq_lbl.setFont(QFont("Microsoft YaHei UI", 9))
        qq_lbl.setStyleSheet("color: #555555;")
        qq_row.addWidget(qq_lbl)
        qq_row.addStretch()
        self._qq_cb = QCheckBox()
        self._qq_cb.setFixedSize(20, 20)
        qq_row.addWidget(self._qq_cb)
        layout.addLayout(qq_row)

        # 频率滑块
        freq_group = QGroupBox("每日消息频率")
        freq_group.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        freq_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #D8D8EE;
                border-radius: 8px;
                margin-top: 8px;
                padding: 8px;
                color: #5060DD;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
        """)
        freq_inner = QVBoxLayout(freq_group)

        freq_desc = QHBoxLayout()
        freq_low  = QLabel("少（约1条/天）")
        freq_high = QLabel("多（约50条/天）")
        for lbl in (freq_low, freq_high):
            lbl.setFont(QFont("Microsoft YaHei UI", 8))
            lbl.setStyleSheet("color: #888888;")
        freq_desc.addWidget(freq_low)
        freq_desc.addStretch()
        freq_desc.addWidget(freq_high)
        freq_inner.addLayout(freq_desc)

        freq_slider_row = QHBoxLayout()
        self._freq_slider = QSlider(Qt.Horizontal)
        self._freq_slider.setRange(1, 50)
        self._freq_slider.setFixedHeight(20)
        self._freq_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 6px;
                background: #E0E0E8;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                width: 18px;
                height: 18px;
                margin: -6px 0;
                background: #6C7BFF;
                border-radius: 9px;
            }
            QSlider::sub-page:horizontal {
                background: #6C7BFF;
                border-radius: 3px;
            }
        """)
        self._freq_slider.valueChanged.connect(self._on_freq_changed)
        freq_slider_row.addWidget(self._freq_slider)

        self._freq_val_lbl = QLabel("3")
        self._freq_val_lbl.setFixedWidth(24)
        self._freq_val_lbl.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        self._freq_val_lbl.setStyleSheet("color: #6C7BFF;")
        self._freq_val_lbl.setAlignment(Qt.AlignCenter)
        freq_slider_row.addWidget(self._freq_val_lbl)
        freq_inner.addLayout(freq_slider_row)
        layout.addWidget(freq_group)

        # 实时概率显示
        prob_frame = QFrame()
        prob_frame.setStyleSheet("background-color: #F0F2F7; border-radius: 8px;")
        prob_inner = QHBoxLayout(prob_frame)
        prob_inner.setContentsMargins(16, 10, 16, 10)
        self._prob_label = QLabel()
        self._prob_label.setFont(QFont("Microsoft YaHei UI", 9))
        self._prob_label.setStyleSheet("color: #5060DD;")
        prob_inner.addWidget(self._prob_label)
        layout.addWidget(prob_frame)

        # 高级设置
        advanced_group = QGroupBox("高级设置")
        advanced_group.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        advanced_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #D8D8EE;
                border-radius: 8px;
                margin-top: 8px;
                padding: 8px;
                color: #5060DD;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
        """)
        adv_inner = QVBoxLayout(advanced_group)

        int_row = QHBoxLayout()
        int_lbl = QLabel("两次主动消息最小间隔（分钟）")
        int_lbl.setFont(QFont("Microsoft YaHei UI", 9))
        int_lbl.setStyleSheet("color: #555555;")
        int_row.addWidget(int_lbl)
        int_row.addStretch()
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(10, 120)
        self._interval_spin.setSuffix(" 分钟")
        self._interval_spin.setFixedWidth(100)
        int_row.addWidget(self._interval_spin)
        adv_inner.addLayout(int_row)

        defer_row = QHBoxLayout()
        defer_lbl = QLabel("用户发消息后推迟时间（分钟）")
        defer_lbl.setFont(QFont("Microsoft YaHei UI", 9))
        defer_lbl.setStyleSheet("color: #555555;")
        defer_row.addWidget(defer_lbl)
        defer_row.addStretch()
        self._defer_spin = QSpinBox()
        self._defer_spin.setRange(5, 60)
        self._defer_spin.setSuffix(" 分钟")
        self._defer_spin.setFixedWidth(100)
        defer_row.addWidget(self._defer_spin)
        adv_inner.addLayout(defer_row)
        layout.addWidget(advanced_group)

        # 每小时权重
        hour_group = QGroupBox("各时间段触发权重（0=不发，10=最高）")
        hour_group.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        hour_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #D8D8EE;
                border-radius: 8px;
                margin-top: 8px;
                padding: 8px;
                color: #5060DD;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
        """)
        hour_inner = QVBoxLayout(hour_group)

        quick_row = QHBoxLayout()
        btn_reset = QPushButton("恢复默认权重")
        btn_reset.setFixedHeight(24)
        btn_reset.setFont(QFont("Microsoft YaHei UI", 8))
        btn_reset.setCursor(Qt.PointingHandCursor)
        btn_reset.setStyleSheet("""
            QPushButton {
                background-color: #ECEEFF;
                color: #5060DD;
                border-radius: 6px;
                border: 1px solid #C8CCEE;
            }
            QPushButton:hover { background-color: #DDE0FF; }
        """)
        btn_reset.clicked.connect(self._reset_weights)
        quick_row.addStretch()
        quick_row.addWidget(btn_reset)
        hour_inner.addLayout(quick_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(100)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(0)
        scroll_layout.setContentsMargins(0, 0, 4, 0)

        self._hour_rows = []
        from utils.proactive_chat import _DEFAULT_WEIGHTS
        for h in range(24):
            row = _HourRow(h, _DEFAULT_WEIGHTS[h])
            row.value_changed.connect(self._on_weight_changed)
            scroll_layout.addWidget(row)
            self._hour_rows.append(row)

        scroll.setWidget(scroll_content)
        hour_inner.addWidget(scroll, 1)
        layout.addWidget(hour_group, 1)

    # ────────── 调皮观察选项卡 ────────────────────────────

    def _build_observe_tab(self, layout: QVBoxLayout):
        # 说明文字
        hint = QLabel(
            '莲心可以偶尔"偷看"你在干什么——截图或打开摄像头瞄一眼，\n'
            '然后基于看到的东西调皮地跟你打招呼。'
        )
        hint.setFont(QFont("Microsoft YaHei UI", 9))
        hint.setStyleSheet("color: #777777;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # 启用开关
        toggle_row = QHBoxLayout()
        toggle_lbl = QLabel("启用调皮观察")
        toggle_lbl.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        toggle_lbl.setStyleSheet("color: #3A3A5C;")
        toggle_row.addWidget(toggle_lbl)
        toggle_row.addStretch()
        self._observe_cb = QCheckBox()
        self._observe_cb.setFixedSize(20, 20)
        toggle_row.addWidget(self._observe_cb)
        layout.addLayout(toggle_row)

        # 分割
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #E0E0E8;")
        layout.addWidget(line)

        # 截图概率
        scr_row = QHBoxLayout()
        scr_lbl = QLabel("截图概率（每小时）")
        scr_lbl.setFont(QFont("Microsoft YaHei UI", 9))
        scr_lbl.setStyleSheet("color: #555555;")
        scr_row.addWidget(scr_lbl)
        scr_row.addStretch()
        self._scr_slider = QSlider(Qt.Horizontal)
        self._scr_slider.setRange(0, 100)
        self._scr_slider.setFixedWidth(140)
        self._scr_slider.setFixedHeight(18)
        self._scr_slider.valueChanged.connect(
            lambda v: self._scr_val_lbl.setText(f"{v}%"))
        scr_row.addWidget(self._scr_slider)
        self._scr_val_lbl = QLabel("30%")
        self._scr_val_lbl.setFixedWidth(36)
        self._scr_val_lbl.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        self._scr_val_lbl.setStyleSheet("color: #FF6B8A;")
        scr_row.addWidget(self._scr_val_lbl)
        layout.addLayout(scr_row)

        # 摄像头概率
        cam_row = QHBoxLayout()
        cam_lbl = QLabel("摄像头概率（每小时）")
        cam_lbl.setFont(QFont("Microsoft YaHei UI", 9))
        cam_lbl.setStyleSheet("color: #555555;")
        cam_row.addWidget(cam_lbl)
        cam_row.addStretch()
        self._cam_slider = QSlider(Qt.Horizontal)
        self._cam_slider.setRange(0, 100)
        self._cam_slider.setFixedWidth(140)
        self._cam_slider.setFixedHeight(18)
        self._cam_slider.valueChanged.connect(
            lambda v: self._cam_val_lbl.setText(f"{v}%"))
        cam_row.addWidget(self._cam_slider)
        self._cam_val_lbl = QLabel("15%")
        self._cam_val_lbl.setFixedWidth(36)
        self._cam_val_lbl.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        self._cam_val_lbl.setStyleSheet("color: #FF6B8A;")
        cam_row.addWidget(self._cam_val_lbl)
        layout.addLayout(cam_row)

        # 摄像头参数
        params_row = QHBoxLayout()
        cam_wait_lbl = QLabel("等待")
        cam_wait_lbl.setFont(QFont("Microsoft YaHei UI", 9))
        cam_wait_lbl.setStyleSheet("color: #555555;")
        params_row.addWidget(cam_wait_lbl)
        self._cam_wait_spin = QSpinBox()
        self._cam_wait_spin.setRange(3, 30)
        self._cam_wait_spin.setSuffix(" 秒")
        self._cam_wait_spin.setFixedWidth(70)
        params_row.addWidget(self._cam_wait_spin)
        layout.addLayout(params_row)

        # 摄像头选择行：标签 + 下拉 + 刷新按钮
        cam_select_row = QHBoxLayout()
        cam_sel_lbl = QLabel("使用摄像头")
        cam_sel_lbl.setFont(QFont("Microsoft YaHei UI", 9))
        cam_sel_lbl.setStyleSheet("color: #555555;")
        cam_select_row.addWidget(cam_sel_lbl)
        self._cam_combo = QComboBox()
        self._cam_combo.setMinimumWidth(180)
        cam_select_row.addWidget(self._cam_combo)

        btn_refresh = QPushButton("刷新")
        btn_refresh.setFixedHeight(26)
        btn_refresh.setFont(QFont("Microsoft YaHei UI", 8))
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #E8F0FF;
                color: #5070DD;
                border-radius: 6px;
                border: 1px solid #C8D8F0;
            }
            QPushButton:hover { background-color: #D8E4FF; }
        """)
        btn_refresh.clicked.connect(self._refresh_camera_list)
        cam_select_row.addWidget(btn_refresh)
        cam_select_row.addStretch()
        layout.addLayout(cam_select_row)

        # 是否发送到 QQ
        qq_row = QHBoxLayout()
        self._obs_qq_cb = QCheckBox()
        self._obs_qq_cb.setFixedSize(18, 18)
        qq_row.addWidget(self._obs_qq_cb)
        qq_lbl = QLabel("观察消息同时发送到 QQ")
        qq_lbl.setFont(QFont("Microsoft YaHei UI", 9))
        qq_lbl.setStyleSheet("color: #555555;")
        qq_row.addWidget(qq_lbl)
        qq_row.addStretch()
        layout.addLayout(qq_row)

        # 调试按钮行
        debug_row = QHBoxLayout()
        self._btn_debug_scr = btn_scr = QPushButton("调试：截图观察")
        btn_scr.setFixedHeight(32)
        btn_scr.setFont(QFont("Microsoft YaHei UI", 9))
        btn_scr.setCursor(Qt.PointingHandCursor)
        btn_scr.setStyleSheet("""
            QPushButton {
                background-color: #FFE0E8;
                color: #D6406A;
                border-radius: 8px;
                border: 1px solid #FCC0D0;
            }
            QPushButton:hover { background-color: #FFD0DC; }
        """)
        btn_scr.clicked.connect(lambda: self._on_debug_observe("screenshot"))
        debug_row.addWidget(btn_scr)

        self._btn_debug_cam = btn_cam = QPushButton("调试：摄像头观察")
        btn_cam.setFixedHeight(32)
        btn_cam.setFont(QFont("Microsoft YaHei UI", 9))
        btn_cam.setCursor(Qt.PointingHandCursor)
        btn_cam.setStyleSheet("""
            QPushButton {
                background-color: #FFE0E8;
                color: #D6406A;
                border-radius: 8px;
                border: 1px solid #FCC0D0;
            }
            QPushButton:hover { background-color: #FFD0DC; }
        """)
        btn_cam.clicked.connect(lambda: self._on_debug_observe("camera"))
        debug_row.addWidget(btn_cam)
        debug_row.addStretch()
        layout.addLayout(debug_row)

        layout.addStretch(1)

        # 不自动扫描摄像头（避免物理激活 + 刷屏警告），仅在用户点"刷新"时扫描
        self._cam_combo.addItem('（点击"刷新"检测摄像头）', -1)

    # ── 摄像头扫描 ────────────────────────────────────────────

    def _scan_cameras(self) -> list[tuple[int, str]]:
        """扫描可用摄像头，返回 [(index, label), ...]。
        注意：此操作会物理激活摄像头（LED 会亮），仅在用户点击"刷新"时调用。
        """
        try:
            import cv2
        except ImportError:
            return []

        # 抑制 OpenCV C 层日志
        try:
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        except Exception:
            pass
        try:
            os.environ["OPENCV_LOG_LEVEL"] = "ERROR"
        except Exception:
            pass

        available = []
        backend = cv2.CAP_DSHOW if hasattr(cv2, "CAP_DSHOW") else 0
        for i in range(4):
            try:
                cap = cv2.VideoCapture(i, backend)
                if cap.isOpened():
                    label = f"摄像头 {i}"
                    available.append((i, label))
                    cap.release()
            except Exception:
                continue
        return available

    def _refresh_camera_list(self):
        """扫描可用摄像头并刷新下拉列表。"""
        self._cam_combo.clear()
        cams = self._scan_cameras()
        if cams:
            for idx, label in cams:
                self._cam_combo.addItem(label, idx)
            # 选中当前保存的 index（如果可用）
            current = self._scheduler.camera_index
            for i in range(self._cam_combo.count()):
                if self._cam_combo.itemData(i) == current:
                    self._cam_combo.setCurrentIndex(i)
                    break
        else:
            self._cam_combo.addItem("（未检测到摄像头）", -1)

    # ── 实时概率更新 ─────────────────────────────────────────

    def _update_current_prob(self):
        from datetime import datetime
        now = datetime.now()
        hour = now.hour
        weight = self._scheduler.weights[hour] if hour < len(self._scheduler.weights) else 0
        freq = self._scheduler.frequency
        prob = (weight / 10.0) * (freq / 30.0) * 0.08 * 1.5
        prob = min(prob, 0.3)
        self._prob_label.setText(
            f"当前时段（{hour:02d}:00）权重={weight}，"
            f"每5分钟触发概率约 {prob * 100:.2f}%"
        )

    # ── 数据加载/保存 ─────────────────────────────────────────

    def _load_from_scheduler(self):
        self._enable_cb.setChecked(self._scheduler.desktop_enabled)
        self._qq_cb.setChecked(self._scheduler.qq_enabled)
        self._freq_slider.setValue(self._scheduler.frequency)
        self._interval_spin.setValue(self._scheduler.min_interval_minutes)
        self._defer_spin.setValue(self._scheduler.user_defer_minutes)
        weights = self._scheduler.weights
        for h, row in enumerate(self._hour_rows):
            if h < len(weights):
                row.set_value(weights[h])

        # 观察设置
        self._observe_cb.setChecked(self._scheduler.observe_enabled)
        self._scr_slider.setValue(self._scheduler.screenshot_prob)
        self._scr_val_lbl.setText(f"{self._scheduler.screenshot_prob}%")
        self._cam_slider.setValue(self._scheduler.camera_prob)
        self._cam_val_lbl.setText(f"{self._scheduler.camera_prob}%")
        self._cam_wait_spin.setValue(self._scheduler.camera_wait)
        self._obs_qq_cb.setChecked(self._scheduler.observe_send_to_qq)

        # 摄像头下拉选中（_refresh_camera_list 已做，但确保外部加载也生效）
        current = self._scheduler.camera_index
        for i in range(self._cam_combo.count()):
            if self._cam_combo.itemData(i) == current:
                self._cam_combo.setCurrentIndex(i)
                break

        self._update_debug_btn_state()

    def _on_save(self):
        self._scheduler.desktop_enabled = self._enable_cb.isChecked()
        self._scheduler.qq_enabled = self._qq_cb.isChecked()
        self._scheduler.frequency = self._freq_slider.value()
        self._scheduler.min_interval_minutes = self._interval_spin.value()
        self._scheduler.user_defer_minutes = self._defer_spin.value()
        self._scheduler.weights = [row.get_value() for row in self._hour_rows]

        self._scheduler.observe_enabled = self._observe_cb.isChecked()
        self._scheduler.screenshot_prob = self._scr_slider.value()
        self._scheduler.camera_prob = self._cam_slider.value()
        self._scheduler.camera_wait = self._cam_wait_spin.value()
        self._scheduler.observe_send_to_qq = self._obs_qq_cb.isChecked()
        idx = self._cam_combo.currentData()
        if idx is not None and idx >= 0:
            self._scheduler.camera_index = idx

        self._scheduler.save_settings()
        self.accept()

    # ── 事件处理 ──────────────────────────────────────────────

    def _on_freq_changed(self, val: int):
        self._freq_val_lbl.setText(str(val))
        self._update_current_prob()

    def _on_weight_changed(self, hour: int, weight: int):
        from datetime import datetime
        if hour == datetime.now().hour:
            self._update_current_prob()

    def _reset_weights(self):
        from utils.proactive_chat import _DEFAULT_WEIGHTS
        for h, row in enumerate(self._hour_rows):
            row.set_value(_DEFAULT_WEIGHTS[h])

    def _on_debug_trigger(self):
        self.debug_trigger.emit()

    def _on_debug_observe(self, mode: str):
        if not self._observe_cb.isChecked():
            return
        btn = self._btn_debug_scr if mode == "screenshot" else self._btn_debug_cam
        orig_text = btn.text()
        btn.setEnabled(False)
        btn.setText("3 秒后…")
        self._btn_debug_scr.setEnabled(False)
        self._btn_debug_cam.setEnabled(False)
        QTimer.singleShot(3000, lambda: self._do_debug_observe(mode, btn, orig_text))

    def _do_debug_observe(self, mode: str, btn, orig_text: str):
        btn.setText(orig_text)
        btn.setEnabled(True)
        self._btn_debug_scr.setEnabled(True)
        self._btn_debug_cam.setEnabled(True)
        self.debug_observe_signal.emit(mode)

    def _update_debug_btn_state(self):
        any_enabled = self._enable_cb.isChecked() or self._qq_cb.isChecked()
        self._btn_debug.setEnabled(any_enabled)
        self._enable_cb.stateChanged.connect(self._refresh_debug_btn)
        self._qq_cb.stateChanged.connect(self._refresh_debug_btn)

    def _refresh_debug_btn(self):
        self._btn_debug.setEnabled(
            self._enable_cb.isChecked() or self._qq_cb.isChecked()
        )

    def closeEvent(self, event):
        self._prob_timer.stop()
        event.accept()
