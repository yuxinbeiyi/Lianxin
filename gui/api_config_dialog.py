"""
ApiConfigDialog：API Key 配置对话框
支持填写 DeepSeek API、阿里云语音识别、QQ 桥接的配置信息。
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QFrame, QMessageBox, QTabWidget,
    QWidget, QFormLayout, QCheckBox, QComboBox, QApplication,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont

from config import (
    get_api_config, save_api_config,
    get_aliyun_stt_config, save_aliyun_stt_config,
    get_qq_bridge_config, save_qq_bridge_config,
    get_siliconflow_config, save_siliconflow_config,
    get_qweather_config, save_qweather_config,
    get_tavily_config, save_tavily_config,
    get_firecrawl_config, save_firecrawl_config,

)

# ── 测试 DeepSeek 连接的后台线程 ──────────────────────────────

class _TestWorker(QThread):
    success = pyqtSignal(str)
    failed  = pyqtSignal(str)

    def __init__(self, api_key: str, base_url: str, model: str, is_local: bool = False, parent=None):
        super().__init__(parent)
        self._api_key  = api_key
        self._base_url = base_url
        self._model    = model
        self._is_local = is_local

    def run(self):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self._api_key, base_url=self._base_url)
            kwargs = dict(
                model=self._model,
                max_tokens=16,
                messages=[{"role": "user", "content": "你好"}],
            )
            # 本地模型温度可能需要设为 0 避免随机性
            if self._is_local:
                kwargs["temperature"] = 0.0
            resp = client.chat.completions.create(**kwargs)
            reply = resp.choices[0].message.content or ""
            self.success.emit(reply[:20])
        except Exception as e:
            self.failed.emit(str(e))


class _BalanceWorker(QThread):
    success = pyqtSignal(dict)
    failed  = pyqtSignal(str)

    def __init__(self, api_key: str, parent=None):
        super().__init__(parent)
        self._api_key = api_key

    def run(self):
        from utils.balance import get_balance_info
        result, error = get_balance_info(self._api_key)
        if error:
            self.failed.emit(error)
        else:
            self.success.emit(result)


# ── 对话框主体 ────────────────────────────────────────────────

class ApiConfigDialog(QDialog):
    config_saved = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("API 配置")
        self.setFixedWidth(560)
        self.setModal(True)
        self.setStyleSheet("background-color: #F8F8FC;")
        self._test_worker: _TestWorker | None = None
        self._build_ui()
        self._load()

    # ── 界面构建 ──────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        # 标题
        title = QLabel("🔑 API 配置")
        title.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
        title.setStyleSheet("color: #3A3A5C;")
        layout.addWidget(title)

        desc = QLabel(
            "配置 DeepSeek API Key、阿里云语音识别和 QQ 桥接的参数。\n"
            "所有信息仅保存在本地 data/user_config.json，不会上传到任何服务器。"
        )
        desc.setFont(QFont("Microsoft YaHei UI", 9))
        desc.setStyleSheet("color: #888888;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #E0E0E8; max-height: 1px;")
        layout.addWidget(line)

        # ── Tab 页 ────────────────────────────────────────────
        tabs = QTabWidget()
        tabs.setFont(QFont("Microsoft YaHei UI", 9))
        tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #D8D8EE;
                border-radius: 8px;
                background-color: #FFFFFF;
                padding: 0px;
            }
            QTabBar::tab {
                background-color: #F0F0F8;
                border: 1px solid #D8D8EE;
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                padding: 8px 20px;
                margin-right: 2px;
                color: #666666;
            }
            QTabBar::tab:selected {
                background-color: #FFFFFF;
                color: #3A3A5C;
                font-weight: bold;
                border-bottom: 1px solid #FFFFFF;
            }
            QTabBar::tab:hover:!selected {
                background-color: #E4E4F0;
            }
        """)
        self._tab_widget = tabs

        # Tab 0: DeepSeek API
        tab_ds = QWidget()
        self._build_tab_deepseek(tab_ds)
        tabs.addTab(tab_ds, "DeepSeek API")

        # Tab 1: 语音识别
        tab_ali = QWidget()
        self._build_tab_aliyun(tab_ali)
        tabs.addTab(tab_ali, "语音识别")

        # Tab 2: QQ 聊天
        tab_qq = QWidget()
        self._build_tab_qq(tab_qq)
        tabs.addTab(tab_qq, "QQ 聊天")

        # Tab 3: 视觉理解 (SiliconFlow)
        tab_vision = QWidget()
        self._build_tab_siliconflow(tab_vision)
        tabs.addTab(tab_vision, "视觉理解")

        # Tab 4: 和风天气
        tab_qw = QWidget()
        self._build_tab_qweather(tab_qw)
        tabs.addTab(tab_qw, "☁️ 和风天气")
        
        # Tab 5: Tavily Search
        tab_tavily = QWidget()
        self._build_tab_tavily(tab_tavily)
        tabs.addTab(tab_tavily, "🔍 Tavily 搜索")
        # Tab 6: Firecrawl
        tab_firecrawl = QWidget()
        self._build_tab_firecrawl(tab_firecrawl)
        tabs.addTab(tab_firecrawl, "🔍 Firecrawl 爬取")


        layout.addWidget(tabs)

        # ── 底部按钮区 ──
        btn_row = QHBoxLayout()

        self._test_btn = QPushButton("测试 DeepSeek 连接")
        self._test_btn.setFixedHeight(36)
        self._test_btn.setFont(QFont("Microsoft YaHei UI", 9))
        self._test_btn.setCursor(Qt.PointingHandCursor)
        self._test_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9500;
                color: white;
                border-radius: 8px;
                border: none;
                padding: 0 16px;
            }
            QPushButton:hover   { background-color: #E08600; }
            QPushButton:pressed { background-color: #C07600; }
            QPushButton:disabled{ background-color: #CCCCCC; }
        """)
        self._test_btn.clicked.connect(self._on_test)
        btn_row.addWidget(self._test_btn)

        btn_row.addStretch()

        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedSize(80, 36)
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
        btn_save.setFixedSize(80, 36)
        btn_save.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.setStyleSheet("""
            QPushButton {
                background-color: #6C7BFF;
                color: white;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover   { background-color: #5A6AEE; }
            QPushButton:pressed { background-color: #4A5ADE; }
        """)
        btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(btn_save)

        layout.addLayout(btn_row)

    # ── Tab: DeepSeek API ───────────────────────────────────

    def _build_tab_deepseek(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(16, 20, 16, 16)
        form = QFormLayout()
        form.setSpacing(16)
        form.setContentsMargins(0, 0, 0, 0)

        # ── 本地模型开关 ──
        self._use_local_check = QCheckBox("使用本地模型 (Ollama)")
        self._use_local_check.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        self._use_local_check.setStyleSheet("""
            QCheckBox {
                color: #3A3A5C;
                spacing: 8px;
                padding: 8px 12px;
                background-color: #F0F0F8;
                border-radius: 8px;
                border: 1px solid #D8D8EE;
            }
            QCheckBox:hover { background-color: #E4E4F0; }
            QCheckBox::indicator { width: 18px; height: 18px; }
        """)
        self._use_local_check.toggled.connect(self._on_use_local_toggled)
        layout.addWidget(self._use_local_check)

        # 提示
        self._local_hint = QLabel(
            "💡 开启后将使用本地 Ollama 部署的模型，无需联网，不消耗 API 额度。\n"
            "    注意：本地模型不支持工具调用（打开应用、文件操作等），仅限纯文本聊天。"
        )
        self._local_hint.setFont(QFont("Microsoft YaHei UI", 8))
        self._local_hint.setStyleSheet("color: #999999; background-color: #F8F8FC; padding: 8px; border-radius: 6px;")
        self._local_hint.setWordWrap(True)
        self._local_hint.hide()
        layout.addWidget(self._local_hint)

        layout.addSpacing(4)

        # ── 云端配置分组 ──
        self._cloud_group = QFrame()
        self._cloud_group.setStyleSheet("QFrame { border: none; }")
        cloud_layout = QVBoxLayout(self._cloud_group)
        cloud_layout.setContentsMargins(0, 0, 0, 0)
        cloud_form = QFormLayout()
        cloud_form.setSpacing(16)
        cloud_form.setContentsMargins(0, 0, 0, 0)

        # API Key
        self._key_edit = QLineEdit()
        self._key_edit.setPlaceholderText("sk-xxxxxxxxxxxxxxxxxxxxxxxx")
        self._key_edit.setEchoMode(QLineEdit.Password)
        self._key_edit.setFont(QFont("Consolas", 10))
        self._apply_field_style(self._key_edit)
        key_layout = QHBoxLayout()
        key_layout.addWidget(self._key_edit)
        self._show_btn = QPushButton("显示")
        self._show_btn.setFixedSize(52, 32)
        self._show_btn.setCheckable(True)
        self._show_btn.setCursor(Qt.PointingHandCursor)
        self._show_btn.setFont(QFont("Microsoft YaHei UI", 8))
        self._show_btn.setStyleSheet("""
            QPushButton {
                background-color: #ECEEFF;
                color: #5060DD;
                border-radius: 6px;
                border: 1px solid #C8CCEE;
            }
            QPushButton:checked {
                background-color: #5060DD;
                color: white;
            }
            QPushButton:hover { background-color: #DDE0FF; }
        """)
        self._show_btn.toggled.connect(self._toggle_key_visibility)
        key_layout.addWidget(self._show_btn)
        cloud_form.addRow("API Key:", key_layout)

        # Base URL
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("https://api.deepseek.com")
        self._url_edit.setFont(QFont("Consolas", 10))
        self._apply_field_style(self._url_edit)
        cloud_form.addRow("Base URL:", self._url_edit)

        # 模型名称
        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText("deepseek-v4-flash")
        self._model_edit.setFont(QFont("Consolas", 10))
        self._apply_field_style(self._model_edit)
        cloud_form.addRow("模型名称:", self._model_edit)

        # API 格式
        self._api_format_combo = QComboBox()
        self._api_format_combo.addItems(["openai", "anthropic"])
        self._api_format_combo.setFixedHeight(34)
        self._api_format_combo.setFont(QFont("Microsoft YaHei UI", 10))
        self._api_format_combo.setStyleSheet("""
            QComboBox {
                border: 1px solid #D8D8EE;
                border-radius: 8px;
                padding: 4px 8px;
                background-color: #FFFFFF;
                color: #2C2C2C;
            }
            QComboBox:focus { border: 1px solid #6C7BFF; }
            QComboBox::drop-down { border: none; width: 24px; }
            QComboBox QAbstractItemView {
                background-color: #FFFFFF;
                border: 1px solid #D8D8EE;
                selection-background-color: #ECEEFF;
                color: #2C2C2C;
            }
        """)
        cloud_form.addRow("API 格式:", self._api_format_combo)

        # 最大 Token 数
        self._tokens_spin = QSpinBox()
        self._tokens_spin.setRange(512, 32768)
        self._tokens_spin.setSingleStep(512)
        self._tokens_spin.setFixedHeight(34)
        self._tokens_spin.setFont(QFont("Microsoft YaHei UI", 10))
        self._tokens_spin.setStyleSheet("""
            QSpinBox {
                border: 1px solid #D8D8EE;
                border-radius: 8px;
                padding: 4px 8px;
                background-color: #FFFFFF;
                color: #2C2C2C;
            }
            QSpinBox:focus { border: 1px solid #6C7BFF; }
        """)
        cloud_form.addRow("最大 Token 数:", self._tokens_spin)

        cloud_layout.addLayout(cloud_form)

        # 余额查询按钮
        balance_btn = QPushButton("💰 查询余额")
        balance_btn.setFixedHeight(36)
        balance_btn.setFont(QFont("Microsoft YaHei UI", 9))
        balance_btn.setCursor(Qt.PointingHandCursor)
        balance_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9500;
                color: white;
                border-radius: 8px;
                border: none;
                padding: 0 16px;
            }
            QPushButton:hover   { background-color: #E08600; }
            QPushButton:pressed { background-color: #C07600; }
            QPushButton:disabled{ background-color: #CCCCCC; }
        """)
        balance_btn.clicked.connect(self._on_balance_query)
        cloud_layout.addWidget(balance_btn)

        layout.addWidget(self._cloud_group)

        # ── 本地配置分组 ──
        self._local_group = QFrame()
        self._local_group.setStyleSheet("QFrame { border: none; }")
        local_layout = QVBoxLayout(self._local_group)
        local_layout.setContentsMargins(0, 0, 0, 0)
        local_form = QFormLayout()
        local_form.setSpacing(16)
        local_form.setContentsMargins(0, 0, 0, 0)

        # 本地服务地址
        self._local_url_edit = QLineEdit()
        self._local_url_edit.setPlaceholderText("http://localhost:11434/v1")
        self._local_url_edit.setFont(QFont("Consolas", 10))
        self._apply_field_style(self._local_url_edit)
        local_form.addRow("Ollama 地址:", self._local_url_edit)

        # 本地模型名称
        self._local_model_edit = QLineEdit()
        self._local_model_edit.setPlaceholderText("my-deepseek")
        self._local_model_edit.setFont(QFont("Consolas", 10))
        self._apply_field_style(self._local_model_edit)
        local_form.addRow("本地模型名:", self._local_model_edit)

        # 路由模型名称（意图分类用小模型）
        self._router_model_edit = QLineEdit()
        self._router_model_edit.setPlaceholderText("my-qwen（留空则回退到规则路由）")
        self._router_model_edit.setFont(QFont("Consolas", 10))
        self._apply_field_style(self._router_model_edit)
        local_form.addRow("路由模型名:", self._router_model_edit)

        local_layout.addLayout(local_form)
        self._local_group.hide()
        layout.addWidget(self._local_group)

        layout.addStretch()

    def _on_use_local_toggled(self, checked: bool):
        """切换本地/云端模式的 UI 可见性。"""
        self._cloud_group.setVisible(not checked)
        self._local_group.setVisible(checked)
        self._local_hint.setVisible(checked)
        # 更新测试按钮文字
        if checked:
            self._test_btn.setText("测试本地模型连接")
        else:
            self._test_btn.setText("测试 DeepSeek 连接")

    # ── Tab: 阿里云语音识别 ─────────────────────────────────

    def _build_tab_aliyun(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(16, 20, 16, 16)
        form = QFormLayout()
        form.setSpacing(16)
        form.setContentsMargins(0, 0, 0, 0)

        self._ali_access_key_id = QLineEdit()
        self._ali_access_key_id.setPlaceholderText("LTAI...")
        self._apply_field_style(self._ali_access_key_id)
        form.addRow("AccessKey ID:", self._ali_access_key_id)

        self._ali_access_key_secret = QLineEdit()
        self._ali_access_key_secret.setPlaceholderText("请妥善保管")
        self._ali_access_key_secret.setEchoMode(QLineEdit.Password)
        self._apply_field_style(self._ali_access_key_secret)
        ali_secret_layout = QHBoxLayout()
        ali_secret_layout.addWidget(self._ali_access_key_secret)
        self._show_ali_btn = QPushButton("显示")
        self._show_ali_btn.setFixedSize(52, 32)
        self._show_ali_btn.setCheckable(True)
        self._show_ali_btn.setCursor(Qt.PointingHandCursor)
        self._show_ali_btn.setFont(QFont("Microsoft YaHei UI", 8))
        self._show_ali_btn.setStyleSheet("""
            QPushButton {
                background-color: #ECEEFF;
                color: #5060DD;
                border-radius: 6px;
                border: 1px solid #C8CCEE;
            }
            QPushButton:checked {
                background-color: #5060DD;
                color: white;
            }
            QPushButton:hover { background-color: #DDE0FF; }
        """)
        self._show_ali_btn.toggled.connect(self._toggle_ali_secret_visibility)
        ali_secret_layout.addWidget(self._show_ali_btn)
        form.addRow("AccessKey Secret:", ali_secret_layout)

        self._ali_app_key = QLineEdit()
        self._ali_app_key.setPlaceholderText("ZCaEYdFPhr9kuR3V")
        self._apply_field_style(self._ali_app_key)
        form.addRow("AppKey:", self._ali_app_key)

        layout.addLayout(form)
        layout.addStretch()

    # ── Tab: QQ 聊天 ────────────────────────────────────────

    def _build_tab_qq(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(16, 20, 16, 16)
        form = QFormLayout()
        form.setSpacing(16)
        form.setContentsMargins(0, 0, 0, 0)

        # QQ 账号（机器人）
        self._qq_account = QLineEdit()
        self._qq_account.setPlaceholderText("机器人 QQ 号")
        self._apply_field_style(self._qq_account)
        form.addRow("QQ 账号:", self._qq_account)

        # WebSocket 地址
        self._ws_url = QLineEdit()
        self._ws_url.setPlaceholderText("ws://127.0.0.1:3001")
        self._ws_url.setFont(QFont("Consolas", 10))
        self._apply_field_style(self._ws_url)
        form.addRow("WebSocket 地址:", self._ws_url)

        # 主人 QQ 号
        self._owner_qq = QLineEdit()
        self._owner_qq.setPlaceholderText("主人的 QQ 号")
        self._apply_field_style(self._owner_qq)
        form.addRow("主人 QQ 号:", self._owner_qq)

        # 主人称呼
        self._owner_name = QLineEdit()
        self._owner_name.setPlaceholderText("主人")
        self._owner_name.setText("主人")
        self._apply_field_style(self._owner_name)
        form.addRow("主人称呼:", self._owner_name)

        # 自动连接
        self._auto_enable = QCheckBox("程序启动时自动连接 QQ")
        self._auto_enable.setFont(QFont("Microsoft YaHei UI", 9))
        self._auto_enable.setStyleSheet("color: #555555; spacing: 6px;")
        form.addRow("", self._auto_enable)

        layout.addLayout(form)

        # 帮助提示
        help_text = QLabel(
            "💡 使用前需要自行部署 NapCatQQ（开源 OneBot v11 实现），\n"
            "    并在 NapCatQQ 配置中开启 WebSocket 服务端。\n"
            "    莲心AI 不支持也无法内置 NapCatQQ。"
        )
        help_text.setFont(QFont("Microsoft YaHei UI", 8))
        help_text.setStyleSheet("color: #999999; background-color: #F8F8FC; padding: 8px; border-radius: 6px;")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        layout.addStretch()

    # ── Tab: 视觉理解 (SiliconFlow) ──────────────────────────

    def _build_tab_siliconflow(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(16, 20, 16, 16)
        form = QFormLayout()
        form.setSpacing(16)
        form.setContentsMargins(0, 0, 0, 0)

        # API Key
        self._sf_key_edit = QLineEdit()
        self._sf_key_edit.setPlaceholderText("sk-xxxxxxxxxxxxxxxxxxxxxxxx")
        self._sf_key_edit.setEchoMode(QLineEdit.Password)
        self._sf_key_edit.setFont(QFont("Consolas", 10))
        self._apply_field_style(self._sf_key_edit)
        sf_key_layout = QHBoxLayout()
        sf_key_layout.addWidget(self._sf_key_edit)
        self._show_sf_btn = QPushButton("显示")
        self._show_sf_btn.setFixedSize(52, 32)
        self._show_sf_btn.setCheckable(True)
        self._show_sf_btn.setCursor(Qt.PointingHandCursor)
        self._show_sf_btn.setFont(QFont("Microsoft YaHei UI", 8))
        self._show_sf_btn.setStyleSheet("""
            QPushButton {
                background-color: #ECEEFF;
                color: #5060DD;
                border-radius: 6px;
                border: 1px solid #C8CCEE;
            }
            QPushButton:checked {
                background-color: #5060DD;
                color: white;
            }
            QPushButton:hover { background-color: #DDE0FF; }
        """)
        self._show_sf_btn.toggled.connect(self._toggle_sf_secret_visibility)
        sf_key_layout.addWidget(self._show_sf_btn)
        form.addRow("API Key:", sf_key_layout)

        # Base URL
        self._sf_url_edit = QLineEdit()
        self._sf_url_edit.setPlaceholderText("https://api.siliconflow.cn/v1")
        self._sf_url_edit.setFont(QFont("Consolas", 10))
        self._apply_field_style(self._sf_url_edit)
        form.addRow("Base URL:", self._sf_url_edit)

        # 模型名称
        self._sf_model_edit = QLineEdit()
        self._sf_model_edit.setPlaceholderText("Qwen/Qwen3-VL-30B-A3B-Instruct")
        self._sf_model_edit.setFont(QFont("Consolas", 10))
        self._apply_field_style(self._sf_model_edit)
        form.addRow("模型名称:", self._sf_model_edit)

        layout.addLayout(form)
        layout.addSpacing(8)

        # 帮助提示
        help_text = QLabel(
            "🔍 SiliconFlow 提供托管的视觉大模型 API。\n"
            "    推荐模型 Qwen/Qwen3-VL-30B-A3B-Instruct（性价比高、262K上下文）。\n"
            "    也可尝试 Qwen/Qwen2.5-VL-72B-Instruct 或 Qwen/Qwen3-Omni。\n"
            "    需在 siliconflow.cn 注册并申请 API Key。"
        )
        help_text.setFont(QFont("Microsoft YaHei UI", 8))
        help_text.setStyleSheet("color: #999999; background-color: #F8F8FC; padding: 8px; border-radius: 6px;")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        layout.addStretch()

    # ── 和风天气选项卡 ───────────────────────────────────────

    def _build_tab_qweather(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        title = QLabel("☁️ 和风天气 API 配置")
        title.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        title.setStyleSheet("color: #3A3A5C;")
        layout.addWidget(title)

        desc = QLabel(
            "配置和风天气 API Key 后，莲心就能查询实时天气和预报，"
            "并在适当时机主动提醒你天气变化和出行建议～"
        )
        desc.setFont(QFont("Microsoft YaHei UI", 9))
        desc.setStyleSheet("color: #888888;")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        layout.addSpacing(8)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)

        # API Key（密码模式）
        key_row = QHBoxLayout()
        self._qw_key_edit = QLineEdit()
        self._qw_key_edit.setPlaceholderText("输入和风天气 API Key")
        self._qw_key_edit.setEchoMode(QLineEdit.Password)
        self._qw_key_edit.setFont(QFont("Consolas", 10))
        self._apply_field_style(self._qw_key_edit)
        key_row.addWidget(self._qw_key_edit)

        self._show_qw_btn = QPushButton("显示")
        self._show_qw_btn.setFixedSize(60, 34)
        self._show_qw_btn.setFont(QFont("Microsoft YaHei UI", 9))
        self._show_qw_btn.setCursor(Qt.PointingHandCursor)
        self._show_qw_btn.setStyleSheet("""
            QPushButton {
                background-color: #F0F0F8;
                color: #555555;
                border-radius: 8px;
                border: 1px solid #D8D8EE;
            }
            QPushButton:hover { background-color: #E4E4F0; }
        """)
        self._show_qw_btn.setCheckable(True)
        self._show_qw_btn.clicked.connect(self._toggle_qw_key_visibility)
        key_row.addWidget(self._show_qw_btn)

        form.addRow("API Key:", key_row)
        # API 专属域名
        self._qw_host_edit = QLineEdit()
        self._qw_host_edit.setPlaceholderText("pp65npvqtt.re.qweatherapi.com")
        self._qw_host_edit.setFont(QFont("Consolas", 10))
        self._apply_field_style(self._qw_host_edit)
        form.addRow("API 主机:", self._qw_host_edit)

        # 开发者 ID
        self._qw_dev_id_edit = QLineEdit()
        self._qw_dev_id_edit.setPlaceholderText("Q158859C18（选填）")
        self._qw_dev_id_edit.setFont(QFont("Consolas", 10))
        self._apply_field_style(self._qw_dev_id_edit)
        form.addRow("开发者 ID:", self._qw_dev_id_edit)

        # 主动天气提醒开关
        self._qw_auto_remind = QCheckBox("开启主动天气提醒")
        self._qw_auto_remind.setFont(QFont("Microsoft YaHei UI", 9))
        self._qw_auto_remind.setStyleSheet("color: #3A3A5C;")
        form.addRow("", self._qw_auto_remind)

        # 每日提醒时间
        self._qw_remind_time = QComboBox()
        self._qw_remind_time.setFont(QFont("Microsoft YaHei UI", 9))
        self._qw_remind_time.setFixedWidth(120)
        self._qw_remind_time.setStyleSheet("""
            QComboBox {
                border: 1px solid #D8D8EE;
                border-radius: 8px;
                padding: 4px 10px;
                background-color: #FFFFFF;
                color: #2C2C2C;
            }
            QComboBox:focus { border: 1px solid #6C7BFF; }
        """)
        for h in range(6, 23):
            self._qw_remind_time.addItem(f"{h:02d}:00")
            self._qw_remind_time.addItem(f"{h:02d}:30")
        form.addRow("提醒时间:", self._qw_remind_time)

        layout.addLayout(form)
        layout.addSpacing(8)

        help_text = QLabel(
            "💡 和风天气（QWeather）免费版每日 1000 次调用，个人使用绰绰有余。\n"
            "    API 主机和 Key 可在 console.qweather.com 获取。\n"
            "    建议开启主动提醒，莲心会在每天早上提醒你今日天气和出行建议。"
        )
        help_text.setFont(QFont("Microsoft YaHei UI", 8))
        help_text.setStyleSheet("color: #999999; background-color: #F8F8FC; padding: 8px; border-radius: 6px;")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        layout.addStretch()

        # ── Tavily Search 选项卡 ─────────────────────────────────

    def _build_tab_tavily(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        title = QLabel("🔍 Tavily Search AI 配置")
        title.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        title.setStyleSheet("color: #3A3A5C;")
        layout.addWidget(title)

        desc = QLabel(
            "配置 Tavily Search API Key 后，莲心就能使用高质量 AI 搜索，"
            "获取实时新闻和公开网页内容，绕过后端网络限制。\n"
            "注册地址：https://tavily.com/，免费额度 1000次/月。"
        )
        desc.setFont(QFont("Microsoft YaHei UI", 9))
        desc.setStyleSheet("color: #888888;")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        layout.addSpacing(8)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)

        # API Key（密码模式）
        key_row = QHBoxLayout()
        self._tv_key_edit = QLineEdit()
        self._tv_key_edit.setPlaceholderText("tvly-xxxxxxxxxxxxxxxxxxxxxxxx")
        self._tv_key_edit.setEchoMode(QLineEdit.Password)
        self._tv_key_edit.setFont(QFont("Consolas", 10))
        self._apply_field_style(self._tv_key_edit)
        key_row.addWidget(self._tv_key_edit)

        self._show_tv_btn = QPushButton("显示")
        self._show_tv_btn.setFixedSize(60, 34)
        self._show_tv_btn.setFont(QFont("Microsoft YaHei UI", 9))
        self._show_tv_btn.setCursor(Qt.PointingHandCursor)
        self._show_tv_btn.setStyleSheet("""
            QPushButton {
                background-color: #F0F0F8;
                color: #555555;
                border-radius: 8px;
                border: 1px solid #D8D8EE;
            }
            QPushButton:hover { background-color: #E4E4F0; }
        """)
        self._show_tv_btn.setCheckable(True)
        self._show_tv_btn.clicked.connect(self._toggle_tv_key_visibility)
        key_row.addWidget(self._show_tv_btn)

        form.addRow("API Key:", key_row)

        layout.addLayout(form)
        layout.addStretch()

        # 帮助提示
        help_text = QLabel(
            "💡 提示：MCP Tavily 请求从你本地发出，绕过后端被墙限制，搜索质量优于 DuckDuckGo。"
        )
        help_text.setFont(QFont("Microsoft YaHei UI", 8))
        help_text.setStyleSheet("color: #999999; background-color: #F8F8FC; padding: 8px; border-radius: 6px;")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

    # ── Firecrawl 选项卡 ─────────────────────────────────
    def _build_tab_firecrawl(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        title = QLabel("🕷️ Firecrawl 网页爬虫配置")
        title.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        title.setStyleSheet("color: #3A3A5C;")
        layout.addWidget(title)

        desc = QLabel(
            "配置 Firecrawl API Key 后，莲心就能抓取任意网页的纯净内容，"
            "输出干净的 Markdown 格式，供 AI 分析使用。\n"
            "配合 Tavily 搜索：搜索 → 发现网页 → 爬取完整内容。\n"
            "注册地址：https://firecrawl.org.cn/，免费额度 500页/月。"
        )
        desc.setFont(QFont("Microsoft YaHei UI", 9))
        desc.setStyleSheet("color: #888888;")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        layout.addSpacing(8)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)

        # API Key（密码模式）
        key_row = QHBoxLayout()
        self._fc_key_edit = QLineEdit()
        self._fc_key_edit.setPlaceholderText("fc-xxxxxxxxxxxxxxxxxxxxxxxx")
        self._fc_key_edit.setEchoMode(QLineEdit.Password)
        self._fc_key_edit.setFont(QFont("Consolas", 10))
        self._apply_field_style(self._fc_key_edit)
        key_row.addWidget(self._fc_key_edit)

        self._show_fc_btn = QPushButton("显示")
        self._show_fc_btn.setFixedSize(60, 34)
        self._show_fc_btn.setFont(QFont("Microsoft YaHei UI", 9))
        self._show_fc_btn.setCursor(Qt.PointingHandCursor)
        self._show_fc_btn.setStyleSheet("""
            QPushButton {
                background-color: #F0F0F8;
                color: #555555;
                border-radius: 8px;
                border: 1px solid #D8D8EE;
            }
            QPushButton:hover { background-color: #E4E4F0; }
        """)
        self._show_fc_btn.setCheckable(True)
        self._show_fc_btn.clicked.connect(self._toggle_fc_key_visibility)
        key_row.addWidget(self._show_fc_btn)

        form.addRow("API Key:", key_row)

        layout.addLayout(form)
        layout.addStretch()

        # 帮助提示
        help_text = QLabel(
            "💡 提示：Firecrawl 将网页转为 LLM 友好的 Markdown，自动去除广告和噪音。"
        )
        help_text.setFont(QFont("Microsoft YaHei UI", 8))
        help_text.setStyleSheet("color: #999999; background-color: #F8F8FC; padding: 8px; border-radius: 6px;")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

    def _toggle_fc_key_visibility(self, checked: bool):
        self._fc_key_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self._show_fc_btn.setText("隐藏" if checked else "显示")


    def _toggle_qw_key_visibility(self, checked: bool):
        self._qw_key_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self._show_qw_btn.setText("隐藏" if checked else "显示")
    
    def _toggle_tv_key_visibility(self, checked: bool):
        self._tv_key_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self._show_tv_btn.setText("隐藏" if checked else "显示")

    # ── 辅助样式 ──────────────────────────────────────────────

    def _apply_field_style(self, widget: QLineEdit):
        widget.setFixedHeight(34)
        widget.setStyleSheet("""
            QLineEdit {
                border: 1px solid #D8D8EE;
                border-radius: 8px;
                padding: 4px 10px;
                background-color: #FFFFFF;
                color: #2C2C2C;
            }
            QLineEdit:focus { border: 1px solid #6C7BFF; }
        """)

    def _toggle_key_visibility(self, checked: bool):
        self._key_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self._show_btn.setText("隐藏" if checked else "显示")

    def _toggle_ali_secret_visibility(self, checked: bool):
        self._ali_access_key_secret.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self._show_ali_btn.setText("隐藏" if checked else "显示")

    def _toggle_sf_secret_visibility(self, checked: bool):
        self._sf_key_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self._show_sf_btn.setText("隐藏" if checked else "显示")

    # ── 数据加载 ─────────────────────────────────────────────

    def _load(self):
        # DeepSeek 配置
        ds_cfg = get_api_config()
        use_local = ds_cfg.get("use_local", False)
        self._use_local_check.setChecked(use_local)
        self._key_edit.setText(ds_cfg.get("api_key", ""))
        self._url_edit.setText(ds_cfg.get("base_url", "https://api.deepseek.com"))
        self._model_edit.setText(ds_cfg.get("model", "deepseek-v4-flash"))
        self._tokens_spin.setValue(ds_cfg.get("max_tokens", 4096))
        # api_format
        api_format = ds_cfg.get("api_format", "openai")
        idx = self._api_format_combo.findText(api_format)
        if idx >= 0:
            self._api_format_combo.setCurrentIndex(idx)
        self._local_url_edit.setText(ds_cfg.get("local_base_url", "http://localhost:11434/v1"))
        self._local_model_edit.setText(ds_cfg.get("local_model_name", "my-deepseek"))
        self._router_model_edit.setText(ds_cfg.get("router_model", "my-qwen"))
        # 根据 use_local 状态切换 UI（toggle 信号不会在 setChecked 前触发）
        self._cloud_group.setVisible(not use_local)
        self._local_group.setVisible(use_local)
        self._local_hint.setVisible(use_local)
        if use_local:
            self._test_btn.setText("测试本地模型连接")
        else:
            self._test_btn.setText("测试 DeepSeek 连接")

        # 阿里云 STT 配置
        ali_cfg = get_aliyun_stt_config()
        self._ali_access_key_id.setText(ali_cfg.get("access_key_id", ""))
        self._ali_access_key_secret.setText(ali_cfg.get("access_key_secret", ""))
        self._ali_app_key.setText(ali_cfg.get("app_key", ""))

        # QQ 桥接配置
        qq_cfg = get_qq_bridge_config()
        self._qq_account.setText(qq_cfg.get("qq_account", ""))
        self._ws_url.setText(qq_cfg.get("ws_url", "ws://127.0.0.1:3001"))
        self._owner_qq.setText(qq_cfg.get("owner_qq", ""))
        owner_name = qq_cfg.get("owner_name", "")
        if owner_name:
            self._owner_name.setText(owner_name)
        self._auto_enable.setChecked(qq_cfg.get("enabled", False))

        # SiliconFlow 视觉 API 配置
        sf_cfg = get_siliconflow_config()
        self._sf_key_edit.setText(sf_cfg.get("api_key", ""))
        self._sf_url_edit.setText(sf_cfg.get("base_url", "https://api.siliconflow.cn/v1"))
        self._sf_model_edit.setText(sf_cfg.get("vision_model", "Qwen/Qwen3-VL-30B-A3B-Instruct"))

        # 和风天气配置
        qw_cfg = get_qweather_config()
        self._qw_key_edit.setText(qw_cfg.get("api_key", ""))
        self._qw_auto_remind.setChecked(qw_cfg.get("auto_remind", True))
        self._qw_host_edit.setText(qw_cfg.get("api_host", ""))
        self._qw_dev_id_edit.setText(qw_cfg.get("dev_id", ""))
        self._qw_remind_time.setCurrentText(qw_cfg.get("remind_time", "07:00"))
        remind_time = qw_cfg.get("remind_time", "07:00")
        idx = self._qw_remind_time.findText(remind_time)
        if idx >= 0:
            self._qw_remind_time.setCurrentIndex(idx)

        # Tavily Search 配置
        tv_cfg = get_tavily_config()
        self._tv_key_edit.setText(tv_cfg.get("api_key", ""))

        # Firecrawl 网页爬虫配置
        fc_cfg = get_firecrawl_config()
        self._fc_key_edit.setText(fc_cfg.get("api_key", ""))


    # ── 数据收集 ─────────────────────────────────────────────

    def _collect_deepseek(self) -> dict:
        return {
            "api_key":    self._key_edit.text().strip(),
            "base_url":   self._url_edit.text().strip() or "https://api.deepseek.com",
            "model":      self._model_edit.text().strip() or "deepseek-v4-flash",
            "max_tokens": self._tokens_spin.value(),
            "api_format": self._api_format_combo.currentText(),
            "use_local": self._use_local_check.isChecked(),
            "local_base_url": self._local_url_edit.text().strip() or "http://localhost:11434/v1",
            "local_model_name": self._local_model_edit.text().strip() or "my-deepseek",
            "router_model": self._router_model_edit.text().strip(),
        }

    def _collect_aliyun(self) -> dict:
        return {
            "access_key_id": self._ali_access_key_id.text().strip(),
            "access_key_secret": self._ali_access_key_secret.text().strip(),
            "app_key": self._ali_app_key.text().strip(),
        }

    def _collect_qq_bridge(self) -> dict:
        return {
            "enabled":    self._auto_enable.isChecked(),
            "ws_url":     self._ws_url.text().strip() or "ws://127.0.0.1:3001",
            "qq_account": self._qq_account.text().strip(),
            "owner_qq":   self._owner_qq.text().strip(),
            "owner_name": self._owner_name.text().strip() or "主人",
        }

    def _collect_siliconflow(self) -> dict:
        return {
            "api_key":      self._sf_key_edit.text().strip(),
            "base_url":     self._sf_url_edit.text().strip() or "https://api.siliconflow.cn/v1",
            "vision_model": self._sf_model_edit.text().strip() or "deepseek-ai/deepseek-vl2",
        }

    def _collect_qweather(self) -> dict:
        return {
            "api_key":     self._qw_key_edit.text().strip(),
            "api_host":    self._qw_host_edit.text().strip(),
            "dev_id":      self._qw_dev_id_edit.text().strip(),
            "auto_remind": self._qw_auto_remind.isChecked(),
            "remind_time": self._qw_remind_time.currentText(),
        }

    # ── 保存 ─────────────────────────────────────────────────

    def _on_save(self):
        # DeepSeek
        ds_cfg = self._collect_deepseek()
        if not ds_cfg["use_local"] and not ds_cfg["api_key"]:
            QMessageBox.warning(self, "提示", "DeepSeek API Key 不能为空！")
            return
        save_api_config(ds_cfg)

        # 阿里云语音识别
        ali_cfg = self._collect_aliyun()
        if not ali_cfg["access_key_id"] or not ali_cfg["access_key_secret"] or not ali_cfg["app_key"]:
            reply = QMessageBox.question(
                self, "提示",
                "阿里云语音识别配置不完整，将无法使用待机模式语音输入。\n仍然保存吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        save_aliyun_stt_config(ali_cfg["access_key_id"], ali_cfg["access_key_secret"], ali_cfg["app_key"])

        # QQ 桥接
        qq_cfg = self._collect_qq_bridge()
        save_qq_bridge_config(qq_cfg)

        # SiliconFlow 视觉 API
        sf_cfg = self._collect_siliconflow()
        save_siliconflow_config(sf_cfg)

        # 和风天气
        qw_cfg = self._collect_qweather()
        save_qweather_config(qw_cfg)

        self.config_saved.emit()
        self.accept()
        
        # Tavily Search
        tv_cfg = {
            "api_key": self._tv_key_edit.text().strip(),
        }
        save_tavily_config(tv_cfg)

        # Firecrawl 网页爬虫
        fc_cfg = {
            "api_key": self._fc_key_edit.text().strip(),
        }
        save_firecrawl_config(fc_cfg)



    # ── 测试 DeepSeek 连接 ────────────────────────────────────

    def _on_test(self):
        cfg = self._collect_deepseek()
        is_local = cfg.get("use_local", False)
        if not is_local and not cfg["api_key"]:
            QMessageBox.warning(self, "提示", "请先填写 DeepSeek API Key！")
            return
        if self._test_worker and self._test_worker.isRunning():
            return

        self._test_btn.setEnabled(False)
        self._test_btn.setText("连接中…")

        if is_local:
            api_key = "ollama"
            base_url = cfg.get("local_base_url", "http://localhost:11434/v1")
            model = cfg.get("local_model_name", "my-deepseek")
        else:
            api_key = cfg["api_key"]
            base_url = cfg["base_url"]
            model = cfg["model"]

        self._test_worker = _TestWorker(
            api_key, base_url, model, is_local=is_local, parent=self
        )
        self._test_worker.success.connect(self._on_test_success)
        self._test_worker.failed.connect(self._on_test_failed)
        self._test_worker.start()

    def _on_test_success(self, reply: str):
        self._test_btn.setEnabled(True)
        is_local = self._use_local_check.isChecked()
        label = "测试本地模型连接" if is_local else "测试 DeepSeek 连接"
        self._test_btn.setText(label)
        api_name = "本地 Ollama" if is_local else "DeepSeek API"
        QMessageBox.information(
            self, "连接成功",
            f"{api_name} 连接正常！\n模型回复了：{reply}…"
        )

    # ── 余额查询 ──────────────────────────────────────────

    def _on_balance_query(self):
        api_key = self._key_edit.text().strip()
        if not api_key:
            QMessageBox.warning(self, "提示", "请先在 DeepSeek API 选项卡中填写 API Key！")
            return
        self._balance_worker = _BalanceWorker(api_key, self)
        self._balance_worker.success.connect(self._on_balance_success)
        self._balance_worker.failed.connect(self._on_balance_failed)
        self._balance_worker.start()

    def _on_balance_success(self, info: dict):
        total = info["total_balance"]
        currency = info["currency"]
        if total < 1.0:
            message = f"⚠️ 余额预警：当前余额为 {total:.2f} {currency}，已不足 1 元，请尽快充值以免影响使用！"
        else:
            message = f"✅ 当前账户余额为：{total:.2f} {currency}"
        mb = QMessageBox(self)
        mb.setWindowTitle("💰 余额查询")
        mb.setText(message)
        if total < 1.0:
            import webbrowser
            recharge_btn = mb.addButton("去充值", QMessageBox.AcceptRole)
            mb.addButton(QMessageBox.Cancel)
            mb.exec_()
            if mb.clickedButton() == recharge_btn:
                webbrowser.open("https://platform.deepseek.com/usage")
        else:
            mb.exec_()

    def _on_balance_failed(self, err: str):
        QMessageBox.warning(self, "余额查询失败", f"无法获取余额信息：\n{err}")

    def _on_test_failed(self, err: str):
        self._test_btn.setEnabled(True)
        is_local = self._use_local_check.isChecked()
        label = "测试本地模型连接" if is_local else "测试 DeepSeek 连接"
        self._test_btn.setText(label)
        api_name = "本地 Ollama" if is_local else "DeepSeek API"
        hint = (
            "请确认 Ollama 已启动（命令行运行 ollama serve），\n"
            f"且模型已通过 ollama create 导入。"
        ) if is_local else "请检查 Key 和 URL 是否正确。"
        QMessageBox.warning(
            self, "连接失败",
            f"无法连接到 {api_name}。{hint}\n\n错误信息：{err}"
        )