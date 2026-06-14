"""
InputPanel：底部输入区域
包含文字输入框、发送按钮、语音按钮、清空小纸条按钮、自动发送复选框
支持拖拽/粘贴图片（发送图片给莲心进行OCR识别）
"""

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QTextEdit, QCheckBox,
    QSizePolicy, QApplication, QDialog, QListWidget, QListWidgetItem,
    QLineEdit, QMenu, QAction, QTreeWidget, QTreeWidgetItem, QStackedWidget,
    QLabel
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QPoint
from PyQt5.QtGui import QFont, QKeyEvent, QDragEnterEvent, QDropEvent, QColor, QPixmap
import tempfile
import os
import json
from pathlib import Path
from brain.tools import TOOL_DEFINITIONS
from brain.skill_manager import get_active_tool_definitions
from utils.paths import get_user_data_dir




try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# 常用工具配置文件路径
FAVORITES_FILE = get_user_data_dir() / "favorite_tools.json"


def load_favorites():
    """加载收藏的工具列表"""
    try:
        if FAVORITES_FILE.exists():
            with open(FAVORITES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("favorites", []))
    except Exception:
        pass
    return set()


def save_favorites(favorites):
    """保存收藏的工具列表"""
    try:
        FAVORITES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(FAVORITES_FILE, "w", encoding="utf-8") as f:
            json.dump({"favorites": list(favorites)}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class _InputBox(QTextEdit):
    """支持 Enter 发送、Shift+Enter 换行的输入框。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)

    enter_pressed = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.enter_pressed.emit()
        else:
            super().keyPressEvent(event)


# ==================== 工具分组映射 ====================
TOOL_GROUP_MAP = {
    # 文件操作类
    "read_file": "📁 文件操作",
    "read_file_chunk": "📁 文件操作",
    "list_directory": "📁 文件操作",
    "search_files": "📁 文件操作",
    "read_excel": "📁 文件操作",
    "write_file": "📁 文件操作",
    "write_docx": "📁 文件操作",
    "format_document": "📁 文件操作",
    "write_excel": "📁 文件操作",
    "copy_excel_content": "📁 文件操作",
    "glob_files": "📁 文件操作",
    "grep_file": "📁 文件操作",
    "read_file_lines": "📁 文件操作",
    "edit_file": "📁 文件操作",
    "search_code": "🔍 代码搜索",
    "diff_files": "📁 文件操作",
    "run_shell": "💻 系统命令",
    "git_status": "🔧 开发工具",
    "code_structure": "🔍 代码搜索",
    "plan_tasks": "🧩 任务分解",
    "delegate_task": "🧩 任务分解",
    "track_tasks": "📋 任务追踪",
    "notebook_write": "📝 草稿本",
    "notebook_read": "📝 草稿本",
    "notebook_delete": "📝 草稿本",
    "code_goto_def": "🔍 代码搜索",
    "code_find_refs": "🔍 代码搜索",
    "code_diagnostics": "🔍 代码搜索",

    "describe_image": "🔍 视觉理解",
    # 系统命令类
    "open_app": "💻 系统命令",
    "run_command": "💻 系统命令",
    "get_clipboard": "💻 系统命令",
    "run_python_code": "💻 系统命令",
    # 联网搜索类
    "web_search": "🌐 联网搜索",
    "fetch_webpage": "🌐 联网搜索",
    "fetch_webpage_browser": "🌐 联网搜索",
    "fetch_webpage_via_api": "🌐 联网搜索",
    # 信息查询类
    "get_current_time": "📅 信息查询",
    "get_balance": "📅 信息查询",
    # 记忆与任务类
    "save_memory": "🧠 记忆与任务",
    "add_todo": "🧠 记忆与任务",
    "list_todos": "🧠 记忆与任务",
    "complete_todo": "🧠 记忆与任务",
    

}

# ==================== 工具别名映射（用于搜索） ====================
TOOL_ALIASES = {
    # 文件操作别名
    "read_file": ["读文件", "打开文件", "查看文件", "读取文件", "文件内容"],
    "list_directory": ["列目录", "查看文件夹", "目录内容", "列出文件"],
    "search_files": ["搜索文件", "查找文件", "找文件"],
    "write_file": ["写文件", "保存文件", "写入文件"],
    # 系统命令别名
    "open_app": ["打开程序", "启动应用", "运行软件", "打开软件"],
    "run_command": ["执行命令", "运行命令", "cmd命令"],
    "get_clipboard": ["剪贴板", "粘贴板", "复制内容"],
    # 联网搜索别名
    "web_search": ["搜索", "查一下", "百度", "谷歌", "联网查", "网上搜"],
    "fetch_webpage": ["获取网页", "抓取网页", "网页内容"],
    # 信息查询别名
    "get_current_time": ["现在时间", "几点了", "今天日期", "农历", "节假日"],
    "get_balance": ["余额", "查余额", "账户余额"],
    # 记忆与任务
    "save_memory": ["记住", "记一下", "保存记忆"],
    "add_todo": ["添加待办", "记任务", "提醒我", "设置提醒"],
    "list_todos": ["待办列表", "查看待办", "有什么任务"],
    "complete_todo": ["完成待办", "任务完成", "做完了"],
    # 编程工具别名
    "edit_file": ["修改文件", "替换", "编辑代码", "改代码"],
    "search_code": ["搜索代码", "查找代码", "代码搜索", "正则搜索"],
    "diff_files": ["对比文件", "文件差异", "diff"],
    "run_shell": ["执行shell", "命令行", "终端"],
    "git_status": ["git状态", "查看git", "版本控制"],
    "code_structure": ["代码结构", "函数列表", "类定义"],
    "plan_tasks": ["分解任务", "任务规划", "拆分任务"],
    "delegate_task": ["委派任务", "子代理", "并行执行"],
    "track_tasks": ["任务进度", "追踪任务", "更新任务", "任务清单"],
    "notebook_write": ["写入草稿", "保存草稿", "记录笔记"],
    "notebook_read": ["读取草稿", "查看草稿", "列出笔记"],
    "notebook_delete": ["删除草稿", "清除笔记", "移除记录"],
    "code_goto_def": ["跳转定义", "查看定义", "在哪定义", "函数定义"],
    "code_find_refs": ["查找引用", "谁调用了", "哪用了", "引用位置"],
    "code_diagnostics": ["检查代码", "代码诊断", "语法检查", "错误检查"],



}


DEFAULT_GROUP = "🔧 其他（音乐盒+日记本+备忘本+OCR相机）"


def get_tool_group(tool_name: str) -> str:
    return TOOL_GROUP_MAP.get(tool_name, DEFAULT_GROUP)


class ToolSelectionDialog(QDialog):
    """工具选择弹窗（支持分组显示、滚动、搜索、收藏）"""
    tool_selected = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_tool = None
        self.favorites = load_favorites()
        self.expanded_groups = set()  # 记录展开的分组名称
        self.setWindowTitle("选择工具")
        self.setModal(True)
        self.setMinimumWidth(450)
        self.setMinimumHeight(500)
        self.resize(480, 550)

        # 样式表（包含QMenu样式，解决右键菜单文字消失）
        self.setStyleSheet("""
            QDialog {
                border-radius: 8px;
            }
            QListWidget, QTreeWidget {
                border: 1px solid #3D3D5A;
                border-radius: 6px;
                padding: 4px;
                outline: none;
                font-size: 10pt;
                font-family: "Microsoft YaHei UI";
            }
            QListWidget::item, QTreeWidget::item {
                padding: 8px 12px;
                border-bottom: 1px solid #EEEEEE;
            }
            QListWidget::item:selected, QTreeWidget::item:selected {
                background-color: #6C7BFF;
                color: white;
            }
            QTreeWidget::item:hover, QListWidget::item:hover {
                background-color: #F0F2F5;
            }
            QTreeWidget::item:selected:hover, QListWidget::item:selected:hover {
                background-color: #6C7BFF;
                color: white;
            }
            QMenu {
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                border-radius: 4px;
                padding: 4px;
            }
            QMenu::item {
                background-color: transparent;
                color: #E0E0E0;
                padding: 6px 24px 6px 12px;
                margin: 2px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #6C7BFF;
                color: #FFFFFF;
            }
            QPushButton {
                background-color: #6C7BFF;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 10pt;
            }
            QPushButton:hover {
                background-color: #5A6AEE;
            }
            QPushButton#cancel_btn {
                background-color: #3D3D5A;
                color: #E0E0E0;
            }
            QPushButton#cancel_btn:hover {
                background-color: #4D4D6A;
            }
            QLineEdit {
                border: 1px solid #3D3D5A;
                border-radius: 6px;
                padding: 8px 10px;
                font-size: 10pt;
            }
            QLineEdit:focus {
                border: 1px solid #6C7BFF;
            }
            QCheckBox {
                font-size: 10pt;
                spacing: 6px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # 搜索框
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 搜索工具...")
        self.search_edit.textChanged.connect(self._refresh_ui)
        layout.addWidget(self.search_edit)

        # 选项区域
        opts_layout = QHBoxLayout()
        self.fav_only_cb = QCheckBox("⭐ 仅显示收藏（右键收藏工具）")
        self.fav_only_cb.stateChanged.connect(self._refresh_ui)
        self.group_cb = QCheckBox("📁 分组显示")
        self.group_cb.setChecked(True)
        self.group_cb.stateChanged.connect(self._refresh_ui)
        opts_layout.addWidget(self.fav_only_cb)
        opts_layout.addWidget(self.group_cb)
        opts_layout.addStretch()
        layout.addLayout(opts_layout)

        # 堆叠视图：0 = 分组树形视图，1 = 扁平列表视图
        self.stacked = QStackedWidget()
        self.tool_tree = QTreeWidget()
        self.tool_tree.setHeaderHidden(True)
        self.tool_tree.setIndentation(20)
        self.tool_tree.itemDoubleClicked.connect(self._on_tree_item_activated)
        self.tool_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tool_tree.customContextMenuRequested.connect(self._show_tree_context_menu)
        self.tool_tree.setIndentation(20)

        self.tool_list_flat = QListWidget()
        self.tool_list_flat.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.tool_list_flat.setUniformItemSizes(True)
        self.tool_list_flat.itemDoubleClicked.connect(self._on_flat_item_activated)
        self.tool_list_flat.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tool_list_flat.customContextMenuRequested.connect(self._show_flat_context_menu)

        self.stacked.addWidget(self.tool_tree)      # index 0
        self.stacked.addWidget(self.tool_list_flat) # index 1
        layout.addWidget(self.stacked)

        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        self.auto_btn = QPushButton("⚙️ 无工具（自动）")
        self.auto_btn.clicked.connect(lambda: self._select_tool(None))
        btn_layout.addWidget(self.auto_btn)
        btn_layout.addStretch()
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("cancel_btn")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

        # 加载工具数据
        self._load_tools()

        # 初始刷新
        self._refresh_ui()

    def _load_tools(self):
        """从 TOOL_DEFINITIONS 及已激活技能加载工具"""
        self.all_tools = []
        for tool_def in TOOL_DEFINITIONS:
            func_def = tool_def["function"]
            tool_name = func_def["name"]
            description = func_def.get("description", "")
            is_favorite = tool_name in self.favorites
            self.all_tools.append({
                "name": tool_name,
                "description": description,
                "is_favorite": is_favorite,
                "is_skill_tool": False,
            })
        # 加载已激活技能的工具
        for tool_def in get_active_tool_definitions():
            func_def = tool_def["function"]
            tool_name = func_def["name"]
            description = func_def.get("description", "")
            is_favorite = tool_name in self.favorites
            self.all_tools.append({
                "name": tool_name,
                "description": description,
                "is_favorite": is_favorite,
                "is_skill_tool": True,
            })
        # 排序：收藏的在前，然后按名称排序（用于扁平列表）
        self.all_tools.sort(key=lambda x: (not x["is_favorite"], x["name"]))

        # ---------- 分组树形视图 ----------
    def _build_group_tree(self):
        """构建分组树形视图（两列布局：工具名绿色加粗，描述灰色）"""
        self.tool_tree.clear()
        self.tool_tree.setHeaderLabels(["工具名称", "描述"])
        self.tool_tree.header().setVisible(False)
        self.tool_tree.setColumnWidth(0, 350)
        self.tool_tree.setIndentation(20)

        keyword = self.search_edit.text().strip().lower()
        show_fav_only = self.fav_only_cb.isChecked()

        def matches_keyword(tool_name, tool_desc, kw):
            if kw in tool_name.lower() or kw in tool_desc.lower():
                return True
            aliases = TOOL_ALIASES.get(tool_name, [])
            for alias in aliases:
                if kw in alias.lower():
                    return True
            return False

        groups = {}
        for tool in self.all_tools:
            if show_fav_only and not tool["is_favorite"]:
                continue
            if keyword and not matches_keyword(tool["name"], tool["description"], keyword):
                continue
            group_name = "📦 技能工具" if tool.get("is_skill_tool") else get_tool_group(tool["name"])
            groups.setdefault(group_name, []).append(tool)

        for group_name in sorted(groups.keys()):
            group_item = QTreeWidgetItem([group_name, ""])
            group_item.setFlags(group_item.flags() & ~Qt.ItemIsSelectable)
            font = group_item.font(0)
            font.setBold(True)
            group_item.setFont(0, font)
            group_item.setForeground(0, Qt.gray)
            self.tool_tree.addTopLevelItem(group_item)

            for tool in groups[group_name]:
                star = "⭐ " if tool["is_favorite"] else "   "
                tool_name_display = f"{star}{tool['name']}"
                desc = tool["description"][:80]
                if len(tool["description"]) > 80:
                    desc += "..."

                child = QTreeWidgetItem([tool_name_display, desc])
                child.setData(0, Qt.UserRole, tool["name"])
                child.setData(0, Qt.UserRole + 1, tool["is_favorite"])
                child.setToolTip(0, tool["description"])
                child.setToolTip(1, tool["description"])
                child.setForeground(0, QColor(46, 125, 50))
                font = child.font(0)
                font.setBold(True)
                child.setFont(0, font)
                child.setForeground(1, QColor(85, 85, 85))
                group_item.addChild(child)
            
            # 恢复展开状态
            is_expanded = group_name in self.expanded_groups
            group_item.setExpanded(is_expanded)

        # 保存当前展开状态
        self.expanded_groups.clear()
        for i in range(self.tool_tree.topLevelItemCount()):
            item = self.tool_tree.topLevelItem(i)
            if item.isExpanded():
                self.expanded_groups.add(item.text(0))

    # ---------- 扁平列表视图 ----------
    def _build_flat_list(self):
        """构建扁平列表（根据搜索和收藏过滤）"""
        self.tool_list_flat.clear()
        keyword = self.search_edit.text().strip().lower()
        show_fav_only = self.fav_only_cb.isChecked()

        def matches_keyword(tool_name, tool_desc, kw):
            if kw in tool_name.lower() or kw in tool_desc.lower():
                return True
            aliases = TOOL_ALIASES.get(tool_name, [])
            for alias in aliases:
                if kw in alias.lower():
                    return True
            return False

        self.tool_list_flat.setUpdatesEnabled(False)
        for tool in self.all_tools:
            if show_fav_only and not tool["is_favorite"]:
                continue
            if keyword and not matches_keyword(tool["name"], tool["description"], keyword):
                continue

            star = "⭐ " if tool["is_favorite"] else "   "
            display_text = f"{star}{tool['name']}\n   {tool['description'][:80]}"
            if len(tool['description']) > 80:
                display_text += "..."

            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, tool["name"])
            item.setData(Qt.UserRole + 1, tool["is_favorite"])
            item.setToolTip(tool["description"])
            self.tool_list_flat.addItem(item)
        self.tool_list_flat.setUpdatesEnabled(True)

    # ---------- 统一刷新入口 ----------
    def _refresh_ui(self):
        """根据当前选项刷新视图"""
        group_mode = self.group_cb.isChecked()
        if group_mode:
            self._build_group_tree()
            self.stacked.setCurrentIndex(0)
        else:
            self._build_flat_list()
            self.stacked.setCurrentIndex(1)

    # ---------- 右键菜单（树形视图） ----------
    def _show_tree_context_menu(self, position: QPoint):
        item = self.tool_tree.itemAt(position)
        if not item or item.parent() is None:  # 忽略分组项
            return
        tool_name = item.data(0, Qt.UserRole)
        if not tool_name:
            return
        is_fav = tool_name in self.favorites
        full_description = item.toolTip(0) or "无描述"

        menu = QMenu(self)
        # 收藏/取消收藏
        if is_fav:
            fav_action = QAction("❌ 取消收藏", menu)
            fav_action.triggered.connect(lambda: self._toggle_favorite(tool_name))
        else:
            fav_action = QAction("⭐ 收藏此工具", menu)
            fav_action.triggered.connect(lambda: self._toggle_favorite(tool_name))
        menu.addAction(fav_action)
        
        # 查看完整描述
        desc_action = QAction("📄 查看完整描述", menu)
        desc_action.triggered.connect(lambda: self._show_full_description(tool_name, full_description))
        menu.addAction(desc_action)
        
        menu.exec_(self.tool_tree.mapToGlobal(position))


    def _show_full_description(self, tool_name: str, description: str):
        """弹出对话框显示完整描述"""
        from PyQt5.QtWidgets import QMessageBox, QTextEdit, QDialogButtonBox, QVBoxLayout
        dialog = QDialog(self)
        dialog.setWindowTitle(f"工具描述 - {tool_name}")
        dialog.setMinimumWidth(500)
        dialog.setMinimumHeight(300)
        
        layout = QVBoxLayout(dialog)
        
        text_edit = QTextEdit()
        text_edit.setPlainText(description)
        text_edit.setReadOnly(True)
        text_edit.setStyleSheet("""
            QTextEdit {
                font-size: 12pt;
                font-family: "Microsoft YaHei UI";
                border: 1px solid #DDDDDD;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        layout.addWidget(text_edit)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(dialog.accept)
        layout.addWidget(button_box)
        
        dialog.exec_()

    # ---------- 右键菜单（扁平视图） ----------
    def _show_flat_context_menu(self, position: QPoint):
        item = self.tool_list_flat.itemAt(position)
        if not item:
            return
        tool_name = item.data(Qt.UserRole)
        if not tool_name:
            return
        is_fav = tool_name in self.favorites
        full_description = item.toolTip() or "无描述"

        menu = QMenu(self)
        if is_fav:
            fav_action = QAction("❌ 取消收藏", menu)
            fav_action.triggered.connect(lambda: self._toggle_favorite(tool_name))
        else:
            fav_action = QAction("⭐ 收藏此工具", menu)
            fav_action.triggered.connect(lambda: self._toggle_favorite(tool_name))
        menu.addAction(fav_action)
        
        desc_action = QAction("📄 查看完整描述", menu)
        desc_action.triggered.connect(lambda: self._show_full_description(tool_name, full_description))
        menu.addAction(desc_action)
        
        menu.exec_(self.tool_list_flat.mapToGlobal(position))
    # ---------- 双击选择 ----------
    def _on_tree_item_activated(self, item, column):
        if item.parent() is None:
            return
        tool_name = item.data(0, Qt.UserRole)  # 从第0列获取数据
        if tool_name:
            self._select_tool(tool_name)

    def _on_flat_item_activated(self, item):
        tool_name = item.data(Qt.UserRole)
        if tool_name:
            self._select_tool(tool_name)

    # ---------- 切换收藏 ----------
    def _toggle_favorite(self, tool_name: str):
        """切换收藏状态（供右键菜单调用）"""
        if tool_name in self.favorites:
            self.favorites.remove(tool_name)
        else:
            self.favorites.add(tool_name)
        save_favorites(self.favorites)

        # 更新 all_tools 中的收藏标记
        for tool in self.all_tools:
            if tool["name"] == tool_name:
                tool["is_favorite"] = tool_name in self.favorites
                break

        # 刷新界面
        self._refresh_ui()

    def _select_tool(self, tool_name):
        self.selected_tool = tool_name
        self.accept()


class InputPanel(QWidget):
    message_submitted = pyqtSignal(str, list)   # (text, image_paths)
    voice_clicked = pyqtSignal()
    clear_clicked = pyqtSignal()
    image_submitted = pyqtSignal(str)           # 旧接口保留，供外部使用

    def __init__(self, parent=None):
        super().__init__(parent)
        self._voice_connected = False
        self._clear_connected = False
        self._selected_tool = None
        self._pending_images: list[str] = []    # 暂存的图片路径
        self._image_preview_widgets: list[QWidget] = []
        self._build_ui()
        self.setAcceptDrops(True)
        self._input.installEventFilter(self)

    def _build_ui(self):
        self.setStyleSheet("""
            QWidget {
                background: transparent;
                border-top: 1px solid rgba(255, 255, 255, 30);
            }
        """)

        # 外层垂直布局：图片预览栏 + 主输入行
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # ── 图片预览栏 ──
        self._image_preview = QWidget()
        self._image_preview.setVisible(False)
        self._image_preview.setStyleSheet("background-color: #1E1E30; border-bottom: 1px solid #3D3D5A;")
        self._image_preview.setMaximumHeight(72)
        self._image_preview_layout = QHBoxLayout(self._image_preview)
        self._image_preview_layout.setContentsMargins(12, 6, 12, 6)
        self._image_preview_layout.setSpacing(8)
        self._image_preview_layout.setAlignment(Qt.AlignLeft)
        tip = QLabel("📷")
        tip.setFont(QFont("Segoe UI Emoji", 14))
        tip.setToolTip("待发送的图片，输入文字后按 Enter 发送")
        self._image_preview_layout.addWidget(tip)
        outer_layout.addWidget(self._image_preview)

        # ── 主布局：水平 ──
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(8)

        # 工具箱按钮
        self._tool_btn = QPushButton("🔧")
        self._tool_btn.setFixedSize(36, 36)
        self._tool_btn.setFont(QFont("Segoe UI Emoji", 14))
        self._tool_btn.setCursor(Qt.PointingHandCursor)
        self._tool_btn.setToolTip("选择工具（强制使用）")
        self._tool_btn.setStyleSheet("""
            QPushButton {
                background-color: #F0F2F5;
                border-radius: 8px;
                border: 1px solid #CCCCCC;
            }
            QPushButton:hover {
                background-color: #E0E4F0;
            }
            QPushButton:pressed {
                background-color: #D0D4E8;
            }
        """)
        self._tool_btn.clicked.connect(self._show_tool_dialog)
        main_layout.addWidget(self._tool_btn)

        # 输入框
        self._input = _InputBox()
        self._input.setFont(QFont("Microsoft YaHei UI", 12))
        self._input.setPlaceholderText("输入消息，按 Enter 发送，Shift+Enter 换行... (可粘贴图片到此)")
        self._input.setMinimumHeight(80)
        self._input.setMaximumHeight(150)
        self._input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._input.setStyleSheet("""
            QTextEdit {
                border: 2px solid #FFB347;
                border-radius: 10px;
                padding: 8px 12px;
                background-color: #2D2A20;
                color: #E0E0E0;
                font-size: 12pt;
                font-family: "Microsoft YaHei UI";
            }
            QTextEdit:focus {
                border: 2px solid #6C7BFF;
                background-color: #252540;
            }
        """)
        self._input.enter_pressed.connect(self._on_send)
        main_layout.addWidget(self._input, 1)

        # 右侧按钮区域
        right_layout = QHBoxLayout()
        right_layout.setAlignment(Qt.AlignTop)
        right_layout.setSpacing(6)

        self._btn_send = QPushButton("发送")
        self._btn_send.setFixedSize(60, 36)
        self._btn_send.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        self._btn_send.setCursor(Qt.PointingHandCursor)
        self._btn_send.setStyleSheet("""
            QPushButton {
                background-color: #6C7BFF;
                color: white;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover  { background-color: #5A6AEE; }
            QPushButton:pressed{ background-color: #4A5ADE; }
            QPushButton:disabled{ background-color: #BBBBCC; }
        """)
        self._btn_send.clicked.connect(self._on_send)
        right_layout.addWidget(self._btn_send)

        self._btn_voice = QPushButton("🎤")
        self._btn_voice.setFixedSize(48, 36)
        self._btn_voice.setFont(QFont("Segoe UI Emoji", 14))
        self._btn_voice.setCursor(Qt.PointingHandCursor)
        self._btn_voice.setToolTip("语音输入")
        self._btn_voice.setEnabled(False)
        self._btn_voice.setStyleSheet("""
            QPushButton {
                background-color: #EEEEEE;
                color: #999999;
                border-radius: 8px;
                border: none;
            }
        """)
        right_layout.addWidget(self._btn_voice)

        self._btn_clear = QPushButton("清空")
        self._btn_clear.setFixedSize(48, 36)
        self._btn_clear.setFont(QFont("Microsoft YaHei UI", 9))
        self._btn_clear.setCursor(Qt.PointingHandCursor)
        self._btn_clear.setToolTip("清空小纸条")
        self._btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #F0F0F0;

                border-radius: 8px;
                border: 1px solid #DDDDDD;
            }
            QPushButton:hover {
                background-color: #FFE0E0;
                color: #CC3333;
                border: 1px solid #FFAAAA;
            }
            QPushButton:pressed {
                background-color: #FFCCCC;
                color: #CC0000;
            }
            QPushButton:disabled {
                background-color: #F5F5F5;
                color: #BBBBBB;
                border: 1px solid #EEEEEE;
            }
        """)
        right_layout.addWidget(self._btn_clear)
        # 🔇 静音按钮
        self._btn_mute = QPushButton("🔇")
        self._btn_mute.setFixedSize(36, 36)
        self._btn_mute.setFont(QFont("Segoe UI Emoji", 14))
        self._btn_mute.setCursor(Qt.PointingHandCursor)
        self._btn_mute.setToolTip("停止朗读")
        self._btn_mute.setVisible(False)
        self._btn_mute.setStyleSheet("""
            QPushButton {
                background-color: #FFF3CD;
                color: #856404;
                border-radius: 8px;
                border: 1px solid #FFC107;
            }
            QPushButton:hover {
                background-color: #FFE69C;
                border: 1px solid #FF9800;
            }
        """)
        right_layout.addWidget(self._btn_mute)

        # ✏️ 重新发送按钮
        self._btn_resend = QPushButton("✏️")
        self._btn_resend.setFixedSize(36, 36)
        self._btn_resend.setFont(QFont("Segoe UI Emoji", 14))
        self._btn_resend.setCursor(Qt.PointingHandCursor)
        self._btn_resend.setToolTip("打断思考，回填上一条消息")
        self._btn_resend.setVisible(False)
        self._btn_resend.setStyleSheet("""
            QPushButton {
                background-color: #E8F0FE;
                color: #1A73E8;
                border-radius: 8px;
                border: 1px solid #4285F4;
            }
            QPushButton:hover {
                background-color: #D2E3FC;
                border: 1px solid #1A73E8;
            }
        """)
        right_layout.addWidget(self._btn_resend)

        self._auto_send_cb = QCheckBox("自动发送")
        self._auto_send_cb.setFont(QFont("Microsoft YaHei UI", 9))
        self._auto_send_cb.setChecked(True)
        self._auto_send_cb.setCursor(Qt.PointingHandCursor)
        self._auto_send_cb.setStyleSheet("""
            QCheckBox {
                spacing: 6px;
                font-size: 9pt;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
            }
        """)
        right_layout.addWidget(self._auto_send_cb)

        main_layout.addLayout(right_layout)

        outer_layout.addLayout(main_layout)

        self._highlight_timer = QTimer(self)
        self._highlight_timer.setSingleShot(True)
        self._highlight_timer.timeout.connect(self._clear_highlight)

    # ── 工具选择相关方法 ─────────────────────────────────────

    def _show_tool_dialog(self):
        from utils.sound import play_sound
        play_sound("ToolBox1.mp3")
        dialog = ToolSelectionDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            self._selected_tool = dialog.selected_tool
            self._update_tool_button_style()

    def _update_tool_button_style(self):
        if self._selected_tool:
            self._tool_btn.setStyleSheet("""
                QPushButton {
                    background-color: #6C7BFF;
                    color: white;
                    border-radius: 8px;
                    border: none;
                }
                QPushButton:hover {
                    background-color: #5A6AEE;
                }
                QPushButton:pressed {
                    background-color: #4A5ADE;
                }
            """)
            self._tool_btn.setToolTip(f"已绑定工具：{self._selected_tool}")
        else:
            self._tool_btn.setStyleSheet("""
                QPushButton {
                    background-color: #F0F2F5;
                    border-radius: 8px;
                    border: 1px solid #CCCCCC;
                }
                QPushButton:hover {
                    background-color: #E0E4F0;
                }
                QPushButton:pressed {
                    background-color: #D0D4E8;
                }
            """)
            self._tool_btn.setToolTip("选择工具（强制让莲心使用某工具）")

    def get_selected_tool(self):
        return self._selected_tool

    def clear_selection(self):
        self._selected_tool = None
        self._update_tool_button_style()

    # ── 公开接口 ─────────────────────────────────────────────

    def set_enabled(self, enabled: bool):
        self._btn_send.setEnabled(enabled)
        self._auto_send_cb.setEnabled(enabled)
        if enabled:
            self._input.setFocus()
            self._input.setStyleSheet("""
                QTextEdit {
                    border: 1px solid #3D3D5A;
                    border-radius: 10px;
                    padding: 8px 12px;
                    background-color: #1E1E30;
                    color: #E0E0E0;
                    font-size: 12pt;
                    font-family: "Microsoft YaHei UI";
                }
                QTextEdit:focus {
                    border: 1px solid #6C7BFF;
                    background-color: #252540;
                }
            """)
        else:
            self._input.setStyleSheet("""
                QTextEdit {
                    border: 1px solid #3D3D5A;
                    border-radius: 10px;
                    padding: 8px 12px;
                    background-color: #1E1E30;
                    color: #707070;
                    font-size: 12pt;
                    font-family: "Microsoft YaHei UI";
                }
                QTextEdit:focus {
                    border: 1px solid #6C7BFF;
                    background-color: #252540;
                }
            """)

    def enable_voice_button(self):
        self._btn_voice.setEnabled(True)
        self._btn_voice.setToolTip("点击开始语音输入，检测到停顿后自动识别")
        if not self._voice_connected:
            self._btn_voice.clicked.connect(self.voice_clicked)
            self._voice_connected = True
        self._set_voice_idle()

    def disable_voice_button(self):
        self._btn_voice.setEnabled(False)
        self._btn_voice.setToolTip("待机模式运行中，麦克风被占用")
        self._btn_voice.setStyleSheet("""
            QPushButton {
                background-color: #EEEEEE;
                color: #BBBBBB;
                border-radius: 8px;
                border: none;
            }
        """)

    def set_voice_recording(self):
        self._btn_voice.setStyleSheet("""
            QPushButton {
                background-color: #FF3B30;
                color: white;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover { background-color: #E0302A; }
        """)
        self._btn_voice.setToolTip("录音中…（检测到停顿后自动停止）")

    def set_voice_idle(self):
        self._set_voice_idle()

    def _set_voice_idle(self):
        self._btn_voice.setStyleSheet("""
            QPushButton {
                background-color: #F0F2FF;
                color: #6C7BFF;
                border-radius: 8px;
                border: 1px solid #C8CCEE;
            }
            QPushButton:hover  { background-color: #E0E4FF; }
            QPushButton:pressed{ background-color: #D0D4FF; }
        """)

    def set_text(self, text: str):
        self._input.setText(text)
        self._input.setFocus()
        cursor = self._input.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._input.setTextCursor(cursor)
        self._highlight_input()

    def _highlight_input(self):
        self._input.setStyleSheet("""
            QTextEdit {
                border: 2px solid #FFB347;
                border-radius: 10px;
                padding: 8px 12px;
                background-color: #2D2A20;
                color: #E0E0E0;
                font-size: 12pt;
                font-family: "Microsoft YaHei UI";
            }
            QTextEdit:focus {
                border: 2px solid #6C7BFF;
                background-color: #FFFFFF;
            }
        """)
        self._highlight_timer.start(3000)

    def _clear_highlight(self):
        self._input.setStyleSheet("""
            QTextEdit {
                border: 1px solid #3D3D5A;
                border-radius: 10px;
                padding: 8px 12px;
                background-color: #1E1E30;
                color: #E0E0E0;
                font-size: 12pt;
                font-family: "Microsoft YaHei UI";
            }
            QTextEdit:focus {
                border: 1px solid #6C7BFF;
                background-color: #252540;
            }
        """)

    def is_auto_send_enabled(self) -> bool:
        return self._auto_send_cb.isChecked()

    @property
    def voice_button(self):
        return self._btn_voice

    def enable_clear_button(self):
        self._btn_clear.setEnabled(True)
        if not self._clear_connected:
            self._btn_clear.clicked.connect(self._on_clear)
            self._clear_connected = True

    def disable_clear_button(self):
        self._btn_clear.setEnabled(False)

    # ── 内部发送/清空 ──────────────────────────────────────

    def _on_send(self):
        from utils.sound import play_sound
        play_sound("Send message.mp3")

        text = self._input.toPlainText().strip()
        has_images = bool(self._pending_images)
        if not text and not has_images:
            return
        # 如果只有图片没有文字，给一个默认文本
        if not text and has_images:
            text = "看看这张图"
        images = list(self._pending_images)
        self._pending_images.clear()
        self._clear_image_preview()
        self._input.clear()
        self._highlight_timer.stop()
        self._clear_highlight()
        self.message_submitted.emit(text, images)

    def _on_clear(self):
        self.clear_clicked.emit()

    # ── 图片处理 ───────────────────────────────────────────

    def eventFilter(self, obj, event):
        if obj == self._input and event.type() == event.KeyPress:
            if event.key() == Qt.Key_V and event.modifiers() == Qt.ControlModifier:
                if self._paste_image_from_clipboard():
                    return True
        return super().eventFilter(obj, event)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(('.png','.jpg','.jpeg','.bmp','.tiff')):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(('.png','.jpg','.jpeg','.bmp','.tiff')):
                self._process_image(path)
                break
        event.acceptProposedAction()

    def _paste_image_from_clipboard(self) -> bool:
        clipboard = QApplication.clipboard()
        pixmap = clipboard.pixmap()
        if not pixmap.isNull():
            if not HAS_PIL:
                self._show_image_error("缺少 Pillow 库，无法处理剪贴板图片")
                return False
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                tmp_path = f.name
            pixmap.save(tmp_path, 'PNG')
            self._process_image(tmp_path)
            return True
        mime = clipboard.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                path = url.toLocalFile()
                if path.lower().endswith(('.png','.jpg','.jpeg','.bmp','.tiff')):
                    self._process_image(path)
                    return True
        return False

    def _process_image(self, img_path: str):
        self._pending_images.append(img_path)
        self._update_image_preview()

    def _remove_pending_image(self, index: int):
        if 0 <= index < len(self._pending_images):
            # 清理临时文件（粘贴产生的 tmp 文件）
            path = self._pending_images.pop(index)
            try:
                if "tmp" in Path(path).stem.lower() and Path(path).exists():
                    Path(path).unlink()
            except Exception:
                pass
            self._update_image_preview()

    def _update_image_preview(self):
        # 清除旧的预览缩略图
        while self._image_preview_layout.count() > 1:  # 保留 "📷" 提示
            item = self._image_preview_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()

        if not self._pending_images:
            self._image_preview.setVisible(False)
            return

        self._image_preview.setVisible(True)
        for i, img_path in enumerate(self._pending_images):
            thumb = QLabel()
            pixmap = QPixmap(img_path)
            if not pixmap.isNull():
                thumb.setPixmap(pixmap.scaled(50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            thumb.setFixedSize(54, 54)
            thumb.setAlignment(Qt.AlignCenter)
            thumb.setStyleSheet("border: 2px solid #CCCCCC; border-radius: 6px; background: white;")
            self._image_preview_layout.addWidget(thumb)

            btn_x = QPushButton("×")
            btn_x.setFixedSize(16, 16)
            btn_x.setFont(QFont("Arial", 10, QFont.Bold))
            btn_x.setStyleSheet("QPushButton { background: #CC3333; color: white; border-radius: 8px; border: none; } QPushButton:hover { background: #FF4444; }")
            btn_x.setCursor(Qt.PointingHandCursor)
            idx = i
            btn_x.clicked.connect(lambda checked, idx=idx: self._remove_pending_image(idx))
            self._image_preview_layout.addWidget(btn_x)

    def _clear_image_preview(self):
        self._pending_images.clear()
        while self._image_preview_layout.count() > 1:
            item = self._image_preview_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        self._image_preview.setVisible(False)

    def _show_image_error(self, msg: str):
        self._input.setPlainText(msg)
        QTimer.singleShot(2000, lambda: self._input.clear() if self._input.toPlainText() == msg else None)
    # ── 中途插话条 ───────────────────
    def show_interrupt_bar(self, agent_worker):
        """显示插话输入条，绑定到 AgentWorker 的 interrupt_queue。"""
        from PyQt5.QtWidgets import QLineEdit, QPushButton, QHBoxLayout, QFrame
        from PyQt5.QtCore import Qt

        if hasattr(self, '_interrupt_bar') and self._interrupt_bar is not None:
            self._interrupt_bar.show()
            self._interrupt_input.setText("")
            self._interrupt_input.setFocus()
            return

        bar = QFrame(self)
        bar.setObjectName("interruptBar")
        bar.setStyleSheet("""
            QFrame#interruptBar {
                background: rgba(60, 60, 80, 200);
                border: 1px solid #666;
                border-radius: 8px;
                margin: 4px 8px;
            }
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(4)

        lbl = QLineEdit()
        lbl.setPlaceholderText("插话问问进度…（Enter 发送）")
        lbl.setStyleSheet("""
            QLineEdit {
                background: transparent; border: none; color: #ddd;
                font-size: 13px; padding: 3px 6px;
            }
        """)
        lbl.setEnabled(True)

        btn = QPushButton("发送")
        btn.setStyleSheet("""
            QPushButton {
                background: #4a6fa5; color: white; border-radius: 4px;
                padding: 3px 10px; font-size: 12px; min-width: 40px;
            }
            QPushButton:hover { background: #5a8fc5; }
        """)

        def _do_send():
            txt = lbl.text().strip()
            if txt and agent_worker and agent_worker.isRunning():
                agent_worker.send_interrupt(txt)
            lbl.setText("")

        lbl.returnPressed.connect(_do_send)
        btn.clicked.connect(_do_send)

        layout.addWidget(lbl)
        layout.addWidget(btn)

        # 插入到当前布局底部
        parent_layout = self.parent().layout() if self.parent() else None
        if parent_layout:
            parent_layout.addWidget(bar)

        self._interrupt_bar = bar
        self._interrupt_input = lbl
        bar.show()
        lbl.setFocus()

    def hide_interrupt_bar(self):
        """隐藏插话输入条。"""
        if hasattr(self, '_interrupt_bar') and self._interrupt_bar is not None:
            self._interrupt_bar.hide()
    def get_mute_button(self):
        return self._btn_mute

    def get_resend_button(self):
        return self._btn_resend

    def set_mute_visible(self, visible: bool):
        self._btn_mute.setVisible(visible)

    def set_resend_visible(self, visible: bool):
        self._btn_resend.setVisible(visible)