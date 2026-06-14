"""
ChatWidget：聊天记录滚动区域
动态插入气泡，自动滚动到底部。
"""

from datetime import datetime

from PyQt5.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout, QLabel, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from gui.message_bubble import MessageBubble, ImageMessageBubble

_TIMESTAMP_GAP_SECONDS = 5 * 60   # 超过此间隔则在气泡前插入时间标签


class ChatWidget(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_message_time: datetime | None = None
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
        self._layout.insertWidget(self._layout.count() - 1, bubble)
        self._scroll_to_bottom()

    def add_ai_message(self, text: str):
        self._hide_thinking()
        self._maybe_insert_timestamp()
        bubble = MessageBubble(text, is_user=False)
        self._layout.insertWidget(self._layout.count() - 1, bubble)
        self._scroll_to_bottom()

    def show_thinking(self, tool_name: str = ""):
        hint = f"  莲心调用工具: {tool_name}..." if tool_name else "  莲心思考中..."
        self._thinking_label.setText(hint)
        self._thinking_label.show()
        self._scroll_to_bottom()

    def hide_thinking(self):
        self._hide_thinking()

    def clear_messages(self):
        """清空所有消息气泡和系统提示（保留内部 _thinking_label）。"""
        self._last_message_time = None
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

    def _scroll_to_bottom(self):
        QTimer.singleShot(50, lambda: self.verticalScrollBar().setValue(
            self.verticalScrollBar().maximum()
        ))
    
    def add_ai_image(self, image_path: str):
        """在聊天区域添加一张 AI 发送的图片气泡（左对齐）"""
        self._hide_thinking()
        self._maybe_insert_timestamp()
        bubble = ImageMessageBubble(image_path, sender="ai", parent=self)
        self._layout.insertWidget(self._layout.count() - 1, bubble)
        self._scroll_to_bottom()