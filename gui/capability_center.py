# gui/capability_center.py
"""能力中枢 — 浏览和管理莲心的 Skills 与 MCP 服务"""

from datetime import datetime
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QPushButton, QScrollArea, QFrame, QLineEdit,
    QCheckBox, QGridLayout, QSizePolicy, QComboBox, QMessageBox,
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
        layout = QGridLayout(self._stats_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        cards = [
            (f"{skill_count}", "📦 Skills", "#6C7BFF"),
            (f"{active_count}", "✅ 已激活", "#27AE60"),
            (f"{mcp_count}", "⚡ MCP", "#E67E22"),
            (f"{tool_count}", "🔧 工具", "#8E44AD"),
        ]
        for i, (num, label, color) in enumerate(cards):
            card = QFrame()
            card.setStyleSheet(f"""
                QFrame {{
                    background: #FFF8DC; border: 1px solid #E0D0A0;
                    border-radius: 10px;
                }}
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
        self._load_skills()
        self._load_mcp()
        self._update_refresh_time()
        self._on_search("")

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

            card, badge = self._make_card(
                icon, name, skill.get("description", ""),
                skill.get("version", ""), status_text, status_color,
                tool_count, tool_infos,
            )
            card.setProperty("skill_name", name)
            card.setProperty("card_type", "skill")
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
            layout.insertWidget(layout.count() - 1, card)

        if not MCP_REGISTRY:
            empty = QLabel("暂无 MCP 服务。\n将 mcp-manifest.json 放入 mcp_servers/ 目录即可自动发现。")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("color: #AAA; padding: 40px;")
            layout.insertWidget(layout.count() - 1, empty)

        # 更新统计
        active_count = sum(1 for a in MCP_REGISTRY.values()
                          if getattr(a, "_connected", True))
        self._rebuild_stats(active_count)

    def _rebuild_stats(self, mcp_connected=0):
        from brain.skill_manager import _skill_registry, _active_skills
        from brain.mcp.mcp_registry import MCP_REGISTRY

        skill_count = len(_skill_registry)
        active_count = len(_active_skills)
        mcp_count = len(MCP_REGISTRY)
        tool_count = sum(len(getattr(a, "_tools", [])) for a in MCP_REGISTRY.values())
        for s in _skill_registry.values():
            tool_count += len(s.get("tool_definitions", []))

        self._build_stats(skill_count, active_count, mcp_count, mcp_connected, tool_count)

    # ── 搜索过滤 ────────────────────────────────────────

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