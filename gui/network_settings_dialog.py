"""
NetworkSettingsDialog：网络搜索设置对话框
独立配置 Tavily 搜索、Firecrawl 爬虫、重试回退策略。
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QMessageBox, QTabWidget,
    QWidget, QFormLayout, QCheckBox, QSpinBox, QButtonGroup, QRadioButton,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont

from config import (
    get_tavily_config, save_tavily_config,
    get_firecrawl_config, save_firecrawl_config,
    get_zhihu_config, save_zhihu_config,
    get_search_fallback_config, save_search_fallback_config,
    get_proxy_config, save_proxy_config,
    get_builtin_tool_config, save_builtin_tool_config,
)


class NetworkSettingsDialog(QDialog):
    """网络搜索设置独立对话框。"""

    config_saved = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🌐 联网搜索")
        self.setMinimumSize(520, 460)
        self.setStyleSheet("""
            QDialog {
                background-color: #FAFBFF;
            }
        """)
        self._build_ui()
        self._load_config()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 16, 20, 16)

        title = QLabel("🌐 网络搜索设置")
        title.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
        title.setStyleSheet("color: #3A3A5C;")
        layout.addWidget(title)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #E0E0E8; max-height: 1px;")
        layout.addWidget(line)

        desc = QLabel(
            "配置 Tavily AI 搜索、Firecrawl 网页爬虫的 API Key，\n"
            "以及 MCP 搜索失败后的重试和回退策略。"
        )
        desc.setWordWrap(True)
        desc.setFont(QFont("Microsoft YaHei UI", 9))
        desc.setStyleSheet("color: #666; background: #F5F5FF; padding: 8px; border-radius: 4px;")
        layout.addWidget(desc)

        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: 0; background: transparent; }
            QTabBar::tab {
                background: #F0F2F7; border: 1px solid #E0E0E8; border-bottom: 0;
                border-top-left-radius: 6px; border-top-right-radius: 6px;
                padding: 6px 14px; margin-right: 4px;
            }
            QTabBar::tab:selected { background: #FFFFFF; font-weight: bold; }
        """)
        layout.addWidget(tabs)

        # ── Tab 1: Tavily 搜索 ────────────────────────────
        tab_tavily = QWidget()
        self._build_tab_tavily(tab_tavily)
        tabs.addTab(tab_tavily, "🔍 Tavily 搜索")

        # ── Tab 2: Firecrawl 爬虫 ─────────────────────────
        tab_firecrawl = QWidget()
        self._build_tab_firecrawl(tab_firecrawl)
        tabs.addTab(tab_firecrawl, "🕷️ Firecrawl 爬虫")

        # ── Tab 3: 知乎全搜索 ─────────────────────────
        tab_zhihu = QWidget()
        self._build_tab_zhihu(tab_zhihu)
        tabs.addTab(tab_zhihu, "🎓 知乎搜索")

        # ── Tab 4: 重试与回退 ─────────────────────────────
        tab_fallback = QWidget()
        self._build_tab_fallback(tab_fallback)
        tabs.addTab(tab_fallback, "⚙️ 重试回退")

        # ── Tab 5: 代理设置 ─────────────────────────────
        tab_proxy = QWidget()
        self._build_tab_proxy(tab_proxy)
        tabs.addTab(tab_proxy, "🛡️ 代理设置")

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

    # ── Tavily ────────────────────────────────────────────
    def _build_tab_tavily(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        section_title = QLabel("🔍 Tavily AI 搜索配置")
        section_title.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        section_title.setStyleSheet("color: #3A3A5C;")
        layout.addWidget(section_title)

        desc = QLabel(
            "配置 Tavily API Key 后，莲心就能使用高质量的 AI 专属搜索引擎，\n"
            "支持实时网络搜索、网页内容提取、深度爬取。\n"
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

        key_row = QHBoxLayout()
        self._tv_key_edit = QLineEdit()
        self._tv_key_edit.setPlaceholderText("tvly-xxxxxxxxxxxxxxxxxxxxxxxx")
        self._tv_key_edit.setEchoMode(QLineEdit.Password)
        self._tv_key_edit.setFont(QFont("Consolas", 10))
        self._tv_key_edit.setStyleSheet("""
            QLineEdit {
                border: 1px solid #D0D0E0; border-radius: 6px;
                padding: 6px 10px; background: #FFFFFF;
            }
            QLineEdit:focus { border-color: #6C7BFF; }
        """)
        key_row.addWidget(self._tv_key_edit)

        self._show_tv_btn = QPushButton("显示")
        self._show_tv_btn.setFixedSize(60, 34)
        self._show_tv_btn.setFont(QFont("Microsoft YaHei UI", 9))
        self._show_tv_btn.setCursor(Qt.PointingHandCursor)
        self._show_tv_btn.setCheckable(True)
        self._show_tv_btn.clicked.connect(self._toggle_tv_key_visibility)
        key_row.addWidget(self._show_tv_btn)
        form.addRow("Tavily API Key：", key_row)

        layout.addLayout(form)
        layout.addSpacing(8)

        help_text = QLabel(
            "💡 提示：MCP Tavily 请求从你本地发出，绕过后端被墙限制，搜索质量优于 DuckDuckGo。"
        )
        help_text.setFont(QFont("Microsoft YaHei UI", 8))
        help_text.setStyleSheet("color: #999999; background-color: #F8F8FC; padding: 8px; border-radius: 6px;")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        layout.addStretch()

    def _toggle_tv_key_visibility(self, checked: bool):
        self._tv_key_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self._show_tv_btn.setText("隐藏" if checked else "显示")

    # ── Firecrawl ─────────────────────────────────────────
    def _build_tab_firecrawl(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        section_title = QLabel("🕷️ Firecrawl 网页爬虫配置")
        section_title.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        section_title.setStyleSheet("color: #3A3A5C;")
        layout.addWidget(section_title)

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

        key_row = QHBoxLayout()
        self._fc_key_edit = QLineEdit()
        self._fc_key_edit.setPlaceholderText("fc-xxxxxxxxxxxxxxxxxxxxxxxx")
        self._fc_key_edit.setEchoMode(QLineEdit.Password)
        self._fc_key_edit.setFont(QFont("Consolas", 10))
        self._fc_key_edit.setStyleSheet("""
            QLineEdit {
                border: 1px solid #D0D0E0; border-radius: 6px;
                padding: 6px 10px; background: #FFFFFF;
            }
            QLineEdit:focus { border-color: #6C7BFF; }
        """)
        key_row.addWidget(self._fc_key_edit)

        self._show_fc_btn = QPushButton("显示")
        self._show_fc_btn.setFixedSize(60, 34)
        self._show_fc_btn.setFont(QFont("Microsoft YaHei UI", 9))
        self._show_fc_btn.setCursor(Qt.PointingHandCursor)
        self._show_fc_btn.setCheckable(True)
        self._show_fc_btn.clicked.connect(self._toggle_fc_key_visibility)
        key_row.addWidget(self._show_fc_btn)
        form.addRow("Firecrawl API Key：", key_row)

        layout.addLayout(form)
        layout.addStretch()

    def _toggle_fc_key_visibility(self, checked: bool):
        self._fc_key_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self._show_fc_btn.setText("隐藏" if checked else "显示")

    # ── 知乎全搜索 ────────────────────────────────────────
    def _build_tab_zhihu(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        title = QLabel("🎓 知乎全网搜索配置")
        title.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        title.setStyleSheet("color: #3A3A5C;")
        layout.addWidget(title)

        desc = QLabel(
            "接入知乎开放平台 MCP 服务，支持全站搜索和实时热榜。\n"
            "配置后莲心可以直接搜索知乎最新内容、热门话题。\n"
            "注册地址：https://developer.zhihu.com/，在个人中心获取 Access Secret。"
        )
        desc.setFont(QFont("Microsoft YaHei UI", 9))
        desc.setStyleSheet("color: #888;")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        layout.addSpacing(8)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)

        key_row = QHBoxLayout()
        self._zhihu_key_edit = QLineEdit()
        self._zhihu_key_edit.setPlaceholderText("你的知乎开放平台 Access Secret")
        self._zhihu_key_edit.setEchoMode(QLineEdit.Password)
        self._zhihu_key_edit.setFont(QFont("Consolas", 10))
        self._zhihu_key_edit.setStyleSheet("""
            QLineEdit {
                border: 1px solid #D0D0E0; border-radius: 6px;
                padding: 6px 10px; background: #FFFFFF;
            }
            QLineEdit:focus { border-color: #6C7BFF; }
        """)
        key_row.addWidget(self._zhihu_key_edit)

        self._show_zh_btn = QPushButton("显示")
        self._show_zh_btn.setFixedSize(60, 34)
        self._show_zh_btn.setFont(QFont("Microsoft YaHei UI", 9))
        self._show_zh_btn.setCursor(Qt.PointingHandCursor)
        self._show_zh_btn.setCheckable(True)
        self._show_zh_btn.clicked.connect(self._toggle_zh_key_visibility)
        key_row.addWidget(self._show_zh_btn)
        form.addRow("知乎 Access Secret：", key_row)

        layout.addLayout(form)
        layout.addStretch()

    def _toggle_zh_key_visibility(self, checked: bool):
        self._zhihu_key_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self._show_zh_btn.setText("隐藏" if checked else "显示")

    # ── 重试与回退 ────────────────────────────────────────
    def _build_tab_fallback(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        desc = QLabel(
            "配置 MCP 搜索（Tavily/Firecrawl）失败后的重试和回退策略。\n"
            "- 重试：同一请求失败后自动重试几次，偶发网络问题可以自动恢复\n"
            "- 回退：重试全部失败后，是改用内建工具，还是基于已有信息直接回答\n"
            "- 额度检测：免费额度用完时自动切换，不用手动改配置"
        )
        desc.setWordWrap(True)
        desc.setFont(QFont("Microsoft YaHei UI", 9))
        desc.setStyleSheet("color: #666; background: #F5F5FF; padding: 8px; border-radius: 4px;")
        layout.addWidget(desc)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)

        self._search_max_retries_spin = QSpinBox()
        self._search_max_retries_spin.setRange(0, 5)
        self._search_max_retries_spin.setSuffix(" 次")
        form.addRow("MCP 最大重试次数：", self._search_max_retries_spin)

        strategy_widget = QWidget()
        strategy_vbox = QVBoxLayout(strategy_widget)
        strategy_vbox.setContentsMargins(0, 4, 0, 4)
        strategy_vbox.setSpacing(6)
        self._search_strategy_group = QButtonGroup(strategy_widget)
        self._search_strategy_builtin = QRadioButton("回退到内建搜索工具（web_search/fetch_webpage）")
        self._search_strategy_direct = QRadioButton("基于已有信息直接回答")
        self._search_strategy_group.addButton(self._search_strategy_builtin)
        self._search_strategy_group.addButton(self._search_strategy_direct)
        strategy_vbox.addWidget(self._search_strategy_builtin)
        strategy_vbox.addWidget(self._search_strategy_direct)
        form.addRow("重试失败后策略：", strategy_widget)

        self._search_auto_fallback_check = QCheckBox("启用")
        form.addRow("额度不足自动回退：", self._search_auto_fallback_check)

        layout.addLayout(form)

        # ── 内建工具开关 ────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #E0E0E8; max-height: 1px;")
        layout.addWidget(sep)

        builtin_label = QLabel("内建网页抓取工具（勾选=可用，取消=禁止LLM调用）")
        builtin_label.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        builtin_label.setStyleSheet("color: #3A3A5C;")
        layout.addWidget(builtin_label)

        self._bt_fetch_webpage = QCheckBox("fetch_webpage — 普通HTTP抓取，直连速度快")
        self._bt_fetch_webpage.setChecked(True)
        layout.addWidget(self._bt_fetch_webpage)

        self._bt_fetch_via_api = QCheckBox("fetch_webpage_via_api — API中转抓取，速度慢但穿透力强")
        layout.addWidget(self._bt_fetch_via_api)

        self._bt_fetch_browser = QCheckBox("fetch_webpage_browser — 浏览器模式Playwright，最慢")
        layout.addWidget(self._bt_fetch_browser)

        self._bt_fetch_stealth = QCheckBox("fetch_webpage_stealth — 反反爬模式，额外伪装头")
        layout.addWidget(self._bt_fetch_stealth)

        layout.addStretch()

    # ── 代理设置 ─────────────────────────────────────────
    def _build_tab_proxy(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        self._proxy_enabled_cb = QCheckBox("启用智能代理（先直连，不通自动切代理）")
        self._proxy_enabled_cb.setFont(QFont("Microsoft YaHei UI", 9))
        self._proxy_enabled_cb.setCursor(Qt.PointingHandCursor)
        self._proxy_enabled_cb.setToolTip(
            "开启后，莲心的所有网络请求会先尝试直连，只有直连不通时才会走代理。"
        )
        layout.addWidget(self._proxy_enabled_cb)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)

        http_row = QHBoxLayout()
        self._proxy_http_edit = QLineEdit()
        self._proxy_http_edit.setPlaceholderText("http://127.0.0.1:7890")
        self._proxy_http_edit.setToolTip("Clash 默认 http://127.0.0.1:7890")
        http_row.addWidget(self._proxy_http_edit, 1)
        form.addRow("HTTP 代理地址：", http_row)

        https_row = QHBoxLayout()
        self._proxy_https_edit = QLineEdit()
        self._proxy_https_edit.setPlaceholderText("http://127.0.0.1:7890")
        self._proxy_https_edit.setToolTip("通常与 HTTP 相同")
        https_row.addWidget(self._proxy_https_edit, 1)
        form.addRow("HTTPS 代理地址：", https_row)

        noproxy_row = QHBoxLayout()
        self._proxy_noproxy_edit = QLineEdit()
        self._proxy_noproxy_edit.setPlaceholderText("localhost,127.0.0.1")
        self._proxy_noproxy_edit.setToolTip("不走代理的地址，多个逗号分隔")
        noproxy_row.addWidget(self._proxy_noproxy_edit, 1)
        form.addRow("直连白名单：", noproxy_row)

        layout.addLayout(form)

        tip = QLabel(
            "💡 Clash 默认代理地址为 http://127.0.0.1:7890。\n"
            "如果代理工具使用不同端口，请在上方修改。\n"
            "\n"
            "🔍 智能代理策略：\n"
            "· 国内网站（百度等）→ 直连，速度不受影响\n"
            "· 国外网站（GitHub 等）→ 先直连，能通则通，不通自动切代理\n"
            "· 代理失败时不再尝试直连，避免反复超时"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #888; font-size: 12px; padding: 8px;")
        layout.addWidget(tip)
        layout.addStretch()

    # ── 加载与保存 ────────────────────────────────────────
    def _load_config(self):
        tv_cfg = get_tavily_config()
        self._tv_key_edit.setText(tv_cfg.get("api_key", ""))

        fc_cfg = get_firecrawl_config()
        self._fc_key_edit.setText(fc_cfg.get("api_key", ""))

        zh_cfg = get_zhihu_config()
        self._zhihu_key_edit.setText(zh_cfg.get("access_secret", ""))

        cfg = get_search_fallback_config()
        self._search_max_retries_spin.setValue(cfg.get("max_retries", 2))

        proxy_cfg = get_proxy_config()
        self._proxy_enabled_cb.setChecked(proxy_cfg.get("enabled", False))
        self._proxy_http_edit.setText(proxy_cfg.get("http_proxy", ""))
        self._proxy_https_edit.setText(proxy_cfg.get("https_proxy", ""))
        self._proxy_noproxy_edit.setText(proxy_cfg.get("no_proxy", ""))
        if cfg.get("fallback_strategy", "builtin") == "builtin":
            self._search_strategy_builtin.setChecked(True)
        else:
            self._search_strategy_direct.setChecked(True)
        self._search_auto_fallback_check.setChecked(cfg.get("auto_fallback_on_quota", True))

        # 内建工具开关
        builtin = get_builtin_tool_config()
        self._bt_fetch_webpage.setChecked(builtin.get("fetch_webpage", True))
        self._bt_fetch_via_api.setChecked(builtin.get("fetch_webpage_via_api", False))
        self._bt_fetch_browser.setChecked(builtin.get("fetch_webpage_browser", True))
        self._bt_fetch_stealth.setChecked(builtin.get("fetch_webpage_stealth", True))

    def _on_save(self):
        save_tavily_config({"api_key": self._tv_key_edit.text().strip()})
        save_firecrawl_config({"api_key": self._fc_key_edit.text().strip()})
        save_zhihu_config({"access_secret": self._zhihu_key_edit.text().strip()})
        save_search_fallback_config({
            "max_retries": self._search_max_retries_spin.value(),
            "fallback_strategy": "builtin" if self._search_strategy_builtin.isChecked() else "direct",
            "auto_fallback_on_quota": self._search_auto_fallback_check.isChecked(),
        })
        save_proxy_config({
            "enabled":     self._proxy_enabled_cb.isChecked(),
            "http_proxy":  self._proxy_http_edit.text().strip(),
            "https_proxy": self._proxy_https_edit.text().strip(),
            "no_proxy":    self._proxy_noproxy_edit.text().strip(),
        })

        save_builtin_tool_config({
            "fetch_webpage":           self._bt_fetch_webpage.isChecked(),
            "fetch_webpage_via_api":   self._bt_fetch_via_api.isChecked(),
            "fetch_webpage_browser":   self._bt_fetch_browser.isChecked(),
            "fetch_webpage_stealth":   self._bt_fetch_stealth.isChecked(),
        })

        self.config_saved.emit()
        self.accept()