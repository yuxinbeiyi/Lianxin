"""
ChatWidget：聊天记录滚动区域
动态插入气泡，自动滚动到底部。
"""

from datetime import datetime
import time

from PyQt5.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout, QLabel, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from gui.message_bubble import MessageBubble, ImageMessageBubble

_TIMESTAMP_GAP_SECONDS = 5 * 60   # 超过此间隔则在气泡前插入时间标签

# 工具名 → 第一人称友好描述（莲心口吻）
_TOOL_FRIENDLY = {
    "search_files": "让我翻翻你的文件...",
    "search_files_everything": "让我用 Everything 搜一下...",
    "get_file_info_everything": "让我看看文件信息...",
    "glob_files": "让我找找匹配的文件...",
    "read_file": "让我看看这个文件...",
    "read_file_chunk": "让我读一段文件...",
    "read_file_lines": "让我读几行文件...",
    "write_file": "让我帮你写下来...",
    "edit_file": "让我改改这个文件...",
    "list_directory": "让我看看这个文件夹...",
    "grep_file": "让我在文件里搜一下...",
    "diff_files": "让我比较一下文件...",
    "web_search": "让我上网搜一下...",
    "fetch_webpage": "让我打开这个网页...",
    "fetch_webpage_browser": "让我用浏览器打开...",
    "fetch_webpage_via_api": "让我抓取网页内容...",
    "fetch_webpage_stealth": "让我悄悄打开网页...",
    "run_python_code": "让我运行一段代码...",
    "run_command": "让我执行命令...",
    "run_shell": "让我开个 shell 跑一下...",
    "search_code": "让我搜搜代码...",
    "code_structure": "让我看看代码结构...",
    "code_goto_def": "让我跳转到定义...",
    "code_find_refs": "让我找找引用...",
    "code_diagnostics": "让我检查下代码问题...",
    "git_status": "让我看看 git 状态...",
    "get_current_time": "让我看看现在几点...",
    "get_balance": "让我查查余额...",
    "save_memory": "让我记住你说的话...",
    "update_memory": "让我更新一下记忆...",
    "delete_memory": "让我删掉这个记忆...",
    "search_memory": "让我回忆一下...",
    "search_graph_memory": "让我在知识图谱里找找...",
    "list_memories": "让我翻翻记忆本...",
    "query_connected_entities": "让我查查关联信息...",
    "delete_graph_entity": "让我清理一下图谱...",
    "add_graph_edge": "让我建立关联...",
    "remove_graph_edge": "让我断开关联...",
    "search_cross_session": "让我翻翻之前的聊天...",
    "ocr_image": "让我看看这张图...",
    "ocr_batch": "让我批量识别图片...",
    "describe_image": "让我描述一下这张图...",
    "capture_from_camera": "让我拍个照...",
    "capture_desktop": "让我看看你的屏幕...",
    "generate_image": "让我画张图...",
    "generate_video": "让我生成视频...",
    "read_excel": "让我看看这个表格...",
    "write_excel": "让我写个表格...",
    "copy_excel_content": "让我复制表格内容...",
    "write_docx": "让我写个文档...",
    "format_document": "让我排排版...",
    "open_app": "让我打开应用...",
    "get_clipboard": "让我看看剪贴板...",
    "send_file_to_qq": "让我帮你发文件...",
    "toggle_proactive_chat": "让我切换主动聊天...",
    "plan_tasks": "让我规划一下任务...",
    "delegate_task": "让我分配任务...",
    "track_tasks": "让我跟踪任务进度...",
    "add_todo": "让我记到待办里...",
    "list_todos": "让我看看待办列表...",
    "complete_todo": "让我标记完成...",
    "get_weather": "让我查查天气...",
    "set_user_city": "让我记住你的城市...",
    "list_skills": "让我看看有哪些技能...",
    "activate_skill": "让我启动技能...",
    "deactivate_skill": "让我关闭技能...",
    "notebook_write": "让我在草稿本上记一下...",
    "notebook_read": "让我看看草稿本...",
    "notebook_delete": "让我清理草稿本...",
    "bilibili_search": "让我搜搜 B 站...",
    "bilibili_add_tag": "让我加个 B 站标签...",
    "bilibili_list_tags": "让我看看 B 站标签...",
    "set_expression": "让我调整一下表情...",
}

# 等待超过此秒数时显示安抚提示
_BOREDOM_THRESHOLD_MS = 15_000
_BOREDOM_MESSAGES = [
    "别催哦，让我再想一想...",
    "嗯…这个有点复杂，稍等我一下~",
    "快了快了，马上就好！",
    "让我再仔细想想...",
    "别急别急，我在努力呢~",
    "这个问题需要多花点时间呢...",
]


