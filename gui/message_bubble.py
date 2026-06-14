"""
MessageBubble：单条消息气泡组件
- 用户消息：右对齐，紫蓝色背景，白色文字
- AI 消息：左对齐，白色背景，深色文字
- 图片消息：右对齐，紫蓝色背景，显示图片缩略图 + OCR 文字摘要
- AI 图片消息：左对齐，白色背景，显示图片缩略图 + 描述文字（深色）
"""

from pathlib import Path
from PyQt5.QtWidgets import QWidget, QLabel, QHBoxLayout, QVBoxLayout, QSizePolicy
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QPixmap, QMovie

from utils.settings import get_settings


class MessageBubble(QWidget):
    def __init__(self, text: str, is_user: bool, parent=None):
        super().__init__(parent)
        self.is_user = is_user
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._build_ui(text)

    def _build_ui(self, text: str):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 4, 16, 4)
        outer.setSpacing(0)

        # 用容器包裹 label，容器控制最大宽度，label 在容器内自由伸展
        bubble = QWidget()
        bubble.setAttribute(Qt.WA_StyledBackground, True)
        bubble.setMaximumWidth(520)
        bubble.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)

        inner = QVBoxLayout(bubble)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)

        label = QLabel(text)
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        # 从全局设置读取字体大小
        settings = get_settings()
        font_size = settings.font_size
        label.setFont(QFont("Microsoft YaHei UI", font_size))

        inner.addWidget(label)

        if self.is_user:
            bubble.setStyleSheet("""
                QWidget {
                    background-color: #2D2D3F;
                    border-radius: 14px;
                    border: 1px solid #3D3D5A;
                }
                QLabel {
                    color: #E0E0E0;
                    padding: 10px 16px;
                    background: transparent;
                }
            """)
            outer.addStretch(1)
            outer.addWidget(bubble)
        else:
            bubble.setStyleSheet("""
                QWidget {
                    background-color: #2D2D3F;
                    border-radius: 14px;
                    border: 1px solid #3D3D5A;
                }
                QLabel {
                    color: #E0E0E0;
                    padding: 10px 16px;
                    background: transparent;
                }
            """)
            outer.addWidget(bubble)
            outer.addStretch(1)


