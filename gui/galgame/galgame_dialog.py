"""
GalgameDialog：莲心 Galgame 模式 — 对话窗口
半透明圆角对话框，附着在立绘旁边，
包含对话气泡、逐字显示、输入框。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QPushButton, QSizeGrip
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QEvent
from PyQt5.QtGui import (
    QFont, QPainter, QPainterPath, QColor, QKeyEvent
)


class GalgameDialog(QWidget):
    """Galgame 风格对话窗口，附着在立绘窗口旁。"""

    # 用户发送消息时发射（文本内容）
    message_submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._name = "莲心"
        self._full_text = ""
        self._current_index = 0
        self._is_typing = False

        self._init_window()
        self._init_ui()
        self._init_typing_timer()

    def _init_window(self):
        """窗口基础设置。"""
        self.setWindowTitle("莲心 - 对话")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowOpacity(0.92)
        self.resize(360, 300)

    def _init_ui(self):
        """创建 UI 组件。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 8)
        layout.setSpacing(4)

        # ── 角色名标签 ──
        self._name_label = QLabel(self._name)
        self._name_label.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        self._name_label.setStyleSheet("color: #5060DD; background: transparent;")
        layout.addWidget(self._name_label)

        # ── 回复文本区（只读，可滚动） ──
        self._reply_area = QTextEdit()
        self._reply_area.setReadOnly(True)
        self._reply_area.setFont(QFont("Microsoft YaHei UI", 10))
        self._reply_area.setStyleSheet("""
            QTextEdit {
                background: transparent;
                border: none;
                color: #333;
                padding: 2px 0;
            }
            QScrollBar:vertical {
                width: 4px;
                background: transparent;
            }
            QScrollBar::handle:vertical {
                background: rgba(136,136,136,0.4);
                border-radius: 2px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        self._reply_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        layout.addWidget(self._reply_area, stretch=1)

        # ── 输入框 ──
        self._input_edit = QTextEdit()
        self._input_edit.setFont(QFont("Microsoft YaHei UI", 10))
        self._input_edit.setPlaceholderText("说点什么吧（Enter发送 Shift+Enter换行）")
        self._input_edit.setFixedHeight(52)
        self._input_edit.setStyleSheet("""
            QTextEdit {
                background: rgba(255,255,255,200);
                border: 1px solid #d0d0e8;
                border-radius: 8px;
                padding: 6px 10px;
                color: #333;
            }
            QTextEdit:focus {
                border-color: #6C7BFF;
            }
        """)
        self._input_edit.verticalScrollBar().setVisible(False)
        # 事件过滤器：捕获输入框的回车键
        self._input_edit.installEventFilter(self)
        layout.addWidget(self._input_edit)

        # ── 发送按钮 ──
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._send_btn = QPushButton("发送")
        self._send_btn.setFont(QFont("Microsoft YaHei UI", 9))
        self._send_btn.setFixedSize(60, 28)
        self._send_btn.setCursor(Qt.PointingHandCursor)
        self._send_btn.setStyleSheet("""
            QPushButton {
                background: #6C7BFF;
                color: white;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover  { background: #5A6AEE; }
            QPushButton:pressed{ background: #4A5ADE; }
        """)
        self._send_btn.clicked.connect(self._on_send)
        btn_layout.addWidget(self._send_btn)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def _init_typing_timer(self):
        """逐字显示定时器。"""
        self._typing_timer = QTimer(self)
        self._typing_timer.timeout.connect(self._update_typing)

    def set_name(self, name: str):
        """设置角色名。"""
        self._name = name
        self._name_label.setText(name)

    def show_reply(self, text: str):
        """逐字显示 AI 回复。"""
        self._full_text = text
        self._current_index = 0
        self._is_typing = True
        self._reply_area.setHtml("")
        # 滚动到底部
        scrollbar = self._reply_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self._typing_timer.start(40)

    def clear_reply(self):
        """清空回复显示区。"""
        self._typing_timer.stop()
        self._reply_area.setHtml("")

    def show_thinking(self):
        """显示思考中。"""
        self.clear_reply()
        self._reply_area.setHtml("（思考中…）")

    def _update_typing(self):
        """逐字显示更新。"""
        if self._current_index < len(self._full_text):
            text = self._full_text[:self._current_index + 1]
            # 用 html 保留换行
            html = text.replace("\n", "<br>")
            self._reply_area.setHtml(html)
            self._current_index += 1
            # 逐字时自动滚到底
            scrollbar = self._reply_area.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        else:
            self._typing_timer.stop()
            self._is_typing = False

    def _on_send(self):
        """发送按钮点击。"""
        text = self._input_edit.toPlainText().strip()
        if text:
            self._input_edit.clear()
            self.show_thinking()
            self.message_submitted.emit(text)

    # ── 事件过滤器：捕获输入框回车键 ──
    def eventFilter(self, obj, event):
        if obj == self._input_edit and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Return and not (event.modifiers() & Qt.ShiftModifier):
                self._on_send()
                return True
        return super().eventFilter(obj, event)

    # ── 键盘事件 ──
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Return and not (event.modifiers() & Qt.ShiftModifier):
            self._on_send()
            event.accept()
        else:
            super().keyPressEvent(event)

    # ── 窗口大小调整手柄 ──
    def _init_resize_grip(self):
        self._size_grip = QSizeGrip(self)
        self._size_grip.resize(16, 16)
        self._size_grip.move(self.width() - self._size_grip.width(),
                              self.height() - self._size_grip.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_size_grip'):
            self._size_grip.move(self.width() - self._size_grip.width(),
                                  self.height() - self._size_grip.height())

    # ── 自定义圆角绘制 ──
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        path = QPainterPath()
        r = self.rect().adjusted(6, 6, -6, -6)
        path.addRoundedRect(float(r.x()), float(r.y()), float(r.width()), float(r.height()), 12, 12)
        painter.fillPath(path, QColor(255, 255, 255, 230))

        painter.setPen(QColor(0, 0, 0, 30))
        for i in range(3):
            shrink = 3 - i
            sr = r.adjusted(-shrink, -shrink, shrink, shrink)
            sp = QPainterPath()
            sp.addRoundedRect(float(sr.x()), float(sr.y()), float(sr.width()), float(sr.height()), 12, 12)
            painter.setPen(QColor(0, 0, 0, 10 - i * 3))
            painter.drawPath(sp)

    # ── 鼠标拖拽 ──
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and hasattr(self, '_drag_pos'):
            self.move(event.globalPos() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and hasattr(self, '_drag_pos'):
            del self._drag_pos
            event.accept()