class ChatWidget(QScrollArea):
    quote_requested = pyqtSignal(str, str)
    speak_requested = pyqtSignal(str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_message_time: datetime | None = None
        self._current_tool_group = None       # ToolCallGroup | None
        self._tool_groups: list = []          # list[ToolCallGroup]
        self._tool_round_count = 0            # highest round seen
        self._thinking_started_at: float = 0  # 思考开始时间戳（秒）
        self._boredom_timer: QTimer | None = None
        self._boredom_index: int = 0
        self._build_ui()

    def _build_ui(self):
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
# 原代码（第 28-49 行）：
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")

        self._layout = QVBoxLayout(self._container)
        self._layout.setAlignment(Qt.AlignTop)
        self._layout.setSpacing(6)
        self._layout.setContentsMargins(0, 12, 0, 12)

        self.setWidget(self._container)

        self._thinking_label = QLabel("  莲心思考中...")
        self._thinking_label.setFont(QFont("Microsoft YaHei UI", 10))
        self._thinking_label.setStyleSheet("padding: 4px 16px; background: transparent;")
        self._thinking_label.hide()
        self._layout.addWidget(self._thinking_label)

    # ── 公开接口 ─────────────────────────────────────────────

    def add_user_message(self, text: str):
        self._hide_thinking()
        self._maybe_insert_timestamp()
        bubble = MessageBubble(text, is_user=True)
        bubble.quote_requested.connect(self.quote_requested.emit)
        bubble.speak_requested.connect(self.speak_requested.emit)
        bubble.delete_requested.connect(lambda b=bubble: self._delete_message_bubble(b))
        self._layout.insertWidget(self._layout.count() - 1, bubble)
        self._container.updateGeometry()
        self._scroll_to_bottom()

        return bubble

    def add_ai_message(self, text: str):
        self._hide_thinking()
        self._maybe_insert_timestamp()
        bubble = MessageBubble(text, is_user=False)
        bubble.quote_requested.connect(self.quote_requested.emit)
        bubble.speak_requested.connect(self.speak_requested.emit)
        bubble.delete_requested.connect(lambda b=bubble: self._delete_message_bubble(b))
        self._layout.insertWidget(self._layout.count() - 1, bubble)
        self._container.updateGeometry()
        self._scroll_to_bottom()

        return bubble

    def add_image_message(self, image_path: str, desc: str = "", full_text: str = "", is_ai: bool = False):
        """添加图片消息气泡。
        Args:
            image_path: 图片文件路径
            desc: 图片描述/OCR 文本
            is_ai: True=莲心发的（左侧白色气泡），False=用户发的（右侧紫色气泡）
        """
        self._hide_thinking()
        self._maybe_insert_timestamp()
        sender = "ai" if is_ai else "user"
        bubble = ImageMessageBubble(image_path, ocr_text=desc, full_text=full_text, sender=sender)
        self._layout.insertWidget(self._layout.count() - 1, bubble)
        self._container.updateGeometry()
        self._scroll_to_bottom()

    def show_thinking(self, tool_name: str = ""):
        """显示思考状态。
        如果 tool_name 非空，显示第一人称友好描述。
        """
        if tool_name:
            description = _TOOL_FRIENDLY.get(tool_name, f"正在调用工具: {tool_name}...")
            hint = f"💭  {description}"
        else:
            hint = "💭  莲心思考中..."
        
        self._thinking_label.setText(hint)
        self._thinking_label.show()
        
        self._thinking_started_at = time.time()
        
        if self._boredom_timer is not None:
            self._boredom_timer.stop()
        self._boredom_index = 0
        self._boredom_timer = QTimer(self)
        self._boredom_timer.timeout.connect(self._check_boredom)
        self._boredom_timer.start(_BOREDOM_THRESHOLD_MS)
        
        self._scroll_to_bottom()

    def _check_boredom(self):
        """思考超过阈值，轮换显示安抚提示"""
        if not self._thinking_label.isVisible():
            if self._boredom_timer:
                self._boredom_timer.stop()
            return
        
        msg = _BOREDOM_MESSAGES[self._boredom_index % len(_BOREDOM_MESSAGES)]
        self._boredom_index += 1
        self._thinking_label.setText(f"💭  {msg}")
        self._scroll_to_bottom()

    # ── 工具调用卡片管理 ──────────────────────────────────

    def start_tool_round(self, round_num: int):
        """新 ReAct 轮开始：创建 ToolCallGroup 并插入聊天流"""
        from gui.tool_call_group import ToolCallGroup
        # finalize 前一组
        if self._current_tool_group is not None:
            self._current_tool_group.finalize(round_num - 1)
        group = ToolCallGroup(round_num)
        self._layout.insertWidget(self._layout.count() - 1, group)
        self._current_tool_group = group
        self._tool_groups.append(group)
        self._tool_round_count = max(self._tool_round_count, round_num)
        # 不再隐藏思考提示，而是保持可见
        if not self._thinking_label.isVisible():
            self._thinking_label.show()
        self._scroll_to_bottom()

    def add_tool_call_card(self, tool_name: str, args_json: str, round_num: int):
        """工具开始执行：在对应轮组中添加 running 卡片"""
        if self._current_tool_group is None or self._current_tool_group.round_num != round_num:
            self.start_tool_round(round_num)
        self._current_tool_group.add_card(tool_name, args_json)
        # 更新思考提示为当前工具的第一人称描述
        self._update_thinking_for_tool(tool_name)
        self._container.updateGeometry()
        self._scroll_to_bottom()

    def update_tool_call_result(self, tool_name: str, preview: str,
                                 is_error: bool, round_num: int, elapsed_ms: float):
        """工具执行完成：更新匹配卡片的状态"""
        target = None
        for g in reversed(self._tool_groups):
            if g.round_num == round_num:
                target = g
                break
        if target is None:
            self.start_tool_round(round_num)
            target = self._current_tool_group
        target.update_card(tool_name, preview, is_error, elapsed_ms)
        # 工具完成后显示"正在思考下一步..."
        if self._thinking_label.isVisible():
            self._thinking_label.setText("💭  让我想想接下来怎么做...")
        self._container.updateGeometry()

    def _update_thinking_for_tool(self, tool_name: str):
        """更新思考提示为当前工具的第一人称描述"""
        if not self._thinking_label.isVisible():
            self._thinking_label.show()
        description = _TOOL_FRIENDLY.get(tool_name, f"正在调用工具: {tool_name}...")
        self._thinking_label.setText(f"💭  {description}")

    def finalize_tool_groups(self):
        """AI 回复就绪：完结所有工具组，设置轮次标题"""
        total = self._tool_round_count
        for g in self._tool_groups:
            if not g.finalized:
                g.finalize(total)
        self._current_tool_group = None
        self._tool_groups.clear()
        self._tool_round_count = 0
        self._hide_thinking()

    def hide_thinking(self):
        self._hide_thinking()

    def clear_messages(self):
        """清空所有消息气泡和系统提示（保留内部 _thinking_label）。"""
        self._last_message_time = None
        self._current_tool_group = None
        self._tool_groups.clear()
        self._tool_round_count = 0
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def add_system_tip(self, text: str):
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setFont(QFont("Microsoft YaHei UI", 10))
        label.setStyleSheet("background: transparent; padding: 2px;")
        self._layout.insertWidget(self._layout.count() - 1, label)
        self._container.updateGeometry()
        self._scroll_to_bottom()  
        return label  # 返回引用，供调用方后续 hide()

    def add_user_image(self, image_path: str, ocr_text: str = "", full_text: str = ""):
        """插入用户图片消息气泡（右侧）。ocr_text 为摘要，full_text 为完整描述（支持展开）。"""
        self._hide_thinking()
        self._maybe_insert_timestamp()
        bubble = ImageMessageBubble(image_path, ocr_text, full_text)
        bubble.setObjectName("image_bubble")
        self._layout.insertWidget(self._layout.count() - 1, bubble)
        self._scroll_to_bottom()
        return bubble  # 返回引用，供调用方后续 update_text

    # ── 内部方法 ─────────────────────────────────────────────

    def _maybe_insert_timestamp(self):
        now = datetime.now()
        if (self._last_message_time is None or
                (now - self._last_message_time).total_seconds() >= _TIMESTAMP_GAP_SECONDS):
            time_str = now.strftime("%Y年%m月%d日  %H:%M")
            label = QLabel(time_str)
            label.setAlignment(Qt.AlignCenter)
            label.setFont(QFont("Microsoft YaHei UI", 10))
            label.setStyleSheet(
                "background: transparent; padding: 8px 0px 2px 0px;"
            )
            self._layout.insertWidget(self._layout.count() - 1, label)
        self._last_message_time = now

    def _hide_thinking(self):
        self._thinking_label.hide()
        if self._boredom_timer is not None:
            self._boredom_timer.stop()
            self._boredom_timer = None

    def _scroll_to_bottom(self):
        def _do():
            self._container.updateGeometry()
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().maximum()
            )
        QTimer.singleShot(50, _do)
    
    def add_ai_image(self, image_path: str):
        """在聊天区域添加一张 AI 发送的图片气泡（左对齐）"""
        self._hide_thinking()
        self._maybe_insert_timestamp()
        bubble = ImageMessageBubble(image_path, sender="ai", parent=self)
        self._layout.insertWidget(self._layout.count() - 1, bubble)
        self._scroll_to_bottom()
    def _delete_message_bubble(self, bubble):
        """删除消息气泡，并从历史记录中移除。"""
        from PyQt5.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "确认删除",
            "确定要删除这条消息吗？\n（删除后无法恢复）",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # 从历史记录中删除
        msg_text = bubble._text.strip()
        if msg_text:
            try:
                from brain.agent import conversation_manager
                conversation_manager.remove_message_by_content(msg_text)
            except Exception as e:
                print(f"[对话] 删除历史记录失败: {e}")

        # 从布局中移除
        self._layout.removeWidget(bubble)
        bubble.deleteLater()