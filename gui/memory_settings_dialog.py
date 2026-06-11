# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QSpinBox,QWidget,
    QPushButton, QScrollArea, QFrame, QLineEdit, QFileDialog, QComboBox,
    QTabWidget
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from config import get_memory_config, save_memory_config



class MemorySettingsDialog(QDialog):
    """记忆系统独立设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mem_cfg = get_memory_config()

        self.setWindowTitle("🧠 记忆系统设置")
        self.setMinimumSize(500, 420)
        self.resize(520, 460)
        self.setModal(True)
        self.setStyleSheet("background-color: #F8F8FC;")
        self._build_ui()
        self._load_from_config()

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

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 16, 20, 16)

        # 标题
        title = QLabel("🧠 记忆系统设置")
        title.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
        title.setStyleSheet("color: #3A3A5C;")
        layout.addWidget(title)

        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #E0E0E8; max-height: 1px;")
        layout.addWidget(line)

        # 选项卡
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 0;
                background: transparent;
            }
            QTabBar::tab {
                background: #F0F2F7;
                border: 1px solid #E0E0E8;
                border-bottom: 0;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 6px 14px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background: #FFFFFF;
                font-weight: bold;
            }
        """)
        layout.addWidget(tabs)

        # ── 选项卡 1：记忆提取 ─────────────────────────────
        tab1 = QWidget()
        tab1_layout = QVBoxLayout(tab1)
        tab1_layout.setSpacing(14)

        # 自动提取开关
        auto_frame = self._create_frame()
        auto_vbox = QVBoxLayout(auto_frame)
        auto_vbox.setSpacing(8)
        self._memory_auto_cb = QCheckBox("自动提取对话记忆")
        self._memory_auto_cb.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        auto_vbox.addWidget(self._memory_auto_cb)
        auto_desc = QLabel(
            "开启后，莲心会自动从对话中提取关键信息保存到长期记忆中，\n"
            "下次对话时会根据记忆回忆起你的过往信息。\n"
            "关闭后记忆系统仍然可用，但不会自动新增记忆。"
        )
        auto_desc.setWordWrap(True)
        auto_desc.setStyleSheet("color: #888; font-size: 11px; padding: 4px 0;")
        auto_vbox.addWidget(auto_desc)
        tab1_layout.addWidget(auto_frame)

        # 提取间隔（对话轮数）
        interval_frame = self._create_frame()
        interval_vbox = QVBoxLayout(interval_frame)
        interval_vbox.setSpacing(8)
        interval_title = QLabel("自动提取轮次间隔")
        interval_title.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        interval_vbox.addWidget(interval_title)
        self._memory_extract_interval_spin = QSpinBox()
        self._memory_extract_interval_spin.setRange(1, 30)
        self._memory_extract_interval_spin.setSuffix(" 轮对话")
        interval_vbox.addWidget(self._memory_extract_interval_spin)
        interval_desc = QLabel("每完成 N 轮对话后触发一次自动提取，间隔越小记忆越及时但也越占用Token。")
        interval_desc.setWordWrap(True)
        interval_desc.setStyleSheet("color: #888; font-size: 11px; padding: 4px 0;")
        interval_vbox.addWidget(interval_desc)
        tab1_layout.addWidget(interval_frame)

        # 单次提取最大消息数
        count_frame = self._create_frame()
        count_vbox = QVBoxLayout(count_frame)
        count_vbox.setSpacing(8)
        count_title = QLabel("单次提取最大消息数")
        count_title.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        count_vbox.addWidget(count_title)
        self._memory_extract_msgs_spin = QSpinBox()
        self._memory_extract_msgs_spin.setRange(5, 100)
        self._memory_extract_msgs_spin.setSuffix(" 条")
        count_vbox.addWidget(self._memory_extract_msgs_spin)
        count_desc = QLabel("单次自动提取最多包含多少条最近消息，数值越大包含上下文越多但也越慢。")
        count_desc.setWordWrap(True)
        count_desc.setStyleSheet("color: #888; font-size: 11px; padding: 4px 0;")
        count_vbox.addWidget(count_desc)
        tab1_layout.addWidget(count_frame)

        # 每类记忆上限
        max_frame = self._create_frame()
        max_vbox = QVBoxLayout(max_frame)
        max_vbox.setSpacing(8)
        max_title = QLabel("每类记忆最大条数")
        max_title.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        max_vbox.addWidget(max_title)
        self._memory_max_items_spin = QSpinBox()
        self._memory_max_items_spin.setRange(50, 500)
        self._memory_max_items_spin.setSuffix(" 条")
        max_vbox.addWidget(self._memory_max_items_spin)
        max_desc = QLabel("每个分类最多保留多少条记忆，超出自动淘汰最旧+强度最低的记忆。")
        max_desc.setWordWrap(True)
        max_desc.setStyleSheet("color: #888; font-size: 11px; padding: 4px 0;")
        max_vbox.addWidget(max_desc)
        tab1_layout.addWidget(max_frame)

        # 默认保存分类
        cat_frame = self._create_frame()
        cat_vbox = QVBoxLayout(cat_frame)
        cat_vbox.setSpacing(8)
        cat_title = QLabel("默认保存分类")
        cat_title.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        cat_vbox.addWidget(cat_title)
        self._memory_default_cat_combo = QComboBox()
        categories = [
            ("profile", "个人档案"),
            ("preferences", "偏好"),
            ("events", "事件"),
            ("knowledge", "知识"),
            ("behaviors", "行为模式"),
            ("skills", "技能"),
        ]
        for key, name in categories:
            self._memory_default_cat_combo.addItem(name, key)
        cat_vbox.addWidget(self._memory_default_cat_combo)
        cat_desc = QLabel("当用户要求记住某件事但没有指定分类时，默认存到哪个分类。")
        cat_desc.setWordWrap(True)
        cat_desc.setStyleSheet("color: #888; font-size: 11px; padding: 4px 0;")
        cat_vbox.addWidget(cat_desc)
        tab1_layout.addWidget(cat_frame)

        tab1_layout.addStretch()
        tabs.addTab(tab1, "📝 记忆提取")

        # ── 选项卡 2：知识图谱 ─────────────────────────────
        tab2 = QWidget()
        tab2_layout = QVBoxLayout(tab2)
        tab2_layout.setSpacing(14)

        # 图记忆总开关
        graph_frame = self._create_frame()
        graph_vbox = QVBoxLayout(graph_frame)
        graph_vbox.setSpacing(8)
        self._graph_enabled_cb = QCheckBox("启用知识图谱记忆")
        self._graph_enabled_cb.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        graph_vbox.addWidget(self._graph_enabled_cb)
        graph_desc = QLabel(
            "知识图谱存储实体之间的关联关系，让莲心能回答类似\n"
            "\"莲心AI项目用到了哪些技术\"这种关联查询。\n"
            "关闭后只使用分类事实记忆，不影响基本功能。"
        )
        graph_desc.setWordWrap(True)
        graph_desc.setStyleSheet("color: #888; font-size: 11px; padding: 4px 0;")
        graph_vbox.addWidget(graph_desc)
        tab2_layout.addWidget(graph_frame)

        # 自动提取五元组
        auto_quin_frame = self._create_frame()
        auto_quin_vbox = QVBoxLayout(auto_quin_frame)
        auto_quin_vbox.setSpacing(8)
        self._graph_auto_quin_cb = QCheckBox("自动提取实体关系")
        self._graph_auto_quin_cb.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        auto_quin_vbox.addWidget(self._graph_auto_quin_cb)
        auto_quin_desc = QLabel(
            "开启后，莲心会自动识别对话中的实体（人物、地点、物品等）\n"
            "并提取它们之间的关联关系保存到图谱中。\n"
            "不需要手动调用工具添加关系。"
        )
        auto_quin_desc.setWordWrap(True)
        auto_quin_desc.setStyleSheet("color: #888; font-size: 11px; padding: 4px 0;")
        auto_quin_vbox.addWidget(auto_quin_desc)
        tab2_layout.addWidget(auto_quin_frame)

        tab2_layout.addStretch()
        tabs.addTab(tab2, "🔗 知识图谱")

        # ── 选项卡 3：上下文压缩 ─────────────────────────────
        tab3 = QWidget()
        tab3_layout = QVBoxLayout(tab3)
        tab3_layout.setSpacing(14)

        # 滑动窗口大小
        window_frame = self._create_frame()
        window_vbox = QVBoxLayout(window_frame)
        window_vbox.setSpacing(8)
        window_title = QLabel("上下文窗口大小")
        window_title.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        window_vbox.addWidget(window_title)
        self._context_window_spin = QSpinBox()
        self._context_window_spin.setRange(4, 40)
        self._context_window_spin.setSuffix(" 条消息")
        window_vbox.addWidget(self._context_window_spin)
        window_desc = QLabel(
            "对话中始终保留最近 N 条消息作为完整上下文。\n"
            "数值越大：记忆越完整，但 Token 消耗越高。\n"
            "数值越小：越省 Token，但对早期事情回忆可能需要依赖摘要。\n"
            "推荐：15-25"
        )
        window_desc.setWordWrap(True)
        window_desc.setStyleSheet("color: #888; font-size: 11px; padding: 4px 0;")
        window_vbox.addWidget(window_desc)
        tab3_layout.addWidget(window_frame)

        # 摘要压缩开关
        summary_frame = self._create_frame()
        summary_vbox = QVBoxLayout(summary_frame)
        summary_vbox.setSpacing(8)
        self._summary_enabled_cb = QCheckBox("启用早期对话摘要压缩")
        self._summary_enabled_cb.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        summary_vbox.addWidget(self._summary_enabled_cb)
        summary_desc = QLabel(
            "开启后，窗口外的早期对话会被压缩成一段摘要注入上下文，\n"
            "既保持对话连续性，又节省大量 Token。\n"
            "关闭后只保留窗口内对话，早期内容直接截断。"
        )
        summary_desc.setWordWrap(True)
        summary_desc.setStyleSheet("color: #888; font-size: 11px; padding: 4px 0;")
        summary_vbox.addWidget(summary_desc)
        tab3_layout.addWidget(summary_frame)

        # 摘要触发阈值
        trigger_frame = self._create_frame()
        trigger_vbox = QVBoxLayout(trigger_frame)
        trigger_vbox.setSpacing(8)
        trigger_title = QLabel("摘要触发阈值")
        trigger_title.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        trigger_vbox.addWidget(trigger_title)
        self._summary_trigger_spin = QSpinBox()
        self._summary_trigger_spin.setRange(0, 100)
        self._summary_trigger_spin.setSuffix(" 条消息")
        trigger_vbox.addWidget(self._summary_trigger_spin)
        trigger_desc = QLabel(
            "历史消息总数超过多少条后，才开始启动摘要压缩。\n"
            "0 = 无论多少条都压缩（适合非常短对话），推荐 20-40。"
        )
        trigger_desc.setWordWrap(True)
        trigger_desc.setStyleSheet("color: #888; font-size: 11px; padding: 4px 0;")
        trigger_vbox.addWidget(trigger_desc)
        tab3_layout.addWidget(trigger_frame)

        # 估算提示
        estimate_label = QLabel(
            "💡 效果参考：\n"
            "· 关闭摘要 + 窗口 10 条 → Token ~ 1200/轮，早期内容丢失\n"
            "· 开启摘要 + 窗口 20 条 → Token ~ 2500/轮，长对话不增长\n"
            "· 原全量历史 → 30轮后 Token > 6000，持续增长"
        )
        estimate_label.setWordWrap(True)
        estimate_label.setStyleSheet("color: #666; font-size: 11px; background: #F5F5FF; padding: 8px; border-radius: 4px;")
        tab3_layout.addWidget(estimate_label)

        tab3_layout.addStretch()
        tabs.addTab(tab3, "⚙️ 上下文压缩")

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

    def _load_from_config(self):
        from config import get_memory_config, get_graph_config
        self._mem_cfg = get_memory_config()
        self._graph_cfg = get_graph_config()

        # 记忆提取
        self._memory_auto_cb.setChecked(self._mem_cfg.get("auto_extract", True))
        self._memory_extract_interval_spin.setValue(self._mem_cfg.get("extract_interval", 6))
        self._memory_extract_msgs_spin.setValue(self._mem_cfg.get("extract_message_count", 20))
        self._memory_max_items_spin.setValue(self._mem_cfg.get("max_items_per_category", 200))
        # 默认分类
        default_cat = self._mem_cfg.get("default_save_category", "knowledge")
        for i in range(self._memory_default_cat_combo.count()):
            if self._memory_default_cat_combo.itemData(i) == default_cat:
                self._memory_default_cat_combo.setCurrentIndex(i)
                break

        # 知识图谱
        self._graph_enabled_cb.setChecked(self._graph_cfg.get("graph_enabled", True))
        self._graph_auto_quin_cb.setChecked(self._graph_cfg.get("auto_extract_quintuples", True))

        # 上下文压缩
        self._context_window_spin.setValue(self._mem_cfg.get("context_window_size", 20))
        self._summary_enabled_cb.setChecked(self._mem_cfg.get("enable_conversation_summary", True))
        self._summary_trigger_spin.setValue(self._mem_cfg.get("summary_trigger_threshold", 30))

    def _on_save(self):
        cfg = {
            "auto_extract": self._memory_auto_cb.isChecked(),
            "extract_interval": self._memory_extract_interval_spin.value(),
            "extract_message_count": self._memory_extract_msgs_spin.value(),
            "max_items_per_category": self._memory_max_items_spin.value(),
            "default_save_category": self._memory_default_cat_combo.currentData(),
            "context_window_size": self._context_window_spin.value(),
            "enable_conversation_summary": self._summary_enabled_cb.isChecked(),
            "summary_trigger_threshold": self._summary_trigger_spin.value(),
        }
        from config import save_memory_config
        save_memory_config(cfg)

        # 保存图记忆配置
        graph_cfg = {
            "graph_enabled": self._graph_enabled_cb.isChecked(),
            "auto_extract_quintuples": self._graph_auto_quin_cb.isChecked(),
            "graph_max_edges": self._graph_cfg.get("graph_max_edges", 2000),
        }
        from config import save_graph_config
        save_graph_config(graph_cfg)

        self.accept()

