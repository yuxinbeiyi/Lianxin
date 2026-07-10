# gui/capability_center.py
"""能力中枢 — 浏览和管理莲心的 Skills 与 MCP 服务"""

from datetime import datetime
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QPushButton, QScrollArea, QFrame, QLineEdit, QTextEdit,
    QCheckBox, QGridLayout, QSizePolicy, QComboBox, QMessageBox,
    QFileDialog,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont


class CapabilityCenter(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🧩 能力中枢")
        self.setMinimumSize(700, 560)
        self.resize(750, 600)
        self.setStyleSheet("""
            QDialog {
                background-color: #FFFFFF;
            }
            QWidget {
                background-color: #FFFFFF;
                color: #2C2C2C;
            }
            QTabWidget::pane {
                background: #FFFFFF;
                border: none;
            }
            QTabBar::tab {
                background: #F0F0F5;
                border: 1px solid #D0D0D8;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 8px 18px;
                margin-right: 4px;
                color: #2C2C2C;
                font-size: 12px;
            }
            QTabBar::tab:selected {
                background: #FFFFFF;
                font-weight: bold;
                color: #2C2C2C;
            }
            QFrame {
                background: #FFFFFF;
                border: 1px solid #E0E0E8;
                border-radius: 10px;
            }
            QScrollArea {
                background: #FFFFFF;
                border: none;
            }
            QLabel {
                background: transparent;
                color: #2C2C2C;
            }
            QLineEdit {
                background: #FFFFFF;
                color: #2C2C2C;
                border: 1px solid #D0D0E0;
                border-radius: 8px;
                padding: 6px 12px;
            }
            QLineEdit:focus {
                border-color: #6C7BFF;
            }
        """)
        self._last_refresh = datetime.now()
        self._skill_seen = set()
        self._mcp_seen = set()
        self._build_ui()
        self._refresh_all()

    # ── UI 构建 ─────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 16)
        root.setSpacing(10)

        # 标题栏 + 刷新按钮
        header = QHBoxLayout()
        title = QLabel("🧩 能力中枢")
        title.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
        title.setStyleSheet("color: #2C2C2C;")
        header.addWidget(title)
        header.addStretch()

        self._refresh_label = QLabel()
        self._refresh_label.setFont(QFont("Microsoft YaHei UI", 8))
        self._refresh_label.setStyleSheet("color: #555;")
        header.addWidget(self._refresh_label)

        self._refresh_btn = QPushButton("🔄 刷新")
        self._refresh_btn.setFixedSize(72, 28)
        self._refresh_btn.setFont(QFont("Microsoft YaHei UI", 9))
        self._refresh_btn.setCursor(Qt.PointingHandCursor)
        self._refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #E8C85A; color: #2C2C2C;
                border-radius: 6px; border: 1px solid #D0B040;
            }
            QPushButton:hover { background-color: #DDB840; }
        """)
        self._refresh_btn.clicked.connect(self._on_refresh)
        header.addWidget(self._refresh_btn)
        root.addLayout(header)

        # 统计卡片
        self._stats_widget = QWidget()
        root.addWidget(self._stats_widget)

        # 搜索栏
        search_row = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("🔍 搜索技能或工具...")
        self._search_edit.setFont(QFont("Microsoft YaHei UI", 10))
        self._search_edit.setStyleSheet("""
            QLineEdit {
                border: 1px solid #D0D0E0; border-radius: 8px;
                padding: 6px 12px; background: #FFF8DC; color: #2C2C2C;
            }
            QLineEdit:focus { border-color: #6C7BFF; }
        """)
        self._search_edit.textChanged.connect(self._on_search)
        search_row.addWidget(self._search_edit)
        root.addLayout(search_row)

        # 选项卡
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("")

        self._skill_tab = QWidget()
        self._skill_scroll = self._make_scroll_area()
        self._skill_layout = QVBoxLayout(self._skill_scroll.widget())
        self._skill_layout.setContentsMargins(0, 0, 0, 0)
        self._skill_layout.setSpacing(8)
        self._skill_layout.addStretch()
        skill_wrapper = QVBoxLayout(self._skill_tab)
        skill_wrapper.setContentsMargins(0, 0, 0, 0)
        skill_wrapper.addWidget(self._skill_scroll)
        self._tabs.addTab(self._skill_tab, "📦 Skills")

        self._mcp_tab = QWidget()
        self._mcp_scroll = self._make_scroll_area()
        self._mcp_layout = QVBoxLayout(self._mcp_scroll.widget())
        self._mcp_layout.setContentsMargins(0, 0, 0, 0)
        self._mcp_layout.setSpacing(8)
        self._mcp_layout.addStretch()
        mcp_wrapper = QVBoxLayout(self._mcp_tab)
        mcp_wrapper.setContentsMargins(0, 0, 0, 0)
        mcp_wrapper.addWidget(self._mcp_scroll)
        self._tabs.addTab(self._mcp_tab, "⚡ MCP 服务")

        self._tool_tab = QWidget()
        self._tool_scroll = self._make_scroll_area()
        self._tool_layout = QVBoxLayout(self._tool_scroll.widget())
        self._tool_layout.setContentsMargins(0, 0, 0, 0)
        self._tool_layout.setSpacing(8)
        self._tool_layout.addStretch()
        tool_wrapper = QVBoxLayout(self._tool_tab)
        tool_wrapper.setContentsMargins(0, 0, 0, 0)
        tool_wrapper.addWidget(self._tool_scroll)
        self._tabs.addTab(self._tool_tab, "🛠️ 内置工具")

        self._install_tab = QWidget()
        self._build_install_tab()
        self._tabs.addTab(self._install_tab, "➕ 安装插件")

        self._log_tab = QWidget()
        self._build_log_tab()
        self._tabs.addTab(self._log_tab, "📋 日志")

        root.addWidget(self._tabs)

    def _make_scroll_area(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        scroll.setWidget(container)
        return scroll

    # ── 统计卡片 ────────────────────────────────────────

    def _build_stats(self, skill_count, active_count, mcp_count, mcp_connected, tool_count):
        # 清空旧布局
        old_layout = self._stats_widget.layout()
        if old_layout:
            while old_layout.count():
                item = old_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            del old_layout

        layout = QGridLayout(self._stats_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._stat_labels = {}
        self._stat_cards = {}

        cards = [
            ("skill", f"{active_count}/{skill_count}", "📦 Skills", "#6C7BFF",
             "已激活", "未激活"),
            ("mcp",   f"{mcp_connected}/{mcp_count}", "⚡ MCP", "#E67E22",
             "已连接", "未连接"),
            ("tool",  f"{tool_count}", "🔧 工具", "#8E44AD",
             "", ""),
        ]
        for i, (key, num, label, color, on_label, off_label) in enumerate(cards):
            card = QFrame()
            card.setStyleSheet("""
                QFrame {
                    background: #FFF8DC; border: 1px solid #E0D0A0;
                    border-radius: 10px;
                }
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 10, 14, 10)
            card_layout.setSpacing(2)
            num_lbl = QLabel(num)
            num_lbl.setFont(QFont("Segoe UI", 20, QFont.Bold))
            num_lbl.setStyleSheet(f"color: {color};")
            num_lbl.setAlignment(Qt.AlignCenter)
            card_layout.addWidget(num_lbl)
            lbl = QLabel(label)
            lbl.setFont(QFont("Microsoft YaHei UI", 9))
            lbl.setStyleSheet("color: #555;")
            lbl.setAlignment(Qt.AlignCenter)
            card_layout.addWidget(lbl)
            layout.addWidget(card, 0, i)

            self._stat_labels[key] = num_lbl
            self._stat_cards[key] = {"card": card, "on_label": on_label, "off_label": off_label}

    # ── 卡片组件 ────────────────────────────────────────

    def _make_card(self, icon, name, description, version, status_text, status_color,
                   tool_count, tools, extra_label="", extra_color="#888"):
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background: #FFF8DC; border: 1px solid #E0D0A0;
                border-radius: 10px;
            }
        """)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(6)

        # 第一行：图标 + 名称 + 状态
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        icon_lbl = QLabel(icon)
        icon_lbl.setFont(QFont("Segoe UI Emoji", 16))
        row1.addWidget(icon_lbl)

        name_lbl = QLabel(name)
        name_lbl.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        name_lbl.setStyleSheet("color: #2C2C2C;")
        row1.addWidget(name_lbl)

        if version:
            ver = QLabel(f"v{version}")
            ver.setFont(QFont("Microsoft YaHei UI", 8))
            ver.setStyleSheet("color: #888;")
            row1.addWidget(ver)

        row1.addStretch()

        status = QLabel(status_text)
        status.setFont(QFont("Microsoft YaHei UI", 9))
        status.setStyleSheet(f"color: {status_color}; font-weight: bold;")
        row1.addWidget(status)
        layout.addLayout(row1)

        # 描述
        desc = QLabel(description)
        desc.setFont(QFont("Microsoft YaHei UI", 9))
        desc.setStyleSheet("color: #555;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 状态标签
        if extra_label:
            extra = QLabel(extra_label)
            extra.setFont(QFont("Microsoft YaHei UI", 8))
            extra.setStyleSheet(f"color: {extra_color};")
            extra.setWordWrap(True)
            layout.addWidget(extra)

        # 工具行
        tool_row = QHBoxLayout()
        tool_row.setSpacing(8)
        tool_badge = QLabel(f"▸ {tool_count} 个工具")
        tool_badge.setFont(QFont("Microsoft YaHei UI", 9))
        tool_badge.setStyleSheet("color: #2C2C2C;")
        tool_badge.setCursor(Qt.PointingHandCursor)
        tool_row.addWidget(tool_badge)
        tool_row.addStretch()

        layout.addLayout(tool_row)

        # 展开的工具列表
        tool_list = QWidget()
        tool_list.setVisible(False)
        tool_list_layout = QVBoxLayout(tool_list)
        tool_list_layout.setContentsMargins(8, 4, 0, 4)
        tool_list_layout.setSpacing(4)
        for t in tools:
            tool_item = self._make_tool_item(t)
            tool_list_layout.addWidget(tool_item)
        layout.addWidget(tool_list)

        # 点击展开/折叠
        tool_badge.mousePressEvent = lambda e: tool_list.setVisible(not tool_list.isVisible())

        return card, tool_badge

    def _make_tool_item(self, tool_info):
        """单个工具条目：名称 + 描述 + 可展开参数"""
        name = tool_info.get("name", "?")
        desc = tool_info.get("description", "")
        params = tool_info.get("parameters", {})

        frame = QFrame()
        frame.setStyleSheet("background: #FFF8DC; border-radius: 6px; padding: 4px; border: 1px solid #E8D8A0;")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(8, 4, 8, 4)
        fl.setSpacing(2)

        name_lbl = QLabel(f"🔹 {name}")
        name_lbl.setFont(QFont("Consolas", 9, QFont.Bold))
        name_lbl.setStyleSheet("color: #2C2C2C;")
        fl.addWidget(name_lbl)

        if desc:
            d = QLabel(desc)
            d.setFont(QFont("Microsoft YaHei UI", 8))
            d.setStyleSheet("color: #888;")
            d.setWordWrap(True)
            fl.addWidget(d)

        if params:
            params_widget = QWidget()
            params_widget.setVisible(False)
            pl = QVBoxLayout(params_widget)
            pl.setContentsMargins(12, 2, 0, 2)
            pl.setSpacing(2)
            for pname, pinfo in params.items():
                ptype = pinfo.get("type", "string")
                pdesc = pinfo.get("description", "")
                pl.addWidget(QLabel(f"  {pname}: {ptype} — {pdesc}"))
            fl.addWidget(params_widget)

            name_lbl.setCursor(Qt.PointingHandCursor)
            name_lbl.mousePressEvent = lambda e, w=params_widget: w.setVisible(not w.isVisible())

        return frame

    # ── 刷新逻辑 ────────────────────────────────────────

    def _refresh_all(self):
        self._global_log_msg("🔄 开始刷新...", "info")
        self._load_skills()
        self._load_mcp()
        self._load_tools()
        self._update_refresh_time()
        self._rebuild_stats()
        self._on_search("")
        self._global_log_msg("✅ 刷新完成", "ok")

    def _on_refresh(self):
        self._refresh_btn.setText("⏳ 刷新中...")
        self._refresh_btn.setEnabled(False)
        QTimer.singleShot(100, self._do_refresh)

    def _do_refresh(self):
        try:
            from brain.skill_manager import discover_skills, activate_all_skills
            discover_skills()
            activate_all_skills()
        except Exception as e:
            print(f"[能力中心] Skills 刷新失败: {e}")

        try:
            from brain.mcp.mcp_registry import unload_all, scan_mcp_services
            unload_all()
            scan_mcp_services()
        except Exception as e:
            print(f"[能力中心] MCP 刷新失败: {e}")

        self._last_refresh = datetime.now()
        self._refresh_all()
        self._refresh_btn.setText("🔄 刷新")
        self._refresh_btn.setEnabled(True)

    def _update_refresh_time(self):
        ts = self._last_refresh.strftime("%H:%M:%S")
        self._refresh_label.setText(f"上次刷新：{ts}")

    # ── Skills 加载 ─────────────────────────────────────

    def _load_skills(self):
        # 清空旧卡片
        layout = self._skill_layout
        while layout.count() > 1:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        from brain.skill_manager import _skill_registry, _active_skills
        skills = list(_skill_registry.values())

        for skill in skills:
            name = skill["name"]
            active = name in _active_skills
            tools = skill.get("tool_definitions", [])
            tool_count = len(tools)
            icon = self._skill_icon(name)
            status_text = "✅ 已激活" if active else "⏸ 未激活"
            status_color = "#27AE60" if active else "#AAA"

            # 提取工具信息
            tool_infos = []
            for td in tools:
                fn = td.get("function", {})
                tool_infos.append({
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {}).get("properties", {}),
                })

            license_text = skill.get("license", "")
            extra = f"📜 {license_text}" if license_text else ""
            card, badge = self._make_card(
                icon, name, skill.get("description", ""),
                skill.get("version", ""), status_text, status_color,
                tool_count, tool_infos,
                extra_label=extra, extra_color="#888",
            )
            card.setProperty("skill_name", name)
            card.setProperty("card_type", "skill")

            # 操作按钮行
            action_row = QHBoxLayout()
            action_row.setSpacing(8)
            toggle_btn = QPushButton("\u23f8 \u505c\u7528" if active else "\u25b6 \u542f\u7528")
            toggle_btn.setFixedSize(72, 26)
            toggle_btn.setFont(QFont("Microsoft YaHei UI", 9))
            toggle_btn.setCursor(Qt.PointingHandCursor)
            if active:
                toggle_btn.setStyleSheet("QPushButton{background:#FFE0B2;color:#E65100;border-radius:6px;border:1px solid #FFB74D;}QPushButton:hover{background:#FFCC80;}")
            else:
                toggle_btn.setStyleSheet("QPushButton{background:#C8E6C9;color:#2E7D32;border-radius:6px;border:1px solid #A5D6A7;}QPushButton:hover{background:#A5D6A7;}")
            toggle_btn.clicked.connect(lambda checked, n=name: self._on_toggle_skill(n))
            action_row.addWidget(toggle_btn)

            uninstall_btn = QPushButton("\U0001f5d1\ufe0f \u5378\u8f7d")
            uninstall_btn.setFixedSize(60, 26)
            uninstall_btn.setFont(QFont("Microsoft YaHei UI", 9))
            uninstall_btn.setCursor(Qt.PointingHandCursor)
            uninstall_btn.setStyleSheet("QPushButton{background:#FFCDD2;color:#C62828;border-radius:6px;border:1px solid #EF9A9A;}QPushButton:hover{background:#EF9A9A;}")
            uninstall_btn.clicked.connect(lambda checked, n=name: self._on_uninstall_skill(n))
            action_row.addWidget(uninstall_btn)
            action_row.addStretch()
            card.layout().addLayout(action_row)

            layout.insertWidget(layout.count() - 1, card)

        if not skills:
            empty.setAlignment(Qt.AlignCenter)
            empty = QLabel("暂无技能。\n将 SKILL.md 放入 skills/ 目录即可自动发现。")
            empty.setStyleSheet("color: #888; padding: 40px;")
            layout.insertWidget(layout.count() - 1, empty)

    def _skill_icon(self, name):
        icons = {
            "日记与备忘": "📔", "浏览器自动化": "🌐", "肩部外设控制": "📷",
            "音乐播放控制": "🎵", "系统信息工具": "💻", "语音合成": "🔊",
            "学习助手": "📚",
        }
        return icons.get(name, "📦")

    # ── MCP 加载 ────────────────────────────────────────

    def _load_mcp(self):
        layout = self._mcp_layout
        while layout.count() > 1:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        from brain.mcp.mcp_registry import MCP_REGISTRY, MANIFEST_CACHE

        for sname, agent in MCP_REGISTRY.items():
            manifest = MANIFEST_CACHE.get(sname, {})
            display = manifest.get("displayName", sname)
            desc = manifest.get("description", agent.description if hasattr(agent, "description") else "")
            agent_type = manifest.get("agentType", "local")
            icon = getattr(agent, "icon", "⚡") if hasattr(agent, "icon") else "⚡"

            # 连接状态
            connected = getattr(agent, "_connected", True)
            if agent_type == "external":
                status_text = "🟢 已连接" if connected else "🔴 未连接"
                status_color = "#27AE60" if connected else "#E74C3C"
            else:
                status_text = "✅ 本地运行"
                status_color = "#27AE60"

            # 工具
            tools = getattr(agent, "_tools", [])
            tool_count = len(tools)
            tool_infos = []
            for t in tools:
                if hasattr(t, "name"):
                    tool_infos.append({
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    })
                elif isinstance(t, dict):
                    tool_infos.append({
                        "name": t.get("name", ""),
                        "description": t.get("description", ""),
                        "parameters": t.get("inputSchema", {}).get("properties", t.get("parameters", {})),
                    })

            extra = ""
            extra_color = "#888"
            if agent_type == "external":
                extra = f"类型：外部 MCP（{agent_type}）"
            elif agent_type == "local":
                extra = f"类型：本地 MCP"

            card, badge = self._make_card(
                icon, display, desc, manifest.get("version", ""),
                status_text, status_color, tool_count, tool_infos,
                extra, extra_color,
            )
            card.setProperty("mcp_name", sname)
            card.setProperty("card_type", "mcp")

            # 操作按钮
            action_row = QHBoxLayout()
            action_row.setSpacing(8)
            from brain.mcp.mcp_registry import is_mcp_enabled
            enabled = is_mcp_enabled(sname)
            toggle_btn = QPushButton("⏸ 停用" if enabled else "▶ 启用")
            toggle_btn.setFixedSize(72, 26)
            toggle_btn.setFont(QFont("Microsoft YaHei UI", 9))
            toggle_btn.setCursor(Qt.PointingHandCursor)
            if enabled:
                toggle_btn.setStyleSheet("QPushButton{background:#FFE0B2;color:#E65100;border-radius:6px;border:1px solid #FFB74D;}QPushButton:hover{background:#FFCC80;}")
            else:
                toggle_btn.setStyleSheet("QPushButton{background:#C8E6C9;color:#2E7D32;border-radius:6px;border:1px solid #A5D6A7;}QPushButton:hover{background:#A5D6A7;}")
            toggle_btn.clicked.connect(lambda checked, n=sname: self._on_toggle_mcp(n))
            action_row.addWidget(toggle_btn)

            test_btn = QPushButton("🔌 测试")
            test_btn.setFixedSize(56, 26)
            test_btn.setFont(QFont("Microsoft YaHei UI", 9))
            test_btn.setCursor(Qt.PointingHandCursor)
            test_btn.setStyleSheet("QPushButton{background:#E3F2FD;color:#1565C0;border-radius:6px;border:1px solid #90CAF9;}QPushButton:hover{background:#BBDEFB;}")
            test_btn.clicked.connect(lambda checked, n=sname: self._on_test_mcp(n))
            action_row.addWidget(test_btn)

            uninstall_btn = QPushButton("\U0001f5d1\ufe0f \u5378\u8f7d")
            uninstall_btn.setFixedSize(60, 26)
            uninstall_btn.setFont(QFont("Microsoft YaHei UI", 9))
            uninstall_btn.setCursor(Qt.PointingHandCursor)
            uninstall_btn.setStyleSheet("QPushButton{background:#FFCDD2;color:#C62828;border-radius:6px;border:1px solid #EF9A9A;}QPushButton:hover{background:#EF9A9A;}")
            uninstall_btn.clicked.connect(lambda checked, n=sname: self._on_uninstall_mcp(n))
            action_row.addWidget(uninstall_btn)
            action_row.addStretch()
            card.layout().addLayout(action_row)

            layout.insertWidget(layout.count() - 1, card)

        if not MCP_REGISTRY:
            empty = QLabel("暂无 MCP 服务。\n将 mcp-manifest.json 放入 mcp_servers/ 目录即可自动发现。")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("color: #AAA; padding: 40px;")
            layout.insertWidget(layout.count() - 1, empty)

    # ── 内置工具加载 ─────────────────────────────────────

    def _load_tools(self):
        layout = self._tool_layout
        while layout.count() > 1:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            from brain.tool_registry import get_tool_registry
            reg = get_tool_registry()
            by_cat = reg.get_by_category()
        except Exception:
            empty = QLabel("工具注册中心暂不可用。")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("color: #AAA; padding: 40px;")
            layout.insertWidget(layout.count() - 1, empty)
            return

        if not by_cat:
            empty = QLabel("暂无内置工具。发送消息让莲心调用工具后，统计将在此显示。")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("color: #AAA; padding: 40px;")
            layout.insertWidget(layout.count() - 1, empty)
            return

        for cat, tools in by_cat.items():
            # 分类标题
            cat_label = QLabel(cat)
            cat_label.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
            cat_label.setStyleSheet("color: #4A4A6A; padding: 8px 4px 2px 4px;")
            cat_label.setProperty("card_type", "tool_cat")
            cat_label.setProperty("tool_names", " ".join(t.name for t in tools))
            layout.insertWidget(layout.count() - 1, cat_label)

            for ts in tools:
                card = self._make_tool_card(ts)
                layout.insertWidget(layout.count() - 1, card)

    def _make_tool_card(self, ts):
        """为单个工具创建统计卡片。"""
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background: #FFF8DC; border: 1px solid #E8E0C0;
                border-radius: 8px;
            }
        """)
        card.setProperty("card_type", "builtin_tool")
        card.setProperty("tool_name", ts.name)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        # 名称
        name_lbl = QLabel(ts.name)
        name_lbl.setFont(QFont("Consolas", 10, QFont.Bold))
        name_lbl.setStyleSheet("color: #2C2C2C; background: transparent;")
        layout.addWidget(name_lbl)

        layout.addStretch()

        # 调用次数
        count_lbl = QLabel(f"📊 {ts.call_count}")
        count_lbl.setFont(QFont("Microsoft YaHei UI", 9))
        count_lbl.setStyleSheet("color: #6C7BFF; background: transparent;")
        layout.addWidget(count_lbl)

        # 成功率
        if ts.call_count > 0:
            rate = ts.success_rate * 100
            rate_color = "#27AE60" if rate >= 90 else "#E67E22" if rate >= 50 else "#E74C3C"
            rate_lbl = QLabel(f"✅ {rate:.0f}%")
            rate_lbl.setFont(QFont("Microsoft YaHei UI", 9))
            rate_lbl.setStyleSheet(f"color: {rate_color}; background: transparent;")
            layout.addWidget(rate_lbl)

            # 平均耗时
            avg = ts.avg_duration_ms
            if avg >= 1000:
                dur_text = f"⏱ {avg/1000:.1f}s"
            else:
                dur_text = f"⏱ {avg:.0f}ms"
            dur_lbl = QLabel(dur_text)
            dur_lbl.setFont(QFont("Microsoft YaHei UI", 9))
            dur_lbl.setStyleSheet("color: #888; background: transparent;")
            layout.addWidget(dur_lbl)

        return card

    def _rebuild_stats(self, mcp_connected=0):
        from brain.skill_manager import _skill_registry, _active_skills
        from brain.mcp.mcp_registry import MCP_REGISTRY, is_mcp_enabled

        skill_count = len(_skill_registry)
        active_count = len(_active_skills)
        mcp_count = len(MCP_REGISTRY)
        mcp_enabled_count = sum(1 for n in MCP_REGISTRY if is_mcp_enabled(n))

        tool_count = sum(len(getattr(a, "_tools", [])) for a in MCP_REGISTRY.values())
        for s in _skill_registry.values():
            tool_count += len(s.get("tool_definitions", []))

        if not hasattr(self, "_stat_labels") or not self._stat_labels:
            self._build_stats(skill_count, active_count, mcp_count, mcp_enabled_count, tool_count)
            return

        self._stat_labels["skill"].setText(f"{active_count}/{skill_count}")
        self._stat_labels["mcp"].setText(f"{mcp_enabled_count}/{mcp_count}")
        self._stat_labels["tool"].setText(f"{tool_count}")

        active_names = [n for n in _active_skills]
        inactive_names = [n for n in _skill_registry if n not in _active_skills]
        active_str = "、".join(active_names) if active_names else "(无)"
        inactive_str = "、".join(inactive_names) if inactive_names else "(无)"
        self._stat_cards["skill"]["card"].setToolTip(
            f"━━ 已激活 ({active_count}/{skill_count}) ━━\n{active_str}\n\n"
            f"━━ 未激活 ({skill_count - active_count}/{skill_count}) ━━\n{inactive_str}"
        )

        mcp_on = [n for n in MCP_REGISTRY if is_mcp_enabled(n)]
        mcp_off = [n for n in MCP_REGISTRY if not is_mcp_enabled(n)]
        mcp_on_str = "、".join(mcp_on) if mcp_on else "(无)"
        mcp_off_str = "、".join(mcp_off) if mcp_off else "(无)"
        self._stat_cards["mcp"]["card"].setToolTip(
            f"━━ 已连接 ({mcp_enabled_count}/{mcp_count}) ━━\n{mcp_on_str}\n\n"
            f"━━ 未连接 ({mcp_count - mcp_enabled_count}/{mcp_count}) ━━\n{mcp_off_str}"
        )

    # ── 搜索过滤 ────────────────────────────────────────

    # ── 安装插件选项卡 ────────────────────────────────

    def _build_install_tab(self):
        layout = QVBoxLayout(self._install_tab)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # 说明文字
        hint = QLabel("将社区 Skills 或 MCP 服务文件夹拖入下方，或点击浏览选择文件夹，系统将自动识别并安装。")
        hint.setFont(QFont("Microsoft YaHei UI", 9))
        hint.setStyleSheet("color: #555; padding: 4px 0;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # 路径选择行
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self._install_path = QLineEdit()
        self._install_path.setPlaceholderText("选择要安装的插件文件夹...")
        self._install_path.setFont(QFont("Microsoft YaHei UI", 10))
        self._install_path.setStyleSheet("""
            QLineEdit {
                border: 2px dashed #D0D0E0; border-radius: 8px;
                padding: 10px 14px; background: #FFF8DC; color: #2C2C2C;
            }
            QLineEdit:focus { border-color: #6C7BFF; }
        """)
        self._install_path.textChanged.connect(self._on_install_path_changed)
        path_row.addWidget(self._install_path)

        browse_btn = QPushButton("📂 浏览")
        browse_btn.setFixedSize(80, 40)
        browse_btn.setFont(QFont("Microsoft YaHei UI", 10))
        browse_btn.setCursor(Qt.PointingHandCursor)
        browse_btn.setStyleSheet("""
            QPushButton {
                background-color: #6C7BFF; color: #FFF;
                border-radius: 8px; border: none;
            }
            QPushButton:hover { background-color: #5A6AE0; }
        """)
        browse_btn.clicked.connect(self._on_browse_folder)
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        # 检测结果卡片
        self._detect_card = QFrame()
        self._detect_card.setStyleSheet("""
            QFrame {
                background: #F8F8FF; border: 1px solid #E0E0F0;
                border-radius: 10px;
            }
        """)
        self._detect_card.setVisible(False)
        detect_layout = QVBoxLayout(self._detect_card)
        detect_layout.setContentsMargins(16, 12, 16, 12)
        detect_layout.setSpacing(6)

        self._detect_type = QLabel()
        self._detect_type.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        detect_layout.addWidget(self._detect_type)

        self._detect_name = QLabel()
        self._detect_name.setFont(QFont("Microsoft YaHei UI", 10))
        detect_layout.addWidget(self._detect_name)

        self._detect_desc = QLabel()
        self._detect_desc.setFont(QFont("Microsoft YaHei UI", 9))
        self._detect_desc.setStyleSheet("color: #555;")
        self._detect_desc.setWordWrap(True)
        detect_layout.addWidget(self._detect_desc)

        self._install_btn = QPushButton("⬇️ 一键安装")
        self._install_btn.setFixedHeight(36)
        self._install_btn.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        self._install_btn.setCursor(Qt.PointingHandCursor)
        self._install_btn.setStyleSheet("""
            QPushButton {
                background-color: #27AE60; color: #FFF;
                border-radius: 8px; border: none;
            }
            QPushButton:hover { background-color: #219A52; }
            QPushButton:disabled { background-color: #CCC; }
        """)
        self._install_btn.clicked.connect(self._on_install)
        detect_layout.addWidget(self._install_btn)

        layout.addWidget(self._detect_card)

        # 状态日志
        self._install_log = QTextEdit()
        self._install_log.setReadOnly(True)
        self._install_log.setFont(QFont("Consolas", 9))
        self._install_log.setMaximumHeight(120)
        self._install_log.setStyleSheet("""
            QTextEdit {
                background: #FFF8DC; border: 1px solid #E0D0A0;
                border-radius: 8px; padding: 8px; color: #2C2C2C;
            }
        """)
        self._install_log.setPlaceholderText("安装日志将在此显示...")
        layout.addWidget(self._install_log)

        layout.addStretch()

        self._pending_source = None

    def _build_log_tab(self):
        layout = QVBoxLayout(self._log_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("📋 调试日志")
        title.setFont(QFont("Microsoft YaHei UI", 12, QFont.Bold))
        header.addWidget(title)
        header.addStretch()

        clear_btn = QPushButton("🗑️ 清空")
        clear_btn.setFixedSize(60, 24)
        clear_btn.setFont(QFont("Microsoft YaHei UI", 9))
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setStyleSheet("QPushButton{background:#EEE;color:#555;border-radius:4px;border:1px solid #CCC;}QPushButton:hover{background:#DDD;}")
        clear_btn.clicked.connect(lambda: self._global_log.clear())
        header.addWidget(clear_btn)
        layout.addLayout(header)

        self._global_log = QTextEdit()
        self._global_log.setReadOnly(True)
        self._global_log.setFont(QFont("Consolas", 9))
        self._global_log.setStyleSheet("""
            QTextEdit {
                background: #1E1E2E; color: #CDD6F4;
                border: 1px solid #313244; border-radius: 8px;
                padding: 8px;
            }
        """)
        self._global_log.setPlaceholderText("技能和 MCP 的加载日志将在此显示...")
        layout.addWidget(self._global_log)

    def _global_log_msg(self, msg, level="info"):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        colors = {"info": "#CDD6F4", "ok": "#A6E3A1", "warn": "#F9E2AF", "err": "#F38BA8"}
        color = colors.get(level, "#CDD6F4")
        if hasattr(self, "_global_log"):
            self._global_log.append(f'<span style="color:#89B4FA;">[{ts}]</span> <span style="color:{color};">{msg}</span>')

    def _on_browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择插件文件夹")
        if folder:
            self._install_path.setText(folder)

    def _on_install_path_changed(self, text):
        self._detect_card.setVisible(False)
        self._pending_source = None
        if not text.strip():
            return

        try:
            from brain.plugin_installer import get_plugin_info
            info = get_plugin_info(text.strip())
        except Exception as e:
            self._log(f"❌ 检测失败: {e}")
            return

        ptype = info.get("type", "unknown")
        if ptype == "unknown":
            self._detect_type.setText("❌ 无法识别")
            self._detect_type.setStyleSheet("color: #E74C3C;")
            self._detect_name.setText("未找到 SKILL.md 或 mcp-manifest.json")
            self._detect_desc.setText("")
            self._install_btn.setEnabled(False)
            self._detect_card.setVisible(True)
            return

        if ptype == "skill":
            self._detect_type.setText("📦 检测到技能")
            self._detect_type.setStyleSheet("color: #6C7BFF;")
        else:
            self._detect_type.setText("⚡ 检测到 MCP 服务")
            self._detect_type.setStyleSheet("color: #E67E22;")

        self._detect_name.setText(f"名称: {info.get('name', '?')}")
        desc = info.get("description", "")
        ver = info.get("version", "")
        self._detect_desc.setText(f"{desc}\n版本: {ver}" if ver else desc)
        self._install_btn.setEnabled(True)
        self._detect_card.setVisible(True)
        self._pending_source = info.get("_source_path", text.strip())

    def _on_install(self):
        if not self._pending_source:
            return

        self._install_btn.setEnabled(False)
        self._install_btn.setText("⏳ 安装中...")

        try:
            from brain.plugin_installer import install_plugin
            success, msg = install_plugin(self._pending_source)
        except Exception as e:
            success, msg = False, f"安装异常: {e}"

        self._log(msg)
        self._install_btn.setText("⬇️ 一键安装")
        self._install_btn.setEnabled(True) if not success else None

        if success:
            self._detect_card.setVisible(False)
            self._install_path.clear()
            self._pending_source = None
            self._global_log_msg("⚡ 热加载完成，无需重启莲心即可使用新插件", "ok")
            self._refresh_all()

    def _log(self, msg, level="info"):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self._install_log.append(f"[{ts}] {msg}")
        self._global_log_msg(msg, level)

    def _on_toggle_skill(self, name):
        from brain.skill_manager import _active_skills, activate_skill, deactivate_skill
        if name in _active_skills:
            deactivate_skill(name)
            self._log(f"⏸ 技能「{name}」已停用", "warn")
        else:
            activate_skill(name)
            self._log(f"▶ 技能「{name}」已启用", "ok")
        self._refresh_all()

    def _on_uninstall_skill(self, name):
        reply = QMessageBox.question(self, "确认卸载",
            f"确定要卸载技能「{name}」吗？\n\n这将永久删除技能目录，不可恢复。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        from brain.skill_manager import uninstall_skill
        success, msg = uninstall_skill(name)
        self._log(msg)
        self._refresh_all()

    def _on_uninstall_mcp(self, name):
        reply = QMessageBox.question(self, "确认卸载",
            f"确定要卸载 MCP 服务「{name}」吗？\n\n这将永久删除服务目录，不可恢复。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        from brain.plugin_installer import uninstall_plugin
        success, msg = uninstall_plugin(name, "mcp")
        self._log(msg)
        self._refresh_all()

    def _on_toggle_mcp(self, name):
        from brain.mcp.mcp_registry import toggle_mcp_enabled
        new_state = toggle_mcp_enabled(name)
        if new_state:
            self._log(f"▶ MCP「{name}」已启用", "ok")
        else:
            self._log(f"⏸ MCP「{name}」已停用，工具定义不再注入 API", "warn")
        self._refresh_all()

    def _on_test_mcp(self, name):
        from brain.mcp.mcp_registry import MCP_REGISTRY
        self._log(f"🔌 正在测试 MCP「{name}」...", "info")
        agent = MCP_REGISTRY.get(name)
        if not agent:
            self._log(f"❌ MCP「{name}」未在注册表中找到", "err")
            return
        try:
            if hasattr(agent, "list_tools"):
                tools = agent.list_tools()
                tool_count = len(tools) if isinstance(tools, list) else len(list(tools))
                self._log(f"✅ MCP「{name}」连接正常，提供 {tool_count} 个工具", "ok")
            elif hasattr(agent, "get_tool_definitions_openai"):
                tools = agent.get_tool_definitions_openai()
                self._log(f"✅ MCP「{name}」连接正常，提供 {len(tools)} 个工具定义", "ok")
            elif hasattr(agent, "_tools"):
                self._log(f"✅ MCP「{name}」已加载，{len(agent._tools)} 个工具就绪", "ok")
            else:
                self._log(f"⚠️ MCP「{name}」已加载但无法获取工具列表", "warn")
        except Exception as e:
            self._log(f"❌ MCP「{name}」测试失败: {e}", "err")

    def _on_search(self, text):
        kw = text.strip().lower()

        for i in range(self._skill_layout.count()):
            item = self._skill_layout.itemAt(i)
            if item and item.widget():
                w = item.widget()
                if w.property("card_type") == "skill":
                    name = w.property("skill_name") or ""
                    w.setVisible(kw in name.lower() if kw else True)

        for i in range(self._mcp_layout.count()):
            item = self._mcp_layout.itemAt(i)
            if item and item.widget():
                w = item.widget()
                if w.property("card_type") == "mcp":
                    name = w.property("mcp_name") or ""
                    w.setVisible(kw in name.lower() if kw else True)

        for i in range(self._tool_layout.count()):
            item = self._tool_layout.itemAt(i)
            if item and item.widget():
                w = item.widget()
                ct = w.property("card_type") or ""
                if ct == "tool_cat":
                    names = w.property("tool_names") or ""
                    visible = kw in names.lower() if kw else True
                    w.setVisible(visible)
                elif ct == "builtin_tool":
                    name = w.property("tool_name") or ""
                    w.setVisible(kw in name.lower() if kw else True)