class ImageMessageBubble(QWidget):
    """用于显示图片消息的气泡。
    支持 sender 参数：
        - "user": 右侧，紫蓝色背景，白色文字
        - "ai":   左侧，白色背景，深色文字
    支持展开/收起完整描述文本。
    """
    def __init__(self, image_path: str, ocr_text: str = "", full_text: str = "", 
                 sender: str = "user", parent=None):
        super().__init__(parent)
        self._image_path = image_path
        self._full_text = full_text if full_text else ocr_text
        self._expanded = False
        self._sender = sender  # "user" 或 "ai"
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._build_ui()

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 4, 16, 4)
        outer.setSpacing(0)

        bubble = QWidget()
        bubble.setAttribute(Qt.WA_StyledBackground, True)
        bubble.setMaximumWidth(320)
        bubble.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)

        inner = QVBoxLayout(bubble)
        inner.setContentsMargins(10, 8, 10, 8)
        inner.setSpacing(6)
        inner.setObjectName("image_bubble_inner")

        # 图片缩略图（GIF 动图用 QMovie，静态图用 QPixmap）
        is_gif = Path(self._image_path).suffix.lower() == ".gif"
        if is_gif:
            # 用 QPixmap 读第一帧获取原始尺寸，用于保持宽高比缩放
            probe = QPixmap(self._image_path)
            movie = QMovie(self._image_path)
            if not probe.isNull():
                target = probe.size().scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                movie.setScaledSize(target)
            img_label = QLabel()
            img_label.setMovie(movie)
            img_label.setAlignment(Qt.AlignCenter)
            movie.start()
            inner.addWidget(img_label)
        else:
            pixmap = QPixmap(self._image_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                img_label = QLabel()
                img_label.setPixmap(scaled)
                img_label.setAlignment(Qt.AlignCenter)
                inner.addWidget(img_label)

        # 描述文本区域
        if self._full_text:
            summary = self._full_text[:100] + "..." if len(self._full_text) > 100 else self._full_text
            self._text_label = QLabel(summary)
            self._text_label.setWordWrap(True)
            self._text_label.setFont(QFont("Microsoft YaHei UI", 9))
            
            # 根据发送者设置文字颜色
            if self._sender == "user":
                self._text_label.setStyleSheet("background: transparent; padding: 2px 0;")
            else:
                self._text_label.setStyleSheet("background: transparent; padding: 2px 0;")
            
            inner.addWidget(self._text_label)

            # 展开/收起按钮（仅当描述超过100字时显示）
            if len(self._full_text) > 100:
                # 按钮文字颜色也根据发送者调整
                if self._sender == "user":
                    btn_color = "#FFD966"
                else:
                    btn_color = "#6C7BFF"
                self._toggle_btn = QLabel(f"<a href='#' style='color:{btn_color}; text-decoration:none;'>展开 ▾</a>")
                self._toggle_btn.setFont(QFont("Microsoft YaHei UI", 8))
                self._toggle_btn.setStyleSheet("background: transparent;")
                self._toggle_btn.setCursor(Qt.PointingHandCursor)
                self._toggle_btn.linkActivated.connect(self._on_toggle)
                inner.addWidget(self._toggle_btn)
            else:
                self._toggle_btn = None
        else:
            # 没有描述文本时，不显示占位文字（表情包不需要分析）
            self._text_label = None
            self._toggle_btn = None

        # 根据发送者设置气泡样式
        if self._sender == "user":
            bubble.setStyleSheet("""
                QWidget {
                    background-color: #1ABC9C;
                    border-radius: 14px;
                }
                QLabel {
                    color: #FFFFFF;
                    background: transparent;
                }
            """)
            outer.addStretch(1)
            outer.addWidget(bubble)
        else:
            bubble.setStyleSheet("""
                QWidget {
                    background-color: #2D2D3F;
                    border-radius: 14px;
                    border: 1px solid #3D3D5A;
                }
                QLabel {
                    color: #E0E0E0;
                    background: transparent;
                }
            """)
            outer.addWidget(bubble)
            outer.addStretch(1)

    def _on_toggle(self):
        self._expanded = not self._expanded
        if self._expanded:
            self._text_label.setText(self._full_text)
            if self._toggle_btn:
                btn_color = "#FFD966" if self._sender == "user" else "#6C7BFF"
                self._toggle_btn.setText(f"<a href='#' style='color:{btn_color}; text-decoration:none;'>收起 ▴</a>")
        else:
            summary = self._full_text[:100] + "..." if len(self._full_text) > 100 else self._full_text
            self._text_label.setText(summary)
            if self._toggle_btn:
                btn_color = "#FFD966" if self._sender == "user" else "#6C7BFF"
                self._toggle_btn.setText(f"<a href='#' style='color:{btn_color}; text-decoration:none;'>展开 ▾</a>")

    def update_text(self, full_text: str):
        """异步更新完整描述（分析完成后调用）。"""
        self._full_text = full_text
        summary = full_text[:100] + "..." if len(full_text) > 100 else full_text
        if self._text_label:
            self._text_label.setText(summary)
        if len(full_text) > 100 and self._toggle_btn is None:
            btn_color = "#FFD966" if self._sender == "user" else "#6C7BFF"
            self._toggle_btn = QLabel(f"<a href='#' style='color:{btn_color}; text-decoration:none;'>展开 ▾</a>")
            self._toggle_btn.setFont(QFont("Microsoft YaHei UI", 8))
            self._toggle_btn.setStyleSheet("background: transparent;")
            self._toggle_btn.setCursor(Qt.PointingHandCursor)
            self._toggle_btn.linkActivated.connect(self._on_toggle)
            # 找到 inner layout 并添加按钮
            bubble = self.layout().itemAt(0 if self._sender == "ai" else 1).widget()
            if bubble:
                bubble.layout().addWidget(self._toggle_btn)