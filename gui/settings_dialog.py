"""
SettingsDialog：莲心全局设置对话框
包含：常规设置、日记本、声音设置、记忆系统 四个选项卡
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QGroupBox, QFrame, QMessageBox, QSpinBox, QSlider, QLineEdit,
    QFileDialog, QTabWidget, QComboBox, QWidget,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QAbstractItemView,
    QTableWidget, QTableWidgetItem, QFormLayout,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from datetime import datetime

from utils.settings import get_settings
from utils.autostart import enable_autostart, disable_autostart, is_autostart_enabled
from utils.accompany_stats import AccompanyStats
from config import get_memory_config, save_memory_config
from config import get_quick_launch_apps, save_quick_launch_apps
from brain.memory_store import ALL_CATEGORIES, CATEGORY_DESCRIPTIONS
from brain.graph_memory import list_all_facts, delete_facts
from gui.quick_launch_dialog import QuickLaunchEditDialog



class SettingsDialog(QDialog):
    date_saved = pyqtSignal()          # 初识日期保存信号
    font_size_changed = pyqtSignal(int)  # 字体大小变化信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = get_settings()
        self._accompany_stats = AccompanyStats()
        self._load_memory_config()

        self.setWindowTitle("全局设置")
        self.setMinimumSize(540, 780)
        self.resize(580, 800)
        self.setModal(True)
        self.setStyleSheet("background-color: #F8F8FC;")
        self._build_ui()
        self._load_from_settings()

    def _load_memory_config(self):
        self._mem_cfg = get_memory_config()

    def _save_memory_config(self):
        save_memory_config({
            "auto_extract": self._mem_cfg["auto_extract"],
            "extract_interval": self._mem_cfg["extract_interval"],
            "extract_message_count": self._mem_cfg["extract_message_count"],
            "max_items_per_category": self._mem_cfg["max_items_per_category"],
            "default_save_category": self._mem_cfg["default_save_category"],
        })

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # 标题
        title = QLabel("⚙️ 全局设置")
        title.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
        title.setStyleSheet("color: #3A3A5C;")
        layout.addWidget(title)

        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #E0E0E8; max-height: 1px;")
        layout.addWidget(line)

        # ========== 选项卡 ==========
        tab_widget = QTabWidget()
        tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #D8D8E8;
                border-radius: 8px;
                background: #F8F8FC;
            }
            QTabBar::tab {
                background: #F0F0F8;
                border-radius: 6px;
                padding: 6px 12px;
                margin: 4px;
            }
            QTabBar::tab:selected {
                background: #6C7BFF;
                color: white;
            }
        """)

        # ----- 常规设置选项卡 -----
        # ----- 常规设置选项卡 -----
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        general_layout.setSpacing(16)

        # 表情包发送概率设置（放在字体设置之后、小纸条路径之前）
        prob_frame = self._create_frame()
        prob_layout = QVBoxLayout(prob_frame)
        prob_layout.setSpacing(8)

        slider_layout = QHBoxLayout()
        slider_layout.addWidget(QLabel("表情包发送概率："))
        self.emotion_prob_slider = QSlider(Qt.Horizontal)
        self.emotion_prob_slider.setRange(0, 100)
        self.emotion_prob_slider.setValue(int(self._settings.emotion_probability * 100))
        self.emotion_prob_slider.setTickPosition(QSlider.TicksBelow)
        self.emotion_prob_slider.setTickInterval(10)
        self.emotion_prob_value = QLabel(f"{int(self._settings.emotion_probability * 100)}%")
        self.emotion_prob_slider.valueChanged.connect(self._on_emotion_prob_changed)
        slider_layout.addWidget(self.emotion_prob_slider)
        slider_layout.addWidget(self.emotion_prob_value)
        slider_layout.addStretch()
        prob_layout.addLayout(slider_layout)

        prob_hint = QLabel("💡 提示：若表情包文件夹为空，则不会发送图片。")
        prob_hint.setFont(QFont("Microsoft YaHei UI", 8))
        prob_hint.setStyleSheet("color: #888888;")
        prob_layout.addWidget(prob_hint)

        general_layout.addWidget(prob_frame)

        # 静默模式
        silent_frame = self._create_frame()
        silent_layout = QHBoxLayout(silent_frame)
        self._silent_cb = QCheckBox("开启静默模式（所有消息只显示气泡，不语音朗读）")
        self._silent_cb.setFont(QFont("Microsoft YaHei UI", 9))
        self._silent_cb.setCursor(Qt.PointingHandCursor)
        silent_layout.addWidget(self._silent_cb)
        general_layout.addWidget(silent_frame)

        # 退出确认
        exit_frame = self._create_frame()
        exit_layout = QHBoxLayout(exit_frame)
        self._exit_confirm_cb = QCheckBox("退出时显示确认弹窗（防止误触关闭）")
        self._exit_confirm_cb.setFont(QFont("Microsoft YaHei UI", 9))
        self._exit_confirm_cb.setCursor(Qt.PointingHandCursor)
        exit_layout.addWidget(self._exit_confirm_cb)
        general_layout.addWidget(exit_frame)

        # 字体大小
        font_frame = self._create_frame()
        font_layout = QVBoxLayout(font_frame)
        font_title = QLabel("🔤 聊天字体大小")
        font_title.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        font_title.setStyleSheet("color: #444466;")
        font_layout.addWidget(font_title)

        slider_layout_font = QHBoxLayout()
        self._font_slider = QSlider(Qt.Horizontal)
        self._font_slider.setRange(10, 20)
        self._font_slider.setTickPosition(QSlider.TicksBelow)
        self._font_slider.setTickInterval(2)
        self._font_slider.setSingleStep(1)
        self._font_slider.setCursor(Qt.PointingHandCursor)
        slider_layout_font.addWidget(self._font_slider)

        self._font_value_label = QLabel("12")
        self._font_value_label.setFixedWidth(30)
        self._font_value_label.setAlignment(Qt.AlignCenter)
        self._font_value_label.setStyleSheet("color: #5060DD; font-weight: bold;")
        slider_layout_font.addWidget(self._font_value_label)

        font_layout.addLayout(slider_layout_font)
        font_tip = QLabel("💡 调整聊天气泡中的文字大小（10-20px）")
        font_tip.setFont(QFont("Microsoft YaHei UI", 8))
        font_tip.setStyleSheet("color: #888888;")
        font_layout.addWidget(font_tip)
        self._font_slider.valueChanged.connect(self._on_font_size_changed)
        general_layout.addWidget(font_frame)

        # 小纸条路径
        note_frame = self._create_frame()
        note_layout = QVBoxLayout(note_frame)
        note_title = QLabel("📝 小纸条文件路径")
        note_title.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        note_title.setStyleSheet("color: #444466;")
        note_layout.addWidget(note_title)

        path_layout = QHBoxLayout()
        self._note_path_edit = QLineEdit()
        self._note_path_edit.setPlaceholderText("默认：桌面/小纸条.txt")
        self._note_path_edit.setFont(QFont("Microsoft YaHei UI", 9))
        path_layout.addWidget(self._note_path_edit)
        self._browse_btn = QPushButton("浏览...")
        self._browse_btn.setFixedSize(70, 32)
        self._browse_btn.setCursor(Qt.PointingHandCursor)
        self._browse_btn.clicked.connect(self._browse_note_path)
        path_layout.addWidget(self._browse_btn)
        note_layout.addLayout(path_layout)

        note_tip = QLabel("💡 小纸条是使用待机模式时给莲心用的txt文件，请选择一个合适的路径创建‘小纸条.txt’")
        note_tip.setWordWrap(True)
        note_tip.setFont(QFont("Microsoft YaHei UI", 8))
        note_tip.setStyleSheet("color: #888888;")
        note_layout.addWidget(note_tip)
        general_layout.addWidget(note_frame)

        # 开机自启动
        autostart_frame = self._create_frame()
        autostart_layout = QVBoxLayout(autostart_frame)
        self._autostart_cb = QCheckBox("开启开机自启动（下次开机时莲心自动启动）")
        self._autostart_cb.setFont(QFont("Microsoft YaHei UI", 9))
        self._autostart_cb.setCursor(Qt.PointingHandCursor)
        autostart_layout.addWidget(self._autostart_cb)
        autostart_tip = QLabel("启动后若检测到网络，莲心会自动发送一条问候消息（每天仅一次）")
        autostart_tip.setFont(QFont("Microsoft YaHei UI", 8))
        autostart_tip.setStyleSheet("color: #999999;")
        autostart_layout.addWidget(autostart_tip)
        general_layout.addWidget(autostart_frame)

        # 初识日期
        first_meet_group = QGroupBox("📅 初识日期")
        first_meet_group.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        first_meet_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #D8D8EE;
                border-radius: 8px;
                margin-top: 8px;
                padding: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
        """)
        first_meet_layout = QVBoxLayout(first_meet_group)
        date_input_layout = QHBoxLayout()

        self._year_spin = QSpinBox()
        self._year_spin.setRange(2000, 2100)
        self._year_spin.setFixedWidth(100)
        self._year_spin.setSuffix(" 年")
        date_input_layout.addWidget(self._year_spin)

        self._month_spin = QSpinBox()
        self._month_spin.setRange(1, 12)
        self._month_spin.setFixedWidth(80)
        self._month_spin.setSuffix(" 月")
        date_input_layout.addWidget(self._month_spin)

        self._day_spin = QSpinBox()
        self._day_spin.setRange(1, 31)
        self._day_spin.setFixedWidth(80)
        self._day_spin.setSuffix(" 日")
        date_input_layout.addWidget(self._day_spin)

        today_btn = QPushButton("今天")
        today_btn.setFixedSize(60, 30)
        today_btn.setCursor(Qt.PointingHandCursor)
        today_btn.clicked.connect(self._set_today_date)
        date_input_layout.addWidget(today_btn)
        date_input_layout.addStretch()

        first_meet_layout.addLayout(date_input_layout)
        date_tip = QLabel("💡 设置你与莲心初次见面的日期，用于计算「一起度过的第X天」")
        date_tip.setFont(QFont("Microsoft YaHei UI", 8))
        date_tip.setStyleSheet("color: #888888;")
        first_meet_layout.addWidget(date_tip)
        general_layout.addWidget(first_meet_group)

        general_layout.addStretch()
        tab_widget.addTab(general_tab, "常规")

        # ----- 声音设置选项卡 -----
        sound_tab = QWidget()
        sound_layout = QVBoxLayout(sound_tab)
        sound_layout.setSpacing(20)

        # TTS 音量
        tts_frame = self._create_frame()
        tts_layout = QVBoxLayout(tts_frame)
        tts_layout.addWidget(QLabel("🗣️ 莲心语音音量"))
        self.tts_slider = QSlider(Qt.Horizontal)
        self.tts_slider.setRange(0, 100)
        self.tts_slider.setValue(int(self._settings.tts_volume * 100))
        self.tts_slider.valueChanged.connect(self._on_tts_volume_changed)
        tts_layout.addWidget(self.tts_slider)
        sound_layout.addWidget(tts_frame)

        # 音效音量
        sfx_frame = self._create_frame()
        sfx_layout = QVBoxLayout(sfx_frame)
        sfx_layout.addWidget(QLabel("🔊 按键/反馈音效音量"))
        self.sfx_slider = QSlider(Qt.Horizontal)
        self.sfx_slider.setRange(0, 100)
        self.sfx_slider.setValue(int(self._settings.sfx_volume * 100))
        self.sfx_slider.valueChanged.connect(self._on_sfx_volume_changed)
        sfx_layout.addWidget(self.sfx_slider)
        sound_layout.addWidget(sfx_frame)

        sound_layout.addStretch()
        tab_widget.addTab(sound_tab, "🔊 声音设置")

        # ----- 记忆系统设置选项卡 -----
        memory_tab = QWidget()
        memory_layout = QVBoxLayout(memory_tab)
        memory_layout.setSpacing(14)

        # ── 自动记忆提取 ──
        extract_frame = self._create_frame()
        extract_layout = QVBoxLayout(extract_frame)
        extract_layout.setSpacing(10)

        self._memory_auto_cb = QCheckBox("启用自动记忆提取（后台分析对话内容，自动提取值得记住的信息）")
        self._memory_auto_cb.setFont(QFont("Microsoft YaHei UI", 9))
        self._memory_auto_cb.setCursor(Qt.PointingHandCursor)
        self._memory_auto_cb.setToolTip("开启后，莲心会在聊天时悄悄分析对话，自动提取你的个人信息、偏好、事件等保存到长期记忆中。关闭后只能通过手动说「记住这个」来保存。")
        extract_layout.addWidget(self._memory_auto_cb)

        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("每"))
        self._memory_extract_interval_spin = QSpinBox()
        self._memory_extract_interval_spin.setRange(1, 50)
        self._memory_extract_interval_spin.setValue(6)
        self._memory_extract_interval_spin.setFixedWidth(70)
        self._memory_extract_interval_spin.setSuffix(" 轮")
        self._memory_extract_interval_spin.setToolTip("莲心每跟你聊完这么多轮对话后，会触发一次后台记忆分析。数值越小提取越频繁（更耗token），数值越大越省但可能漏掉信息。")
        interval_row.addWidget(self._memory_extract_interval_spin)
        interval_row.addWidget(QLabel("对话触发一次自动提取"))
        interval_row.addStretch()
        extract_layout.addLayout(interval_row)

        msg_row = QHBoxLayout()
        msg_row.addWidget(QLabel("每次提取分析最近"))
        self._memory_extract_msgs_spin = QSpinBox()
        self._memory_extract_msgs_spin.setRange(5, 100)
        self._memory_extract_msgs_spin.setValue(20)
        self._memory_extract_msgs_spin.setFixedWidth(70)
        self._memory_extract_msgs_spin.setSuffix(" 条")
        self._memory_extract_msgs_spin.setToolTip("每次提取时，莲心会分析最近多少条消息来找出值得记住的内容。消息越多分析越全面，但也更耗token。建议20-30条。")
        msg_row.addWidget(self._memory_extract_msgs_spin)
        msg_row.addWidget(QLabel("消息"))
        msg_row.addStretch()
        extract_layout.addLayout(msg_row)

        memory_layout.addWidget(extract_frame)

        # ── 存储设置 ──
        store_frame = self._create_frame()
        store_layout = QVBoxLayout(store_frame)
        store_layout.setSpacing(10)

        max_row = QHBoxLayout()
        max_row.addWidget(QLabel("每类记忆最多保留"))
        self._memory_max_per_cat_spin = QSpinBox()
        self._memory_max_per_cat_spin.setRange(10, 9999)
        self._memory_max_per_cat_spin.setValue(200)
        self._memory_max_per_cat_spin.setFixedWidth(90)
        self._memory_max_per_cat_spin.setSuffix(" 条")
        self._memory_max_per_cat_spin.setToolTip("每个分类（个人档案/偏好/事件/知识/行为模式/技能）最多保留多少条记忆。超出时会自动淘汰最旧且最不重要的条目。设得太大可能导致记忆文件臃肿，太小可能丢失有用信息。")
        max_row.addWidget(self._memory_max_per_cat_spin)
        max_row.addStretch()
        store_layout.addLayout(max_row)

        default_cat_row = QHBoxLayout()
        default_cat_row.addWidget(QLabel("未指定分类时默认存入："))
        self._memory_default_cat_combo = QComboBox()
        for cat in ALL_CATEGORIES:
            desc = CATEGORY_DESCRIPTIONS.get(cat, cat)
            self._memory_default_cat_combo.addItem(f"{cat} — {desc}", cat)
        self._memory_default_cat_combo.setToolTip("当你对莲心说「记住这个」但没有说属于哪类时，默认存到哪个分类。当前默认是「知识（knowledge）」。")
        default_cat_row.addWidget(self._memory_default_cat_combo)
        default_cat_row.addStretch()
        store_layout.addLayout(default_cat_row)

        memory_layout.addWidget(store_frame)

        # ── 记忆浏览器（手动管理） ──
        browse_frame = self._create_frame()
        browse_layout = QVBoxLayout(browse_frame)
        browse_layout.setSpacing(6)

        browse_title = QLabel("📖 记忆浏览与管理")
        browse_title.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        browse_title.setStyleSheet("color: #444466;")
        browse_layout.addWidget(browse_title)

        self._memory_tree = QTreeWidget()
        self._memory_tree.setHeaderLabels(["分类", "内容", "强度", "来源", "日期"])
        self._memory_tree.setAlternatingRowColors(True)
        self._memory_tree.setRootIsDecorated(False)
        self._memory_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._memory_tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self._memory_tree.setFixedHeight(200)
        self._memory_tree.setStyleSheet("""
            QTreeWidget {
                background-color: white;
                border: 1px solid #D8D8E8;
                border-radius: 4px;
                font-size: 9pt;
            }
            QTreeWidget::item {
                padding: 3px;
            }
            QHeaderView::section {
                background-color: #E8EAF6;
                padding: 4px;
                border: none;
                font-weight: bold;
            }
        """)
        browse_layout.addWidget(self._memory_tree)

        btn_row2 = QHBoxLayout()
        self._memory_refresh_btn = QPushButton("🔄 刷新列表")
        self._memory_refresh_btn.setCursor(Qt.PointingHandCursor)
        self._memory_refresh_btn.setToolTip("从记忆文件中重新加载最新数据，反映其他方式新增或删除的记忆。")
        self._memory_refresh_btn.clicked.connect(self._refresh_memory_tree)
        btn_row2.addWidget(self._memory_refresh_btn)

        self._memory_delete_btn = QPushButton("🗑️ 删除选中")
        self._memory_delete_btn.setCursor(Qt.PointingHandCursor)
        self._memory_delete_btn.setStyleSheet("background-color: #FFE0E0; border: 1px solid #FFB0B0; border-radius: 4px; padding: 4px 10px;")
        self._memory_delete_btn.setToolTip("删除列表中勾选的记忆条目。此操作不可恢复，请谨慎使用。")
        self._memory_delete_btn.clicked.connect(self._delete_selected_memories)
        btn_row2.addWidget(self._memory_delete_btn)

        self._memory_export_btn = QPushButton("💾 导出备份")
        self._memory_export_btn.setCursor(Qt.PointingHandCursor)
        self._memory_export_btn.setToolTip("将所有记忆导出为 JSON 文件，方便备份或迁移。")
        self._memory_export_btn.clicked.connect(self._export_memories)
        btn_row2.addWidget(self._memory_export_btn)

        btn_row2.addStretch()
        browse_layout.addLayout(btn_row2)

        memory_layout.addWidget(browse_frame)

        memory_layout.addStretch()
        tab_widget.addTab(memory_tab, "🧠 记忆系统")

        # ----- 快捷启动设置选项卡 -----
        ql_tab = QWidget()
        ql_layout = QVBoxLayout(ql_tab)
        ql_layout.setSpacing(12)

        ql_tip = QLabel(
            "在这里添加你常用的应用，之后在 QQ 或桌面端说「打开xxx」时，莲心会优先从这里匹配。"
        )
        ql_tip.setWordWrap(True)
        ql_tip.setStyleSheet("color: #666; font-size: 12px;")
        ql_layout.addWidget(ql_tip)

        self._ql_table = QTableWidget()
        self._ql_table.setColumnCount(3)
        self._ql_table.setHorizontalHeaderLabels(["应用名称", "可执行文件", "完整路径"])
        self._ql_table.horizontalHeader().setStretchLastSection(True)
        self._ql_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._ql_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._ql_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._ql_table.setSelectionMode(QTableWidget.SingleSelection)
        self._ql_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._ql_table.setAlternatingRowColors(True)
        self._ql_table.verticalHeader().setVisible(False)
        self._ql_table.setMinimumHeight(200)
        ql_layout.addWidget(self._ql_table)

        ql_btn_layout = QHBoxLayout()
        ql_btn_add = QPushButton("＋ 添加")
        ql_btn_add.setFixedWidth(100)
        ql_btn_add.setCursor(Qt.PointingHandCursor)
        ql_btn_add.clicked.connect(self._on_ql_add)
        ql_btn_edit = QPushButton("✏ 编辑")
        ql_btn_edit.setFixedWidth(100)
        ql_btn_edit.setCursor(Qt.PointingHandCursor)
        ql_btn_edit.clicked.connect(self._on_ql_edit)
        ql_btn_del = QPushButton("✕ 删除")
        ql_btn_del.setFixedWidth(100)
        ql_btn_del.setCursor(Qt.PointingHandCursor)
        ql_btn_del.clicked.connect(self._on_ql_delete)
        ql_btn_layout.addWidget(ql_btn_add)
        ql_btn_layout.addWidget(ql_btn_edit)
        ql_btn_layout.addWidget(ql_btn_del)
        ql_btn_layout.addStretch()
        ql_layout.addLayout(ql_btn_layout)

        ql_layout.addStretch()
        tab_widget.addTab(ql_tab, "⚡ 快捷启动")

        layout.addWidget(tab_widget)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedSize(80, 32)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_save = QPushButton("保存")
        btn_save.setFixedSize(80, 32)
        btn_save.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(btn_save)

        layout.addLayout(btn_row)

        # 初始化记忆设置界面
        self._init_memory_ui()
        self._refresh_ql_table()

    def _create_frame(self):
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: #F0F2F7;
                border-radius: 8px;
                border: 1px solid #E0E0E8;
            }
        """)
        return frame

    def _init_memory_ui(self):
        """从实例变量填充记忆系统界面的控件。"""
        self._memory_auto_cb.setChecked(self._mem_cfg.get("auto_extract", True))
        self._memory_extract_interval_spin.setValue(self._mem_cfg.get("extract_interval", 6))
        self._memory_extract_msgs_spin.setValue(self._mem_cfg.get("extract_message_count", 20))
        self._memory_max_per_cat_spin.setValue(self._mem_cfg.get("max_items_per_category", 200))
        idx = self._memory_default_cat_combo.findData(self._mem_cfg.get("default_save_category", "knowledge"))
        if idx >= 0:
            self._memory_default_cat_combo.setCurrentIndex(idx)
        self._refresh_memory_tree()

    def _refresh_memory_tree(self):
        """从 SQLite 知识库重新加载记忆并刷新树形列表。"""
        self._memory_tree.clear()
        all_mem = list_all_facts()
        for cat in ALL_CATEGORIES:
            items = all_mem.get(cat, [])
            for item in items:
                source = "自动" if item.get("source") == "auto_extracted" else "手动"
                qitem = QTreeWidgetItem([
                    CATEGORY_DESCRIPTIONS.get(cat, cat).split("：")[0],
                    item.get("content", ""),
                    str(item.get("strength", 1)),
                    source,
                    item.get("created_at", ""),
                ])
                qitem.setData(0, Qt.UserRole, item.get("id", ""))
                qitem.setData(1, Qt.UserRole, cat)
                self._memory_tree.addTopLevelItem(qitem)

    def _delete_selected_memories(self):
        """删除列表中选中的记忆条目（从 SQLite 知识库）。"""
        selected = self._memory_tree.selectedItems()
        if not selected:
            QMessageBox.information(self, "提示", "请先在列表中选择要删除的记忆条目。")
            return
        count = len(selected)
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除选中的 {count} 条记忆吗？此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        deleted = 0
        for item in selected:
            content = item.text(1)
            cat = item.data(1, Qt.UserRole)
            n = delete_facts(content, category=cat)
            deleted += n
        if deleted > 0:
            QMessageBox.information(self, "删除成功", f"已删除 {deleted} 条记忆。")
            self._refresh_memory_tree()
        else:
            QMessageBox.information(self, "提示", "未能删除选中的记忆，请刷新后重试。")

    def _export_memories(self):
        """将全部记忆导出为 JSON 文件。"""
        from pathlib import Path
        default_name = f"莲心记忆备份_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出记忆备份",
            str(Path.home() / "Desktop" / default_name),
            "JSON 文件 (*.json)",
        )
        if not file_path:
            return
        try:
            import json
            all_mem = list_all_facts()
            export_data = {
                "version": 2,
                "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "categories": all_mem,
            }
            Path(file_path).write_text(
                json.dumps(export_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            QMessageBox.information(self, "导出成功", f"记忆已导出到：\n{file_path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", f"导出时出错：{e}")

    # === 以下为原有方法（保持不变） ===
    def _browse_note_path(self):
        from pathlib import Path
        current_path = self._note_path_edit.text().strip()
        if not current_path:
            current_path = str(Path.home() / "Desktop")
        else:
            current_path = str(Path(current_path).parent)
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "选择小纸条文件保存位置",
            current_path,
            "文本文件 (*.txt)"
        )
        if file_path:
            if not file_path.endswith('.txt'):
                file_path += '.txt'
            self._note_path_edit.setText(file_path)

    def _on_font_size_changed(self, value):
        self._font_value_label.setText(str(value))


    def _on_tts_volume_changed(self, value):
        vol = value / 100.0
        self._settings.tts_volume = vol
        # 可选：播放一段测试语音，为了简单起见，不自动播放

    def _on_sfx_volume_changed(self, value):
        vol = value / 100.0
        self._settings.sfx_volume = vol
        # 可选：播放一个测试音效
        try:
            from utils.sound import play_sound
            play_sound("ButtonAll.mp3")
        except:
            pass

    def _set_today_date(self):
        from datetime import date
        today = date.today()
        self._year_spin.setValue(today.year)
        self._month_spin.setValue(today.month)
        self._day_spin.setValue(today.day)

    def _update_day_range(self):
        year = self._year_spin.value()
        month = self._month_spin.value()
        if month in (1, 3, 5, 7, 8, 10, 12):
            max_day = 31
        elif month in (4, 6, 9, 11):
            max_day = 30
        else:
            is_leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
            max_day = 29 if is_leap else 28
        self._day_spin.setRange(1, max_day)
        if self._day_spin.value() > max_day:
            self._day_spin.setValue(max_day)

    def _load_from_settings(self):
        self._silent_cb.setChecked(self._settings.silent_mode)
        self._exit_confirm_cb.setChecked(self._settings.show_exit_confirmation)
        self._autostart_cb.setChecked(is_autostart_enabled())
        font_size = self._settings.font_size
        self._font_slider.setValue(font_size)
        self._font_value_label.setText(str(font_size))

        from pathlib import Path
        note_path = self._settings.note_file_path
        default_path = str(Path.home() / "Desktop" / "小纸条.txt")
        if note_path != default_path:
            self._note_path_edit.setText(note_path)
        else:
            self._note_path_edit.setText("")

        self._year_spin.valueChanged.connect(self._update_day_range)
        self._month_spin.valueChanged.connect(self._update_day_range)
        first_date = self._accompany_stats.get_first_meet_date()
        if first_date:
            try:
                y, m, d = map(int, first_date.split('-'))
                self._year_spin.setValue(y)
                self._month_spin.setValue(m)
                self._day_spin.setValue(d)
            except:
                pass
        self._update_day_range()
       
        self.emotion_prob_slider.setValue(int(self._settings.emotion_probability * 100))
        self.emotion_prob_value.setText(f"{int(self._settings.emotion_probability * 100)}%")

    def _on_save(self):
        self._settings.silent_mode = self._silent_cb.isChecked()
        self._settings.show_exit_confirmation = self._exit_confirm_cb.isChecked()
        self._settings.font_size = self._font_slider.value()
        self.font_size_changed.emit(self._font_slider.value())

        new_path = self._note_path_edit.text().strip()
        if new_path:
            if not new_path.endswith('.txt'):
                new_path += '.txt'
            self._settings.note_file_path = new_path
        else:
            self._settings.note_file_path = ""

        want_autostart = self._autostart_cb.isChecked()
        currently_enabled = is_autostart_enabled()
        if want_autostart != currently_enabled:
            if want_autostart:
                ok, err = enable_autostart()
                if not ok:
                    QMessageBox.warning(self, "自启动设置失败", f"无法写入注册表，请尝试以管理员身份运行。\n\n错误：{err}")
                    return
            else:
                ok, err = disable_autostart()
                if not ok:
                    QMessageBox.warning(self, "自启动设置失败", f"无法删除注册表项。\n\n错误：{err}")
                    return

        date_str = f"{self._year_spin.value():04d}-{self._month_spin.value():02d}-{self._day_spin.value():02d}"
        self._accompany_stats.set_first_meet_date(date_str)
        self.date_saved.emit()

        # ── 保存记忆系统配置 ──
        self._mem_cfg["auto_extract"] = self._memory_auto_cb.isChecked()
        self._mem_cfg["extract_interval"] = self._memory_extract_interval_spin.value()
        self._mem_cfg["extract_message_count"] = self._memory_extract_msgs_spin.value()
        self._mem_cfg["max_items_per_category"] = self._memory_max_per_cat_spin.value()
        self._mem_cfg["default_save_category"] = self._memory_default_cat_combo.currentData()
        self._save_memory_config()

        self.accept()

    def _on_emotion_prob_changed(self, value: int):
        percent = value
        self.emotion_prob_value.setText(f"{percent}%")
        self._settings.emotion_probability = percent / 100.0

    # ── 快捷启动管理 ─────────────────────────────────────────
    def _refresh_ql_table(self):
        apps = get_quick_launch_apps()
        self._ql_apps = apps
        self._ql_table.setRowCount(len(apps))
        for row, app in enumerate(apps):
            self._ql_table.setItem(row, 0, QTableWidgetItem(app.get("name", "")))
            self._ql_table.setItem(row, 1, QTableWidgetItem(app.get("exe_name", "")))
            self._ql_table.setItem(row, 2, QTableWidgetItem(app.get("path", "")))

    def _on_ql_add(self):
        dlg = QuickLaunchEditDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            self._ql_apps.append(dlg.get_data())
            save_quick_launch_apps(self._ql_apps)
            self._refresh_ql_table()

    def _on_ql_edit(self):
        row = self._ql_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选中一个应用")
            return
        dlg = QuickLaunchEditDialog(self, data=self._ql_apps[row])
        if dlg.exec_() == QDialog.Accepted:
            self._ql_apps[row] = dlg.get_data()
            save_quick_launch_apps(self._ql_apps)
            self._refresh_ql_table()

    def _on_ql_delete(self):
        row = self._ql_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选中一个应用")
            return
        name = self._ql_apps[row].get("name", "")
        ok = QMessageBox.question(
            self, "确认删除", f"确定要删除「{name}」吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if ok == QMessageBox.Yes:
            del self._ql_apps[row]
            save_quick_launch_apps(self._ql_apps)
            self._refresh_ql_table()